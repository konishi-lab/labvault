"""MCP サーバーのテスト。"""

from __future__ import annotations

import pytest

mcp = pytest.importorskip("mcp", reason="mcp package not installed")

from labvault.backends.memory import (  # noqa: E402
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab  # noqa: E402
from labvault.mcp.server import create_server  # noqa: E402


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


class TestSearchIncludeConditions:
    def test_include_conditions_true(self, lab, tools):
        lab.new("exp1", auto_log=False, power=20, angle=45)
        result = tools["search"](include_conditions=True)
        assert len(result) == 1
        assert "conditions" in result[0]
        assert result[0]["conditions"]["power"] == 20

    def test_include_conditions_default_false(self, lab, tools):
        lab.new("exp1", auto_log=False, power=20)
        result = tools["search"]()
        assert "conditions" not in result[0]


class TestConditionRangeFilter:
    def test_gte(self, lab, tools):
        lab.new("low", auto_log=False, power=10)
        lab.new("high", auto_log=False, power=50)
        result = tools["search"](conditions={"power": {"gte": 30}})
        assert len(result) == 1
        assert result[0]["title"] == "high"

    def test_range(self, lab, tools):
        for p in [10, 20, 30, 40, 50]:
            lab.new(f"p{p}", auto_log=False, power=p)
        result = tools["search"](
            conditions={"power": {"gte": 20, "lte": 40}},
            include_conditions=True,
        )
        assert len(result) == 3
        powers = [r["conditions"]["power"] for r in result]
        assert sorted(powers) == [20, 30, 40]

    def test_exact_match_backward_compat(self, lab, tools):
        lab.new("match", auto_log=False, power=20)
        lab.new("no", auto_log=False, power=30)
        result = tools["search"](conditions={"power": 20})
        assert len(result) == 1
        assert result[0]["title"] == "match"

    def test_range_with_query(self, lab, tools):
        lab.new("laser low", auto_log=False, power=10)
        lab.new("laser high", auto_log=False, power=50)
        result = tools["search"](query="laser", conditions={"power": {"gt": 20}})
        assert len(result) == 1
        assert result[0]["title"] == "laser high"


class TestAggregate:
    def test_aggregate_basic(self, lab, tools):
        for i in range(5):
            r = lab.new(f"exp{i}", auto_log=False)
            r.results["thickness"] = 100 + i * 10
            r.status = "success"

        result = tools["aggregate"](key="thickness")
        assert result["overall"]["count"] == 5
        assert result["overall"]["mean"] == 120.0
        assert result["overall"]["min"] == 100
        assert result["overall"]["max"] == 140

    def test_aggregate_group_by(self, lab, tools):
        for temp in [400, 400, 500, 500]:
            r = lab.new("exp", auto_log=False, temperature_C=temp)
            r.results["thickness"] = temp / 4
            r.status = "success"

        result = tools["aggregate"](key="thickness", group_by="temperature_C")
        assert "groups" in result
        assert "400" in result["groups"]
        assert "500" in result["groups"]

    def test_aggregate_condition_key(self, lab, tools):
        """conditions のキーでも集計できる。"""
        for p in [10, 20, 30]:
            lab.new(f"exp_p{p}", auto_log=False, power=p)
        result = tools["aggregate"](key="power")
        assert result["overall"]["count"] == 3
        assert result["overall"]["mean"] == 20.0

    def test_aggregate_with_parent_id(self, lab, tools):
        parent = lab.new("series", auto_log=False)
        for p in [10, 20, 30]:
            c = parent.sub(f"sub_p{p}")
            c.conditions(power=p)
        lab.new("other", auto_log=False, power=999)

        result = tools["aggregate"](key="power", parent_id=parent.id)
        assert result["overall"]["count"] == 3
        assert result["overall"]["mean"] == 20.0


class TestGetOverview:
    def test_overview_basic(self, lab, tools):
        parent = lab.new("series", auto_log=False)
        for p in [10, 20, 30]:
            c = parent.sub(f"sub_p{p}")
            c.conditions(power=p, material="Fe")

        result = tools["get_overview"](parent_id=parent.id)
        assert result["child_count"] == 3
        assert result["conditions"]["power"]["type"] == "numeric"
        assert result["conditions"]["power"]["min"] == 10
        assert result["conditions"]["power"]["max"] == 30
        assert result["conditions"]["material"]["type"] == "categorical"
        assert "Fe" in result["conditions"]["material"]["unique_values"]

    def test_overview_no_children(self, lab, tools):
        parent = lab.new("empty", auto_log=False)
        result = tools["get_overview"](parent_id=parent.id)
        assert result["child_count"] == 0
        assert result["conditions"] == {}

    def test_overview_with_results(self, lab, tools):
        parent = lab.new("series", auto_log=False)
        for i in range(3):
            c = parent.sub(f"sub{i}")
            c.results["roughness"] = 0.1 * (i + 1)

        result = tools["get_overview"](parent_id=parent.id)
        assert "roughness" in result["results"]
        assert result["results"]["roughness"]["count"] == 3


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


class TestTeamArg:
    """各ツールの team 引数 (Phase: MCP の team 対応)。"""

    def test_search_with_explicit_team_uses_registered_lab(self, lab, tools):
        """team を明示しても、それが lab.team と一致すれば登録済 lab が使われる。"""
        lab.new("only-in-test-team", auto_log=False)
        # lab fixture の team は "test-team"
        result = tools["search"](query="only-in-test-team", team=lab.team)
        assert len(result) == 1
        assert result[0]["title"] == "only-in-test-team"

    def test_search_with_blank_team_falls_back(self, lab, tools):
        """空文字 team は team=None と同等扱い (default lab にフォールバック)。"""
        lab.new("blank-team-test", auto_log=False)
        result = tools["search"](query="blank-team-test", team="")
        assert len(result) == 1
