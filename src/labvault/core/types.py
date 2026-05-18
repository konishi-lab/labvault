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
class ConditionField:
    """テンプレートの条件フィールド定義 (name, type, unit, range, aliases)。

    aliases に挙げた key を Record.conditions() に渡すと name に正規化される。
    required=True のフィールドは Record の status を success にした時点で未入力警告。
    """

    name: str
    display_name: str = ""
    type: str = "str"  # "float", "int", "str", "bool"
    unit: str = ""
    required: bool = False
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    choices: list[str] | None = None
    aliases: list[str] | None = None
    description: str = ""


@dataclass
class FileParserConfig:
    """テンプレートが扱うファイル拡張子とパーサーのマッピング。"""

    extension: str  # ".ras", ".dm3", ".wdf" 等
    parser_name: str
    auto_extract_conditions: bool = True


@dataclass
class TemplateV10:
    """テンプレート定義。

    `lab.define_template(template)` で永続化、`lab.new(title, template=name)` で
    Record に紐付ける。required_conditions に挙げた key が status=success/failed
    時に未入力ならば warnings.warn する。aliases は Record.conditions() で
    自動正規化に使われる。indexed_fields / file_parsers の機能は別途追加予定。
    """

    name: str
    display_name: str = ""
    description: str = ""
    type: str = "experiment"
    default_tags: list[str] = field(default_factory=list)
    condition_fields: list[ConditionField] = field(default_factory=list)
    required_conditions: list[str] = field(default_factory=list)
    recommended_results: list[str] = field(default_factory=list)
    indexed_fields: list[str] = field(default_factory=list)
    file_parsers: list[FileParserConfig] = field(default_factory=list)

    def alias_map(self) -> dict[str, str]:
        """alias → 正規化された name の lookup を返す。"""
        out: dict[str, str] = {}
        for f in self.condition_fields:
            for a in f.aliases or []:
                out[a] = f.name
        return out


def template_to_dict(t: TemplateV10) -> dict[str, Any]:
    """TemplateV10 を Firestore 等に保存可能な dict に変換する。"""
    from dataclasses import asdict

    return asdict(t)


def template_from_dict(d: dict[str, Any]) -> TemplateV10:
    """dict から TemplateV10 を再構築する。未知フィールドは無視する。"""
    fields_raw = d.get("condition_fields") or []
    fields_obj = [
        ConditionField(
            name=f["name"],
            display_name=f.get("display_name", ""),
            type=f.get("type", "str"),
            unit=f.get("unit", ""),
            required=bool(f.get("required", False)),
            default=f.get("default"),
            min_value=f.get("min_value"),
            max_value=f.get("max_value"),
            choices=f.get("choices"),
            aliases=f.get("aliases"),
            description=f.get("description", ""),
        )
        for f in fields_raw
        if isinstance(f, dict) and f.get("name")
    ]
    parsers_raw = d.get("file_parsers") or []
    parsers_obj = [
        FileParserConfig(
            extension=p["extension"],
            parser_name=p["parser_name"],
            auto_extract_conditions=bool(p.get("auto_extract_conditions", True)),
        )
        for p in parsers_raw
        if isinstance(p, dict) and p.get("extension") and p.get("parser_name")
    ]
    return TemplateV10(
        name=d["name"],
        display_name=d.get("display_name", ""),
        description=d.get("description", ""),
        type=d.get("type", "experiment"),
        default_tags=list(d.get("default_tags") or []),
        condition_fields=fields_obj,
        required_conditions=list(d.get("required_conditions") or []),
        recommended_results=list(d.get("recommended_results") or []),
        indexed_fields=list(d.get("indexed_fields") or []),
        file_parsers=parsers_obj,
    )


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
