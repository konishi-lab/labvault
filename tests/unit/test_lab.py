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

    def test_list_parent_id_root_only(self, lab: Lab) -> None:
        """C2: parent_id=None で root record のみを返す。"""
        parent = lab.new("parent")
        parent.sub("child-1")
        parent.sub("child-2")
        lab.new("other-root")

        root_only = lab.list(parent_id=None)
        ids = {r.id for r in root_only}
        assert parent.id in ids
        assert len(ids) == 2  # parent + other-root
        # 子は含まれていない
        assert all(r.parent_id is None for r in root_only)

    def test_list_parent_id_specific(self, lab: Lab) -> None:
        """C2: parent_id='X' で X 直下の子のみを返す。"""
        parent = lab.new("parent")
        c1 = parent.sub("child-1")
        c2 = parent.sub("child-2")
        lab.new("other-root")  # 関係ない root

        children = lab.list(parent_id=parent.id)
        ids = {r.id for r in children}
        assert ids == {c1.id, c2.id}

    def test_list_parent_id_unset_returns_all(self, lab: Lab) -> None:
        """C2: parent_id='__unset__' (default) は全件 (フィルタなし)。"""
        parent = lab.new("parent")
        parent.sub("child")
        # default なので parent_id 指定なし
        all_recs = lab.list()
        ids = {r.id for r in all_recs}
        assert len(ids) >= 2  # parent + child の両方


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


class TestLabPublicAPI:
    """C2 (2026-06-30): C2 で public 化した API の smoke test。"""

    def test_team_property(self, lab: Lab) -> None:
        """Lab.team は public な team_id getter。"""
        # conftest の lab fixture が team="test-team" で構築している前提。
        assert lab.team == "test-team"

    def test_backend_property_returns_metadata(self, lab: Lab) -> None:
        """Lab.backend は MetadataBackend Protocol を返す (admin escape hatch)。"""
        from labvault.backends.memory import InMemoryMetadataBackend

        assert isinstance(lab.backend, InMemoryMetadataBackend)
        # Protocol method が呼べる (raw access)
        rec = lab.new("t")
        raw = lab.backend.get_record(lab.team, rec.id)
        assert raw is not None
        assert raw["id"] == rec.id

    def test_get_cell_logs_empty(self, lab: Lab) -> None:
        """cell log 未保存の record では空 list を返す。"""
        rec = lab.new("t")
        assert lab.get_cell_logs(rec.id) == []

    def test_save_and_get_cell_logs(self, lab: Lab) -> None:
        """save_cell_log → get_cell_logs roundtrip。"""
        rec = lab.new("t")
        lab.save_cell_log(
            rec.id,
            {"cell_id": "c1", "cell_number": 1, "code": "print(1)"},
        )
        lab.save_cell_log(
            rec.id,
            {"cell_id": "c2", "cell_number": 2, "code": "print(2)"},
        )
        logs = lab.get_cell_logs(rec.id)
        assert len(logs) == 2
        assert [log["cell_number"] for log in logs] == [1, 2]


class TestLabGetUsage:
    """Lab.get_usage — team の storage 集計 (2026-07-01)。"""

    def _seed(self, lab: Lab) -> None:
        from labvault.core.types import DataRef

        rec1 = lab.new("a1", auto_log=False, created_by="alice@x.com")
        rec2 = lab.new("a2", auto_log=False, created_by="alice@x.com")
        rec3 = lab.new("b1", auto_log=False, created_by="bob@x.com")
        for r, files in (
            (
                rec1,
                [
                    DataRef(name="x.npz", size_bytes=100_000),
                    DataRef(name="x.png", size_bytes=500),
                ],
            ),
            (rec2, [DataRef(name="y.npz", size_bytes=200_000)]),
            (rec3, [DataRef(name="z.png", size_bytes=1_000)]),
        ):
            r._data_refs.extend(files)
            r._persist()

    def test_totals(self, lab: Lab) -> None:
        self._seed(lab)
        s = lab.get_usage()
        assert s["total_records"] == 3
        assert s["total_files"] == 4
        assert s["total_bytes"] == 301_500

    def test_by_creator_split(self, lab: Lab) -> None:
        self._seed(lab)
        s = lab.get_usage()
        assert s["by_creator"]["alice@x.com"] == {
            "records": 2,
            "files": 3,
            "bytes": 300_500,
        }
        assert s["by_creator"]["bob@x.com"] == {
            "records": 1,
            "files": 1,
            "bytes": 1_000,
        }

    def test_by_extension_and_type(self, lab: Lab) -> None:
        self._seed(lab)
        s = lab.get_usage()
        assert s["by_extension"]["npz"] == {"files": 2, "bytes": 300_000}
        assert s["by_extension"]["png"] == {"files": 2, "bytes": 1_500}
        # 全部 experiment (default type)
        assert s["by_type"]["experiment"] == 3

    def test_created_by_filter(self, lab: Lab) -> None:
        self._seed(lab)
        s = lab.get_usage(created_by="alice@x.com")
        assert s["total_records"] == 2
        assert s["total_files"] == 3
        assert s["total_bytes"] == 300_500
        assert set(s["by_creator"].keys()) == {"alice@x.com"}

    def test_deleted_records_excluded(self, lab: Lab) -> None:
        from labvault.core.types import DataRef

        rec = lab.new("gone", auto_log=False, created_by="alice@x.com")
        rec._data_refs.append(DataRef(name="gone.npz", size_bytes=999))
        rec._persist()
        lab.delete(rec.id)
        s = lab.get_usage()
        assert s["total_records"] == 0
        assert s["total_bytes"] == 0


class TestNoPrivateAccessInvariant:
    """C2 invariant: 外部モジュールから lab._team / lab._metadata を触らない。

    SDK の `core/lab.py` と `core/record.py` 自身 (= tight-coupled な対の
    実装) と CLI の help テキスト以外で、``lab._team`` / ``lab._metadata``
    を検出したら fail。リグレッション防止 (= 「ちょっと書いてしまえ」を
    防ぐ)。
    """

    def test_no_external_private_access(self) -> None:
        import re
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent.parent
        targets = [
            repo_root / "src" / "labvault",
            repo_root / "platform" / "backend" / "app",
        ]
        allowed = {
            repo_root / "src" / "labvault" / "core" / "lab.py",
            repo_root / "src" / "labvault" / "core" / "record.py",
        }

        pattern = re.compile(r"\blab\._(team|metadata)\b")
        offenders: list[str] = []
        for root in targets:
            for path in root.rglob("*.py"):
                if path in allowed:
                    continue
                text = path.read_text(encoding="utf-8")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if pattern.search(line):
                        rel = path.relative_to(repo_root)
                        offenders.append(f"{rel}:{lineno}: {line.strip()}")

        assert not offenders, (
            "外部モジュールが lab._team / lab._metadata を直接参照しています。"
            " lab.team / lab.backend / lab.list(parent_id=...) 等の public API を"
            " 使ってください (C2 規約):\n  - " + "\n  - ".join(offenders)
        )
