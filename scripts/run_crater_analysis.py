"""全サブレコードに対してクレーター解析を実行するスクリプト。

PLUX データ (measure3d_plux.zip) から before/after 差分でクレーター計測し、
解析 Record を作成 + 測定 Record に results を書き戻す。

使い方:
    python scripts/run_crater_analysis.py --parent 6HDKNS
    python scripts/run_crater_analysis.py --parent 6HDKNS --dry-run
"""

from __future__ import annotations

import argparse
import os
import time


def analyze_crater(data: bytes, *, threshold_um: float = 0.05) -> dict:
    """PLUX zip から before/after 差分でクレーター計測する。"""
    import io
    import zipfile

    from labvault.parsers._analysis import correct_tilt, detect_crater
    from labvault.parsers.plux import diff_height_maps

    zf = zipfile.ZipFile(io.BytesIO(data))
    names = zf.namelist()
    before_name = next((n for n in names if "before" in n), None)
    after_name = next((n for n in names if "after" in n), None)

    results: dict = {}

    if before_name and after_name:
        diff, pixel_size = diff_height_maps(zf.read(before_name), zf.read(after_name))
        corrected = correct_tilt(diff)
        crater = detect_crater(corrected, pixel_size, threshold_um=threshold_um)
        if crater:
            results = {
                "diameter": round(crater.diameter_um, 2),
                "depth": round(crater.depth_um, 2),
                "mean_depth": round(crater.mean_depth_um, 2),
                "volume": round(crater.volume_um3, 1),
                "area": round(crater.area_um2, 1),
            }
        else:
            results = {"crater_detected": False}
    else:
        results = {"crater_detected": False}

    return {
        "results": results,
        "units": {
            "diameter": "um",
            "depth": "um",
            "mean_depth": "um",
            "volume": "um3",
            "area": "um2",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run crater analysis on all sub-records")
    parser.add_argument("--parent", required=True, help="親レコード ID")
    parser.add_argument("--dry-run", action="store_true", help="プレビューのみ")
    parser.add_argument("--start", type=int, default=0, help="開始インデックス")
    args = parser.parse_args()

    os.environ["LABVAULT_AUTO_SYNC"] = "false"

    from labvault import Lab
    from labvault.core.record import Record

    lab = Lab()

    # 子レコード取得
    if hasattr(lab._metadata, "list_records"):
        rows = lab._metadata.list_records(lab._team, parent_id=args.parent, limit=10000)
        children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        children = [r for r in all_records if r.parent_id == args.parent]

    # PLUX があるレコードのみ対象
    targets = []
    for rec in children:
        has_plux = any(r.name == "measure3d_plux.zip" for r in rec.list_data())
        already_done = "depth" in rec.results
        if has_plux and not already_done:
            targets.append(rec)

    print(f"Parent: {args.parent}")
    print(f"Total children: {len(children)}")
    print(f"With PLUX (not yet analyzed): {len(targets)}")
    print(f"Start index: {args.start}")
    print()

    if args.dry_run:
        for i, rec in enumerate(targets[:10]):
            print(f"  [{rec.id}] {rec.title}")
        if len(targets) > 10:
            print(f"  ... and {len(targets) - 10} more")
        return

    analyzed = 0
    skipped = 0
    errors = 0
    no_crater = 0
    start_time = time.time()

    for i, rec in enumerate(targets[args.start:], start=args.start):
        try:
            ana = rec.run_analysis(analyze_crater, "measure3d_plux.zip", params={"threshold_um": 0.05})

            if rec.results.get("crater_detected") is False:
                no_crater += 1
                tag = "no crater"
            else:
                analyzed += 1
                depth = rec.results.get("depth", "?")
                diameter = rec.results.get("diameter", "?")
                tag = f"depth={depth} diameter={diameter}"

            elapsed = time.time() - start_time
            done = analyzed + no_crater + errors
            if done > 0:
                per_rec = elapsed / done
                remaining = per_rec * (len(targets) - args.start - done)
            else:
                remaining = 0

            if (i + 1) % 50 == 0 or i < 3:
                print(
                    f"  [{rec.id}] {tag}"
                    f"  ({i + 1}/{len(targets)}, ~{remaining / 60:.0f}min remaining)"
                )

        except Exception as e:
            print(f"  [{rec.id}] ERROR: {e}")
            errors += 1

    elapsed = time.time() - start_time
    print()
    print(f"Done in {elapsed / 60:.1f} min")
    print(f"  Analyzed: {analyzed}")
    print(f"  No crater: {no_crater}")
    print(f"  Skipped (already done): {skipped}")
    print(f"  Errors: {errors}")

    lab.close()


if __name__ == "__main__":
    main()
