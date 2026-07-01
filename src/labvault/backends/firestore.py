"""Firestore メタデータバックエンド。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FirestoreMetadataBackend:
    """Firestore によるメタデータ永続化。

    ドキュメント構造:
        teams/{team}/records/{record_id}
        teams/{team}/records/{record_id}/cell_logs/{cell_id}
        teams/{team}/templates/{name}
    """

    def __init__(
        self,
        project: str = "",
        database: str = "(default)",
    ) -> None:
        self._project = project
        self._database = database
        self._db: Any | None = None

    def _get_db(self) -> Any:
        """Firestore クライアントを遅延初期化する。"""
        if self._db is None:
            from google.cloud import firestore

            self._db = firestore.Client(
                project=self._project or None,
                database=self._database,
            )
        return self._db

    def _records_ref(self, team: str) -> Any:
        return self._get_db().collection("teams").document(team).collection("records")

    # --- Record CRUD ---

    def create_record(self, team: str, data: dict[str, Any]) -> None:
        """レコードを作成する。"""
        record_id = data["id"]
        self._records_ref(team).document(record_id).set(data)

    def get_record(self, team: str, record_id: str) -> dict[str, Any] | None:
        """レコードを取得する。"""
        doc = self._records_ref(team).document(record_id).get()
        if not doc.exists:
            return None
        result: dict[str, Any] | None = doc.to_dict()
        if result is None:
            return None
        # deleted_at が設定されている場合は None を返す (ソフトデリート)
        if result.get("deleted_at") is not None:
            return None
        return result

    def update_record(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        """レコードを更新する。

        Firestore の ``update()`` を使うことで、top-level field ごとに
        値を置換する (nested map は **deep-merge せず全置換**)。これは
        `Record._to_dict()` が常に完全な state を返す前提と整合する。

        **S1-DATA1 (2026-06-29 hot-fix)**: 以前は ``set(data, merge=True)``
        を使っていたが、Firestore SDK の merge=True は nested map (例:
        ``shares``) を **field-path レベルで deep-merge** し、新 dict に
        含まれない subfield (revoke した email 等) を温存する仕様だった。
        結果として ``revoke_share`` が永続化されず、URL 直アクセスで
        revoke 済 user が record を読めてしまう authorization leak が発生
        していた。``update()`` は top-level field 単位の置換になるので
        この問題を構造的に解決する。

        ``firestore_search.py`` が別経路で書き込む ``embedding`` /
        ``embedding_text`` field は data dict に含まれないため、
        ``update()`` 経由でも触られず温存される (regression なし)。

        ``NotFound`` (= doc が無い) は通常 ``create_record`` 経由で
        先に作成しているので起きないが、buffer 復元 / legacy 経路の
        ために ``set()`` で fallback する。

        google package を遅延参照する形にして、``[gcp]`` extra 未インス
        トール環境 (CI minimal) でも import-time エラーを起こさない
        (Firestore 系 unit test は ``_get_db`` を mock するので
        ``ref.update`` も MagicMock 経由で成功し、本 fallback path は
        実 Firestore でのみ通る)。
        """
        ref = self._records_ref(team).document(record_id)
        try:
            ref.update(data)
        except Exception as e:
            # NotFound のみ fallback (他例外は re-raise)。google package を
            # 遅延 import して [gcp] extra 未インストール環境でも壊さない。
            try:
                from google.api_core.exceptions import NotFound
            except ImportError:
                raise e from None
            if not isinstance(e, NotFound):
                raise
            ref.set(data)

    def delete_record(self, team: str, record_id: str) -> None:
        """レコードを物理削除する。"""
        self._records_ref(team).document(record_id).delete()

    def list_records(
        self,
        team: str,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        record_type: str | None = None,
        created_by: str | None = None,
        parent_id: str | None = "__unset__",
        conditions: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """レコード一覧を取得する。

        conditions は top-level field の等値フィルタ (例: ``{"idx_target": "Cu"}``)。
        対応する Firestore 複合 index が `firestore.indexes.json` に宣言されて
        いる必要がある。
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        q: Any = self._records_ref(team)

        # ソフトデリート除外
        q = q.where(filter=FieldFilter("deleted_at", "==", None))

        # parent_id フィルタ (ルートレコードのみ等)
        if parent_id != "__unset__":
            q = q.where(filter=FieldFilter("parent_id", "==", parent_id))

        if tags:
            q = q.where(filter=FieldFilter("tags", "array_contains_any", tags))
        if status:
            q = q.where(filter=FieldFilter("status", "==", status))
        if record_type:
            q = q.where(filter=FieldFilter("type", "==", record_type))
        if created_by:
            q = q.where(filter=FieldFilter("created_by", "==", created_by))
        if conditions:
            for key, value in conditions.items():
                q = q.where(filter=FieldFilter(key, "==", value))

        q = q.order_by("updated_at", direction="DESCENDING")

        if offset:
            q = q.offset(offset)
        q = q.limit(limit)

        return [doc.to_dict() for doc in q.stream()]

    def list_records_shared_with(
        self,
        email: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """email に共有された record を全 team 横断で取得する (S1).

        `collection_group('records')` で全 team の records を 1 クエリで
        走査し、`shared_with_emails` array-contains と `deleted_at == None`
        で絞り込んで `updated_at` 降順に返す。Firestore 側で複合 index
        `(deleted_at, shared_with_emails, updated_at DESC)` を `firestore.indexes.json`
        に宣言しておく必要がある。
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        target = (email or "").strip().lower()
        if not target:
            return []

        q: Any = self._get_db().collection_group("records")
        q = q.where(filter=FieldFilter("deleted_at", "==", None))
        q = q.where(filter=FieldFilter("shared_with_emails", "array_contains", target))
        q = q.order_by("updated_at", direction="DESCENDING")
        if offset:
            q = q.offset(offset)
        q = q.limit(limit)
        return [doc.to_dict() for doc in q.stream()]

    # --- CellLog ---

    def save_cell_log(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        """セルログを保存する。cell_id をドキュメント ID とする。"""
        cell_id = data.get("cell_id", "")
        if not cell_id:
            import uuid

            cell_id = uuid.uuid4().hex
            data["cell_id"] = cell_id

        self._records_ref(team).document(record_id).collection("cell_logs").document(
            cell_id
        ).set(data)

    def get_cell_logs(
        self,
        team: str,
        record_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """セルログを取得する (cell_number 昇順)."""
        q = (
            self._records_ref(team)
            .document(record_id)
            .collection("cell_logs")
            .order_by("cell_number")
            .limit(limit)
        )
        return [doc.to_dict() for doc in q.stream()]

    # --- Template ---

    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None:
        """テンプレートを保存する。"""
        self._get_db().collection("teams").document(team).collection(
            "templates"
        ).document(name).set(data)

    def get_template(self, team: str, name: str) -> dict[str, Any] | None:
        """テンプレートを取得する。"""
        doc = (
            self._get_db()
            .collection("teams")
            .document(team)
            .collection("templates")
            .document(name)
            .get()
        )
        return doc.to_dict() if doc.exists else None

    def list_templates(self, team: str) -> list[dict[str, Any]]:
        """テンプレート一覧を取得する。"""
        docs = (
            self._get_db()
            .collection("teams")
            .document(team)
            .collection("templates")
            .stream()
        )
        return [doc.to_dict() for doc in docs]

    # --- Share event 監査 log (2026-07-01) ---

    def _share_events_ref(self, team: str) -> Any:
        """``teams/{team}/share_events`` collection ref."""
        return (
            self._get_db()
            .collection("teams")
            .document(team)
            .collection("share_events")
        )

    def append_share_event(self, team: str, event: dict[str, Any]) -> None:
        """1 event を追記する。auto ID + server timestamp。

        ``at`` field は呼び出し側が set した datetime をそのまま保存する
        (SERVER_TIMESTAMP に置き換えない): 単一 tx 内で ordering を
        安定させるため呼び出し側で 1 秒未満の精度で set する想定。
        """
        self._share_events_ref(team).add(event)

    def list_share_events(
        self,
        team: str,
        record_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """record 単位で新しい順に返す。

        Firestore composite index: ``record_id ASC, at DESC``
        (`firestore.indexes.json` に定義)。
        """
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = (
            self._share_events_ref(team)
            .where(filter=FieldFilter("record_id", "==", record_id))
            .order_by("at", direction="DESCENDING")
            .limit(limit)
        )
        return [doc.to_dict() for doc in q.stream()]
