"""検索エンドポイント。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query

from labvault import Lab

from ..auth import get_lab
from ..schemas import RecordSummary

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=list[RecordSummary])
def search_records(
    q: str = "",
    tags: str | None = None,
    status: str | None = None,
    type: str | None = None,
    parent_id: str | None = None,
    conditions: str | None = Query(
        None, description='JSON形式の条件フィルタ (例: {"power":20})'
    ),
    limit: int = 20,
    lab: Lab = Depends(get_lab),
) -> list[RecordSummary]:
    """レコードを検索する。"""
    tag_list = tags.split(",") if tags else None
    cond_dict: dict[str, Any] | None = None
    if conditions:
        cond_dict = json.loads(conditions)

    if q:
        records = lab.search(
            q,
            tags=tag_list,
            status=status,
            type=type,
            parent_id=parent_id,
            conditions=cond_dict,
            limit=limit,
        )
    else:
        records = lab.list(
            tags=tag_list,
            status=status,
            type=type,
            limit=limit * 5 if (parent_id or cond_dict) else limit,
        )
        if parent_id is not None:
            records = [r for r in records if r.parent_id == parent_id]
        if cond_dict:
            records = [
                r
                for r in records
                if all(r.get_conditions().get(k) == v for k, v in cond_dict.items())
            ]
        records = records[:limit]

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
