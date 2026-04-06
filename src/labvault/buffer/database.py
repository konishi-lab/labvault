"""SQLite ローカルバッファデータベース。

データ消失防止のため、Record/ファイル/セルログをローカルに先に保存する。
M2 でリモート同期 (SyncManager) と統合される。
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# 現在のスキーマバージョン
SCHEMA_VERSION = 1

# スキーマ定義
_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pending_records (
    id TEXT PRIMARY KEY,
    team TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS pending_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    team TEXT NOT NULL,
    local_path TEXT NOT NULL,
    remote_path TEXT NOT NULL,
    content_type TEXT DEFAULT '',
    size_bytes INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    synced_at TEXT
);

CREATE TABLE IF NOT EXISTS pending_cell_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id TEXT NOT NULL,
    team TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    synced_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_pending_records_team
    ON pending_records(team);
CREATE INDEX IF NOT EXISTS idx_pending_files_record
    ON pending_files(record_id);
CREATE INDEX IF NOT EXISTS idx_pending_cell_logs_record
    ON pending_cell_logs(record_id);
CREATE INDEX IF NOT EXISTS idx_pending_files_synced
    ON pending_files(synced_at);
CREATE INDEX IF NOT EXISTS idx_pending_cell_logs_synced
    ON pending_cell_logs(synced_at);
"""

# マイグレーション定義 (バージョン間の差分SQL)
_MIGRATIONS: dict[int, str] = {
    # v1 -> v2 の例 (将来用)
    # 2: "ALTER TABLE pending_records ADD COLUMN priority INTEGER DEFAULT 0;",
}


def _now_iso() -> str:
    return datetime.now(_dt.UTC).isoformat()


class BufferDatabase:
    """SQLite ローカルバッファデータベース。

    - busy_timeout=5000: 複数カーネル同時アクセス時の SQLITE_BUSY 回避
    - WAL モード: 読み取り/書き込みの並行性向上
    - schema_version + マイグレーション: スキーマ変更時の自動更新
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        """接続を取得 (遅延初期化 + 設定適用)."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self._db_path),
                timeout=5.0,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._initialize_schema()

        return self._conn

    def _initialize_schema(self) -> None:
        """スキーマの初期化とマイグレーション。"""
        conn = self._conn
        assert conn is not None

        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_info'"
        )
        has_schema_info = cursor.fetchone() is not None

        if not has_schema_info:
            conn.executescript(_SCHEMA_V1)
            conn.execute(
                "INSERT INTO schema_info (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            conn.commit()
            return

        cursor = conn.execute("SELECT version FROM schema_info")
        row = cursor.fetchone()
        current_version = row["version"] if row else 0

        if current_version >= SCHEMA_VERSION:
            return

        for version in range(current_version + 1, SCHEMA_VERSION + 1):
            migration_sql = _MIGRATIONS.get(version)
            if migration_sql:
                conn.executescript(migration_sql)

        conn.execute(
            "UPDATE schema_info SET version = ?",
            (SCHEMA_VERSION,),
        )
        conn.commit()

    # --- 書き込み ---

    def save_record(self, team: str, record_id: str, data_json: str) -> None:
        """レコードをローカルバッファに保存する。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO pending_records "
            "(id, team, data, created_at) VALUES (?, ?, ?, ?)",
            (record_id, team, data_json, _now_iso()),
        )
        conn.commit()

    def save_file(
        self,
        record_id: str,
        team: str,
        local_path: str,
        remote_path: str,
        content_type: str = "",
        size_bytes: int = 0,
    ) -> None:
        """ファイル情報をローカルバッファに保存する。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO pending_files "
            "(record_id, team, local_path, remote_path,"
            " content_type, size_bytes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record_id,
                team,
                local_path,
                remote_path,
                content_type,
                size_bytes,
                _now_iso(),
            ),
        )
        conn.commit()

    def save_cell_log(self, record_id: str, team: str, data_json: str) -> None:
        """セルログをローカルバッファに保存する。"""
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO pending_cell_logs "
            "(record_id, team, data, created_at) VALUES (?, ?, ?, ?)",
            (record_id, team, data_json, _now_iso()),
        )
        conn.commit()

    # --- 読み取り ---

    def get_pending_records(self, limit: int = 10) -> list[dict[str, Any]]:
        """未同期のレコードを取得する。"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM pending_records "
            "WHERE synced_at IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_pending_files(self, limit: int = 10) -> list[dict[str, Any]]:
        """未同期のファイルを取得する。"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM pending_files "
            "WHERE synced_at IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_pending_cell_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """未同期のセルログを取得する。"""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT * FROM pending_cell_logs "
            "WHERE synced_at IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    # --- 同期管理 ---

    def mark_synced(self, table: str, ids: list[int | str]) -> None:
        """アイテムを同期済みにマークする。"""
        if not ids:
            return
        allowed = {"pending_records", "pending_files", "pending_cell_logs"}
        if table not in allowed:
            msg = f"Invalid table: {table}"
            raise ValueError(msg)
        conn = self._get_conn()
        now = _now_iso()
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE {table} SET synced_at = ? WHERE id IN ({placeholders})",
            [now, *ids],
        )
        conn.commit()

    def cleanup_synced(self, retention_days: int = 7) -> int:
        """同期済みアイテムを削除する。retention_days 日以上前のもの。"""
        cutoff = (datetime.now(_dt.UTC) - timedelta(days=retention_days)).isoformat()
        conn = self._get_conn()
        total = 0
        for table in (
            "pending_records",
            "pending_files",
            "pending_cell_logs",
        ):
            cursor = conn.execute(
                f"DELETE FROM {table} WHERE synced_at IS NOT NULL AND synced_at < ?",
                (cutoff,),
            )
            total += cursor.rowcount
        conn.commit()
        return total

    # --- ライフサイクル ---

    def close(self) -> None:
        """接続を閉じる。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
