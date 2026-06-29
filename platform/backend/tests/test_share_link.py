"""S1 Phase 2: 外部 token sharing の認可境界テスト。

PR #84 (foundation) → #85 (shared-with-me) → #87 (analyst write) の
延長線上で、**Firebase アカウントを持たない外部協力者** に対する
record 共有 token (``ls_*``) を発行 → 検証 → 使用する経路を検証する。

主なシナリオ:
- record owner / team admin が token を発行できる (`require_grant`)
- 一般 team member や share された外部 user は token 発行できない
- 発行された token で `Authorization: Bearer ls_<hex>` を投げると
  - viewer scope: 詳細閲覧 + ファイル DL は OK、upload は 403
  - analyst scope: 詳細閲覧 + 子 record 作成 + upload OK、ただし
    record 自体の edit (title 等) は不可、shares grant は不可、root
    record 作成は不可
- 期限切れ / revoked / 不正 token は 401
- share-link user の scope.record_id と異なる record にアクセス →
  request は 200 で record 自体取れるが permission check で 403
  (record_id mismatch を弾く)
- 子 record 作成時 created_by に pseudo_email が刻まれる (audit)
"""

from __future__ import annotations

import datetime as dt
import io
from collections.abc import Iterator
from typing import Any

import pytest
from app.auth import User, current_user
from app.main import app
from app.share_links import InMemoryShareLinkStore
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)

# --- fixtures ---


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
def store() -> InMemoryShareLinkStore:
    """InMemory share-link store (test 全体で共有)。"""
    return InMemoryShareLinkStore()


@pytest.fixture()
def record_id(lab: Lab) -> str:
    rec = lab.new("share-link-test", auto_log=False, created_by="owner@a.com")
    return rec.id


def _user(*, email: str, teams: list[tuple[str, str]], role: str = "member") -> User:
    return User(
        uid=f"uid-{email}",
        email=email,
        display_name=email.split("@")[0],
        role=role,
        teams=tuple(teams),
        default_team=teams[0][0] if teams else "",
    )


def _owner() -> User:
    return _user(email="owner@a.com", teams=[("teamA", "member")])


def _team_a_admin() -> User:
    return _user(email="admin_a@a.com", teams=[("teamA", "admin")])


def _outsider() -> User:
    return _user(email="dave@d.com", teams=[("teamD", "member")])


def _super_admin() -> User:
    return _user(email="super@a.com", teams=[("teamA", "admin")], role="admin")


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    lab: Lab,
    store: InMemoryShareLinkStore,
) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: lab,
    )
    monkeypatch.setattr(
        "app.dependencies.get_share_link_store",
        lambda: store,
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _as(client: TestClient, factory: Any) -> TestClient:
    app.dependency_overrides[current_user] = factory
    return client


def _hdrs(team: str = "teamA") -> dict[str, str]:
    return {"X-Labvault-Team": team}


# --- token 発行 ---------------------------------------------------------


def test_owner_can_issue_share_link(client: TestClient, record_id: str) -> None:
    """record creator は share-link を発行できる。"""
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "viewer",
            "pseudo_email": "external+jane@klab.share",
            "pseudo_display_name": "Jane (NIMS)",
            "label": "for NIMS collab",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["token"].startswith("ls_")
    assert body["role"] == "viewer"
    assert body["pseudo_email"] == "external+jane@klab.share"
    assert body["is_active"] is True
    # raw token は 1 回しか返らない: 一覧では token field は無い (Info の方が返る)
    list_res = c.get(f"/api/records/{record_id}/share-links", headers=_hdrs())
    items = list_res.json()["items"]
    assert len(items) == 1
    assert "token" not in items[0]


def test_team_admin_can_issue_share_link(client: TestClient, record_id: str) -> None:
    c = _as(client, _team_a_admin)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "analyst",
            "pseudo_email": "external+team@klab.share",
        },
    )
    assert res.status_code == 201


def test_super_admin_can_issue_share_link(client: TestClient, record_id: str) -> None:
    c = _as(client, _super_admin)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "external+x@klab.share"},
    )
    assert res.status_code == 201


def test_outsider_cannot_issue_share_link(client: TestClient, record_id: str) -> None:
    c = _as(client, _outsider)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "external+e@klab.share"},
    )
    assert res.status_code == 403


def test_invalid_role_rejected(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "godmode", "pseudo_email": "e@x.com"},
    )
    assert res.status_code == 400


def test_invalid_pseudo_email_rejected(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "not-an-email"},
    )
    assert res.status_code == 400


def test_excessive_expires_rejected(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "viewer",
            "pseudo_email": "e@x.com",
            "expires_days": 9999,
        },
    )
    assert res.status_code == 400


def test_expires_zero_means_no_expiry(client: TestClient, record_id: str) -> None:
    """expires_days=0 は「無期限」(expires_at=null) として記録される。"""
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "viewer",
            "pseudo_email": "e@x.com",
            "expires_days": 0,
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["expires_at"] is None


# --- revoke ---------------------------------------------------------------


def test_owner_can_revoke_share_link(client: TestClient, record_id: str) -> None:
    c = _as(client, _owner)
    issued = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "e@x.com"},
    ).json()
    prefix = issued["token_hash_prefix"]
    res = c.delete(
        f"/api/records/{record_id}/share-links/{prefix}", headers=_hdrs()
    )
    assert res.status_code == 200
    # 取消後は is_active=False
    items = c.get(f"/api/records/{record_id}/share-links", headers=_hdrs()).json()[
        "items"
    ]
    target = next(i for i in items if i["token_hash_prefix"] == prefix)
    assert target["is_active"] is False
    assert target["revoked_at"] is not None


def test_outsider_cannot_revoke(client: TestClient, record_id: str) -> None:
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "e@x.com"},
    ).json()
    prefix = issued["token_hash_prefix"]

    c2 = _as(client, _outsider)
    res = c2.delete(
        f"/api/records/{record_id}/share-links/{prefix}", headers=_hdrs()
    )
    assert res.status_code == 403


def test_outsider_cannot_list(client: TestClient, record_id: str) -> None:
    c = _as(client, _outsider)
    res = c.get(f"/api/records/{record_id}/share-links", headers=_hdrs())
    assert res.status_code == 403


def test_revoke_unknown_prefix_returns_404(
    client: TestClient, record_id: str
) -> None:
    c = _as(client, _owner)
    res = c.delete(
        f"/api/records/{record_id}/share-links/deadbeefdeadbeef", headers=_hdrs()
    )
    assert res.status_code == 404


# --- token を使った read / write 経路 ------------------------------------


def test_viewer_token_can_read_record(
    client: TestClient, record_id: str, store: InMemoryShareLinkStore
) -> None:
    """viewer token で record 詳細を引ける (Authorization 経由)。"""
    # owner として発行 (token 取得)
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "jane@external.com"},
    ).json()
    raw_token = issued["token"]

    # current_user override を外して、Authorization header で認証する
    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{record_id}",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == record_id


def test_viewer_token_cannot_upload(
    client: TestClient, record_id: str, store: InMemoryShareLinkStore
) -> None:
    """viewer token で upload を試みると 403。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "jane@external.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        f"/api/records/{record_id}/files",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        files={"file": ("v.txt", io.BytesIO(b"x"), "text/plain")},
    )
    assert res.status_code == 403


def test_analyst_token_can_upload_with_audit(
    client: TestClient, record_id: str, lab: Lab
) -> None:
    """analyst token で upload OK、updated_by に pseudo_email が刻まれる。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "analyst",
            "pseudo_email": "ext+ana@klab.share",
            "pseudo_display_name": "Ana",
        },
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        f"/api/records/{record_id}/files",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        files={"file": ("ana.txt", io.BytesIO(b"results"), "text/plain")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["updated_by"] == "ext+ana@klab.share"
    assert any(f["name"] == "ana.txt" for f in body["files"])


def test_analyst_token_can_create_child_with_audit(
    client: TestClient, record_id: str
) -> None:
    """analyst token で子 record 作成、created_by が pseudo_email。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@klab.share"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        "/api/records",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        json={"title": "external-analysis", "parent_id": record_id},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["created_by"] == "ext+ana@klab.share"
    assert body["parent_id"] == record_id


def test_analyst_token_cannot_create_root_record(
    client: TestClient, record_id: str
) -> None:
    """analyst token でも root record (parent_id 無し) は作れない。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@klab.share"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        "/api/records",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        json={"title": "would-be-root"},  # parent_id 無し
    )
    assert res.status_code == 403


def test_analyst_token_cannot_grant_share(
    client: TestClient, record_id: str
) -> None:
    """analyst token でも shares grant (再共有) はできない。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@klab.share"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        f"/api/records/{record_id}/shares",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        json={"email": "evil@evil.com", "role": "viewer"},
    )
    assert res.status_code == 403


def test_analyst_token_cannot_issue_share_link(
    client: TestClient, record_id: str
) -> None:
    """analyst token でも token 再発行はできない (chain of trust 切断)。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@klab.share"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        f"/api/records/{record_id}/share-links",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        json={"role": "viewer", "pseudo_email": "evil@evil.com"},
    )
    assert res.status_code == 403


# --- scope mismatch -------------------------------------------------------


def test_token_cannot_access_other_record(
    client: TestClient, record_id: str, lab: Lab
) -> None:
    """share-link token は scope.record_id 以外の record には触れない。"""
    # 別 record (rec2) を teamA に作る
    other = lab.new("other-record", auto_log=False, created_by="owner@a.com")

    # rec1 用の viewer token を発行
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext+e@klab.share"},
    ).json()
    raw_token = issued["token"]

    # token で rec2 を覗こうとする → 403 (record_id mismatch)
    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{other.id}",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
    )
    assert res.status_code == 403


# --- token 検証 (期限切れ / revoke / invalid) ----------------------------


def test_revoked_token_rejected(
    client: TestClient, record_id: str, store: InMemoryShareLinkStore
) -> None:
    """revoke 済 token は 401。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext+e@klab.share"},
    ).json()
    raw_token = issued["token"]
    prefix = issued["token_hash_prefix"]

    # owner が revoke
    c1.delete(f"/api/records/{record_id}/share-links/{prefix}", headers=_hdrs())

    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{record_id}",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
    )
    assert res.status_code == 401


def test_expired_token_rejected(
    client: TestClient,
    record_id: str,
    store: InMemoryShareLinkStore,
    lab: Lab,
) -> None:
    """有効期限切れ token は 401。"""
    # 直接 store を作って expires_at を過去にする
    from app.share_links import ShareLink, generate_token

    raw, h = generate_token()
    store.create(
        ShareLink(
            token_hash=h,
            record_id=record_id,
            team="teamA",
            role="viewer",
            pseudo_email="ext+expired@klab.share",
            pseudo_display_name="Expired",
            created_by="owner@a.com",
            created_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=10),
            expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
            revoked_at=None,
            label="",
        )
    )

    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{record_id}",
        headers={
            "Authorization": f"Bearer {raw}",
            "X-Labvault-Team": "teamA",
        },
    )
    assert res.status_code == 401


def test_unknown_token_rejected(client: TestClient) -> None:
    """存在しない ls_* token は 401。"""
    app.dependency_overrides.clear()
    res = client.get(
        "/api/records/AB3F7K",
        headers={
            "Authorization": "Bearer ls_abcdef1234567890abcdef1234567890",
            "X-Labvault-Team": "teamA",
        },
    )
    assert res.status_code == 401


def test_malformed_ls_token_rejected(client: TestClient) -> None:
    """ls_ で始まるが lookup できない token は 401。"""
    app.dependency_overrides.clear()
    res = client.get(
        "/api/records/AB3F7K",
        headers={"Authorization": "Bearer ls_garbage"},
    )
    assert res.status_code == 401
