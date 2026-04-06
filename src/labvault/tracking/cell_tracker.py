"""CellTracker -- IPython hooks によるセル自動記録。"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from labvault.tracking.namespace import capture_namespace, diff_namespaces

if TYPE_CHECKING:
    from labvault.core.lab import Lab
    from labvault.core.record import Record

logger = logging.getLogger(__name__)


def _get_ipython_shell() -> Any | None:
    """IPython shell を取得する。IPython 環境でなければ None。"""
    try:
        from IPython import get_ipython  # type: ignore[attr-defined]

        return get_ipython()  # type: ignore[no-untyped-call]
    except ImportError:
        return None


def _get_session_id() -> str:
    """notebook名 + kernel ID でセッションを識別する。"""
    shell = _get_ipython_shell()
    if shell is None:
        return f"script:{uuid.uuid4().hex[:8]}"

    # Jupyter kernel の場合
    kernel_id = ""
    try:
        import ipykernel.connect

        raw_info = ipykernel.connect.get_connection_info()
        info = raw_info if isinstance(raw_info, dict) else {}
        key = info.get("key", b"")
        if isinstance(key, bytes):
            kernel_id = key.decode("utf-8", errors="ignore")[:8]
        else:
            kernel_id = str(key)[:8]
    except Exception:
        kernel_id = uuid.uuid4().hex[:8]

    # Notebook 名の取得 (ベストエフォート)
    notebook_name = "unknown"
    try:
        # ipykernel >= 6 + jupyter_client
        if hasattr(shell, "kernel") and hasattr(shell.kernel, "session"):
            notebook_name = getattr(shell.kernel, "_notebook_name", "notebook")
    except Exception:
        pass

    return f"{notebook_name}:{kernel_id}"


class CellTracker:
    """IPython のセル実行を自動記録する。

    pre_run_cell で namespace スナップショットを取り、
    post_run_cell で差分を CellLog として保存する。
    """

    def __init__(self, record: Record, lab: Lab) -> None:
        self._record = record
        self._lab = lab
        self._shell: Any | None = None
        self._active = False
        self._paused = False
        self._cell_number = 0
        self._session_id = _get_session_id()
        self._before_ns: dict[str, tuple[int, str]] = {}
        self._cell_start_time: float = 0.0

    @property
    def paused(self) -> bool:
        """一時停止中かどうか。"""
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        self._paused = value

    def activate(self) -> None:
        """IPython hooks を登録する。"""
        shell = _get_ipython_shell()
        if shell is None:
            logger.debug("Not in IPython environment, skipping activation")
            return

        self._shell = shell
        shell.events.register("pre_run_cell", self._pre_run_cell)
        shell.events.register("post_run_cell", self._post_run_cell)
        self._active = True
        logger.debug("CellTracker activated for record %s", self._record.id)

    def deactivate(self) -> None:
        """IPython hooks を解除する。"""
        if not self._active or self._shell is None:
            return

        try:
            self._shell.events.unregister("pre_run_cell", self._pre_run_cell)
            self._shell.events.unregister("post_run_cell", self._post_run_cell)
        except ValueError:
            pass

        self._active = False
        logger.debug("CellTracker deactivated for record %s", self._record.id)

    def _pre_run_cell(self, info: Any) -> None:
        """セル実行前: namespace スナップショットを取る。"""
        if self._paused or self._shell is None:
            return

        self._before_ns = capture_namespace(self._shell.user_ns)
        self._cell_start_time = time.monotonic()

    def _post_run_cell(self, result: Any) -> None:
        """セル実行後: 差分を計算して CellLog を保存する。"""
        if self._paused or self._shell is None:
            return

        duration = time.monotonic() - self._cell_start_time
        after_ns = capture_namespace(self._shell.user_ns)
        new_vars, changed_vars, deleted_vars = diff_namespaces(
            self._before_ns, after_ns
        )

        self._cell_number += 1

        # エラー情報
        error_info: dict[str, Any] | None = None
        if result.error_in_exec is not None:
            exc = result.error_in_exec
            error_info = {
                "type": type(exc).__name__,
                "message": str(exc),
            }

        # ソースコード
        source = ""
        if hasattr(result, "info") and hasattr(result.info, "raw_cell"):
            source = result.info.raw_cell
        elif hasattr(result, "info"):
            source = getattr(result.info, "cell", "")

        execution_count = getattr(self._shell, "execution_count", 0)

        cell_log = {
            "cell_id": uuid.uuid4().hex,
            "record_id": self._record.id,
            "cell_number": self._cell_number,
            "execution_count": execution_count,
            "source": source,
            "source_hash": hashlib.sha256(source.encode()).hexdigest()[:16],
            "new_vars": new_vars,
            "changed_vars": changed_vars,
            "deleted_vars": deleted_vars,
            "duration_sec": round(duration, 4),
            "executed_at": datetime.now(_dt.UTC).isoformat(),
            "error": error_info,
            "session_id": self._session_id,
        }

        try:
            self._lab._metadata.save_cell_log(
                self._record.team,
                self._record.id,
                cell_log,
            )
        except Exception:
            logger.exception("Failed to save cell log")
