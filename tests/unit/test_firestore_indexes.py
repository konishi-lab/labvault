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
    found = [idx for idx in data["indexes"] if _fields_of(idx) == expected]
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
    found = [idx for idx in data["indexes"] if _fields_of(idx) == expected]
    assert len(found) == 1, f"Missing composite index: {expected}"


def test_shared_with_emails_collection_group_index_exists() -> None:
    """S1 Phase 1B: `shared-with-me` cross-team query 用の collection group index。

    `FirestoreMetadataBackend.list_records_shared_with` が
    `collection_group('records').where(deleted_at==None)
        .where(shared_with_emails array_contains email)
        .order_by(updated_at DESC)` を投げるので、
    `(deleted_at ASC, shared_with_emails CONTAINS, updated_at DESC)` の
    COLLECTION_GROUP scoped index が要る。
    """
    expected = (
        ("deleted_at", "ASCENDING"),
        ("shared_with_emails", "CONTAINS"),
        ("updated_at", "DESCENDING"),
    )
    data = json.loads(INDEXES_PATH.read_text())
    found = [
        idx
        for idx in data["indexes"]
        if _fields_of(idx) == expected and idx.get("queryScope") == "COLLECTION_GROUP"
    ]
    assert len(found) == 1, (
        f"Missing COLLECTION_GROUP composite index for shared-with-me: {expected}"
    )


def test_tags_composite_index_exists() -> None:
    """2026-07-01: tag search 用の COLLECTION index。

    `FirestoreMetadataBackend.list_records` が
    `where(deleted_at==None).where(tags array_contains X).order_by(updated_at DESC)`
    を投げるので、`(deleted_at ASC, tags CONTAINS, updated_at DESC)` の
    COLLECTION scoped index が要る。旧来は本番 Firestore に手動で作られて
    いない状態で、CLI `labvault search --tags X` / MCP `search(tags=[X])`
    が `FailedPrecondition: requires an index` を踏む状況だった (2026-07-01
    kimura record 調査時に判明)。
    """
    expected = (
        ("deleted_at", "ASCENDING"),
        ("tags", "CONTAINS"),
        ("updated_at", "DESCENDING"),
    )
    data = json.loads(INDEXES_PATH.read_text())
    found = [
        idx
        for idx in data["indexes"]
        if _fields_of(idx) == expected and idx.get("queryScope") == "COLLECTION"
    ]
    assert len(found) == 1, f"Missing COLLECTION composite index for tags: {expected}"


def test_shared_links_does_not_require_composite_index() -> None:
    """S1-OBS8 hot-fix (2026-06-29): ``shared_links`` collection の query
    パターンが composite index を要求しない構造を documented invariant 化。

    現在の query (``platform/backend/app/share_links.py``):

    - ``get_by_hash`` / ``revoke``:
      ``where('token_hash','==',x).limit(1)`` — 単一 equality
    - ``list_for_record``:
      ``where('record_id','==',x).where('team','==',y)`` —
      2 equality filter (no ordering)。Firestore は zigzag merge で
      単一 field index を組合せ可能 → composite 不要

    将来 ``order_by`` 追加 / range filter 追加で composite が必要になっ
    たら、``firestore.indexes.json`` に declare + 本 test の docstring +
    assertion を更新する (PR #74 の教訓: ``FailedPrecondition: requires
    an index`` を本番 deploy 後に踏まないために事前固定)。
    """
    data = json.loads(INDEXES_PATH.read_text())
    shared_link_indexes = [
        idx for idx in data["indexes"] if idx.get("collectionGroup") == "shared_links"
    ]
    assert shared_link_indexes == [], (
        "shared_links に composite index 宣言が出現しました。query pattern が "
        "変わって composite が必要になった可能性があります。本 test の "
        "docstring を更新し、新しい query 形を documented invariant として "
        "明示してください。"
    )
