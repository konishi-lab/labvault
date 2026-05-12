"""SDK 用 raw metadata API。

PlatformMetadataBackend (PAT 認証で動く SDK) からの呼び出しを受ける。
レスポンスは Firestore の生 dict (FirestoreMetadataBackend.get_record と同型)
をそのまま JSON 化する。Web UI 向けの整形済 ``/api/records/...`` とは別系統。

team は ``X-Labvault-Team`` header から取る (current_team が解決)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from labvault import Lab

from ..auth import current_team, get_lab

router = APIRouter(prefix="/api/metadata")


def _jsonable(value: Any) -> Any:
    """Firestore 固有型 (Vector 等) を JSON-safe な形に再帰変換する。

    - Vector → list[float]
    - dict → 値を再帰変換
    - list/tuple → 要素を再帰変換
    - その他 (datetime / プリミティブ) はそのまま返す (FastAPI が処理)
    """
    # google.cloud.firestore Vector を遅延 import (依存を main 経路から外す)
    try:
        from google.cloud.firestore_v1.vector import Vector
    except ImportError:  # pragma: no cover
        Vector = None  # type: ignore[assignment]

    if Vector is not None and isinstance(value, Vector):
        return list(value.to_map_value().get("value", []))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


@router.get("/records/{record_id}")
def get_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, Any]:
    """単一レコードの生 dict を返す。soft delete 済は 404。"""
    data = lab._metadata.get_record(team, record_id)
    if data is None:
        raise HTTPException(status_code=404, detail="record not found")
    return _jsonable(data)


@router.get("/records")
def list_records(
    tags: str | None = None,
    status: str | None = None,
    record_type: str | None = Query(None, alias="type"),
    created_by: str | None = None,
    parent_id: str | None = None,
    parent_unset: bool = False,
    limit: int = 100,
    offset: int = 0,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """レコード一覧の生 dict 配列を返す。

    parent_id semantics:
      - parent_unset=true: parent_id が None (ルートレコード) のみ
      - parent_id="abc": parent_id == "abc"
      - 両方未指定: parent_id フィルタなし (全レコード)
    """
    tag_list = tags.split(",") if tags else None
    if parent_unset:
        pid: str | None = None
    elif parent_id is not None:
        pid = parent_id
    else:
        pid = "__unset__"  # MetadataBackend の sentinel: フィルタなし
    rows = lab._metadata.list_records(
        team,
        tags=tag_list,
        status=status,
        record_type=record_type,
        created_by=created_by,
        parent_id=pid,
        limit=limit,
        offset=offset,
    )
    return [_jsonable(r) for r in rows]


@router.get("/records/{record_id}/cell_logs")
def get_cell_logs(
    record_id: str,
    limit: int = 100,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """セルログ一覧の生 dict 配列。cell_number 昇順。"""
    return [_jsonable(r) for r in lab._metadata.get_cell_logs(team, record_id, limit=limit)]


@router.get("/templates/{name}")
def get_template(
    name: str,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, Any]:
    """テンプレートの生 dict。未存在は 404。"""
    data = lab._metadata.get_template(team, name)
    if data is None:
        raise HTTPException(status_code=404, detail="template not found")
    return _jsonable(data)


@router.get("/templates")
def list_templates(
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """テンプレート一覧の生 dict 配列。"""
    return [_jsonable(t) for t in lab._metadata.list_templates(team)]
