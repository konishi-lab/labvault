"""admin endpoint の認可境界テスト。

カバー範囲:
- /api/admin/pending (require_super_admin)
- /api/admin/teams  (require_any_team_admin + team admin は自 team のみ)
- /api/admin/users  (require_any_team_admin + team admin は restrict_to で
                     他 team の所属を隠す + 他 team only の user は除外)

期待:
- super-admin → 200 / 全件 / teams[] フル
- team admin → /pending は 403、/teams は 200 で自 team のみ、
              /users は自 team に所属する user のみ & 各 user の
              teams[] は restrict_to で他 team が隠れる
- member → 403
- unauth → 401

future work: /api/admin/approve / users/{email}/teams など。
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


# ----------------------------------------------------------------------
# /api/admin/users  (any team admin; team admin は restrict_to で
#                    他 team の所属を隠す + 他 team only の user は除外)
# ----------------------------------------------------------------------


def _seed_users(fake_db: FakeDB) -> None:
    """3 役のテストユーザーを allowed_users に置く。

    - alice: teamA + teamB
    - bob:   teamA だけ
    - carol: teamB だけ
    """
    _seed_teams(fake_db)
    fake_db.collection("allowed_users")._docs.update(
        {
            "alice@example.com": {
                "email": "alice@example.com",
                "display_name": "Alice",
                "role": "member",
                "teams": [
                    {"team_id": "teamA", "role": "member"},
                    {"team_id": "teamB", "role": "member"},
                ],
                "default_team": "teamA",
                "active": True,
            },
            "bob@example.com": {
                "email": "bob@example.com",
                "display_name": "Bob",
                "role": "member",
                "teams": [{"team_id": "teamA", "role": "member"}],
                "default_team": "teamA",
                "active": True,
            },
            "carol@example.com": {
                "email": "carol@example.com",
                "display_name": "Carol",
                "role": "member",
                "teams": [{"team_id": "teamB", "role": "member"}],
                "default_team": "teamB",
                "active": True,
            },
        }
    )


def test_users_super_sees_all(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_super.get("/api/admin/users")
    assert res.status_code == 200
    items = {u["email"]: u for u in res.json()["items"]}
    assert set(items.keys()) == {
        "alice@example.com",
        "bob@example.com",
        "carol@example.com",
    }
    # super なので alice の teams[] は teamA + teamB 両方残る
    alice_teams = {t["team_id"] for t in items["alice@example.com"]["teams"]}
    assert alice_teams == {"teamA", "teamB"}


def test_users_team_admin_filters_and_restricts(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    _seed_users(fake_db)
    # as_team_admin は teamA admin (conftest の user_team_admin)
    res = as_team_admin.get("/api/admin/users")
    assert res.status_code == 200
    items = {u["email"]: u for u in res.json()["items"]}
    # carol は teamB only なので team admin の視界には入らない
    assert set(items.keys()) == {"alice@example.com", "bob@example.com"}
    # alice の teams[] は restrict_to=teamA で teamB が隠れる
    alice_teams = {t["team_id"] for t in items["alice@example.com"]["teams"]}
    assert alice_teams == {"teamA"}, (
        f"team admin に teamB が漏れてはいけない: {alice_teams}"
    )


def test_users_team_admin_other_sees_disjoint_set(
    as_team_admin_other: TestClient, fake_db: FakeDB
) -> None:
    """teamB admin から見える user は alice (両方所属) + carol (teamB のみ)。
    bob (teamA only) は除外される。"""
    _seed_users(fake_db)
    res = as_team_admin_other.get("/api/admin/users")
    assert res.status_code == 200
    items = {u["email"]: u for u in res.json()["items"]}
    assert set(items.keys()) == {"alice@example.com", "carol@example.com"}
    # alice の teams[] は teamB だけに restrict される
    alice_teams = {t["team_id"] for t in items["alice@example.com"]["teams"]}
    assert alice_teams == {"teamB"}


def test_users_member_403(as_member: TestClient) -> None:
    res = as_member.get("/api/admin/users")
    assert res.status_code == 403


def test_users_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.get("/api/admin/users")
    assert res.status_code == 401
