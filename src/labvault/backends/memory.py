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

        # updated_at 降順ソート
        records.sort(key=lambda r: r.get("updated_at", ""), reverse=True)

        return copy.deepcopy(records[offset : offset + limit])

    # --- CellLog ---

    def save_cell_log(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        logs = self._cell_logs.setdefault(team, {}).setdefault(record_id, [])
        logs.append(copy.deepcopy(data))

    def get_cell_logs(
        self, team: str, record_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        logs = self._cell_logs.get(team, {}).get(record_id, [])
        return copy.deepcopy(logs[:limit])

    # --- Template ---

    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None:
        self._templates.setdefault(team, {})[name] = copy.deepcopy(data)

    def get_template(self, team: str, name: str) -> dict[str, Any] | None:
        tmpl = self._templates.get(team, {}).get(name)
        return copy.deepcopy(tmpl) if tmpl else None

    def list_templates(self, team: str) -> list[dict[str, Any]]:
        return copy.deepcopy(list(self._templates.get(team, {}).values()))


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
