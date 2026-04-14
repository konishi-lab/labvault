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
    ConditionUnitsUpdate,
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
        condition_units=rec.get_condition_units(),
        condition_descriptions=rec.get_condition_descriptions(),
        results=rec.results.to_dict(),
        result_units=rec.get_result_units(),
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
    # Firestore に parent_id==None フィルタを直接渡す
    if hasattr(lab._metadata, "list_records"):
        records = lab._metadata.list_records(
            lab._team,
            tags=tag_list,
            status=status,
            record_type=type,
            parent_id=None,  # ルートレコードのみ
            limit=limit,
            offset=offset,
        )
        from labvault.core.record import Record

        items = [Record._from_dict(r, lab=lab) for r in records]
    else:
        items = lab.list(
            tags=tag_list, status=status, type=type, limit=limit, offset=offset
        )
        items = [r for r in items if r.parent_id is None]

    return RecordListResponse(
        items=[_to_summary(r) for r in items],
        total=len(items),
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


@router.get("/{record_id}/children", response_model=RecordListResponse)
def get_children(
    record_id: str,
    limit: int = 100,
    offset: int = 0,
    lab: Lab = Depends(get_lab),
) -> RecordListResponse:
    """子レコード一覧を取得する（ページネーション対応）。"""
    from labvault.core.record import Record

    try:
        lab.get(record_id)  # 存在確認
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    if hasattr(lab._metadata, "list_records"):
        # total カウント用に大きめに取得
        all_rows = lab._metadata.list_records(
            lab._team,
            parent_id=record_id,
            limit=10000,
        )
        total = len(all_rows)
        rows = all_rows[offset : offset + limit]
        children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        all_children = [r for r in all_records if r.parent_id == record_id]
        total = len(all_children)
        children = all_children[offset : offset + limit]

    return RecordListResponse(
        items=[_to_summary(c) for c in children],
        total=total,
    )


@router.get("/{record_id}/children/conditions")
def get_children_conditions(
    record_id: str,
    limit: int = 2000,
    lab: Lab = Depends(get_lab),
) -> list[dict[str, Any]]:
    """子レコードの ID + conditions を一括取得する。散布図用。"""
    from labvault.core.record import Record

    try:
        lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    if hasattr(lab._metadata, "list_records"):
        rows = lab._metadata.list_records(
            lab._team, parent_id=record_id, limit=limit
        )
        children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        children = [r for r in all_records if r.parent_id == record_id]

    return [
        {"id": c.id, "title": c.title, "conditions": c.get_conditions()}
        for c in children
    ]


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


@router.patch("/{record_id}/units", response_model=RecordDetail)
def update_units(
    record_id: str,
    body: ConditionUnitsUpdate,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """条件の単位と説明を更新する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    rec._condition_units.update(body.units)
    if body.descriptions:
        rec._condition_descriptions.update(body.descriptions)
    rec._persist()
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
