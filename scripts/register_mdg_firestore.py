"""MDG セッションデータを Firestore に登録するスクリプト。

Nextcloud へのファイル保存 (import_mdg.py) とは独立して実行可能。
trial_table からメタデータを取得し、labvault レコードとして登録する。

使い方:
    python scripts/register_mdg_firestore.py --session kkonishi --dry-run
    python scripts/register_mdg_firestore.py --session kkonishi
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from brokersystem import Broker

from labvault import Lab
from labvault.core.record import Record
from labvault.core.types import DataRef

MDG_BROKER_URL = "https://mdg2.gigalixirapp.com"
MDG_TOKEN = "db1cfc13-d02d-40f1-8056-2d4e80c14380"
BATCH_AGENT = "fdc1c45c-7204-46ab-9e08-0b85c5c1e90c"

IMAGE_FILES = [
    "take_image_before.png",
    "take_image_after.png",
    "take_image_comparison.png",
    "measure3d_before_plot.png",
    "measure3d_after_plot.png",
    "measure3d_comparison.png",
    "measure3d_stack_before.png",
    "measure3d_stack_after.png",
    "measure3d_stack_comparison.png",
]


def get_session_data(
    broker: Broker, session_name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """セッションのメタデータと trial_table を取得する。"""
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

    # trial_table を行リストに変換
    table = r.get("trial_table", {})
    col_keys = [k for k in table.keys() if not k.startswith("@") and not k.startswith("_")]
    if not col_keys:
        return r, []

    num_rows = len(table[col_keys[0]])
    rows = []
    for i in range(num_rows):
        row = {k: table[k][i] for k in col_keys}
        rows.append(row)

    return r, rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Register MDG session data in Firestore"
    )
    parser.add_argument("--session", required=True, help="セッション名")
    parser.add_argument("--dry-run", action="store_true", help="プレビューのみ")
    args = parser.parse_args()

    os.environ["LABVAULT_AUTO_SYNC"] = "false"

    broker = Broker(broker_url=MDG_BROKER_URL, auth=MDG_TOKEN)
    lab = Lab()

    session_name = args.session
    base_path = f"large/24UTARIM004/labvault/konishi-lab/mdg/{session_name}"

    print(f"Session: {session_name}")
    print(f"Metadata backend: {type(lab._metadata).__name__}")
    print(f"Dry run: {args.dry_run}")
    print()

    # セッション情報取得
    print("Fetching session data from MDG...")
    session_meta, trials = get_session_data(broker, session_name)
    num_trials = session_meta["num_trials"]
    valid_ids = {int(t["trial_location_id"]) for t in trials}
    missing_ids = set(range(num_trials)) - valid_ids

    print(f"  num_trials: {num_trials}")
    print(f"  completed: {len(trials)}")
    print(f"  missing: {len(missing_ids)}")
    print()

    if args.dry_run:
        print("=== Dry Run ===")
        print(f"Would create root record: MDG carbide1 {session_name}")
        print(f"Would create {num_trials} sub-records:")
        for t in trials[:3]:
            print(f"  location_id={t['trial_location_id']}: "
                  f"material={t['trial_material']}, "
                  f"pulseenergy={t['trial_pulseenergy']}, "
                  f"pulsenumber={t['trial_pulsenumber']}")
        if len(trials) > 3:
            print(f"  ... and {len(trials) - 3} more")
        for mid in sorted(missing_ids)[:3]:
            print(f"  location_id={mid}: MISSING")
        if len(missing_ids) > 3:
            print(f"  ... and {len(missing_ids) - 3} more missing")
        print()
        print("Run without --dry-run to execute.")
        lab.close()
        return

    # ルートレコード作成
    root = lab.new(
        f"MDG carbide1 {session_name}",
        tags=["MDG", "carbide1", session_name],
        auto_log=False,
    )
    root.conditions(
        session_name=session_name,
        session_id=session_meta.get("session_id", ""),
        source="MDG",
        agent="carbide1照射前後表面形状評価",
    )
    root.status = "success"
    print(f"Root record: [{root.id}] {root.title}")

    # trial_table を dict でインデックス化
    trial_by_loc = {int(t["trial_location_id"]): t for t in trials}

    created = 0
    for loc_id in range(num_trials):
        trial = trial_by_loc.get(loc_id)
        is_missing = loc_id in missing_ids
        folder = f"{base_path}/{loc_id:04d}"

        if trial:
            title = (
                f"loc{loc_id:04d}_{trial.get('trial_material', '')}"
                f"_{trial.get('trial_pulseenergy', '')}J"
            )
            child = root.sub(title, type="measurement")
            child.conditions(
                location_id=loc_id,
                material=trial.get("trial_material", ""),
                cassette_id=trial.get("trial_cassette_id", ""),
                lot_id=trial.get("trial_lot_id", ""),
                x=trial.get("trial_x", 0),
                y=trial.get("trial_y", 0),
                defocus=trial.get("trial_defocus", 0),
                pulseenergy=trial.get("trial_pulseenergy", 0),
                pulsenumber=trial.get("trial_pulsenumber", 0),
                pulseduration=trial.get("trial_pulseduration", 0),
                pulse_count=trial.get("trial_pulse_count", 0),
            )

            # DataRef (ファイル参照)
            for fname in IMAGE_FILES:
                child._data_refs.append(
                    DataRef(name=fname, nextcloud_path=f"{folder}/{fname}")
                )
            child._data_refs.append(
                DataRef(
                    name="measure3d_plux.zip",
                    nextcloud_path=f"{folder}/measure3d_plux.zip",
                )
            )
            child._data_refs.append(
                DataRef(
                    name="parameters.json",
                    nextcloud_path=f"{folder}/parameters.json",
                )
            )

            child.status = "success"
            child._persist()
        else:
            # 欠損トライアル
            child = root.sub(f"loc{loc_id:04d}_MISSING", type="measurement")
            child.conditions(location_id=loc_id)
            child.note("MDG trial missing: データ取得に失敗")
            child.status = "failed"
            child._persist()

        created += 1
        if created % 100 == 0:
            print(f"  {created}/{num_trials} records created...")

    print()
    print(f"Done: {created} sub-records created under [{root.id}]")
    lab.close()


if __name__ == "__main__":
    main()
