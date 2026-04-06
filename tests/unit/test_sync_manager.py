"""SyncManager のテスト。"""

from __future__ import annotations

import json

import pytest

from labvault.backends.memory import InMemoryMetadataBackend, InMemoryStorageBackend
from labvault.buffer.database import BufferDatabase
from labvault.buffer.sync import SyncManager


@pytest.fixture()
def buffer_db(tmp_path):
    db = BufferDatabase(tmp_path / "buffer.db")
    yield db
    db.close()


@pytest.fixture()
def metadata():
    return InMemoryMetadataBackend()


@pytest.fixture()
def storage():
    return InMemoryStorageBackend()


@pytest.fixture()
def sync_manager(buffer_db, metadata, storage):
    sm = SyncManager(
        buffer_db=buffer_db,
        metadata_backend=metadata,
        storage_backend=storage,
        interval_sec=60.0,  # 長めに設定 (自動同期を防ぐ)
    )
    yield sm
    sm.stop(flush=False)


class TestLifecycle:
    def test_start_stop(self, sync_manager):
        sync_manager.start()
        assert sync_manager.sync_status["is_running"]

        sync_manager.stop(flush=False)
        assert not sync_manager.sync_status["is_running"]

    def test_start_idempotent(self, sync_manager):
        sync_manager.start()
        sync_manager.start()  # 二回呼んでもエラーにならない
        assert sync_manager.sync_status["is_running"]

    def test_stop_without_start(self, sync_manager):
        sync_manager.stop(flush=False)  # 未起動でも安全


class TestSyncRecords:
    def test_sync_pending_records(self, sync_manager, buffer_db, metadata):
        # メタデータバックエンドにレコードを先に作成
        record_data = {"id": "AB3F", "title": "test", "status": "running"}
        metadata.create_record("team-a", record_data)

        # バッファにペンディングレコードを追加
        updated = {"id": "AB3F", "title": "updated", "status": "success"}
        buffer_db.save_record("team-a", "AB3F", json.dumps(updated))

        # 同期実行
        sync_manager.sync_now()

        # メタデータバックエンドが更新されている
        result = metadata.get_record("team-a", "AB3F")
        assert result["title"] == "updated"

        # バッファからペンディングが消えている
        assert len(buffer_db.get_pending_records()) == 0

    def test_sync_multiple_records(self, sync_manager, buffer_db, metadata):
        for i in range(3):
            rid = f"R{i:03d}"
            metadata.create_record("t", {"id": rid, "title": f"rec{i}"})
            data = json.dumps({"id": rid, "title": f"updated{i}"})
            buffer_db.save_record("t", rid, data)

        sync_manager.sync_now()

        for i in range(3):
            result = metadata.get_record("t", f"R{i:03d}")
            assert result["title"] == f"updated{i}"
        assert len(buffer_db.get_pending_records()) == 0


class TestSyncCellLogs:
    def test_sync_pending_cell_logs(self, sync_manager, buffer_db, metadata):
        # レコードを先に作成
        metadata.create_record("team-a", {"id": "AB3F", "title": "test"})

        # セルログをバッファに追加
        log = {"cell_id": "c1", "cell_number": 1, "source": "x = 1"}
        buffer_db.save_cell_log("AB3F", "team-a", json.dumps(log))

        # 同期実行
        sync_manager.sync_now()

        # メタデータバックエンドにセルログがある
        logs = metadata.get_cell_logs("team-a", "AB3F")
        assert len(logs) == 1
        assert logs[0]["source"] == "x = 1"

        # バッファからペンディングが消えている
        assert len(buffer_db.get_pending_cell_logs()) == 0


class TestSyncStatus:
    def test_initial_status(self, sync_manager):
        status = sync_manager.sync_status
        assert status["pending"] == 0
        assert status["last_error"] is None
        assert status["is_running"] is False

    def test_status_after_sync(self, sync_manager, buffer_db, metadata):
        metadata.create_record("t", {"id": "R1", "title": "t"})
        buffer_db.save_record("t", "R1", json.dumps({"id": "R1", "title": "u"}))

        sync_manager.sync_now()

        status = sync_manager.sync_status
        assert status["pending"] == 0
        assert status["last_error"] is None
        assert status["last_sync"] > 0

    def test_pending_count(self, sync_manager, buffer_db):
        buffer_db.save_record("t", "R1", "{}")
        buffer_db.save_record("t", "R2", "{}")

        status = sync_manager.sync_status
        assert status["pending"] == 2


class TestErrorHandling:
    def test_error_recorded_in_status(self, buffer_db, storage):
        """同期エラーが sync_status に記録される。"""
        # エラーを起こすモックバックエンド
        broken_metadata = InMemoryMetadataBackend()

        sm = SyncManager(
            buffer_db=buffer_db,
            metadata_backend=broken_metadata,
            storage_backend=storage,
            interval_sec=60.0,
        )

        # 存在しないレコードを更新しようとする (update_record は存在チェックしない)
        # → 代わりに save_cell_log でエラーを起こす
        buffer_db.save_cell_log("R1", "t", "invalid json{{{")

        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sm.sync_now()

        status = sm.sync_status
        assert status["last_error"] is not None


class TestStopFlush:
    def test_stop_flush_syncs_pending(self, buffer_db, metadata, storage):
        metadata.create_record("t", {"id": "R1", "title": "orig"})
        buffer_db.save_record("t", "R1", json.dumps({"id": "R1", "title": "flushed"}))

        sm = SyncManager(
            buffer_db=buffer_db,
            metadata_backend=metadata,
            storage_backend=storage,
            interval_sec=60.0,
        )
        sm.start()
        sm.stop(flush=True)

        result = metadata.get_record("t", "R1")
        assert result["title"] == "flushed"


class TestLabIntegration:
    """Lab + SyncManager の統合テスト。"""

    def test_persist_writes_to_buffer(self, tmp_path):
        from labvault.core.lab import Lab

        lab = Lab(
            "test-team",
            user="tester",
            metadata_backend=InMemoryMetadataBackend(),
            storage_backend=InMemoryStorageBackend(),
        )
        # auto_sync=True (デフォルト) なので buffer が作られている
        assert lab._buffer is not None

        rec = lab.new("test", auto_log=False)

        # _persist() でバッファにも書かれる
        rec.conditions(temp=100)

        pending = lab._buffer.get_pending_records()
        assert len(pending) >= 1

        lab.close()

    def test_sync_status_property(self, tmp_path):
        from labvault.core.lab import Lab

        lab = Lab(
            "test-team",
            user="tester",
            metadata_backend=InMemoryMetadataBackend(),
            storage_backend=InMemoryStorageBackend(),
        )

        status = lab.sync_status
        assert "pending" in status
        assert "is_running" in status
        assert status["is_running"] is True

        lab.close()
        status = lab.sync_status
        assert status["is_running"] is False
