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


# --- Auth / signup ---


class RequestAccessRequest(BaseModel):
    requested_team_name: str
    note: str = ""


class RequestAccessResponse(BaseModel):
    status: str  # "pending" | "already_allowed"
    email: str
    requested_team_name: str = ""


class PendingUser(BaseModel):
    email: str
    display_name: str = ""
    requested_team_name: str = ""
    note: str = ""
    created_at: datetime | None = None


class PendingListResponse(BaseModel):
    items: list[PendingUser]


class NewTeamSpec(BaseModel):
    team_id: str
    name: str
    nextcloud_group_folder: str


class ApproveRequest(BaseModel):
    email: str
    action: str  # "create_team" | "assign"
    role: str = "member"  # member | admin | viewer (team 単位 role)
    team_id: str = ""  # action == "assign" の場合に必要
    new_team: NewTeamSpec | None = None  # action == "create_team" の場合に必要


class ApproveResponse(BaseModel):
    status: str  # "ok"
    email: str
    team_id: str
    # Artifact Registry reader 権限を付与できたか
    # (None=試行せず, True=成功 or 既に付与済み, False=失敗 — backend ログ参照)
    ar_granted: bool | None = None


# --- Admin: user / team management ---


class TeamMembershipResponse(BaseModel):
    team_id: str
    role: str
    name: str = ""


class AllowedUser(BaseModel):
    email: str
    display_name: str = ""
    role: str = ""  # legacy global role
    teams: list[TeamMembershipResponse] = []
    default_team: str = ""
    active: bool = True
    created_at: datetime | None = None
    last_login_at: datetime | None = None


class UserListResponse(BaseModel):
    items: list[AllowedUser]


class AddTeamRequest(BaseModel):
    team_id: str
    role: str = "member"  # admin | member | viewer


class UserTeamsResponse(BaseModel):
    status: str  # "ok"
    email: str
    teams: list[TeamMembershipResponse]
    default_team: str
    ar_granted: bool | None = None  # add 時のみ意味あり


class UpdateUserRequest(BaseModel):
    """`PATCH /api/admin/users/{email}` の body。

    現状は active toggle のみ。将来 display_name や role など足す場合は optional で。
    """

    active: bool


class TeamSummary(BaseModel):
    team_id: str
    name: str = ""
    nextcloud_group_folder: str = ""


class TeamListResponse(BaseModel):
    items: list[TeamSummary]
