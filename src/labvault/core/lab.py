"""Lab クラス -- チームデータベースのエントリポイント。"""

from __future__ import annotations

import builtins
import datetime as _dt
from datetime import datetime
from typing import Any

from labvault.backends.base import MetadataBackend
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.config import Settings
from labvault.core.exceptions import RecordNotFoundError
from labvault.core.id import generate_id
from labvault.core.record import Record
from labvault.core.types import (
    RecordType,
    Status,
    TemplateV10,
    template_from_dict,
    template_to_dict,
)


def _match_condition(actual: Any, spec: Any) -> bool:
    """条件の一致判定。スカラーは完全一致、dict は範囲演算子。

    Examples:
        _match_condition(20, 20)  # True (完全一致)
        _match_condition(20, {"gte": 10, "lte": 30})  # True (範囲)
        _match_condition(5, {"gt": 10})  # False
    """
    if not isinstance(spec, dict):
        return bool(actual == spec)
    ops = {
        "gte": "__ge__",
        "gt": "__gt__",
        "lte": "__le__",
        "lt": "__lt__",
        "eq": "__eq__",
        "ne": "__ne__",
    }
    for op, method in ops.items():
        if op in spec:
            if actual is None:
                return False
            try:
                if not bool(getattr(actual, method)(spec[op])):
                    return False
            except TypeError:
                return False
    return True


class Lab:
    """チームデータベース。Record の生成・取得・検索を行う。"""

    def __init__(
        self,
        team: str | None = None,
        *,
        user: str | None = None,
        metadata_backend: Any | None = None,
        storage_backend: Any | None = None,
        search_backend: Any | None = None,
        embedding_client: Any | None = None,
    ) -> None:
        settings = Settings()
        self._team = team or settings.team or "default"
        self._user = user or settings.user or ""

        # PAT mode 検出: token + platform_url が揃えば全 backend を Platform* に切替。
        # これにより装置 PC/CI など GCP ADC が使えない環境でも SDK が動作する。
        # 個別 backend が明示指定されていれば常にそれを優先 (テスト互換)。
        platform_client = _build_platform_client(settings)
        # C2 (2026-06-30): Protocol typed にすることで Lab.backend property の
        # 戻り値型推論を強化 (mypy の no-any-return 解消)。
        self._metadata: MetadataBackend = metadata_backend or _auto_metadata(
            settings, platform_client
        )
        self._storage = storage_backend or _auto_storage(
            settings, platform_client, team=self._team
        )
        self._search = search_backend or _auto_search(settings, platform_client)
        self._embedding = embedding_client or _auto_embedding(
            settings, platform_client, team=self._team
        )
        self._settings = settings
        self._active_tracker: Any | None = None
        self._buffer: Any | None = None
        # template lookup の簡易キャッシュ。Record._to_dict が _persist のたびに
        # 引くので、毎回 backend に問い合わせると遅い。define_template で無効化。
        self._template_cache: dict[str, TemplateV10] = {}
        # 全 template の indexed_fields の union。Lab.search / Lab.list で
        # conditions の key が含まれているか判定し、含まれていれば Firestore
        # 側に idx_<key> として push down するために使う。lazy build。
        self._indexed_keys_cache: set[str] | None = None
        self._sync_manager: Any | None = None

        if settings.auto_sync:
            self._init_sync()

    # --- Record 生成 ---

    def new(
        self,
        title: str,
        *,
        type: str | RecordType = RecordType.EXPERIMENT,
        template: str | None = None,
        tags: list[str] | None = None,
        sample: str | None = None,
        auto_log: bool = True,
        created_by: str | None = None,
        **conditions: Any,
    ) -> Record:
        """新しいレコードを作成する。

        Args:
            title: レコードタイトル。
            type: レコードタイプ。
            template: テンプレート名 (M2 以降)。
            tags: 初期タグ。
            sample: サンプルレコード ID (link 自動追加)。
            auto_log: IPython hooks 有効化 (M2 以降)。
            created_by: 作成者識別子。省略時は Settings の user を使用。
            **conditions: 実験条件。
        """
        record_id = self._generate_unique_id()
        record_type = str(type)

        # template が指定されていれば、default_tags / type / 必須条件チェック等のための
        # 紐付けを行う。template を見つけ次第 backend にも upsert する (冪等)。
        resolved_template: TemplateV10 | None = None
        if template:
            resolved_template = self.get_template(template)
            if resolved_template is None:
                msg = (
                    f"template {template!r} not found. "
                    "ビルトイン (XRD/SEM/SQUID/TEM/Raman) もしくは "
                    "lab.define_template(...) で定義した名前を指定してください。"
                )
                raise ValueError(msg)
            # template の type / default_tags をマージ。明示指定が優先。
            if type == RecordType.EXPERIMENT and resolved_template.type:
                record_type = resolved_template.type
            merged_tags = list(tags) if tags else []
            for t in resolved_template.default_tags:
                if t not in merged_tags:
                    merged_tags.append(t)
            tags = merged_tags

        rec = Record(
            id=record_id,
            team=self._team,
            title=title,
            record_type=record_type,
            status=Status.RUNNING,
            created_by=created_by if created_by is not None else self._user,
            tags=tags,
            # conditions は下で template alias を適用してから conditions() で書く
            conditions_data=None,
            template_name=resolved_template.name if resolved_template else None,
            lab=self,
        )

        # conditions は template の alias / unit が効いた状態で書きたいので、
        # Record 生成後に conditions() メソッド経由で渡す。
        if conditions:
            rec.conditions(**conditions)

        self._metadata.create_record(self._team, rec._to_dict())

        # 検索インデックスに追加
        self._index_record(rec)

        if sample:
            rec.link(sample, "measured_on")

        if auto_log:
            self._activate_tracker(rec)

        return rec

    # --- テンプレート API ---

    def define_template(self, template: TemplateV10) -> None:
        """テンプレートを定義 / 上書き保存する。

        backend.save_template(team, name, dict) に永続化される。同名 template が
        既にあれば内容を置き換える (冪等)。in-memory キャッシュも上書きする。
        """
        self._metadata.save_template(
            self._team, template.name, template_to_dict(template)
        )
        self._template_cache[template.name] = template
        # indexed_keys は新しい template の追加で増える可能性があるので invalidate。
        # 次回 _get_indexed_keys() で再構築される。
        self._indexed_keys_cache = None

    def templates(self) -> builtins.list[TemplateV10]:
        """この team に登録された template の一覧。

        backend にも未登録なビルトインは含まれない点に注意 (initial state では
        空リスト)。ビルトインは `lab.new(title, template="XRD")` で初めて参照
        された時に backend に lazy save される。
        """
        raw_list = self._metadata.list_templates(self._team)
        out: builtins.list[TemplateV10] = []
        for raw in raw_list:
            try:
                out.append(template_from_dict(raw))
            except (KeyError, TypeError):
                continue
        return out

    def get_template(self, name: str) -> TemplateV10 | None:
        """名前で template を取得する (見つからなければ None)。

        探索順: in-memory cache → backend に保存済 → ビルトイン (BUILTIN_TEMPLATES)。
        ビルトインがヒットした場合は backend に自動 upsert する (次回参照を高速化)。
        Record._persist のたびに引かれるので cache hit パスが効く。
        """
        cached = self._template_cache.get(name)
        if cached is not None:
            return cached

        raw = self._metadata.get_template(self._team, name)
        if raw is not None:
            try:
                tpl = template_from_dict(raw)
                self._template_cache[name] = tpl
                self._indexed_keys_cache = None
                return tpl
            except (KeyError, TypeError):
                pass

        import contextlib

        from labvault.core.builtin_templates import BUILTIN_TEMPLATES

        builtin = BUILTIN_TEMPLATES.get(name)
        if builtin is None:
            return None
        # 初回参照時に backend に lazy save (冪等)。backend 側の不具合があっても
        # in-memory のビルトインは返したいので、ここでは黙って吸収する。
        # define_template が cache 更新も兼ねる。
        with contextlib.suppress(Exception):
            self.define_template(builtin)
        # define_template が失敗しても cache にだけは入れて返す
        self._template_cache[name] = builtin
        self._indexed_keys_cache = None
        return builtin

    def _get_indexed_keys(self) -> set[str]:
        """この team で indexed_fields に登録されている key の union を返す。

        Lab.search / Lab.list で conditions の key がこの集合に含まれていれば、
        Firestore に `idx_<key>` として push down できる (PR #11 で追加された
        top-level promotion 機能と対になる)。含まれない key は post-filter。

        cache は define_template / get_template で invalidate される。
        """
        if self._indexed_keys_cache is not None:
            return self._indexed_keys_cache

        keys: set[str] = set()
        # in-memory cache 分
        for tpl in self._template_cache.values():
            keys.update(tpl.indexed_fields)
        # backend 側 (まだ cache に来てない template も含む)
        try:
            for raw in self._metadata.list_templates(self._team):
                for k in raw.get("indexed_fields") or []:
                    if isinstance(k, str):
                        keys.add(k)
        except Exception:
            pass
        self._indexed_keys_cache = keys
        return keys

    # --- Record 取得 ---

    def get(
        self,
        record_id: str,
        *,
        auto_log: bool = False,
    ) -> Record:
        """ID でレコードを取得する。

        Args:
            record_id: レコード ID。
            auto_log: IPython hooks を再起動 (M2 以降)。

        Raises:
            RecordNotFoundError: レコードが見つからない。
        """
        from labvault.core.id import normalize_id

        rid = normalize_id(record_id)
        data = self._metadata.get_record(self._team, rid)
        if data is None:
            raise RecordNotFoundError(rid)

        rec = Record._from_dict(data, lab=self)

        if auto_log:
            self._activate_tracker(rec)

        return rec

    # --- 一覧 ---

    def list(
        self,
        *,
        tags: builtins.list[str] | None = None,
        status: str | Status | None = None,
        type: str | RecordType | None = None,
        created_by: str | None = None,
        parent_id: str | None | object = "__unset__",
        conditions: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> builtins.list[Record]:
        """レコード一覧を取得する。

        Args:
            parent_id: 親 record id で絞り込む。``"__unset__"`` sentinel は
                フィルタ無し (全レコード)、``None`` は root only (親無し)。
                Backend Protocol の `list_records(parent_id=)` にそのまま
                pass-through する。
            conditions: scalar の等値フィルタ。indexed_fields に挙がっている
                key は Firestore に push down される (`idx_<key>` で where
                filter)。dict 値や indexed でない key は post-filter。
        """
        status_str = str(status) if status else None
        type_str = str(type) if type else None

        push_down: dict[str, Any] | None = None
        post_filter: dict[str, Any] = {}
        if conditions:
            indexed_keys = self._get_indexed_keys()
            push_down = {}
            for key, value in conditions.items():
                if (
                    key in indexed_keys
                    and not isinstance(value, dict)
                    and isinstance(value, (str, int, float, bool))
                ):
                    push_down[f"idx_{key}"] = value
                else:
                    post_filter[key] = value
            if not push_down:
                push_down = None

        # push down が効いていれば backend 側で絞り込まれているはずだが、
        # 念のため多めに取って post-filter する (Platform backend がサーバー未
        # 対応な場合の保険)。
        fetch_limit = limit * 5 if conditions else limit

        rows = self._metadata.list_records(
            self._team,
            tags=tags,
            status=status_str,
            record_type=type_str,
            created_by=created_by,
            parent_id=parent_id,
            conditions=push_down,
            limit=fetch_limit,
            offset=offset,
        )

        results: builtins.list[Record] = []
        for r in rows:
            rec = Record._from_dict(r, lab=self)
            if conditions:
                rec_cond = rec.get_conditions()
                if not all(
                    _match_condition(rec_cond.get(k), v) for k, v in conditions.items()
                ):
                    continue
            results.append(rec)
            if len(results) >= limit:
                break
        return results

    def recent(self, n: int = 10) -> builtins.list[Record]:
        """最新 n 件を返す。"""
        return self.list(limit=n)

    def today(self) -> builtins.list[Record]:
        """今日作成されたレコードを返す。"""
        now = datetime.now(_dt.UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        all_records = self.list(limit=1000)
        return [r for r in all_records if r.created_at >= start]

    # --- 検索 ---

    def search(
        self,
        query: str,
        *,
        tags: builtins.list[str] | None = None,
        status: str | Status | None = None,
        type: str | RecordType | None = None,
        parent_id: str | None = None,
        conditions: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> builtins.list[Record]:
        """レコードを検索する。Embedding があればセマンティック検索。

        Args:
            query: 検索クエリ。
            tags: タグでフィルタ。
            status: ステータスでフィルタ。
            type: レコードタイプでフィルタ。
            parent_id: 親レコード ID でフィルタ。
            conditions: 条件でフィルタ (例: {"power": 20})。
            limit: 最大件数。
        """
        filters: dict[str, Any] = {}
        if tags:
            filters["tags"] = tags
        if status:
            filters["status"] = str(status)
        if type:
            filters["type"] = str(type)

        # conditions のうち template.indexed_fields に挙がっている key は
        # `idx_<key>` として SearchBackend に push down する (Firestore の
        # where 句に乗る)。範囲指定 (dict 値) や indexed でない key は
        # post-filter のまま。push down した key も最終結果には post-filter で
        # 念のため再チェックする (Platform backend がサーバー未対応の場合の
        # 正確性保証のため)。
        if conditions:
            indexed_keys = self._get_indexed_keys()
            for key, value in conditions.items():
                if (
                    key in indexed_keys
                    and not isinstance(value, dict)
                    and isinstance(value, (str, int, float, bool))
                ):
                    filters[f"idx_{key}"] = value

        # Embedding が利用可能ならクエリを embed
        import contextlib

        query_embedding: builtins.list[float] | None = None
        if self._embedding is not None:
            with contextlib.suppress(Exception):
                query_embedding = self._embedding.embed(query)

        # 条件フィルタは後処理なので多めに取得
        fetch_limit = limit * 5 if conditions or parent_id else limit

        hits = self._search.search(
            self._team,
            query,
            embedding=query_embedding,
            filters=filters if filters else None,
            limit=fetch_limit,
        )
        results: builtins.list[Record] = []
        for hit in hits:
            rid = hit["record_id"]
            data = self._metadata.get_record(self._team, rid)
            if data and data.get("deleted_at") is None:
                rec = Record._from_dict(data, lab=self)

                # parent_id フィルタ
                if parent_id is not None and rec.parent_id != parent_id:
                    continue

                # 条件フィルタ
                if conditions:
                    rec_cond = rec.get_conditions()
                    if not all(
                        _match_condition(rec_cond.get(k), v)
                        for k, v in conditions.items()
                    ):
                        continue

                results.append(rec)
                if len(results) >= limit:
                    break
        return results

    # --- 削除 / 復元 ---

    def delete(self, record_id: str) -> None:
        """ソフトデリート (deleted_at を設定)."""
        from labvault.core.id import normalize_id

        rid = normalize_id(record_id)
        data = self._metadata.get_record(self._team, rid)
        if data is None:
            raise RecordNotFoundError(rid)

        data["deleted_at"] = datetime.now(_dt.UTC).isoformat()
        self._metadata.update_record(self._team, rid, data)

    def trash(self) -> builtins.list[Record]:
        """削除済みレコードを返す。"""
        # list_records は deleted_at 非 None を除外するため、
        # InMemory の内部 _records を直接参照する (M1 簡易実装)。
        results: builtins.list[Record] = []
        if hasattr(self._metadata, "_records"):
            team_records = self._metadata._records.get(self._team, {})
            for data in team_records.values():
                if data.get("deleted_at") is not None:
                    results.append(Record._from_dict(data, lab=self))
        return results

    def restore(self, record_id: str) -> Record:
        """削除を取り消す。"""
        from labvault.core.id import normalize_id

        rid = normalize_id(record_id)

        # 削除済みも含めて取得する必要がある
        data: dict[str, Any] | None = None
        if hasattr(self._metadata, "_records"):
            data = self._metadata._records.get(self._team, {}).get(rid)

        if data is None:
            data = self._metadata.get_record(self._team, rid)

        if data is None:
            raise RecordNotFoundError(rid)

        data["deleted_at"] = None
        self._metadata.update_record(self._team, rid, data)

        return Record._from_dict(data, lab=self)

    # --- コンテキストマネージャ ---

    @property
    def team(self) -> str:
        """この Lab が紐付いている team_id。"""
        return self._team

    @property
    def backend(self) -> MetadataBackend:
        """metadata backend を Protocol typed で返す (admin / raw access 用)。

        通常の record CRUD は ``Lab.get`` / ``Lab.list`` / ``Lab.new`` 等の
        public API を使うこと。``Lab.backend`` は ``platform/backend/routers
        /metadata.py`` のような「Protocol を 1:1 で晒す admin endpoint」
        専用の escape hatch。private な ``_metadata`` を直接参照するより
        意図 (= raw access していることが明示) が伝わる。
        """
        return self._metadata

    def get_cell_logs(
        self, record_id: str, *, limit: int = 100
    ) -> builtins.list[dict[str, Any]]:
        """record に紐付く cell log の一覧を取得する (cell_number 昇順)。

        Protocol の ``MetadataBackend.get_cell_logs`` を team 引数を埋めて
        薄く wrap するだけ。SDK / platform 両者がこの public 経路を使う
        ことで private ``_metadata`` 参照を避ける (C2)。
        """
        return self._metadata.get_cell_logs(self._team, record_id, limit=limit)

    def save_cell_log(self, record_id: str, data: dict[str, Any]) -> None:
        """cell log を保存する。

        Notebook hooks (``tracking.CellTracker``) からの呼び出し向け薄
        ラッパ。``data`` は ``CellLog._to_dict()`` 等の dict (`cell_id` /
        `cell_number` / `code` / `executed_at` / `error` etc.)。
        """
        self._metadata.save_cell_log(self._team, record_id, data)

    def get_usage(
        self,
        *,
        created_by: str | None = None,
        max_records: int = 20000,
    ) -> dict[str, Any]:
        """team の storage 利用量を集計する (2026-07-01)。

        `data_refs[].size_bytes` を record 全件走査して合算し、以下を返す:

        - ``total_records``: 削除されていない record 数
        - ``total_files``: 添付ファイル総数 (data_refs entries)
        - ``total_bytes``: 添付ファイルの size_bytes 合計
        - ``by_creator``: ``{email: {records, files, bytes}}``
        - ``by_extension``: ``{ext: {files, bytes}}`` (先頭 20 拡張子)
        - ``by_type``: ``{record_type: records}``

        Args:
            created_by: email 完全一致で絞り込む (省略時は team 全体)
            max_records: 走査上限 (安全弁)。大きい team では調整推奨。

        Firestore の集計 API は限定的なので client-side 集計。5,000〜10,000
        records で数秒。MCP tool / CLI ``labvault usage`` から呼ぶ想定。
        """
        from collections import Counter, defaultdict

        target = (created_by or "").strip().lower() or None
        rows = self._metadata.list_records(
            self._team,
            created_by=created_by,
            parent_id="__unset__",  # parent フィルタなし = 全 record
            limit=max_records,
        )

        total_records = 0
        total_files = 0
        total_bytes = 0
        by_creator: dict[str, dict[str, int]] = defaultdict(
            lambda: {"records": 0, "files": 0, "bytes": 0}
        )
        ext_files: Counter[str] = Counter()
        ext_bytes: Counter[str] = Counter()
        by_type: Counter[str] = Counter()

        for row in rows:
            if row.get("deleted_at"):
                continue
            cb_raw = row.get("created_by") or ""
            cb = cb_raw.strip().lower() if isinstance(cb_raw, str) else ""
            if target is not None and cb != target:
                continue
            total_records += 1
            by_type[row.get("type") or "<unknown>"] += 1
            creator_key = cb_raw or "<unknown>"
            by_creator[creator_key]["records"] += 1
            for ref in row.get("data_refs") or []:
                if not isinstance(ref, dict):
                    continue
                size = int(ref.get("size_bytes") or 0)
                total_files += 1
                total_bytes += size
                by_creator[creator_key]["files"] += 1
                by_creator[creator_key]["bytes"] += size
                name = ref.get("name") or ""
                if isinstance(name, str) and "." in name:
                    ext = name.rsplit(".", 1)[-1].lower()
                else:
                    ext = "<no-ext>"
                ext_files[ext] += 1
                ext_bytes[ext] += size

        top_ext = ext_files.most_common(20)
        return {
            "team": self._team,
            "total_records": total_records,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "by_creator": dict(by_creator),
            "by_extension": {
                ext: {"files": count, "bytes": ext_bytes[ext]}
                for ext, count in top_ext
            },
            "by_type": dict(by_type),
        }

    @property
    def sync_status(self) -> dict[str, Any]:
        """同期状態を返す。"""
        if self._sync_manager is None:
            return {
                "pending": 0,
                "last_error": None,
                "last_sync": 0.0,
                "is_running": False,
            }
        status: dict[str, Any] = self._sync_manager.sync_status
        return status

    def close(self) -> None:
        """リソースを解放する。"""
        if self._active_tracker is not None:
            self._active_tracker.deactivate()
            self._active_tracker = None
        if self._sync_manager is not None:
            self._sync_manager.stop(flush=True)
            self._sync_manager = None
        if self._buffer is not None:
            self._buffer.close()
            self._buffer = None

    def __enter__(self) -> Lab:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    # --- ヘルパー ---

    def _generate_unique_id(self, max_attempts: int = 100) -> str:
        """衝突チェック付き ID 生成。"""
        for _ in range(max_attempts):
            rid = generate_id()
            if self._metadata.get_record(self._team, rid) is None:
                return rid
        msg = "Failed to generate unique ID"
        raise RuntimeError(msg)

    def _index_record(self, record: Record) -> None:
        """レコードを検索インデックスに追加する。"""
        from labvault.backends.embedding import build_embedding_text

        text = build_embedding_text(record._to_dict())

        import contextlib

        embedding: list[float] | None = None
        if self._embedding is not None:
            with contextlib.suppress(Exception):
                embedding = self._embedding.embed(text)

        self._search.index(self._team, record.id, text, embedding=embedding)

    def _init_sync(self) -> None:
        """BufferDatabase + SyncManager を初期化する。"""
        from labvault.buffer.database import BufferDatabase
        from labvault.buffer.sync import SyncManager

        db_path = self._settings.buffer_dir / f"{self._team}.db"
        self._buffer = BufferDatabase(db_path)
        self._sync_manager = SyncManager(
            buffer_db=self._buffer,
            metadata_backend=self._metadata,
            storage_backend=self._storage,
            interval_sec=self._settings.sync_interval_sec,
            cleanup=self._settings.buffer_cleanup,
            retention_days=self._settings.buffer_retention_days,
        )
        self._sync_manager.start()

    def _activate_tracker(self, record: Record) -> None:
        """CellTracker を起動する (IPython 環境の場合のみ)."""
        from labvault.tracking.cell_tracker import CellTracker

        if self._active_tracker is not None:
            self._active_tracker.deactivate()

        tracker = CellTracker(record, self)
        tracker.activate()

        if tracker._active:
            self._active_tracker = tracker

    def __repr__(self) -> str:
        return f"Lab(team={self._team!r})"


def _build_platform_client(settings: Settings) -> Any | None:
    """PAT mode 用の PlatformClient を組む。

    token + platform_url が両方あるときだけ生成 (これが PAT mode の trigger)。
    どちらか欠けたら None を返し、各 _auto_* は従来の direct backend を返す。

    片方だけ設定されている場合: token だけ → URL 不明、platform_url だけ → ADC で
    既に動くので Platform 強制不要、と解釈し Platform mode には入らない。
    """
    if not settings.token or not settings.platform_url:
        return None
    from labvault.backends.platform_client import PlatformClient

    return PlatformClient(settings.platform_url, token=settings.token)


def _auto_metadata(settings: Settings, client: Any | None = None) -> Any:
    """設定に応じてメタデータバックエンドを自動選択する。

    PAT mode (client が渡されたとき) は PlatformMetadataBackend を返す。
    """
    if client is not None:
        from labvault.backends.platform_metadata import PlatformMetadataBackend

        return PlatformMetadataBackend(client)
    if settings.gcp_project:
        from labvault.backends.firestore import FirestoreMetadataBackend

        return FirestoreMetadataBackend(
            project=settings.gcp_project,
            database=settings.firestore_database,
        )
    return InMemoryMetadataBackend()


def _auto_storage(
    settings: Settings, client: Any | None = None, *, team: str = ""
) -> Any:
    """設定に応じてストレージバックエンドを自動選択する。

    優先順位:
    1. PAT mode (client) → PlatformStorage (file ops を backend HTTP 経由)
    2. LABVAULT_PLATFORM_URL がある + ADC → platform 経由で creds 取得 → 直 Nextcloud
    3. LABVAULT_NEXTCLOUD_PASSWORD が .env にある → 直接接続 (開発用)
    4. どれも無ければ InMemory
    """
    if client is not None:
        from labvault.backends.platform_storage import PlatformStorage

        return PlatformStorage(client, team=team or settings.team or "default")

    if settings.platform_url:
        try:
            from labvault.backends.nextcloud import NextcloudStorage
            from labvault.backends.platform_client import PlatformClient

            creds = PlatformClient(settings.platform_url).get_nextcloud_credentials(
                team=settings.team,
            )
            return NextcloudStorage(
                url=creds.get("url") or settings.nextcloud_url,
                user=creds.get("username") or settings.nextcloud_user,
                password=creds["password"],
                group_folder=creds.get("group_folder")
                or settings.nextcloud_group_folder,
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).warning(
                "platform credentials fetch failed: %s; falling back", e
            )

    if (
        settings.nextcloud_url
        and settings.nextcloud_user
        and settings.nextcloud_password
    ):
        from labvault.backends.nextcloud import NextcloudStorage

        return NextcloudStorage(
            url=settings.nextcloud_url,
            user=settings.nextcloud_user,
            password=settings.nextcloud_password,
            group_folder=settings.nextcloud_group_folder,
        )
    return InMemoryStorageBackend()


def _auto_embedding(
    settings: Settings, client: Any | None = None, *, team: str = ""
) -> Any | None:
    """設定に応じて EmbeddingClient を自動作成する。

    PAT mode (client) → PlatformEmbedding (backend で Vertex AI を呼ぶ)。
    """
    if client is not None:
        from labvault.backends.platform_search import PlatformEmbedding

        return PlatformEmbedding(client, team=team or settings.team or "default")
    if settings.gcp_project:
        try:
            from labvault.backends.embedding import EmbeddingClient

            return EmbeddingClient(project=settings.gcp_project)
        except Exception:
            return None
    return None


def _auto_search(settings: Settings, client: Any | None = None) -> Any:
    """設定に応じて検索バックエンドを自動選択する。

    PAT mode (client) → PlatformSearch (backend HTTP)。
    なければ Firestore Vector Search、それも無ければ InMemory。
    """
    if client is not None:
        from labvault.backends.platform_search import PlatformSearch

        return PlatformSearch(client)
    if settings.gcp_project:
        from labvault.backends.firestore_search import FirestoreSearchBackend

        return FirestoreSearchBackend(
            project=settings.gcp_project,
            database=settings.firestore_database,
        )
    return InMemorySearchBackend()
