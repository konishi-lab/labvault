"""Record クラス -- 実験レコードの操作インターフェース。"""

from __future__ import annotations

import builtins
import datetime as _dt
import hashlib
import io
import json
import mimetypes
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from labvault.core.types import (
    DataRef,
    ExternalRef,
    Link,
    Note,
    Status,
)

if TYPE_CHECKING:
    from labvault.core.lab import Lab


class _ResultsProxy:
    """dict-like proxy. __setitem__ で Record の dirty フラグを立てる。"""

    def __init__(self, record: Record) -> None:
        self._record = record
        self._data: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._record._persist()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return repr(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        """dict.get と同等。"""
        return self._data.get(key, default)

    def keys(self) -> Any:
        """dict.keys と同等。"""
        return self._data.keys()

    def values(self) -> Any:
        """dict.values と同等。"""
        return self._data.values()

    def items(self) -> Any:
        """dict.items と同等。"""
        return self._data.items()

    def to_dict(self) -> dict[str, Any]:
        """内部辞書のコピーを返す。"""
        return dict(self._data)

    def _load(self, data: dict[str, Any]) -> None:
        """永続化データから復元 (persist なし)."""
        self._data = dict(data)


class Record:
    """実験レコード。Lab.new() / Lab.get() で生成される。"""

    def __init__(
        self,
        *,
        id: str,
        team: str,
        title: str,
        record_type: str,
        status: str = Status.RUNNING,
        created_by: str = "",
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        tags: list[str] | None = None,
        notes: list[Note] | None = None,
        links: list[Link] | None = None,
        data_refs: list[DataRef] | None = None,
        external_refs: list[ExternalRef] | None = None,
        conditions_data: dict[str, Any] | None = None,
        results_data: dict[str, Any] | None = None,
        events: list[dict[str, Any]] | None = None,
        deleted_at: datetime | None = None,
        parent_id: str | None = None,
        lab: Lab | None = None,
    ) -> None:
        self._id = id
        self._team = team
        self._title = title
        self._type = record_type
        self._status = Status(status) if status else Status.RUNNING
        self._created_by = created_by
        now = datetime.now(_dt.UTC)
        self._created_at = created_at or now
        self._updated_at = updated_at or now
        self._tags: list[str] = list(tags) if tags else []
        self._notes: list[Note] = list(notes) if notes else []
        self._links: list[Link] = list(links) if links else []
        self._data_refs: list[DataRef] = list(data_refs) if data_refs else []
        self._external_refs: list[ExternalRef] = (
            list(external_refs) if external_refs else []
        )
        self._conditions: dict[str, Any] = (
            dict(conditions_data) if conditions_data else {}
        )
        self._results = _ResultsProxy(self)
        if results_data:
            self._results._load(results_data)
        self._events: list[dict[str, Any]] = list(events) if events else []
        self._deleted_at = deleted_at
        self._parent_id = parent_id
        self._lab = lab

    # --- プロパティ ---

    @property
    def id(self) -> str:
        """レコード ID。"""
        return self._id

    @property
    def team(self) -> str:
        """チーム名。"""
        return self._team

    @property
    def title(self) -> str:
        """タイトル。"""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value
        self._persist()

    @property
    def type(self) -> str:
        """レコードタイプ。"""
        return self._type

    @property
    def status(self) -> Status:
        """ステータス。"""
        return self._status

    @status.setter
    def status(self, value: str | Status) -> None:
        self._status = Status(value)
        self._persist()

    @property
    def created_by(self) -> str:
        """作成者。"""
        return self._created_by

    @property
    def created_at(self) -> datetime:
        """作成日時。"""
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        """更新日時。"""
        return self._updated_at

    @property
    def tags(self) -> list[str]:
        """タグリスト。"""
        return list(self._tags)

    @property
    def notes(self) -> list[Note]:
        """ノートリスト。"""
        return list(self._notes)

    @property
    def links(self) -> list[Link]:
        """リンクリスト。"""
        return list(self._links)

    @property
    def data_refs(self) -> list[DataRef]:
        """データ参照リスト。"""
        return list(self._data_refs)

    @property
    def external_refs(self) -> list[ExternalRef]:
        """外部参照リスト。"""
        return list(self._external_refs)

    @property
    def results(self) -> _ResultsProxy:
        """結果 (dict-like proxy)."""
        return self._results

    @property
    def events(self) -> list[dict[str, Any]]:
        """イベントリスト。"""
        return list(self._events)

    @property
    def deleted_at(self) -> datetime | None:
        """削除日時 (None = 未削除)."""
        return self._deleted_at

    @property
    def parent_id(self) -> str | None:
        """親レコード ID (None = ルート)."""
        return self._parent_id

    # --- ミューテーション (全て self を返す) ---

    def conditions(self, **kwargs: Any) -> Record:
        """実験条件を設定する。"""
        self._conditions.update(kwargs)
        self._persist()
        return self

    def get_conditions(self) -> dict[str, Any]:
        """実験条件を返す。"""
        return dict(self._conditions)

    def tag(self, *tags: str) -> Record:
        """タグを追加する。"""
        for t in tags:
            if t not in self._tags:
                self._tags.append(t)
        self._persist()
        return self

    def untag(self, *tags: str) -> Record:
        """タグを除去する。"""
        self._tags = [t for t in self._tags if t not in tags]
        self._persist()
        return self

    def note(self, text: str, *, author: str = "") -> Record:
        """メモを追加する。直近と同一テキストなら重複を防ぐ (冪等性)."""
        if self._notes and self._notes[-1].text == text:
            return self
        self._notes.append(
            Note(
                text=text,
                author=author or self._created_by,
            )
        )
        self._persist()
        return self

    def link(
        self,
        target_id: str,
        relation: str = "related_to",
        *,
        description: str = "",
    ) -> Record:
        """他レコードへリンクする。"""
        self._links.append(
            Link(
                target_id=target_id,
                relation=relation,
                description=description,
            )
        )
        self._persist()
        return self

    def add_ref(
        self,
        uri: str,
        *,
        location: str = "",
        size_bytes: int | None = None,
        description: str = "",
        doi: str = "",
    ) -> Record:
        """外部参照を追加する。"""
        self._external_refs.append(
            ExternalRef(
                uri=uri,
                location=location,
                size_bytes=size_bytes,
                description=description,
                doi=doi,
            )
        )
        self._persist()
        return self

    def log_value(self, key: str, value: Any) -> Record:
        """タイムスタンプ付き値を記録する。"""
        self._events.append(
            {
                "type": "value",
                "key": key,
                "value": value,
                "timestamp": datetime.now(_dt.UTC).isoformat(),
            }
        )
        self._persist()
        return self

    def log_event(
        self,
        event_type: str,
        description: str = "",
    ) -> Record:
        """イベントを記録する。"""
        self._events.append(
            {
                "type": event_type,
                "description": description,
                "timestamp": datetime.now(_dt.UTC).isoformat(),
            }
        )
        self._persist()
        return self

    # --- ログ制御 ---

    def pause_logging(self) -> Record:
        """セル自動記録を一時停止する。"""
        if self._lab and self._lab._active_tracker:
            self._lab._active_tracker.paused = True
        return self

    def resume_logging(self) -> Record:
        """セル自動記録を再開する。"""
        if self._lab and self._lab._active_tracker:
            self._lab._active_tracker.paused = False
        return self

    @contextmanager
    def no_logging(self) -> Any:
        """セル自動記録を一時的に無効化するコンテキストマネージャ。"""
        self.pause_logging()
        try:
            yield
        finally:
            self.resume_logging()

    # --- 子レコード ---

    def sub(
        self,
        title: str,
        *,
        type: str | None = None,
        **conditions: Any,
    ) -> Record:
        """子レコードを作成する。"""
        from labvault.core.types import RecordType

        if self._lab is None:
            msg = "Cannot create sub-record without a Lab instance"
            raise RuntimeError(msg)

        rec_type = type or RecordType.MEASUREMENT
        child = self._lab.new(title, type=rec_type, **conditions)
        child._parent_id = self._id
        child._persist()

        self.link(child.id, "has_child")
        child.link(self._id, "child_of")
        return child

    def children(self) -> builtins.list[Record]:
        """直接の子レコード一覧を返す。"""
        if self._lab is None:
            return []
        all_records = self._lab.list(limit=1000)
        return [r for r in all_records if r.parent_id == self._id]

    # --- ファイル操作 ---

    def add(
        self,
        source: str | Path | bytes,
        *,
        name: str | None = None,
        content_type: str = "",
    ) -> Record:
        """ファイルを保存する。

        同一ファイル名の DataRef が既にあり SHA256 が同じなら
        スキップ (冪等性)。
        """
        data: bytes
        file_name: str

        if isinstance(source, (str, Path)):
            p = Path(source)
            data = p.read_bytes()
            file_name = name or p.name
            if not content_type:
                ct, _ = mimetypes.guess_type(str(p))
                content_type = ct or "application/octet-stream"
        else:
            data = source
            file_name = name or "untitled"
            content_type = content_type or "application/octet-stream"

        sha = hashlib.sha256(data).hexdigest()

        # 冪等性: 同一ファイル名 & 同一ハッシュならスキップ
        for ref in self._data_refs:
            if ref.name == file_name and ref.sha256 == sha:
                return self

        storage_path = f"{self._team}/{self._id}/{file_name}"

        if self._lab and self._lab._storage:
            self._lab._storage.upload(storage_path, data, content_type)

        # 同一ファイル名は上書き
        self._data_refs = [r for r in self._data_refs if r.name != file_name]
        self._data_refs.append(
            DataRef(
                name=file_name,
                nextcloud_path=storage_path,
                content_type=content_type,
                size_bytes=len(data),
                sha256=sha,
            )
        )
        self._persist()
        return self

    def save(
        self,
        name: str,
        obj: Any,
        *,
        content_type: str = "",
    ) -> Record:
        """Python オブジェクトを自動判定してファイル保存する。

        - dict/list -> JSON
        - str -> テキスト (.txt)
        - bytes -> バイナリ
        - numpy.ndarray -> .npy (try/except)
        - matplotlib.Figure -> .png (try/except)
        - pandas.DataFrame -> .csv (try/except)
        """
        data: bytes
        ct = content_type

        if isinstance(obj, bytes):
            data = obj
            ct = ct or "application/octet-stream"
        elif isinstance(obj, str):
            data = obj.encode("utf-8")
            if not name.endswith(".txt"):
                name = name if "." in name else f"{name}.txt"
            ct = ct or "text/plain; charset=utf-8"
        elif isinstance(obj, (dict, list)):
            data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
            if not name.endswith(".json"):
                name = name if "." in name else f"{name}.json"
            ct = ct or "application/json"
        else:
            data, name, ct = _try_save_special(obj, name, ct)

        return self.add(data, name=name, content_type=ct)

    def add_dir(self, dir_path: str | Path) -> Record:
        """ディレクトリ配下の全ファイルを再帰的に追加する。"""
        root = Path(dir_path)
        if not root.is_dir():
            msg = f"Not a directory: {root}"
            raise NotADirectoryError(msg)
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root)
                self.add(p, name=str(rel))
        return self

    def get_data(self, name: str) -> bytes:
        """保存済みファイルのデータをバイナリで取得する。"""
        for ref in self._data_refs:
            if ref.name == name:
                if self._lab and self._lab._storage:
                    return self._lab._storage.download(ref.nextcloud_path)
                msg = "No storage backend available"
                raise RuntimeError(msg)
        msg = f"File not found: {name}"
        raise FileNotFoundError(msg)

    def list_data(self) -> builtins.list[DataRef]:
        """レコードに紐づくファイルの一覧を返す。"""
        return list(self._data_refs)

    # --- 永続化 ---

    def _persist(self) -> None:
        """メタデータバックエンドに現在の状態を書き込む。"""
        self._updated_at = datetime.now(_dt.UTC)
        if self._lab and self._lab._metadata:
            self._lab._metadata.update_record(self._team, self._id, self._to_dict())

    def _to_dict(self) -> dict[str, Any]:
        """永続化用の辞書表現。"""
        return {
            "id": self._id,
            "team": self._team,
            "title": self._title,
            "type": self._type,
            "status": str(self._status),
            "created_by": self._created_by,
            "created_at": self._created_at.isoformat(),
            "updated_at": self._updated_at.isoformat(),
            "tags": list(self._tags),
            "notes": [
                {
                    "text": n.text,
                    "created_at": n.created_at.isoformat(),
                    "author": n.author,
                }
                for n in self._notes
            ],
            "links": [
                {
                    "target_id": lk.target_id,
                    "relation": lk.relation,
                    "description": lk.description,
                }
                for lk in self._links
            ],
            "data_refs": [
                {
                    "name": d.name,
                    "nextcloud_path": d.nextcloud_path,
                    "content_type": d.content_type,
                    "size_bytes": d.size_bytes,
                    "sha256": d.sha256,
                }
                for d in self._data_refs
            ],
            "external_refs": [
                {
                    "uri": e.uri,
                    "location": e.location,
                    "size_bytes": e.size_bytes,
                    "description": e.description,
                    "doi": e.doi,
                }
                for e in self._external_refs
            ],
            "conditions": dict(self._conditions),
            "results": self._results.to_dict(),
            "events": list(self._events),
            "deleted_at": (self._deleted_at.isoformat() if self._deleted_at else None),
            "parent_id": self._parent_id,
        }

    # --- コンテキストマネージャ ---

    def __enter__(self) -> Record:
        return self

    def __exit__(
        self,
        exc_type: builtins.type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        if exc_type is not None:
            self._status = Status.FAILED
        elif self._status == Status.RUNNING:
            self._status = Status.SUCCESS
        self._persist()

    # --- repr ---

    def __repr__(self) -> str:
        return (
            f"Record(id={self._id!r}, title={self._title!r}, status={self._status!r})"
        )

    # --- クラスメソッド: dict からの復元 ---

    @classmethod
    def _from_dict(
        cls,
        data: dict[str, Any],
        *,
        lab: Lab | None = None,
    ) -> Record:
        """バックエンドの辞書から Record を復元する。"""
        notes = [
            Note(
                text=n["text"],
                created_at=_parse_dt(n.get("created_at", "")),
                author=n.get("author", ""),
            )
            for n in data.get("notes", [])
        ]
        links = [
            Link(
                target_id=lk["target_id"],
                relation=lk.get("relation", "related_to"),
                description=lk.get("description", ""),
            )
            for lk in data.get("links", [])
        ]
        data_refs = [DataRef(**d) for d in data.get("data_refs", [])]
        external_refs = [
            ExternalRef(
                uri=e["uri"],
                location=e.get("location", ""),
                size_bytes=e.get("size_bytes"),
                description=e.get("description", ""),
                doi=e.get("doi", ""),
            )
            for e in data.get("external_refs", [])
        ]

        created_at_raw = data.get("created_at")
        updated_at_raw = data.get("updated_at")
        deleted_at_raw = data.get("deleted_at")

        return cls(
            id=data["id"],
            team=data.get("team", ""),
            title=data.get("title", ""),
            record_type=data.get("type", "experiment"),
            status=data.get("status", "running"),
            created_by=data.get("created_by", ""),
            created_at=(_parse_dt(created_at_raw) if created_at_raw else None),
            updated_at=(_parse_dt(updated_at_raw) if updated_at_raw else None),
            tags=data.get("tags"),
            notes=notes,
            links=links,
            data_refs=data_refs,
            external_refs=external_refs,
            conditions_data=data.get("conditions"),
            results_data=data.get("results"),
            events=data.get("events"),
            deleted_at=(_parse_dt(deleted_at_raw) if deleted_at_raw else None),
            parent_id=data.get("parent_id"),
            lab=lab,
        )


# --- ヘルパー ---


def _parse_dt(raw: str | datetime) -> datetime:
    """ISO 文字列 or datetime を timezone-aware datetime に変換。"""
    if isinstance(raw, datetime):
        if raw.tzinfo is None:
            return raw.replace(tzinfo=_dt.UTC)
        return raw
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.UTC)
    return dt


def _try_save_special(obj: Any, name: str, content_type: str) -> tuple[bytes, str, str]:
    """numpy / matplotlib / pandas の自動保存を試みる。"""
    # numpy.ndarray
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            buf = io.BytesIO()
            np.save(buf, obj)
            if not name.endswith(".npy"):
                name = name if "." in name else f"{name}.npy"
            return (
                buf.getvalue(),
                name,
                content_type or "application/octet-stream",
            )
    except ImportError:
        pass

    # pandas.DataFrame
    try:
        import pandas as pd

        if isinstance(obj, pd.DataFrame):
            csv_data = obj.to_csv(index=False)
            if not name.endswith(".csv"):
                name = name if "." in name else f"{name}.csv"
            return (
                csv_data.encode("utf-8"),
                name,
                content_type or "text/csv; charset=utf-8",
            )
    except ImportError:
        pass

    # matplotlib.Figure
    try:
        import matplotlib.figure

        if isinstance(obj, matplotlib.figure.Figure):
            buf = io.BytesIO()
            obj.savefig(buf, format="png")
            if not name.endswith(".png"):
                name = name if "." in name else f"{name}.png"
            return (
                buf.getvalue(),
                name,
                content_type or "image/png",
            )
    except ImportError:
        pass

    msg = f"Unsupported type: {type(obj).__name__}"
    raise TypeError(msg)
