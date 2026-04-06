"""レコード CRUD + 操作エンドポイント。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError

from ..dependencies import get_lab
from ..schemas import (
    ConditionsUpdate,
    NoteCreate,
    RecordCreate,
    RecordDetail,
    RecordListResponse,
    RecordSummary,
    ResultUpdate,
    StatusUpdate,
    TagsUpdate,
)

router = APIRouter(prefix="/api/records", tags=["records"])


def _to_summary(rec: Any) -> RecordSummary:
    return RecordSummary(
        id=rec.id,
        title=rec.title,
        type=rec.type,
        status=str(rec.status),
        tags=rec.tags,
        created_by=rec.created_by,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        parent_id=rec.parent_id,
    )


def _to_detail(rec: Any) -> RecordDetail:
    return RecordDetail(
        id=rec.id,
        title=rec.title,
        type=rec.type,
        status=str(rec.status),
        tags=rec.tags,
        created_by=rec.created_by,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
        parent_id=rec.parent_id,
        conditions=rec.get_conditions(),
        results=rec.results.to_dict(),
        notes=[
            {"text": n.text, "created_at": n.created_at, "author": n.author}
            for n in rec.notes
        ],
        files=[
            {
                "name": ref.name,
                "content_type": ref.content_type,
                "size_bytes": ref.size_bytes,
            }
            for ref in rec.list_data()
        ],
        links=[
            {
                "target_id": lk.target_id,
                "relation": lk.relation,
                "description": lk.description,
            }
            for lk in rec.links
        ],
        events=rec.events,
    )


@router.get("", response_model=RecordListResponse)
def list_records(
    tags: str | None = None,
    status: str | None = None,
    type: str | None = None,
    limit: int = 20,
    offset: int = 0,
    lab: Lab = Depends(get_lab),
) -> RecordListResponse:
    """レコード一覧を取得する。"""
    tag_list = tags.split(",") if tags else None
    records = lab.list(
        tags=tag_list,
        status=status,
        type=type,
        limit=1000,
        offset=0,
    )
    # ルートレコードのみ (サブレコードを除外)
    root_records = [r for r in records if r.parent_id is None]
    page = root_records[offset : offset + limit]
    return RecordListResponse(
        items=[_to_summary(r) for r in page],
        total=len(root_records),
    )


@router.post("", response_model=RecordDetail, status_code=201)
def create_record(
    body: RecordCreate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """レコードを作成する。"""
    rec = lab.new(
        body.title,
        type=body.type,
        tags=body.tags if body.tags else None,
        auto_log=False,
        **body.conditions,
    )
    return _to_detail(rec)


@router.get("/{record_id}", response_model=RecordDetail)
def get_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """レコード詳細を取得する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    return _to_detail(rec)


@router.delete("/{record_id}", status_code=204)
def delete_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> None:
    """レコードを削除する (ソフトデリート)."""
    try:
        lab.delete(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")


@router.post("/{record_id}/restore", response_model=RecordDetail)
def restore_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """削除を取り消す。"""
    try:
        rec = lab.restore(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    return _to_detail(rec)


@router.get("/{record_id}/children", response_model=list[RecordSummary])
def get_children(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> list[RecordSummary]:
    """子レコード一覧を取得する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    return [_to_summary(c) for c in rec.children()]


# --- Record Operations ---


@router.patch("/{record_id}/conditions", response_model=RecordDetail)
def update_conditions(
    record_id: str,
    body: ConditionsUpdate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """実験条件を更新する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    rec.conditions(**body.conditions)
    return _to_detail(rec)


@router.post("/{record_id}/tags", response_model=RecordDetail)
def add_tags(
    record_id: str,
    body: TagsUpdate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """タグを追加する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    rec.tag(*body.tags)
    return _to_detail(rec)


@router.post("/{record_id}/notes", response_model=RecordDetail)
def add_note(
    record_id: str,
    body: NoteCreate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """メモを追加する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    rec.note(body.text)
    return _to_detail(rec)


@router.patch("/{record_id}/status", response_model=RecordDetail)
def update_status(
    record_id: str,
    body: StatusUpdate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """ステータスを更新する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    rec.status = body.status
    return _to_detail(rec)


@router.post("/{record_id}/results", response_model=RecordDetail)
def add_result(
    record_id: str,
    body: ResultUpdate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """結果を追加する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    rec.results[body.key] = body.value
    return _to_detail(rec)
