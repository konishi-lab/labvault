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
    # 元の Python 型 ("ndarray" / "figure" / "dataframe" / "dict" / "list" /
    # "str" / "bytes")。add_object 経路で自動付与。add_file / add_bytes 経由
    # (raw 取り込み) は None。Web UI が拡張子推測でなく metadata から
    # 「これは Figure 由来」「これは ndarray」を判別するのに使う。
    original_type: str | None = None


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
    # template 名 (`Record._template_name`)。Web UI が context chip
    # `[template: XRD]` を表示するために使う。template 未紐付けは None。
    template_name: str | None = None
    # S1-SEC2 (2026-06-29): record 生成・最終更新の認証経路。値:
    # ``"share-link"`` (外部 token 経由) / ``"firebase"`` (Web API + Firebase
    # / PAT 経由) / ``None`` (SDK 直接 / 旧 record で未付与)。Web UI が
    # 「🔗 外部 token 由来」chip を出すのに使う。pseudo_email impersonation を
    # audit log で構造的に検出可能 (SEC2 の核心防御)。
    created_audit_source: str | None = None
    updated_audit_source: str | None = None


class RecordDetail(RecordSummary):
    conditions: dict[str, Any] = {}
    condition_units: dict[str, str] = {}
    condition_descriptions: dict[str, str] = {}
    results: dict[str, Any] = {}
    result_units: dict[str, str] = {}
    result_descriptions: dict[str, str] = {}
    # S1 (PR #84): 共有設定 (email → role)。Web UI の record 詳細で
    # 「共有」モーダルが現状を表示するのに使う。閲覧者本人がこの
    # record に共有されている場合も `shares[email]` で role が分かる。
    shares: dict[str, str] = {}
    # template.result_fields に登録された unit / description (auto-fill 元)。
    # Web UI が「この値は template 由来か手動入力か」を判別するために使う:
    # result_units[key] と template_result_units[key] が等しい → template 由来。
    # template が紐付いていない record では空 dict。
    template_result_units: dict[str, str] = {}
    template_result_descriptions: dict[str, str] = {}
    # template が要求する必須 condition / result の key リスト。Web UI の
    # sticky summary chip 行で「結果 3/9 必須」のような充足率表示に使う。
    # template 未紐付けは空 list。
    template_required_conditions: list[str] = []
    template_required_results: list[str] = []
    notes: list[NoteResponse] = []
    files: list[FileInfo] = []
    links: list[LinkResponse] = []
    events: list[dict[str, Any]] = []


class CellLogEntry(BaseModel):
    """1 セル分の Notebook 実行ログ。

    SDK の ``CellLog`` dataclass と同じスキーマの公開版。`new_vars` /
    `changed_vars` / `deleted_vars` は `tracking.namespace.diff_namespaces`
    が出した「変数名 → digest (type / shape / hash)」の dict。
    フルの値を返すと巨大化するし、機微情報も乗りやすいので、digest
    のみが入っている。
    """

    cell_id: str
    record_id: str
    cell_number: int
    execution_count: int = 0
    source: str = ""
    source_hash: str = ""
    new_vars: dict[str, Any] = {}
    changed_vars: dict[str, Any] = {}
    deleted_vars: list[str] = []
    duration_sec: float = 0.0
    executed_at: datetime | None = None
    error: dict[str, Any] | None = None
    session_id: str = ""


class CellLogListResponse(BaseModel):
    """`GET /api/records/{id}/cell_logs` のレスポンス。

    `cell_number` 昇順で `limit` 件まで。`limit` を超えた場合
    `has_more=True` を返すので、frontend は「N+ 件 (もっと絞り込んで)」
    の表記を出せる。
    """

    items: list[CellLogEntry]
    total: int
    has_more: bool = False


class RecordListResponse(BaseModel):
    items: list[RecordSummary]
    # 表示中の件数 (= items の長さ)。総ヒット数ではない (Firestore に対し
    # post-filter を含む場合、サーバ側で正確な total を出すのは現状高コスト)。
    total: int
    # サーバが limit に達して打ち切った可能性を示す。frontend は
    # 「N+ 件 (もっと絞り込んでください)」のような表記を出す。
    has_more: bool = False


class SharedRecordSummary(RecordSummary):
    """`/api/records/shared-with-me` の各要素。

    通常の `RecordSummary` に加え:
    - `team`: record の所有 team (X-Labvault-Team header を frontend が
      組み立てる際に必要)
    - `role`: 閲覧ユーザーがこの record に持つ share role
      (``"viewer"`` または ``"analyst"``)。UI が「解析」アクションを
      出すかどうか判定するのに使う。
    """

    team: str
    role: str  # "viewer" | "analyst"


class SharedRecordListResponse(BaseModel):
    """`GET /api/records/shared-with-me` のレスポンス。"""

    items: list[SharedRecordSummary]
    total: int
    has_more: bool = False


class StatsBlock(BaseModel):
    """数値集合の要約統計 (`/api/records/aggregate` のサブ構造)。

    値が空のときは null を返さず {"count": 0} を返したい — pydantic は
    field 不在を null と区別しないので、呼び出し側で常に count を見て
    判定する。
    """

    count: int
    mean: float = 0.0
    std: float = 0.0
    min: float = 0.0
    max: float = 0.0
    median: float = 0.0


class AggregateResponse(BaseModel):
    """`/api/records/aggregate` のレスポンス。

    指定した `key` (conditions または results) を numeric として
    抜き出し、`record_count` 件のうち value が見つかった `value_count`
    件で `stats` を計算する。`group_by` 指定時は `groups[label]` に
    label 別の stats を返す (labels は文字列化)。

    Web UI の `/records` StatsPanel で「現在のフィルタ集合の n /
    min / max / mean / median」を出すのに使う。limit は record の
    走査上限 (=500 default) で、超過した場合 `truncated=true`。
    """

    key: str
    record_count: int
    value_count: int
    stats: StatsBlock
    group_by: str | None = None
    groups: dict[str, StatsBlock] = {}
    truncated: bool = False


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
    # S1 Phase 1C: 子 record として作る場合は親の ID を指定する。指定時は
    # 認可が「親 record に対する ``require_analyze``」に切り替わるため、
    # 他チームから analyst 共有された user も子 record (= 解析結果) を
    # 作成できる。未指定なら root record として現 team に作成、こちらは
    # team member だけが作れる (``require_team_member``)。
    parent_id: str | None = None


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


class ResultUnitsUpdate(BaseModel):
    units: dict[str, str]
    descriptions: dict[str, str] = {}


class ResultUpdate(BaseModel):
    key: str
    value: Any


# --- 共有 (S1 / PR #84) ---


class ShareGrantRequest(BaseModel):
    """`POST /api/records/{id}/shares` の body。

    `email` は招待先 (lowercase 化して保存)、`role` は ``"viewer"`` か
    ``"analyst"`` のいずれか。
    """

    email: str
    role: str  # "viewer" | "analyst"


class ShareEntry(BaseModel):
    """`GET /api/records/{id}/shares` の各要素。"""

    email: str
    role: str


class ShareListResponse(BaseModel):
    items: list[ShareEntry]


# --- 外部 token sharing (S1 Phase 2) ---


class ShareLinkCreate(BaseModel):
    """``POST /api/records/{id}/share-links`` の body。

    pseudo_email + pseudo_display_name は token 利用者の identity。token
    で書き込んだ record の ``created_by`` / ``updated_by`` に刻まれるので、
    監査可能性のため required。expires_days 省略時は 30 日。
    """

    role: str  # "viewer" | "analyst"
    pseudo_email: str
    pseudo_display_name: str = ""
    label: str = ""
    # 0 → 期限無し、None → 30 日 (default)、最大は 365 日 (sanity)
    expires_days: int | None = None


class ShareLinkInfo(BaseModel):
    """share-link 1 件の公開メタデータ (raw token は含めない)。"""

    token_hash_prefix: str  # 表示用 prefix (先頭 16 chars)
    record_id: str
    team: str
    role: str
    pseudo_email: str
    pseudo_display_name: str
    created_by: str
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    # S1-OBS9/UX5: 最後に使われた時刻 (auth.py `_verify_share_link` で更新)。
    # ShareLinksPanel が「最終使用: ...」を表示して dormant token の特定に使う。
    last_used_at: datetime | None = None
    label: str = ""
    is_active: bool


class CreatedShareLink(ShareLinkInfo):
    """token 発行直後だけ返すレスポンス。``token`` は再表示不可。"""

    token: str


class ShareLinkListResponse(BaseModel):
    items: list[ShareLinkInfo]


class RevokeShareLinkResponse(BaseModel):
    status: str  # "ok"
    token_hash_prefix: str


class ShareLinkScopeMe(BaseModel):
    """``GET /api/share-links/me`` のレスポンス。

    share-link token で認証された user が、自分のスコープ (どの record に
    どの role でアクセス可能か) を発見するための endpoint。``/share/{token}``
    公開ページが「最初の 1 fetch」で record_id を引いて、その後通常の
    ``/api/records/{id}`` を叩く流れに使う。
    """

    record_id: str
    team: str
    role: str  # "viewer" | "analyst"
    pseudo_email: str
    pseudo_display_name: str
    expires_at: datetime | None = None
    revoked_at: datetime | None = None


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
    # AR reader grant の直近結果。None=試行記録なし、True=成功、False=失敗。
    # admin UI が「失敗 user に retry button を出す」のに使う。
    ar_granted: bool | None = None


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


class GrantArResponse(BaseModel):
    """`POST /api/admin/users/{email}/ar/grant` のレスポンス。"""

    status: str  # "ok" (grant が成功・失敗のいずれでも "ok"; 結果は ar_granted)
    email: str
    ar_granted: bool


class UpdateUserRequest(BaseModel):
    """`PATCH /api/admin/users/{email}` の body。

    各 field は optional。指定された field のみ更新する (PATCH semantics)。
    将来 role など足す場合も同じ流儀で。
    """

    active: bool | None = None
    display_name: str | None = None


class TeamSummary(BaseModel):
    team_id: str
    name: str = ""
    nextcloud_group_folder: str = ""


# --- Personal Access Tokens (PAT) ---


class CreateTokenRequest(BaseModel):
    label: str = ""


class CreateTokenResponse(BaseModel):
    """発行直後のレスポンス。raw `token` はこのときのみ返却 (再表示不可)。"""

    id: str
    label: str
    token: str
    prefix: str  # 表示用の先頭プレフィックス (e.g., "lv_abcdefghi")
    created_at: datetime


class TokenInfo(BaseModel):
    id: str
    label: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None


class TokenListResponse(BaseModel):
    items: list[TokenInfo]


class RevokeTokenResponse(BaseModel):
    status: str  # "ok"
    id: str


class TeamListResponse(BaseModel):
    items: list[TeamSummary]
