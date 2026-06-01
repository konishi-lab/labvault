"""admin endpoint の整合性ルール (認可ではなく business rule) のテスト。

カバー:
- 自己 deactivate 不可 (PATCH /api/admin/users/<self>)
- 最後の active super-admin の deactivate 不可 (admin 全員不在を防ぐ)
- ユーザーから最後の team を外せない (DELETE users/{e}/teams/{t})
- 既存 active user の再 approve は 409 (Use team-add endpoint と伝える)

PR #21 で認可境界を網羅した後、handler 内に書かれている「禁止ルール」を
回帰防止する。これらが緩むと運用上の事故 (admin 全員不在、user の team
喪失、approve でデータが消える) に直結するため。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import FakeDB

# ----------------------------------------------------------------------
# 自己 deactivate 不可
# ----------------------------------------------------------------------


def test_super_cannot_deactivate_self(as_super: TestClient, fake_db: FakeDB) -> None:
    # as_super は email="super@example.com" / role="admin"
    fake_db.collection("allowed_users")._docs["super@example.com"] = {
        "email": "super@example.com",
        "role": "admin",
        "active": True,
    }
    res = as_super.patch(
        "/api/admin/users/super@example.com",
        json={"active": False},
    )
    assert res.status_code == 400
    assert "yourself" in res.json()["detail"]


# ----------------------------------------------------------------------
# 最後の active super-admin の deactivate 不可
# ----------------------------------------------------------------------


def test_cannot_deactivate_last_super_admin(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """allowed_users 上に他に active super がいない状況で other を
    deactivate しようとすると 400。

    handler の `_count_active_super_admins(exclude_email=email)` は
    allowed_users コレクションをスキャンするため、authentication 経由で
    認可を通している super@ は数に入らない。other を exclude して残る
    super がゼロなら 400。
    """
    fake_db.collection("allowed_users")._docs["other@example.com"] = {
        "email": "other@example.com",
        "role": "admin",
        "active": True,
    }
    res = as_super.patch(
        "/api/admin/users/other@example.com",
        json={"active": False},
    )
    assert res.status_code == 400
    assert "super-admin" in res.json()["detail"]


def test_can_deactivate_non_last_super_admin(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """allowed_users 上に他にも active super がいれば deactivate できる。"""
    fake_db.collection("allowed_users")._docs.update(
        {
            "other@example.com": {
                "email": "other@example.com",
                "role": "admin",
                "active": True,
            },
            "third@example.com": {
                "email": "third@example.com",
                "role": "admin",
                "active": True,
            },
        }
    )
    res = as_super.patch(
        "/api/admin/users/other@example.com",
        json={"active": False},
    )
    assert res.status_code == 200
    assert res.json()["active"] is False


def test_can_deactivate_non_admin_when_only_one_super(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """super が 1 人しかいなくても、非 super (member) なら deactivate OK。"""
    fake_db.collection("allowed_users")._docs.update(
        {
            "super@example.com": {
                "email": "super@example.com",
                "role": "admin",
                "active": True,
            },
            "bob@example.com": {
                "email": "bob@example.com",
                "role": "member",
                "active": True,
            },
        }
    )
    res = as_super.patch(
        "/api/admin/users/bob@example.com",
        json={"active": False},
    )
    assert res.status_code == 200


# ----------------------------------------------------------------------
# user から最後の team を外せない
# ----------------------------------------------------------------------


def test_cannot_remove_last_team(as_super: TestClient, fake_db: FakeDB) -> None:
    """bob は teamA だけ所属。teamA を外そうとすると 400。"""
    fake_db.collection("allowed_users")._docs["bob@example.com"] = {
        "email": "bob@example.com",
        "role": "member",
        "teams": [{"team_id": "teamA", "role": "member"}],
        "default_team": "teamA",
        "active": True,
    }
    res = as_super.delete("/api/admin/users/bob@example.com/teams/teamA")
    assert res.status_code == 400
    assert "last team" in res.json()["detail"]


def test_can_remove_non_last_team(as_super: TestClient, fake_db: FakeDB) -> None:
    """alice は teamA+teamB 所属。teamB を外しても残るので OK。"""
    fake_db.collection("allowed_users")._docs["alice@example.com"] = {
        "email": "alice@example.com",
        "role": "member",
        "teams": [
            {"team_id": "teamA", "role": "member"},
            {"team_id": "teamB", "role": "member"},
        ],
        "default_team": "teamA",
        "active": True,
    }
    res = as_super.delete("/api/admin/users/alice@example.com/teams/teamB")
    assert res.status_code == 200
    team_ids = {t["team_id"] for t in res.json()["teams"]}
    assert team_ids == {"teamA"}


def test_remove_default_team_switches_to_first_remaining(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """default_team を消したら、残った teams の先頭が新しい default_team になる。"""
    fake_db.collection("allowed_users")._docs["alice@example.com"] = {
        "email": "alice@example.com",
        "role": "member",
        "teams": [
            {"team_id": "teamA", "role": "member"},
            {"team_id": "teamB", "role": "member"},
        ],
        "default_team": "teamA",  # ← これを外す
        "active": True,
    }
    res = as_super.delete("/api/admin/users/alice@example.com/teams/teamA")
    assert res.status_code == 200
    assert res.json()["default_team"] == "teamB"


# ----------------------------------------------------------------------
# 既存 active user の再 approve は 409
# ----------------------------------------------------------------------


def test_approve_already_active_user_conflict(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """active 状態の既存 user を approve しようとすると 409。
    team 追加は別 endpoint (POST /users/{email}/teams) を使うべき。"""
    fake_db.collection("teams")._docs["teamA"] = {"name": "Team A"}
    fake_db.collection("allowed_users")._docs["existing@example.com"] = {
        "email": "existing@example.com",
        "role": "member",
        "teams": [{"team_id": "teamA", "role": "member"}],
        "active": True,
    }
    res = as_super.post(
        "/api/admin/approve",
        json={
            "email": "existing@example.com",
            "action": "assign",
            "team_id": "teamA",
            "role": "member",
        },
    )
    assert res.status_code == 409
    assert "team-add" in res.json()["detail"]
