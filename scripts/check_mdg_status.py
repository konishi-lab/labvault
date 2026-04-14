"""MDG インポート状況を確認するスクリプト。

Nextcloud 上の各 location_id フォルダを走査して、
missing / imported / error / plux 状況を一覧表示する。

使い方:
    python scripts/check_mdg_status.py --session kkonishi
    python scripts/check_mdg_status.py --session kkonishi --details
"""

from __future__ import annotations

import argparse
import json

from nc_py_api import Nextcloud

from labvault.core.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Check MDG import status")
    parser.add_argument("--session", required=True, help="セッション名")
    parser.add_argument("--details", action="store_true", help="詳細表示")
    args = parser.parse_args()

    settings = Settings()
    nc = Nextcloud(
        nextcloud_url=settings.nextcloud_url,
        nc_auth_user=settings.nextcloud_user,
        nc_auth_pass=settings.nextcloud_password,
    )

    base_path = f"large/24UTARIM004/labvault/konishi-lab/mdg/{args.session}"

    # フォルダ一覧取得
    try:
        entries = nc.files.listdir(base_path)
    except Exception as e:
        print(f"Error listing {base_path}: {e}")
        return

    folders = sorted(
        [e for e in entries if e.is_dir],
        key=lambda e: e.name,
    )

    print(f"Session: {args.session}")
    print(f"Path: {base_path}")
    print(f"Total folders: {len(folders)}")
    print()

    missing: list[str] = []
    imported: list[str] = []
    no_plux: list[str] = []
    no_folder: list[str] = []
    incomplete: list[tuple[str, int]] = []  # (loc_id, image_count)

    for folder in folders:
        loc_id = folder.name

        # parameters.json を確認
        try:
            params_file = nc.files.download(f"{base_path}/{loc_id}/parameters.json")
            params = json.loads(params_file.decode("utf-8"))
        except Exception:
            no_folder.append(loc_id)
            continue

        # missing チェック
        if params.get("status") == "missing":
            missing.append(loc_id)
            continue

        # ファイル一覧
        try:
            files = nc.files.listdir(f"{base_path}/{loc_id}")
            file_names = {f.name for f in files if not f.is_dir}
        except Exception:
            no_folder.append(loc_id)
            continue

        # 画像カウント
        image_count = sum(1 for name in file_names if name.endswith(".png"))
        has_plux = "measure3d_plux.zip" in file_names

        if not has_plux:
            no_plux.append(loc_id)

        if image_count < 9:
            incomplete.append((loc_id, image_count))

        imported.append(loc_id)

    # 0000〜最大の連番で存在しないフォルダを検出
    if folders:
        max_id = max(int(f.name) for f in folders)
        existing = {f.name for f in folders}
        for i in range(max_id + 1):
            loc_str = f"{i:04d}"
            if loc_str not in existing:
                no_folder.append(loc_str)
        no_folder.sort()

    # サマリ
    print(f"  Imported:   {len(imported)}")
    print(f"  Missing:    {len(missing)}")
    print(f"  No PLUX:    {len(no_plux)}")
    print(f"  Incomplete: {len(incomplete)} (images < 9)")
    print(f"  No folder:  {len(no_folder)} (import failed or not attempted)")

    if args.details:
        if missing:
            print(f"\n--- Missing ({len(missing)}) ---")
            for loc_id in missing:
                print(f"  {loc_id}")

        if no_plux:
            print(f"\n--- No PLUX ({len(no_plux)}) ---")
            for loc_id in no_plux:
                print(f"  {loc_id}")

        if incomplete:
            print(f"\n--- Incomplete images ({len(incomplete)}) ---")
            for loc_id, count in incomplete:
                print(f"  {loc_id}: {count}/9 images")

        if no_folder:
            print(f"\n--- No folder ({len(no_folder)}) ---")
            for loc_id in no_folder:
                print(f"  {loc_id}")


if __name__ == "__main__":
    main()
