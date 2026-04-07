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


class TestLabContextManager:
    """Lab コンテキストマネージャのテスト。"""

    def test_context_manager(self) -> None:
        with Lab("test") as lab:
            rec = lab.new("テスト")
            assert rec.title == "テスト"
