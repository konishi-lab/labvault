"""template.result_fields からの unit / description auto-fill のテスト。

#12a 設計:
- bare scalar 代入時、template.result_fields に key が登録されていれば
  unit / description を自動補完
- tuple 記法 ((値, "unit", "desc")) はユーザー明示として尊重 (空文字も OK)
- 既に値が入っている場合は保護 (上書きしない)
- template が無い / key が result_fields に無ければ no-op
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
def sputter_template() -> TemplateV10:
    """script 実験で使う想定の measurement template (conditions + results)。"""
    return TemplateV10(
        name="sputter_deposition",
        type="measurement",
        condition_fields=[
            ConditionField(name="rf_power_W", type="float", unit="W"),
            ConditionField(name="pressure_Pa", type="float", unit="Pa"),
        ],
        result_fields=[
            ResultField(
                name="film_thickness_nm",
                type="float",
                unit="nm",
                description="膜厚",
            ),
            ResultField(
                name="sheet_resistance",
                type="float",
                unit="ohm/sq",
                description="シート抵抗",
            ),
            ResultField(
                name="uniformity",
                type="float",
                unit="%",
                description="面内一様性",
            ),
            ResultField(
                name="phase",
                type="str",
                description="結晶相",
            ),
        ],
    )


@pytest.fixture()
def lab_with_template(lab: Lab, sputter_template: TemplateV10) -> Lab:
    lab.define_template(sputter_template)
    return lab


class TestAutoFillFromTemplate:
    def test_bare_scalar_picks_unit_and_description(
        self, lab_with_template: Lab
    ) -> None:
        rec = lab_with_template.new("test", template="sputter_deposition")
        rec.results["film_thickness_nm"] = 62.5
        assert rec.results["film_thickness_nm"] == 62.5
        assert rec.get_result_units()["film_thickness_nm"] == "nm"
        assert rec.get_result_descriptions()["film_thickness_nm"] == "膜厚"

    def test_bare_scalar_with_only_unit_field(self, lab_with_template: Lab) -> None:
        """description が空でも unit は補完される (逆も同様)。"""
        rec = lab_with_template.new("test", template="sputter_deposition")
        # ResultField(name="phase", type="str", description="結晶相") は unit=""
        rec.results["phase"] = "BCC"
        # unit は空のまま (template から "" を強制セットしない)
        assert "phase" not in rec.get_result_units() or (
            rec.get_result_units().get("phase", "") == ""
        )
        assert rec.get_result_descriptions()["phase"] == "結晶相"

    def test_tuple_notation_overrides_template(self, lab_with_template: Lab) -> None:
        """tuple で明示した unit / description は template より優先。"""
        rec = lab_with_template.new("test", template="sputter_deposition")
        rec.results["film_thickness_nm"] = (62.5, "μm", "別単位で")
        assert rec.get_result_units()["film_thickness_nm"] == "μm"
        assert rec.get_result_descriptions()["film_thickness_nm"] == "別単位で"

    def test_tuple_empty_unit_respected(self, lab_with_template: Lab) -> None:
        """ユーザーが tuple で意図的に空 unit を渡したら template で
        上書きしない (= 明示の空)。"""
        rec = lab_with_template.new("test", template="sputter_deposition")
        rec.results["film_thickness_nm"] = (62.5, "")  # 空 unit を明示
        # tuple 経路では _result_units[key] = "" がセットされ、auto-fill は
        # bare scalar のみで動くので上書きしない
        assert rec.get_result_units()["film_thickness_nm"] == ""

    def test_existing_unit_not_overwritten(self, lab_with_template: Lab) -> None:
        """先に tuple で unit を入れてから bare scalar で更新しても、
        unit は前回のものを保護する。"""
        rec = lab_with_template.new("test", template="sputter_deposition")
        rec.results["film_thickness_nm"] = (62.5, "μm")
        # bare scalar で値だけ更新
        rec.results["film_thickness_nm"] = 70.0
        assert rec.results["film_thickness_nm"] == 70.0
        # 既存 unit "μm" を保護
        assert rec.get_result_units()["film_thickness_nm"] == "μm"

    def test_unknown_key_no_autofill(self, lab_with_template: Lab) -> None:
        """template.result_fields に登録されていない key は補完しない。"""
        rec = lab_with_template.new("test", template="sputter_deposition")
        rec.results["unrelated_key"] = 1.0
        # 何も入らない
        assert "unrelated_key" not in rec.get_result_units()
        assert "unrelated_key" not in rec.get_result_descriptions()

    def test_no_template_no_autofill(self, lab: Lab) -> None:
        """template 紐付き無しの record では auto-fill は走らない。"""
        rec = lab.new("test")  # template 指定なし
        rec.results["film_thickness_nm"] = 62.5
        assert "film_thickness_nm" not in rec.get_result_units()
        assert "film_thickness_nm" not in rec.get_result_descriptions()


class TestResultFieldRoundTrip:
    """ResultField の永続化 (template_to_dict / from_dict)。"""

    def test_round_trip(self, sputter_template: TemplateV10) -> None:
        from labvault.core.types import template_from_dict, template_to_dict

        d = template_to_dict(sputter_template)
        restored = template_from_dict(d)
        assert len(restored.result_fields) == 4
        names = {f.name for f in restored.result_fields}
        assert names == {
            "film_thickness_nm",
            "sheet_resistance",
            "uniformity",
            "phase",
        }
        # unit / description が永続化される
        rf = restored.result_field_map()["film_thickness_nm"]
        assert rf.unit == "nm"
        assert rf.description == "膜厚"

    def test_legacy_template_without_result_fields(self) -> None:
        """旧 template (result_fields 無し、recommended_results: list[str] のみ)
        も読める。"""
        from labvault.core.types import template_from_dict

        d = {
            "name": "legacy",
            "type": "measurement",
            "recommended_results": ["peak_x", "peak_y"],
        }
        tpl = template_from_dict(d)
        assert tpl.result_fields == []
        assert tpl.recommended_results == ["peak_x", "peak_y"]


class TestBuiltinTemplatesHaveResultFields:
    """XRD/SEM/SQUID/TEM/Raman builtin に result_fields が定義されていること。"""

    @pytest.mark.parametrize(
        "name",
        ["XRD", "SEM", "SQUID", "TEM", "Raman"],
    )
    def test_has_result_fields(self, name: str) -> None:
        from labvault.core.builtin_templates import BUILTIN_TEMPLATES

        tpl = BUILTIN_TEMPLATES[name]
        assert len(tpl.result_fields) >= 2
        # 全 field に最低限 name は付いている
        for rf in tpl.result_fields:
            assert rf.name
            # type は scalar 型のいずれか
            assert rf.type in ("float", "int", "str", "bool")
