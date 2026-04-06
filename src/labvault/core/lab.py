"""Lab クラス -- チームデータベースのエントリポイント。"""

from __future__ import annotations

import builtins
import datetime as _dt
from datetime import datetime
from typing import Any

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.config import Settings
from labvault.core.exceptions import RecordNotFoundError
from labvault.core.id import generate_id
from labvault.core.record import Record
from labvault.core.types import RecordType, Status


class Lab:
    """チームデータベース。Record の生成・取得・検索を行う。"""

    def __init__(
        self,
        team: str | None = None,
        *,
        user: str | None = None,
        metadata_backend: Any | None = None,
        storage_backend: Any | None = None,
        search_backend: Any | None = None,
    ) -> None:
        settings = Settings()
        self._team = team or settings.team or "default"
        self._user = user or settings.user or ""
        self._metadata = metadata_backend or InMemoryMetadataBackend()
        self._storage = storage_backend or InMemoryStorageBackend()
        self._search = search_backend or InMemorySearchBackend()
        self._settings = settings
        self._active_tracker: Any | None = None

    # --- Record 生成 ---

    def new(
        self,
        title: str,
        *,
        type: str | RecordType = RecordType.EXPERIMENT,
        template: str | None = None,
        tags: list[str] | None = None,
        sample: str | None = None,
        auto_log: bool = True,
        **conditions: Any,
    ) -> Record:
        """新しいレコードを作成する。

        Args:
            title: レコードタイトル。
            type: レコードタイプ。
            template: テンプレート名 (M2 以降)。
            tags: 初期タグ。
            sample: サンプルレコード ID (link 自動追加)。
            auto_log: IPython hooks 有効化 (M2 以降)。
            **conditions: 実験条件。
        """
        record_id = self._generate_unique_id()
        record_type = str(type)

        rec = Record(
            id=record_id,
            team=self._team,
            title=title,
            record_type=record_type,
            status=Status.RUNNING,
            created_by=self._user,
            tags=tags,
            conditions_data=conditions if conditions else None,
            lab=self,
        )

        self._metadata.create_record(self._team, rec._to_dict())

        # 検索インデックスに追加
        self._search.index(self._team, record_id, title)

        if sample:
            rec.link(sample, "measured_on")

        # template は M3 以降で実装
        _ = template

        if auto_log:
            self._activate_tracker(rec)

        return rec

    # --- Record 取得 ---

    def get(
        self,
        record_id: str,
        *,
        auto_log: bool = False,
    ) -> Record:
        """ID でレコードを取得する。

        Args:
            record_id: レコード ID。
            auto_log: IPython hooks を再起動 (M2 以降)。

        Raises:
            RecordNotFoundError: レコードが見つからない。
        """
        from labvault.core.id import normalize_id

        rid = normalize_id(record_id)
        data = self._metadata.get_record(self._team, rid)
        if data is None:
            raise RecordNotFoundError(rid)

        rec = Record._from_dict(data, lab=self)

        if auto_log:
            self._activate_tracker(rec)

        return rec

    # --- 一覧 ---

    def list(
        self,
        *,
        tags: builtins.list[str] | None = None,
        status: str | Status | None = None,
        type: str | RecordType | None = None,
        created_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> builtins.list[Record]:
        """レコード一覧を取得する。"""
        status_str = str(status) if status else None
        type_str = str(type) if type else None

        rows = self._metadata.list_records(
            self._team,
            tags=tags,
            status=status_str,
            record_type=type_str,
            created_by=created_by,
            limit=limit,
            offset=offset,
        )
        return [Record._from_dict(r, lab=self) for r in rows]

    def recent(self, n: int = 10) -> builtins.list[Record]:
        """最新 n 件を返す。"""
        return self.list(limit=n)

    def today(self) -> builtins.list[Record]:
        """今日作成されたレコードを返す。"""
        now = datetime.now(_dt.UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        all_records = self.list(limit=1000)
        return [r for r in all_records if r.created_at >= start]

    # --- 検索 ---

    def search(
        self,
        query: str,
        *,
        tags: builtins.list[str] | None = None,
        status: str | Status | None = None,
        type: str | RecordType | None = None,
        limit: int = 20,
    ) -> builtins.list[Record]:
        """レコードを検索する (M1: 部分文字列一致)."""
        filters: dict[str, Any] = {}
        if tags:
            filters["tags"] = tags
        if status:
            filters["status"] = str(status)
        if type:
            filters["type"] = str(type)

        hits = self._search.search(
            self._team,
            query,
            filters=filters if filters else None,
            limit=limit,
        )
        results: builtins.list[Record] = []
        for hit in hits:
            rid = hit["record_id"]
            data = self._metadata.get_record(self._team, rid)
            if data and data.get("deleted_at") is None:
                results.append(Record._from_dict(data, lab=self))
        return results

    # --- 削除 / 復元 ---

    def delete(self, record_id: str) -> None:
        """ソフトデリート (deleted_at を設定)."""
        from labvault.core.id import normalize_id

        rid = normalize_id(record_id)
        data = self._metadata.get_record(self._team, rid)
        if data is None:
            raise RecordNotFoundError(rid)

        data["deleted_at"] = datetime.now(_dt.UTC).isoformat()
        self._metadata.update_record(self._team, rid, data)

    def trash(self) -> builtins.list[Record]:
        """削除済みレコードを返す。"""
        # list_records は deleted_at 非 None を除外するため、
        # InMemory の内部 _records を直接参照する (M1 簡易実装)。
        results: builtins.list[Record] = []
        if hasattr(self._metadata, "_records"):
            team_records = self._metadata._records.get(self._team, {})
            for data in team_records.values():
                if data.get("deleted_at") is not None:
                    results.append(Record._from_dict(data, lab=self))
        return results

    def restore(self, record_id: str) -> Record:
        """削除を取り消す。"""
        from labvault.core.id import normalize_id

        rid = normalize_id(record_id)

        # 削除済みも含めて取得する必要がある
        data: dict[str, Any] | None = None
        if hasattr(self._metadata, "_records"):
            data = self._metadata._records.get(self._team, {}).get(rid)

        if data is None:
            data = self._metadata.get_record(self._team, rid)

        if data is None:
            raise RecordNotFoundError(rid)

        data["deleted_at"] = None
        self._metadata.update_record(self._team, rid, data)

        return Record._from_dict(data, lab=self)

    # --- コンテキストマネージャ ---

    def close(self) -> None:
        """リソースを解放する。"""
        if self._active_tracker is not None:
            self._active_tracker.deactivate()
            self._active_tracker = None

    def __enter__(self) -> Lab:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    # --- ヘルパー ---

    def _generate_unique_id(self, max_attempts: int = 100) -> str:
        """衝突チェック付き ID 生成。"""
        for _ in range(max_attempts):
            rid = generate_id()
            if self._metadata.get_record(self._team, rid) is None:
                return rid
        msg = "Failed to generate unique ID"
        raise RuntimeError(msg)

    def _activate_tracker(self, record: Record) -> None:
        """CellTracker を起動する (IPython 環境の場合のみ)."""
        from labvault.tracking.cell_tracker import CellTracker

        if self._active_tracker is not None:
            self._active_tracker.deactivate()

        tracker = CellTracker(record, self)
        tracker.activate()

        if tracker._active:
            self._active_tracker = tracker

    def __repr__(self) -> str:
        return f"Lab(team={self._team!r})"
