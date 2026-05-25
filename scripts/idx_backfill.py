#!/usr/bin/env python
"""既存 record の `idx_<key>` を template.indexed_fields から backfill する。

背景
----
PR #11 で `Record._to_dict()` が template の `indexed_fields` を
`idx_<key>` として top-level に書くようになった。これは **新規 / 更新後の
record にしか効かない** ので、過去の record は `idx_*` が空のまま。

PR #14 の Firestore push down (`Lab.search` / `Lab.list`) は
`idx_<key>` が存在しない record にはマッチしないため、過去 record も
高速検索に乗せるには 1 度だけ backfill が必要。

使い方
------

    # dry-run (デフォルト): 何が変わるか表示するだけ
    python scripts/idx_backfill.py --team konishi-lab

    # 実行 (本番への書き込みあり)
    python scripts/idx_backfill.py --team konishi-lab --apply

    # 範囲制限 (大きい team を分割実行)
    python scripts/idx_backfill.py --team konishi-lab --apply --limit 500

複数 team を扱う場合は team ごとに呼び直す。
"""

from __future__ import annotations

import argparse
import sys

from labvault import Lab


def _expected_idx(raw: dict, indexed_fields: list[str]) -> dict[str, object]:
    """record の conditions から `idx_<key>` の期待値 dict を組み立てる。

    値が None の key は含めない (Firestore で null を index しないため、
    PR #11 と同じセマンティクス)。
    """
    conditions = raw.get("conditions") or {}
    out: dict[str, object] = {}
    for key in indexed_fields:
        value = conditions.get(key)
        if value is not None:
            out[f"idx_{key}"] = value
    return out


def backfill(lab: Lab, *, apply: bool, limit: int) -> dict[str, int]:
    """team 内の record を走査して idx_<key> を補完する。

    Returns
    -------
    dict[str, int]
        集計 (scanned / no_template / no_change / updated)。
    """
    rows = lab._metadata.list_records(lab._team, limit=limit)
    stats = {
        "scanned": len(rows),
        "no_template": 0,
        "no_change": 0,
        "updated": 0,
    }

    for raw in rows:
        template_name = raw.get("template")
        if not template_name:
            stats["no_template"] += 1
            continue
        tpl = lab.get_template(template_name)
        if tpl is None or not tpl.indexed_fields:
            stats["no_template"] += 1
            continue

        expected = _expected_idx(raw, tpl.indexed_fields)
        # 現状と比較: 期待値と異なる key のみ書く (write 量最小化)
        diff = {k: v for k, v in expected.items() if raw.get(k) != v}
        if not diff:
            stats["no_change"] += 1
            continue

        rid = raw.get("id", "?")
        if apply:
            lab._metadata.update_record(lab._team, rid, diff)
            print(f"  [SET] {rid} ({template_name}): {diff}")
        else:
            print(f"  [DRY] {rid} ({template_name}): would set {diff}")
        stats["updated"] += 1

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--team",
        help="対象 team。省略時は LABVAULT_TEAM 環境変数 / settings から取得。",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="実行モード。指定しないと dry-run。",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="走査する最大件数 (default: 10000)。",
    )
    args = parser.parse_args()

    lab = Lab(team=args.team) if args.team else Lab()
    print(f"Team: {lab._team}")
    print(f"Mode: {'APPLY (will write)' if args.apply else 'DRY-RUN (no writes)'}")
    print(f"Limit: {args.limit}")
    print()

    stats = backfill(lab, apply=args.apply, limit=args.limit)

    print()
    print("=== Summary ===")
    print(f"  scanned      : {stats['scanned']}")
    print(f"  no_template  : {stats['no_template']}  (skipped)")
    print(f"  no_change    : {stats['no_change']}  (already correct)")
    print(f"  updated      : {stats['updated']}")
    if not args.apply and stats["updated"] > 0:
        print()
        print("dry-run のため書き込みは行っていません。--apply で再実行してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
