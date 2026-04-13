"""labvault.core.units のテスト。"""

from __future__ import annotations

import warnings

import pytest

from labvault.core.units import (
    ALL_UNITS,
    UNIT_CATEGORIES,
    find_category,
    validate_unit,
)


class TestAllUnits:
    """ALL_UNITS の基本プロパティ。"""

    def test_not_empty(self) -> None:
        assert len(ALL_UNITS) > 50

    def test_common_units_present(self) -> None:
        for u in [
            "J",
            "uJ",
            "mJ",
            "W",
            "nm",
            "um",
            "fs",
            "ps",
            "Hz",
            "kHz",
            "degC",
            "Pa",
            "V",
            "A",
            "ohm",
            "%",
            "J/cm^2",
        ]:
            assert u in ALL_UNITS, f"{u} が ALL_UNITS にない"

    def test_all_ascii(self) -> None:
        for u in ALL_UNITS:
            assert u.isascii(), f"{u} に非 ASCII 文字が含まれている"

    def test_categories_cover_all(self) -> None:
        """カテゴリ和集合 == ALL_UNITS。"""
        union = frozenset().union(*UNIT_CATEGORIES.values())
        assert union == ALL_UNITS


class TestValidateUnit:
    """validate_unit のテスト。"""

    def test_valid_unit(self) -> None:
        assert validate_unit("J") is True

    def test_invalid_unit_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = validate_unit("furlongs")
            assert result is False
            assert len(w) == 1
            assert "furlongs" in str(w[0].message)

    def test_invalid_unit_strict(self) -> None:
        with pytest.raises(ValueError, match="非標準"):
            validate_unit("bogus", strict=True)


class TestFindCategory:
    """find_category のテスト。"""

    def test_known(self) -> None:
        assert find_category("J") == "energy"
        assert find_category("nm") == "length"
        assert find_category("fs") == "time"
        assert find_category("J/cm^2") == "fluence"

    def test_unknown(self) -> None:
        assert find_category("xyz") is None
