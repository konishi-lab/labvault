"""admin endpoint の認可境界テスト。

カバー範囲:
- /api/admin/pending             (require_super_admin)
- /api/admin/teams               (any team admin; team admin は自 team のみ)
- /api/admin/users               (any team admin; restrict_to で他 team を隠す)
- /api/admin/approve             (assign=対象 team の admin / create_team=super)
- /api/admin/users/{e}/teams     (POST: 追加先 team の admin)
- /api/admin/users/{e}/teams/{t} (DELETE: 対象 team の admin)
- /api/admin/users/{email}       (PATCH: super-admin only)

期待 (共通):
- super-admin → 200 / 全件 / 全許可
- team admin → 自 team に関する操作のみ通る、他 team は 403
- member → 全 endpoint で 403
- unauth → 全 endpoint で 401
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


# ----------------------------------------------------------------------
# /api/admin/approve  (POST)
# - action="assign":     super-admin OR target team の admin
# - action="create_team": super-admin only
# ----------------------------------------------------------------------


def _seed_for_approve(fake_db: FakeDB) -> None:
    """pending_users に 1 件、teamA/B を用意。"""
    _seed_teams(fake_db)
    fake_db.collection("pending_users")._docs.update(
        {
            "dave@example.com": {
                "email": "dave@example.com",
                "display_name": "Dave",
                "requested_team_name": "teamA",
            }
        }
    )


def _assign_body(team_id: str = "teamA") -> dict[str, str]:
    return {
        "email": "dave@example.com",
        "action": "assign",
        "team_id": team_id,
        "role": "member",
    }


def _create_team_body() -> dict[str, object]:
    return {
        "email": "dave@example.com",
        "action": "create_team",
        "role": "member",
        "new_team": {
            "team_id": "teamNew",
            "name": "New Team",
            "nextcloud_group_folder": "large/new",
        },
    }


def test_approve_assign_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_for_approve(fake_db)
    res = as_super.post("/api/admin/approve", json=_assign_body("teamA"))
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["team_id"] == "teamA"
    # pending entry が消えて allowed_users に移行
    assert "dave@example.com" not in fake_db.collection("pending_users")._docs
    assert "dave@example.com" in fake_db.collection("allowed_users")._docs


def test_approve_assign_team_admin_own_ok(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    _seed_for_approve(fake_db)
    # teamA admin が teamA に assign → 通る
    res = as_team_admin.post("/api/admin/approve", json=_assign_body("teamA"))
    assert res.status_code == 200


def test_approve_assign_team_admin_other_403(
    as_team_admin_other: TestClient, fake_db: FakeDB
) -> None:
    _seed_for_approve(fake_db)
    # teamB admin が teamA に assign しようとして弾かれる
    res = as_team_admin_other.post("/api/admin/approve", json=_assign_body("teamA"))
    assert res.status_code == 403


def test_approve_assign_member_403(as_member: TestClient, fake_db: FakeDB) -> None:
    _seed_for_approve(fake_db)
    res = as_member.post("/api/admin/approve", json=_assign_body("teamA"))
    assert res.status_code == 403


def test_approve_assign_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.post("/api/admin/approve", json=_assign_body("teamA"))
    assert res.status_code == 401


def test_approve_create_team_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_for_approve(fake_db)
    res = as_super.post("/api/admin/approve", json=_create_team_body())
    assert res.status_code == 200
    # 新 team が作られて allowed_users に dave が入る
    assert "teamNew" in fake_db.collection("teams")._docs
    assert "dave@example.com" in fake_db.collection("allowed_users")._docs


def test_approve_create_team_team_admin_403(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    _seed_for_approve(fake_db)
    # team admin は create_team を呼べない (super-admin only)
    res = as_team_admin.post("/api/admin/approve", json=_create_team_body())
    assert res.status_code == 403


# ----------------------------------------------------------------------
# /api/admin/users/{email}/teams  (POST)  team 追加
# 認可: super-admin OR 追加先 team の admin
# ----------------------------------------------------------------------


def test_add_team_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    # bob (teamA only) に teamB を追加
    res = as_super.post(
        "/api/admin/users/bob@example.com/teams",
        json={"team_id": "teamB", "role": "member"},
    )
    assert res.status_code == 200
    team_ids = {t["team_id"] for t in res.json()["teams"]}
    assert team_ids == {"teamA", "teamB"}


def test_add_team_admin_of_target_ok(
    as_team_admin_other: TestClient, fake_db: FakeDB
) -> None:
    """teamB admin は bob に teamB を追加できる (追加先の admin だから)。"""
    _seed_users(fake_db)
    res = as_team_admin_other.post(
        "/api/admin/users/bob@example.com/teams",
        json={"team_id": "teamB", "role": "member"},
    )
    assert res.status_code == 200


def test_add_team_admin_of_other_403(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    """teamA admin は bob に teamB を追加できない (teamB の admin ではない)。"""
    _seed_users(fake_db)
    res = as_team_admin.post(
        "/api/admin/users/bob@example.com/teams",
        json={"team_id": "teamB", "role": "member"},
    )
    assert res.status_code == 403


def test_add_team_member_403(as_member: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_member.post(
        "/api/admin/users/bob@example.com/teams",
        json={"team_id": "teamA", "role": "member"},
    )
    assert res.status_code == 403


def test_add_team_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.post(
        "/api/admin/users/bob@example.com/teams",
        json={"team_id": "teamA", "role": "member"},
    )
    assert res.status_code == 401


# ----------------------------------------------------------------------
# /api/admin/users/{email}/teams/{team_id}  (DELETE)  team 削除
# 認可: super-admin OR 対象 team の admin
# ----------------------------------------------------------------------


def test_remove_team_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    # alice (teamA + teamB) から teamB を外す
    res = as_super.delete("/api/admin/users/alice@example.com/teams/teamB")
    assert res.status_code == 200
    team_ids = {t["team_id"] for t in res.json()["teams"]}
    assert team_ids == {"teamA"}


def test_remove_team_admin_of_target_ok(
    as_team_admin_other: TestClient, fake_db: FakeDB
) -> None:
    _seed_users(fake_db)
    res = as_team_admin_other.delete("/api/admin/users/alice@example.com/teams/teamB")
    assert res.status_code == 200


def test_remove_team_admin_of_other_403(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    """teamA admin は alice から teamB を外せない。"""
    _seed_users(fake_db)
    res = as_team_admin.delete("/api/admin/users/alice@example.com/teams/teamB")
    assert res.status_code == 403


def test_remove_team_member_403(as_member: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_member.delete("/api/admin/users/alice@example.com/teams/teamA")
    assert res.status_code == 403


def test_remove_team_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.delete("/api/admin/users/alice@example.com/teams/teamA")
    assert res.status_code == 401


# ----------------------------------------------------------------------
# /api/admin/users/{email}  (PATCH)  — super-admin only
# ----------------------------------------------------------------------


def test_patch_user_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_super.patch(
        "/api/admin/users/bob@example.com",
        json={"display_name": "Bobby"},
    )
    assert res.status_code == 200
    assert res.json()["display_name"] == "Bobby"


def test_patch_user_team_admin_403(as_team_admin: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_team_admin.patch(
        "/api/admin/users/bob@example.com",
        json={"display_name": "Bobby"},
    )
    assert res.status_code == 403


def test_patch_user_member_403(as_member: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_member.patch(
        "/api/admin/users/bob@example.com",
        json={"display_name": "Bobby"},
    )
    assert res.status_code == 403


def test_patch_user_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.patch(
        "/api/admin/users/bob@example.com",
        json={"display_name": "Bobby"},
    )
    assert res.status_code == 401


# ----------------------------------------------------------------------
# /api/admin/users/{email}/ar/grant  (POST)
# 認可: super-admin OR 対象 user の所属 team の admin
# ----------------------------------------------------------------------


def test_ar_grant_super_ok(as_super: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_super.post("/api/admin/users/bob@example.com/ar/grant")
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == "bob@example.com"
    assert body["ar_granted"] is True  # conftest stub で常に True
    # persist 確認: /api/admin/users で ar_granted が返る
    listed = as_super.get("/api/admin/users").json()["items"]
    bob = next(u for u in listed if u["email"] == "bob@example.com")
    assert bob["ar_granted"] is True


def test_ar_grant_team_admin_for_own_team_member_ok(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    """teamA admin は bob (teamA) に対して grant 可。"""
    _seed_users(fake_db)
    res = as_team_admin.post("/api/admin/users/bob@example.com/ar/grant")
    assert res.status_code == 200


def test_ar_grant_team_admin_for_other_team_member_403(
    as_team_admin: TestClient, fake_db: FakeDB
) -> None:
    """teamA admin は carol (teamB only) を触れない。"""
    _seed_users(fake_db)
    res = as_team_admin.post("/api/admin/users/carol@example.com/ar/grant")
    assert res.status_code == 403


def test_ar_grant_member_403(as_member: TestClient, fake_db: FakeDB) -> None:
    _seed_users(fake_db)
    res = as_member.post("/api/admin/users/bob@example.com/ar/grant")
    assert res.status_code == 403


def test_ar_grant_unauth_401(as_unauth: TestClient) -> None:
    res = as_unauth.post("/api/admin/users/bob@example.com/ar/grant")
    assert res.status_code == 401


def test_ar_grant_unknown_user_404(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    _seed_users(fake_db)
    res = as_super.post("/api/admin/users/ghost@example.com/ar/grant")
    assert res.status_code == 404


# ----------------------------------------------------------------------
# Business rules (integrity checks, NOT authorization)
# ----------------------------------------------------------------------
#
# ここでは「権限はあるが整合性を壊す操作」を 400 で弾く挙動を検証する。
#   - 自己 deactivate (誤操作で締め出される)
#   - 最後の active super-admin を deactivate (admin 不在)
#   - 最後の team を remove (team 0 件の user が残る)
#   - DELETE で user に属していない team を指定 (silent no-op しない)


def _seed_users_with_super(fake_db: FakeDB) -> None:
    """super-admin (`super@example.com`) と通常 user 2 名を seed。"""
    _seed_teams(fake_db)
    fake_db.collection("allowed_users")._docs.update(
        {
            "super@example.com": {
                "email": "super@example.com",
                "display_name": "Super",
                "role": "admin",
                "teams": [{"team_id": "teamA", "role": "admin"}],
                "default_team": "teamA",
                "active": True,
            },
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
        }
    )


def test_business_self_deactivate_forbidden(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """super-admin が自分自身を deactivate しようとしたら 400。"""
    _seed_users_with_super(fake_db)
    res = as_super.patch(
        "/api/admin/users/super@example.com",
        json={"active": False},
    )
    assert res.status_code == 400
    assert "yourself" in res.json()["detail"]
    # 状態は変わらない
    assert (
        fake_db.collection("allowed_users")
        ._docs["super@example.com"]["active"]
        is True
    )


def test_business_last_active_super_admin_deactivate_forbidden(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """最後の active super-admin を deactivate しようとしたら 400。

    自己 deactivate は別ルール (上のテスト) で先に弾かれるため、
    「自分以外を deactivate するが、残る admin が 0 になる」状況を作る。
    seed の super@ を **Firestore 上は member に降格** しつつ
    (current_user は admin 持ち合わせの fixture を流用)、もう 1 人の
    admin (super2@) を deactivate しようとする。Firestore 側で role=admin
    が super2@ だけになるので、彼が「最後の active super-admin」になる。
    """
    _seed_users_with_super(fake_db)
    fake_db.collection("allowed_users")._docs.update(
        {
            "super2@example.com": {
                "email": "super2@example.com",
                "display_name": "Super 2",
                "role": "admin",
                "teams": [{"team_id": "teamA", "role": "admin"}],
                "default_team": "teamA",
                "active": True,
            }
        }
    )
    # super (current admin) を Firestore 上で member に降格 → admin は super2 のみ
    fake_db.collection("allowed_users")._docs["super@example.com"]["role"] = (
        "member"
    )

    res = as_super.patch(
        "/api/admin/users/super2@example.com",
        json={"active": False},
    )
    assert res.status_code == 400
    assert "last active super-admin" in res.json()["detail"]
    # 状態は変わらない
    assert (
        fake_db.collection("allowed_users")
        ._docs["super2@example.com"]["active"]
        is True
    )


def test_business_last_team_remove_forbidden(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """team が 1 つしか無い user から最後の team を外そうとしたら 400。"""
    _seed_users_with_super(fake_db)
    # bob は teamA だけ
    res = as_super.delete("/api/admin/users/bob@example.com/teams/teamA")
    assert res.status_code == 400
    assert "deactivate" in res.json()["detail"]
    # bob は teamA に残っている
    bob_teams = fake_db.collection("allowed_users")._docs["bob@example.com"][
        "teams"
    ]
    assert any(t.get("team_id") == "teamA" for t in bob_teams)


def test_business_remove_team_not_member_404(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """user に属していない team を DELETE 指定したら silent no-op せず 404。"""
    _seed_users_with_super(fake_db)
    # bob は teamA だけ
    res = as_super.delete("/api/admin/users/bob@example.com/teams/teamB")
    assert res.status_code == 404
    assert "teamB" in res.json()["detail"]


def test_business_remove_team_reassigns_default(
    as_super: TestClient, fake_db: FakeDB
) -> None:
    """default_team が削除対象だった場合、残った team の先頭に振り替わる。"""
    _seed_users_with_super(fake_db)
    # alice は teamA (default) + teamB の 2 つ所属。teamA を消す。
    res = as_super.delete("/api/admin/users/alice@example.com/teams/teamA")
    assert res.status_code == 200
    body = res.json()
    assert body["default_team"] == "teamB"
    team_ids = {t["team_id"] for t in body["teams"]}
    assert team_ids == {"teamB"}
