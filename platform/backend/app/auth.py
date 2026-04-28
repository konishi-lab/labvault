"""Firebase ID token 認証 + allowed_users ホワイトリスト。

設計:
- Firebase ID token を Authorization: Bearer で受取、firebase-admin で検証
- allowed_users/{email} を Firestore から引き、active=True をチェック
- role ("admin" | "member" | "viewer") を User に詰めて handler に渡す
- 開発時は LABVAULT_DEV_SKIP_AUTH=1 で検証スキップ可 (ローカル開発のみ)
- 初回ログイン時は uid / last_login_at / display_name を自動更新
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Any

import firebase_admin
from fastapi import Depends, Header, HTTPException, status
from firebase_admin import auth as fb_auth
from firebase_admin import credentials

logger = logging.getLogger(__name__)

_initialized = False


def init_firebase_admin() -> None:
    """firebase-admin SDK を一度だけ初期化する。ADC を使うのでキー不要。"""
    global _initialized
    if _initialized:
        return
    from labvault.core.config import Settings

    project_id = os.environ.get("LABVAULT_GCP_PROJECT") or Settings().gcp_project
    if not project_id:
        msg = "LABVAULT_GCP_PROJECT is required for Firebase auth"
        raise RuntimeError(msg)
    firebase_admin.initialize_app(
        credentials.ApplicationDefault(),
        {"projectId": project_id},
    )
    _initialized = True
    logger.info("firebase-admin initialized for project=%s", project_id)


@dataclass(frozen=True)
class AuthenticatedUser:
    """Firebase / Google OAuth トークン検証のみ通った状態のユーザー。

    allowed_users 照合は未実施。サインアップ申請 (`/api/auth/request-access`) のように
    「ログインはしたがまだ認可されていない」ユーザーを受けるエンドポイント用。
    """

    uid: str
    email: str
    display_name: str


@dataclass(frozen=True)
class User:
    """認証 + 認可済ユーザー。handler では Depends(current_user) で受け取る。

    teams: ((team_id, role), ...) のタプル。default_team は header 未指定時の既定。
    role は legacy (allowed_users.role)、teams[].role が新しい team 単位 role。
    """

    uid: str
    email: str
    display_name: str
    role: str  # legacy admin | member | viewer (post-migration は teams[].role を使う)
    teams: tuple[tuple[str, str], ...] = ()
    default_team: str = ""

    def has_team(self, team_id: str) -> bool:
        return any(t == team_id for t, _ in self.teams)

    def role_in(self, team_id: str) -> str | None:
        for t, r in self.teams:
            if t == team_id:
                return r
        return None


def _firestore_db() -> Any:
    """Firestore client を取得する。allowed_users / teams の参照に使う。"""
    from .dependencies import get_firestore_db

    return get_firestore_db()


def allowed_users_ref() -> Any:
    """allowed_users コレクション参照。"""
    return _firestore_db().collection("allowed_users")


def pending_users_ref() -> Any:
    """pending_users コレクション参照。サインアップ申請の保管場所。"""
    return _firestore_db().collection("pending_users")


def _dev_skip() -> bool:
    return os.environ.get("LABVAULT_DEV_SKIP_AUTH") == "1"


def _verify_google_access_token(token: str) -> dict[str, Any] | None:
    """Google OAuth access token を userinfo で検証する。

    SDK/CLI の ADC 由来 access token を受け入れるための fallback。
    成功時は {"email", "sub", "name", "email_verified", ...} を返す。
    service account の access token は email_verified が False だが、
    allowed_users に SA email が登録されていれば通す (後段の判定)。
    """
    import httpx

    try:
        resp = httpx.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    data: dict[str, Any] = resp.json()
    if not data.get("email"):
        return None
    # Service account token には email_verified が無い (or False)。
    # allowed_users に SA email が登録済みであれば信頼する、という運用にする。
    data.setdefault("email_verified", True)
    return data


def current_authenticated_user(
    authorization: str | None = Header(default=None),
) -> AuthenticatedUser:
    """Firebase / Google OAuth トークンのみ検証する (allowed_users は見ない)。

    サインアップ申請のように、まだ allowed_users に登録されていないユーザーを
    受けるエンドポイント用。通常の handler は `current_user` を使うこと。
    """
    if _dev_skip():
        return AuthenticatedUser(
            uid="dev",
            email="dev@local",
            display_name="dev",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    init_firebase_admin()
    token = authorization.removeprefix("Bearer ").strip()

    # 1) Firebase ID token として検証 (Web UI)
    # 2) 失敗したら Google OAuth access token として検証 (SDK/CLI の ADC)
    try:
        decoded = fb_auth.verify_id_token(token)
        email = decoded.get("email")
        uid = decoded["uid"]
        name = decoded.get("name") or email or uid
        email_verified = decoded.get("email_verified", False)
    except Exception as fb_err:
        info = _verify_google_access_token(token)
        if info is None:
            logger.warning("token verification failed: firebase=%s", fb_err)
            raise HTTPException(
                status_code=401, detail="Token verification failed"
            ) from fb_err
        email = info["email"]
        uid = info["sub"]
        name = info.get("name") or email or uid
        email_verified = info.get("email_verified", False)

    if not email or not email_verified:
        raise HTTPException(status_code=403, detail="Email not verified")

    return AuthenticatedUser(uid=uid, email=email, display_name=name)


def current_user(
    auth_user: AuthenticatedUser = Depends(current_authenticated_user),
) -> User:
    """Firebase token + allowed_users 照合を通した User を返す。

    通常の handler はこれを使う。allowed_users 未登録なら 403。
    """
    # 開発用スキップ
    if _dev_skip():
        return User(
            uid="dev",
            email="dev@local",
            display_name="dev",
            role="admin",
            teams=(("konishi-lab", "admin"),),
            default_team="konishi-lab",
        )

    email = auth_user.email
    uid = auth_user.uid
    name = auth_user.display_name

    # allowed_users 照合（email を doc id に使用）
    doc = allowed_users_ref().document(email).get()
    if not doc.exists:
        raise HTTPException(status_code=403, detail=f"{email} is not allowed")

    data = doc.to_dict() or {}
    if not data.get("active", True):
        raise HTTPException(status_code=403, detail=f"{email} is deactivated")

    role = data.get("role", "member")
    teams_raw = data.get("teams") or []
    teams_tuple: tuple[tuple[str, str], ...] = tuple(
        (t["team_id"], t.get("role", "member"))
        for t in teams_raw
        if isinstance(t, dict) and t.get("team_id")
    )
    default_team = data.get("default_team") or ""
    if not teams_tuple:
        # マイグレーション前 / 整合性が崩れた場合のフォールバック。
        raise HTTPException(
            status_code=403,
            detail=f"{email} has no team assignment",
        )
    if not default_team:
        default_team = teams_tuple[0][0]

    # 初回ログインの uid / last_login_at を補完
    patch: dict[str, Any] = {"last_login_at": dt.datetime.now(dt.UTC)}
    if not data.get("uid"):
        patch["uid"] = uid
    if not data.get("display_name"):
        patch["display_name"] = name
    allowed_users_ref().document(email).set(patch, merge=True)

    return User(
        uid=uid,
        email=email,
        display_name=name,
        role=role,
        teams=teams_tuple,
        default_team=default_team,
    )


def require_super_admin(user: User = Depends(current_user)) -> User:
    """super-admin (allowed_users.role == 'admin') のみ通す。

    将来 team-scoped admin (teams[].role == 'admin') を導入する場合は
    `require_team_admin(team_id)` を別途追加する想定。
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="super-admin role required",
        )
    return user


def current_team(
    user: User = Depends(current_user),
    x_labvault_team: str | None = Header(default=None, alias="X-Labvault-Team"),
) -> str:
    """リクエストの team context を解決する。

    優先順位: X-Labvault-Team header → user.default_team。
    user.teams に含まれない team は 403。
    """
    requested = (x_labvault_team or user.default_team or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="team is required")
    if not user.has_team(requested):
        raise HTTPException(
            status_code=403,
            detail=f"user has no access to team {requested!r}",
        )
    return requested


def get_lab(team: str = Depends(current_team)) -> Any:
    """FastAPI dep: 現在のリクエストの team で Lab を返す。

    handler では `lab: Lab = Depends(get_lab)` と書く。
    Lab は team 単位でキャッシュされる。
    """
    from .dependencies import get_lab_for_team

    return get_lab_for_team(team)


def require_role(*allowed_roles: str) -> Any:
    """role ベースのアクセス制御デコレータ。

    使い方:
        @router.post("/xxx")
        def handler(user: User = Depends(require_role("admin"))):
            ...
    """

    def _dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"role '{user.role}' not in {list(allowed_roles)}",
            )
        return user

    return _dep
