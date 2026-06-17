"""``/api/records/{id}`` のレスポンスに ``template_result_units`` /
``template_result_descriptions`` が含まれることを検証する。

Web UI が「この value の unit は template 由来か手動入力か」を判別する
基盤になる。
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
    """template 紐付き record と紐付き無し record を 1 つずつ持つ Lab。"""
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
            name="xrd_test",
            type="measurement",
            result_fields=[
                ResultField(
                    name="lattice_a_A",
                    type="float",
                    unit="Å",
                    description="格子定数 a",
                ),
                ResultField(
                    name="fit_chi2",
                    type="float",
                    description="正規化残差二乗",
                ),
            ],
        )
    )

    # record A: template 紐付き、bare scalar (auto-fill)
    a = lab.new("with-template", template="xrd_test", auto_log=False)
    a.results["lattice_a_A"] = 2.873         # auto-fill: unit "Å", desc "格子定数 a"
    a.results["fit_chi2"] = 0.42             # auto-fill: desc "正規化残差二乗"

    # record B: template 紐付きだが手動で override
    b = lab.new("with-template-override", template="xrd_test", auto_log=False)
    b.results["lattice_a_A"] = (2.873, "nm", "別単位で")

    # record C: template 無し
    c = lab.new("no-template", auto_log=False)
    c.results["misc"] = (1.0, "V", "手動入力")

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


def test_template_result_units_returned(client: TestClient, seeded_lab: Lab) -> None:
    rid = _get(seeded_lab, "with-template")
    res = client.get(f"/api/records/{rid}")
    assert res.status_code == 200
    body = res.json()
    assert body["template_result_units"] == {"lattice_a_A": "Å"}
    assert body["template_result_descriptions"] == {
        "lattice_a_A": "格子定数 a",
        "fit_chi2": "正規化残差二乗",
    }


def test_user_override_still_shows_template_values(
    client: TestClient, seeded_lab: Lab
) -> None:
    """ユーザーが手動で override した record でも、template 側の値は
    引き続き返却される (frontend が比較で provenance を判定するため)。"""
    rid = _get(seeded_lab, "with-template-override")
    res = client.get(f"/api/records/{rid}")
    body = res.json()
    # 実値は手動入力
    assert body["result_units"]["lattice_a_A"] == "nm"
    assert body["result_descriptions"]["lattice_a_A"] == "別単位で"
    # template 側の値は template 由来として変わらず返る
    assert body["template_result_units"]["lattice_a_A"] == "Å"
    assert body["template_result_descriptions"]["lattice_a_A"] == "格子定数 a"


def test_record_without_template_returns_empty_dict(
    client: TestClient, seeded_lab: Lab
) -> None:
    """template 紐付き無しの record では template_* は空 dict。"""
    rid = _get(seeded_lab, "no-template")
    res = client.get(f"/api/records/{rid}")
    body = res.json()
    assert body["template_result_units"] == {}
    assert body["template_result_descriptions"] == {}


def test_field_always_present(client: TestClient, seeded_lab: Lab) -> None:
    """API レスポンスに必ず両 key が含まれる (frontend が optional 扱いせず
    そのまま参照できる)。"""
    rid = _get(seeded_lab, "no-template")
    body = client.get(f"/api/records/{rid}").json()
    assert "template_result_units" in body
    assert "template_result_descriptions" in body
