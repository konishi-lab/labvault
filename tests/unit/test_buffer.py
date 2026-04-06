"""BufferDatabase のテスト。"""

from __future__ import annotations

import datetime as _dt
import json
from datetime import datetime, timedelta

import pytest

from labvault.buffer.database import SCHEMA_VERSION, BufferDatabase


@pytest.fixture()
def db(tmp_path):
    """一時ディレクトリに BufferDatabase を作成する。"""
    buf = BufferDatabase(tmp_path / "buffer.db")
    yield buf
    buf.close()


class TestSchemaCreation:
    """テーブル作成とスキーマ管理。"""

    def test_tables_created(self, db: BufferDatabase):
        conn = db._get_conn()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        assert "pending_records" in tables
        assert "pending_files" in tables
        assert "pending_cell_logs" in tables
        assert "schema_info" in tables

    def test_schema_version(self, db: BufferDatabase):
        conn = db._get_conn()
        cursor = conn.execute("SELECT version FROM schema_info")
        row = cursor.fetchone()
        assert row["version"] == SCHEMA_VERSION

    def test_wal_mode(self, db: BufferDatabase):
        conn = db._get_conn()
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"

    def test_reopen_no_migration(self, tmp_path):
        """既存DBを再オープンしてもエラーにならない。"""
        db_path = tmp_path / "buffer.db"
        db1 = BufferDatabase(db_path)
        db1._get_conn()
        db1.close()

        db2 = BufferDatabase(db_path)
        conn = db2._get_conn()
        cursor = conn.execute("SELECT version FROM schema_info")
        assert cursor.fetchone()["version"] == SCHEMA_VERSION
        db2.close()


class TestPendingRecords:
    """pending_records テーブルの操作。"""

    def test_save_and_get(self, db: BufferDatabase):
        data = json.dumps({"title": "XRD測定", "status": "running"})
        db.save_record("team-a", "AB3F", data)

        pending = db.get_pending_records()
        assert len(pending) == 1
        assert pending[0]["id"] == "AB3F"
        assert pending[0]["team"] == "team-a"
        assert json.loads(pending[0]["data"])["title"] == "XRD測定"

    def test_fifo_order(self, db: BufferDatabase):
        db.save_record("t", "REC1", '{"n":1}')
        db.save_record("t", "REC2", '{"n":2}')
        db.save_record("t", "REC3", '{"n":3}')

        pending = db.get_pending_records(limit=2)
        assert len(pending) == 2
        assert pending[0]["id"] == "REC1"
        assert pending[1]["id"] == "REC2"

    def test_upsert_idempotency(self, db: BufferDatabase):
        """同じIDで保存すると上書きされる (INSERT OR REPLACE)."""
        db.save_record("t", "AB3F", '{"v":1}')
        db.save_record("t", "AB3F", '{"v":2}')

        pending = db.get_pending_records()
        assert len(pending) == 1
        assert json.loads(pending[0]["data"])["v"] == 2


class TestPendingFiles:
    """pending_files テーブルの操作。"""

    def test_save_and_get(self, db: BufferDatabase):
        db.save_file(
            record_id="AB3F",
            team="team-a",
            local_path="/tmp/data.csv",
            remote_path="team-a/AB3F/data.csv",
            content_type="text/csv",
            size_bytes=1024,
        )

        pending = db.get_pending_files()
        assert len(pending) == 1
        assert pending[0]["record_id"] == "AB3F"
        assert pending[0]["local_path"] == "/tmp/data.csv"
        assert pending[0]["remote_path"] == "team-a/AB3F/data.csv"
        assert pending[0]["content_type"] == "text/csv"
        assert pending[0]["size_bytes"] == 1024

    def test_multiple_files_per_record(self, db: BufferDatabase):
        db.save_file("R1", "t", "/a.csv", "t/R1/a.csv")
        db.save_file("R1", "t", "/b.csv", "t/R1/b.csv")

        pending = db.get_pending_files()
        assert len(pending) == 2


class TestPendingCellLogs:
    """pending_cell_logs テーブルの操作。"""

    def test_save_and_get(self, db: BufferDatabase):
        log = json.dumps({"cell_id": "c1", "source": "x = 1"})
        db.save_cell_log("AB3F", "team-a", log)

        pending = db.get_pending_cell_logs()
        assert len(pending) == 1
        assert pending[0]["record_id"] == "AB3F"
        assert json.loads(pending[0]["data"])["cell_id"] == "c1"


class TestMarkSynced:
    """同期済みマークの操作。"""

    def test_mark_record_synced(self, db: BufferDatabase):
        db.save_record("t", "R1", "{}")
        db.save_record("t", "R2", "{}")

        db.mark_synced("pending_records", ["R1"])

        pending = db.get_pending_records()
        assert len(pending) == 1
        assert pending[0]["id"] == "R2"

    def test_mark_file_synced(self, db: BufferDatabase):
        db.save_file("R1", "t", "/a.csv", "t/R1/a.csv")
        db.save_file("R1", "t", "/b.csv", "t/R1/b.csv")

        pending = db.get_pending_files()
        file_id = pending[0]["id"]
        db.mark_synced("pending_files", [file_id])

        remaining = db.get_pending_files()
        assert len(remaining) == 1

    def test_mark_cell_log_synced(self, db: BufferDatabase):
        db.save_cell_log("R1", "t", '{"c":1}')
        db.save_cell_log("R1", "t", '{"c":2}')

        pending = db.get_pending_cell_logs()
        db.mark_synced("pending_cell_logs", [pending[0]["id"]])

        remaining = db.get_pending_cell_logs()
        assert len(remaining) == 1

    def test_mark_synced_empty_ids(self, db: BufferDatabase):
        """空リストを渡しても何も起きない。"""
        db.mark_synced("pending_records", [])

    def test_mark_synced_invalid_table(self, db: BufferDatabase):
        with pytest.raises(ValueError, match="Invalid table"):
            db.mark_synced("users", ["id1"])


class TestCleanupSynced:
    """同期済みアイテムのクリーンアップ。"""

    def test_cleanup_old_synced(self, db: BufferDatabase):
        db.save_record("t", "R1", "{}")
        db.mark_synced("pending_records", ["R1"])

        # synced_at を 10 日前に書き換え
        conn = db._get_conn()
        old_time = (datetime.now(_dt.UTC) - timedelta(days=10)).isoformat()
        conn.execute(
            "UPDATE pending_records SET synced_at = ? WHERE id = ?",
            (old_time, "R1"),
        )
        conn.commit()

        deleted = db.cleanup_synced(retention_days=7)
        assert deleted == 1
        assert db.get_pending_records() == []

    def test_cleanup_keeps_recent_synced(self, db: BufferDatabase):
        db.save_record("t", "R1", "{}")
        db.mark_synced("pending_records", ["R1"])

        deleted = db.cleanup_synced(retention_days=7)
        assert deleted == 0

    def test_cleanup_keeps_unsynced(self, db: BufferDatabase):
        db.save_record("t", "R1", "{}")

        deleted = db.cleanup_synced(retention_days=0)
        assert deleted == 0
        assert len(db.get_pending_records()) == 1


class TestClose:
    """リソース解放。"""

    def test_close_and_reopen(self, tmp_path):
        db_path = tmp_path / "buffer.db"
        db = BufferDatabase(db_path)
        db.save_record("t", "R1", "{}")
        db.close()

        db2 = BufferDatabase(db_path)
        pending = db2.get_pending_records()
        assert len(pending) == 1
        assert pending[0]["id"] == "R1"
        db2.close()

    def test_close_idempotent(self, db: BufferDatabase):
        db.close()
        db.close()  # 二回呼んでもエラーにならない
