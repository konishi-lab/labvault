"""core/types.py のテスト。"""

from __future__ import annotations

from labvault.core.types import (
    CellLog,
    DataRef,
    ExternalRef,
    Link,
    Note,
    RecordType,
    Status,
)


class TestStatus:
    def test_values(self) -> None:
        assert Status.RUNNING == "running"
        assert Status.SUCCESS == "success"
        assert Status.FAILED == "failed"
        assert Status.PARTIAL == "partial"

    def test_str_comparison(self) -> None:
        assert Status.SUCCESS == "success"
        assert Status.SUCCESS == "success"


class TestRecordType:
    def test_values(self) -> None:
        assert RecordType.EXPERIMENT == "experiment"
        assert RecordType.SAMPLE == "sample"
        assert RecordType.MEASUREMENT == "measurement"

    def test_str_comparison(self) -> None:
        assert RecordType.EXPERIMENT == "experiment"


class TestNote:
    def test_create(self) -> None:
        note = Note(text="結晶性良好")
        assert note.text == "結晶性良好"
        assert note.author == ""
        assert note.created_at.tzinfo is not None  # timezone-aware

    def test_with_author(self) -> None:
        note = Note(text="メモ", author="tanaka")
        assert note.author == "tanaka"


class TestLink:
    def test_create(self) -> None:
        link = Link(target_id="AB3F")
        assert link.target_id == "AB3F"
        assert link.relation == "related_to"

    def test_with_relation(self) -> None:
        link = Link(target_id="AB3F", relation="derived_from", description="元データ")
        assert link.relation == "derived_from"
        assert link.description == "元データ"


class TestDataRef:
    def test_create(self) -> None:
        ref = DataRef(name="xrd_data.csv", size_bytes=1024)
        assert ref.name == "xrd_data.csv"
        assert ref.size_bytes == 1024
        assert ref.sha256 == ""


class TestExternalRef:
    def test_create(self) -> None:
        ref = ExternalRef(uri="TSUBAME:/work/vasp/WAVECAR", size_bytes=12_000_000_000)
        assert ref.uri == "TSUBAME:/work/vasp/WAVECAR"

    def test_with_doi(self) -> None:
        ref = ExternalRef(uri="", doi="10.5281/zenodo.12345")
        assert ref.doi == "10.5281/zenodo.12345"


class TestCellLog:
    def test_create(self) -> None:
        log = CellLog(
            cell_id="c1",
            record_id="AB3F",
            cell_number=1,
            execution_count=1,
            source="import numpy as np",
        )
        assert log.cell_id == "c1"
        assert log.record_id == "AB3F"
        assert log.new_vars == {}
        assert log.executed_at.tzinfo is not None
