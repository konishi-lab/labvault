"""MCP サーバーのテスト。"""

from __future__ import annotations

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab
from labvault.mcp.server import create_server


@pytest.fixture()
def lab():
    return Lab(
        "test-team",
        user="tester",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


@pytest.fixture()
def server(lab):
    return create_server(lab)


@pytest.fixture()
def tools(server):
    """サーバーのツール関数を名前で取得する辞書。"""
    return {t.name: t.fn for t in server._tool_manager.list_tools()}


class TestSearch:
    def test_search_empty(self, tools):
        result = tools["search"](query="nonexistent")
        assert result == []

    def test_search_finds_record(self, lab, tools):
        lab.new("XRD Fe-Cr", tags=["XRD"], auto_log=False)
        result = tools["search"](query="XRD Fe-Cr")
        assert len(result) >= 1
        assert result[0]["title"] == "XRD Fe-Cr"

    def test_search_by_tags(self, lab, tools):
        lab.new("exp1", tags=["XRD"], auto_log=False)
        lab.new("exp2", tags=["SEM"], auto_log=False)
        result = tools["search"](tags=["XRD"])
        assert all("XRD" in r["tags"] for r in result)

    def test_list_all(self, lab, tools):
        lab.new("exp1", auto_log=False)
        lab.new("exp2", auto_log=False)
        result = tools["search"]()
        assert len(result) == 2


class TestGetDetail:
    def test_get_detail(self, lab, tools):
        rec = lab.new("Detail Test", tags=["XRD"], auto_log=False)
        rec.conditions(temperature_C=500)
        rec.results["lattice_a"] = 2.87
        rec.note("test note")
        rec.add(b"csv data", name="data.csv", content_type="text/csv")

        result = tools["get_detail"](record_id=rec.id)
        assert result["id"] == rec.id
        assert result["title"] == "Detail Test"
        assert result["conditions"]["temperature_C"] == 500
        assert result["results"]["lattice_a"] == 2.87
        assert len(result["notes"]) == 1
        assert len(result["files"]) == 1
        assert result["files"][0]["name"] == "data.csv"


class TestCompare:
    def test_compare_records(self, lab, tools):
        r1 = lab.new("exp1", auto_log=False, temperature_C=400)
        r1.results["thickness"] = 100

        r2 = lab.new("exp2", auto_log=False, temperature_C=500)
        r2.results["thickness"] = 150

        result = tools["compare"](record_ids=[r1.id, r2.id])
        assert len(result["records"]) == 2
        assert "temperature_C" in result["differences"]

    def test_compare_with_common(self, lab, tools):
        r1 = lab.new("exp1", auto_log=False, gas="Ar")
        r2 = lab.new("exp2", auto_log=False, gas="Ar")

        result = tools["compare"](record_ids=[r1.id, r2.id])
        assert "gas" in result["common"]
        assert result["common"]["gas"] == "Ar"


class TestDataPreview:
    def test_preview_csv(self, lab, tools):
        rec = lab.new("test", auto_log=False)
        csv = "a,b,c\n1,2,3\n4,5,6\n7,8,9\n"
        rec.add(csv.encode(), name="data.csv", content_type="text/csv")

        result = tools["data_preview"](record_id=rec.id, filename="data.csv")
        assert result["preview_type"] == "csv"
        assert result["header"] == "a,b,c"
        assert len(result["rows"]) == 3

    def test_preview_json(self, lab, tools):
        rec = lab.new("test", auto_log=False)
        rec.save("config", {"key": "value"})

        result = tools["data_preview"](record_id=rec.id, filename="config.json")
        assert result["preview_type"] == "json"
        assert result["content"]["key"] == "value"


class TestAggregate:
    def test_aggregate_basic(self, lab, tools):
        for i in range(5):
            r = lab.new(f"exp{i}", auto_log=False)
            r.results["thickness"] = 100 + i * 10
            r.status = "success"

        result = tools["aggregate"](result_key="thickness")
        assert result["overall"]["count"] == 5
        assert result["overall"]["mean"] == 120.0
        assert result["overall"]["min"] == 100
        assert result["overall"]["max"] == 140

    def test_aggregate_group_by(self, lab, tools):
        for temp in [400, 400, 500, 500]:
            r = lab.new("exp", auto_log=False, temperature_C=temp)
            r.results["thickness"] = temp / 4
            r.status = "success"

        result = tools["aggregate"](result_key="thickness", group_by="temperature_C")
        assert "groups" in result
        assert "400" in result["groups"]
        assert "500" in result["groups"]


class TestGetTimeline:
    def test_timeline_by_tags(self, lab, tools):
        lab.new("exp1", tags=["Fe-Cr"], auto_log=False)
        lab.new("exp2", tags=["Fe-Cr"], auto_log=False)
        lab.new("exp3", tags=["SiO2"], auto_log=False)

        result = tools["get_timeline"](tags=["Fe-Cr"])
        assert len(result) == 2

    def test_timeline_with_children(self, lab, tools):
        parent = lab.new("parent", auto_log=False)
        parent.sub("child1")
        parent.sub("child2")

        result = tools["get_timeline"](record_id=parent.id)
        assert len(result) == 3  # parent + 2 children
