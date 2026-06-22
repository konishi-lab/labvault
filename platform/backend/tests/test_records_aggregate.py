"""`GET /api/records/aggregate` の挙動を検証する。

戦略案 #6 Phase A: `/records` の StatsPanel が叩く endpoint。
「表示中の N 件でなく、フィルタにマッチする全集合の統計」を返すのが
存在意義なので、numeric 抽出 / 非 numeric 除外 / parent_id フィルタ /
truncated フラグ / group_by を中心にカバーする。
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
    """root 5 件 + parent 配下に 3 件、numeric 値あり/なし混在。"""
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

    # root 5 件: power = 10, 20, 30, 40, 50
    for i, p in enumerate([10, 20, 30, 40, 50], start=1):
        lab.new(f"root-{i}", power=p, auto_log=False)

    # 1 件だけ power に文字列を入れる (numeric として除外されるべき)
    lab.new("root-bad", power="not-a-number", auto_log=False)

    # parent + 3 件の子。条件は同じ power でも parent_id でだけ拾える。
    parent = lab.new("parent", auto_log=False)
    for i, p in enumerate([100, 200, 300], start=1):
        parent.sub(f"child-{i}", power=p, auto_log=False)

    # group_by 用: angle を 2 グループに分けた root を追加
    lab.new("g1-a", power=11, angle=0, auto_log=False)
    lab.new("g1-b", power=13, angle=0, auto_log=False)
    lab.new("g2-a", power=21, angle=45, auto_log=False)
    lab.new("g2-b", power=23, angle=45, auto_log=False)

    # results-key 検証用: conditions に無く、results にだけ存在する record。
    # backend は merged = {**conditions, **results} で両方拾える設計なので
    # results-key も問題なく集計対象になることを担保する。
    r1 = lab.new("with-result-a", auto_log=False)
    r1.results["lattice_a_A"] = 2.873
    r2 = lab.new("with-result-b", auto_log=False)
    r2.results["lattice_a_A"] = 2.875

    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


def test_root_aggregate_returns_stats(client: TestClient) -> None:
    """親なし record 集合の power 統計が返る。文字列値の record は除外。"""
    res = client.get("/api/records/aggregate?key=power")
    assert res.status_code == 200
    body = res.json()
    assert body["key"] == "power"
    # power に値がある root: 10/20/30/40/50 + 11/13/21/23 = 9 件
    # 文字列 "not-a-number" は value_count から除外
    assert body["value_count"] == 9
    # record_count は走査した record 全件 (parent も root だが parent_id=None)
    # SeededLab の root レコード総数 = 13 (root-1..5, root-bad, parent,
    # g1-a, g1-b, g2-a, g2-b, with-result-a, with-result-b)
    assert body["record_count"] == 13
    assert body["stats"]["count"] == 9
    assert body["stats"]["min"] == 10
    assert body["stats"]["max"] == 50
    assert body["truncated"] is False


def test_non_numeric_values_excluded(client: TestClient) -> None:
    """key が存在しても文字列値は value_count に入らない。"""
    res = client.get("/api/records/aggregate?key=power")
    body = res.json()
    # root-bad の "not-a-number" は除外されるはず
    assert body["value_count"] < body["record_count"]


def test_parent_id_filter(client: TestClient, seeded_lab: Lab) -> None:
    """parent_id 指定で子レコード集合のみの集計を返す。"""
    parent_id = None
    for r in seeded_lab.list(limit=50):
        if r.title == "parent":
            parent_id = r.id
            break
    assert parent_id is not None
    res = client.get(f"/api/records/aggregate?key=power&parent_id={parent_id}")
    assert res.status_code == 200
    body = res.json()
    # 子 3 件、power = 100, 200, 300
    assert body["record_count"] == 3
    assert body["value_count"] == 3
    assert body["stats"]["min"] == 100
    assert body["stats"]["max"] == 300
    assert body["stats"]["mean"] == 200.0


def test_missing_key_returns_zero_value_count(client: TestClient) -> None:
    """そもそも誰も持っていない key は count=0 を返す (HTTP 200)。"""
    res = client.get("/api/records/aggregate?key=nonexistent")
    assert res.status_code == 200
    body = res.json()
    assert body["value_count"] == 0
    assert body["stats"]["count"] == 0


def test_group_by_splits_values(client: TestClient) -> None:
    """group_by 指定で label 別の stats を返す。"""
    res = client.get("/api/records/aggregate?key=power&group_by=angle")
    body = res.json()
    assert body["group_by"] == "angle"
    # angle=0 グループは power=11, 13 → mean=12
    assert "0" in body["groups"]
    assert body["groups"]["0"]["count"] == 2
    assert body["groups"]["0"]["mean"] == 12.0
    # angle=45 グループは power=21, 23 → mean=22
    assert "45" in body["groups"]
    assert body["groups"]["45"]["mean"] == 22.0


def test_truncated_flag(client: TestClient) -> None:
    """limit を超えた場合 truncated=true を返す。"""
    # limit=2 だけ走査すれば、root 10 件あるので必ず truncated
    res = client.get("/api/records/aggregate?key=power&limit=2")
    body = res.json()
    assert body["truncated"] is True
    assert body["record_count"] == 2


def test_invalid_conditions_returns_400(client: TestClient) -> None:
    """conditions が JSON でない → 400。"""
    res = client.get("/api/records/aggregate?key=power&conditions=not-json")
    assert res.status_code == 400


def test_limit_out_of_range_returns_400(client: TestClient) -> None:
    """limit が範囲外 → 400 (silently clamp しない、UX 上の混乱回避)。"""
    res = client.get("/api/records/aggregate?key=power&limit=0")
    assert res.status_code == 400
    res = client.get("/api/records/aggregate?key=power&limit=100000")
    assert res.status_code == 400


def test_results_key_aggregated(client: TestClient) -> None:
    """results にだけ存在する key (conditions に無い) も拾えること。

    backend は `merged = {**conditions, **results}` で両方を 1 つの dict に
    マージしてから key lookup する設計なので、解析後 lattice_a_A を
    `results[...]=...` で書いた record も /records StatsPanel から
    1st-class で集計対象になる。
    """
    res = client.get("/api/records/aggregate?key=lattice_a_A")
    body = res.json()
    assert body["value_count"] == 2
    assert body["stats"]["min"] == pytest.approx(2.873)
    assert body["stats"]["max"] == pytest.approx(2.875)


def test_endpoint_not_shadowed_by_record_id_route(client: TestClient) -> None:
    """`/records/{record_id}` が `/records/aggregate` を吸収しないこと
    (FastAPI ルーティング順の regression test)。"""
    res = client.get("/api/records/aggregate?key=power")
    # aggregate route が当たれば 200。{record_id} が吸収すると 404
    # ("Record not found")。
    assert res.status_code == 200, res.text
