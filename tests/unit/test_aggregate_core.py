"""`labvault.core.aggregate` の pure 関数群を単体検証する。

backend / MCP / CLI の 3 経路がここに delegate するので、ガード仕様
(bool 除外、NaN 除外、merge 優先順、空集合の表現) はここでまとめて
固定する。
"""

from __future__ import annotations

import math

import pytest

from labvault.core.aggregate import (
    AggregateResult,
    StatsResult,
    compute_aggregate,
    compute_stats,
    is_numeric,
    merge_fields,
    numeric_values_only,
)

# ---- is_numeric --------------------------------------------------------------


def test_is_numeric_accepts_int_and_float() -> None:
    assert is_numeric(0)
    assert is_numeric(-3)
    assert is_numeric(0.0)
    assert is_numeric(3.14)
    assert is_numeric(math.inf)  # inf は許容 (情報を失わない)


def test_is_numeric_rejects_bool() -> None:
    """bool は int の subclass だが mean に混ぜると壊れるので除外。"""
    assert not is_numeric(True)
    assert not is_numeric(False)


def test_is_numeric_rejects_nan() -> None:
    assert not is_numeric(float("nan"))


def test_is_numeric_rejects_non_numeric() -> None:
    assert not is_numeric("20")
    assert not is_numeric(None)
    assert not is_numeric([1, 2])
    assert not is_numeric({"a": 1})


# ---- compute_stats -----------------------------------------------------------


def test_compute_stats_empty() -> None:
    s = compute_stats([])
    assert s.count == 0
    # 他フィールドは 0.0 で埋まる (None ではなく)
    assert s.mean == 0.0 and s.std == 0.0


def test_compute_stats_single_value() -> None:
    s = compute_stats([42.0])
    assert s.count == 1
    assert s.mean == 42.0
    assert s.std == 0.0  # 単一値で statistics.stdev は raise なので 0 を返す
    assert s.min == 42.0
    assert s.max == 42.0
    assert s.median == 42.0


def test_compute_stats_basic() -> None:
    s = compute_stats([10, 20, 30, 40, 50])
    assert s.count == 5
    assert s.mean == 30.0
    assert s.min == 10
    assert s.max == 50
    assert s.median == 30.0


def test_compute_stats_min_max_unrounded() -> None:
    """min/max は丸めずに生の値を返す (整数 power=10 の表示を綺麗に保つため)。"""
    s = compute_stats([10, 20])
    assert s.min == 10
    assert s.max == 20


# ---- numeric_values_only -----------------------------------------------------


def test_numeric_values_only_filters_bool_and_nan() -> None:
    vals = [1, 2.5, True, None, "x", float("nan"), 3]
    assert numeric_values_only(vals) == [1.0, 2.5, 3.0]


# ---- merge_fields ------------------------------------------------------------


class _FakeResults:
    """Record.results に相当する duck-type。"""

    def __init__(self, d: dict) -> None:
        self._d = d

    def to_dict(self) -> dict:
        return self._d


class _FakeRecord:
    def __init__(self, conditions: dict, results: dict) -> None:
        self._cond = conditions
        self.results = _FakeResults(results)

    def get_conditions(self) -> dict:
        return self._cond


def test_merge_fields_results_wins_on_conflict() -> None:
    """conditions と results で同じ key を持つとき results が勝つ。

    元の MCP / CLI 実装 (`{**cond, **res}`) と挙動を合わせる。
    """
    rec = _FakeRecord({"power": 10, "shared": "from_cond"}, {"shared": "from_res"})
    merged = merge_fields(rec)
    assert merged["shared"] == "from_res"
    assert merged["power"] == 10


# ---- compute_aggregate -------------------------------------------------------


def test_compute_aggregate_basic() -> None:
    records = [_FakeRecord({"power": v}, {}) for v in [10, 20, 30, 40, 50]]
    res = compute_aggregate(records, "power")
    assert res.key == "power"
    assert res.record_count == 5
    assert res.value_count == 5
    assert res.overall.mean == 30.0


def test_compute_aggregate_excludes_bool_and_strings() -> None:
    """bool / 文字列 / NaN は value_count に入らない。"""
    records = [
        _FakeRecord({"power": 10}, {}),
        _FakeRecord({"power": 20}, {}),
        _FakeRecord({"power": True}, {}),  # bool 除外
        _FakeRecord({"power": "30W"}, {}),  # str 除外
        _FakeRecord({"power": float("nan")}, {}),  # NaN 除外
        _FakeRecord({"other": 99}, {}),  # key 無し
    ]
    res = compute_aggregate(records, "power")
    assert res.record_count == 6
    assert res.value_count == 2
    assert res.overall.mean == 15.0


def test_compute_aggregate_results_key() -> None:
    """results にしかない key も拾える。"""
    records = [
        _FakeRecord({}, {"lattice_a": 2.87}),
        _FakeRecord({}, {"lattice_a": 2.88}),
    ]
    res = compute_aggregate(records, "lattice_a")
    assert res.value_count == 2
    assert res.overall.mean == pytest.approx(2.875)


def test_compute_aggregate_group_by_categorical() -> None:
    records = [
        _FakeRecord({"power": 10, "angle": 0}, {}),
        _FakeRecord({"power": 20, "angle": 0}, {}),
        _FakeRecord({"power": 30, "angle": 45}, {}),
    ]
    res = compute_aggregate(records, "power", group_by="angle")
    assert res.group_by == "angle"
    assert res.groups["0"].mean == 15.0
    assert res.groups["45"].mean == 30.0


def test_compute_aggregate_group_by_missing_yields_unknown() -> None:
    records = [
        _FakeRecord({"power": 10}, {}),  # angle 無し → "unknown"
        _FakeRecord({"power": 20, "angle": 45}, {}),
    ]
    res = compute_aggregate(records, "power", group_by="angle")
    assert "unknown" in res.groups
    assert res.groups["unknown"].mean == 10.0
    assert res.groups["45"].mean == 20.0


def test_compute_aggregate_empty_records() -> None:
    res = compute_aggregate([], "power")
    assert res.record_count == 0
    assert res.value_count == 0
    assert res.overall.count == 0


def test_compute_aggregate_no_matching_key() -> None:
    """key が誰にも無いときは record_count > 0, value_count = 0。"""
    records = [_FakeRecord({"x": 1}, {}), _FakeRecord({"x": 2}, {})]
    res = compute_aggregate(records, "y")
    assert res.record_count == 2
    assert res.value_count == 0


# ---- dataclass shape ---------------------------------------------------------


def test_stats_result_to_dict_keys() -> None:
    d = StatsResult(count=1, mean=1.0).to_dict()
    assert set(d.keys()) == {"count", "mean", "std", "min", "max", "median"}


def test_aggregate_result_to_dict_keys() -> None:
    res = AggregateResult(
        key="x", record_count=0, value_count=0, overall=StatsResult()
    ).to_dict()
    assert set(res.keys()) == {
        "key",
        "record_count",
        "value_count",
        "overall",
        "group_by",
        "groups",
    }
