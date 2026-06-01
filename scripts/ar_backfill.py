#!/usr/bin/env python
"""Artifact Registry reader 権限の漏れを backfill する。

背景
----
labvault SDK は private Artifact Registry (`labvault-pypi`) で配布されて
おり、approve / team 追加 / reactivate のタイミングで対象 email に
AR reader (`roles/artifactregistry.reader`) を自動付与する
(`platform/backend/app/artifact_registry.py`)。

ただし以下のケースで AR reader が付与されていない可能性がある:

1. AR 連動機能が追加される前に approve されたユーザー
2. approve 当時に `LABVAULT_AR_REPO` 環境変数が未設定だった
3. approve 時に AR API が一時的に落ちて grant が失敗した (静かに `False`
   で返るため admin が気付かない)

このスクリプトは:

- `allowed_users` を走査して active なユーザーをリストアップ
- AR repo の IAM policy を 1 回取得して reader binding の members 集合を作る
- 漏れている email を表示
- `--apply` を付けたら漏れている email に `grant_reader` を呼ぶ (冪等)

使い方:

    # dry-run (デフォルト): 漏れている人を表示するだけ
    python scripts/ar_backfill.py

    # 実行 (本番への書き込みあり)
    python scripts/ar_backfill.py --apply

    # 特定 team のメンバーだけ対象にする
    python scripts/ar_backfill.py --team konishi-lab

環境変数:
    LABVAULT_GCP_PROJECT       (必須)
    LABVAULT_FIRESTORE_DATABASE (省略時 "(default)")
    LABVAULT_AR_REPO           (必須。例: projects/.../repositories/labvault-pypi)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# platform/backend/app の artifact_registry を import するため sys.path に追加。
# 既存スクリプト (scripts/migrate_to_multitenant.py) と同じ relative 関係。
_BACKEND = Path(__file__).resolve().parents[1] / "platform" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _firestore_client() -> Any:
    from google.cloud import firestore

    project = os.environ.get("LABVAULT_GCP_PROJECT")
    database = os.environ.get("LABVAULT_FIRESTORE_DATABASE", "(default)")
    if not project:
        print("LABVAULT_GCP_PROJECT not set", file=sys.stderr)
        sys.exit(1)
    return firestore.Client(project=project, database=database)


def _list_active_users(db: Any, team: str | None) -> list[dict[str, Any]]:
    """allowed_users の active なユーザー一覧を返す。

    team が指定されたら、teams[].team_id にその team を含むユーザーのみ。
    """
    users: list[dict[str, Any]] = []
    for snap in db.collection("allowed_users").stream():
        d = snap.to_dict() or {}
        if not d.get("active", True):
            continue
        email = d.get("email") or snap.id
        if not email:
            continue
        if team is not None:
            user_team_ids = {
                t.get("team_id") for t in (d.get("teams") or []) if isinstance(t, dict)
            }
            if team not in user_team_ids:
                continue
        users.append({"email": email, "display_name": d.get("display_name", "")})
    users.sort(key=lambda u: u["email"])
    return users


def _ar_reader_members() -> set[str] | None:
    """AR repo の現在の reader member 一覧 (例: ``user:foo@bar``)。

    取得に失敗したら None を返す (LABVAULT_AR_REPO 未設定など)。
    """
    import google.auth
    import google.auth.transport.requests
    import httpx
    from app.artifact_registry import (  # type: ignore[import-not-found]
        AR_SCOPE,
        READER_ROLE,
        _api_url,
        _repo_resource,
    )

    repo = _repo_resource()
    if not repo:
        print(
            "LABVAULT_AR_REPO not set; cannot read AR IAM policy",
            file=sys.stderr,
        )
        return None

    creds, _ = google.auth.default(scopes=[AR_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    resp = httpx.post(
        _api_url(repo, "getIamPolicy"),
        headers={
            "Authorization": f"Bearer {creds.token}",
            "Content-Type": "application/json",
        },
        json={},
        timeout=10.0,
    )
    resp.raise_for_status()
    policy = resp.json()
    members: set[str] = set()
    for binding in policy.get("bindings") or []:
        if binding.get("role") == READER_ROLE:
            members.update(binding.get("members") or [])
    return members


def classify_missing(
    users: list[dict[str, Any]], reader_members: set[str]
) -> list[dict[str, Any]]:
    """user list と AR reader members から「漏れているユーザー」を返す。

    純粋関数。テストで AR / Firestore を実呼びせずに検証できる。
    """
    out: list[dict[str, Any]] = []
    for u in users:
        if f"user:{u['email']}" not in reader_members:
            out.append(u)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--team",
        help="対象 team を絞る (例: konishi-lab)。省略で全 team。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実行モード。指定しないと dry-run。",
    )
    args = parser.parse_args()

    db = _firestore_client()
    users = _list_active_users(db, args.team)
    print(
        f"Scanning {len(users)} active user(s)"
        + (f" in team={args.team}" if args.team else "")
    )

    reader_members = _ar_reader_members()
    if reader_members is None:
        return 1

    missing = classify_missing(users, reader_members)
    print()
    print(f"Found {len(missing)} user(s) missing AR reader:")
    for u in missing:
        print(f"  - {u['email']}  ({u.get('display_name') or '<no name>'})")
    if not missing:
        print("  (none)")
        return 0

    if not args.apply:
        print()
        print("dry-run のため書き込みは行いません。--apply で実行してください。")
        return 0

    from app.artifact_registry import grant_reader  # type: ignore[import-not-found]

    print()
    print("Applying grants...")
    granted = 0
    failed = 0
    for u in missing:
        ok = grant_reader(u["email"])
        if ok:
            granted += 1
            print(f"  [OK]   {u['email']}")
        else:
            failed += 1
            print(f"  [FAIL] {u['email']}")
    print()
    print(f"Done. granted={granted}, failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
