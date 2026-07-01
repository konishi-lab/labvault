"""InMemory バックエンド実装 (テスト用).

Firestore との完全互換ではない。テストでは API の呼び出し契約を検証する。
"""

from __future__ import annotations

import copy
from typing import Any


class InMemoryMetadataBackend:
    """メタデータのインメモリ実装。"""

    def __init__(self) -> None:
        self._records: dict[str, dict[str, dict[str, Any]]] = {}
        self._cell_logs: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._templates: dict[str, dict[str, dict[str, Any]]] = {}
        # {team: [event, ...]}. record 単位の filter は list_share_events で。
        self._share_events: dict[str, list[dict[str, Any]]] = {}

    # --- Record CRUD ---

    def create_record(self, team: str, data: dict[str, Any]) -> None:
        self._records.setdefault(team, {})[data["id"]] = copy.deepcopy(data)

    def get_record(self, team: str, record_id: str) -> dict[str, Any] | None:
        record = self._records.get(team, {}).get(record_id)
        return copy.deepcopy(record) if record else None

    def update_record(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        existing = self._records.get(team, {}).get(record_id)
        if existing is None:
            return
        existing.update(copy.deepcopy(data))

    def delete_record(self, team: str, record_id: str) -> None:
        self._records.get(team, {}).pop(record_id, None)
        self._cell_logs.get(team, {}).pop(record_id, None)

    def list_records(
        self,
        team: str,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        record_type: str | None = None,
        created_by: str | None = None,
        parent_id: str | None | object = "__unset__",
        conditions: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        records = list(self._records.get(team, {}).values())

        # deleted 除外
        records = [r for r in records if r.get("deleted_at") is None]

        if tags:
            records = [r for r in records if any(t in r.get("tags", []) for t in tags)]
        if status:
            records = [r for r in records if r.get("status") == status]
        if record_type:
            records = [r for r in records if r.get("type") == record_type]
        if created_by:
            records = [r for r in records if r.get("created_by") == created_by]
        # parent_id フィルタ (Firestore backend と signature を揃える)。
        # "__unset__" sentinel は「フィルタ無し」、None は「root only」。
        if parent_id != "__unset__":
            records = [r for r in records if r.get("parent_id") == parent_id]
        # top-level field の等値フィルタ (idx_* を想定)。Firestore の where と
        # 振る舞いを揃えるため、key が record に無ければ無条件で除外する。
        if conditions:
            for key, value in conditions.items():
                records = [r for r in records if r.get(key) == value]

        # updated_at 降順ソート
        records.sort(key=lambda r: r.get("updated_at", ""), reverse=True)

        return copy.deepcopy(records[offset : offset + limit])

    def list_records_shared_with(
        self,
        email: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """email に共有された record を全 team 横断で返す。"""
        target = (email or "").strip().lower()
        if not target:
            return []
        results: list[dict[str, Any]] = []
        for records in self._records.values():
            for r in records.values():
                if r.get("deleted_at") is not None:
                    continue
                shared = r.get("shared_with_emails") or []
                if target in shared:
                    results.append(r)
        results.sort(key=lambda r: r.get("updated_at", ""), reverse=True)
        return copy.deepcopy(results[offset : offset + limit])

    # --- CellLog ---

    def save_cell_log(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        logs = self._cell_logs.setdefault(team, {}).setdefault(record_id, [])
        logs.append(copy.deepcopy(data))

    def get_cell_logs(
        self, team: str, record_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        # Firestore backend は cell_number 昇順で返す (firestore.py:148)。
        # SDK / Web / MCP の callers はその順序を前提にしているので、
        # InMemory も同じ contract に揃える (テスト経路で挿入順がバラつ
        # いた場合に Firestore と挙動差が出るのを防ぐ)。
        logs = self._cell_logs.get(team, {}).get(record_id, [])
        sorted_logs = sorted(logs, key=lambda d: d.get("cell_number", 0))
        return copy.deepcopy(sorted_logs[:limit])

    # --- Template ---

    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None:
        self._templates.setdefault(team, {})[name] = copy.deepcopy(data)

    def get_template(self, team: str, name: str) -> dict[str, Any] | None:
        tmpl = self._templates.get(team, {}).get(name)
        return copy.deepcopy(tmpl) if tmpl else None

    def list_templates(self, team: str) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self._templates.get(team, {}).values()))

    # --- Share event 監査 log (2026-07-01) ---

    def append_share_event(self, team: str, event: dict[str, Any]) -> None:
        self._share_events.setdefault(team, []).append(copy.deepcopy(event))

    def list_share_events(
        self,
        team: str,
        record_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = [
            e
            for e in self._share_events.get(team, [])
            if e.get("record_id") == record_id
        ]
        # 新しい順 (at DESC)。at は datetime or ISO string を想定。
        events.sort(key=lambda e: e.get("at") or "", reverse=True)
        return copy.deepcopy(events[:limit])


class InMemoryStorageBackend:
    """バイナリストレージのインメモリ実装。"""

    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    def upload(self, path: str, data: bytes, content_type: str = "") -> str:
        self._files[path] = data
        return path

    def download(self, path: str) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(f"File not found: {path}")
        return self._files[path]

    def delete(self, path: str) -> None:
        self._files.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self._files

    def list_files(self, prefix: str) -> list[str]:
        return sorted(p for p in self._files if p.startswith(prefix))


class InMemorySearchBackend:
    """検索のインメモリ実装。部分文字列一致。

    Firestore Vector Search とはセマンティクスが異なる。
    テストでは API の呼び出し契約と基本フィルタを検証する。

    filters の `idx_*` 等の任意 key は post-filter で扱えないため、テストでは
    Lab.search の post-filter 側のパスでカバーすること。
    """

    def __init__(self) -> None:
        self._index: dict[str, dict[str, str]] = {}

    def index(
        self,
        team: str,
        record_id: str,
        text: str,
        embedding: list[float] | None = None,
    ) -> None:
        self._index.setdefault(team, {})[record_id] = text

    def search(
        self,
        team: str,
        query: str,
        *,
        embedding: list[float] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record_id, text in self._index.get(team, {}).items():
            if query.lower() in text.lower():
                results.append({"record_id": record_id, "text": text, "score": 1.0})
        return results[:limit]

    def delete_index(self, team: str, record_id: str) -> None:
        self._index.get(team, {}).pop(record_id, None)
