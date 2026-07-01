const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// --- auth token plumbing ---
let _getToken: () => Promise<string | null> = async () => null;
let _getTeam: () => string | null = () => null;

export function setTokenProvider(fn: () => Promise<string | null>) {
  _getToken = fn;
}

export function setTeamProvider(fn: () => string | null) {
  _getTeam = fn;
}

export async function authFetch(
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = await _getToken();
  const team = _getTeam();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (team) headers.set("X-Labvault-Team", team);
  return fetch(url, { ...init, headers });
}

export interface RecordSummary {
  id: string;
  title: string;
  type: string;
  status: string;
  tags: string[];
  created_by: string;
  created_at: string;
  updated_by: string;
  updated_at: string;
  parent_id: string | null;
  // template 名 (Record._template_name)。Web UI が context chip
  // `[template: XRD]` を表示するために使う。template 未紐付けは null。
  template_name?: string | null;
  // S1-SEC2 (2026-06-29): record 生成・最終更新の認証経路。
  // "share-link" = 外部 token 経由、"firebase" = Web API 認証経由、
  // null = SDK 直接 / 旧 record。`/records/[id]` の header に
  // 「🔗 外部 token 由来」chip を出すのに使う。
  created_audit_source?: string | null;
  updated_audit_source?: string | null;
}

export interface NoteResponse {
  text: string;
  created_at: string;
  author: string;
}

export interface LinkResponse {
  target_id: string;
  relation: string;
  description: string;
}

export interface FileInfo {
  name: string;
  content_type: string;
  size_bytes: number;
  // 元の Python 型 ("ndarray" / "figure" / "dataframe" / "dict" / "list" /
  // "str" / "bytes")。add_object 経路で自動付与。null は raw 取り込み
  // (add_file / add_bytes) または旧 record で未付与のもの。
  original_type: string | null;
}

export interface RecordDetail extends RecordSummary {
  conditions: Record<string, unknown>;
  condition_units: Record<string, string>;
  condition_descriptions: Record<string, string>;
  results: Record<string, unknown>;
  result_units: Record<string, string>;
  result_descriptions: Record<string, string>;
  // template.result_fields に登録された unit / description (auto-fill 元)。
  // result_units[key] === template_result_units[key] なら template 由来、
  // それ以外は手動入力。template が無い record では {}。
  template_result_units: Record<string, string>;
  template_result_descriptions: Record<string, string>;
  // template が要求する必須 key リスト (sticky summary chip 行で
  // 充足率 `結果 3/9 必須` を出すのに使う)。template 未紐付けは空。
  template_required_conditions?: string[];
  template_required_results?: string[];
  // S1 Phase 1A: email → role ("viewer" | "analyst") の共有設定。
  // 共有モーダルが現状を表示するのに使う。viewer/analyst として share
  // されている本人にも、自分の role 確認のため返ってくる。共有が無い
  // 場合は空 dict、旧 record では undefined (Phase 1A 以降は常に dict)。
  shares?: Record<string, string>;
  notes: NoteResponse[];
  files: FileInfo[];
  links: LinkResponse[];
  events: Record<string, unknown>[];
}

export interface RecordListResponse {
  items: RecordSummary[];
  // 表示中の件数 (= items.length)。総ヒット数ではない。
  total: number;
  // サーバが limit に達して打ち切った可能性 (true なら「N+ 件」表示)。
  has_more?: boolean;
}

export interface HealthResponse {
  status: string;
  team: string;
  metadata_backend: string;
  storage_backend: string;
}

export async function fetchRecords(params?: {
  tags?: string;
  status?: string;
  type?: string;
  conditions?: Record<string, unknown>;
  createdBy?: string;
  template?: string;
  limit?: number;
  offset?: number;
}): Promise<RecordListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.tags) searchParams.set("tags", params.tags);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.type) searchParams.set("type", params.type);
  if (params?.conditions && Object.keys(params.conditions).length > 0) {
    // backend は conditions を JSON 文字列で受ける。indexed_fields に
    // 挙がっている key は Firestore に push down される (PR #14)。
    searchParams.set("conditions", JSON.stringify(params.conditions));
  }
  if (params?.createdBy) searchParams.set("created_by", params.createdBy);
  if (params?.template) searchParams.set("template", params.template);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));

  const res = await authFetch(`${API_BASE}/api/records?${searchParams}`);
  if (!res.ok) throw new Error(`Failed to fetch records: ${res.status}`);
  return res.json();
}

export async function fetchRecord(id: string): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch record: ${res.status}`);
  return res.json();
}

export async function searchRecords(
  query: string,
  params?: {
    tags?: string;
    status?: string;
    type?: string;
    conditions?: Record<string, unknown>;
    createdBy?: string;
    template?: string;
    limit?: number;
  }
): Promise<RecordSummary[]> {
  const searchParams = new URLSearchParams();
  if (query) searchParams.set("q", query);
  if (params?.tags) searchParams.set("tags", params.tags);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.type) searchParams.set("type", params.type);
  if (params?.conditions && Object.keys(params.conditions).length > 0) {
    searchParams.set("conditions", JSON.stringify(params.conditions));
  }
  if (params?.createdBy) searchParams.set("created_by", params.createdBy);
  if (params?.template) searchParams.set("template", params.template);
  if (params?.limit) searchParams.set("limit", String(params.limit));

  const res = await authFetch(`${API_BASE}/api/search?${searchParams}`);
  if (!res.ok) throw new Error(`Failed to search: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await authFetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error(`Failed to fetch health: ${res.status}`);
  return res.json();
}

// `/api/records/aggregate` のレスポンス型 (backend の AggregateResponse と一致)。
// 値が空でも stats.count=0 で返るので null 判定不要。
export interface StatsBlock {
  count: number;
  mean: number;
  std: number;
  min: number;
  max: number;
  median: number;
}

export interface AggregateResponse {
  key: string;
  record_count: number;
  value_count: number;
  stats: StatsBlock;
  group_by?: string | null;
  groups: Record<string, StatsBlock>;
  truncated: boolean;
}

// 現フィルタ集合に対する key の数値統計。/records StatsPanel で
// 「表示中 200 件でなく、フィルタにマッチする全集合の n / min / max /
// mean / median」を出すのに使う。limit はサーバ走査上限 (default 500)。
export async function fetchAggregate(
  key: string,
  params?: {
    tags?: string;
    status?: string;
    type?: string;
    conditions?: Record<string, unknown>;
    createdBy?: string;
    template?: string;
    parentId?: string;
    groupBy?: string;
    limit?: number;
  },
): Promise<AggregateResponse> {
  const searchParams = new URLSearchParams();
  searchParams.set("key", key);
  if (params?.tags) searchParams.set("tags", params.tags);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.type) searchParams.set("type", params.type);
  if (params?.conditions && Object.keys(params.conditions).length > 0) {
    searchParams.set("conditions", JSON.stringify(params.conditions));
  }
  if (params?.createdBy) searchParams.set("created_by", params.createdBy);
  if (params?.template) searchParams.set("template", params.template);
  if (params?.parentId) searchParams.set("parent_id", params.parentId);
  if (params?.groupBy) searchParams.set("group_by", params.groupBy);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  const res = await authFetch(
    `${API_BASE}/api/records/aggregate?${searchParams}`,
  );
  if (!res.ok) throw new Error(`Failed to aggregate: ${res.status}`);
  return res.json();
}

export async function createRecord(data: {
  title: string;
  type?: string;
  tags?: string[];
  conditions?: Record<string, unknown>;
}): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create record: ${res.status}`);
  return res.json();
}

export interface ChildConditions {
  // scatter 軸ラベルで `[unit]` を出すために、子レコードの units を同梱。
  // 通常は子が同じ template を共有するので、全子をマージして 1 つの
  // units map を作る (空でない値が勝つ)。
  id: string;
  title: string;
  conditions: Record<string, unknown>;
  results: Record<string, unknown>;
  condition_units?: Record<string, string>;
  result_units?: Record<string, string>;
}

export async function fetchChildrenConditions(
  id: string
): Promise<ChildConditions[]> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/children/conditions`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchChildren(
  id: string,
  params?: { limit?: number; offset?: number }
): Promise<RecordListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const res = await authFetch(`${API_BASE}/api/records/${id}/children?${searchParams}`);
  if (!res.ok) throw new Error(`Failed to fetch children: ${res.status}`);
  return res.json();
}

// IPython hooks 自動収集の Notebook セルログ (R13)。`/api/records/{id}/cell_logs`
// の backend schema と一致。new_vars/changed_vars/deleted_vars は変数の
// digest (type/shape/hash) のみで、生の値は含まれない。
export interface CellLogEntry {
  cell_id: string;
  record_id: string;
  cell_number: number;
  execution_count: number;
  source: string;
  source_hash: string;
  new_vars: Record<string, unknown>;
  changed_vars: Record<string, unknown>;
  deleted_vars: string[];
  duration_sec: number;
  executed_at: string | null;
  error: { type: string; message: string } | null;
  session_id: string;
}

export interface CellLogListResponse {
  items: CellLogEntry[];
  total: number;
  has_more: boolean;
}

export async function fetchCellLogs(
  id: string,
  params?: { limit?: number },
): Promise<CellLogListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  const res = await authFetch(
    `${API_BASE}/api/records/${id}/cell_logs?${searchParams}`,
  );
  if (!res.ok) throw new Error(`Failed to fetch cell logs: ${res.status}`);
  return res.json();
}

export async function addTags(
  id: string,
  tags: string[]
): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/tags`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
  if (!res.ok) throw new Error(`Failed to add tags: ${res.status}`);
  return res.json();
}

export async function updateUnits(
  id: string,
  units: Record<string, string>,
  descriptions?: Record<string, string>
): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/units`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ units, descriptions: descriptions || {} }),
  });
  if (!res.ok) throw new Error(`Failed to update units: ${res.status}`);
  return res.json();
}

export async function updateResultUnits(
  id: string,
  units: Record<string, string>,
  descriptions?: Record<string, string>
): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/result_units`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ units, descriptions: descriptions || {} }),
  });
  if (!res.ok) throw new Error(`Failed to update result units: ${res.status}`);
  return res.json();
}

export async function addNote(
  id: string,
  text: string
): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`Failed to add note: ${res.status}`);
  return res.json();
}

export async function deleteRecord(id: string): Promise<void> {
  const res = await authFetch(`${API_BASE}/api/records/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete record: ${res.status}`);
}

// --- 共有 (S1 Phase 1 / PR #84 + PR #85) ---

// S1-CQ4/11/13 (2026-06-29): 共有 role の type は SDK / backend と揃えて
// 1 つだけ定義する。``ShareLinkRole`` は ``ShareRole`` の alias として
// 残してあるが、新規 code では ``ShareRole`` を使うこと。
export type ShareRole = "viewer" | "analyst";

export interface ShareEntry {
  email: string;
  role: string;  // "viewer" | "analyst" (ShareRole)
}

export interface ShareListResponse {
  items: ShareEntry[];
}

// `GET /api/records/{id}/shares` — read 権限があれば誰でも (= team
// membership または shares 経由) 引ける。grant 主体でないユーザーが
// 自分の role を確認するのにも使う。
export async function fetchShares(id: string): Promise<ShareEntry[]> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/shares`);
  if (!res.ok) throw new Error(`Failed to fetch shares: ${res.status}`);
  const data = (await res.json()) as ShareListResponse;
  return data.items;
}

// `POST /api/records/{id}/shares` — grant 主体は record.created_by 本人 +
// team admin + super-admin。同じ email を再 grant すると role が上書き
// (role 変更にも使える)。
export async function grantShare(
  id: string,
  email: string,
  role: ShareRole,
): Promise<RecordDetail> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/shares`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, role }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Grant share failed: ${res.status} ${text}`);
  }
  return res.json();
}

// `DELETE /api/records/{id}/shares/{email}` — 存在しない email を渡しても
// 200 が返る idempotent 仕様 (UI 上の race 対策)。
export async function revokeShare(
  id: string,
  email: string,
): Promise<RecordDetail> {
  const res = await authFetch(
    `${API_BASE}/api/records/${id}/shares/${encodeURIComponent(email)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Revoke share failed: ${res.status} ${text}`);
  }
  return res.json();
}

// S1 Phase 1B: 自分宛てに共有された record を **全 team 横断** で返す。
// X-Labvault-Team header は無視されるため、ここだけは authFetch を経由
// せずに済むが、Authorization header は要るので便宜上 authFetch を使う
// (backend 側で team header があっても無視する)。
//
// 各 item の `team` を使って、frontend は detail 遷移時に currentTeam を
// 一時的に切り替える (record owner team で X-Labvault-Team を送るため)。
export interface SharedRecordSummary extends RecordSummary {
  team: string;
  role: string;  // "viewer" | "analyst" (ShareRole)
}

export interface SharedRecordListResponse {
  items: SharedRecordSummary[];
  total: number;
  has_more?: boolean;
}

// --- S1 Phase 2: 外部 token sharing (ls_*) ---

// S1-CQ11/13 (2026-06-29): 旧 ``ShareLinkRole`` は ``ShareRole`` と完全
// 同義だったので alias に降格。新規 code は ``ShareRole`` を使うこと。
// 既存 import の互換性のためここで export 維持。
export type ShareLinkRole = ShareRole;

export interface ShareLinkInfo {
  // 一覧 / revoke ハンドルは hash の先頭 16 chars。raw token は含まれない。
  token_hash_prefix: string;
  record_id: string;
  team: string;
  role: string;
  pseudo_email: string;
  pseudo_display_name: string;
  created_by: string;
  created_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  // S1-OBS9/UX5 (2026-06-29): 最終使用時刻 (auth.py で best-effort 更新)。
  // ShareLinksPanel が「最終使用: ...」を表示して dormant token 特定に使う。
  last_used_at: string | null;
  label: string;
  is_active: boolean;
}

export interface CreatedShareLink extends ShareLinkInfo {
  // 発行直後だけ含まれる raw token。再表示不可なので UI で 1 回だけ
  // クリップボードへ。
  token: string;
}

export interface ShareLinkListResponse {
  items: ShareLinkInfo[];
}

export interface ShareLinkScopeMe {
  record_id: string;
  team: string;
  role: string;
  pseudo_email: string;
  pseudo_display_name: string;
  expires_at: string | null;
  revoked_at: string | null;
}

export interface IssueShareLinkBody {
  role: ShareLinkRole;
  pseudo_email: string;
  pseudo_display_name?: string;
  label?: string;
  expires_days?: number | null;
}

// `GET /api/records/{id}/share-links` — grant 主体だけが叩ける一覧。
export async function fetchShareLinks(id: string): Promise<ShareLinkInfo[]> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/share-links`);
  if (!res.ok) throw new Error(`Failed to fetch share-links: ${res.status}`);
  const data = (await res.json()) as ShareLinkListResponse;
  return data.items;
}

// `POST /api/records/{id}/share-links` — token 発行 (raw token は 1 回限り)。
export async function issueShareLink(
  id: string,
  body: IssueShareLinkBody,
): Promise<CreatedShareLink> {
  const res = await authFetch(`${API_BASE}/api/records/${id}/share-links`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Issue share-link failed: ${res.status} ${text}`);
  }
  return res.json();
}

// --- Share event 監査 log (2026-07-01) ---
// backend: `records/{id}/share-events` — 共有 grant / revoke / share-link
// 発行・失効の永続監査 log。Cloud Logging (30 日) と併存し、Firestore
// 側は無期限保存。認可: grant 主体 (admin) だけ。

export type ShareEventType =
  | "granted"
  | "revoked"
  | "link_issued"
  | "link_revoked";

export interface ShareEventEntry {
  event_type: ShareEventType;
  record_id: string;
  role: string; // "" for revoked
  actor_email: string;
  actor_audit_source: string;
  at: string; // ISO
  target_email?: string | null;
  token_hash_prefix?: string | null;
  pseudo_email?: string | null;
  label?: string | null;
}

export interface ShareEventListResponse {
  items: ShareEventEntry[];
}

export async function fetchShareEvents(
  id: string,
  opts?: { limit?: number },
): Promise<ShareEventEntry[]> {
  const params = new URLSearchParams();
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const url = `${API_BASE}/api/records/${id}/share-events${qs ? "?" + qs : ""}`;
  const res = await authFetch(url);
  if (!res.ok) throw new Error(`Failed to fetch share events: ${res.status}`);
  const data = (await res.json()) as ShareEventListResponse;
  return data.items;
}

// `DELETE /api/records/{id}/share-links/{token_hash_prefix}` — revoke。
export async function revokeShareLink(
  id: string,
  tokenHashPrefix: string,
): Promise<void> {
  const res = await authFetch(
    `${API_BASE}/api/records/${id}/share-links/${encodeURIComponent(tokenHashPrefix)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Revoke share-link failed: ${res.status} ${text}`);
  }
}

// 公開 ``/share/<record_id>#<token>`` ページ用: fragment から取り出した
// token を Authorization header に詰めて自身の scope を取得する。
// `authFetch` は使わず raw fetch (Firebase auth 経路を bypass)。
// Phase D1 (2026-06-30): URL fragment 化に伴い旧 ``/share/<token>`` 形式
// は client-side で新形式に redirect。本関数の入出力は変わらない。
export async function fetchShareLinkScope(
  token: string,
): Promise<ShareLinkScopeMe> {
  const res = await fetch(`${API_BASE}/api/share-links/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to verify share-link: ${res.status}`);
  }
  return res.json();
}

// 公開ページ用の汎用 fetcher。token を渡すだけで Authorization を付ける。
export async function shareTokenFetch(
  token: string,
  url: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...init, headers });
}


export async function fetchSharedWithMe(params?: {
  limit?: number;
  offset?: number;
}): Promise<SharedRecordListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  const url = qs
    ? `${API_BASE}/api/records/shared-with-me?${qs}`
    : `${API_BASE}/api/records/shared-with-me`;
  const res = await authFetch(url);
  if (!res.ok) throw new Error(`Failed to fetch shared records: ${res.status}`);
  return res.json();
}

// --- signup / admin ---

export interface RequestAccessResult {
  status: string; // "pending" | "already_allowed"
  email: string;
  requested_team_name: string;
}

export async function requestAccess(
  requested_team_name: string,
  note: string = "",
): Promise<RequestAccessResult> {
  const res = await authFetch(`${API_BASE}/api/auth/request-access`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ requested_team_name, note }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Request access failed: ${res.status} ${text}`);
  }
  return res.json();
}

export interface PendingUser {
  email: string;
  display_name: string;
  requested_team_name: string;
  note: string;
  created_at: string | null;
}

export async function fetchPendingUsers(): Promise<PendingUser[]> {
  const res = await authFetch(`${API_BASE}/api/admin/pending`);
  if (!res.ok) throw new Error(`Failed to fetch pending: ${res.status}`);
  const data = (await res.json()) as { items: PendingUser[] };
  return data.items;
}

export interface ApproveBody {
  email: string;
  action: "create_team" | "assign";
  role: "admin" | "member" | "viewer";
  team_id?: string; // assign のみ
  new_team?: {
    team_id: string;
    name: string;
    nextcloud_group_folder: string;
  }; // create_team のみ
}

export async function approveUser(
  body: ApproveBody,
): Promise<{ status: string; email: string; team_id: string }> {
  const res = await authFetch(`${API_BASE}/api/admin/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Approve failed: ${res.status} ${text}`);
  }
  return res.json();
}

// --- admin: user / team management ---

export type TeamRole = "admin" | "member" | "viewer";

export interface UserTeamMembership {
  team_id: string;
  role: string;
  name: string;
}

export interface AllowedUserSummary {
  email: string;
  display_name: string;
  role: string; // legacy global
  teams: UserTeamMembership[];
  default_team: string;
  active: boolean;
  created_at: string | null;
  last_login_at: string | null;
  // null=試行記録なし、true=AR grant 成功 (or 既に付与済)、false=失敗。
  // false の場合 admin UI は「再付与」ボタンを表示する。
  ar_granted: boolean | null;
}

export async function fetchAllowedUsers(): Promise<AllowedUserSummary[]> {
  const res = await authFetch(`${API_BASE}/api/admin/users`);
  if (!res.ok) throw new Error(`Failed to fetch users: ${res.status}`);
  const data = (await res.json()) as { items: AllowedUserSummary[] };
  return data.items;
}

export interface TeamSummary {
  team_id: string;
  name: string;
  nextcloud_group_folder: string;
}

export async function fetchAllTeams(): Promise<TeamSummary[]> {
  const res = await authFetch(`${API_BASE}/api/admin/teams`);
  if (!res.ok) throw new Error(`Failed to fetch teams: ${res.status}`);
  const data = (await res.json()) as { items: TeamSummary[] };
  return data.items;
}

export interface UserTeamsResult {
  status: string;
  email: string;
  teams: UserTeamMembership[];
  default_team: string;
}

export async function addUserTeam(
  email: string,
  team_id: string,
  role: TeamRole,
): Promise<UserTeamsResult> {
  const res = await authFetch(
    `${API_BASE}/api/admin/users/${encodeURIComponent(email)}/teams`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ team_id, role }),
    },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Add team failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function removeUserTeam(
  email: string,
  team_id: string,
): Promise<UserTeamsResult> {
  const res = await authFetch(
    `${API_BASE}/api/admin/users/${encodeURIComponent(email)}/teams/${encodeURIComponent(team_id)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Remove team failed: ${res.status} ${text}`);
  }
  return res.json();
}

export interface UpdateUserBody {
  active?: boolean;
  display_name?: string;
}

export async function updateUser(
  email: string,
  body: UpdateUserBody,
): Promise<AllowedUserSummary> {
  const res = await authFetch(
    `${API_BASE}/api/admin/users/${encodeURIComponent(email)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Update user failed: ${res.status} ${text}`);
  }
  return res.json();
}

export const setUserActive = (email: string, active: boolean) =>
  updateUser(email, { active });

export interface GrantArResult {
  status: string;
  email: string;
  ar_granted: boolean;
}

export async function grantAr(email: string): Promise<GrantArResult> {
  const res = await authFetch(
    `${API_BASE}/api/admin/users/${encodeURIComponent(email)}/ar/grant`,
    { method: "POST" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`AR grant failed: ${res.status} ${text}`);
  }
  return res.json();
}

// --- Personal Access Tokens (PAT) ---

export interface TokenSummary {
  id: string;
  label: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface CreatedToken {
  id: string;
  label: string;
  token: string; // raw, only present at creation time
  prefix: string;
  created_at: string;
}

export async function createToken(label: string): Promise<CreatedToken> {
  const res = await authFetch(`${API_BASE}/api/auth/tokens`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Create token failed: ${res.status} ${text}`);
  }
  return res.json();
}

export async function listTokens(): Promise<TokenSummary[]> {
  const res = await authFetch(`${API_BASE}/api/auth/tokens`);
  if (!res.ok) throw new Error(`Failed to list tokens: ${res.status}`);
  const data = (await res.json()) as { items: TokenSummary[] };
  return data.items;
}

export async function revokeToken(id: string): Promise<void> {
  const res = await authFetch(
    `${API_BASE}/api/auth/tokens/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Revoke token failed: ${res.status} ${text}`);
  }
}

/**
 * 現 team の template から indexed_fields の union を取得する。
 * 条件 chip の key 候補 (push down 可能な key) として WebUI で suggest する。
 *
 * 失敗時は空配列を返す (chip 自体は自由入力で使えるためフェイルクローズ)。
 */
export async function fetchIndexedFieldSuggestions(): Promise<string[]> {
  try {
    const res = await authFetch(`${API_BASE}/api/metadata/templates`);
    if (!res.ok) return [];
    const templates = (await res.json()) as Array<{
      indexed_fields?: string[];
    }>;
    const all = new Set<string>();
    for (const t of templates) {
      for (const k of t.indexed_fields ?? []) {
        if (typeof k === "string") all.add(k);
      }
    }
    return Array.from(all).sort();
  } catch {
    return [];
  }
}

// D4: 指定 template の result_fields のうち `required=true` の key を
// 宣言順で返す。StatsPanel の初期表示 (template 紐付き record 用) に使う。
// `/api/metadata/templates` の raw dict を直接 filter する (template 名 1
// 件用の専用 endpoint は無くても済む)。
export async function fetchTemplateRequiredResultKeys(
  templateName: string,
): Promise<string[]> {
  try {
    const res = await authFetch(`${API_BASE}/api/metadata/templates`);
    if (!res.ok) return [];
    const templates = (await res.json()) as Array<{
      name?: string;
      result_fields?: Array<{ name?: string; required?: boolean }>;
    }>;
    const tpl = templates.find((t) => t.name === templateName);
    if (!tpl) return [];
    return (tpl.result_fields ?? [])
      .filter((rf) => rf.required && typeof rf.name === "string")
      .map((rf) => rf.name as string);
  } catch {
    return [];
  }
}
