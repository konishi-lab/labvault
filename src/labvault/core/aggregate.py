"""数値集合の集計と record 集合からの key 抽出を扱う pure 関数群。

aggregate ロジックはこれまで backend (`platform/backend/.../records.py`) /
MCP (`mcp/server.py`) / CLI (`cli/main.py`) で 3 重実装になっており、
PR #74 で発覚した「MCP / CLI で `isinstance(v, bool)` ガード漏れにより
True/False が 1.0/0.0 として mean に混入する」バグの温床になっていた。

本モジュールに pure 関数として 1 本化することで:

1. ガード仕様 (bool 除外、conditions/results のマージ順、float 化、
   NaN ハンドリング等) を 1 箇所に集約
2. 3 経路の delegate 化により実装ズレが構造的に再発しない
3. ユニットテスト (`tests/unit/test_aggregate_core.py`) で挙動を固定

外部依存無し、stdlib `statistics` のみ。Record 型に直接依存せず
duck-typed (record.get_conditions() / record.results.to_dict() を持つ
オブジェクトなら何でも) に保つ。
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

# ---- 値抽出 (numeric ガード) --------------------------------------------------


def is_numeric(value: Any) -> bool:
    """`value` が aggregate に乗せるべき数値かを判定する。

    Python の `bool` は `int` のサブクラスなので、素朴な
    ``isinstance(v, (int, float))`` だと True/False が 1.0/0.0 として
    すり抜けて mean に混入する。本関数では bool を明示除外する
    (PR #74 緊急 trio A2 の根本対応)。

    NaN は `statistics.mean` / `min` / `max` を破壊するため除外する。
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    # NaN は自身と等しくない。inf は許容 (情報を失わない)。
    return value == value


def merge_fields(record: Any) -> dict[str, Any]:
    """record の `conditions` と `results` を 1 つの dict にマージする。

    重複 key は results を優先 (元の MCP / CLI 実装に合わせる)。
    record は `get_conditions()` + `results.to_dict()` を実装する
    duck-typed なオブジェクトを想定。
    """
    cond = record.get_conditions()
    res = record.results.to_dict()
    return {**cond, **res}


# ---- 統計 --------------------------------------------------------------------


@dataclass
class StatsResult:
    """数値集合の要約統計。

    値が空のとき (`count == 0`) は他フィールドが 0.0 で埋まる
    (Optional にせず明示的に空集合を表すことで呼び出し側の None ガードを
    省略する; 既存 backend `StatsBlock` schema と整合)。
    """

    count: int = 0
    mean: float = 0.0
    std: float = 0.0
    min: float = 0.0
    max: float = 0.0
    median: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_stats(values: Iterable[float]) -> StatsResult:
    """数値リスト → StatsResult。空集合は count=0 で返す。

    std は標本標準偏差 (`statistics.stdev`)。要素 1 件のときは 0.0。
    値はすべて round 4 桁。`min`/`max` は丸めずに生の値を返す
    (整数キー `power=10` のような場合の表示を綺麗に保つため)。
    """
    vs = list(values)
    if not vs:
        return StatsResult()
    return StatsResult(
        count=len(vs),
        mean=round(statistics.mean(vs), 4),
        std=round(statistics.stdev(vs), 4) if len(vs) > 1 else 0.0,
        min=min(vs),
        max=max(vs),
        median=round(statistics.median(vs), 4),
    )


# ---- record 集合からの集計 ---------------------------------------------------


class _HasConditionsAndResults(Protocol):
    """compute_aggregate / iter_numeric が受け取れる record の最小契約。"""

    def get_conditions(self) -> Mapping[str, Any]: ...

    @property
    def results(self) -> Any: ...


@dataclass
class AggregateResult:
    """key に対する全体統計 + (任意で) グループ別統計。

    record_count: フィルタ後 records の総数 (key の有無に関わらず)。
    value_count: そのうち key が numeric として読めた件数 (== overall.count)。
    """

    key: str
    record_count: int
    value_count: int
    overall: StatsResult
    group_by: str | None = None
    groups: dict[str, StatsResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "record_count": self.record_count,
            "value_count": self.value_count,
            "overall": self.overall.to_dict(),
            "group_by": self.group_by,
            "groups": {k: v.to_dict() for k, v in self.groups.items()},
        }


def compute_aggregate(
    records: Iterable[_HasConditionsAndResults],
    key: str,
    *,
    group_by: str | None = None,
) -> AggregateResult:
    """records 集合の `key` 値を numeric として抽出して統計を取る。

    `group_by` が指定された場合、その key の値で label を作って
    label 別の stats も計算する (label は str 化、未存在は "unknown")。

    group_by 自身は numeric である必要はない (categorical でよい)。
    """
    records_list = list(records)
    values: list[float] = []
    groups: dict[str, list[float]] = {}

    for rec in records_list:
        merged = merge_fields(rec)
        if key not in merged:
            continue
        v = merged[key]
        if not is_numeric(v):
            continue
        values.append(float(v))
        if group_by:
            gv = merged.get(group_by)
            label = "unknown" if gv is None else str(gv)
            groups.setdefault(label, []).append(float(v))

    overall = compute_stats(values)
    group_stats = (
        {k: compute_stats(v) for k, v in sorted(groups.items())} if group_by else {}
    )
    return AggregateResult(
        key=key,
        record_count=len(records_list),
        value_count=overall.count,
        overall=overall,
        group_by=group_by,
        groups=group_stats,
    )


# ---- overview 用ヘルパ -------------------------------------------------------


def numeric_values_only(values: Iterable[Any]) -> list[float]:
    """`is_numeric` ガード付きで float リストに正規化する。

    MCP `get_overview` / CLI `overview` が「conditions の値が全部数値か」
    判定して numeric / categorical に分岐するときに使う。bool / NaN は
    `is_numeric` で除外される。
    """
    return [float(v) for v in values if is_numeric(v)]
