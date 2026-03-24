"""labvault 型定義。"""

from __future__ import annotations

import datetime as _dt
import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class Status(enum.StrEnum):
    """レコードのステータス。"""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class RecordType(enum.StrEnum):
    """レコードタイプのプリセット。フリーテキストも許容する。"""

    EXPERIMENT = "experiment"
    SAMPLE = "sample"
    PROCESS = "process"
    MEASUREMENT = "measurement"
    COMPUTATION = "computation"
    ANALYSIS = "analysis"


def _now_utc() -> datetime:
    return datetime.now(_dt.UTC)


@dataclass
class Note:
    """メモ。"""

    text: str
    created_at: datetime = field(default_factory=_now_utc)
    author: str = ""


@dataclass
class Link:
    """レコード間リンク。"""

    target_id: str
    relation: str = "related_to"
    description: str = ""


@dataclass
class DataRef:
    """Nextcloud に保存されたファイルのメタデータ。"""

    name: str
    nextcloud_path: str = ""
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""


@dataclass
class ExternalRef:
    """転送せず参照だけ登録するデータ。"""

    uri: str
    location: str = ""
    size_bytes: int | None = None
    description: str = ""
    doi: str = ""


@dataclass
class CellLog:
    """1セルの実行記録。"""

    cell_id: str
    record_id: str
    cell_number: int
    execution_count: int
    source: str
    source_hash: str = ""
    new_vars: dict[str, Any] = field(default_factory=dict)
    changed_vars: dict[str, Any] = field(default_factory=dict)
    deleted_vars: list[str] = field(default_factory=list)
    duration_sec: float = 0.0
    executed_at: datetime = field(default_factory=_now_utc)
    error: dict[str, Any] | None = None
    session_id: str = ""
