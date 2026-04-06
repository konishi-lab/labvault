"""Vertex AI Embedding クライアント (REST API 直接呼び出し)。

google-cloud-aiplatform を使わず httpx + google-auth で軽量に実装。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_EMBEDDING_URL = (
    "https://{region}-aiplatform.googleapis.com/v1/"
    "projects/{project}/locations/{region}/"
    "publishers/google/models/{model}:predict"
)

_DEFAULT_MODEL = "text-embedding-004"
_DEFAULT_REGION = "asia-northeast1"
_DEFAULT_DIMENSIONS = 768


class EmbeddingClient:
    """Vertex AI text-embedding-004 クライアント。"""

    def __init__(
        self,
        project: str,
        *,
        region: str = _DEFAULT_REGION,
        model: str = _DEFAULT_MODEL,
        dimensions: int = _DEFAULT_DIMENSIONS,
    ) -> None:
        self._project = project
        self._region = region
        self._model = model
        self._dimensions = dimensions
        self._credentials: Any = None
        self._url = _EMBEDDING_URL.format(
            region=region,
            project=project,
            model=model,
        )

    def _get_token(self) -> str:
        """Google Cloud ADC トークンを取得する。"""
        import google.auth
        import google.auth.transport.requests

        if self._credentials is None:
            self._credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

        request = google.auth.transport.requests.Request()
        self._credentials.refresh(request)
        return self._credentials.token  # type: ignore[no-any-return]

    def embed(self, text: str) -> list[float]:
        """単一テキストを Embedding に変換する。"""
        results = self.embed_batch([text])
        return results[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """複数テキストをバッチで Embedding に変換する。"""
        token = self._get_token()
        payload = {
            "instances": [{"content": t} for t in texts],
            "parameters": {
                "outputDimensionality": self._dimensions,
            },
        }

        resp = httpx.post(
            self._url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        resp.raise_for_status()

        data = resp.json()
        return [p["embeddings"]["values"] for p in data["predictions"]]


def build_embedding_text(record: dict[str, Any]) -> str:
    """Record の dict から Embedding 用テキストを生成する。"""
    parts: list[str] = []

    title = record.get("title", "")
    if title:
        parts.append(title)
        parts.append(title)  # 重み付けのため2回

    tags = record.get("tags", [])
    if tags:
        parts.append(" ".join(tags))

    for k, v in record.get("conditions", {}).items():
        parts.append(f"{k}={v}")

    for k, v in record.get("results", {}).items():
        parts.append(f"{k}: {v}")

    for note in record.get("notes", [])[-3:]:
        text = note.get("text", "") if isinstance(note, dict) else ""
        if text:
            parts.append(text)

    return " ".join(parts)
