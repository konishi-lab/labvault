"""検索エンドポイント。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from labvault import Lab

from ..dependencies import get_lab
from ..schemas import RecordSummary

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[RecordSummary])
def search_records(
    q: str = "",
    tags: str | None = None,
    status: str | None = None,
    type: str | None = None,
    limit: int = 20,
    lab: Lab = Depends(get_lab),
) -> list[RecordSummary]:
    """レコードを検索する。"""
    tag_list = tags.split(",") if tags else None

    if q:
        records = lab.search(
            q,
            tags=tag_list,
            status=status,
            type=type,
            limit=limit,
        )
    else:
        records = lab.list(
            tags=tag_list,
            status=status,
            type=type,
            limit=limit,
        )

    return [
        RecordSummary(
            id=r.id,
            title=r.title,
            type=r.type,
            status=str(r.status),
            tags=r.tags,
            created_by=r.created_by,
            created_at=r.created_at,
            updated_at=r.updated_at,
            parent_id=r.parent_id,
        )
        for r in records
    ]
