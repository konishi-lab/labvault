"""/api/auth/* endpoint のテスト (admin authz テストとは別レイヤ)。

カバー:
- POST /api/auth/request-access (Firebase auth 通過、allowed_users 未登録)
- POST /api/auth/welcome-acknowledged (allowed_users 登録済の任意 user)
- 通知 (notify_signup_request) は autouse fixture で no-op

`notify_signup_request` は Slack 通知の副作用がある。テストでは常に
stub で吸収する。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import FakeDB


@pytest.fixture(autouse=True)
def stub_notify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.main.notify_signup_request",
        lambda **kwargs: None,
    )


# ----------------------------------------------------------------------
# /api/auth/request-access
# ----------------------------------------------------------------------


def test_request_access_new_user_creates_pending(
    as_authed_new: TestClient, fake_db: FakeDB
) -> None:
    res = as_authed_new.post(
        "/api/auth/request-access",
        json={"requested_team_name": "klab", "note": "QA test"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["email"] == "newcomer@example.com"
    assert body["requested_team_name"] == "klab"

    # pending_users に doc が作られている
    pending = fake_db.collection("pending_users")._docs
    assert "newcomer@example.com" in pending
    assert pending["newcomer@example.com"]["requested_team_name"] == "klab"
    assert pending["newcomer@example.com"]["note"] == "QA test"


def test_request_access_existing_user_returns_already_allowed(
    as_authed_existing_allowed: TestClient, fake_db: FakeDB
) -> None:
    res = as_authed_existing_allowed.post(
        "/api/auth/request-access",
        json={"requested_team_name": "klab"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "already_allowed"
    # pending_users には書かれない
    assert "existing@example.com" not in fake_db.collection("pending_users")._docs


def test_request_access_empty_team_name_400(as_authed_new: TestClient) -> None:
    res = as_authed_new.post(
        "/api/auth/request-access",
        json={"requested_team_name": "  ", "note": ""},
    )
    assert res.status_code == 400


def test_request_access_idempotent_resubmit(
    as_authed_new: TestClient, fake_db: FakeDB
) -> None:
    """同じ email で 2 回叩いても pending entry は 1 件 (内容は更新される)。"""
    as_authed_new.post(
        "/api/auth/request-access",
        json={"requested_team_name": "klab", "note": "first"},
    )
    res = as_authed_new.post(
        "/api/auth/request-access",
        json={"requested_team_name": "klab2", "note": "second"},
    )
    assert res.status_code == 200
    pending = fake_db.collection("pending_users")._docs
    assert len(pending) == 1
    # 上書き反映
    assert pending["newcomer@example.com"]["requested_team_name"] == "klab2"
    assert pending["newcomer@example.com"]["note"] == "second"


# ----------------------------------------------------------------------
# /api/auth/welcome-acknowledged
# ----------------------------------------------------------------------


def _seed_self_allowed(fake_db: FakeDB, email: str, team: str = "teamA") -> None:
    fake_db.collection("allowed_users")._docs[email] = {
        "email": email,
        "display_name": email.split("@")[0],
        "role": "member",
        "teams": [{"team_id": team, "role": "member"}],
        "default_team": team,
        "active": True,
    }


def test_welcome_acknowledged_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_self_allowed(fake_db, "super@example.com")
    res = as_super.post("/api/auth/welcome-acknowledged")
    assert res.status_code == 200
    assert (
        "welcomed_at" in fake_db.collection("allowed_users")._docs["super@example.com"]
    )


def test_welcome_acknowledged_member_ok(as_member: TestClient, fake_db: FakeDB) -> None:
    """welcome 確認は member でも通る (admin endpoint ではない)。"""
    _seed_self_allowed(fake_db, "m@example.com")
    res = as_member.post("/api/auth/welcome-acknowledged")
    assert res.status_code == 200


def test_welcome_acknowledged_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.post("/api/auth/welcome-acknowledged")
    assert res.status_code == 401
