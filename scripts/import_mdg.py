"""MDG carbide1 セッションデータを Nextcloud に取り込むスクリプト。

1件ずつ逐次処理。各トライアルの画像 + PLUX raw + parameters.json を保存。

使い方:
    python scripts/import_mdg.py --session kkonishi
    python scripts/import_mdg.py --session kkonishi --start 100  # 途中から再開
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import requests
from brokersystem import Broker
from nc_py_api import Nextcloud

from labvault.core.config import Settings

MDG_BROKER_URL = "https://mdg2.gigalixirapp.com"
MDG_TOKEN = "db1cfc13-d02d-40f1-8056-2d4e80c14380"
RESULT_AGENT = "b086434b-6ffc-4f81-aee2-13ac1d3a5c0a"
BATCH_AGENT = "fdc1c45c-7204-46ab-9e08-0b85c5c1e90c"

IMAGE_KEYS = [
    "take_image_before",
    "take_image_after",
    "take_image_comparison",
    "measure3d_before_plot",
    "measure3d_after_plot",
    "measure3d_comparison",
    "measure3d_stack_before",
    "measure3d_stack_after",
    "measure3d_stack_comparison",
]


def get_session_info(
    broker: Broker, session_name: str
) -> tuple[int, set[int]]:
    """セッションの総トライアル数と有効な location_id セットを返す。"""
    result = broker.ask(
        BATCH_AGENT,
        {
            "session_name": session_name,
            "generate_take_image_plots": False,
            "generate_measure3d_plots": False,
            "generate_plux_zip": False,
        },
    )
    r = result["result"]
    num_trials = r["num_trials"]
    table = r.get("trial_table", {})
    valid_ids = set(int(i) for i in table.get("trial_location_id", []))
    return num_trials, valid_ids


def import_trial(
    broker: Broker,
    nc: Nextcloud,
    session_name: str,
    location_id: int,
    base_path: str,
) -> dict:
    """1トライアルを取得して Nextcloud に保存する。"""
    folder = f"{base_path}/{location_id:04d}"
    stats = {"images": 0, "plux": False, "errors": []}

    # 既にパラメータファイルがあればスキップ
    try:
        if nc.files.by_path(f"{folder}/parameters.json") is not None:
            return {"skipped": True}
    except Exception:
        pass

    # MDG からデータ取得 (PLUX 付きで試行、失敗したら PLUX なし)
    plux_ok = True
    try:
        result = broker.ask(
            RESULT_AGENT,
            {
                "session_name": session_name,
                "location_id": location_id,
                "generate_plux_zip": True,
            },
        )
        r = result.get("result")
        if r is None:
            raise ValueError("No result")
    except Exception:
        plux_ok = False
        result = broker.ask(
            RESULT_AGENT,
            {
                "session_name": session_name,
                "location_id": location_id,
                "generate_plux_zip": False,
            },
        )
        r = result.get("result")
        if r is None:
            raise ValueError("No result even without PLUX")
        stats["errors"].append("plux: fallback to no-plux")

    # フォルダ作成
    nc.files.makedirs(folder, exist_ok=True)

    # parameters.json
    params_json = r.get("parameters_json", "{}")
    nc.files.upload(f"{folder}/parameters.json", params_json.encode())

    # 画像
    for key in IMAGE_KEYS:
        file_id = r.get(key)
        if file_id and isinstance(file_id, str):
            try:
                resp = broker.get_file(f"files/{file_id}")
                nc.files.upload(f"{folder}/{key}.png", resp.content)
                stats["images"] += 1
            except Exception as e:
                stats["errors"].append(f"{key}: {e}")

    # PLUX zip (relay_file) — plux_ok の場合のみ
    plux = r.get("measure3d_plux_zip") if plux_ok else None
    if plux and isinstance(plux, dict) and "uri" in plux:
        uri = plux["uri"]
        try:
            resp = requests.get(
                f"{MDG_BROKER_URL}{uri}",
                headers={"Authorization": f"Basic {MDG_TOKEN}"},
                timeout=300,
            )
            if resp.status_code == 200:
                nc.files.upload(f"{folder}/measure3d_plux.zip", resp.content)
                stats["plux"] = True
            else:
                stats["errors"].append(f"plux: HTTP {resp.status_code}")
        except Exception as e:
            stats["errors"].append(f"plux: {e}")

    return stats


def record_missing_trial(
    nc: Nextcloud,
    session_name: str,
    location_id: int,
    base_path: str,
) -> dict:
    """欠損トライアルを記録する。"""
    folder = f"{base_path}/{location_id:04d}"

    # 既に記録済みならスキップ
    try:
        if nc.files.by_path(f"{folder}/parameters.json") is not None:
            return {"skipped": True}
    except Exception:
        pass

    nc.files.makedirs(folder, exist_ok=True)
    info = json.dumps(
        {"status": "missing", "location_id": location_id, "session_name": session_name},
        ensure_ascii=False,
    )
    nc.files.upload(f"{folder}/parameters.json", info.encode())
    return {"missing": True}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import MDG session to Nextcloud")
    parser.add_argument("--session", required=True, help="セッション名")
    parser.add_argument("--start", type=int, default=0, help="開始 location_id")
    parser.add_argument("--end", type=int, default=-1, help="終了 location_id (-1=全件)")
    args = parser.parse_args()

    settings = Settings()
    broker = Broker(broker_url=MDG_BROKER_URL, auth=MDG_TOKEN)
    nc = Nextcloud(
        nextcloud_url=settings.nextcloud_url,
        nc_auth_user=settings.nextcloud_user,
        nc_auth_pass=settings.nextcloud_password,
    )

    session_name = args.session
    base_path = f"large/24UTARIM004/labvault/konishi-lab/mdg/{session_name}"

    # セッション情報取得
    num_trials, valid_ids = get_session_info(broker, session_name)
    missing_ids = set(range(num_trials)) - valid_ids

    end = args.end if args.end >= 0 else num_trials
    target_ids = [i for i in range(args.start, end)]

    print(f"Session: {session_name}")
    print(f"Total: {num_trials}, valid: {len(valid_ids)}, missing: {len(missing_ids)}")
    print(f"Importing: {len(target_ids)} (from {args.start} to {end - 1})")
    print(f"Nextcloud path: {base_path}")
    print()

    imported = 0
    skipped = 0
    missing_recorded = 0
    errors = 0
    start_time = time.time()

    for idx, loc_id in enumerate(target_ids):
        # 欠損トライアル
        if loc_id in missing_ids:
            try:
                stats = record_missing_trial(nc, session_name, loc_id, base_path)
                if stats.get("skipped"):
                    skipped += 1
                else:
                    missing_recorded += 1
                    print(f"  [{loc_id:04d}] MISSING (recorded)  ({idx + 1}/{len(target_ids)})")
            except Exception as e:
                print(f"  [{loc_id:04d}] MISSING record failed: {e}")
                errors += 1
            continue

        # 正常トライアル
        try:
            stats = import_trial(broker, nc, session_name, loc_id, base_path)

            if stats.get("skipped"):
                skipped += 1
                continue

            imported += 1
            elapsed = time.time() - start_time
            per_trial = elapsed / imported if imported > 0 else 0
            remaining = per_trial * (len(target_ids) - idx - 1)

            err_str = f" errors: {stats['errors']}" if stats["errors"] else ""
            print(
                f"  [{loc_id:04d}] "
                f"images={stats['images']} plux={'Y' if stats['plux'] else 'N'}"
                f"{err_str}"
                f"  ({idx + 1}/{len(target_ids)},"
                f" ~{remaining / 60:.0f}min remaining)"
            )

            if stats["errors"]:
                errors += len(stats["errors"])

        except Exception as e:
            print(f"  [{loc_id:04d}] FAILED: {e}")
            errors += 1

        # サーバー負荷軽減のため少し待つ
        time.sleep(1)

    elapsed = time.time() - start_time
    print()
    print(f"Done in {elapsed / 60:.1f} min")
    print(f"  Imported: {imported}")
    print(f"  Missing recorded: {missing_recorded}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")


if __name__ == "__main__":
    main()
