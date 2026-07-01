"""2026-07-01: 共有 event 監査 log (Firestore ``share_events``) の統合テスト。

`records.py` の grant / revoke / share-link issue / share-link revoke 4
経路で ``append_share_event`` が呼ばれることを確認する。加えて
``GET /api/records/{id}/share-events`` の認可境界と時系列順を検証。

`test_record_shares.py` の fixture 構造を踏襲。in-memory backend が
``append_share_event`` / ``list_share_events`` を提供するので、live
Firestore は不要。
"""

from __future__ import annotations

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
    rec = lab.new("event-test", auto_log=False, created_by="owner@a.com")
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


def _admin() -> User:
    return _user(email="admin_a@a.com", teams=[("teamA", "admin")])


def _member() -> User:
    return _user(email="member@a.com", teams=[("teamA", "member")])


def _outsider() -> User:
    return _user(email="bob@b.com", teams=[("teamB", "member")])


@pytest.fixture()
def share_link_store() -> InMemoryShareLinkStore:
    return InMemoryShareLinkStore()


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    lab: Lab,
    share_link_store: InMemoryShareLinkStore,
) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: lab,
    )
    monkeypatch.setattr(
        "app.dependencies.get_share_link_store",
        lambda: share_link_store,
    )
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _as(client: TestClient, factory: Any) -> TestClient:
    app.dependency_overrides[current_user] = factory
    return client


def _hdrs(team: str = "teamA") -> dict[str, str]:
    return {"X-Labvault-Team": team}


# --- backend method 直接 (protocol contract) --------------------------------


def test_backend_append_and_list_roundtrip(lab: Lab) -> None:
    """InMemoryMetadataBackend の append → list を最小契約で確認。"""
    import datetime as dt

    lab.backend.append_share_event(
        "teamA",
        {
            "event_type": "granted",
            "record_id": "REC001",
            "role": "viewer",
            "actor_email": "a@x.com",
            "at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            "target_email": "b@y.com",
        },
    )
    events = lab.backend.list_share_events("teamA", "REC001")
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "granted"
    assert e["target_email"] == "b@y.com"


def test_backend_list_filters_by_record_id(lab: Lab) -> None:
    """list_share_events は record_id で絞り込む (他 record は返さない)。"""
    import datetime as dt

    for rid in ("REC-A", "REC-B"):
        lab.backend.append_share_event(
            "teamA",
            {
                "event_type": "granted",
                "record_id": rid,
                "role": "viewer",
                "actor_email": "a@x.com",
                "at": dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            },
        )
    a_events = lab.backend.list_share_events("teamA", "REC-A")
    assert len(a_events) == 1
    assert a_events[0]["record_id"] == "REC-A"


def test_backend_list_new_first(lab: Lab) -> None:
    """新しい順で返る (at DESC contract)."""
    import datetime as dt

    for day in (10, 5, 20, 1, 15):
        lab.backend.append_share_event(
            "teamA",
            {
                "event_type": "granted",
                "record_id": "REC",
                "role": "viewer",
                "actor_email": f"a{day}@x.com",
                "at": dt.datetime(2026, 7, day, tzinfo=dt.UTC),
            },
        )
    events = lab.backend.list_share_events("teamA", "REC")
    days = [e["at"].day for e in events]
    assert days == [20, 15, 10, 5, 1]


# --- endpoint 統合 (event が実際に飛んでいるか + 認可境界) ------------------


def test_grant_endpoint_appends_event(client: TestClient, record_id: str) -> None:
    c = _as(client, _admin)
    r = c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "analyst"},
    )
    assert r.status_code == 201

    r2 = c.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) == 1
    e = items[0]
    assert e["event_type"] == "granted"
    assert e["target_email"] == "bob@b.com"
    assert e["role"] == "analyst"
    assert e["actor_email"] == "admin_a@a.com"


def test_revoke_endpoint_appends_event(client: TestClient, record_id: str) -> None:
    c = _as(client, _admin)
    c.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    c.delete(f"/api/records/{record_id}/shares/bob@b.com", headers=_hdrs())

    r = c.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    items = r.json()["items"]
    # 新しい順: revoked が先
    assert items[0]["event_type"] == "revoked"
    assert items[1]["event_type"] == "granted"


def test_revoke_nonexistent_does_not_append(
    client: TestClient, record_id: str
) -> None:
    """revoke idempotent (実際には share が無かった) では event を残さない。"""
    c = _as(client, _admin)
    c.delete(f"/api/records/{record_id}/shares/nobody@nowhere.com", headers=_hdrs())
    r = c.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    assert r.json()["items"] == []


def test_share_link_issue_appends_event(
    client: TestClient, record_id: str
) -> None:
    c = _as(client, _admin)
    r = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "viewer",
            "pseudo_email": "guest@external.com",
            "pseudo_display_name": "External Guest",
            "label": "poster reviewer",
            "expires_days": 7,
        },
    )
    assert r.status_code == 201, r.json()
    r2 = c.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    items = r2.json()["items"]
    assert len(items) == 1
    e = items[0]
    assert e["event_type"] == "link_issued"
    assert e["pseudo_email"] == "guest@external.com"
    assert e["label"] == "poster reviewer"
    assert e["token_hash_prefix"]  # 16 chars 埋まっている


def test_share_link_revoke_appends_event(
    client: TestClient, record_id: str
) -> None:
    c = _as(client, _admin)
    issue = c.post(
        f"/api/records/{record_id}/share-links",
        headers=_hdrs(),
        json={
            "role": "analyst",
            "pseudo_email": "guest@external.com",
            "pseudo_display_name": "Guest",
            "expires_days": 7,
        },
    ).json()
    prefix = issue["token_hash_prefix"]

    r = c.delete(
        f"/api/records/{record_id}/share-links/{prefix}", headers=_hdrs()
    )
    assert r.status_code == 200

    r2 = c.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    items = r2.json()["items"]
    types = [e["event_type"] for e in items]
    # 新しい順: link_revoked → link_issued
    assert types[0] == "link_revoked"
    assert types[1] == "link_issued"


# --- 認可 -------------------------------------------------------------------


def test_read_endpoint_requires_grant_permission(
    client: TestClient, record_id: str
) -> None:
    """share-events 閲覧は grant 権限 (admin) と同等。member は 403。"""
    # まず admin が 1 件 grant しておく (event が発生)
    c_admin = _as(client, _admin)
    c_admin.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    # member は event log を読めない (403)
    c_member = _as(client, _member)
    r = c_member.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    assert r.status_code == 403


def test_read_endpoint_outsider_gets_404(
    client: TestClient, record_id: str
) -> None:
    """team 外の user は uniform 404 (存在オラクル隠蔽)."""
    c = _as(client, _outsider)
    r = c.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    assert r.status_code == 404


def test_read_endpoint_shared_user_cannot_read_history(
    client: TestClient, record_id: str
) -> None:
    """共有された user 本人でも履歴は読めない (grant 主体 only)。

    履歴には他の共有相手の email が入っており、それを見えると情報漏洩
    (S1-CQ1 と同じ理屈で shares list も grant only にしている)。
    """
    c_admin = _as(client, _admin)
    c_admin.post(
        f"/api/records/{record_id}/shares",
        headers=_hdrs(),
        json={"email": "bob@b.com", "role": "viewer"},
    )
    c_bob = _as(client, _outsider)
    r = c_bob.get(f"/api/records/{record_id}/share-events", headers=_hdrs())
    assert r.status_code == 403


def test_limit_validation(client: TestClient, record_id: str) -> None:
    c = _as(client, _admin)
    r = c.get(f"/api/records/{record_id}/share-events?limit=0", headers=_hdrs())
    assert r.status_code == 400
    r2 = c.get(f"/api/records/{record_id}/share-events?limit=1001", headers=_hdrs())
    assert r2.status_code == 400
