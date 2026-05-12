"""PlatformStorage / PlatformSearch / PlatformEmbedding (Phase 4) のユニットテスト。

httpx をモックして HTTP レイヤだけ確認する (実 backend は不要)。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from labvault.backends.platform_client import PlatformClient
from labvault.backends.platform_search import PlatformEmbedding, PlatformSearch
from labvault.backends.platform_storage import PlatformStorage


def _install_request_mock(
    monkeypatch: pytest.MonkeyPatch, responses: dict[tuple[str, str], Any]
) -> list[httpx.Request]:
    """httpx.request をモックする (PlatformClient._request 用)."""
    captured: list[httpx.Request] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        from urllib.parse import urlparse

        path = urlparse(url).path
        req = httpx.Request(
            method,
            url,
            **{k: v for k, v in kwargs.items() if k in {"headers", "params", "json"}},
        )
        captured.append(req)
        key = (method, path)
        if key not in responses:
            return httpx.Response(404, request=req, json={"detail": "not found"})
        body = responses[key]
        if isinstance(body, int):
            return httpx.Response(body, request=req)
        if body is None:
            return httpx.Response(204, request=req)
        return httpx.Response(200, request=req, json=body)

    monkeypatch.setattr(httpx, "request", fake_request)
    return captured


def _install_storage_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    download_data: bytes | None = None,
    download_status: int = 200,
    delete_status: int = 204,
    upload_response: dict[str, str] | None = None,
) -> dict[str, list[httpx.Request]]:
    """httpx.post / httpx.get / httpx.delete をモック (PlatformStorage 用)."""
    seen: dict[str, list[httpx.Request]] = {"post": [], "get": [], "delete": []}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        req = httpx.Request("POST", url, headers=kwargs.get("headers"))
        seen["post"].append(req)
        # data/files を保持しておきたいので Request 経由ではなく属性に保存
        req.extensions["sent_data"] = kwargs.get("data")
        req.extensions["sent_files"] = kwargs.get("files")
        body = upload_response or {"path": "stored/path"}
        return httpx.Response(200, request=req, json=body)

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        req = httpx.Request(
            "GET", url, headers=kwargs.get("headers"), params=kwargs.get("params")
        )
        seen["get"].append(req)
        if download_status == 404:
            return httpx.Response(404, request=req)
        return httpx.Response(
            download_status, request=req, content=download_data or b""
        )

    def fake_delete(url: str, **kwargs: Any) -> httpx.Response:
        req = httpx.Request(
            "DELETE", url, headers=kwargs.get("headers"), params=kwargs.get("params")
        )
        seen["delete"].append(req)
        return httpx.Response(delete_status, request=req)

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "delete", fake_delete)
    return seen


@pytest.fixture()
def client() -> PlatformClient:
    return PlatformClient("https://example.test", token="lv_x")


class TestPlatformStorage:
    def test_upload_calls_multipart_post(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        seen = _install_storage_mock(
            monkeypatch, upload_response={"path": "konishi-lab/REC1/data.csv"}
        )
        storage = PlatformStorage(client, team="konishi-lab")
        result = storage.upload(
            "konishi-lab/REC1/data.csv", b"hello", content_type="text/csv"
        )
        assert result == "konishi-lab/REC1/data.csv"
        assert len(seen["post"]) == 1
        req = seen["post"][0]
        assert req.url.path == "/api/metadata/storage"
        assert req.headers["X-Labvault-Team"] == "konishi-lab"
        # form data に path と content_type が乗っている
        sent_data = req.extensions["sent_data"]
        assert sent_data["path"] == "konishi-lab/REC1/data.csv"
        assert sent_data["content_type"] == "text/csv"

    def test_download_returns_bytes(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_storage_mock(monkeypatch, download_data=b"file content")
        storage = PlatformStorage(client, team="t1")
        assert storage.download("foo/bar.txt") == b"file content"

    def test_download_404_raises_filenotfound(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_storage_mock(monkeypatch, download_status=404)
        storage = PlatformStorage(client, team="t1")
        with pytest.raises(FileNotFoundError):
            storage.download("missing.txt")

    def test_delete_idempotent_on_404(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_storage_mock(monkeypatch, delete_status=404)
        storage = PlatformStorage(client, team="t1")
        # 404 でも例外を出さない
        storage.delete("gone.txt")

    def test_exists_uses_get_dict(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_request_mock(
            monkeypatch,
            {("GET", "/api/metadata/storage/exists"): {"exists": True}},
        )
        storage = PlatformStorage(client, team="t1")
        assert storage.exists("foo") is True

    def test_list_files_returns_paths(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_request_mock(
            monkeypatch,
            {("GET", "/api/metadata/storage/list"): {"paths": ["a", "b"]}},
        )
        storage = PlatformStorage(client, team="t1")
        assert storage.list_files("prefix/") == ["a", "b"]


class TestPlatformSearch:
    def test_index_sends_text_only_when_no_embedding(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        import json

        captured = _install_request_mock(
            monkeypatch, {("POST", "/api/metadata/search/index"): None}
        )
        search = PlatformSearch(client)
        search.index("t1", "REC1", "hello world")
        body = json.loads(captured[0].read())
        assert body == {"record_id": "REC1", "text": "hello world"}
        assert "embedding" not in body

    def test_index_sends_embedding_when_provided(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        import json

        captured = _install_request_mock(
            monkeypatch, {("POST", "/api/metadata/search/index"): None}
        )
        search = PlatformSearch(client)
        search.index("t1", "REC1", "text", embedding=[0.1, 0.2, 0.3])
        body = json.loads(captured[0].read())
        assert body["embedding"] == [0.1, 0.2, 0.3]

    def test_search_returns_list(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        rows = [{"record_id": "R1", "score": 0.9}]
        _install_request_mock(monkeypatch, {("POST", "/api/metadata/search"): rows})
        search = PlatformSearch(client)
        assert search.search("t1", "query", limit=10) == rows

    def test_search_filters_passed_through(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        import json

        captured = _install_request_mock(
            monkeypatch, {("POST", "/api/metadata/search"): []}
        )
        search = PlatformSearch(client)
        search.search("t1", "q", filters={"status": "success"}, limit=5)
        body = json.loads(captured[0].read())
        assert body["filters"] == {"status": "success"}
        assert body["limit"] == 5

    def test_delete_index(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        captured = _install_request_mock(
            monkeypatch, {("DELETE", "/api/metadata/search/index/REC1"): None}
        )
        search = PlatformSearch(client)
        search.delete_index("t1", "REC1")
        assert captured[0].method == "DELETE"


class TestPlatformEmbedding:
    def test_embed_single(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_request_mock(
            monkeypatch,
            {("POST", "/api/metadata/embedding"): {"embedding": [0.1, 0.2]}},
        )
        emb = PlatformEmbedding(client, team="t1")
        assert emb.embed("hello") == [0.1, 0.2]

    def test_embed_batch(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_request_mock(
            monkeypatch,
            {
                ("POST", "/api/metadata/embedding"): {
                    "embeddings": [[0.1, 0.2], [0.3, 0.4]]
                }
            },
        )
        emb = PlatformEmbedding(client, team="t1")
        assert emb.embed_batch(["hello", "world"]) == [[0.1, 0.2], [0.3, 0.4]]

    def test_embed_invalid_response_raises(
        self, monkeypatch: pytest.MonkeyPatch, client: PlatformClient
    ) -> None:
        _install_request_mock(
            monkeypatch, {("POST", "/api/metadata/embedding"): {"unexpected": "shape"}}
        )
        emb = PlatformEmbedding(client, team="t1")
        with pytest.raises(RuntimeError, match="invalid embedding"):
            emb.embed("hi")
