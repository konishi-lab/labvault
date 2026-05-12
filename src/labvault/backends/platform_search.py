"""HTTP-based search backend (PAT-friendly)。

PAT 認証で動く SDK 用の SearchBackend / EmbeddingClient 実装。直接 Firestore
Vector Search や Vertex AI Embedding を呼ばず、labvault platform backend の
``/api/metadata/search/*`` / ``/api/metadata/embedding`` 経由でアクセスする。

embedding 引数は省略可能。省略時は backend が text/query を内部で embedding に
変換する (ADC を持たない PAT-only クライアントに優しい設計)。
"""

from __future__ import annotations

import logging
from typing import Any

from .platform_client import PlatformClient

logger = logging.getLogger(__name__)


class PlatformSearch:
    """labvault platform 経由のベクトル検索バックエンド。"""

    def __init__(self, client: PlatformClient) -> None:
        self._client = client

    def index(
        self,
        team: str,
        record_id: str,
        text: str,
        embedding: list[float] | None = None,
    ) -> None:
        body: dict[str, Any] = {"record_id": record_id, "text": text}
        if embedding is not None:
            body["embedding"] = embedding
        self._client._request(
            "POST", "/api/metadata/search/index", team=team, json=body
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
        body: dict[str, Any] = {"query": query, "limit": limit}
        if embedding is not None:
            body["embedding"] = embedding
        if filters:
            body["filters"] = filters
        result = self._client._request(
            "POST", "/api/metadata/search", team=team, json=body
        )
        if not isinstance(result, list):
            raise RuntimeError(
                f"expected list from /api/metadata/search, got {type(result).__name__}"
            )
        return result

    def delete_index(self, team: str, record_id: str) -> None:
        self._client._request(
            "DELETE",
            f"/api/metadata/search/index/{record_id}",
            team=team,
        )


class PlatformEmbedding:
    """labvault platform 経由の Embedding client (Vertex AI のラッパー)。

    EmbeddingClient と同じ interface (embed / embed_batch) を提供。
    team は header で渡す (コンストラクタで束縛)。

    Note: 既存の SDK は embed_batch を呼び出さないが、API 整合性のため実装する。
    """

    def __init__(self, client: PlatformClient, team: str = "") -> None:
        self._client = client
        self._team = team

    def embed(self, text: str) -> list[float]:
        result = self._client._request(
            "POST",
            "/api/metadata/embedding",
            team=self._team,
            json={"text": text},
        )
        emb = (result or {}).get("embedding") if isinstance(result, dict) else None
        if not isinstance(emb, list):
            raise RuntimeError("invalid embedding response from platform")
        return [float(x) for x in emb]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        result = self._client._request(
            "POST",
            "/api/metadata/embedding",
            team=self._team,
            json={"texts": texts},
        )
        embs = (result or {}).get("embeddings") if isinstance(result, dict) else None
        if not isinstance(embs, list):
            raise RuntimeError("invalid embeddings response from platform")
        return [[float(x) for x in e] for e in embs]
