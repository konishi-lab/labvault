"""MDG インポート失敗分を再インポートするスクリプト。

check_mdg_status.py で特定された no_folder + incomplete を対象に再実行。

使い方:
    python scripts/reimport_mdg.py --session kkonishi
    python scripts/reimport_mdg.py --session kkonishi --dry-run
"""

from __future__ import annotations

import argparse
import time

from brokersystem import Broker
from nc_py_api import Nextcloud

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from labvault.core.config import Settings
from import_mdg import (
    MDG_BROKER_URL,
    MDG_TOKEN,
    import_trial,
)

# check_mdg_status.py で特定された再インポート対象
NO_FOLDER = [
    689, 691, 900,
    1048, 1049, 1050, 1051, 1055, 1056, 1057, 1058, 1059, 1060,
    1080, 1081, 1082, 1083, 1084, 1085, 1088, 1089, 1090, 1091,
    1092, 1093, 1094, 1095, 1096, 1097, 1098,
    1137, 1138, 1139, 1140, 1141, 1142, 1143, 1146, 1147, 1148,
    1149, 1150,
]

# 画像 0 枚 (parameters.json のみ存在) — 削除して再取得
INCOMPLETE = [1634, 1635, 1637]

TARGET_IDS = sorted(set(NO_FOLDER + INCOMPLETE))


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-import failed MDG trials")
    parser.add_argument("--session", required=True, help="セッション名")
    parser.add_argument("--dry-run", action="store_true", help="実行せず対象を表示")
    args = parser.parse_args()

    print(f"Session: {args.session}")
    print(f"Targets: {len(TARGET_IDS)} trials")
    print(f"  No folder: {len(NO_FOLDER)}")
    print(f"  Incomplete: {len(INCOMPLETE)}")
    print()

    if args.dry_run:
        for loc_id in TARGET_IDS:
            tag = "incomplete" if loc_id in INCOMPLETE else "no_folder"
            print(f"  [{loc_id:04d}] {tag}")
        return

    settings = Settings()
    broker = Broker(broker_url=MDG_BROKER_URL, auth=MDG_TOKEN)
    nc = Nextcloud(
        nextcloud_url=settings.nextcloud_url,
        nc_auth_user=settings.nextcloud_user,
        nc_auth_pass=settings.nextcloud_password,
    )

    base_path = f"large/24UTARIM004/labvault/konishi-lab/mdg/{args.session}"

    # incomplete のフォルダは削除してから再取得
    for loc_id in INCOMPLETE:
        folder = f"{base_path}/{loc_id:04d}"
        try:
            # parameters.json を削除（import_trial のスキップ判定を回避）
            nc.files.delete(f"{folder}/parameters.json")
            print(f"  [{loc_id:04d}] Cleared incomplete folder")
        except Exception:
            pass

    imported = 0
    failed = 0
    start_time = time.time()

    for idx, loc_id in enumerate(TARGET_IDS):
        try:
            stats = import_trial(broker, nc, args.session, loc_id, base_path)

            if stats.get("skipped"):
                print(f"  [{loc_id:04d}] Skipped (already exists)")
                continue

            imported += 1
            err_str = f" errors: {stats['errors']}" if stats.get("errors") else ""
            print(
                f"  [{loc_id:04d}] "
                f"images={stats['images']} plux={'Y' if stats['plux'] else 'N'}"
                f"{err_str}"
                f"  ({idx + 1}/{len(TARGET_IDS)})"
            )

        except Exception as e:
            print(f"  [{loc_id:04d}] FAILED: {e}")
            failed += 1

        time.sleep(1)

    elapsed = time.time() - start_time
    print()
    print(f"Done in {elapsed / 60:.1f} min")
    print(f"  Imported: {imported}")
    print(f"  Failed:   {failed}")


if __name__ == "__main__":
    main()
