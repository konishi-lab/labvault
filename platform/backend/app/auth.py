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
class User:
    """認証済ユーザー。handler では Depends(current_user) で受け取る。"""

    uid: str
    email: str
    display_name: str
    role: str  # admin | member | viewer


def _allowed_users_ref(lab: Any) -> Any:
    """Firestore の allowed_users コレクション参照を返す。

    lab._metadata が FirestoreMetadataBackend の場合のみ動作。
    """
    db = lab._metadata._get_db()
    return db.collection("allowed_users")


def _dev_skip() -> bool:
    return os.environ.get("LABVAULT_DEV_SKIP_AUTH") == "1"


def current_user(
    authorization: str | None = Header(default=None),
) -> User:
    """Authorization: Bearer <id_token> を検証して User を返す。

    FastAPI の Depends から使う。
    """
    # 開発用スキップ
    if _dev_skip():
        return User(
            uid="dev",
            email="dev@local",
            display_name="dev",
            role="admin",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    init_firebase_admin()
    token = authorization.removeprefix("Bearer ").strip()
    try:
        decoded = fb_auth.verify_id_token(token)
    except fb_auth.InvalidIdTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}") from e
    except fb_auth.ExpiredIdTokenError as e:
        raise HTTPException(status_code=401, detail="Token expired") from e
    except Exception as e:
        logger.warning("token verification failed: %s", e)
        raise HTTPException(status_code=401, detail="Token verification failed") from e

    email = decoded.get("email")
    uid = decoded["uid"]
    name = decoded.get("name") or email or uid

    if not email or not decoded.get("email_verified", False):
        raise HTTPException(status_code=403, detail="Email not verified")

    # allowed_users 照合（email を doc id に使用）
    from .dependencies import get_lab

    lab = get_lab()
    doc = _allowed_users_ref(lab).document(email).get()
    if not doc.exists:
        raise HTTPException(status_code=403, detail=f"{email} is not allowed")

    data = doc.to_dict() or {}
    if not data.get("active", True):
        raise HTTPException(status_code=403, detail=f"{email} is deactivated")

    role = data.get("role", "member")

    # 初回ログインの uid / last_login_at を補完
    patch: dict[str, Any] = {"last_login_at": dt.datetime.now(dt.UTC)}
    if not data.get("uid"):
        patch["uid"] = uid
    if not data.get("display_name"):
        patch["display_name"] = name
    _allowed_users_ref(lab).document(email).set(patch, merge=True)

    return User(uid=uid, email=email, display_name=name, role=role)


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
