"""Firestore Vector Search バックエンド。

Record ドキュメントに embedding ベクトルを書き、find_nearest で KNN 検索する。
FirestoreMetadataBackend と同じコレクション (teams/{team}/records) を使う。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FirestoreSearchBackend:
    """Firestore Vector Search による検索。"""

    def __init__(
        self,
        project: str = "",
        database: str = "(default)",
    ) -> None:
        self._project = project
        self._database = database
        self._db: Any | None = None

    def _get_db(self) -> Any:
        if self._db is None:
            from google.cloud import firestore

            self._db = firestore.Client(
                project=self._project or None,
                database=self._database,
            )
        return self._db

    def _records_ref(self, team: str) -> Any:
        return self._get_db().collection("teams").document(team).collection("records")

    def index(
        self,
        team: str,
        record_id: str,
        text: str,
        embedding: list[float] | None = None,
    ) -> None:
        """record ドキュメントの embedding フィールドを更新する。

        embedding が無い場合は noop (EmbeddingClient が未設定の環境)。
        """
        if embedding is None:
            return
        from google.cloud.firestore_v1.vector import Vector

        self._records_ref(team).document(record_id).set(
            {
                "embedding": Vector(embedding),
                "embedding_text": text,
            },
            merge=True,
        )

    def search(
        self,
        team: str,
        query: str,
        *,
        embedding: list[float] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """ベクトル近傍検索。embedding 必須 (無ければ空リスト)。"""
        if embedding is None:
            return []

        from google.cloud.firestore_v1.base_query import FieldFilter
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
        from google.cloud.firestore_v1.vector import Vector

        q: Any = self._records_ref(team)
        q = q.where(filter=FieldFilter("deleted_at", "==", None))
        if filters:
            for key in ("status", "type"):
                if key in filters:
                    q = q.where(filter=FieldFilter(key, "==", filters[key]))
            # tags フィルタ等は post-filter で対応するため find_nearest 後で弾く

        q = q.find_nearest(
            vector_field="embedding",
            query_vector=Vector(embedding),
            distance_measure=DistanceMeasure.COSINE,
            limit=limit,
        )

        results: list[dict[str, Any]] = []
        for doc in q.stream():
            d = doc.to_dict() or {}
            # tags フィルタの post-filter
            if filters and "tags" in filters:
                want = set(filters["tags"])
                have = set(d.get("tags") or [])
                if not (want & have):
                    continue
            results.append(
                {
                    "record_id": doc.id,
                    "text": d.get("embedding_text", ""),
                    "score": 1.0,
                }
            )
        return results

    def delete_index(self, team: str, record_id: str) -> None:
        """embedding フィールドをクリアする。document 自体は残す。"""
        from google.cloud.firestore_v1 import DELETE_FIELD

        self._records_ref(team).document(record_id).update(
            {
                "embedding": DELETE_FIELD,
                "embedding_text": DELETE_FIELD,
            }
        )
