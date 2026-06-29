"""Firebase ID token 認証 + allowed_users ホワイトリスト。

設計:
- Authorization: Bearer の token を 3 通りで検証 (順に試行):
    1. PAT (lv_*) — Firestore tokens collection を hash で lookup
    2. Firebase ID token — firebase-admin で verify
    3. Google OAuth access token — userinfo endpoint 経由
- allowed_users/{email} を Firestore から引き、active=True をチェック
- role ("admin" | "member" | "viewer") を User に詰めて handler に渡す
- 開発時は LABVAULT_DEV_SKIP_AUTH=1 で検証スキップ可 (ローカル開発のみ)
- 初回ログイン時は uid / last_login_at / display_name を自動更新
"""

from __future__ import annotations

import datetime as dt
import hashlib
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
class ShareLinkScope:
    """S1 Phase 2: share-link token 認証で得た「1 record + 1 role」のスコープ。

    User に attach されると、その user はこの 1 record 以外には何もできない。
    permissions.py がこの scope を見て can_read / can_analyze を判定する。
    """

    record_id: str
    role: str  # "viewer" | "analyst"
    team: str  # record owner team (header 検証用 / observability 用)


@dataclass(frozen=True)
class User:
    """認証 + 認可済ユーザー。handler では Depends(current_user) で受け取る。

    teams: ((team_id, role), ...) のタプル。default_team は header 未指定時の既定。
    role は legacy (allowed_users.role)、teams[].role が新しい team 単位 role。

    S1 Phase 2: ``share_link_scope`` が set されている場合、この user は
    record 1 本だけにアクセス可能な「外部 token」モード。team membership は
    持たない (= teams=()). audit 用の email / display_name は pseudo identity。
    """

    uid: str
    email: str
    display_name: str
    role: str  # legacy admin | member | viewer (post-migration は teams[].role を使う)
    teams: tuple[tuple[str, str], ...] = ()
    default_team: str = ""
    share_link_scope: ShareLinkScope | None = None

    def has_team(self, team_id: str) -> bool:
        return any(t == team_id for t, _ in self.teams)

    def role_in(self, team_id: str) -> str | None:
        for t, r in self.teams:
            if t == team_id:
                return r
        return None

    @property
    def is_share_link_user(self) -> bool:
        """share-link token 経由で認証された user か。"""
        return self.share_link_scope is not None


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


def tokens_ref() -> Any:
    """tokens コレクション参照。PAT (Personal Access Token) の保管場所。"""
    return _firestore_db().collection("tokens")


PAT_PREFIX = "lv_"
SHARE_LINK_PREFIX = "ls_"


def _verify_share_link(token: str) -> User | None:
    """S1 Phase 2: share-link token (``ls_*``) を検証する。

    - token_hash で ``shared_links`` collection を引く
    - 有効期限切れ / revoke 済みは弾く
    - 成功時は pseudo identity + ``share_link_scope`` を持った User を返す
      (= 通常の ``current_user`` フローを bypass し、handler では普通の
      User として扱える。``permissions.py`` が scope を見て認可する)

    raw token は保存していないので、SHA-256 hash で lookup する (PAT と同じ)。
    """
    if not token.startswith(SHARE_LINK_PREFIX):
        return None

    from .dependencies import get_share_link_store
    from .share_links import hash_token

    token_hash = hash_token(token)
    store = get_share_link_store()
    link = store.get_by_hash(token_hash)
    if link is None or not link.is_active():
        return None

    # S1-OBS9 hot-fix (2026-06-29): best-effort で last_used_at を更新。
    # PAT の `_verify_pat` と同じパターン (ここで失敗しても auth は通す)。
    try:
        store.touch_last_used(token_hash, at=dt.datetime.now(dt.UTC))
    except Exception:  # noqa: BLE001 — auth path を切らない
        logger.warning(
            "failed to update last_used_at for share-link", exc_info=True
        )

    scope = ShareLinkScope(
        record_id=link.record_id,
        role=link.role,
        team=link.team,
    )
    # share-link user は allowed_users 照合を経由しない (外部協力者で
    # team membership が無いのが前提)。teams=() / role="" / default_team=team
    # にして、handler から見ると「特定 team の record にだけアクセス可能な
    # 不思議な user」になる。`current_team_for_shared_access` は header の
    # team を 200 で通すので、frontend は X-Labvault-Team: <owner-team> を
    # 必ず付けて投げる。
    return User(
        uid=f"share-link:{token_hash[:16]}",
        email=link.pseudo_email,
        display_name=link.pseudo_display_name or link.pseudo_email,
        role="",
        teams=(),
        default_team=link.team,
        share_link_scope=scope,
    )


def _verify_pat(token: str) -> AuthenticatedUser | None:
    """PAT (lv_*) を検証する。失敗時 None。

    raw token は保存していないので、SHA-256 hash で tokens collection を引く。
    検証成功時は last_used_at を best-effort 更新する。
    """
    if not token.startswith(PAT_PREFIX):
        return None
    h = hashlib.sha256(token.encode("utf-8")).hexdigest()
    db = _firestore_db()

    snaps = list(db.collection("tokens").where("token_hash", "==", h).limit(1).stream())
    if not snaps:
        return None
    snap = snaps[0]
    d = snap.to_dict() or {}
    if d.get("revoked_at"):
        return None
    email = d.get("email")
    if not email:
        return None

    # last_used_at 更新は best-effort (失敗しても認証は通す)
    try:
        db.collection("tokens").document(snap.id).update(
            {"last_used_at": dt.datetime.now(dt.UTC)}
        )
    except Exception:
        logger.warning("failed to update last_used_at for token %s", snap.id)

    # uid / display_name は allowed_users から拾えれば拾う (まだ未承認なら email を使う)
    user_snap = allowed_users_ref().document(email).get()
    user_data = (user_snap.to_dict() or {}) if user_snap.exists else {}
    return AuthenticatedUser(
        uid=user_data.get("uid", email),
        email=email,
        display_name=user_data.get("display_name", email),
    )


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

    token = authorization.removeprefix("Bearer ").strip()

    # S1 Phase 2: share-link token (``ls_*``) は ``current_user`` 側で
    # 完全に処理するため、ここでは到達しない (current_user が早期 return)。
    # しかし、サインアップ申請のように ``current_authenticated_user`` を
    # 直接使う path から ``ls_*`` が来た場合は、share-link は allowed_users
    # 概念と無関係なので 401 で弾く方が安全。
    if token.startswith(SHARE_LINK_PREFIX):
        raise HTTPException(
            status_code=401,
            detail="share-link token cannot be used for this endpoint",
        )

    init_firebase_admin()

    # 1) PAT (Personal Access Token) — 我々が発行した lv_* 形式
    if token.startswith(PAT_PREFIX):
        pat_user = _verify_pat(token)
        if pat_user is None:
            raise HTTPException(status_code=401, detail="Invalid PAT")
        return pat_user

    # 2) Firebase ID token として検証 (Web UI)
    # 3) 失敗したら Google OAuth access token として検証 (SDK/CLI の ADC)
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
    authorization: str | None = Header(default=None),
) -> User:
    """Firebase token + allowed_users 照合を通した User を返す。

    通常の handler はこれを使う。allowed_users 未登録なら 403。

    S1 Phase 2: ``Authorization: Bearer ls_*`` の場合は share-link token と
    して **allowed_users 照合を bypass** し、pseudo identity + scope を
    持った User を返す。permissions.py がその scope を見て record 単位で
    認可する。

    本 dep は意図的に ``Depends(current_authenticated_user)`` を使わずに
    Authorization header を直接受ける。FastAPI の Depends は手前で
    評価されるので、``current_authenticated_user`` を Depends すると
    share-link でも一度 Firebase 検証経路に入ってしまうため。
    """
    # S1 Phase 2: share-link 経路は allowed_users 照合をスキップ。
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.removeprefix("Bearer ").strip()
        if raw.startswith(SHARE_LINK_PREFIX):
            link_user = _verify_share_link(raw)
            if link_user is None:
                # S1-OBS2 hot-fix (2026-06-29): 失敗の brute-force 検出 +
                # 監査用に WARNING で 1 行 emit。raw token は
                # ``observability._ShareLinkTokenRedactor`` で自動マスク
                # されるが、念のため hash prefix だけを log に乗せる。
                import hashlib

                from .observability import log_event

                token_hash_prefix = hashlib.sha256(
                    raw.encode("utf-8")
                ).hexdigest()[:8]
                log_event(
                    logger,
                    "share_link.auth_failed",
                    level=logging.WARNING,
                    token_hash_prefix=token_hash_prefix,
                    reason="invalid_or_expired",
                )
                raise HTTPException(
                    status_code=401, detail="Invalid or expired share-link"
                )
            return link_user

    # 通常 token (Firebase / PAT / Google OAuth) は手動で
    # current_authenticated_user を呼ぶ (Depends ではないので Header
    # default の値を明示的に渡す)。
    auth_user = current_authenticated_user(authorization=authorization)
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

    全 team を横断する操作 (pending 承認の create_team, 他 team の global active
    切替など) に使う。team 単位の操作は `require_any_team_admin` +
    `require_team_admin_for` の組み合わせを使う。
    """
    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="super-admin role required",
        )
    return user


def is_super_admin(user: User) -> bool:
    """legacy global admin (allowed_users.role == 'admin')。"""
    return user.role == "admin"


def is_team_admin(user: User, team_id: str) -> bool:
    """指定 team の admin 権限を持つか (super-admin は常に True)。"""
    return is_super_admin(user) or user.role_in(team_id) == "admin"


def is_any_team_admin(user: User) -> bool:
    """super-admin もしくは何らかの team の admin。"""
    return is_super_admin(user) or any(r == "admin" for _, r in user.teams)


def admin_team_ids(user: User) -> tuple[str, ...]:
    """user が admin である team の id 一覧 (super-admin の場合は () = 全 team 相当)。

    呼び出し側で「super-admin なら全件、team admin なら自 team のみ」を
    分岐させるのに使う。
    """
    if is_super_admin(user):
        return ()
    return tuple(t for t, r in user.teams if r == "admin")


def require_team_admin_for(user: User, team_id: str) -> None:
    """team_id の admin でなければ 403。super-admin はバイパス。"""
    if not is_team_admin(user, team_id):
        raise HTTPException(
            status_code=403,
            detail=f"admin role required for team {team_id!r}",
        )


def require_any_team_admin(user: User = Depends(current_user)) -> User:
    """super-admin もしくは何らかの team の admin を要求する FastAPI dep。

    team 一覧 / user 一覧など「どの team の admin でも見てよい」エンドポイントで使う。
    実際の team 絞り込みは handler 側で `admin_team_ids(user)` を使って行う。
    """
    if not is_any_team_admin(user):
        raise HTTPException(
            status_code=403,
            detail="team admin role required",
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


def current_team_for_shared_access(
    user: User = Depends(current_user),
    x_labvault_team: str | None = Header(default=None, alias="X-Labvault-Team"),
) -> str:
    """S1 (PR #84) 共有 record アクセス用の team dep。

    `current_team` は user.has_team(requested) を強制するが、share された
    record の閲覧/解析では **user は team のメンバーではない** ケースが
    発生する。本 dep は team membership を強制せず、handler 側で
    `require_read` / `require_analyze` (`permissions.py`) によって record
    単位で認可を判定させる。

    team が無指定 (header も default_team も無い) のときは 400 を返す
    のは同じ。team の存在自体は handler 側で record 取得時に判明する。
    """
    requested = (x_labvault_team or user.default_team or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="team is required")
    return requested


def get_lab_relaxed(team: str = Depends(current_team_for_shared_access)) -> Any:
    """S1 用: team membership 不問で Lab を取得する。

    handler 側で `require_read` / `require_analyze` を使って record 単位の
    認可を行う必要がある。**直接 `lab.list(...)` / `lab.delete(...)` 等を
    呼ぶ前に必ず record 単位の認可チェックを通すこと**。
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
