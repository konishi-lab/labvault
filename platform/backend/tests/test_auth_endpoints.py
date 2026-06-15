"""Auth endpoint (request_access / welcome_acknowledged) のテスト。

`current_authenticated_user` (Firebase 認証のみ) と `current_user`
(allowed_users 照合済) の 2 系統に分かれる:

- `/api/auth/request-access` → current_authenticated_user
  Firebase 認証はあるが allowed_users には未登録、というユーザー向け。
- `/api/auth/welcome-acknowledged` → current_user
  既に承認済ユーザーが Welcome 画面を閉じる時に叩く。

ここでは:
  - request_access: 新規 / 重複 / 既に allowed / 空 team 名 / email 無し
  - welcome_acknowledged: happy path / 冪等性 / unauth
を検証する。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from .conftest import FakeDB


# ----------------------------------------------------------------------
# /api/auth/request-access  (POST, current_authenticated_user)
# ----------------------------------------------------------------------


def test_request_access_new_creates_pending_and_notifies(
    as_applicant: TestClient,
    fake_db: FakeDB,
    slack_notifications: list[dict[str, Any]],
) -> None:
    res = as_applicant.post(
        "/api/auth/request-access",
        json={
            "requested_team_name": "konishi-lab",
            "note": "学部 4 年、レーザー加工で参加します",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "pending"
    assert body["email"] == "applicant@example.com"
    assert body["requested_team_name"] == "konishi-lab"

    # pending に書かれている
    pending = fake_db.collection("pending_users")._docs
    assert "applicant@example.com" in pending
    doc = pending["applicant@example.com"]
    assert doc["requested_team_name"] == "konishi-lab"
    assert doc["note"] == "学部 4 年、レーザー加工で参加します"

    # Slack 通知が 1 回飛ぶ
    assert len(slack_notifications) == 1
    assert slack_notifications[0]["email"] == "applicant@example.com"
    assert slack_notifications[0]["requested_team_name"] == "konishi-lab"


def test_request_access_repeat_overwrites_and_skips_notify(
    as_applicant: TestClient,
    fake_db: FakeDB,
    slack_notifications: list[dict[str, Any]],
) -> None:
    """同じ user が 2 回叩いたら pending は上書き、Slack は重複通知しない。"""
    fake_db.collection("pending_users")._docs.update(
        {
            "applicant@example.com": {
                "email": "applicant@example.com",
                "display_name": "Applicant",
                "requested_team_name": "old-team",
                "note": "first",
            },
        }
    )
    res = as_applicant.post(
        "/api/auth/request-access",
        json={"requested_team_name": "new-team", "note": "updated"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "pending"
    # 上書きされている
    assert (
        fake_db.collection("pending_users")
        ._docs["applicant@example.com"]["requested_team_name"]
        == "new-team"
    )
    # 既存 pending があったので Slack 通知は飛ばない
    assert slack_notifications == []


def test_request_access_already_allowed(
    as_applicant: TestClient,
    fake_db: FakeDB,
    slack_notifications: list[dict[str, Any]],
) -> None:
    """既に allowed_users (active) に居る場合は no-op + already_allowed を返す。"""
    fake_db.collection("allowed_users")._docs.update(
        {
            "applicant@example.com": {
                "email": "applicant@example.com",
                "role": "member",
                "active": True,
            },
        }
    )
    res = as_applicant.post(
        "/api/auth/request-access",
        json={"requested_team_name": "any-team"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "already_allowed"
    assert res.json()["email"] == "applicant@example.com"
    # pending には書かれない
    assert "applicant@example.com" not in fake_db.collection("pending_users")._docs
    # 通知も飛ばない
    assert slack_notifications == []


def test_request_access_empty_team_name_400(
    as_applicant: TestClient,
    fake_db: FakeDB,
    slack_notifications: list[dict[str, Any]],
) -> None:
    res = as_applicant.post(
        "/api/auth/request-access",
        json={"requested_team_name": "   "},  # 空白のみ → strip 後に空
    )
    assert res.status_code == 400
    assert "requested_team_name" in res.json()["detail"]
    # pending / 通知は走らない
    assert "applicant@example.com" not in fake_db.collection("pending_users")._docs
    assert slack_notifications == []


def test_request_access_no_email_400(
    as_applicant_no_email: TestClient,
    fake_db: FakeDB,
    slack_notifications: list[dict[str, Any]],
) -> None:
    """Firebase token に email が無い極めて稀なケースは 400 で弾く。"""
    res = as_applicant_no_email.post(
        "/api/auth/request-access",
        json={"requested_team_name": "any-team"},
    )
    assert res.status_code == 400
    assert "email" in res.json()["detail"].lower()
    assert slack_notifications == []


def test_request_access_unauth_401(
    as_unauth_authenticated: TestClient,
    fake_db: FakeDB,
    slack_notifications: list[dict[str, Any]],
) -> None:
    res = as_unauth_authenticated.post(
        "/api/auth/request-access",
        json={"requested_team_name": "any-team"},
    )
    assert res.status_code == 401
    assert slack_notifications == []


# ----------------------------------------------------------------------
# /api/auth/welcome-acknowledged  (POST, current_user)
# ----------------------------------------------------------------------


def test_welcome_acknowledged_sets_timestamp(
    as_member: TestClient, fake_db: FakeDB
) -> None:
    # member ロール (conftest の user_member) で叩く
    fake_db.collection("allowed_users")._docs.update(
        {
            "m@example.com": {
                "email": "m@example.com",
                "role": "member",
                "active": True,
            },
        }
    )
    res = as_member.post("/api/auth/welcome-acknowledged")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    doc = fake_db.collection("allowed_users")._docs["m@example.com"]
    assert "welcomed_at" in doc
    first_ts = doc["welcomed_at"]
    assert first_ts is not None


def test_welcome_acknowledged_is_idempotent(
    as_member: TestClient, fake_db: FakeDB
) -> None:
    """2 回目以降の呼び出しも 200 を返し、welcomed_at は新しい値で上書きされる。"""
    fake_db.collection("allowed_users")._docs.update(
        {
            "m@example.com": {
                "email": "m@example.com",
                "role": "member",
                "active": True,
            },
        }
    )
    res1 = as_member.post("/api/auth/welcome-acknowledged")
    first_ts = fake_db.collection("allowed_users")._docs["m@example.com"][
        "welcomed_at"
    ]

    res2 = as_member.post("/api/auth/welcome-acknowledged")
    assert res1.status_code == res2.status_code == 200

    second_ts = fake_db.collection("allowed_users")._docs["m@example.com"][
        "welcomed_at"
    ]
    # 上書き挙動 (新しい値か同値) — 大事なのは「2 回目も成功する」こと
    assert second_ts is not None
    assert second_ts >= first_ts


def test_welcome_acknowledged_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.post("/api/auth/welcome-acknowledged")
    assert res.status_code == 401
