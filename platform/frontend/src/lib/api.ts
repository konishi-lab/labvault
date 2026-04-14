const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RecordSummary {
  id: string;
  title: string;
  type: string;
  status: string;
  tags: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
  parent_id: string | null;
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
}

export interface RecordDetail extends RecordSummary {
  conditions: Record<string, unknown>;
  condition_units: Record<string, string>;
  condition_descriptions: Record<string, string>;
  results: Record<string, unknown>;
  notes: NoteResponse[];
  files: FileInfo[];
  links: LinkResponse[];
  events: Record<string, unknown>[];
}

export interface RecordListResponse {
  items: RecordSummary[];
  total: number;
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
  limit?: number;
  offset?: number;
}): Promise<RecordListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.tags) searchParams.set("tags", params.tags);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.type) searchParams.set("type", params.type);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));

  const res = await fetch(`${API_BASE}/api/records?${searchParams}`);
  if (!res.ok) throw new Error(`Failed to fetch records: ${res.status}`);
  return res.json();
}

export async function fetchRecord(id: string): Promise<RecordDetail> {
  const res = await fetch(`${API_BASE}/api/records/${id}`);
  if (!res.ok) throw new Error(`Failed to fetch record: ${res.status}`);
  return res.json();
}

export async function searchRecords(
  query: string,
  params?: { tags?: string; status?: string; type?: string; limit?: number }
): Promise<RecordSummary[]> {
  const searchParams = new URLSearchParams();
  if (query) searchParams.set("q", query);
  if (params?.tags) searchParams.set("tags", params.tags);
  if (params?.status) searchParams.set("status", params.status);
  if (params?.type) searchParams.set("type", params.type);
  if (params?.limit) searchParams.set("limit", String(params.limit));

  const res = await fetch(`${API_BASE}/api/search?${searchParams}`);
  if (!res.ok) throw new Error(`Failed to search: ${res.status}`);
  return res.json();
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error(`Failed to fetch health: ${res.status}`);
  return res.json();
}

export async function createRecord(data: {
  title: string;
  type?: string;
  tags?: string[];
  conditions?: Record<string, unknown>;
}): Promise<RecordDetail> {
  const res = await fetch(`${API_BASE}/api/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`Failed to create record: ${res.status}`);
  return res.json();
}

export async function fetchChildrenConditions(
  id: string
): Promise<{ id: string; title: string; conditions: Record<string, unknown> }[]> {
  const res = await fetch(`${API_BASE}/api/records/${id}/children/conditions`);
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
  const res = await fetch(`${API_BASE}/api/records/${id}/children?${searchParams}`);
  if (!res.ok) throw new Error(`Failed to fetch children: ${res.status}`);
  return res.json();
}

export async function addTags(
  id: string,
  tags: string[]
): Promise<RecordDetail> {
  const res = await fetch(`${API_BASE}/api/records/${id}/tags`, {
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
  const res = await fetch(`${API_BASE}/api/records/${id}/units`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ units, descriptions: descriptions || {} }),
  });
  if (!res.ok) throw new Error(`Failed to update units: ${res.status}`);
  return res.json();
}

export async function addNote(
  id: string,
  text: string
): Promise<RecordDetail> {
  const res = await fetch(`${API_BASE}/api/records/${id}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) throw new Error(`Failed to add note: ${res.status}`);
  return res.json();
}

export async function deleteRecord(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/records/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete record: ${res.status}`);
}
