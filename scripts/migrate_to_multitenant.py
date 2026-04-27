"""マルチテナント化マイグレーション (Phase 1)。

- teams/{team_id} ドキュメントを作成 (konishi-lab を seed)
- 既存 allowed_users に teams field と default_team を追加 (additive, 既存 role は残す)
- teams/{team}/records 配下のレコード team 整合性を audit

冪等。--dry-run で書き込みなしで影響範囲を表示。

使い方:
    python scripts/migrate_to_multitenant.py --dry-run
    python scripts/migrate_to_multitenant.py            # 実行
    python scripts/migrate_to_multitenant.py --team konishi-lab \\
        --group-folder large/24UTARIM004 --display-name "Konishi Lab"
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Any

from google.cloud import firestore


def _client() -> firestore.Client:
    project = os.environ.get("LABVAULT_GCP_PROJECT")
    database = os.environ.get("LABVAULT_FIRESTORE_DATABASE", "(default)")
    if not project:
        print("LABVAULT_GCP_PROJECT not set", file=sys.stderr)
        sys.exit(1)
    return firestore.Client(project=project, database=database)


def ensure_team(
    db: firestore.Client,
    team_id: str,
    display_name: str,
    group_folder: str,
    *,
    dry_run: bool,
) -> None:
    ref = db.collection("teams").document(team_id)
    snap = ref.get()
    if snap.exists:
        data = snap.to_dict() or {}
        missing = []
        if not data.get("name"):
            missing.append("name")
        if not data.get("nextcloud_group_folder"):
            missing.append("nextcloud_group_folder")
        if not missing:
            print(f"[teams] {team_id}: already exists, skip")
            return
        patch: dict[str, Any] = {}
        if "name" in missing:
            patch["name"] = display_name
        if "nextcloud_group_folder" in missing:
            patch["nextcloud_group_folder"] = group_folder
        print(f"[teams] {team_id}: patch missing fields {missing}")
        if not dry_run:
            ref.set(patch, merge=True)
        return

    payload = {
        "name": display_name,
        "nextcloud_group_folder": group_folder,
        "created_at": dt.datetime.now(dt.UTC),
        "created_by": "system",
    }
    print(f"[teams] {team_id}: CREATE name={display_name!r} folder={group_folder!r}")
    if not dry_run:
        ref.set(payload)


def migrate_allowed_users(
    db: firestore.Client,
    default_team_id: str,
    *,
    dry_run: bool,
) -> None:
    docs = list(db.collection("allowed_users").stream())
    if not docs:
        print("[allowed_users] no documents found")
        return

    updated = 0
    skipped = 0
    for doc in docs:
        data = doc.to_dict() or {}
        email = data.get("email") or doc.id

        existing_teams = data.get("teams")
        existing_default = data.get("default_team")
        if (
            isinstance(existing_teams, list)
            and existing_teams
            and existing_default
        ):
            skipped += 1
            continue

        role = data.get("role", "member")
        patch: dict[str, Any] = {}

        if not isinstance(existing_teams, list) or not existing_teams:
            patch["teams"] = [{"team_id": default_team_id, "role": role}]

        if not existing_default:
            patch["default_team"] = default_team_id

        print(
            f"[allowed_users] {email}: add "
            + ", ".join(f"{k}={v!r}" for k, v in patch.items())
        )
        if not dry_run:
            doc.reference.set(patch, merge=True)
        updated += 1

    print(f"[allowed_users] updated={updated} skipped={skipped} total={len(docs)}")


def audit_records(
    db: firestore.Client,
    team_id: str,
) -> None:
    ref = db.collection("teams").document(team_id).collection("records")
    total = 0
    mismatched: list[str] = []
    missing: list[str] = []
    for doc in ref.stream():
        total += 1
        data = doc.to_dict() or {}
        team = data.get("team")
        if team is None or team == "":
            missing.append(doc.id)
        elif team != team_id:
            mismatched.append(f"{doc.id} (team={team!r})")
    print(f"[records audit] team={team_id} total={total}")
    if missing:
        print(f"  missing team field: {len(missing)} records")
        for rid in missing[:10]:
            print(f"    - {rid}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")
    if mismatched:
        print(f"  mismatched team field: {len(mismatched)} records")
        for entry in mismatched[:10]:
            print(f"    - {entry}")
        if len(mismatched) > 10:
            print(f"    ... and {len(mismatched) - 10} more")
    if not missing and not mismatched:
        print("  all records OK")


def backfill_record_team(
    db: firestore.Client,
    team_id: str,
    *,
    dry_run: bool,
) -> None:
    ref = db.collection("teams").document(team_id).collection("records")
    fixed = 0
    for doc in ref.stream():
        data = doc.to_dict() or {}
        team = data.get("team")
        if team == team_id:
            continue
        print(f"[records backfill] {doc.id}: team {team!r} -> {team_id!r}")
        if not dry_run:
            doc.reference.set({"team": team_id}, merge=True)
        fixed += 1
    print(f"[records backfill] fixed={fixed}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", default="konishi-lab", help="default team id")
    parser.add_argument("--display-name", default="Konishi Lab")
    parser.add_argument("--group-folder", default="large/24UTARIM004")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--backfill-records",
        action="store_true",
        help="audit で見つかった record の team を強制的に backfill する",
    )
    args = parser.parse_args()

    db = _client()
    project = db.project
    database = db._database  # internal but stable
    print(f"# project={project} database={database} dry_run={args.dry_run}")
    print()

    ensure_team(
        db,
        team_id=args.team,
        display_name=args.display_name,
        group_folder=args.group_folder,
        dry_run=args.dry_run,
    )
    print()

    migrate_allowed_users(db, default_team_id=args.team, dry_run=args.dry_run)
    print()

    audit_records(db, team_id=args.team)
    print()

    if args.backfill_records:
        backfill_record_team(db, team_id=args.team, dry_run=args.dry_run)
        print()

    if args.dry_run:
        print("# dry-run: no writes performed")
    else:
        print("# done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
