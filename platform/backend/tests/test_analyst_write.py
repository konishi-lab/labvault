"""S1 Phase 1C: analyst write path の認可境界テスト。

PR #84 (grant/revoke) + PR #85 (shared-with-me) で read 経路が揃った後、
本 Phase で analyst が他チーム record に「解析結果 = 子 record + ファイル」を
書ける経路を解禁する。

検証する書き込み経路:
- ``POST /api/records`` with ``parent_id`` (子 record 作成)
- ``POST /api/records/{id}/files`` (単一ファイル upload)
- ``POST /api/records/{id}/bulk-upload/preview`` + ``POST .../bulk-upload``
  (グリッド一括 upload の preview と本番、両方 ``require_analyze``)

共通シナリオ:
- teamA member が rec1 を作る (本人 owner)
- bob (teamB, analyst 共有) → 子作成 OK / file upload OK
- charlie (teamC, viewer 共有) → 全部 403
- dave (teamD, 共有なし) → 全部 403
- super-admin → 全部 OK
- teamA member 本人 → 全部 OK (回帰なし)

bulk-upload の SSE body は逐次レスポンスなので、本 PR では
preview endpoint だけ詳細にカバー (本番 endpoint は 200 が返れば OK と
する — SSE 中の挙動は別 PR で)。
"""

from __future__ import annotations

import io
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
def parent_id(lab: Lab) -> str:
    """teamA owner が親 record を作り、bob (analyst) / charlie (viewer) に share。"""
    rec = lab.new("parent-experiment", auto_log=False, created_by="owner@a.com")
    rec.grant_share("bob@b.com", "analyst")
    rec.grant_share("charlie@c.com", "viewer")
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


def _bob_analyst() -> User:
    """bob: teamB の member、teamA の parent に analyst で共有されている。"""
    return _user(email="bob@b.com", teams=[("teamB", "member")])


def _charlie_viewer() -> User:
    return _user(email="charlie@c.com", teams=[("teamC", "member")])


def _dave_outsider() -> User:
    """共有されていない第三者。"""
    return _user(email="dave@d.com", teams=[("teamD", "member")])


def _super_admin() -> User:
    return _user(
        email="super@a.com",
        teams=[("teamA", "admin")],
        role="admin",
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


# --- POST /api/records 子 record 作成 ----------------------------------------


def test_owner_can_create_root_record(client: TestClient) -> None:
    """team member は root record (parent_id 無し) を作れる。"""
    c = _as(client, _owner)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={"title": "root-test"},
    )
    assert res.status_code == 201


def test_outsider_cannot_create_root_record(client: TestClient) -> None:
    """team member でない user は root record を作れない (403)。"""
    c = _as(client, _dave_outsider)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={"title": "evil-root"},
    )
    assert res.status_code == 403


def test_analyst_can_create_child_record(
    client: TestClient, parent_id: str
) -> None:
    """analyst 共有されていれば parent_id 指定で子 record を作れる。"""
    c = _as(client, _bob_analyst)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={
            "title": "bob-analysis",
            "parent_id": parent_id,
            "conditions": {"method": "fft"},
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["parent_id"] == parent_id
    assert body["title"] == "bob-analysis"
    # created_by は bob 本人の email が刻まれる (audit 用)
    assert body["created_by"] == "bob@b.com"


def test_viewer_cannot_create_child_record(
    client: TestClient, parent_id: str
) -> None:
    """viewer 共有された user は子 record を作れない (analyst が必要)。"""
    c = _as(client, _charlie_viewer)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={
            "title": "charlie-attempt",
            "parent_id": parent_id,
        },
    )
    assert res.status_code == 403


def test_outsider_cannot_create_child_record(
    client: TestClient, parent_id: str
) -> None:
    """共有されていない user は子 record を作れない。

    S1-SEC6 (PR γ-2): 外部 user は parent を read もできないので、
    存在オラクル防止のため **404** で uniform (旧仕様の 403 から変更)。
    """
    c = _as(client, _dave_outsider)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={
            "title": "dave-attempt",
            "parent_id": parent_id,
        },
    )
    assert res.status_code == 404


def test_team_member_can_create_child_record(
    client: TestClient, parent_id: str
) -> None:
    """team member 本人 (owner) は子 record を作れる (回帰なし)。"""
    c = _as(client, _owner)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={
            "title": "owner-analysis",
            "parent_id": parent_id,
        },
    )
    assert res.status_code == 201
    assert res.json()["created_by"] == "owner@a.com"


def test_super_admin_can_create_child_anywhere(
    client: TestClient, parent_id: str
) -> None:
    c = _as(client, _super_admin)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={"title": "super-analysis", "parent_id": parent_id},
    )
    assert res.status_code == 201


def test_missing_parent_id_returns_404(client: TestClient) -> None:
    """存在しない parent_id を指定すると 404。"""
    c = _as(client, _owner)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={"title": "orphan", "parent_id": "NONEXISTENT"},
    )
    assert res.status_code == 404


# --- 子 record が親⇄子の双方向 link を持つ ---


def test_child_creation_links_parent_and_child(
    client: TestClient, parent_id: str, lab: Lab
) -> None:
    """analyst が作った子 record と親に has_child / child_of の link が張られる。"""
    c = _as(client, _bob_analyst)
    res = c.post(
        "/api/records",
        headers=_hdrs(),
        json={"title": "bob-link-test", "parent_id": parent_id},
    )
    assert res.status_code == 201
    child_id = res.json()["id"]
    parent = lab.get(parent_id)
    child = lab.get(child_id)
    assert any(
        lk.target_id == child_id and lk.relation == "has_child"
        for lk in parent.links
    )
    assert any(
        lk.target_id == parent_id and lk.relation == "child_of"
        for lk in child.links
    )


# --- POST /api/records/{id}/files (単一 upload) -------------------------------


def test_analyst_can_upload_file(
    client: TestClient, parent_id: str
) -> None:
    """analyst 共有された user はファイル upload できる。"""
    c = _as(client, _bob_analyst)
    file_data = ("data.txt", io.BytesIO(b"hello from bob"), "text/plain")
    res = c.post(
        f"/api/records/{parent_id}/files",
        headers=_hdrs(),
        files={"file": file_data},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["updated_by"] == "bob@b.com"
    assert any(f["name"] == "data.txt" for f in body["files"])


def test_viewer_cannot_upload_file(
    client: TestClient, parent_id: str
) -> None:
    c = _as(client, _charlie_viewer)
    file_data = ("evil.txt", io.BytesIO(b"x"), "text/plain")
    res = c.post(
        f"/api/records/{parent_id}/files",
        headers=_hdrs(),
        files={"file": file_data},
    )
    assert res.status_code == 403


def test_outsider_cannot_upload_file(
    client: TestClient, parent_id: str
) -> None:
    """S1-SEC6: outsider は read 不可 → uniform 404 (旧 403)。"""
    c = _as(client, _dave_outsider)
    file_data = ("evil.txt", io.BytesIO(b"x"), "text/plain")
    res = c.post(
        f"/api/records/{parent_id}/files",
        headers=_hdrs(),
        files={"file": file_data},
    )
    assert res.status_code == 404


def test_team_member_can_upload_file(
    client: TestClient, parent_id: str
) -> None:
    """team member 本人は upload できる (回帰)。"""
    c = _as(client, _owner)
    file_data = ("owner-data.bin", io.BytesIO(b"\x00\x01\x02"), "application/octet-stream")
    res = c.post(
        f"/api/records/{parent_id}/files",
        headers=_hdrs(),
        files={"file": file_data},
    )
    assert res.status_code == 201


# --- GET 系 (file list / download) は read 権限 -------------------------------


def test_viewer_can_list_files(client: TestClient, parent_id: str, lab: Lab) -> None:
    """viewer 共有された user はファイル一覧を引ける (S1 Phase 1B 補完)。"""
    # 事前に owner が 1 ファイル置く
    rec = lab.get(parent_id)
    rec.add(b"sample", name="for-charlie.txt")

    c = _as(client, _charlie_viewer)
    res = c.get(f"/api/records/{parent_id}/files", headers=_hdrs())
    assert res.status_code == 200
    items = res.json()
    assert any(f["name"] == "for-charlie.txt" for f in items)


def test_outsider_cannot_list_files(client: TestClient, parent_id: str) -> None:
    """S1-SEC6: outsider は read 不可 → uniform 404 (旧 403)。"""
    c = _as(client, _dave_outsider)
    res = c.get(f"/api/records/{parent_id}/files", headers=_hdrs())
    assert res.status_code == 404


# --- bulk-upload preview ---------------------------------------------------


def test_analyst_can_bulk_upload_preview(
    client: TestClient, parent_id: str, lab: Lab
) -> None:
    """analyst は bulk-upload preview を叩ける。"""
    # 子 record を 2 つ作っておく (preview がマッチさせる対象)
    parent = lab.get(parent_id)
    parent.sub("sub-A1")
    parent.sub("sub-A2")

    c = _as(client, _bob_analyst)
    res = c.post(
        f"/api/records/{parent_id}/bulk-upload/preview",
        headers=_hdrs(),
        json={
            "grid": {
                "rows": 1,
                "cols": 2,
                "start_position": "top-left",
                "direction": "row-first",
            },
            "filenames": ["a.txt", "b.txt"],
        },
    )
    # FastAPI で grid と filenames を別 body params にできるよう既存の
    # endpoint シグネチャに合わせる必要あり (この test が通れば preview の
    # 認可 path は OK)。
    # backend は grid を Body 0、filenames を Body 1 に分けて宣言している
    # ため、JSON ペイロード形式は上記 schema。
    assert res.status_code == 200


def test_viewer_cannot_bulk_upload_preview(
    client: TestClient, parent_id: str, lab: Lab
) -> None:
    parent = lab.get(parent_id)
    parent.sub("sub-V1")
    c = _as(client, _charlie_viewer)
    res = c.post(
        f"/api/records/{parent_id}/bulk-upload/preview",
        headers=_hdrs(),
        json={
            "grid": {
                "rows": 1,
                "cols": 1,
                "start_position": "top-left",
                "direction": "row-first",
            },
            "filenames": ["x.txt"],
        },
    )
    assert res.status_code == 403


def test_outsider_cannot_bulk_upload_preview(
    client: TestClient, parent_id: str
) -> None:
    """S1-SEC6: outsider は read 不可 → uniform 404 (旧 403)。"""
    c = _as(client, _dave_outsider)
    res = c.post(
        f"/api/records/{parent_id}/bulk-upload/preview",
        headers=_hdrs(),
        json={
            "grid": {
                "rows": 1,
                "cols": 1,
                "start_position": "top-left",
                "direction": "row-first",
            },
            "filenames": ["x.txt"],
        },
    )
    assert res.status_code == 404
