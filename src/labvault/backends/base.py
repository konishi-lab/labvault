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
        conditions: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """レコード一覧を取得する。

        Args:
            conditions: top-level field の等値フィルタ (key → value)。
                呼び出し側 (Lab.search / Lab.list) が `idx_<key>` の prefix を
                付けて渡すことで、template の indexed_fields を Firestore の
                where 句に push down する。値は scalar (str/int/float/bool) のみ
                想定。範囲指定や dict 値は post-filter で扱う。
        """
        ...

    def list_records_shared_with(
        self,
        email: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """email に共有された record を **全 team 横断** で返す (S1 / 共有機能).

        従来の `list_records` は team を必須引数に取るが、共有された側のユー
        ザーから「自分に共有された全 record」を引きたいときは team 単位で
        分けない方が自然なので、専用の cross-team query を Protocol に置く。

        Firestore 実装は `collection_group('records')` で全 team を走査し、
        `shared_with_emails` array-contains で絞る。InMemory 実装は内部の
        全 team 辞書を線形スキャンする。返り値の各 record dict には
        `team` field が入っている (record 詳細を取り直す際に X-Labvault-Team
        を組み立てるため)。
        """
        ...

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
