"""SyncManager -- バッファからリモートへの自動同期。"""

from __future__ import annotations

import atexit
import json
import logging
import threading
import time
import warnings
import weakref
from typing import Any

from labvault.buffer.database import BufferDatabase

logger = logging.getLogger(__name__)


class SyncManager:
    """BufferDatabase のペンディングアイテムをリモートに同期する。

    - daemon スレッドで定期的に同期
    - atexit で安全にフラッシュ
    - エラー時は次回再試行
    """

    def __init__(
        self,
        buffer_db: BufferDatabase,
        metadata_backend: Any,
        storage_backend: Any,
        *,
        interval_sec: float = 30.0,
        batch_size: int = 10,
    ) -> None:
        self._buffer = buffer_db
        self._metadata = metadata_backend
        self._storage = storage_backend
        self._interval = interval_sec
        self._batch_size = batch_size

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_error: str | None = None
        self._last_sync_time: float = 0.0

        # atexit 登録 (weakref で循環参照回避)
        ref = weakref.ref(self)

        def _cleanup() -> None:
            obj = ref()
            if obj is not None:
                obj._flush_on_exit()

        atexit.register(_cleanup)

    def start(self) -> None:
        """同期スレッドを開始する。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sync_loop,
            name="labvault-sync",
            daemon=True,
        )
        self._thread.start()
        logger.debug("SyncManager started (interval=%ss)", self._interval)

    def stop(self, *, flush: bool = True) -> None:
        """同期スレッドを停止する。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if flush:
            self._do_sync()
        logger.debug("SyncManager stopped")

    def sync_now(self) -> None:
        """即時同期を実行する。"""
        self._do_sync()

    @property
    def sync_status(self) -> dict[str, Any]:
        """同期状態を返す。"""
        pending = (
            len(self._buffer.get_pending_records(limit=1000))
            + len(self._buffer.get_pending_files(limit=1000))
            + len(self._buffer.get_pending_cell_logs(limit=1000))
        )
        return {
            "pending": pending,
            "last_error": self._last_error,
            "last_sync": self._last_sync_time,
            "is_running": (self._thread is not None and self._thread.is_alive()),
        }

    def _sync_loop(self) -> None:
        """バックグラウンド同期ループ。"""
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._interval)
            if not self._stop_event.is_set():
                self._do_sync()

    def _do_sync(self) -> None:
        """ペンディングアイテムを同期する。"""
        try:
            self._sync_records()
            self._sync_cell_logs()
            self._last_error = None
            self._last_sync_time = time.time()
        except Exception as e:
            self._last_error = str(e)
            logger.warning("Sync error: %s", e)
            warnings.warn(
                f"labvault sync error: {e}",
                stacklevel=2,
            )

    def _sync_records(self) -> None:
        """ペンディングレコードを同期する。"""
        pending = self._buffer.get_pending_records(limit=self._batch_size)
        if not pending:
            return

        synced_ids: list[int | str] = []
        for row in pending:
            data = json.loads(row["data"])
            team = row["team"]
            record_id = row["id"]
            self._metadata.update_record(team, record_id, data)
            synced_ids.append(record_id)

        self._buffer.mark_synced("pending_records", synced_ids)

    def _sync_cell_logs(self) -> None:
        """ペンディングセルログを同期する。"""
        pending = self._buffer.get_pending_cell_logs(limit=self._batch_size)
        if not pending:
            return

        synced_ids: list[int | str] = []
        for row in pending:
            data = json.loads(row["data"])
            team = row["team"]
            record_id = row["record_id"]
            self._metadata.save_cell_log(team, record_id, data)
            synced_ids.append(row["id"])

        self._buffer.mark_synced("pending_cell_logs", synced_ids)

    def _flush_on_exit(self) -> None:
        """プロセス終了時のフラッシュ。"""
        import contextlib

        with contextlib.suppress(Exception):
            self._do_sync()
