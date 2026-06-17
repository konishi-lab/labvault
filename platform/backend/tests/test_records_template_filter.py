"""`/api/records` と `/api/search` の `template` クエリパラメータ +
`RecordSummary.template_name` の検証。

Web UI の context chip `[template: XRD]` クリックで `/records?template=XRD`
に遷移するときに使う。
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
from labvault.core.types import TemplateV10


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    """XRD 紐付け 2 件、SEM 紐付け 1 件、template 無し 2 件。"""
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
    lab.define_template(TemplateV10(name="XRD", type="measurement"))
    lab.define_template(TemplateV10(name="SEM", type="measurement"))
    for i in range(2):
        lab.new(f"xrd-{i}", template="XRD", auto_log=False)
    lab.new("sem-0", template="SEM", auto_log=False)
    for i in range(2):
        lab.new(f"plain-{i}", auto_log=False)
    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


class TestTemplateFilter:
    def test_filter_by_xrd(self, client: TestClient) -> None:
        res = client.get("/api/records?template=XRD&limit=20")
        body = res.json()
        names = {r["template_name"] for r in body["items"]}
        assert names == {"XRD"}
        assert len(body["items"]) == 2

    def test_filter_by_sem(self, client: TestClient) -> None:
        res = client.get("/api/records?template=SEM&limit=20")
        body = res.json()
        assert len(body["items"]) == 1
        assert body["items"][0]["template_name"] == "SEM"

    def test_unknown_template_empty(self, client: TestClient) -> None:
        res = client.get("/api/records?template=ghost&limit=20")
        body = res.json()
        assert body["items"] == []

    def test_search_endpoint_template_filter(self, client: TestClient) -> None:
        res = client.get("/api/search?template=XRD")
        items = res.json()
        names = {r["template_name"] for r in items}
        assert names == {"XRD"}


class TestTemplateNameInSummary:
    def test_template_name_present(self, client: TestClient) -> None:
        res = client.get("/api/records?limit=20")
        items = res.json()["items"]
        # XRD / SEM / None が全て含まれる
        names = {r.get("template_name") for r in items}
        assert "XRD" in names
        assert "SEM" in names
        assert None in names

    def test_field_always_present(self, client: TestClient) -> None:
        """template 無しの record でも field は present (frontend が optional 扱い
        できるよう)。"""
        res = client.get("/api/records?limit=20")
        for item in res.json()["items"]:
            assert "template_name" in item
