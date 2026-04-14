"""Lab クラスのテスト。"""

from __future__ import annotations

import pytest

from labvault.core.exceptions import RecordNotFoundError
from labvault.core.lab import Lab
from labvault.core.types import RecordType, Status


class TestLabInit:
    """Lab 初期化のテスト。"""

    def test_default_team(self) -> None:
        lab = Lab()
        assert lab._team

    def test_explicit_team(self) -> None:
        lab = Lab("my-team")
        assert lab._team == "my-team"

    def test_repr(self, lab: Lab) -> None:
        assert "Lab(" in repr(lab)
        assert "test-team" in repr(lab)


class TestLabNew:
    """Lab.new のテスト。"""

    def test_new_basic(self, lab: Lab) -> None:
        rec = lab.new("基本テスト")
        assert rec.title == "基本テスト"
        assert rec.status == Status.RUNNING
        assert rec.type == RecordType.EXPERIMENT

    def test_new_with_type(self, lab: Lab) -> None:
        rec = lab.new("サンプル", type=RecordType.SAMPLE)
        assert rec.type == "sample"

    def test_new_with_type_string(self, lab: Lab) -> None:
        rec = lab.new("分析", type="analysis")
        assert rec.type == "analysis"

    def test_new_ids_are_unique(self, lab: Lab) -> None:
        ids = {lab.new(f"テスト{i}").id for i in range(20)}
        assert len(ids) == 20


class TestLabGet:
    """Lab.get のテスト。"""

    def test_get_existing(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        fetched = lab.get(rec.id)
        assert fetched.id == rec.id
        assert fetched.title == "テスト"

    def test_get_normalizes_id(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        fetched = lab.get(rec.id.lower())
        assert fetched.id == rec.id

    def test_get_not_found(self, lab: Lab) -> None:
        with pytest.raises(RecordNotFoundError):
            lab.get("ZZZZ")


class TestLabList:
    """Lab.list のテスト。"""

    def test_list_all(self, lab: Lab) -> None:
        lab.new("A")
        lab.new("B")
        lab.new("C")
        result = lab.list()
        assert len(result) == 3

    def test_list_by_tags(self, lab: Lab) -> None:
        lab.new("A", tags=["XRD"])
        lab.new("B", tags=["SEM"])
        lab.new("C", tags=["XRD", "SEM"])
        result = lab.list(tags=["XRD"])
        assert len(result) == 2

    def test_list_by_status(self, lab: Lab) -> None:
        r1 = lab.new("A")
        lab.new("B")
        r1.status = Status.SUCCESS
        result = lab.list(status=Status.SUCCESS)
        assert len(result) == 1
        assert result[0].id == r1.id

    def test_list_by_type(self, lab: Lab) -> None:
        lab.new("実験", type=RecordType.EXPERIMENT)
        lab.new("サンプル", type=RecordType.SAMPLE)
        result = lab.list(type=RecordType.SAMPLE)
        assert len(result) == 1

    def test_list_with_limit(self, lab: Lab) -> None:
        for i in range(5):
            lab.new(f"テスト{i}")
        result = lab.list(limit=3)
        assert len(result) == 3

    def test_list_with_offset(self, lab: Lab) -> None:
        for i in range(5):
            lab.new(f"テスト{i}")
        all_recs = lab.list()
        offset_recs = lab.list(offset=2)
        assert len(offset_recs) == 3
        assert offset_recs[0].id == all_recs[2].id


class TestLabRecent:
    """Lab.recent のテスト。"""

    def test_recent(self, lab: Lab) -> None:
        for i in range(5):
            lab.new(f"テスト{i}")
        result = lab.recent(3)
        assert len(result) == 3


class TestLabToday:
    """Lab.today のテスト。"""

    def test_today(self, lab: Lab) -> None:
        lab.new("今日の実験")
        result = lab.today()
        assert len(result) >= 1
        assert result[0].title == "今日の実験"


class TestLabSearch:
    """Lab.search のテスト。"""

    def test_search_by_title(self, lab: Lab) -> None:
        lab.new("XRD測定")
        lab.new("SEM観察")
        result = lab.search("XRD")
        assert len(result) == 1
        assert result[0].title == "XRD測定"

    def test_search_no_results(self, lab: Lab) -> None:
        lab.new("テスト")
        result = lab.search("存在しないクエリ")
        assert len(result) == 0

    def test_search_excludes_deleted(self, lab: Lab) -> None:
        rec = lab.new("削除テスト")
        lab.delete(rec.id)
        result = lab.search("削除テスト")
        assert len(result) == 0


class TestLabSearchConditions:
    """Lab.search の条件フィルタテスト。"""

    def test_search_by_conditions(self, lab: Lab) -> None:
        lab.new("exp1", auto_log=False, power=20, angle=70)
        lab.new("exp2", auto_log=False, power=50, angle=80)
        lab.new("exp3", auto_log=False, power=20, angle=90)

        result = lab.search("exp", conditions={"power": 20})
        assert len(result) == 2
        assert all(r.get_conditions()["power"] == 20 for r in result)

    def test_search_by_parent_id(self, lab: Lab) -> None:
        parent1 = lab.new("parent1", auto_log=False)
        parent2 = lab.new("parent2", auto_log=False)
        parent1.sub("child1a")
        parent1.sub("child1b")
        parent2.sub("child2a")

        result = lab.search("child", parent_id=parent1.id)
        assert len(result) == 2
        assert all(r.parent_id == parent1.id for r in result)

    def test_search_by_conditions_and_parent(self, lab: Lab) -> None:
        parent = lab.new("parent", auto_log=False)
        parent.sub("sub1", power=20)
        parent.sub("sub2", power=50)
        parent.sub("sub3", power=20)

        result = lab.search("sub", parent_id=parent.id, conditions={"power": 20})
        assert len(result) == 2

    def test_search_conditions_no_match(self, lab: Lab) -> None:
        lab.new("exp", auto_log=False, power=20)
        result = lab.search("exp", conditions={"power": 999})
        assert len(result) == 0

    def test_search_conditions_range_gte(self, lab: Lab) -> None:
        lab.new("low", auto_log=False, power=10)
        lab.new("high", auto_log=False, power=50)
        result = lab.search("", conditions={"power": {"gte": 30}})
        assert len(result) == 1
        assert result[0].get_conditions()["power"] == 50

    def test_search_conditions_range_combined(self, lab: Lab) -> None:
        for p in [10, 20, 30, 40, 50]:
            lab.new(f"p{p}", auto_log=False, power=p)
        result = lab.search("", conditions={"power": {"gte": 20, "lte": 40}})
        assert len(result) == 3

    def test_search_conditions_exact_still_works(self, lab: Lab) -> None:
        lab.new("a", auto_log=False, power=20)
        lab.new("b", auto_log=False, power=30)
        result = lab.search("", conditions={"power": 20})
        assert len(result) == 1


class TestLabDelete:
    """Lab.delete / trash / restore のテスト。"""

    def test_delete_soft(self, lab: Lab) -> None:
        rec = lab.new("削除テスト")
        lab.delete(rec.id)
        # list から除外される
        result = lab.list()
        assert all(r.id != rec.id for r in result)

    def test_delete_not_found(self, lab: Lab) -> None:
        with pytest.raises(RecordNotFoundError):
            lab.delete("ZZZZ")

    def test_trash(self, lab: Lab) -> None:
        rec = lab.new("ゴミ箱テスト")
        lab.delete(rec.id)
        trashed = lab.trash()
        assert len(trashed) == 1
        assert trashed[0].id == rec.id

    def test_restore(self, lab: Lab) -> None:
        rec = lab.new("復元テスト")
        lab.delete(rec.id)
        restored = lab.restore(rec.id)
        assert restored.id == rec.id
        # list に戻る
        result = lab.list()
        assert any(r.id == rec.id for r in result)

    def test_restore_not_found(self, lab: Lab) -> None:
        with pytest.raises(RecordNotFoundError):
            lab.restore("ZZZZ")


class TestRunAnalysis:
    """Record.run_analysis のテスト。"""

    def test_basic(self, lab: Lab) -> None:
        """解析関数の実行と結果の記録。"""
        rec = lab.new("measurement", auto_log=False)
        rec.add(b"dummy data", name="data.bin")

        def my_analysis(data: bytes, *, scale: float = 1.0) -> dict:
            return {
                "results": {"depth": 0.5 * scale, "roughness": 0.12},
                "units": {"depth": "um", "roughness": "um"},
                "files": {"output.csv": b"x,y\n1,2\n"},
            }

        ana = rec.run_analysis(my_analysis, "data.bin", params={"scale": 2.0})

        # 解析 Record が作成されている
        assert ana.type == "analysis"
        assert ana.parent_id == rec.id
        assert ana.status == "success"

        # 解析 Record の conditions
        cond = ana.get_conditions()
        assert cond["method"] == "my_analysis"
        assert cond["analyzer_type"] == "python"
        assert cond["source_file"] == "data.bin"
        assert cond["scale"] == 2.0

        # 解析 Record の results + units
        assert ana.results["depth"] == 1.0
        assert ana.results["roughness"] == 0.12
        assert ana.get_result_units() == {"depth": "um", "roughness": "um"}

        # 解析 Record にコードが保存されている
        code = ana.get_data("analyzer.py")
        assert b"my_analysis" in code

        # 解析 Record に出力ファイルが保存されている
        csv = ana.get_data("output.csv")
        assert csv == b"x,y\n1,2\n"

        # 測定 Record に書き戻されている (値 + units + __analysis_id)
        assert rec.results["depth"] == 1.0
        assert rec.results["roughness"] == 0.12
        assert rec.results["depth__analysis_id"] == ana.id
        assert rec.get_result_units()["depth"] == "um"

    def test_results_only(self, lab: Lab) -> None:
        """files なしの解析。"""
        rec = lab.new("measurement", auto_log=False)
        rec.add(b"test", name="input.txt")

        def simple(data: bytes) -> dict:
            return {"results": {"length": len(data)}}

        ana = rec.run_analysis(simple, "input.txt")
        assert ana.results["length"] == 4
        assert rec.results["length"] == 4

    def test_code_string(self, lab: Lab) -> None:
        """コード文字列を渡す場合。"""
        rec = lab.new("measurement", auto_log=False)
        rec.add(b"hello", name="input.txt")

        code = """
def analyze(data):
    return {"results": {"size": len(data)}}
"""
        ana = rec.run_analysis(code, "input.txt")
        assert ana.results["size"] == 5
        assert rec.results["size"] == 5

    def test_overwrites_previous(self, lab: Lab) -> None:
        """再解析で測定 Record のキャッシュが更新される。"""
        rec = lab.new("measurement", auto_log=False)
        rec.add(b"data", name="input.bin")

        def v1(data: bytes) -> dict:
            return {"results": {"depth": 0.5}}

        def v2(data: bytes) -> dict:
            return {"results": {"depth": 0.6}}

        ana1 = rec.run_analysis(v1, "input.bin")
        assert rec.results["depth"] == 0.5
        assert rec.results["depth__analysis_id"] == ana1.id

        ana2 = rec.run_analysis(v2, "input.bin")
        assert rec.results["depth"] == 0.6
        assert rec.results["depth__analysis_id"] == ana2.id

        # 旧解析 Record の値はそのまま残っている
        assert ana1.results["depth"] == 0.5


class TestLabContextManager:
    """Lab コンテキストマネージャのテスト。"""

    def test_context_manager(self) -> None:
        with Lab("test") as lab:
            rec = lab.new("テスト")
            assert rec.title == "テスト"
