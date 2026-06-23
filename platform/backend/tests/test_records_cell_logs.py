"""`GET /api/records/{id}/cell_logs` の挙動を検証する。

戦略 B1: Notebook セルログ (R13) の Web/MCP 露出。これまで実装が
あっても消費経路が無く実質死蔵状態だった差別化資産の最終ピース。
backend endpoint としては Pydantic schema 経由で安全に正規化された
形を返すこと、cell_number 昇順、limit と has_more の整合を担保。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from app.main import app
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


def _make_cell(
    *,
    cell_id: str,
    cell_number: int,
    source: str,
    error: dict | None = None,
    new_vars: dict | None = None,
) -> dict:
    return {
        "cell_id": cell_id,
        "record_id": "",  # backend が seed 時に上書きする
        "cell_number": cell_number,
        "execution_count": cell_number,
        "source": source,
        "source_hash": "deadbeef",
        "new_vars": new_vars or {},
        "changed_vars": {},
        "deleted_vars": [],
        "duration_sec": 0.01,
        "executed_at": datetime.now(UTC).isoformat(),
        "error": error,
        "session_id": "test-session",
    }


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> tuple[Lab, str]:
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
    rec = lab.new("with-cells", auto_log=False)
    rid = rec.id

    # セルを意図的に逆順 (3 → 1 → 2) で投入。`get_cell_logs` が
    # cell_number 昇順に並べることを担保する。
    lab._metadata.save_cell_log(
        lab._team,
        rid,
        _make_cell(
            cell_id="c3",
            cell_number=3,
            source="exp.results['max_x'] = float(x.max())",
            new_vars={"_": {"type": "float"}},
        ),
    )
    lab._metadata.save_cell_log(
        lab._team,
        rid,
        _make_cell(
            cell_id="c1",
            cell_number=1,
            source="import numpy as np\nx = np.linspace(0, 1, 100)",
            new_vars={"np": {"type": "module"}, "x": {"type": "ndarray", "shape": [100]}},
        ),
    )
    lab._metadata.save_cell_log(
        lab._team,
        rid,
        _make_cell(
            cell_id="c2",
            cell_number=2,
            source="y = 1/0  # raises",
            error={"type": "ZeroDivisionError", "message": "division by zero"},
        ),
    )

    # CellLog ゼロ件の record (装置 PC スクリプト由来等)
    bare = lab.new("no-cells", auto_log=False)
    return lab, rid, bare.id  # type: ignore[return-value]


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch, seeded_lab: tuple[Lab, str, str]
) -> Iterator[TestClient]:
    lab, _, _ = seeded_lab
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: lab,
    )
    with TestClient(app) as c:
        yield c


def test_cell_logs_sorted_by_number(
    client: TestClient, seeded_lab: tuple[Lab, str, str]
) -> None:
    """挿入順に関わらず cell_number 昇順で返ること。"""
    _, rid, _ = seeded_lab
    res = client.get(f"/api/records/{rid}/cell_logs")
    assert res.status_code == 200
    body = res.json()
    nums = [it["cell_number"] for it in body["items"]]
    assert nums == [1, 2, 3]
    # 各 cell の source / new_vars / error が pass-through で残る
    assert "numpy" in body["items"][0]["source"]
    assert body["items"][1]["error"] == {
        "type": "ZeroDivisionError",
        "message": "division by zero",
    }
    assert body["items"][2]["execution_count"] == 3


def test_cell_logs_empty_record_returns_empty_list(
    client: TestClient, seeded_lab: tuple[Lab, str, str]
) -> None:
    """CellLog が紐付いていない record では空 list を返す (404 ではない)。"""
    _, _, bare_rid = seeded_lab
    res = client.get(f"/api/records/{bare_rid}/cell_logs")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_more"] is False


def test_cell_logs_404_for_unknown_record(client: TestClient) -> None:
    res = client.get("/api/records/NONEXISTENT/cell_logs")
    assert res.status_code == 404
    # PR #74 で入れた no-store guard が効いている
    assert res.headers.get("cache-control") == "no-store"


def test_cell_logs_has_more_when_limit_hit(
    client: TestClient, seeded_lab: tuple[Lab, str, str]
) -> None:
    """limit=2 を渡すと 2 件 + has_more=True で返る。"""
    _, rid, _ = seeded_lab
    res = client.get(f"/api/records/{rid}/cell_logs?limit=2")
    body = res.json()
    assert body["total"] == 2
    assert body["has_more"] is True
    # 順序は維持
    assert [it["cell_number"] for it in body["items"]] == [1, 2]


def test_cell_logs_limit_out_of_range(
    client: TestClient, seeded_lab: tuple[Lab, str, str]
) -> None:
    _, rid, _ = seeded_lab
    res = client.get(f"/api/records/{rid}/cell_logs?limit=0")
    assert res.status_code == 400
    res = client.get(f"/api/records/{rid}/cell_logs?limit=10000")
    assert res.status_code == 400


def test_cell_logs_pydantic_normalizes_missing_fields(
    client: TestClient, seeded_lab: tuple[Lab, str, str]
) -> None:
    """backend の Pydantic schema (`CellLogEntry`) が optional fields
    に default を埋めることで、frontend が undefined 判定なしで使える。"""
    _, rid, _ = seeded_lab
    body = client.get(f"/api/records/{rid}/cell_logs").json()
    for it in body["items"]:
        # 必須キーは常に存在
        assert "cell_id" in it
        assert "cell_number" in it
        assert "source" in it
        assert "new_vars" in it
        assert "changed_vars" in it
        assert "deleted_vars" in it
        # error は None or dict のいずれかであっても schema 通過
        assert it["error"] is None or isinstance(it["error"], dict)
