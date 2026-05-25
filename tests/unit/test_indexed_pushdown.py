"""conditions の Firestore push down (`idx_<key>` 経由) のユニットテスト。

PR #14 で Lab.search / Lab.list が template.indexed_fields を見て、
scalar 等値の conditions を `idx_<key>` として backend に push down するように
なった。テスト方針:

- backend (InMemoryMetadataBackend / InMemorySearchBackend) を spy 化して
  filters / conditions が正しく `idx_<key>` で渡っていることを確認
- post-filter fallback が範囲指定 (dict 値) / indexed でない key を弾けること
- _get_indexed_keys() が define_template / get_template で invalidate される
"""

from __future__ import annotations

from typing import Any

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab
from labvault.core.types import ConditionField, TemplateV10


@pytest.fixture()
def lab() -> Lab:
    return Lab(
        "test-team",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


# ----------------------------------------------------------------------
# _get_indexed_keys
# ----------------------------------------------------------------------


def test_indexed_keys_empty_initially(lab: Lab) -> None:
    assert lab._get_indexed_keys() == set()


def test_indexed_keys_collects_from_define_template(lab: Lab) -> None:
    tpl = TemplateV10(
        name="Tmpl",
        condition_fields=[
            ConditionField(name="alpha"),
            ConditionField(name="beta"),
        ],
        indexed_fields=["alpha"],
    )
    lab.define_template(tpl)
    assert lab._get_indexed_keys() == {"alpha"}


def test_indexed_keys_collects_from_builtin_get(lab: Lab) -> None:
    # XRD ビルトインは indexed_fields=["target", "method", "sample_name"]
    lab.get_template("XRD")
    keys = lab._get_indexed_keys()
    assert {"target", "method", "sample_name"}.issubset(keys)


def test_indexed_keys_invalidated_on_define(lab: Lab) -> None:
    lab.get_template("XRD")  # cache を温める
    _ = lab._get_indexed_keys()  # 一度評価
    tpl = TemplateV10(name="ExtraTmpl", indexed_fields=["custom_key"])
    lab.define_template(tpl)
    assert "custom_key" in lab._get_indexed_keys()
    assert "target" in lab._get_indexed_keys()  # XRD 由来も残る


# ----------------------------------------------------------------------
# Lab.list の push down
# ----------------------------------------------------------------------


def test_list_pushes_down_indexed_scalar_conditions(lab: Lab) -> None:
    """conditions の scalar 値かつ indexed_fields に含まれる key は
    `idx_<key>` として backend.list_records の conditions 引数に渡る。"""
    lab.get_template("XRD")  # indexed_fields を引いておく

    received: dict[str, Any] = {}
    original = lab._metadata.list_records

    def spy(team: str, **kwargs: Any) -> list[dict[str, Any]]:
        received.update(kwargs)
        return original(team, **kwargs)

    lab._metadata.list_records = spy  # type: ignore[method-assign]

    lab.list(conditions={"target": "Cu"})

    assert received.get("conditions") == {"idx_target": "Cu"}


def test_list_does_not_push_down_non_indexed_conditions(lab: Lab) -> None:
    """indexed_fields に挙がっていない key は push down されない。"""
    lab.get_template("XRD")

    received: dict[str, Any] = {}
    original = lab._metadata.list_records

    def spy(team: str, **kwargs: Any) -> list[dict[str, Any]]:
        received.update(kwargs)
        return original(team, **kwargs)

    lab._metadata.list_records = spy  # type: ignore[method-assign]

    # power は XRD の indexed_fields ではない
    lab.list(conditions={"power": 50})

    assert received.get("conditions") is None


def test_list_does_not_push_down_dict_value(lab: Lab) -> None:
    """範囲指定 (dict 値) は push down されない (post-filter)。"""
    lab.get_template("XRD")

    received: dict[str, Any] = {}
    original = lab._metadata.list_records

    def spy(team: str, **kwargs: Any) -> list[dict[str, Any]]:
        received.update(kwargs)
        return original(team, **kwargs)

    lab._metadata.list_records = spy  # type: ignore[method-assign]

    lab.list(conditions={"target": {"eq": "Cu"}})
    # dict 値は indexed でも push down しない
    assert received.get("conditions") is None


def test_list_post_filter_excludes_non_matching(lab: Lab) -> None:
    """push down に乗らない条件 (範囲指定) でも post-filter が効く。"""
    exp1 = lab.new("a", template="XRD", target="Cu", two_theta_start_deg=10.0)
    exp2 = lab.new("b", template="XRD", target="Cu", two_theta_start_deg=30.0)

    rs = lab.list(conditions={"two_theta_start_deg": {"gte": 20.0}})
    ids = {r.id for r in rs}
    assert exp2.id in ids
    assert exp1.id not in ids


def test_list_pushdown_actually_filters(lab: Lab) -> None:
    """push down 経路でも end-to-end で結果が正しく絞り込まれる。"""
    cu_exp = lab.new("a", template="XRD", target="Cu")
    lab.new("b", template="XRD", target="Mo")

    rs = lab.list(conditions={"target": "Cu"})
    ids = {r.id for r in rs}
    assert cu_exp.id in ids
    assert len(ids) == 1


# ----------------------------------------------------------------------
# Lab.search の push down
# ----------------------------------------------------------------------


def test_search_pushes_down_indexed_conditions_to_search_filters(lab: Lab) -> None:
    """Lab.search も SearchBackend.search の filters に `idx_<key>` を載せる。"""
    lab.get_template("XRD")

    received: dict[str, Any] = {}
    original = lab._search.search

    def spy(team: str, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        received.update(kwargs)
        return original(team, query, **kwargs)

    lab._search.search = spy  # type: ignore[method-assign]

    lab.search("noise", conditions={"target": "Cu"})
    assert received.get("filters", {}).get("idx_target") == "Cu"


def test_search_post_filter_runs_even_with_pushdown(lab: Lab) -> None:
    """push down に乗せた key も post-filter で再チェックされる
    (Platform backend がサーバー未対応な場合の正確性保証)。"""
    cu_exp = lab.new("Cu sample", template="XRD", target="Cu")
    mo_exp = lab.new("Mo sample", template="XRD", target="Mo")

    # InMemorySearchBackend は filters を無視する (= push down が効かない
    # 環境のシミュレーション)。それでも post-filter で正しく絞れる。
    rs = lab.search("sample", conditions={"target": "Cu"})
    ids = {r.id for r in rs}
    assert cu_exp.id in ids
    assert mo_exp.id not in ids


# ----------------------------------------------------------------------
# InMemoryMetadataBackend.list_records の conditions サポート
# ----------------------------------------------------------------------


def test_inmemory_backend_filters_by_top_level_field(lab: Lab) -> None:
    """backend 単体テスト: conditions={"idx_target": "Cu"} を直接渡したら
    `idx_target == "Cu"` の record だけ返す。"""
    lab.new("a", template="XRD", target="Cu")
    lab.new("b", template="XRD", target="Mo")

    rows = lab._metadata.list_records("test-team", conditions={"idx_target": "Cu"})
    targets = [r.get("idx_target") for r in rows]
    assert all(t == "Cu" for t in targets)
    assert len(targets) == 1


def test_inmemory_backend_excludes_missing_field(lab: Lab) -> None:
    """`idx_<key>` フィールド自体が無い record は除外する
    (Firestore と振る舞いを揃える)。"""
    lab.new("no-template")  # idx_* 無し
    lab.new("with-tpl", template="XRD", target="Cu")

    rows = lab._metadata.list_records("test-team", conditions={"idx_target": "Cu"})
    assert len(rows) == 1
