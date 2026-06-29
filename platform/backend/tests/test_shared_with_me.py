"""S1 Phase 1B: `GET /api/records/shared-with-me` の認可境界テスト。

`test_record_shares.py` は record per-record の grant / revoke / read を
カバーするが、こちらは「複数 team の複数 record にまたがる shared-with-me
の一覧 endpoint」の挙動を検証する。

シナリオ:
- teamA に rec1 / rec2 / rec3 を作る
- rec1: bob (teamB) に viewer 共有
- rec2: bob (teamB) に analyst 共有 + charlie (teamC) に viewer 共有
- rec3: 誰にも共有しない
- bob で shared-with-me → rec1 + rec2 が返る (role それぞれ)
- charlie で shared-with-me → rec2 のみ
- 自 team の member は shared-with-me に自 team の record が漏れないこと
  (= shared_with_emails に email が入っている record のみが対象)
- 削除済 record は shared-with-me に出ない
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from app.auth import User, current_user
from app.main import app
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(k, "")
    return Lab(
        "teamA",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


@pytest.fixture()
def seeded_records(lab: Lab) -> dict[str, str]:
    """teamA に 3 件作って、bob / charlie への共有を設定する。

    返り値: title → record_id の辞書。
    """
    rec1 = lab.new("rec1-viewer-bob", auto_log=False, created_by="owner@a.com")
    rec1.grant_share("bob@b.com", "viewer")

    rec2 = lab.new(
        "rec2-analyst-bob-and-viewer-charlie",
        auto_log=False,
        created_by="owner@a.com",
    )
    rec2.grant_share("bob@b.com", "analyst")
    rec2.grant_share("charlie@c.com", "viewer")

    rec3 = lab.new("rec3-unshared", auto_log=False, created_by="owner@a.com")

    return {"rec1": rec1.id, "rec2": rec2.id, "rec3": rec3.id}


def _user(*, email: str, teams: list[tuple[str, str]], role: str = "member") -> User:
    return User(
        uid=f"uid-{email}",
        email=email,
        display_name=email.split("@")[0],
        role=role,
        teams=tuple(teams),
        default_team=teams[0][0] if teams else "",
    )


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    lab: Lab,
) -> Iterator[TestClient]:
    # share grant / revoke 用 (get_lab_for_team) も含めて、両方の経路で
    # 同じ InMemory backend を返すように差し替える。
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: lab,
    )
    # shared-with-me 専用の dep: backend を直に差し替え (Firestore に
    # アクセスしない)。
    monkeypatch.setattr(
        "app.dependencies.get_shared_metadata_backend",
        lambda: lab._metadata,
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _as(client: TestClient, factory: Any) -> TestClient:
    app.dependency_overrides[current_user] = factory
    return client


# テストで使う user factory 群 (E731 回避のため def 化)。


def _bob() -> User:
    return _user(email="bob@b.com", teams=[("teamB", "member")])


def _bob_upper() -> User:
    return _user(email="Bob@B.com", teams=[("teamB", "member")])


def _charlie() -> User:
    return _user(email="charlie@c.com", teams=[("teamC", "member")])


def _nobody() -> User:
    return _user(email="nobody@nowhere.com", teams=[("teamB", "member")])


def _owner() -> User:
    return _user(email="owner@a.com", teams=[("teamA", "member")])


# --- 一覧取得の正常系 -------------------------------------------------------


def test_bob_sees_both_rec1_and_rec2(
    client: TestClient, seeded_records: dict[str, str]
) -> None:
    """viewer 共有された rec1 と analyst 共有された rec2 の両方が見える。"""
    c = _as(client, _bob)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    body = res.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {seeded_records["rec1"], seeded_records["rec2"]}
    # role が正しく付与される (rec1 = viewer, rec2 = analyst)
    by_id = {item["id"]: item for item in body["items"]}
    assert by_id[seeded_records["rec1"]]["role"] == "viewer"
    assert by_id[seeded_records["rec2"]]["role"] == "analyst"
    # team も入っている (frontend が X-Labvault-Team を組むため)
    assert by_id[seeded_records["rec1"]]["team"] == "teamA"


def test_charlie_sees_only_rec2(
    client: TestClient, seeded_records: dict[str, str]
) -> None:
    """rec2 だけ charlie に共有されている。"""
    c = _as(client, _charlie)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    items = res.json()["items"]
    assert [item["id"] for item in items] == [seeded_records["rec2"]]
    assert items[0]["role"] == "viewer"


def test_other_user_sees_nothing(
    client: TestClient, seeded_records: dict[str, str]
) -> None:
    """共有されていない user は空配列。"""
    c = _as(client, _nobody)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_more"] is False


def test_owner_does_not_see_own_unshared_records(
    client: TestClient, seeded_records: dict[str, str]
) -> None:
    """自 team の record でも shares に自分が居なければ出ない。

    shared-with-me は「自分宛てに明示的に共有された」だけを返す
    のが契約。自 team の record は別エンドポイント (/api/records)
    で取る前提。owner には rec3 (誰にも共有していない) は出ない。
    """
    c = _as(client, _owner)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    items = res.json()["items"]
    # owner@a.com を shares に入れていないので空
    assert items == []


# --- revoke 後の挙動 -------------------------------------------------------


def test_revoked_share_disappears(
    client: TestClient, seeded_records: dict[str, str], lab: Lab
) -> None:
    """共有を取り消すと shared-with-me から消える。"""
    c = _as(client, _bob)

    # 最初は 2 件見える
    assert len(c.get("/api/records/shared-with-me").json()["items"]) == 2

    # owner が rec1 の共有を取り消す
    rec1 = lab.get(seeded_records["rec1"])
    rec1.revoke_share("bob@b.com")

    # rec2 だけ残る
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()["items"]}
    assert ids == {seeded_records["rec2"]}


# --- 削除済 record は除外 -------------------------------------------------


def test_soft_deleted_record_excluded(
    client: TestClient, seeded_records: dict[str, str], lab: Lab
) -> None:
    """ソフト削除された record は shared-with-me に出ない。"""
    # rec1 を削除
    lab.delete(seeded_records["rec1"])

    c = _as(client, _bob)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()["items"]}
    # rec1 は除外、rec2 だけ
    assert ids == {seeded_records["rec2"]}


# --- limit / has_more -----------------------------------------------------


def test_has_more_when_results_exceed_limit(
    client: TestClient, seeded_records: dict[str, str], lab: Lab
) -> None:
    """limit を 1 にすると 1 件だけ返り、has_more=True。"""
    c = _as(client, _bob)
    res = c.get("/api/records/shared-with-me?limit=1")
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == 1
    assert body["has_more"] is True


def test_limit_boundary_validation(client: TestClient) -> None:
    """limit が範囲外なら 400。"""
    c = _as(client, _bob)
    assert c.get("/api/records/shared-with-me?limit=0").status_code == 400
    assert c.get("/api/records/shared-with-me?limit=1000").status_code == 400
    assert c.get("/api/records/shared-with-me?offset=-1").status_code == 400


# --- email lower-case 化 ---------------------------------------------------


def test_email_lookup_is_lowercase(
    client: TestClient, seeded_records: dict[str, str]
) -> None:
    """user.email が大文字混じりでも、shares の lowercase key にヒットする。"""
    c = _as(client, _bob_upper)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()["items"]}
    assert ids == {seeded_records["rec1"], seeded_records["rec2"]}


# --- ルーティング順 / 既存の path との衝突 -------------------------------


def test_shared_with_me_does_not_collide_with_record_id_path(
    client: TestClient, seeded_records: dict[str, str]
) -> None:
    """`/api/records/{record_id}` の catch-all より優先される。

    `shared-with-me` を `/{record_id}` 経路として解釈すると 404 になる
    はず (`record_id="shared-with-me"` という record は存在しない)。
    実装ミスで順序を間違えると即検知する。
    """
    c = _as(client, _bob)
    res = c.get("/api/records/shared-with-me")
    # 200 で SharedRecordListResponse が返れば順序は正しい (404 や 422 ではない)
    assert res.status_code == 200
    assert "items" in res.json()


# --- S1 Phase γ-1 hot-fix (2026-06-29): DATA7 unknown-role skip ---


def test_data7_unknown_role_is_skipped(
    client: TestClient, lab: Lab
) -> None:
    """S1-DATA7: shares dict に未知 role がある record は /shared-with-me
    に出ない (旧実装は silent viewer 降格 → 詳細 403 で矛盾していた)。"""
    # 正規 role の record
    rec_ok = lab.new("ok-rec", auto_log=False, created_by="owner@a.com")
    rec_ok.grant_share("bob@b.com", "viewer")

    # 直接 shares を未知 role に汚染した record (Firestore console 編集 / 手動
    # migration を想定)
    rec_bad = lab.new("bad-rec", auto_log=False, created_by="owner@a.com")
    rec_bad._shares["bob@b.com"] = "super_viewer"  # 未知 role
    rec_bad._persist()

    c = _as(client, _bob)
    res = c.get("/api/records/shared-with-me")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()["items"]}
    # rec_ok だけ出る、rec_bad は skip
    assert rec_ok.id in ids
    assert rec_bad.id not in ids
