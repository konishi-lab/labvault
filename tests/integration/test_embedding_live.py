"""Vertex AI Embedding 結合テスト。

実行方法:
    LABVAULT_GCP_PROJECT=klab-laser-process \
    pytest tests/integration/test_embedding_live.py -v -m integration
"""

from __future__ import annotations

import pytest

from labvault.backends.embedding import EmbeddingClient
from labvault.core.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture()
def client():
    settings = Settings()
    if not settings.gcp_project:
        pytest.skip("LABVAULT_GCP_PROJECT not set")
    return EmbeddingClient(project=settings.gcp_project)


class TestEmbeddingLive:
    def test_embed_single(self, client):
        result = client.embed("XRD measurement of Fe-Cr thin film")
        assert isinstance(result, list)
        assert len(result) == 768
        assert all(isinstance(v, float) for v in result)

    def test_embed_batch(self, client):
        results = client.embed_batch(
            [
                "XRD measurement",
                "SEM observation",
            ]
        )
        assert len(results) == 2
        assert len(results[0]) == 768
        assert len(results[1]) == 768
