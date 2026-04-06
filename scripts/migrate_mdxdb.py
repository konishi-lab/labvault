"""mdxdb → labvault マイグレーションスクリプト。

Nextcloud 上の mdxdb データを読み取り、labvault の Firestore に登録する。
ファイルは既に Nextcloud にあるため、メタデータ (DataRef) のパスを設定するだけ。

使い方:
    python scripts/migrate_mdxdb.py --dry-run   # プレビュー
    python scripts/migrate_mdxdb.py              # 実行
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from labvault import Lab
from labvault.core.config import Settings


def get_nc_client(settings: Settings) -> Any:
    """Nextcloud クライアントを取得する。"""
    from nc_py_api import Nextcloud

    return Nextcloud(
        nextcloud_url=settings.nextcloud_url,
        nc_auth_user=settings.nextcloud_user,
        nc_auth_pass=settings.nextcloud_password,
    )


def read_json(nc: Any, path: str) -> dict[str, Any] | None:
    """Nextcloud からJSONファイルを読み取る。"""
    try:
        data = nc.files.download(path)
        return json.loads(data)
    except Exception as e:
        print(f"  Warning: cannot read {path}: {e}")
        return None


def list_data_files(nc: Any, data_path: str) -> list[dict[str, Any]]:
    """_data/ ディレクトリ内のファイル一覧を取得する。"""
    try:
        nodes = nc.files.listdir(data_path)
        files = []
        for node in nodes:
            if not node.is_dir:
                files.append(
                    {
                        "name": node.name,
                        "path": node.user_path.lstrip("/"),
                        "size": getattr(node, "size", 0) or 0,
                    }
                )
        return files
    except Exception:
        return []


def list_sub_records(nc: Any, record_path: str) -> list[str]:
    """レコードディレクトリ内のサブレコード一覧を取得する。"""
    try:
        nodes = nc.files.listdir(record_path)
        subs = []
        for node in nodes:
            if node.is_dir and node.name not in ("_data", "_preview", "_analyses"):
                subs.append(node.name)
        return sorted(subs)
    except Exception:
        return []


def migrate_record(
    lab: Lab,
    nc: Any,
    record_path: str,
    record_id_mdxdb: str,
    parent_labvault_id: str | None,
    group_folder: str,
    dry_run: bool,
    stats: dict[str, int],
) -> str | None:
    """1つのレコードをマイグレーションする。"""
    meta_path = f"{record_path}/_record_meta.json"
    meta = read_json(nc, meta_path)

    title = record_id_mdxdb
    description = ""
    created_by = ""
    created_at_str = ""

    if meta:
        description = meta.get("description", "") or ""
        created_by = meta.get("created_by", "") or ""
        created_at_str = meta.get("created_at", "") or ""
        if description:
            title = f"{record_id_mdxdb}: {description}"

    # データファイル一覧
    data_path = f"{record_path}/_data"
    data_files = list_data_files(nc, data_path)

    if dry_run:
        print(f"  [DRY RUN] Would create: {title}")
        print(f"    mdxdb path: {record_path}")
        print(f"    files: {len(data_files)}")
        if parent_labvault_id:
            print(f"    parent: {parent_labvault_id}")
        stats["records"] += 1
        stats["files"] += len(data_files)
        return "DRY_RUN"

    # labvault レコード作成
    if parent_labvault_id:
        parent = lab.get(parent_labvault_id)
        rec = parent.sub(title)
    else:
        rec = lab.new(title, auto_log=False)

    # メタデータ設定
    if description:
        rec.note(f"mdxdb description: {description}")
    if created_by:
        rec.note(f"mdxdb created_by: {created_by}")
    if created_at_str:
        rec.note(f"mdxdb created_at: {created_at_str}")

    rec.tag("migrated-from-mdxdb")
    rec.conditions(mdxdb_id=record_id_mdxdb, mdxdb_path=record_path)

    # ファイル参照を登録 (ファイル自体は Nextcloud にあるのでコピー不要)
    from labvault.core.types import DataRef

    for f in data_files:
        # Nextcloud パスから labvault の SDK パスに変換
        nc_path = f["path"]
        # DataRef を直接追加
        rec._data_refs.append(
            DataRef(
                name=f["name"],
                nextcloud_path=nc_path,
                size_bytes=f["size"],
            )
        )

    rec._persist()
    rec.status = "success"

    stats["records"] += 1
    stats["files"] += len(data_files)
    print(f"  Created: [{rec.id}] {title} ({len(data_files)} files)")

    return rec.id


def main() -> None:
    parser = argparse.ArgumentParser(description="mdxdb → labvault migration")
    parser.add_argument("--dry-run", action="store_true", help="プレビューのみ")
    parser.add_argument(
        "--mdxdb-path",
        default="large/24UTARIM004/v1/mxdb",
        help="Nextcloud 上の mdxdb パス",
    )
    args = parser.parse_args()

    settings = Settings()
    print(f"Team: {settings.team}")
    print(f"Nextcloud: {settings.nextcloud_url}")
    print(f"mdxdb path: {args.mdxdb_path}")
    print(f"Dry run: {args.dry_run}")
    print()

    nc = get_nc_client(settings)

    if not args.dry_run:
        lab = Lab()
        print(f"Metadata backend: {type(lab._metadata).__name__}")
    else:
        lab = Lab()

    stats: dict[str, int] = {"records": 0, "files": 0}

    # ルートレコード一覧を取得
    root_path = args.mdxdb_path
    try:
        root_nodes = nc.files.listdir(root_path)
    except Exception as e:
        print(f"Error: cannot list {root_path}: {e}")
        sys.exit(1)

    root_records = [
        n.name
        for n in root_nodes
        if n.is_dir and n.name not in ("schemas", "_data", "_preview")
    ]
    print(f"Root records found: {len(root_records)}")
    print()

    for root_id in sorted(root_records):
        record_path = f"{root_path}/{root_id}"
        print(f"Processing: {root_id}")

        # ルートレコードをマイグレーション
        labvault_id = migrate_record(
            lab, nc, record_path, root_id, None,
            settings.nextcloud_group_folder, args.dry_run, stats,
        )

        if labvault_id is None:
            continue

        # サブレコードをマイグレーション
        sub_ids = list_sub_records(nc, record_path)
        if sub_ids:
            print(f"  Sub-records: {len(sub_ids)}")
            for sub_id in sub_ids:
                sub_path = f"{record_path}/{sub_id}"
                migrate_record(
                    lab, nc, sub_path, sub_id,
                    labvault_id if not args.dry_run else None,
                    settings.nextcloud_group_folder, args.dry_run, stats,
                )

        print()

    print("=" * 40)
    print(f"Total records: {stats['records']}")
    print(f"Total files:   {stats['files']}")
    if args.dry_run:
        print("\nDry run complete. Run without --dry-run to execute.")

    lab.close()


if __name__ == "__main__":
    main()
