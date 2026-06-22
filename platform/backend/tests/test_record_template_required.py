"""``/api/records/{id}`` のレスポンスに ``template_required_conditions`` /
``template_required_results`` が含まれることを検証する。

Web UI の sticky summary chip 行で「結果 3/9 必須」のような充足率を出す
ための backend データソース。template 紐付き無しでは空 list を返す。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.main import app
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.types import ResultField, TemplateV10


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for key in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(key, "")
    lab = Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )

    lab.define_template(
        TemplateV10(
            name="xrd_strict",
            type="measurement",
            required_conditions=["wavelength_A", "angle_step_deg"],
            result_fields=[
                # required=True が 2 つ、False が 1 つ
                ResultField(name="lattice_a_A", type="float", required=True),
                ResultField(name="fit_chi2", type="float", required=True),
                ResultField(name="notes", type="str", required=False),
            ],
        )
    )

    # required を満たす record
    full = lab.new(
        "full",
        template="xrd_strict",
        wavelength_A=1.54,
        angle_step_deg=0.02,
        auto_log=False,
    )
    full.results["lattice_a_A"] = 2.873
    full.results["fit_chi2"] = 0.42

    # 部分的にしか埋まっていない record (chip で「⚠ 1/2 必須」と出るはず)
    partial = lab.new(
        "partial",
        template="xrd_strict",
        wavelength_A=1.54,
        auto_log=False,
    )
    partial.results["lattice_a_A"] = 2.873

    # template 無しの record
    bare = lab.new("bare", auto_log=False)
    bare.results["misc"] = 1.0

    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


def _get(lab: Lab, title: str) -> str:
    for r in lab.list(limit=10):
        if r.title == title:
            return r.id
    raise AssertionError(f"record not found: {title}")


def test_template_required_lists_returned(client: TestClient, seeded_lab: Lab) -> None:
    rid = _get(seeded_lab, "full")
    res = client.get(f"/api/records/{rid}")
    assert res.status_code == 200
    body = res.json()
    # required_conditions は template の宣言順を保つ
    assert body["template_required_conditions"] == ["wavelength_A", "angle_step_deg"]
    # required_results は result_fields のうち required=True のみ抽出 (順番保持)
    assert body["template_required_results"] == ["lattice_a_A", "fit_chi2"]


def test_partial_fill_still_returns_template_required(
    client: TestClient, seeded_lab: Lab
) -> None:
    """record の埋まり具合に関係なく、template 側の required は同じ list を返す
    (frontend が充足率 = 入っている / required total を計算するため)。"""
    rid = _get(seeded_lab, "partial")
    body = client.get(f"/api/records/{rid}").json()
    assert body["template_required_conditions"] == ["wavelength_A", "angle_step_deg"]
    assert body["template_required_results"] == ["lattice_a_A", "fit_chi2"]


def test_record_without_template_returns_empty_lists(
    client: TestClient, seeded_lab: Lab
) -> None:
    rid = _get(seeded_lab, "bare")
    body = client.get(f"/api/records/{rid}").json()
    assert body["template_required_conditions"] == []
    assert body["template_required_results"] == []


def test_field_always_present(client: TestClient, seeded_lab: Lab) -> None:
    """frontend が optional 扱いせずそのまま参照できるよう、必ず key が存在する。"""
    rid = _get(seeded_lab, "bare")
    body = client.get(f"/api/records/{rid}").json()
    assert "template_required_conditions" in body
    assert "template_required_results" in body
