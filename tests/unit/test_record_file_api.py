"""Record の新ファイル API (add_file / add_bytes / add_object / put) のテスト。

旧 add / save は alias として残るので、旧コードが壊れないことも併せて検証する。

各 method の境界:
    add_file   — path から既存ファイルを取り込む
    add_bytes  — 生バイト列を保存
    add_object — Python オブジェクトを auto-convert して保存
    put        — 上 3 つに dispatch する統一エントリ
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from labvault.core.lab import Lab

# ----------------------------------------------------------------------
# add_file
# ----------------------------------------------------------------------


class TestAddFile:
    def test_add_file_path(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "data.txt"
        f.write_bytes(b"hello")
        rec.add_file(f)
        refs = rec.list_data()
        assert [r.name for r in refs] == ["data.txt"]
        assert rec.get_data("data.txt") == b"hello"

    def test_add_file_rename(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "raw.bin"
        f.write_bytes(b"x")
        rec.add_file(f, name="renamed.bin")
        assert [r.name for r in rec.list_data()] == ["renamed.bin"]

    def test_add_file_content_type_guessed(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "thing.json"
        f.write_bytes(b"{}")
        rec.add_file(f)
        ref = rec.list_data()[0]
        assert ref.content_type == "application/json"

    def test_add_file_content_type_explicit(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "weird"
        f.write_bytes(b"x")
        rec.add_file(f, content_type="custom/x-thing")
        assert rec.list_data()[0].content_type == "custom/x-thing"

    def test_add_file_idempotent(self, lab: Lab, tmp_path: Path) -> None:
        """同 path を 2 回 add しても DataRef は 1 件のまま。"""
        rec = lab.new("test")
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        rec.add_file(f)
        rec.add_file(f)
        assert len(rec.list_data()) == 1

    def test_add_file_overwrite_on_sha_change(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "x.bin"
        f.write_bytes(b"v1")
        rec.add_file(f)
        f.write_bytes(b"v2")
        rec.add_file(f)
        refs = rec.list_data()
        assert len(refs) == 1
        assert rec.get_data("x.bin") == b"v2"

    def test_add_file_returns_self(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "x"
        f.write_bytes(b"x")
        assert rec.add_file(f) is rec

    def test_add_file_missing_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(FileNotFoundError):
            rec.add_file("/nonexistent/path/here.bin")


# ----------------------------------------------------------------------
# add_bytes
# ----------------------------------------------------------------------


class TestAddBytes:
    def test_add_bytes_basic(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_bytes("photo.png", b"\x89PNG\r\n...")
        assert rec.get_data("photo.png") == b"\x89PNG\r\n..."

    def test_add_bytes_default_content_type(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_bytes("blob", b"abc")
        assert rec.list_data()[0].content_type == "application/octet-stream"

    def test_add_bytes_explicit_content_type(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_bytes("photo.png", b"x", content_type="image/png")
        assert rec.list_data()[0].content_type == "image/png"

    def test_add_bytes_accepts_bytearray(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_bytes("ba", bytearray(b"abc"))
        assert rec.get_data("ba") == b"abc"

    def test_add_bytes_accepts_memoryview(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_bytes("mv", memoryview(b"abc"))
        assert rec.get_data("mv") == b"abc"

    def test_add_bytes_idempotent(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_bytes("x", b"v1")
        rec.add_bytes("x", b"v1")
        assert len(rec.list_data()) == 1


# ----------------------------------------------------------------------
# add_object
# ----------------------------------------------------------------------


class TestAddObject:
    def test_add_object_dict_to_json(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("params.json", {"a": 1, "b": 2})
        data = rec.get_data("params.json")
        assert json.loads(data) == {"a": 1, "b": 2}
        assert rec.list_data()[0].content_type == "application/json"

    def test_add_object_dict_auto_extension(self, lab: Lab) -> None:
        """拡張子無しの name は .json が自動補完される。"""
        rec = lab.new("test")
        rec.add_object("params", {"a": 1})
        assert [r.name for r in rec.list_data()] == ["params.json"]

    def test_add_object_list_to_json(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("items", [1, 2, 3])
        assert json.loads(rec.get_data("items.json")) == [1, 2, 3]

    def test_add_object_str_to_txt(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("memo", "hello")
        assert rec.get_data("memo.txt") == b"hello"
        assert rec.list_data()[0].content_type.startswith("text/plain")

    def test_add_object_bytes_passthrough(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("blob.bin", b"\x00\x01")
        assert rec.get_data("blob.bin") == b"\x00\x01"

    def test_add_object_returns_self(self, lab: Lab) -> None:
        rec = lab.new("test")
        assert rec.add_object("x.json", {"a": 1}) is rec


# ----------------------------------------------------------------------
# put (dispatch)
# ----------------------------------------------------------------------


class TestPut:
    def test_put_path_dispatches_to_add_file(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        rec.put(f)
        assert rec.get_data("x.bin") == b"x"

    def test_put_str_path_dispatches_to_add_file(
        self, lab: Lab, tmp_path: Path
    ) -> None:
        rec = lab.new("test")
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        rec.put(str(f))
        assert rec.get_data("x.bin") == b"x"

    def test_put_str_nonexistent_raises_file_not_found(self, lab: Lab) -> None:
        """str は常に path 扱い。リテラル保存したい時は add_object を明示。"""
        rec = lab.new("test")
        with pytest.raises(FileNotFoundError):
            rec.put("/no/such/path.bin")

    def test_put_bytes_dispatches_to_add_bytes(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.put(b"hello", name="greet.bin")
        assert rec.get_data("greet.bin") == b"hello"

    def test_put_bytearray_dispatches_to_add_bytes(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.put(bytearray(b"x"), name="x.bin")
        assert rec.get_data("x.bin") == b"x"

    def test_put_bytes_without_name_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(TypeError, match="name="):
            rec.put(b"x")

    def test_put_dict_dispatches_to_add_object(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.put({"a": 1}, name="params")
        assert json.loads(rec.get_data("params.json")) == {"a": 1}

    def test_put_object_without_name_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(TypeError, match="name="):
            rec.put({"a": 1})

    def test_put_returns_self(self, lab: Lab) -> None:
        rec = lab.new("test")
        assert rec.put(b"x", name="x") is rec


# ----------------------------------------------------------------------
# Legacy alias: add / save
# ----------------------------------------------------------------------


class TestLegacyAliases:
    """旧 add / save は互換 alias として動作し続けることを保証する。"""

    def test_legacy_add_with_path(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "x.bin"
        f.write_bytes(b"v")
        rec.add(f)
        assert rec.get_data("x.bin") == b"v"

    def test_legacy_add_with_bytes(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add(b"v", name="x.bin")
        assert rec.get_data("x.bin") == b"v"

    def test_legacy_add_with_bytes_default_name(self, lab: Lab) -> None:
        """旧 add(bytes) で name 省略 → 'untitled' (旧挙動と一致)。"""
        rec = lab.new("test")
        rec.add(b"x")
        assert [r.name for r in rec.list_data()] == ["untitled"]

    def test_legacy_save_dict(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.save("params", {"a": 1})
        assert json.loads(rec.get_data("params.json")) == {"a": 1}

    def test_legacy_save_str(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.save("memo", "hello")
        assert rec.get_data("memo.txt") == b"hello"

    def test_legacy_no_deprecation_warning_yet(self, lab: Lab, tmp_path: Path) -> None:
        """B 方針: まだ DeprecationWarning は出さない (今 phase の合意)。"""
        rec = lab.new("test")
        f = tmp_path / "x"
        f.write_bytes(b"x")
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            rec.add(f)
            rec.save("p", {"a": 1})


# ----------------------------------------------------------------------
# add_dir still works (内部で add_file を呼ぶ)
# ----------------------------------------------------------------------


def test_add_dir_uses_new_api(lab: Lab, tmp_path: Path) -> None:
    rec = lab.new("test")
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_bytes(b"b")
    rec.add_dir(tmp_path)
    names = sorted(r.name for r in rec.list_data())
    assert names == ["a.txt", "sub/b.txt"]


# ----------------------------------------------------------------------
# BytesIO 等の "bytes 系" は put では渡せない (type strict)、
# 代わりに .getvalue() を渡すか add_bytes を直接呼ぶ運用
# ----------------------------------------------------------------------


def test_io_bytesio_via_getvalue(lab: Lab) -> None:
    rec = lab.new("test")
    buf = io.BytesIO(b"data")
    rec.add_bytes("buf.bin", buf.getvalue())
    assert rec.get_data("buf.bin") == b"data"


# ----------------------------------------------------------------------
# DataRef.original_type — add_object 経路で semantic タグが付与されることを確認
#
# 用途: Web UI / MCP / LLM が「.npy は ndarray、.png は Figure」を
# 拡張子推測ではなく metadata から確実に判別できる。
# ----------------------------------------------------------------------


class TestOriginalType:
    def test_add_object_dict_tags_dict(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("params.json", {"a": 1})
        assert rec.list_data()[0].original_type == "dict"

    def test_add_object_list_tags_list(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("items.json", [1, 2, 3])
        assert rec.list_data()[0].original_type == "list"

    def test_add_object_str_tags_str(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("memo", "hello")
        assert rec.list_data()[0].original_type == "str"

    def test_add_object_bytes_tags_bytes(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.add_object("blob.bin", b"\x00\x01")
        assert rec.list_data()[0].original_type == "bytes"

    def test_add_object_ndarray_tags_ndarray(self, lab: Lab) -> None:
        import numpy as np

        rec = lab.new("test")
        rec.add_object("spectrum", np.array([1.0, 2.0, 3.0]))
        ref = rec.list_data()[0]
        assert ref.original_type == "ndarray"
        assert ref.name == "spectrum.npy"

    def test_add_object_figure_tags_figure(self, lab: Lab) -> None:
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")
        plt = pytest.importorskip("matplotlib.pyplot")

        rec = lab.new("test")
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3])
        rec.add_object("plot.png", fig)
        plt.close(fig)
        ref = rec.list_data()[0]
        assert ref.original_type == "figure"
        assert ref.name == "plot.png"

    def test_add_object_dataframe_tags_dataframe(self, lab: Lab) -> None:
        pd = pytest.importorskip("pandas")

        rec = lab.new("test")
        rec.add_object("table", pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
        ref = rec.list_data()[0]
        assert ref.original_type == "dataframe"
        assert ref.name == "table.csv"

    def test_add_file_has_none(self, lab: Lab, tmp_path: Path) -> None:
        """raw な add_file 経路では original_type が None (= 由来不明)。"""
        rec = lab.new("test")
        f = tmp_path / "raw.bin"
        f.write_bytes(b"x")
        rec.add_file(f)
        assert rec.list_data()[0].original_type is None

    def test_add_bytes_has_none(self, lab: Lab) -> None:
        """raw な add_bytes 経路では original_type が None。"""
        rec = lab.new("test")
        rec.add_bytes("blob.bin", b"x")
        assert rec.list_data()[0].original_type is None

    def test_put_path_propagates_none(self, lab: Lab, tmp_path: Path) -> None:
        rec = lab.new("test")
        f = tmp_path / "x.bin"
        f.write_bytes(b"x")
        rec.put(f)
        assert rec.list_data()[0].original_type is None

    def test_put_object_propagates_tag(self, lab: Lab) -> None:
        """put 経由でも add_object に流れれば original_type が付く。"""
        rec = lab.new("test")
        rec.put({"a": 1}, name="params")
        assert rec.list_data()[0].original_type == "dict"

    def test_persist_round_trip(self, lab: Lab) -> None:
        """_to_dict / 再構成で original_type が保持される。"""
        rec = lab.new("test")
        rec.add_object("params.json", {"a": 1})

        from labvault.core.record import Record

        snapshot = rec._to_dict()
        rec2 = Record._from_dict(snapshot, lab=lab)
        assert rec2.list_data()[0].original_type == "dict"

    def test_legacy_record_without_field_loads(self, lab: Lab) -> None:
        """既存 Firestore データ (original_type field 無し) も graceful に読める。"""
        from labvault.core.record import Record

        snapshot = lab.new("test")._to_dict()
        # 古いスキーマを模す: data_refs から original_type を削る
        snapshot["data_refs"] = [
            {
                "name": "old.bin",
                "nextcloud_path": "p",
                "content_type": "application/octet-stream",
                "size_bytes": 1,
                "sha256": "abc",
            }
        ]
        rec = Record._from_dict(snapshot, lab=lab)
        # default は None
        assert rec.list_data()[0].original_type is None
