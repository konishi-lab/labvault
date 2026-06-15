"""platform/backend のテスト fixture。

方針
----
- `app.dependency_overrides[current_user]` で 4 役 (super / team_admin /
  member / unauth) を切り替える。Firebase token 検証はバイパス。
- Firestore は `_firestore_db` を `FakeDB` で patch。`pending_users` /
  `allowed_users` / `teams` / `tokens` collection を辞書で渡せる。
- 1 テスト = 1 fixture (`as_super` / `as_team_admin` / `as_member` /
  `as_unauth`) で TestClient を取り、後始末 (dependency_overrides.clear)
  も yield 後に行う。

これで admin endpoint の認可境界 (super=全許可、team admin=自 team のみ、
member / unauth=403/401) の回帰を CI で検出できる。
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# firebase-admin 初期化を回避 (テスト中は LABVAULT_DEV_SKIP_AUTH を立てる)。
# 注意: current_user は override で完全に置き換えるため、内部ロジックは
# 一切叩かれない。これは dev_skip の都合ではなく lifespan の
# init_firebase_admin() 呼び出しを止めるためのもの。
os.environ.setdefault("LABVAULT_DEV_SKIP_AUTH", "1")

from app.auth import AuthenticatedUser, User, current_authenticated_user, current_user
from app.main import app

# --------------------------------------------------------------------------
# Fake users (4 roles)
# --------------------------------------------------------------------------


def _user(
    *,
    role: str,
    teams: tuple[tuple[str, str], ...],
    email: str,
    default_team: str = "teamA",
) -> User:
    return User(
        uid=f"uid-{email}",
        email=email,
        display_name=email.split("@")[0],
        role=role,
        teams=teams,
        default_team=default_team,
    )


def user_super() -> User:
    return _user(role="admin", teams=(("teamA", "admin"),), email="super@example.com")


def user_team_admin() -> User:
    """teamA の admin。super-admin ではない。"""
    return _user(role="member", teams=(("teamA", "admin"),), email="ta@example.com")


def user_team_admin_other() -> User:
    """teamB の admin (teamA には member 権限すら無い)。"""
    return _user(
        role="member",
        teams=(("teamB", "admin"),),
        email="tb@example.com",
        default_team="teamB",
    )


def user_member() -> User:
    return _user(role="member", teams=(("teamA", "member"),), email="m@example.com")


def _raise_401() -> User:
    raise HTTPException(status_code=401, detail="not authenticated")


# AuthenticatedUser (allowed_users 未照合) を返す factory。
# `/api/auth/request-access` 等、Firebase 認証のみで通る endpoint 用。
def auth_only_user(
    email: str = "applicant@example.com",
    *,
    display_name: str = "Applicant",
) -> AuthenticatedUser:
    return AuthenticatedUser(
        uid=f"uid-{email}", email=email, display_name=display_name
    )


def auth_only_no_email() -> AuthenticatedUser:
    return AuthenticatedUser(uid="uid-no-email", email="", display_name="anon")


def _raise_401_auth_only() -> AuthenticatedUser:
    raise HTTPException(status_code=401, detail="not authenticated")


# --------------------------------------------------------------------------
# Fake Firestore
# --------------------------------------------------------------------------


class _FakeSnapshot:
    def __init__(self, doc_id: str, data: dict[str, Any] | None) -> None:
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data) if self._data else {}


class _FakeDocRef:
    def __init__(
        self, parent: _FakeCollection, doc_id: str, data: dict[str, Any] | None
    ) -> None:
        self._parent = parent
        self._id = doc_id
        self._data = data

    def get(self) -> _FakeSnapshot:
        return _FakeSnapshot(self._id, self._data)

    def set(self, value: dict[str, Any], merge: bool = False) -> None:
        if merge and self._data:
            self._data.update(value)
        else:
            self._data = dict(value)
        self._parent._docs[self._id] = self._data

    def update(self, patch: dict[str, Any]) -> None:
        if self._data is None:
            self._data = {}
        self._data.update(patch)
        self._parent._docs[self._id] = self._data

    def delete(self) -> None:
        self._parent._docs.pop(self._id, None)


class _FakeCollection:
    def __init__(self, docs: dict[str, dict[str, Any]] | None = None) -> None:
        self._docs: dict[str, dict[str, Any]] = dict(docs or {})

    def document(self, doc_id: str) -> _FakeDocRef:
        return _FakeDocRef(self, doc_id, self._docs.get(doc_id))

    def stream(self) -> Iterator[_FakeSnapshot]:
        for did, data in self._docs.items():
            yield _FakeSnapshot(did, data)


class FakeDB:
    """auth._firestore_db / dependencies.get_firestore_db の戻り値を模した最小実装。"""

    def __init__(self, **collections: dict[str, dict[str, Any]]) -> None:
        self._collections: dict[str, _FakeCollection] = {
            name: _FakeCollection(docs) for name, docs in collections.items()
        }

    def collection(self, name: str) -> _FakeCollection:
        # 未登録 collection は空 collection を返す (stream() で 0 件)。
        return self._collections.setdefault(name, _FakeCollection())


# --------------------------------------------------------------------------
# Pytest fixtures
# --------------------------------------------------------------------------


@pytest.fixture()
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeDB:
    """Firestore client を FakeDB に差し替える。

    `auth._firestore_db` (allowed_users_ref / pending_users_ref / tokens_ref
    / token_history_ref が経由) と `dependencies.get_firestore_db`
    (admin handlers の team 操作で直接使う) の両方を patch する。
    """
    db = FakeDB()
    monkeypatch.setattr("app.auth._firestore_db", lambda: db)
    monkeypatch.setattr("app.dependencies.get_firestore_db", lambda: db)
    monkeypatch.setattr("app.main.get_firestore_db", lambda: db)
    return db


@pytest.fixture(autouse=True)
def stub_artifact_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """approve / add team / patch user は AR (Artifact Registry) を grant/revoke
    する副作用を持つ。テストでは常に成功扱いに固定する。"""
    monkeypatch.setattr("app.main.grant_reader", lambda email: True)
    monkeypatch.setattr("app.main.revoke_reader", lambda email: True)


@pytest.fixture()
def slack_notifications(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`notify_signup_request` の Slack 投稿を握りつぶし、呼び出しを記録する。

    返したリストを assert に使う:
        assert len(slack_notifications) == 1
        assert slack_notifications[0]["email"] == "..."
    """
    calls: list[dict[str, Any]] = []

    def _capture(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("app.main.notify_signup_request", _capture)
    return calls


@pytest.fixture()
def client(fake_db: FakeDB) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _bind(c: TestClient, user_factory: Any) -> TestClient:
    app.dependency_overrides[current_user] = user_factory
    return c


@pytest.fixture()
def as_super(client: TestClient) -> TestClient:
    return _bind(client, user_super)


@pytest.fixture()
def as_team_admin(client: TestClient) -> TestClient:
    return _bind(client, user_team_admin)


@pytest.fixture()
def as_team_admin_other(client: TestClient) -> TestClient:
    return _bind(client, user_team_admin_other)


@pytest.fixture()
def as_member(client: TestClient) -> TestClient:
    return _bind(client, user_member)


@pytest.fixture()
def as_unauth(client: TestClient) -> TestClient:
    return _bind(client, _raise_401)


# --------------------------------------------------------------------------
# Fixtures for AuthenticatedUser-based endpoints (request_access, etc.)
# --------------------------------------------------------------------------


def _bind_authenticated(c: TestClient, factory: Any) -> TestClient:
    app.dependency_overrides[current_authenticated_user] = factory
    return c


@pytest.fixture()
def as_applicant(client: TestClient) -> TestClient:
    """Firebase 認証は通っているが allowed_users 未登録のユーザー。"""
    return _bind_authenticated(client, auth_only_user)


@pytest.fixture()
def as_applicant_no_email(client: TestClient) -> TestClient:
    """email が空 (極めて稀。firebase token に email が無いエッジケース)。"""
    return _bind_authenticated(client, auth_only_no_email)


@pytest.fixture()
def as_unauth_authenticated(client: TestClient) -> TestClient:
    """Firebase 認証自体が通らないユーザー (401)。"""
    return _bind_authenticated(client, _raise_401_auth_only)
