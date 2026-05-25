"""M3 テンプレート機能のユニットテスト。

カバー範囲:
- ビルトイン (XRD) の lookup と backend への lazy save
- alias 正規化 (conditions の旧名 / 表記揺れを name に変換)
- template の unit 自動補完
- status=success 時の required_conditions 不足警告
- define_template / templates / get_template の round trip
- 未定義 template を new(...) に渡したら ValueError
- template 紐付け時の default_tags マージと type 上書き
"""

from __future__ import annotations

import warnings

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.builtin_templates import BUILTIN_TEMPLATES, TEMPLATE_XRD
from labvault.core.lab import Lab
from labvault.core.types import (
    ConditionField,
    TemplateV10,
    template_from_dict,
    template_to_dict,
)


@pytest.fixture()
def lab() -> Lab:
    return Lab(
        "test-team",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


def test_get_template_returns_builtin_and_lazy_saves(lab: Lab) -> None:
    # initial state: backend に何も無い
    assert lab.templates() == []

    tpl = lab.get_template("XRD")
    assert tpl is not None
    assert tpl.name == "XRD"
    # ビルトインを参照したら backend に save される (次回以降は backend ヒット)
    names = [t.name for t in lab.templates()]
    assert "XRD" in names


def test_get_unknown_template_returns_none(lab: Lab) -> None:
    assert lab.get_template("UnknownTemplate") is None


def test_new_with_template_applies_default_tags_and_type(lab: Lab) -> None:
    exp = lab.new(
        "Fe-Cr",
        template="XRD",
        target="Cu",
        two_theta_start_deg=10.0,
        two_theta_end_deg=80.0,
        sample_name="FeCr-001",
    )
    assert exp.template_name == "XRD"
    # XRD は type=measurement, default_tags=["XRD"]
    assert exp.type == "measurement"
    assert "XRD" in exp.tags


def test_new_with_unknown_template_raises(lab: Lab) -> None:
    with pytest.raises(ValueError, match="template 'NoSuch' not found"):
        lab.new("x", template="NoSuch")


def test_alias_normalization_on_new(lab: Lab) -> None:
    # 旧名や別名で渡しても、template が紐付いていれば正規化された name に変換される。
    # 注: lab.new(sample=...) は親レコード ID リンク用の専用 kwarg なので
    # conditions には渡らない。sample_name の alias は "specimen" を使う。
    exp = lab.new(
        "Fe-Cr",
        template="XRD",
        x_ray_target="Cu",  # → target
        specimen="FeCr-001",  # → sample_name
        wavelength=1.5418,  # → wavelength_A
    )
    cond = exp.get_conditions()
    assert cond["target"] == "Cu"
    assert cond["sample_name"] == "FeCr-001"
    assert cond["wavelength_A"] == 1.5418


def test_alias_normalization_via_conditions(lab: Lab) -> None:
    exp = lab.new("x", template="XRD")
    exp.conditions(
        anode="Cu",  # → target
        wavelength=1.5418,  # → wavelength_A
        scan_speed=2.0,  # → scan_speed_deg_per_min
    )
    cond = exp.get_conditions()
    assert cond["target"] == "Cu"
    assert cond["wavelength_A"] == 1.5418
    assert cond["scan_speed_deg_per_min"] == 2.0


def test_unit_auto_fill_from_template(lab: Lab) -> None:
    exp = lab.new("x", template="XRD")
    exp.conditions(two_theta_start_deg=10.0)
    # template 側で unit="deg" が定義されているので自動補完される
    assert exp.get_condition_units().get("two_theta_start_deg") == "deg"


def test_unit_explicit_overrides_template(lab: Lab) -> None:
    exp = lab.new("x", template="XRD")
    # tuple で明示指定したら template の unit に上書きされない
    exp.conditions(two_theta_start_deg=(10.0, "rad"))
    assert exp.get_condition_units().get("two_theta_start_deg") == "rad"


def test_required_conditions_warning_on_status_success(lab: Lab) -> None:
    exp = lab.new("x", template="XRD")  # 必須未入力のまま
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        exp.status = "success"
    msgs = [str(x.message) for x in w]
    assert len(msgs) == 1
    # required 4 個 (target, two_theta_start_deg, two_theta_end_deg, sample_name) が出る
    assert "target" in msgs[0]
    assert "two_theta_start_deg" in msgs[0]
    assert "two_theta_end_deg" in msgs[0]
    assert "sample_name" in msgs[0]


def test_required_conditions_no_warning_when_complete(lab: Lab) -> None:
    exp = lab.new(
        "x",
        template="XRD",
        target="Cu",
        two_theta_start_deg=10.0,
        two_theta_end_deg=80.0,
        sample_name="FeCr-001",
    )
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        exp.status = "success"
    assert [str(x.message) for x in w if issubclass(x.category, UserWarning)] == []


def test_required_warning_only_on_terminal_status(lab: Lab) -> None:
    exp = lab.new("x", template="XRD")  # required 不足
    # running のままなら警告は出ない
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        exp.status = "running"
    assert [
        x
        for x in w
        if issubclass(x.category, UserWarning) and "必須条件" in str(x.message)
    ] == []


def test_no_warning_when_no_template(lab: Lab) -> None:
    # template 未指定 record では warning が出ない
    exp = lab.new("x")  # template なし
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        exp.status = "success"
    assert [
        x
        for x in w
        if issubclass(x.category, UserWarning) and "必須条件" in str(x.message)
    ] == []


def test_define_and_list_round_trip(lab: Lab) -> None:
    tpl = TemplateV10(
        name="Custom",
        display_name="自作",
        type="experiment",
        default_tags=["custom"],
        condition_fields=[
            ConditionField(
                name="foo",
                type="float",
                unit="m",
                required=True,
                aliases=["f"],
            ),
        ],
        required_conditions=["foo"],
    )
    lab.define_template(tpl)

    listed = {t.name: t for t in lab.templates()}
    assert "Custom" in listed
    got = listed["Custom"]
    assert got.display_name == "自作"
    assert got.required_conditions == ["foo"]
    assert got.condition_fields[0].aliases == ["f"]

    # get_template でも引ける
    same = lab.get_template("Custom")
    assert same is not None
    assert same.name == "Custom"


def test_template_persists_to_record_dict(lab: Lab) -> None:
    exp = lab.new("x", template="XRD")
    d = exp._to_dict()
    assert d["template"] == "XRD"


def test_template_restored_from_dict(lab: Lab) -> None:
    # 再 fetch して template が引き継がれているか
    exp = lab.new(
        "x",
        template="XRD",
        target="Cu",
        two_theta_start_deg=10.0,
        two_theta_end_deg=80.0,
        sample_name="s",
    )
    fetched = lab.get(exp.id)
    assert fetched.template_name == "XRD"


def test_template_to_from_dict_round_trip() -> None:
    d = template_to_dict(TEMPLATE_XRD)
    restored = template_from_dict(d)
    assert restored.name == "XRD"
    assert restored.required_conditions == TEMPLATE_XRD.required_conditions
    assert len(restored.condition_fields) == len(TEMPLATE_XRD.condition_fields)


def test_all_builtins_are_loadable() -> None:
    for name, tpl in BUILTIN_TEMPLATES.items():
        # 各ビルトインは round trip 可能
        restored = template_from_dict(template_to_dict(tpl))
        assert restored.name == name
        # required はすべて condition_fields の name に存在
        field_names = {f.name for f in restored.condition_fields}
        for req in restored.required_conditions:
            assert req in field_names, (
                f"{name}: required {req!r} が condition_fields に無い"
            )


def test_alias_map_helper() -> None:
    m = TEMPLATE_XRD.alias_map()
    assert m["x_ray_target"] == "target"
    assert m["wavelength"] == "wavelength_A"
    assert m["sample"] == "sample_name"


# --- indexed_fields の top-level 昇格 ---


def test_indexed_fields_promoted_to_idx_top_level(lab: Lab) -> None:
    # XRD の indexed_fields = ["target", "method", "sample_name"]
    exp = lab.new(
        "x",
        template="XRD",
        target="Cu",
        method="thin_film",
        sample_name="FeCr-001",
        two_theta_start_deg=10.0,
        two_theta_end_deg=80.0,
    )
    d = exp._to_dict()
    assert d["idx_target"] == "Cu"
    assert d["idx_method"] == "thin_film"
    assert d["idx_sample_name"] == "FeCr-001"
    # indexed_fields に含まれない key は昇格しない
    assert "idx_two_theta_start_deg" not in d
    assert "idx_wavelength_A" not in d


def test_indexed_fields_skips_unset_keys(lab: Lab) -> None:
    # indexed_fields の一部しか conditions に入っていない場合
    exp = lab.new("partial", template="XRD", target="Mo")
    d = exp._to_dict()
    assert d["idx_target"] == "Mo"
    # 未入力なら top-level に出さない (Firestore で null を index しないため)
    assert "idx_method" not in d
    assert "idx_sample_name" not in d


def test_indexed_fields_empty_when_no_template(lab: Lab) -> None:
    exp = lab.new("no-template")  # template 未指定
    d = exp._to_dict()
    assert not any(k.startswith("idx_") for k in d)


def test_indexed_fields_follow_condition_updates(lab: Lab) -> None:
    exp = lab.new("x", template="XRD", target="Cu")
    assert exp._to_dict().get("idx_target") == "Cu"
    exp.conditions(target="Mo")
    assert exp._to_dict().get("idx_target") == "Mo"
    # 後から追加した indexed_fields も追従
    assert "idx_method" not in exp._to_dict()
    exp.conditions(method="powder")
    assert exp._to_dict().get("idx_method") == "powder"


def test_template_cache_avoids_repeated_backend_lookups(lab: Lab) -> None:
    # _to_dict は何度呼んでも backend.get_template が増えないこと
    # (template_cache が効いている指標)
    exp = lab.new("x", template="XRD", target="Cu")
    backend = lab._metadata  # InMemoryMetadataBackend
    # _to_dict を 1 回呼んで cache を温める (もし無ければ最初の呼出しで温まる)
    exp._to_dict()
    # Backend を spy 化: get_template の呼出し回数をカウント
    original = backend.get_template
    calls = []

    def spy(team: str, name: str):
        calls.append((team, name))
        return original(team, name)

    backend.get_template = spy  # type: ignore[method-assign]
    for _ in range(5):
        exp._to_dict()
    assert calls == [], "template_cache が効いていれば backend を再度引かない"
