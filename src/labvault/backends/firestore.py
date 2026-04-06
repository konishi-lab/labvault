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
        """レコードを更新する。"""
        self._records_ref(team).document(record_id).set(data, merge=True)

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
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """レコード一覧を取得する。"""
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
