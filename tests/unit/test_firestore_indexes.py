"""`firestore.indexes.json` が必須の複合 index を宣言していることを検証する。

CI ではエミュレータ (= index 不要) で test が通るため、本番 Firestore で
`FailedPrecondition: requires an index` を一発検出する仕組みが無い。
SDK 側で「これらの query 形を叩く」と宣言しているなら、対応 index が
indexes.json に存在することを少なくとも構造レベルで担保する。

将来的には Firestore live smoke test (`-m integration`) で全 query を
本物の DB に投げてカバーすべき (backend review C5)。
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INDEXES_PATH = REPO_ROOT / "firestore.indexes.json"


def _fields_of(idx: dict) -> tuple[tuple[str, str], ...]:
    """index 1 件を (fieldPath, order) のタプルにする (比較用)。"""
    fields: list[tuple[str, str]] = []
    for f in idx["fields"]:
        if "order" in f:
            fields.append((f["fieldPath"], f["order"]))
        elif "arrayConfig" in f:
            fields.append((f["fieldPath"], f["arrayConfig"]))
        elif "vectorConfig" in f:
            fields.append((f["fieldPath"], "VECTOR"))
    return tuple(fields)


def test_indexes_json_is_valid() -> None:
    data = json.loads(INDEXES_PATH.read_text())
    assert "indexes" in data
    assert isinstance(data["indexes"], list)


def test_created_by_mine_only_index_exists() -> None:
    """`/api/search?created_by=X` (root レベル無関係) 用の複合 index。

    Firestore は `deleted_at == None + created_by == X + order_by updated_at`
    を投げると `(deleted_at, created_by, updated_at DESC)` を要求する。
    """
    expected = (
        ("deleted_at", "ASCENDING"),
        ("created_by", "ASCENDING"),
        ("updated_at", "DESCENDING"),
    )
    data = json.loads(INDEXES_PATH.read_text())
    found = [
        idx for idx in data["indexes"] if _fields_of(idx) == expected
    ]
    assert len(found) == 1, f"Missing composite index: {expected}"


def test_created_by_root_filter_index_exists() -> None:
    """`/api/records?created_by=X` (root のみ) 用の複合 index。

    Firestore は `deleted_at + parent_id + created_by + order_by updated_at`
    を投げると `(deleted_at, parent_id, created_by, updated_at DESC)` を要求する。
    """
    expected = (
        ("deleted_at", "ASCENDING"),
        ("parent_id", "ASCENDING"),
        ("created_by", "ASCENDING"),
        ("updated_at", "DESCENDING"),
    )
    data = json.loads(INDEXES_PATH.read_text())
    found = [
        idx for idx in data["indexes"] if _fields_of(idx) == expected
    ]
    assert len(found) == 1, f"Missing composite index: {expected}"
