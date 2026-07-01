"""2026-07-01: 親 record に付いた ``shares`` を子孫 record にも継承する。

前提: `permissions.can_read` / `can_analyze` に ``lab`` kwarg を追加、
渡された場合は直接 ``shares`` に無い user でも祖先を辿って権限判定する。

このテストは in-memory backend で lab を組み、record chain
(parent -> child -> grandchild) を作って各シナリオを確認する。
`test_record_shares.py` の fixture 構造を踏襲。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from app.auth import User, current_user
from app.main import app
from app.permissions import (
    _MAX_PARENT_DEPTH,
    can_analyze,
    can_grant,
    can_read,
)
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)

# --- Lab fixture (test_record_shares.py と同じ pattern) ---


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


def _user(*, email: str, teams: list[tuple[str, str]], role: str = "member") -> User:
    return User(
        uid=f"uid-{email}",
        email=email,
        display_name=email.split("@")[0],
        role=role,
        teams=tuple(teams),
        default_team=teams[0][0] if teams else "",
    )


def _bob() -> User:
    return _user(email="bob@b.com", teams=[("teamB", "member")])


def _charlie() -> User:
    return _user(email="charlie@c.com", teams=[("teamC", "member")])


# --- 直接 can_read / can_analyze の unit test ------------------------------


def _make_parent_and_child(
    lab: Lab, *, shares: dict[str, str] | None = None
) -> tuple[Any, Any]:
    """teamA の parent + child (parent.sub 経由) を作る。"""
    parent = lab.new("parent", auto_log=False, created_by="owner@a.com")
    if shares:
        for email, role in shares.items():
            parent.grant_share(email, role)
    child = parent.sub("child", created_by="owner@a.com")
    return parent, child


def test_child_inherits_parent_viewer_share(lab: Lab) -> None:
    """親に bob:viewer を付けると、子は bob から直接読める。"""
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "viewer"})
    assert can_read(_bob(), child, lab=lab) is True
    # analyze は viewer なので False
    assert can_analyze(_bob(), child, lab=lab) is False


def test_child_inherits_parent_analyst_share(lab: Lab) -> None:
    """親に bob:analyst を付けると、子で bob は read + analyze 両方できる。"""
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "analyst"})
    assert can_read(_bob(), child, lab=lab) is True
    assert can_analyze(_bob(), child, lab=lab) is True


def test_grandchild_inherits_via_multi_hop(lab: Lab) -> None:
    """孫まで継承が届く。"""
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "analyst"})
    grandchild = child.sub("grandchild", created_by="owner@a.com")
    assert can_read(_bob(), grandchild, lab=lab) is True
    assert can_analyze(_bob(), grandchild, lab=lab) is True


def test_third_party_still_denied(lab: Lab) -> None:
    """親が bob に共有されていても、無関係な charlie は読めない。"""
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "viewer"})
    assert can_read(_charlie(), child, lab=lab) is False
    assert can_analyze(_charlie(), child, lab=lab) is False


def test_explicit_child_downgrade_takes_precedence(lab: Lab) -> None:
    """親=analyst でも子が明示的に viewer で bob を持てば analyze 不可。

    子の shares に user email エントリがある場合は継承より優先。
    「特定の子だけ role を下げる」の運用を可能にする。
    """
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "analyst"})
    child.grant_share("bob@b.com", "viewer")
    assert can_read(_bob(), child, lab=lab) is True
    assert can_analyze(_bob(), child, lab=lab) is False


def test_no_inheritance_without_lab(lab: Lab) -> None:
    """lab を渡さない旧経路は継承しない (後方互換フォールバック)。"""
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "viewer"})
    # lab 未指定 → 親を辿らない → False
    assert can_read(_bob(), child) is False


def test_grant_and_edit_not_inherited(lab: Lab) -> None:
    """継承するのは read / analyze のみ。grant / edit は継承しない。"""
    from app.permissions import can_edit

    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "analyst"})
    # bob は親 analyst 共有だが、子の再共有 (grant) はできない
    assert can_grant(_bob(), child) is False
    # 子の edit (タイトル/タグ変更) もできない
    assert can_edit(_bob(), child) is False


def test_share_link_scope_ignores_inheritance(lab: Lab) -> None:
    """share-link token user は record 1 本固定。子孫継承は起きない。"""
    from app.auth import ShareLinkScope

    parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "analyst"})
    # bob が share-link token 経由で parent scope を持つ。
    bob_with_scope = User(
        uid="uid-bob-token",
        email="bob@b.com",
        display_name="bob",
        role="member",
        teams=(),
        default_team="",
        share_link_scope=ShareLinkScope(
            record_id=parent.id, team="teamA", role="analyst"
        ),
    )
    # parent は scope match → True
    assert can_read(bob_with_scope, parent, lab=lab) is True
    # child は scope mismatch → False (継承は使われない)
    assert can_read(bob_with_scope, child, lab=lab) is False
    assert can_analyze(bob_with_scope, child, lab=lab) is False


def test_cycle_protection(lab: Lab, monkeypatch: pytest.MonkeyPatch) -> None:
    """parent_id が循環 (A→B→A) しても無限ループしない。

    通常は Record 側で防いでいるが、壊れた state (直接 backend を書き換えた
    等) でも構造的に落ちない ``seen`` set ガードを検証する。
    """
    from app.permissions import _walk_parents

    a = lab.new("a", auto_log=False, created_by="owner@a.com")
    b = a.sub("b", created_by="owner@a.com")
    # 直接内部フィールドを書き換えて A → B の循環を作る
    a._parent_id = b.id
    a._persist()

    walked = list(_walk_parents(lab, a))
    # A → B → A で seen ガードが働き、chain 長は _MAX_PARENT_DEPTH 未満で
    # 必ず終わる
    assert len(walked) < _MAX_PARENT_DEPTH


def test_broken_parent_chain(lab: Lab) -> None:
    """parent_id が存在しない ID を指していても例外にせず継承を諦める。"""
    from app.permissions import _walk_parents

    orphan = lab.new("orphan", auto_log=False, created_by="owner@a.com")
    orphan._parent_id = "NOPE99"  # 存在しない ID
    orphan._persist()
    walked = list(_walk_parents(lab, orphan))
    assert walked == []
    # 継承経路が無い bob は普通に read 不可
    assert can_read(_bob(), orphan, lab=lab) is False


# --- HTTP 経路 (get_children endpoint) の統合テスト -----------------------


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


def test_get_child_endpoint_inherits_share(
    client: TestClient, lab: Lab
) -> None:
    """/api/records/{child_id}: 親のみ bob に viewer 共有 → 子も 200 を返す。"""
    _parent, child = _make_parent_and_child(lab, shares={"bob@b.com": "viewer"})

    c = _as(client, _bob)
    res = c.get(f"/api/records/{child.id}", headers=_hdrs())
    assert res.status_code == 200, res.json()


def test_children_list_inherits_share(client: TestClient, lab: Lab) -> None:
    """/api/records/{parent}/children: bob は viewer 共有継承で全 child 見える。"""
    parent = lab.new("parent", auto_log=False, created_by="owner@a.com")
    parent.grant_share("bob@b.com", "viewer")
    child1 = parent.sub("child1", created_by="owner@a.com")
    child2 = parent.sub("child2", created_by="owner@a.com")

    c = _as(client, _bob)
    res = c.get(f"/api/records/{parent.id}/children", headers=_hdrs())
    assert res.status_code == 200
    body = res.json()
    ids = {item["id"] for item in body["items"]}
    assert ids == {child1.id, child2.id}


def test_children_list_third_party_still_empty(
    client: TestClient, lab: Lab
) -> None:
    """他人 (charlie) は親も子も見えない (親 404, children も 404)。"""
    parent = lab.new("parent", auto_log=False, created_by="owner@a.com")
    parent.grant_share("bob@b.com", "viewer")
    parent.sub("child1", created_by="owner@a.com")

    c = _as(client, _charlie)
    res = c.get(f"/api/records/{parent.id}/children", headers=_hdrs())
    # parent 自体が読めない → uniform 404
    assert res.status_code == 404
