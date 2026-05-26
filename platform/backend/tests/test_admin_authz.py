"""admin endpoint の認可境界テスト。

カバー範囲 (M0 minimal):
- /api/admin/pending (require_super_admin)
- /api/admin/teams  (require_any_team_admin + team admin は自 team のみ)

期待:
- super-admin → 200 / 全件
- team admin → /pending は 403、 /teams は 200 で自 team のみ
- member → 403
- unauth → 401

future work: /api/admin/users / /api/admin/approve / users/{email}/teams など
の細かい endpoint も同じパターンで追加。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import FakeDB

# ----------------------------------------------------------------------
# /api/admin/pending  (super-admin only)
# ----------------------------------------------------------------------


def test_pending_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    res = as_super.get("/api/admin/pending")
    assert res.status_code == 200
    assert res.json() == {"items": []}


def test_pending_team_admin_403(as_team_admin: TestClient) -> None:
    res = as_team_admin.get("/api/admin/pending")
    assert res.status_code == 403


def test_pending_member_403(as_member: TestClient) -> None:
    res = as_member.get("/api/admin/pending")
    assert res.status_code == 403


def test_pending_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.get("/api/admin/pending")
    assert res.status_code == 401


# ----------------------------------------------------------------------
# /api/admin/teams  (super-admin: all, team admin: own teams only)
# ----------------------------------------------------------------------


def _seed_teams(fake_db: FakeDB) -> None:
    fake_db.collection("teams")._docs.update(
        {
            "teamA": {"name": "Team A"},
            "teamB": {"name": "Team B"},
        }
    )


def test_teams_super_sees_all(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_teams(fake_db)
    res = as_super.get("/api/admin/teams")
    assert res.status_code == 200
    ids = {t["team_id"] for t in res.json()["items"]}
    assert ids == {"teamA", "teamB"}


def test_teams_team_admin_sees_only_own(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    _seed_teams(fake_db)
    res = as_team_admin.get("/api/admin/teams")
    assert res.status_code == 200
    # teamA admin なので teamA だけ見える
    ids = {t["team_id"] for t in res.json()["items"]}
    assert ids == {"teamA"}


def test_teams_member_403(as_member: TestClient) -> None:
    res = as_member.get("/api/admin/teams")
    assert res.status_code == 403


def test_teams_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.get("/api/admin/teams")
    assert res.status_code == 401
