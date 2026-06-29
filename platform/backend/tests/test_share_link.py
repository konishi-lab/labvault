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


# --- /api/share-links/me (self introspection) -----------------------------


def test_share_link_me_returns_scope(
    client: TestClient, record_id: str
) -> None:
    """share-link token で /me を叩くと scope (record_id / role / pseudo) が返る。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "analyst",
            "pseudo_email": "ext+me@klab.share",
            "pseudo_display_name": "Me Tester",
            "label": "intro",
        },
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.get(
        "/api/share-links/me",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["record_id"] == record_id
    assert body["team"] == "teamA"
    assert body["role"] == "analyst"
    assert body["pseudo_email"] == "ext+me@klab.share"
    assert body["pseudo_display_name"] == "Me Tester"
    # 30 日 default で expires_at が入っている
    assert body["expires_at"] is not None
    assert body["revoked_at"] is None


def test_share_link_me_rejects_firebase_user(
    client: TestClient, record_id: str
) -> None:
    """Firebase user が /me を叩くと 403 (share-link 専用 endpoint)。"""
    c = _as(client, _owner)
    res = c.get("/api/share-links/me", headers=_hdrs())
    assert res.status_code == 403


# --- S1-CQ1 / SEC1 / SEC3 hot-fix (2026-06-29) ----------------------------


def test_share_link_user_cannot_see_other_users_shares(
    client: TestClient, record_id: str, lab: Lab
) -> None:
    """S1-CQ1: share-link token で record 詳細を取っても、他の Firebase
    user の email が ``shares`` field で漏洩しない。"""
    # 事前に別 user (alice) に通常の share を grant
    rec = lab.get(record_id)
    rec.grant_share("alice@x.com", "viewer")

    # share-link token を pseudo_email='ext@y.com' で発行
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{record_id}",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
    )
    assert res.status_code == 200
    body = res.json()
    # share-link user 自身は shares dict に居ない (= 空) はず
    # (alice の email も見えない)
    assert "alice@x.com" not in body["shares"]
    assert body["shares"] == {}


def test_share_link_user_cannot_list_shares(
    client: TestClient, record_id: str
) -> None:
    """S1-CQ1: share-link token で /api/records/{id}/shares を叩くと 403。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{record_id}/shares",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
    )
    assert res.status_code == 403


def test_share_link_user_blocked_from_shared_with_me(
    client: TestClient, record_id: str
) -> None:
    """S1-SEC1: share-link token で /shared-with-me を叩くと 403。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        # 攻撃シナリオ: 被害者の email を pseudo_email に指定
        json={"role": "viewer", "pseudo_email": "victim@some.org"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.get(
        "/api/records/shared-with-me",
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert res.status_code == 403


def test_share_link_viewer_cannot_see_children(
    client: TestClient, record_id: str, lab: Lab
) -> None:
    """S1-SEC3: share-link viewer で parent の children/conditions を叩いて
    も子 record の summary や conditions/results が露出しない (scope
    record 1 本に固定)。
    """
    # 親 record の子を 2 件作る
    parent = lab.get(record_id)
    parent.sub("secret-child-1")
    parent.sub("secret-child-2")

    # viewer scope の share-link token を発行
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    # /children は 200 だが空配列 (scope mismatch で per-child filter)
    res = client.get(
        f"/api/records/{record_id}/children",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == []
    assert body["total"] == 0

    # /children/conditions も同様
    res2 = client.get(
        f"/api/records/{record_id}/children/conditions",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
    )
    assert res2.status_code == 200
    assert res2.json() == []


def test_share_link_analyst_bulk_upload_blocked_for_children_out_of_scope(
    client: TestClient, record_id: str, lab: Lab
) -> None:
    """S1-SEC4: bulk_upload は **per-child の require_analyze** を行う。
    share-link analyst (scope = parent record 1 本) は parent の require_analyze
    は通るが、 children へは can_analyze が False なので 1 file ごとに
    forbidden ステータスで弾かれる (= 全 file が 'forbidden' で skip)。
    """
    import io

    # parent に子を 2 件作る
    parent = lab.get(record_id)
    parent.sub("child-A1")
    parent.sub("child-A2")

    # analyst scope の share-link token を発行
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    # 2x1 grid で 2 file を bulk-upload。share-link analyst の scope は
    # parent record 1 本なので、children には can_analyze=False → 全 file
    # forbidden になるはず。
    res = client.post(
        f"/api/records/{record_id}/bulk-upload?rows=1&cols=2",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
        files=[
            ("files", ("a.txt", io.BytesIO(b"a"), "text/plain")),
            ("files", ("b.txt", io.BytesIO(b"b"), "text/plain")),
        ],
    )
    # SSE response。ステータスは 200 (handler の require_analyze は parent
    # で通る)、ただし各 file は 'forbidden' で skip される。
    assert res.status_code == 200
    body = res.text
    # 各 file が forbidden で出ること
    assert body.count('"status": "forbidden"') == 2
    # uploaded カウントは 0 のまま
    assert '"uploaded": 0' in body

    # 子 record にファイルが付いていないこと
    for child in parent.children():
        assert len([f for f in child.list_data()]) == 0


def test_share_link_me_rejects_no_auth(client: TestClient) -> None:
    """auth 無しで /me を叩くと 403 (Firebase 経路で来た user 扱い)。

    本番では Authorization 無し → ``current_authenticated_user`` で 401。
    ただし conftest が ``LABVAULT_DEV_SKIP_AUTH=1`` を立てるため、auth
    無しでも dev user が返り、結果的に「Firebase user → 403 (/me は
    share-link 専用)」の path を踏む。本テストは dev mode 下での
    挙動を保証する。
    """
    app.dependency_overrides.clear()
    res = client.get("/api/share-links/me")
    assert res.status_code == 403


# --- S1-TEST5 hot-fix (2026-06-29): edit / team-list endpoint の 403 ---
#
# share-link user は team membership を持たない (User.teams=())。よって
# ``get_lab`` (= ``current_team`` 経由) を使う 9 endpoint は **dep 評価
# 時点で 403** を返すはず。本テストは「将来 endpoint を ``get_lab_relaxed``
# に切替えて share-link 経路で漏らさないか」の構造的回帰検出。


EDIT_ENDPOINT_CASES = [
    # (method, path_template, json_body, content_type, expect_status)
    # team-scoped list / aggregate (read だが get_lab 経由)
    ("GET", "/api/records", None, None, 403),
    ("GET", "/api/records/aggregate?key=power", None, None, 403),
    # record 自身の mutation
    ("DELETE", "/api/records/{id}", None, None, 403),
    ("POST", "/api/records/{id}/restore", None, None, 403),
    ("PATCH", "/api/records/{id}/conditions", {"conditions": {"x": 1}}, "json", 403),
    ("POST", "/api/records/{id}/tags", {"tags": ["foo"]}, "json", 403),
    ("POST", "/api/records/{id}/notes", {"text": "test"}, "json", 403),
    ("PATCH", "/api/records/{id}/status", {"status": "success"}, "json", 403),
    ("PATCH", "/api/records/{id}/units", {"units": {"x": "W"}}, "json", 403),
    ("PATCH", "/api/records/{id}/result_units", {"units": {"y": "Hz"}}, "json", 403),
    ("POST", "/api/records/{id}/results", {"key": "z", "value": 1.0}, "json", 403),
]


@pytest.mark.parametrize(
    "method,path,body,content_type,expect_status",
    EDIT_ENDPOINT_CASES,
)
def test_share_link_viewer_cannot_use_edit_endpoints(
    client: TestClient,
    record_id: str,
    method: str,
    path: str,
    body: Any,
    content_type: str | None,
    expect_status: int,
) -> None:
    """S1-TEST5: share-link viewer token はあらゆる team-scoped / edit
    endpoint を叩けない (current_team が team membership を要求して 403)。

    記述ミスで将来誰かが get_lab → get_lab_relaxed に切替え、share-link
    user に意図せず権限を渡してしまっても、この test が落ちて発覚する。
    """
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext+v@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    headers = {
        "Authorization": f"Bearer {raw_token}",
        "X-Labvault-Team": "teamA",
    }
    url = path.format(id=record_id)
    kwargs: dict[str, Any] = {"headers": headers}
    if body is not None and content_type == "json":
        kwargs["json"] = body
    res = client.request(method, url, **kwargs)
    assert res.status_code == expect_status, (
        f"{method} {url} expected {expect_status}, got {res.status_code}: "
        f"{res.text[:200]}"
    )


@pytest.mark.parametrize(
    "method,path,body,content_type,expect_status",
    EDIT_ENDPOINT_CASES,
)
def test_share_link_analyst_cannot_use_edit_endpoints(
    client: TestClient,
    record_id: str,
    method: str,
    path: str,
    body: Any,
    content_type: str | None,
    expect_status: int,
) -> None:
    """S1-TEST5: analyst scope でも team-scoped / edit endpoint は使えない。

    analyst が許されるのは ``get_lab_relaxed`` 系の write (子 record 作成 +
    file upload + bulk-upload) のみで、record 自身の edit (status / tags
    等) や team 一覧は不可。
    """
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+a@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    headers = {
        "Authorization": f"Bearer {raw_token}",
        "X-Labvault-Team": "teamA",
    }
    url = path.format(id=record_id)
    kwargs: dict[str, Any] = {"headers": headers}
    if body is not None and content_type == "json":
        kwargs["json"] = body
    res = client.request(method, url, **kwargs)
    assert res.status_code == expect_status, (
        f"{method} {url} expected {expect_status}, got {res.status_code}: "
        f"{res.text[:200]}"
    )


# --- S1-SEC2 hot-fix (2026-06-29): pseudo_email collision + audit_source ---


def test_b1_pseudo_email_matching_allowed_users_rejected(
    client: TestClient, record_id: str, fake_db: Any
) -> None:
    """S1-SEC2 B1: pseudo_email が既存 allowed_users と一致 → 400。

    impersonation の defense-in-depth (audit_source field と二重で守る)。
    """
    # allowed_users に alice@example.com を登録
    from tests.conftest import _FakeCollection  # type: ignore

    fake_db._collections["allowed_users"] = _FakeCollection(
        {"alice@example.com": {"email": "alice@example.com", "active": True}}
    )

    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "alice@example.com"},
    )
    assert res.status_code == 400
    body = res.json()
    assert "allowed_users" not in body.get("detail", "")  # 詳細は user 向け文言
    assert "実在 user" in body.get("detail", "") or "Firebase user" in body.get(
        "detail", ""
    )


def test_b1_pseudo_email_not_in_allowed_users_accepted(
    client: TestClient, record_id: str, fake_db: Any
) -> None:
    """allowed_users に居ない email なら通常通り 201。"""
    c = _as(client, _owner)
    res = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext+e@klab.share"},
    )
    assert res.status_code == 201


def test_audit_source_share_link_on_child_create(
    client: TestClient, record_id: str
) -> None:
    """analyst token で子 record を作ると created/updated 両方が "share-link"。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        "/api/records",
        headers={
            "Authorization": f"Bearer {raw_token}",
            "X-Labvault-Team": "teamA",
        },
        json={"title": "ext-analysis", "parent_id": record_id},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["created_audit_source"] == "share-link"
    assert body["updated_audit_source"] == "share-link"


def test_audit_source_firebase_on_normal_create(
    client: TestClient,
) -> None:
    """Firebase user (owner) が root record を作ると created/updated 両方 "firebase"。"""
    c = _as(client, _owner)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={"title": "firebase-root"},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["created_audit_source"] == "firebase"
    assert body["updated_audit_source"] == "firebase"


def test_audit_source_updated_only_when_share_link_appends_file(
    client: TestClient, record_id: str
) -> None:
    """Firebase user が作った record に share-link analyst がファイル upload
    → created は "firebase" のまま、updated は "share-link" になる。"""
    import io

    # owner が作成 (already exists via fixture, created_by="owner@a.com")。
    # 一度 firebase 経路でファイルを足して audit_source を "firebase" に焼く
    c1 = _as(client, _owner)
    res0 = c1.post(
        f"/api/records/{record_id}/files",
        headers=_hdrs(),
        files={"file": ("seed.txt", io.BytesIO(b"x"), "text/plain")},
    )
    assert res0.status_code == 201
    assert res0.json()["created_audit_source"] in (None, "firebase")
    assert res0.json()["updated_audit_source"] == "firebase"

    # share-link analyst を発行 + token で別ファイル upload
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "analyst", "pseudo_email": "ext+ana@y.com"},
    ).json()
    raw_token = issued["token"]

    app.dependency_overrides.clear()
    res = client.post(
        f"/api/records/{record_id}/files",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
        files={"file": ("ext.txt", io.BytesIO(b"y"), "text/plain")},
    )
    assert res.status_code == 201
    body = res.json()
    # 作成 source は変わらない (Firebase 経路 = 旧 record は None でも OK)
    assert body["created_audit_source"] in (None, "firebase")
    # 最後の mutation は share-link
    assert body["updated_audit_source"] == "share-link"


def test_audit_source_roundtrip_via_get(
    client: TestClient, record_id: str, lab: Lab
) -> None:
    """記録された audit_source は GET /api/records/{id} 経由でも取れる。"""
    rec = lab.get(record_id)
    rec._created_audit_source = "share-link"
    rec._updated_audit_source = "share-link"
    rec._persist()

    c = _as(client, _owner)
    res = c.get(f"/api/records/{record_id}", headers=_hdrs())
    assert res.status_code == 200
    body = res.json()
    assert body["created_audit_source"] == "share-link"
    assert body["updated_audit_source"] == "share-link"


# --- S1 Phase A hot-fix (2026-06-29): D2 + OBS2/3/9 + UX5 ---


def test_obs9_last_used_at_updates_on_verify(
    client: TestClient, record_id: str, store: InMemoryShareLinkStore
) -> None:
    """S1-OBS9/UX5: share-link token を使った時に last_used_at が更新される。"""
    c1 = _as(client, _owner)
    issued = c1.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={"role": "viewer", "pseudo_email": "ext@y.com"},
    ).json()
    raw_token = issued["token"]
    prefix = issued["token_hash_prefix"]
    # 発行直後は未使用
    assert issued["last_used_at"] is None

    # token を使って record fetch
    app.dependency_overrides.clear()
    res = client.get(
        f"/api/records/{record_id}",
        headers={"Authorization": f"Bearer {raw_token}", "X-Labvault-Team": "teamA"},
    )
    assert res.status_code == 200

    # owner 視点で list すると last_used_at が入っている
    _as(client, _owner)
    list_res = client.get(
        f"/api/records/{record_id}/share-links", headers=_hdrs()
    )
    items = list_res.json()["items"]
    target = next(i for i in items if i["token_hash_prefix"] == prefix)
    assert target["last_used_at"] is not None


def test_obs2_invalid_share_link_emits_warning_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """S1-OBS2: 不正な ls_* token は WARNING で log_event される。"""
    import logging as _logging

    caplog.set_level(_logging.WARNING)
    app.dependency_overrides.clear()
    res = client.get(
        "/api/records/AB3F7K",
        headers={
            "Authorization": "Bearer ls_abcdef1234567890abcdef1234567890",
            "X-Labvault-Team": "teamA",
        },
    )
    assert res.status_code == 401
    # `share_link.auth_failed` event が log に出ているはず
    warning_events = [
        r for r in caplog.records if "share_link.auth_failed" in r.getMessage()
    ]
    assert warning_events, "expected share_link.auth_failed WARNING event"


def test_d2_share_link_token_redacted_in_logs(
    client: TestClient, record_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    """S1-D2: log message に ``ls_<hex>`` が乗っていれば redact される。

    application log (logger.info / log_event etc) で path に token が
    含まれても ``ls_<redacted>`` に置換されることを確認。
    """
    import logging as _logging

    from app.observability import _ShareLinkTokenRedactor

    # 直接 filter を適用して動作確認 (root logger の handler 経由は test
    # 環境で confgで抑制されているため)
    rec = _logging.LogRecord(
        name="test",
        level=_logging.INFO,
        pathname="x.py",
        lineno=1,
        msg="GET /share/ls_0123456789abcdef0123456789abcdef HTTP 200",
        args=(),
        exc_info=None,
    )
    f = _ShareLinkTokenRedactor()
    assert f.filter(rec) is True
    assert "ls_0123456789abcdef0123456789abcdef" not in rec.getMessage()
    assert "ls_<redacted>" in rec.getMessage()
