"""CellTracker のテスト。

IPython 環境をモックして hooks の登録・CellLog 保存をテストする。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab
from labvault.tracking.cell_tracker import CellTracker


@pytest.fixture()
def lab():
    return Lab(
        "test-team",
        user="tester",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


@pytest.fixture()
def mock_shell():
    """IPython shell のモック。"""
    shell = MagicMock()
    shell.user_ns = {"x": 1, "y": "hello"}
    shell.execution_count = 1
    shell.events = MagicMock()
    return shell


class TestActivateDeactivate:
    def test_activate_registers_hooks(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()

        assert tracker._active
        assert mock_shell.events.register.call_count == 2

    def test_deactivate_unregisters_hooks(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()
            tracker.deactivate()

        assert not tracker._active
        assert mock_shell.events.unregister.call_count == 2

    def test_activate_no_ipython(self, lab):
        """IPython 環境でない場合は何もしない。"""
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=None,
        ):
            tracker.activate()

        assert not tracker._active

    def test_deactivate_when_not_active(self, lab):
        """未アクティブ状態で deactivate しても安全。"""
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)
        tracker.deactivate()  # エラーにならない


class TestCellLogging:
    def test_pre_post_creates_cell_log(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()

        # pre_run_cell: namespace スナップショット
        tracker._pre_run_cell(info=None)

        # post_run_cell: 差分計算 + CellLog 保存
        mock_shell.user_ns = {"x": 1, "y": "hello", "z": 42}
        result = SimpleNamespace(
            error_in_exec=None,
            info=SimpleNamespace(raw_cell="z = 42"),
        )
        tracker._post_run_cell(result)

        logs = lab._metadata.get_cell_logs("test-team", rec.id)
        assert len(logs) == 1
        assert logs[0]["record_id"] == rec.id
        assert logs[0]["source"] == "z = 42"
        assert "z" in logs[0]["new_vars"]

    def test_error_recorded(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()

        tracker._pre_run_cell(info=None)

        result = SimpleNamespace(
            error_in_exec=ValueError("test error"),
            info=SimpleNamespace(raw_cell="raise ValueError()"),
        )
        tracker._post_run_cell(result)

        logs = lab._metadata.get_cell_logs("test-team", rec.id)
        assert logs[0]["error"] is not None
        assert logs[0]["error"]["type"] == "ValueError"
        assert "test error" in logs[0]["error"]["message"]

    def test_cell_number_increments(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()

        for i in range(3):
            tracker._pre_run_cell(info=None)
            result = SimpleNamespace(
                error_in_exec=None,
                info=SimpleNamespace(raw_cell=f"cell_{i}"),
            )
            tracker._post_run_cell(result)

        logs = lab._metadata.get_cell_logs("test-team", rec.id)
        assert len(logs) == 3
        assert logs[0]["cell_number"] == 1
        assert logs[1]["cell_number"] == 2
        assert logs[2]["cell_number"] == 3


class TestPauseResume:
    def test_paused_skips_logging(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()

        tracker.paused = True
        tracker._pre_run_cell(info=None)
        result = SimpleNamespace(
            error_in_exec=None,
            info=SimpleNamespace(raw_cell="skipped"),
        )
        tracker._post_run_cell(result)

        logs = lab._metadata.get_cell_logs("test-team", rec.id)
        assert len(logs) == 0

    def test_resume_restarts_logging(self, lab, mock_shell):
        rec = lab.new("test", auto_log=False)
        tracker = CellTracker(rec, lab)

        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            tracker.activate()

        # Pause → 記録されない
        tracker.paused = True
        tracker._pre_run_cell(info=None)
        tracker._post_run_cell(
            SimpleNamespace(
                error_in_exec=None,
                info=SimpleNamespace(raw_cell="skipped"),
            )
        )

        # Resume → 記録される
        tracker.paused = False
        tracker._pre_run_cell(info=None)
        tracker._post_run_cell(
            SimpleNamespace(
                error_in_exec=None,
                info=SimpleNamespace(raw_cell="logged"),
            )
        )

        logs = lab._metadata.get_cell_logs("test-team", rec.id)
        assert len(logs) == 1
        assert logs[0]["source"] == "logged"


class TestRecordPauseResume:
    """Record.pause_logging / resume_logging / no_logging のテスト。"""

    def test_pause_resume_via_record(self, lab, mock_shell):
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            rec = lab.new("test")  # auto_log=True

        assert lab._active_tracker is not None
        assert not lab._active_tracker.paused

        rec.pause_logging()
        assert lab._active_tracker.paused

        rec.resume_logging()
        assert not lab._active_tracker.paused

    def test_no_logging_context(self, lab, mock_shell):
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            rec = lab.new("test")

        with rec.no_logging():
            assert lab._active_tracker.paused
        assert not lab._active_tracker.paused

    def test_pause_without_tracker_safe(self, lab):
        """tracker がない場合でもエラーにならない。"""
        rec = lab.new("test", auto_log=False)
        rec.pause_logging()
        rec.resume_logging()


class TestLabTrackerManagement:
    """Lab._active_tracker の切り替えテスト。"""

    def test_new_activates_tracker(self, lab, mock_shell):
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            lab.new("test")

        assert lab._active_tracker is not None

    def test_new_deactivates_previous(self, lab, mock_shell):
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            lab.new("test1")
            tracker1 = lab._active_tracker

            rec2 = lab.new("test2")
            tracker2 = lab._active_tracker

        assert not tracker1._active
        assert tracker2._active
        assert tracker2._record.id == rec2.id

    def test_no_tracker_without_ipython(self, lab):
        """IPython 環境でない場合は tracker が作られない。"""
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=None,
        ):
            lab.new("test")

        assert lab._active_tracker is None

    def test_close_deactivates_tracker(self, lab, mock_shell):
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            lab.new("test")

        tracker = lab._active_tracker
        lab.close()
        assert not tracker._active
        assert lab._active_tracker is None

    def test_get_with_auto_log(self, lab, mock_shell):
        with patch(
            "labvault.tracking.cell_tracker._get_ipython_shell",
            return_value=mock_shell,
        ):
            rec = lab.new("test", auto_log=False)
            assert lab._active_tracker is None

            lab.get(rec.id, auto_log=True)
            assert lab._active_tracker is not None
