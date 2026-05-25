"""ファイルパーサー連携 (M3 part 2) のユニットテスト。

カバー範囲:
- PARSER_REGISTRY: 登録 / lookup / ビルトイン (ras_parser) の自動登録
- Rigaku .ras parser: ヘッダから target / wavelength_A / two_theta_*/
  scan_speed_*/sample_name を抽出する
- Record.add() の dispatch:
  - 拡張子が template の file_parsers と一致したら parser を起動して
    conditions に自動充填する
  - 手動入力済の key は parser 値で上書きされない
  - 拡張子未一致なら no-op
  - template 未指定なら no-op
  - parser_name が未登録なら UserWarning
  - parser が例外を投げても add 自体は成功する
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab
from labvault.parsers import PARSER_REGISTRY
from labvault.parsers.builtin.ras import parse_ras


@pytest.fixture()
def lab() -> Lab:
    return Lab(
        "test-team",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


# Rigaku .ras ヘッダ (代表 key だけ含む簡略版)。utf-8 を想定。
_RAS_SAMPLE = b"""*RAS_DATA_START
*FILE_SAMPLE "FeCr-001"
*HW_XG_TARGET_NAME "Cu"
*HW_XG_WAVE_LENGTH_ALPHA1 1.5418
*MEAS_SCAN_START 10.0
*MEAS_SCAN_STOP 80.0
*MEAS_SCAN_SPEED 2.0
*MEAS_SCAN_STEP 0.02
*RAS_INT_START
1.0 100
2.0 120
*RAS_INT_END
*RAS_DATA_END
"""


# ----------------------------------------------------------------------
# Rigaku .ras parser
# ----------------------------------------------------------------------


def test_ras_parser_extracts_core_conditions() -> None:
    out = parse_ras(_RAS_SAMPLE, "sample.ras")
    assert out["target"] == "Cu"
    assert out["wavelength_A"] == pytest.approx(1.5418)
    assert out["two_theta_start_deg"] == pytest.approx(10.0)
    assert out["two_theta_end_deg"] == pytest.approx(80.0)
    assert out["scan_speed_deg_per_min"] == pytest.approx(2.0)
    assert out["step_deg"] == pytest.approx(0.02)
    assert out["sample_name"] == "FeCr-001"


def test_ras_parser_skips_unknown_keys() -> None:
    # 未知 key だらけだと空 dict を返す
    out = parse_ras(b'*UNKNOWN_KEY "foo"\n*ANOTHER 1.0\n', "x.ras")
    assert out == {}


def test_ras_parser_handles_cp932() -> None:
    # cp932 (Shift_JIS) でもデコードされる
    sample = '*FILE_SAMPLE "サンプルA"\n*HW_XG_TARGET_NAME "Cu"\n'.encode("cp932")
    out = parse_ras(sample, "x.ras")
    assert out["sample_name"] == "サンプルA"
    assert out["target"] == "Cu"


def test_ras_parser_invalid_number_is_skipped() -> None:
    # 数値 cast に失敗するキーは黙ってスキップ (target 等は残る)
    sample = b'*HW_XG_TARGET_NAME "Cu"\n*MEAS_SCAN_START "not-a-number"\n'
    out = parse_ras(sample, "x.ras")
    assert out["target"] == "Cu"
    assert "two_theta_start_deg" not in out


# ----------------------------------------------------------------------
# PARSER_REGISTRY
# ----------------------------------------------------------------------


def test_registry_has_builtins_registered() -> None:
    assert "ras_parser" in PARSER_REGISTRY.names()
    assert PARSER_REGISTRY.get("ras_parser") is parse_ras


def test_registry_register_and_lookup() -> None:
    def my_parser(data: bytes, file_name: str) -> dict[str, object]:
        return {"foo": "bar"}

    PARSER_REGISTRY.register("test_dummy_parser", my_parser)
    try:
        assert PARSER_REGISTRY.get("test_dummy_parser") is my_parser
    finally:
        PARSER_REGISTRY._parsers.pop("test_dummy_parser", None)


# ----------------------------------------------------------------------
# Record.add() dispatch
# ----------------------------------------------------------------------


def test_add_auto_extracts_conditions_via_template(lab: Lab, tmp_path: Path) -> None:
    # XRD template は .ras → ras_parser を宣言済
    exp = lab.new("auto-fill", template="XRD")
    p = tmp_path / "scan.ras"
    p.write_bytes(_RAS_SAMPLE)
    exp.add(p)

    cond = exp.get_conditions()
    assert cond["target"] == "Cu"
    assert cond["wavelength_A"] == pytest.approx(1.5418)
    assert cond["two_theta_start_deg"] == pytest.approx(10.0)
    assert cond["two_theta_end_deg"] == pytest.approx(80.0)
    assert cond["sample_name"] == "FeCr-001"


def test_add_does_not_overwrite_manual_conditions(lab: Lab, tmp_path: Path) -> None:
    # 手動で target=Mo を入力 → .ras 投入しても target は Mo のまま
    exp = lab.new("manual-priority", template="XRD", target="Mo")
    p = tmp_path / "scan.ras"
    p.write_bytes(_RAS_SAMPLE)
    exp.add(p)

    cond = exp.get_conditions()
    assert cond["target"] == "Mo"  # 手動値が勝つ
    # 未入力 key は parser 値で埋まる
    assert cond["wavelength_A"] == pytest.approx(1.5418)


def test_add_noop_when_extension_not_in_template(lab: Lab, tmp_path: Path) -> None:
    # .txt は XRD の file_parsers に無い → conditions は変化しない
    exp = lab.new("no-parser-match", template="XRD")
    p = tmp_path / "note.txt"
    p.write_bytes(b"hello")
    exp.add(p)
    assert exp.get_conditions() == {}


def test_add_noop_when_no_template(lab: Lab, tmp_path: Path) -> None:
    # template 未指定 record では parser は走らない
    exp = lab.new("no-template")
    p = tmp_path / "scan.ras"
    p.write_bytes(_RAS_SAMPLE)
    exp.add(p)
    assert exp.get_conditions() == {}


def test_add_warns_when_parser_name_unregistered(lab: Lab, tmp_path: Path) -> None:
    # XRD には bruker_raw_parser が宣言されているが未登録 → warning
    exp = lab.new("missing-parser", template="XRD")
    p = tmp_path / "scan.raw"
    p.write_bytes(b"\x00\x01\x02")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        exp.add(p)
    msgs = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("bruker_raw_parser" in m and "未登録" in m for m in msgs)


def test_add_swallows_parser_exception(lab: Lab, tmp_path: Path) -> None:
    # parser が例外を投げても add は成功し、warning が出る
    from labvault.core.types import FileParserConfig, TemplateV10

    def bad_parser(data: bytes, file_name: str) -> dict[str, object]:
        msg = "boom"
        raise RuntimeError(msg)

    PARSER_REGISTRY.register("test_bad_parser", bad_parser)
    try:
        tpl = TemplateV10(
            name="BadParserTpl",
            file_parsers=[
                FileParserConfig(extension=".bad", parser_name="test_bad_parser"),
            ],
        )
        lab.define_template(tpl)

        exp = lab.new("oops", template="BadParserTpl")
        p = tmp_path / "x.bad"
        p.write_bytes(b"data")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            exp.add(p)
        # ファイル自体は登録されている (add は成功)
        assert any(d.name == "x.bad" for d in exp.list_data())
        msgs = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
        assert any("test_bad_parser" in m and "boom" in m for m in msgs)
    finally:
        PARSER_REGISTRY._parsers.pop("test_bad_parser", None)


def test_add_respects_auto_extract_conditions_false(lab: Lab, tmp_path: Path) -> None:
    # auto_extract_conditions=False なら parser は走らない
    from labvault.core.types import FileParserConfig, TemplateV10

    def my_parser(data: bytes, file_name: str) -> dict[str, object]:
        return {"foo": "should-not-be-set"}

    PARSER_REGISTRY.register("test_off_parser", my_parser)
    try:
        tpl = TemplateV10(
            name="OffParserTpl",
            file_parsers=[
                FileParserConfig(
                    extension=".off",
                    parser_name="test_off_parser",
                    auto_extract_conditions=False,
                ),
            ],
        )
        lab.define_template(tpl)

        exp = lab.new("off", template="OffParserTpl")
        p = tmp_path / "x.off"
        p.write_bytes(b"data")
        exp.add(p)
        assert "foo" not in exp.get_conditions()
    finally:
        PARSER_REGISTRY._parsers.pop("test_off_parser", None)
