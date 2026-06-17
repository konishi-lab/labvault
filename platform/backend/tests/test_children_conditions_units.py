"""`/api/records/{id}/children/conditions` のレスポンスに condition_units /
result_units が含まれることを検証する。

scatter 軸ラベルで `[unit]` を出すための前提 (UX #16 quick win)。
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
    parent = lab.new("parent", auto_log=False)
    # 子に unit 付きの conditions と results を投入
    for power in [20, 30, 40]:
        child = parent.sub(
            f"power={power}W",
            rf_power_W=(power, "W"),  # conditions tuple notation
        )
        child.results["peak_2theta_deg"] = (32.1, "deg", "main peak")
    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


def test_children_conditions_includes_units(
    client: TestClient, seeded_lab: Lab
) -> None:
    parent_id = next(r for r in seeded_lab.list(limit=10) if r.title == "parent").id
    res = client.get(f"/api/records/{parent_id}/children/conditions")
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 3
    # 全子が同じ条件 schema を持つ
    for item in items:
        assert item["condition_units"]["rf_power_W"] == "W"
        assert item["result_units"]["peak_2theta_deg"] == "deg"


def test_field_always_present(client: TestClient, seeded_lab: Lab) -> None:
    """unit が空でも condition_units / result_units field 自体は present。"""
    parent_id = next(r for r in seeded_lab.list(limit=10) if r.title == "parent").id
    items = client.get(
        f"/api/records/{parent_id}/children/conditions"
    ).json()
    for item in items:
        assert "condition_units" in item
        assert "result_units" in item
