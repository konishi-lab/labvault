"""Record.sub(template=) のテスト (#12b minimal)。

#12a で template の result_fields による auto-fill が `lab.new()` 経由で動く
ようになったが、`parent.sub(...)` には template kwarg が無く、子レコードで
auto-fill が効かなかった。本テストは:

- `parent.sub(template=)` で子に template が紐付くこと
- 子の results 代入で auto-fill が効くこと (#12a と連携)
- 親と子で異なる template を独立に使えること
- 孫世代 (3 階層) でも各世代の template が独立に効くこと
- backward compat: template 省略時は従来どおり

を検証する。
"""

from __future__ import annotations

import pytest

from labvault.core.lab import Lab
from labvault.core.types import (
    ConditionField,
    ResultField,
    TemplateV10,
)


@pytest.fixture()
def parent_template() -> TemplateV10:
    """実験全体 (親) 用 — operator / batch_no などのメタ schema。"""
    return TemplateV10(
        name="thin_film_experiment",
        type="experiment",
        condition_fields=[
            ConditionField(name="operator", type="str"),
            ConditionField(name="batch_no", type="str"),
        ],
    )


@pytest.fixture()
def child_template() -> TemplateV10:
    """子 (測定) 用 — XRD ライク。result_fields に unit/description あり。"""
    return TemplateV10(
        name="xrd_measurement",
        type="measurement",
        condition_fields=[
            ConditionField(name="rf_power_W", type="float", unit="W"),
        ],
        result_fields=[
            ResultField(
                name="peak_2theta_deg",
                type="float",
                unit="deg",
                description="代表ピーク 2θ",
            ),
            ResultField(
                name="lattice_a_A",
                type="float",
                unit="Å",
                description="格子定数 a",
            ),
        ],
    )


@pytest.fixture()
def grandchild_template() -> TemplateV10:
    """孫 (詳細測定) 用 — 別 schema。"""
    return TemplateV10(
        name="rietveld_refinement",
        type="measurement",
        result_fields=[
            ResultField(
                name="fit_chi2",
                type="float",
                description="正規化残差二乗",
            ),
        ],
    )


@pytest.fixture()
def lab_with_templates(
    lab: Lab,
    parent_template: TemplateV10,
    child_template: TemplateV10,
    grandchild_template: TemplateV10,
) -> Lab:
    lab.define_template(parent_template)
    lab.define_template(child_template)
    lab.define_template(grandchild_template)
    return lab


class TestSubTemplateBasic:
    def test_child_has_template_attached(self, lab_with_templates: Lab) -> None:
        parent = lab_with_templates.new("実験全体", template="thin_film_experiment")
        child = parent.sub("XRD 測定", template="xrd_measurement", rf_power_W=30)
        assert child.template_name == "xrd_measurement"

    def test_child_auto_fill_from_template(self, lab_with_templates: Lab) -> None:
        """子で bare scalar 代入したら template の result_fields から unit/desc が
        auto-fill される (#12a と連携、これが本 PR の最大の利得)。"""
        parent = lab_with_templates.new("実験全体", template="thin_film_experiment")
        child = parent.sub("XRD 測定", template="xrd_measurement", rf_power_W=30)
        child.results["peak_2theta_deg"] = 32.1
        assert child.get_result_units()["peak_2theta_deg"] == "deg"
        assert child.get_result_descriptions()["peak_2theta_deg"] == "代表ピーク 2θ"

    def test_parent_and_child_templates_are_independent(
        self, lab_with_templates: Lab
    ) -> None:
        """親と子で異なる template が独立に紐付く。"""
        parent = lab_with_templates.new("実験全体", template="thin_film_experiment")
        child = parent.sub("XRD 測定", template="xrd_measurement", rf_power_W=30)
        assert parent.template_name == "thin_film_experiment"
        assert child.template_name == "xrd_measurement"

    def test_child_parent_id_is_set(self, lab_with_templates: Lab) -> None:
        parent = lab_with_templates.new("実験全体")
        child = parent.sub("子", template="xrd_measurement")
        assert child.parent_id == parent.id


class TestSubWithoutTemplate:
    """既存挙動の保護 — template 省略時は従来どおり template_name=None。"""

    def test_no_template_kwarg(self, lab_with_templates: Lab) -> None:
        parent = lab_with_templates.new("実験全体")
        child = parent.sub("子なし template", rf_power_W=30)
        assert child.template_name is None

    def test_no_auto_fill_without_template(self, lab_with_templates: Lab) -> None:
        """template が無ければ #12a auto-fill は走らない。"""
        parent = lab_with_templates.new("実験全体")
        child = parent.sub("子", rf_power_W=30)
        child.results["peak_2theta_deg"] = 32.1
        # unit / description は付かない
        assert "peak_2theta_deg" not in child.get_result_units()
        assert "peak_2theta_deg" not in child.get_result_descriptions()


class TestGrandchild:
    """孫世代 (3 階層) でも template が独立に効く。"""

    def test_grandchild_template_independent(self, lab_with_templates: Lab) -> None:
        series = lab_with_templates.new("実験全体", template="thin_film_experiment")
        batch = series.sub("batch A", template="xrd_measurement", rf_power_W=30)
        sample = batch.sub("詳細解析", template="rietveld_refinement")

        assert series.template_name == "thin_film_experiment"
        assert batch.template_name == "xrd_measurement"
        assert sample.template_name == "rietveld_refinement"
        assert batch.parent_id == series.id
        assert sample.parent_id == batch.id

    def test_grandchild_auto_fill(self, lab_with_templates: Lab) -> None:
        """孫世代でも #12a auto-fill が効くこと (template が独立に効く証明)。"""
        series = lab_with_templates.new("実験全体", template="thin_film_experiment")
        batch = series.sub("batch A", template="xrd_measurement", rf_power_W=30)
        sample = batch.sub("詳細解析", template="rietveld_refinement")

        sample.results["fit_chi2"] = 0.42
        assert sample.get_result_descriptions()["fit_chi2"] == "正規化残差二乗"


class TestScanPattern:
    """典型的な scan 実験パターン (親 1 + 子 N) が綺麗に書けることの検証。"""

    def test_scan_with_common_conditions(self, lab_with_templates: Lab) -> None:
        """**common dict で親子間の共通条件を渡せる (推奨イディオム)。"""
        common = dict(operator="hiro", batch_no="2026-06")

        series = lab_with_templates.new(
            "Fe-Cr power scan", template="thin_film_experiment", **common
        )

        children = []
        for power in [20, 30, 40, 50, 60]:
            child = series.sub(
                f"power={power}W",
                template="xrd_measurement",
                rf_power_W=power,
                **common,
            )
            children.append(child)

        assert len(children) == 5
        for child in children:
            assert child.template_name == "xrd_measurement"
            assert child.get_conditions()["operator"] == "hiro"
            assert child.get_conditions()["batch_no"] == "2026-06"
        # 各 child の rf_power_W は scan 値
        assert {c.get_conditions()["rf_power_W"] for c in children} == {
            20,
            30,
            40,
            50,
            60,
        }
