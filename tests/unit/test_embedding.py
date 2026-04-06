"""Embedding のテスト。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from labvault.backends.embedding import EmbeddingClient, build_embedding_text


class TestBuildEmbeddingText:
    def test_title_repeated(self):
        record = {"title": "XRD測定"}
        text = build_embedding_text(record)
        assert text.count("XRD測定") == 2

    def test_tags_included(self):
        record = {"title": "test", "tags": ["XRD", "Fe-Cr"]}
        text = build_embedding_text(record)
        assert "XRD" in text
        assert "Fe-Cr" in text

    def test_conditions_included(self):
        record = {
            "title": "test",
            "conditions": {"temperature_C": 500, "pressure_Pa": 0.5},
        }
        text = build_embedding_text(record)
        assert "temperature_C=500" in text
        assert "pressure_Pa=0.5" in text

    def test_results_included(self):
        record = {
            "title": "test",
            "results": {"lattice_a": 2.87, "phase": "BCC"},
        }
        text = build_embedding_text(record)
        assert "lattice_a: 2.87" in text
        assert "phase: BCC" in text

    def test_notes_last_three(self):
        record = {
            "title": "test",
            "notes": [
                {"text": "note1"},
                {"text": "note2"},
                {"text": "note3"},
                {"text": "note4"},
            ],
        }
        text = build_embedding_text(record)
        assert "note1" not in text
        assert "note2" in text
        assert "note3" in text
        assert "note4" in text

    def test_empty_record(self):
        text = build_embedding_text({})
        assert text == ""

    def test_minimal_record(self):
        record = {"title": "XRD"}
        text = build_embedding_text(record)
        assert text == "XRD XRD"


class TestEmbeddingClient:
    def test_embed_calls_api(self):
        with patch("labvault.backends.embedding.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"predictions": [{"embeddings": {"values": [0.1] * 768}}]},
                raise_for_status=lambda: None,
            )

            client = EmbeddingClient("test-project")
            # Mock google-auth
            with patch.object(client, "_get_token", return_value="fake"):
                result = client.embed("hello")

            assert len(result) == 768
            assert result[0] == 0.1
            mock_post.assert_called_once()

    def test_embed_batch(self):
        with patch("labvault.backends.embedding.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "predictions": [
                        {"embeddings": {"values": [0.1] * 768}},
                        {"embeddings": {"values": [0.2] * 768}},
                    ]
                },
                raise_for_status=lambda: None,
            )

            client = EmbeddingClient("test-project")
            with patch.object(client, "_get_token", return_value="fake"):
                results = client.embed_batch(["hello", "world"])

            assert len(results) == 2
            assert results[0][0] == 0.1
            assert results[1][0] == 0.2

    def test_url_format(self):
        client = EmbeddingClient(
            "my-project", region="us-central1", model="text-embedding-004"
        )
        assert "my-project" in client._url
        assert "us-central1" in client._url
        assert "text-embedding-004" in client._url


class TestLabEmbeddingIntegration:
    def test_search_with_embedding(self):
        """EmbeddingClient がある場合、search でクエリを embed する。"""
        from labvault.backends.memory import (
            InMemoryMetadataBackend,
            InMemorySearchBackend,
            InMemoryStorageBackend,
        )
        from labvault.core.lab import Lab

        mock_client = MagicMock()
        mock_client.embed.return_value = [0.1] * 768

        lab = Lab(
            "test",
            user="tester",
            metadata_backend=InMemoryMetadataBackend(),
            storage_backend=InMemoryStorageBackend(),
            search_backend=InMemorySearchBackend(),
            embedding_client=mock_client,
        )

        lab.new("XRD Fe-Cr測定", auto_log=False)
        lab.search("Fe-Cr")

        # embed が呼ばれた
        mock_client.embed.assert_called()
        lab.close()

    def test_search_without_embedding(self):
        """EmbeddingClient がない場合でもテキスト検索は動く。"""
        from labvault.backends.memory import (
            InMemoryMetadataBackend,
            InMemorySearchBackend,
            InMemoryStorageBackend,
        )
        from labvault.core.lab import Lab

        lab = Lab(
            "test",
            user="tester",
            metadata_backend=InMemoryMetadataBackend(),
            storage_backend=InMemoryStorageBackend(),
            search_backend=InMemorySearchBackend(),
        )

        lab.new("XRD Fe-Cr測定", auto_log=False)
        results = lab.search("XRD Fe-Cr")
        assert len(results) >= 1
        lab.close()

    def test_index_includes_embedding_text(self):
        """new() で build_embedding_text が使われる。"""
        from labvault.backends.memory import (
            InMemoryMetadataBackend,
            InMemorySearchBackend,
            InMemoryStorageBackend,
        )
        from labvault.core.lab import Lab

        search = InMemorySearchBackend()

        lab = Lab(
            "test",
            user="tester",
            metadata_backend=InMemoryMetadataBackend(),
            storage_backend=InMemoryStorageBackend(),
            search_backend=search,
        )

        lab.new(
            "XRD測定",
            tags=["XRD", "Fe-Cr"],
            temperature_C=500,
            auto_log=False,
        )

        # InMemorySearchBackend の内部を確認
        indexed_text = next(iter(search._index.get("test", {}).values()))
        assert "XRD測定" in indexed_text
        assert "XRD" in indexed_text
        assert "temperature_C=500" in indexed_text
        lab.close()
