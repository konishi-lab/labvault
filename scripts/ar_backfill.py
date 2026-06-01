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
- `gcloud artifacts repositories get-iam-policy` で AR repo の reader 一覧を取得
- 漏れている email を表示
- `--apply` を付けたら `gcloud artifacts repositories add-iam-policy-binding`
  を 1 件ずつ呼んで reader を付与 (冪等)

gcloud 経由にしているのは、user-credential ADC で REST 直叩きすると
consumer project の解決が OAuth flow と噛み合わず 404 になるため。
gcloud は内部で正しい認証フローを扱ってくれる。実行環境に gcloud が
PATH 上にある前提。

使い方:

    # dry-run (デフォルト): 漏れている人を表示するだけ
    python scripts/ar_backfill.py

    # 実行 (本番への書き込みあり)
    python scripts/ar_backfill.py --apply

    # 特定 team のメンバーだけ対象にする
    python scripts/ar_backfill.py --team konishi-lab

設定の読み込み:
    `.env` (カレントディレクトリ) / `~/.labvault/credentials` /
    `~/.labvault/config.toml` から labvault SDK の Settings 経由で取得する。
    環境変数で上書きも可能 (Settings の優先順位どおり)。

    LABVAULT_GCP_PROJECT       (必須)
    LABVAULT_FIRESTORE_DATABASE (省略時 "(default)")
    LABVAULT_AR_REPO           (必須。例: projects/.../repositories/labvault-pypi)
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any


def _load_settings_into_env() -> None:
    """labvault SDK の Settings 経由で .env / credentials / config.toml を読み、
    backend の artifact_registry が見る os.environ に橋渡しする。

    既に環境変数が立っていれば上書きしない (env 優先)。
    """
    from labvault.core.config import Settings

    s = Settings()
    pairs = {
        "LABVAULT_GCP_PROJECT": s.gcp_project,
        "LABVAULT_FIRESTORE_DATABASE": s.firestore_database,
        "LABVAULT_AR_REPO": s.ar_repo,
    }
    for key, value in pairs.items():
        if value and not os.environ.get(key):
            os.environ[key] = value


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


def _parse_repo_path(repo: str) -> tuple[str, str, str]:
    """``projects/<p>/locations/<l>/repositories/<r>`` を (project, location, name)
    に分解する。"""
    parts = repo.split("/")
    if (
        len(parts) != 6
        or parts[0] != "projects"
        or parts[2] != "locations"
        or parts[4] != "repositories"
    ):
        msg = (
            "LABVAULT_AR_REPO must look like "
            "projects/<p>/locations/<l>/repositories/<r>"
        )
        raise ValueError(msg)
    return parts[1], parts[3], parts[5]


def _gcloud_args_for_repo() -> tuple[list[str], str] | None:
    """LABVAULT_AR_REPO を gcloud 共通フラグに変換する。

    Returns (共通フラグ, repo_name) or None (env 未設定)。
    """
    repo = (os.environ.get("LABVAULT_AR_REPO") or "").strip()
    if not repo:
        print(
            "LABVAULT_AR_REPO not set; cannot manage AR IAM policy",
            file=sys.stderr,
        )
        return None
    try:
        project, location, name = _parse_repo_path(repo)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return None
    return (
        [f"--project={project}", f"--location={location}"],
        name,
    )


def _ar_reader_members() -> set[str] | None:
    """AR repo の現在の reader member 一覧を gcloud 経由で取得する。

    REST 直叩きだと user-credential ADC で 404 になる (consumer project の
    解決が OAuth flow と噛み合わない)。gcloud は内部で正しい認証 flow を
    扱うので、ローカル運用ツールとしてはこれが最も確実。
    """
    import json as _json
    import subprocess

    READER_ROLE = "roles/artifactregistry.reader"

    parsed = _gcloud_args_for_repo()
    if parsed is None:
        return None
    common, name = parsed
    try:
        out = subprocess.check_output(
            [
                "gcloud",
                "artifacts",
                "repositories",
                "get-iam-policy",
                name,
                *common,
                "--format=json",
            ],
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print("gcloud CLI not found in PATH", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(
            "gcloud get-iam-policy failed:\n"
            + (e.stderr.decode(errors="replace") if e.stderr else ""),
            file=sys.stderr,
        )
        return None

    policy = _json.loads(out)
    members: set[str] = set()
    for binding in policy.get("bindings") or []:
        if binding.get("role") == READER_ROLE:
            members.update(binding.get("members") or [])
    return members


def _grant_reader_gcloud(email: str) -> bool:
    """gcloud で reader role binding を追加する (冪等; gcloud がメンバー重複を
    検出して no-op で済ませる)。"""
    import subprocess

    parsed = _gcloud_args_for_repo()
    if parsed is None:
        return False
    common, name = parsed
    try:
        subprocess.check_call(
            [
                "gcloud",
                "artifacts",
                "repositories",
                "add-iam-policy-binding",
                name,
                *common,
                f"--member=user:{email}",
                "--role=roles/artifactregistry.reader",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False
    return True


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

    _load_settings_into_env()
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

    print()
    print("Applying grants...")
    granted = 0
    failed = 0
    for u in missing:
        ok = _grant_reader_gcloud(u["email"])
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
