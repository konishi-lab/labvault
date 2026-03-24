"""Backend Protocol 定義。全メソッド sync。"""

from __future__ import annotations

from typing import Any, Protocol


class MetadataBackend(Protocol):
    """メタデータストアの抽象。Firestore / InMemory。"""

    def create_record(self, team: str, data: dict[str, Any]) -> None: ...

    def get_record(self, team: str, record_id: str) -> dict[str, Any] | None: ...

    def update_record(
        self, team: str, record_id: str, data: dict[str, Any]
    ) -> None: ...

    def delete_record(self, team: str, record_id: str) -> None: ...

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
    ) -> list[dict[str, Any]]: ...

    def save_cell_log(
        self, team: str, record_id: str, data: dict[str, Any]
    ) -> None: ...

    def get_cell_logs(
        self, team: str, record_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None: ...

    def get_template(self, team: str, name: str) -> dict[str, Any] | None: ...

    def list_templates(self, team: str) -> list[dict[str, Any]]: ...


class StorageBackend(Protocol):
    """バイナリストレージの抽象。Nextcloud / InMemory。"""

    def upload(self, path: str, data: bytes, content_type: str = "") -> str: ...

    def download(self, path: str) -> bytes: ...

    def delete(self, path: str) -> None: ...

    def exists(self, path: str) -> bool: ...

    def list_files(self, prefix: str) -> list[str]: ...


class SearchBackend(Protocol):
    """検索エンジンの抽象。Firestore Vector Search / InMemory。"""

    def index(
        self,
        team: str,
        record_id: str,
        text: str,
        embedding: list[float] | None = None,
    ) -> None: ...

    def search(
        self,
        team: str,
        query: str,
        *,
        embedding: list[float] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...

    def delete_index(self, team: str, record_id: str) -> None: ...
