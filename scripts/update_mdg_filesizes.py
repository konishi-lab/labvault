"""MDG レコードの data_refs にファイルサイズを反映するスクリプト。

register_mdg_firestore.py で size_bytes=0 のまま登録された DataRef を
Nextcloud の実ファイルサイズで更新する。

使い方:
    python scripts/update_mdg_filesizes.py --parent 6HDKNS
    python scripts/update_mdg_filesizes.py --parent 6HDKNS --dry-run
"""

from __future__ import annotations

import argparse
import os

from nc_py_api import Nextcloud

from labvault import Lab
from labvault.core.config import Settings
from labvault.core.record import Record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update MDG data_refs with actual file sizes from Nextcloud"
    )
    parser.add_argument("--parent", required=True, help="親レコード ID")
    parser.add_argument("--dry-run", action="store_true", help="プレビューのみ")
    args = parser.parse_args()

    os.environ["LABVAULT_AUTO_SYNC"] = "false"

    settings = Settings()
    lab = Lab()
    nc = Nextcloud(
        nextcloud_url=settings.nextcloud_url,
        nc_auth_user=settings.nextcloud_user,
        nc_auth_pass=settings.nextcloud_password,
    )

    # 子レコード取得
    if hasattr(lab._metadata, "list_records"):
        rows = lab._metadata.list_records(lab._team, parent_id=args.parent, limit=5000)
        children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        children = [r for r in all_records if r.parent_id == args.parent]

    print(f"Parent: {args.parent}")
    print(f"Children: {len(children)}")
    print(f"Dry run: {args.dry_run}")
    print()

    updated = 0
    skipped = 0
    errors = 0

    for i, rec in enumerate(children):
        refs = rec._data_refs
        needs_update = any(r.size_bytes == 0 for r in refs)

        if not needs_update:
            skipped += 1
            continue

        # Nextcloud のフォルダからファイルサイズを一括取得
        nc_folder = None
        for r in refs:
            if r.nextcloud_path:
                nc_folder = "/".join(r.nextcloud_path.split("/")[:-1])
                break

        if not nc_folder:
            skipped += 1
            continue

        try:
            nc_files = nc.files.listdir(nc_folder)
            size_map = {f.name: f.info.size for f in nc_files if not f.is_dir}
        except Exception as e:
            print(f"  [{rec.id}] Error listing {nc_folder}: {e}")
            errors += 1
            continue

        changed = False
        for ref in refs:
            if ref.size_bytes == 0 and ref.name in size_map:
                new_size = size_map[ref.name]
                if new_size > 0:
                    if args.dry_run and not changed:
                        print(f"  [{rec.id}] {rec.title}")
                    if args.dry_run:
                        print(f"    {ref.name}: 0 -> {new_size}")
                    ref.size_bytes = new_size
                    # content_type も設定
                    if not ref.content_type:
                        if ref.name.endswith(".png"):
                            ref.content_type = "image/png"
                        elif ref.name.endswith(".json"):
                            ref.content_type = "application/json"
                        elif ref.name.endswith(".zip"):
                            ref.content_type = "application/zip"
                    changed = True

        if changed and not args.dry_run:
            rec._persist()
            updated += 1

        if changed and args.dry_run:
            updated += 1

        if (i + 1) % 200 == 0:
            print(f"  Progress: {i + 1}/{len(children)} (updated: {updated})")

    print()
    print(f"Done: updated={updated}, skipped={skipped}, errors={errors}")
    lab.close()


if __name__ == "__main__":
    main()
