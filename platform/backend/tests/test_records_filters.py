"""`/api/records` と `/api/search` の created_by フィルタ + has_more の検証。

UI が「自分のみ」filter chip と「N+ 件以上ヒット」表記を出すのに使う。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.main import app
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    """alice 3 件 / bob 2 件 を持つ Lab。created_by フィルタ検証用。"""
    for key in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(key, "")
    lab = Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )
    for i in range(3):
        lab.new(f"alice-{i}", auto_log=False, created_by="alice@example.com")
    for i in range(2):
        lab.new(f"bob-{i}", auto_log=False, created_by="bob@example.com")
    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


class TestListRecordsCreatedBy:
    def test_filter_by_alice(self, client: TestClient) -> None:
        res = client.get("/api/records?created_by=alice@example.com")
        assert res.status_code == 200
        body = res.json()
        emails = {r["created_by"] for r in body["items"]}
        assert emails == {"alice@example.com"}
        assert len(body["items"]) == 3

    def test_filter_by_bob(self, client: TestClient) -> None:
        res = client.get("/api/records?created_by=bob@example.com")
        body = res.json()
        emails = {r["created_by"] for r in body["items"]}
        assert emails == {"bob@example.com"}
        assert len(body["items"]) == 2

    def test_no_filter_returns_all(self, client: TestClient) -> None:
        res = client.get("/api/records?limit=20")
        body = res.json()
        emails = {r["created_by"] for r in body["items"]}
        assert "alice@example.com" in emails
        assert "bob@example.com" in emails

    def test_unknown_user_returns_empty(self, client: TestClient) -> None:
        res = client.get("/api/records?created_by=ghost@example.com")
        body = res.json()
        assert body["items"] == []
        assert body["total"] == 0


class TestHasMore:
    def test_has_more_when_at_limit(self, client: TestClient) -> None:
        # alice 3 件、limit=2 で 2 件返って has_more=True
        res = client.get("/api/records?created_by=alice@example.com&limit=2")
        body = res.json()
        assert len(body["items"]) == 2
        assert body["has_more"] is True

    def test_has_more_false_when_under_limit(self, client: TestClient) -> None:
        # alice 3 件、limit=10 で全件返って has_more=False
        res = client.get("/api/records?created_by=alice@example.com&limit=10")
        body = res.json()
        assert len(body["items"]) == 3
        assert body["has_more"] is False

    def test_has_more_false_when_empty(self, client: TestClient) -> None:
        res = client.get("/api/records?created_by=ghost@example.com&limit=10")
        body = res.json()
        assert body["has_more"] is False


class TestSearchCreatedBy:
    def test_search_filter_by_alice(self, client: TestClient) -> None:
        # query 無し → /api/search も /api/records と同じく created_by が効く
        res = client.get("/api/search?created_by=alice@example.com")
        assert res.status_code == 200
        items = res.json()
        emails = {r["created_by"] for r in items}
        assert emails == {"alice@example.com"}
