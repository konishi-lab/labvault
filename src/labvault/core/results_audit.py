"""results 規約違反の診断ユーティリティ。

v0.3.0 以降、`Record.results` は以下を強制する:
- dict は禁止 (構造体は ``add_object`` に逃がす)
- list は 32 要素以下
- 1 値 100 KB / results 合計 500 KB 以下 (Firestore 1 MB 安全圏)

新規書き込みは ``_ResultsProxy.__setitem__`` で hard error になるが、既存
Firestore レコードには規約以前に書き込まれた dict / 長 list が残っている
可能性がある。本モジュールはそれらを **読み出し時に診断** するための純粋
関数を提供する (副作用なし、CLI / スクリプトから利用可)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

# v0.3.0 で `_ResultsProxy` に入れた閾値と同じ。同期するため import する。
from labvault.core.record import _ResultsProxy

MAX_LIST_LEN = _ResultsProxy._MAX_LIST_LEN
MAX_VALUE_BYTES = _ResultsProxy._MAX_VALUE_BYTES
MAX_TOTAL_BYTES = _ResultsProxy._MAX_TOTAL_BYTES


@dataclass(frozen=True)
class Violation:
    """1 件の results 規約違反。

    record_id / key / kind / detail で違反箇所と理由を記述する。
    Web UI への表示や CSV 出力で使う。
    """

    record_id: str
    key: str  # 違反 key 名 (合計サイズ違反では "<total>")
    kind: str  # "dict" | "long_list" | "value_too_large" | "total_too_large"
    detail: str  # 人間可読の説明
    value_preview: str = ""  # 値の最初 80 文字 (JSON 化)


def _preview(value: Any) -> str:
    """ログ向けに値を短い文字列に整形する。"""
    try:
        s = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(value)
    return s[:80] + ("..." if len(s) > 80 else "")


def _estimate_json_bytes(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(value).encode("utf-8"))


def scan_record(record: dict[str, Any]) -> list[Violation]:
    """1 件の record dict (Firestore からの raw doc) を診断し、違反のリストを返す。

    検出する違反:
    - ``results[k]`` が dict
    - ``results[k]`` が 32 要素超の list
    - ``results[k]`` の値サイズが 100 KB 超
    - ``results`` 全体サイズが 500 KB 超
    """
    rid = str(record.get("id") or "")
    results = record.get("results") or {}
    if not isinstance(results, dict):
        return []

    out: list[Violation] = []

    for key, value in results.items():
        key_str = str(key)

        if isinstance(value, dict):
            out.append(
                Violation(
                    record_id=rid,
                    key=key_str,
                    kind="dict",
                    detail=(
                        f"dict は v0.3.0 以降禁止。flat 展開 "
                        f"({key_str}_a, {key_str}_b, ...) または "
                        f"add_object('{key_str}.json', ...) でファイル化を推奨。"
                    ),
                    value_preview=_preview(value),
                )
            )
            continue  # dict のサイズチェックは無意味なのでスキップ

        if isinstance(value, list) and len(value) > MAX_LIST_LEN:
            out.append(
                Violation(
                    record_id=rid,
                    key=key_str,
                    kind="long_list",
                    detail=(
                        f"list 要素数 {len(value)} > 上限 {MAX_LIST_LEN}。"
                        f"配列本体は add_object('{key_str}.npy', np.array(...)) で"
                        f"ファイル化し、results には代表値だけ残してください。"
                    ),
                    value_preview=_preview(value),
                )
            )

        size = _estimate_json_bytes(value)
        if size > MAX_VALUE_BYTES:
            out.append(
                Violation(
                    record_id=rid,
                    key=key_str,
                    kind="value_too_large",
                    detail=(
                        f"値サイズ {size} byte > 上限 {MAX_VALUE_BYTES} byte。"
                        f"大きいデータは add_object / add_file でファイル化を。"
                    ),
                    value_preview=_preview(value),
                )
            )

    total = _estimate_json_bytes(results)
    if total > MAX_TOTAL_BYTES:
        out.append(
            Violation(
                record_id=rid,
                key="<total>",
                kind="total_too_large",
                detail=(
                    f"results 合計サイズ {total} byte > 上限 {MAX_TOTAL_BYTES} byte "
                    f"(Firestore 1 MB 制限の安全圏)。代表値だけ残し、原本は "
                    f"add_object に逃がしてください。"
                ),
                value_preview="",
            )
        )

    return out


def summarize(violations: list[Violation]) -> dict[str, int]:
    """違反種別ごとの件数を集計する。"""
    counts: dict[str, int] = {}
    for v in violations:
        counts[v.kind] = counts.get(v.kind, 0) + 1
    return counts
