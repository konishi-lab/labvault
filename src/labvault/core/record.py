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
    """dict-like proxy. __setitem__ で Record の dirty フラグを立てる。

    値は スカラー / (値, 単位) tuple / (値, 単位, 説明) tuple のいずれかを
    受け付ける。tuple 記法のときは Record._result_units / _result_descriptions
    にも書き戻す (conditions と対称な API)。
    """

    def __init__(self, record: Record) -> None:
        self._record = record
        self._data: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        from labvault.core.units import validate_unit

        if isinstance(value, tuple):
            if len(value) == 2:
                actual, unit = value
                self._data[key] = actual
                validate_unit(unit)
                self._record._result_units[key] = unit
            elif len(value) >= 3:
                actual, unit, desc = value[0], value[1], value[2]
                self._data[key] = actual
                validate_unit(unit)
                self._record._result_units[key] = unit
                self._record._result_descriptions[key] = str(desc)
            else:
                self._data[key] = value[0]
        else:
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
        updated_by: str = "",
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
        template_name: str | None = None,
        lab: Lab | None = None,
    ) -> None:
        self._id = id
        self._team = team
        self._title = title
        self._type = record_type
        self._status = Status(status) if status else Status.RUNNING
        self._created_by = created_by
        self._updated_by = updated_by or created_by
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
        self._condition_units: dict[str, str] = {}
        self._condition_descriptions: dict[str, str] = {}
        self._result_units: dict[str, str] = {}
        self._result_descriptions: dict[str, str] = {}
        self._results = _ResultsProxy(self)
        if results_data:
            self._results._load(results_data)
        self._events: list[dict[str, Any]] = list(events) if events else []
        self._deleted_at = deleted_at
        self._parent_id = parent_id
        self._template_name = template_name
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
        new_status = Status(value)
        self._status = new_status
        # success / failed / partial に遷移したタイミングで template の必須条件を点検。
        # 未入力なら UserWarning を出して書き込みを止めない。
        if new_status in (Status.SUCCESS, Status.FAILED, Status.PARTIAL):
            self._warn_missing_required_conditions()
        self._persist()

    @property
    def template_name(self) -> str | None:
        """紐付いたテンプレート名 (template 未指定なら None)。"""
        return self._template_name

    def _resolve_template(self) -> Any | None:
        """この record に紐付いた TemplateV10 を取得する (見つからなければ None)。"""
        if not self._template_name or self._lab is None:
            return None
        return self._lab.get_template(self._template_name)

    def _warn_missing_required_conditions(self) -> None:
        """required_conditions のうち未入力の key を UserWarning で警告する。"""
        import warnings

        tpl = self._resolve_template()
        if tpl is None:
            return
        missing = [k for k in tpl.required_conditions if k not in self._conditions]
        if missing:
            warnings.warn(
                f"Record {self._id} ({self._template_name}): "
                f"必須条件が未入力です: {', '.join(missing)}",
                UserWarning,
                stacklevel=3,
            )

    def _compute_indexed_fields(self) -> dict[str, Any]:
        """template.indexed_fields に該当する条件値を idx_<name> で返す。

        Firestore の top-level field として書き出されることで where filter や
        複合 index で使えるようになる。値が None / 未入力なら field を出さない
        (Firestore で null を index しないため)。template 未指定なら空 dict。
        """
        tpl = self._resolve_template()
        if tpl is None:
            return {}
        out: dict[str, Any] = {}
        for name in tpl.indexed_fields:
            value = self._conditions.get(name)
            if value is not None:
                out[f"idx_{name}"] = value
        return out

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
    def updated_by(self) -> str:
        """最終更新者。書き込み前に setter で刻印する。"""
        return self._updated_by

    @updated_by.setter
    def updated_by(self, value: str) -> None:
        # _persist は呼ばない。次の mutation 時にまとめて書かれる
        self._updated_by = value

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
        """実験条件を設定する。

        値はスカラー、(値, 単位) タプル、(値, 単位, 説明) タプルのいずれか。
        template が紐付いていれば alias (旧名・表記揺れ) は正規化された name に変換。
        未定義の key はそのまま保存する。

        Examples:
            exp.conditions(pulseenergy=1e-05)
            exp.conditions(pulseenergy=(1e-05, "J"))
            exp.conditions(pulseenergy=(1e-05, "J", "パルスエネルギー"))
        """
        from labvault.core.units import validate_unit

        tpl = self._resolve_template()
        alias_map = tpl.alias_map() if tpl is not None else {}
        field_unit_map = (
            {f.name: f.unit for f in tpl.condition_fields if f.unit}
            if tpl is not None
            else {}
        )

        for raw_key, val in kwargs.items():
            key = alias_map.get(raw_key, raw_key)
            if isinstance(val, tuple):
                if len(val) == 2:
                    value, unit = val
                    self._conditions[key] = value
                    validate_unit(unit)
                    self._condition_units[key] = unit
                elif len(val) >= 3:
                    value, unit, desc = val[0], val[1], val[2]
                    self._conditions[key] = value
                    validate_unit(unit)
                    self._condition_units[key] = unit
                    self._condition_descriptions[key] = str(desc)
                else:
                    self._conditions[key] = val[0]
            else:
                self._conditions[key] = val
                # template に unit 定義があれば自動補完 (既に設定済なら触らない)
                tu = field_unit_map.get(key)
                if tu and key not in self._condition_units:
                    self._condition_units[key] = tu
        self._persist()
        return self

    def get_conditions(self) -> dict[str, Any]:
        """実験条件を返す。"""
        return dict(self._conditions)

    def get_condition_units(self) -> dict[str, str]:
        """条件の単位マップを返す。"""
        return dict(self._condition_units)

    def get_condition_descriptions(self) -> dict[str, str]:
        """条件の説明マップを返す。"""
        return dict(self._condition_descriptions)

    def get_result_units(self) -> dict[str, str]:
        """結果の単位マップを返す。"""
        return dict(self._result_units)

    def get_result_descriptions(self) -> dict[str, str]:
        """結果の説明マップを返す。"""
        return dict(self._result_descriptions)

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

    # --- 解析 ---

    def run_analysis(
        self,
        fn: Any,
        source_file: str,
        *,
        params: dict[str, Any] | None = None,
        title: str | None = None,
    ) -> Record:
        """解析関数を実行し、結果を解析 Record として保存する。

        解析関数の返り値規約::

            def my_analysis(data: bytes, **params) -> dict:
                return {
                    "results": {"depth": 0.5},           # 必須
                    "files": {"plot.png": png_bytes},     # 任意
                }

        解析 Record (type=analysis) が子として作成され、コード・結果・
        出力ファイルが保存される。測定 Record の results にもキャッシュ
        として書き戻し、``{key}__analysis_id`` で出自を追跡する。

        Args:
            fn: 解析関数 (callable) またはコード文字列 (str)。
            source_file: 入力ファイル名 (self のファイル)。
            params: 解析パラメータ (関数のキーワード引数として渡される)。
            title: 解析 Record のタイトル。省略時は自動生成。

        Returns:
            作成された解析 Record。
        """
        import inspect

        if self._lab is None:
            msg = "Cannot run analysis without a Lab instance"
            raise RuntimeError(msg)

        params = params or {}

        # コード取得
        if callable(fn):
            fn_name = fn.__name__
            try:
                source_code = inspect.getsource(fn)
            except (OSError, TypeError):
                source_code = f"# Could not retrieve source for {fn_name}"
        elif isinstance(fn, str):
            fn_name = "custom"
            source_code = fn
        else:
            msg = f"fn must be callable or str, got {type(fn)}"
            raise TypeError(msg)

        # 入力データ取得
        data = self.get_data(source_file)

        # source_fingerprint (先頭 64KB sha256 + size)
        fingerprint = hashlib.sha256(data[:65536]).hexdigest()[:16] + f":{len(data)}"

        # 関数実行
        if callable(fn):
            output = fn(data, **params)
        else:
            # コード文字列の場合は exec で実行
            local_ns: dict[str, Any] = {}
            exec(source_code, {}, local_ns)
            analyze_fn = local_ns.get("analyze")
            if analyze_fn is None:
                msg = "Code string must define an 'analyze' function"
                raise ValueError(msg)
            output = analyze_fn(data, **params)

        if not isinstance(output, dict) or "results" not in output:
            msg = "Analysis function must return dict with 'results' key"
            raise ValueError(msg)

        result_values: dict[str, Any] = output["results"]
        result_units: dict[str, str] = output.get("units", {})
        output_files: dict[str, bytes] = output.get("files", {})

        # 解析 Record 作成
        ana_title = title or f"analysis:{fn_name}"
        ana = self.sub(ana_title, type="analysis")
        ana.conditions(
            method=fn_name,
            analyzer_type="python",
            source_file=source_file,
            source_fingerprint=fingerprint,
            **params,
        )

        # コードを保存
        ana.add(source_code.encode(), name="analyzer.py", content_type="text/x-python")

        # 結果を解析 Record に保存
        for k, v in result_values.items():
            ana.results[k] = v
        ana._result_units.update(result_units)

        # 出力ファイルを解析 Record に保存
        for fname, fdata in output_files.items():
            ana.add(fdata, name=fname)

        ana.status = "success"

        # 測定 Record に書き戻し (キャッシュ + __analysis_id + units)
        for k, v in result_values.items():
            self.results._data[k] = v
            self.results._data[f"{k}__analysis_id"] = ana.id
        self._result_units.update(result_units)
        self._persist()

        return ana

    # --- ファイル操作 ---

    # --- 新ファイル API (推奨) ---
    #
    # 役割で 3 つに分かれる:
    #   add_file   — 既存ファイル (path) を取り込む
    #   add_bytes  — 生バイト列 (HTTP / バッファ / 装置 API 戻り値) を保存する
    #   add_object — Python オブジェクトを自動変換 (Figure/DataFrame/dict/list/...)
    # 動的に型が変わるループでは put() を使う (3 つに dispatch するシュガー)。
    #
    # 旧 add / save は alias として残す (互換性維持、将来の minor で
    # DeprecationWarning を入れる予定 — CHANGELOG 参照)。

    def add_file(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        content_type: str = "",
    ) -> Record:
        """既存ファイル (装置生バイナリ / ディスク上のファイル) を取り込む。

        Args:
            path: 読み込むファイルのパス。
            name: 保存名 (省略時 path.name)。リネームしたい時のみ指定。
            content_type: MIME。省略時は拡張子から推定。

        冪等: 同一 name + 同一 SHA256 ならスキップ。
        """
        p = Path(path)
        data = p.read_bytes()
        file_name = name or p.name
        if not content_type:
            ct, _ = mimetypes.guess_type(str(p))
            content_type = ct or "application/octet-stream"
        return self._store_bytes(file_name, data, content_type)

    def add_bytes(
        self,
        name: str,
        data: bytes | bytearray | memoryview,
        *,
        content_type: str = "",
    ) -> Record:
        """生バイト列を保存する。HTTP レスポンス / バッファ / エンコード済 str など。

        Args:
            name: 保存名 (必須)。
            data: 保存するバイト列。
            content_type: MIME (省略時 application/octet-stream)。
        """
        return self._store_bytes(
            name,
            bytes(data),
            content_type or "application/octet-stream",
        )

    def add_object(
        self,
        name: str,
        obj: Any,
        *,
        content_type: str = "",
    ) -> Record:
        """Python オブジェクトを自動変換して保存する。

        変換ルール:
        - ``dict`` / ``list`` -> JSON (``.json``)
        - ``str`` -> テキスト (``.txt``)
        - ``bytes`` -> そのままバイナリ
        - ``numpy.ndarray`` -> ``.npy``
        - ``matplotlib.Figure`` -> ``.png``
        - ``pandas.DataFrame`` -> ``.csv``

        Args:
            name: 保存名 (必須)。拡張子が無い場合は型に応じて自動補完。
            obj: 保存対象。
            content_type: MIME (省略時は型から推定)。
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

        return self._store_bytes(name, data, ct)

    def put(
        self,
        target: str | Path | bytes | bytearray | memoryview | Any,
        *,
        name: str | None = None,
        content_type: str = "",
    ) -> Record:
        """型を見て add_file / add_bytes / add_object に dispatch する統一エントリ。

        通常は明示的に ``add_file`` / ``add_bytes`` / ``add_object`` を呼ぶ方が
        読みやすい。``put`` は型が動的に変わる heterogeneous なループや、
        どの method を呼べばよいか迷う場合の便利関数。

        dispatch ルール:
        - ``str`` / ``Path`` -> ``add_file`` (常に path として扱う、無ければ
          FileNotFoundError)
        - ``bytes`` / ``bytearray`` / ``memoryview`` -> ``add_bytes`` (name 必須)
        - その他 (Figure, DataFrame, dict, ndarray など) -> ``add_object`` (name 必須)

        str リテラル保存をしたい場合は ``add_object(name, "...")`` を明示的に呼ぶこと
        (``put`` では str は常に path として解釈される)。
        """
        if isinstance(target, (str, Path)):
            return self.add_file(target, name=name, content_type=content_type)
        if isinstance(target, (bytes, bytearray, memoryview)):
            if name is None:
                msg = (
                    "put(<bytes>, ...) requires name=. "
                    "Use add_bytes(name, data) for an explicit call."
                )
                raise TypeError(msg)
            return self.add_bytes(name, target, content_type=content_type)
        if name is None:
            msg = (
                f"put(<{type(target).__name__}>, ...) requires name=. "
                "Use add_object(name, obj) for an explicit call."
            )
            raise TypeError(msg)
        return self.add_object(name, target, content_type=content_type)

    # --- 旧 API (互換 alias、将来 DeprecationWarning 予定) ---

    def add(
        self,
        source: str | Path | bytes,
        *,
        name: str | None = None,
        content_type: str = "",
    ) -> Record:
        """[Legacy] ファイルを保存する。``add_file`` / ``add_bytes`` の利用を推奨。

        将来の minor リリースで ``DeprecationWarning`` を出す予定 (CHANGELOG 参照)。
        現在は警告なく動作するので既存コードは変更不要。
        """
        if isinstance(source, (str, Path)):
            return self.add_file(source, name=name, content_type=content_type)
        return self.add_bytes(name or "untitled", source, content_type=content_type)

    def _store_bytes(self, name: str, data: bytes, content_type: str) -> Record:
        """ストレージへの実書き込み (全 add_* / put の合流点)。

        冪等: 同一ファイル名 + 同一 SHA256 ならスキップ。
        同一ファイル名で SHA が違えば上書き。
        ``auto_extract_conditions`` を呼ぶので template の file_parsers も起動する。
        """
        sha = hashlib.sha256(data).hexdigest()
        for ref in self._data_refs:
            if ref.name == name and ref.sha256 == sha:
                return self

        storage_path = f"{self._team}/{self._id}/{name}"

        if self._lab and self._lab._storage:
            self._lab._storage.upload(storage_path, data, content_type)

        self._data_refs = [r for r in self._data_refs if r.name != name]
        self._data_refs.append(
            DataRef(
                name=name,
                nextcloud_path=storage_path,
                content_type=content_type,
                size_bytes=len(data),
                sha256=sha,
            )
        )
        self._auto_extract_conditions(name, data)
        self._persist()
        return self

    def _auto_extract_conditions(self, file_name: str, data: bytes) -> None:
        """template の file_parsers を引いて拡張子一致 parser を起動する。

        - template 未指定 / file_parsers 未定義 / 拡張子不一致 → no-op
        - parser_name が PARSER_REGISTRY に未登録 → UserWarning でスキップ
        - parser が例外を投げる → UserWarning でスキップ (add 自体は成功させる)
        - parser が返した key のうち、既に self._conditions に入っているものは
          スキップ (= 手動入力を優先)
        """
        tpl = self._resolve_template()
        if tpl is None or not tpl.file_parsers:
            return

        ext = Path(file_name).suffix.lower()
        target = next(
            (fp for fp in tpl.file_parsers if fp.extension.lower() == ext),
            None,
        )
        if target is None or not target.auto_extract_conditions:
            return

        from labvault.parsers import PARSER_REGISTRY

        parser = PARSER_REGISTRY.get(target.parser_name)
        if parser is None:
            import warnings

            warnings.warn(
                f"file parser {target.parser_name!r} が未登録です "
                f"(template={self._template_name}, file={file_name})",
                UserWarning,
                stacklevel=3,
            )
            return

        try:
            extracted = parser(data, file_name)
        except Exception as e:
            import warnings

            warnings.warn(
                f"file parser {target.parser_name} が {file_name} の解析中に "
                f"失敗しました: {e}",
                UserWarning,
                stacklevel=3,
            )
            return

        if not isinstance(extracted, dict) or not extracted:
            return

        for key, value in extracted.items():
            if value is None:
                continue
            # 手動入力 (=既に conditions に入っている key) は parser 値で上書きしない
            if key not in self._conditions:
                self._conditions[key] = value

    def save(
        self,
        name: str,
        obj: Any,
        *,
        content_type: str = "",
    ) -> Record:
        """[Legacy] Python オブジェクトを保存する。``add_object`` の利用を推奨。

        将来の minor リリースで ``DeprecationWarning`` を出す予定 (CHANGELOG 参照)。
        現在は警告なく動作するので既存コードは変更不要。
        """
        return self.add_object(name, obj, content_type=content_type)

    def add_dir(self, dir_path: str | Path) -> Record:
        """ディレクトリ配下の全ファイルを再帰的に追加する。"""
        root = Path(dir_path)
        if not root.is_dir():
            msg = f"Not a directory: {root}"
            raise NotADirectoryError(msg)
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root)
                self.add_file(p, name=str(rel))
        return self

    def get_data(self, name: str) -> bytes:
        """保存済みファイルのデータをバイナリで取得する。"""
        for ref in self._data_refs:
            if ref.name == name:
                if self._lab and self._lab._storage:
                    result: bytes = self._lab._storage.download(ref.nextcloud_path)
                    return result
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
        # バッファにも書く (データ消失防止)
        if self._lab and self._lab._buffer:
            self._lab._buffer.save_record(
                self._team, self._id, json.dumps(self._to_dict())
            )

    def _to_dict(self) -> dict[str, Any]:
        """永続化用の辞書表現。

        template が紐付いていれば template.indexed_fields の各 key を
        `idx_<name>` として top-level に複製する (Firestore 検索用)。
        """
        base = {
            "id": self._id,
            "team": self._team,
            "title": self._title,
            "type": self._type,
            "status": str(self._status),
            "created_by": self._created_by,
            "created_at": self._created_at.isoformat(),
            "updated_by": self._updated_by,
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
            "condition_units": dict(self._condition_units),
            "condition_descriptions": dict(self._condition_descriptions),
            "results": self._results.to_dict(),
            "result_units": dict(self._result_units),
            "result_descriptions": dict(self._result_descriptions),
            "events": list(self._events),
            "deleted_at": (self._deleted_at.isoformat() if self._deleted_at else None),
            "parent_id": self._parent_id,
            "template": self._template_name,
        }
        # template.indexed_fields の値を idx_<name> として top-level に昇格
        # (Firestore 検索用)。template 未指定 or 値未入力なら何も追加されない。
        base.update(self._compute_indexed_fields())
        return base

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

        rec = cls(
            id=data["id"],
            team=data.get("team", ""),
            title=data.get("title", ""),
            record_type=data.get("type", "experiment"),
            status=data.get("status", "running"),
            created_by=data.get("created_by", ""),
            created_at=(_parse_dt(created_at_raw) if created_at_raw else None),
            updated_by=data.get("updated_by", ""),
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
            template_name=data.get("template"),
            lab=lab,
        )
        rec._condition_units = dict(data.get("condition_units") or {})
        rec._condition_descriptions = dict(data.get("condition_descriptions") or {})
        rec._result_units = dict(data.get("result_units") or {})
        rec._result_descriptions = dict(data.get("result_descriptions") or {})
        return rec


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
