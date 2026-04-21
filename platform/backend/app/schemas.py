"""API リクエスト/レスポンススキーマ。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

# --- Response Models ---


class NoteResponse(BaseModel):
    text: str
    created_at: datetime
    author: str = ""


class LinkResponse(BaseModel):
    target_id: str
    relation: str = "related_to"
    description: str = ""


class FileInfo(BaseModel):
    name: str
    content_type: str = ""
    size_bytes: int = 0


class RecordSummary(BaseModel):
    id: str
    title: str
    type: str
    status: str
    tags: list[str] = []
    created_by: str = ""
    created_at: datetime
    updated_by: str = ""
    updated_at: datetime
    parent_id: str | None = None


class RecordDetail(RecordSummary):
    conditions: dict[str, Any] = {}
    condition_units: dict[str, str] = {}
    condition_descriptions: dict[str, str] = {}
    results: dict[str, Any] = {}
    result_units: dict[str, str] = {}
    notes: list[NoteResponse] = []
    files: list[FileInfo] = []
    links: list[LinkResponse] = []
    events: list[dict[str, Any]] = []


class RecordListResponse(BaseModel):
    items: list[RecordSummary]
    total: int


class HealthResponse(BaseModel):
    status: str
    team: str
    metadata_backend: str
    storage_backend: str


# --- Request Models ---


class RecordCreate(BaseModel):
    title: str
    type: str = "experiment"
    tags: list[str] = []
    conditions: dict[str, Any] = {}


class NoteCreate(BaseModel):
    text: str


class TagsUpdate(BaseModel):
    tags: list[str]


class StatusUpdate(BaseModel):
    status: str


class ConditionsUpdate(BaseModel):
    conditions: dict[str, Any]


class ConditionUnitsUpdate(BaseModel):
    units: dict[str, str]
    descriptions: dict[str, str] = {}


class ResultUpdate(BaseModel):
    key: str
    value: Any
