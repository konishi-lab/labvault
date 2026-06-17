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
