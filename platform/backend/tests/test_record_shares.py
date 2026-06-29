"""S1 Phase 1 (PR #84): cross-team record 共有機能の認可境界テスト。

`permissions.py` の判定関数 (can_read / can_analyze / can_grant) と
record-level の grant / revoke / list endpoint 群を SDK / backend 統合
ベースで検証する。

シナリオ:
- teamA member が record 作成 → teamB member へ viewer 共有
- teamB member は閲覧可能、grant 不可、edit 不可
- teamB を analyst に upgrade → 子 record 作成可能 (PR #84 では grant
  のみテスト、analyst write は次の PR で)
- super-admin はいつでも全権限
- 関係のない第三者 (teamC) は 403
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

# --- Lab fixture ---


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
def record_id(lab: Lab) -> str:
    """teamA の owner 経由で 1 件 record を作る。"""
    rec = lab.new("share-test", auto_log=False, created_by="owner@a.com")
    return rec.id


# --- HTTP client + per-test user override -----------------------------------


def _user(*, email: str, teams: list[tuple[str, str]], role: str = "member") -> User:
    return User(
        uid=f"uid-{email}",
        email=email,
        display_name=email.split("@")[0],
        role=role,
        teams=tuple(teams),
        default_team=teams[0][0] if teams else "",
    )


# 役者
def _owner() -> User:
    return _user(email="owner@a.com", teams=[("teamA", "member")])


def _team_a_admin() -> User:
    return _user(email="admin_a@a.com", teams=[("teamA", "admin")])


def _team_b_member() -> User:
    return _user(email="bob@b.com", teams=[("teamB", "member")])


def _team_c_member() -> User:
    return _user(email="charlie@c.com", teams=[("teamC", "member")])


def _super_admin() -> User:
    return _user(
        email="super@a.com",
        teams=[("teamA", "admin")],
        role="admin",  # legacy global admin = super-admin in this codebase
    )


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    lab: Lab,
) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: lab,
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _as(client: TestClient, factory: Any) -> TestClient:
    app.dependency_overrides[current_user] = factory
    return client


def _hdrs(team: str = "teamA") -> dict[str, str]:
    return {"X-Labvault-Team": team}


# --- 認可境界 ----------------------------------------------------------------


def test_owner_can_grant(client: TestClient, record_id: str) -> None:
    """record 作成者本人は grant できる。"""
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["shares"]["bob@b.com"] == "viewer"


def test_team_admin_can_grant(client: TestClient, record_id: str) -> None:
    """同 team の admin も grant できる (作成者本人でなくても OK)。"""
    c = _as(client, _team_a_admin)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "analyst"},
    )
    assert res.status_code == 201


def test_member_who_is_not_creator_cannot_grant(
    client: TestClient, record_id: str
) -> None:
    """同 team でも、作成者でなく admin でもない member は grant 不可。"""

    def _team_a_member() -> User:
        return _user(email="someone@a.com", teams=[("teamA", "member")])

    c = _as(client, _team_a_member)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    assert res.status_code == 403


def test_outside_team_cannot_grant(client: TestClient, record_id: str) -> None:
    """関係ない team の人は (share されていても) 再共有不可。

    S1-SEC6 (PR γ-2): outsider は read 不可 → uniform 404 で
    存在オラクル隠蔽 (旧 403)。
    """
    c = _as(client, _team_b_member)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),  # teamA を狙うが本人は teamB
        json={"email": "evil@evil.com", "role": "viewer"},
    )
    assert res.status_code == 404


def test_self_share_rejected(client: TestClient, record_id: str) -> None:
    """自分自身に共有しようとすると 400。意味がないので UX 上のガード。"""
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "owner@a.com", "role": "viewer"},
    )
    assert res.status_code == 400


def test_invalid_role_rejected(client: TestClient, record_id: str) -> None:
    """role が Literal["viewer","analyst"] 以外なら schema レベルで 422。

    S1-CQ11/13 hot-fix (PR γ-1): Pydantic Literal で schema validation
    時に 422 を返す (handler 内 400 より構造的に早い段階で弾く)。
    """
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "destroyer"},
    )
    assert res.status_code == 422


def test_invalid_email_rejected(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "not-an-email", "role": "viewer"},
    )
    assert res.status_code == 400


# --- read 認可 ----------------------------------------------------------------


def test_outside_team_cannot_read_without_share(
    client: TestClient, record_id: str
) -> None:
    """share されていない team の人は閲覧不可。

    S1-SEC6 (PR γ-2): uniform 404 で存在を漏らさない (旧 403)。
    GitHub の private repo と同じ pattern。
    """
    c = _as(client, _team_b_member)
    res = c.get(f"/api/records/{record_id}", headers=_hdrs())
    assert res.status_code == 404


def test_outside_team_can_read_after_viewer_grant(
    client: TestClient, record_id: str
) -> None:
    """viewer 共有された外部 team member は閲覧可能。"""
    # owner が grant
    c1 = _as(client, _owner)
    r1 = c1.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    assert r1.status_code == 201

    # bob が読む (header は record owner team を指定)
    c2 = _as(client, _team_b_member)
    res = c2.get(f"/api/records/{record_id}", headers=_hdrs())
    assert res.status_code == 200
    body = res.json()
    # 共有設定が見える (UI が「自分が share されている」表示するため)
    assert body["shares"]["bob@b.com"] == "viewer"


def test_third_party_still_blocked_after_grant_to_someone_else(
    client: TestClient, record_id: str
) -> None:
    """bob に共有されても charlie は閲覧不可。

    S1-SEC6 (PR γ-2): uniform 404 で存在を漏らさない (旧 403)。
    """
    c1 = _as(client, _owner)
    c1.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )

    c2 = _as(client, _team_c_member)
    res = c2.get(f"/api/records/{record_id}", headers=_hdrs())
    assert res.status_code == 404


# --- revoke 認可 / 挙動 -------------------------------------------------------


def test_revoke_by_owner(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    res = c.delete(f"/api/records/{record_id}/shares/bob@b.com", headers=_hdrs())
    assert res.status_code == 200
    body = res.json()
    assert "bob@b.com" not in body["shares"]


def test_revoke_nonexistent_email_is_idempotent(
    client: TestClient, record_id: str
) -> None:
    """存在しない email を revoke しても 200。UI 上の race 対策で no-op。"""
    c = _as(client, _owner)
    res = c.delete(
        f"/api/records/{record_id}/shares/nobody@nowhere.com", headers=_hdrs()
    )
    assert res.status_code == 200


def test_shared_user_cannot_revoke(client: TestClient, record_id: str) -> None:
    """共有された側 (bob) は他人の share を revoke できない。"""
    c1 = _as(client, _owner)
    c1.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    # bob が別の人 (charlie) の share を revoke 試行 (実際には居ない)
    c2 = _as(client, _team_b_member)
    res = c2.delete(f"/api/records/{record_id}/shares/charlie@c.com", headers=_hdrs())
    assert res.status_code == 403


# --- list 認可 ----------------------------------------------------------------


def test_list_shares_blocked_for_shared_user(
    client: TestClient, record_id: str
) -> None:
    """S1-CQ1 hot-fix (2026-06-29): 共有された user は他の共有相手の email
    を見られない (情報漏洩防止)。`list_record_shares` は ``require_grant``
    に格上げされたため、shared user は 403。
    自分の role は ``GET /api/records/{id}`` レスポンスの ``shares`` field
    (自分のエントリ 1 件のみ返る) で確認する。
    """
    c1 = _as(client, _owner)
    c1.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "analyst"},
    )

    # bob は他の共有相手を listしようとして 403
    c2 = _as(client, _team_b_member)
    res = c2.get(f"/api/records/{record_id}/shares", headers=_hdrs())
    assert res.status_code == 403

    # ただし record 詳細で自分の role は確認できる
    detail = c2.get(f"/api/records/{record_id}", headers=_hdrs())
    assert detail.status_code == 200
    body = detail.json()
    assert body["shares"] == {"bob@b.com": "analyst"}


def test_list_shares_blocked_for_non_shared_outsider(
    client: TestClient, record_id: str
) -> None:
    """S1-SEC6 (PR γ-2): outsider は read 不可 → uniform 404 (旧 403)。"""
    c = _as(client, _team_c_member)
    res = c.get(f"/api/records/{record_id}/shares", headers=_hdrs())
    assert res.status_code == 404


def test_list_shares_visible_to_owner_and_admin(
    client: TestClient, record_id: str
) -> None:
    """grant 主体 (owner / team admin) は全件見える。"""
    c1 = _as(client, _owner)
    c1.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "analyst"},
    )
    c1.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "charlie@c.com", "role": "viewer"},
    )

    # owner は全件見える
    res = c1.get(f"/api/records/{record_id}/shares", headers=_hdrs())
    assert res.status_code == 200
    items = res.json()["items"]
    assert {"email": "bob@b.com", "role": "analyst"} in items
    assert {"email": "charlie@c.com", "role": "viewer"} in items

    # team admin も同様
    c2 = _as(client, _team_a_admin)
    res2 = c2.get(f"/api/records/{record_id}/shares", headers=_hdrs())
    assert res2.status_code == 200
    items2 = res2.json()["items"]
    assert len(items2) == 2


# --- super-admin はいつでも全権限 ---------------------------------------------


def test_super_admin_can_grant(client: TestClient, record_id: str) -> None:
    c = _as(client, _super_admin)
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    assert res.status_code == 201


# --- role 変更 (re-grant で上書き) ---------------------------------------------


def test_regrant_updates_role(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    # role 変更
    res = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "analyst"},
    )
    assert res.status_code == 201
    assert res.json()["shares"]["bob@b.com"] == "analyst"
