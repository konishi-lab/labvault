"""Record クラスのテスト。"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from labvault.core.lab import Lab
from labvault.core.record import Record
from labvault.core.types import Status


class TestRecordCreation:
    """Record 生成の基本テスト。"""

    def test_new_creates_record(self, lab: Lab) -> None:
        rec = lab.new("テスト実験")
        assert isinstance(rec, Record)
        assert len(rec.id) == 4
        assert rec.title == "テスト実験"
        assert rec.status == Status.RUNNING
        assert rec.team == "test-team"

    def test_new_with_conditions(self, lab: Lab) -> None:
        rec = lab.new(
            "温度テスト",
            temperature_C=500,
            pressure_Pa=0.5,
        )
        cond = rec.get_conditions()
        assert cond["temperature_C"] == 500
        assert cond["pressure_Pa"] == 0.5

    def test_new_with_tags(self, lab: Lab) -> None:
        rec = lab.new("タグテスト", tags=["XRD", "Fe-Cr"])
        assert rec.tags == ["XRD", "Fe-Cr"]

    def test_new_with_sample_link(self, lab: Lab) -> None:
        sample = lab.new("サンプル", type="sample")
        rec = lab.new("測定", sample=sample.id)
        links = rec.links
        assert len(links) == 1
        assert links[0].target_id == sample.id
        assert links[0].relation == "measured_on"


class TestRecordProperties:
    """Record プロパティのテスト。"""

    def test_title_setter(self, lab: Lab) -> None:
        rec = lab.new("元タイトル")
        rec.title = "新タイトル"
        assert rec.title == "新タイトル"
        # バックエンドに永続化されている
        fetched = lab.get(rec.id)
        assert fetched.title == "新タイトル"

    def test_status_setter_with_string(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.status = "success"
        assert rec.status == Status.SUCCESS

    def test_status_setter_with_enum(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.status = Status.FAILED
        assert rec.status == Status.FAILED


class TestMethodChaining:
    """メソッドチェーンのテスト。"""

    def test_conditions_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.conditions(temp=100)
        assert result is rec

    def test_tag_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.tag("XRD")
        assert result is rec

    def test_untag_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.tag("XRD")
        result = rec.untag("XRD")
        assert result is rec

    def test_note_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.note("メモ")
        assert result is rec

    def test_link_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.link("AB3F", "related_to")
        assert result is rec

    def test_add_ref_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.add_ref("https://example.com")
        assert result is rec

    def test_log_value_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.log_value("temp", 25.0)
        assert result is rec

    def test_log_event_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.log_event("start", "測定開始")
        assert result is rec

    def test_chaining_multiple(self, lab: Lab) -> None:
        rec = lab.new("チェーンテスト").conditions(temp=100).tag("XRD").note("メモ")
        assert rec.get_conditions()["temp"] == 100
        assert "XRD" in rec.tags
        assert len(rec.notes) == 1


class TestTag:
    """tag / untag のテスト。"""

    def test_tag_adds(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.tag("A", "B")
        assert rec.tags == ["A", "B"]

    def test_tag_dedup(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.tag("A")
        rec.tag("A")
        assert rec.tags == ["A"]

    def test_untag_removes(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.tag("A", "B", "C")
        rec.untag("B")
        assert rec.tags == ["A", "C"]


class TestNote:
    """note のテスト。"""

    def test_note_adds(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.note("メモ1")
        rec.note("メモ2")
        assert len(rec.notes) == 2
        assert rec.notes[0].text == "メモ1"
        assert rec.notes[1].text == "メモ2"

    def test_note_idempotent(self, lab: Lab) -> None:
        """直近と同一テキストなら追加しない (冪等性)."""
        rec = lab.new("テスト")
        rec.note("同じメモ")
        rec.note("同じメモ")
        assert len(rec.notes) == 1

    def test_note_different_text_adds(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.note("メモ1")
        rec.note("メモ2")
        rec.note("メモ1")  # 直近がメモ2なので追加される
        assert len(rec.notes) == 3


class TestResults:
    """results proxy のテスト。"""

    def test_setitem(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.results["lattice_a"] = 2.873
        assert rec.results["lattice_a"] == 2.873

    def test_contains(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.results["key"] = 1
        assert "key" in rec.results
        assert "missing" not in rec.results

    def test_len(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        assert len(rec.results) == 0
        rec.results["a"] = 1
        assert len(rec.results) == 1

    def test_to_dict(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.results["a"] = 1
        rec.results["b"] = 2
        assert rec.results.to_dict() == {"a": 1, "b": 2}

    def test_persist_on_setitem(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.results["val"] = 42
        fetched = lab.get(rec.id)
        assert fetched.results["val"] == 42


class TestLogValueAndEvent:
    """log_value / log_event のテスト。"""

    def test_log_value(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.log_value("temperature", 25.0)
        assert len(rec.events) == 1
        ev = rec.events[0]
        assert ev["type"] == "value"
        assert ev["key"] == "temperature"
        assert ev["value"] == 25.0
        assert "timestamp" in ev

    def test_log_event(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.log_event("start", "測定開始")
        assert len(rec.events) == 1
        ev = rec.events[0]
        assert ev["type"] == "start"
        assert ev["description"] == "測定開始"


class TestAdd:
    """add (ファイル保存) のテスト。"""

    def test_add_bytes(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.add(b"hello", name="data.bin")
        assert len(rec.data_refs) == 1
        ref = rec.data_refs[0]
        assert ref.name == "data.bin"
        assert ref.size_bytes == 5
        assert ref.sha256 == hashlib.sha256(b"hello").hexdigest()

    def test_add_file(self, lab: Lab) -> None:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"file content")
            f.flush()
            rec = lab.new("テスト")
            rec.add(f.name)

        assert len(rec.data_refs) == 1
        ref = rec.data_refs[0]
        assert ref.name == Path(f.name).name
        assert ref.size_bytes == 12

    def test_add_idempotent_same_hash(self, lab: Lab) -> None:
        """同一ファイル名 & 同一ハッシュならスキップ。"""
        rec = lab.new("テスト")
        rec.add(b"data", name="file.bin")
        rec.add(b"data", name="file.bin")
        assert len(rec.data_refs) == 1

    def test_add_overwrites_different_hash(self, lab: Lab) -> None:
        """同一ファイル名で内容が異なれば上書き。"""
        rec = lab.new("テスト")
        rec.add(b"old", name="file.bin")
        rec.add(b"new", name="file.bin")
        assert len(rec.data_refs) == 1
        assert rec.data_refs[0].sha256 == hashlib.sha256(b"new").hexdigest()

    def test_add_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.add(b"data", name="f.bin")
        assert result is rec


class TestSave:
    """save (Python オブジェクト保存) のテスト。"""

    def test_save_dict(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.save("params", {"a": 1, "b": 2})
        assert len(rec.data_refs) == 1
        ref = rec.data_refs[0]
        assert ref.name == "params.json"
        assert ref.content_type == "application/json"

    def test_save_list(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.save("items", [1, 2, 3])
        ref = rec.data_refs[0]
        assert ref.name == "items.json"

    def test_save_string(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.save("readme", "Hello World")
        ref = rec.data_refs[0]
        assert ref.name == "readme.txt"
        assert "text/plain" in ref.content_type

    def test_save_bytes(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.save("raw", b"\x00\x01\x02")
        ref = rec.data_refs[0]
        assert ref.name == "raw"

    def test_save_returns_self(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        result = rec.save("data", {"key": "val"})
        assert result is rec

    def test_save_unsupported_type(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        with pytest.raises(TypeError, match="Unsupported type"):
            rec.save("obj", object())

    def test_save_with_extension(self, lab: Lab) -> None:
        """拡張子付きの名前はそのまま使う。"""
        rec = lab.new("テスト")
        rec.save("data.csv", "a,b\n1,2")
        ref = rec.data_refs[0]
        assert ref.name == "data.csv"


class TestContextManager:
    """コンテキストマネージャのテスト。"""

    def test_success_on_normal_exit(self, lab: Lab) -> None:
        with lab.new("テスト") as rec:
            rec.results["val"] = 1
        assert rec.status == Status.SUCCESS

    def test_failed_on_exception(self, lab: Lab) -> None:
        with pytest.raises(ValueError, match="error"), lab.new("テスト") as rec:
            msg = "error"
            raise ValueError(msg)
        assert rec.status == Status.FAILED

    def test_keeps_non_running_status(self, lab: Lab) -> None:
        """RUNNING 以外のステータスは __exit__ で変更しない。"""
        with lab.new("テスト") as rec:
            rec.status = Status.PARTIAL
        assert rec.status == Status.PARTIAL


class TestPersistence:
    """永続化のテスト。"""

    def test_conditions_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.conditions(temp=100)
        fetched = lab.get(rec.id)
        assert fetched.get_conditions()["temp"] == 100

    def test_tags_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.tag("XRD")
        fetched = lab.get(rec.id)
        assert "XRD" in fetched.tags

    def test_notes_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.note("メモ")
        fetched = lab.get(rec.id)
        assert len(fetched.notes) == 1
        assert fetched.notes[0].text == "メモ"

    def test_links_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.link("ABCD", "related_to")
        fetched = lab.get(rec.id)
        assert len(fetched.links) == 1
        assert fetched.links[0].target_id == "ABCD"

    def test_events_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.log_value("x", 10)
        fetched = lab.get(rec.id)
        assert len(fetched.events) == 1

    def test_external_refs_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.add_ref("https://example.com", description="ref")
        fetched = lab.get(rec.id)
        assert len(fetched.external_refs) == 1
        assert fetched.external_refs[0].uri == "https://example.com"

    def test_data_refs_persisted(self, lab: Lab) -> None:
        rec = lab.new("テスト")
        rec.add(b"data", name="file.bin")
        fetched = lab.get(rec.id)
        assert len(fetched.data_refs) == 1
        assert fetched.data_refs[0].name == "file.bin"


class TestRepr:
    """__repr__ のテスト。"""

    def test_repr(self, lab: Lab) -> None:
        rec = lab.new("テスト実験")
        r = repr(rec)
        assert "Record(" in r
        assert rec.id in r
        assert "テスト実験" in r
