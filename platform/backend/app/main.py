"""labvault platform API サーバー。"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import (
    AuthenticatedUser,
    User,
    allowed_users_ref,
    current_authenticated_user,
    current_team,
    current_user,
    init_firebase_admin,
    pending_users_ref,
    require_super_admin,
    tokens_ref,
)
from .artifact_registry import grant_reader, revoke_reader
from .dependencies import close_lab, get_firestore_db, get_team_meta
from .notifications import notify_signup_request
from .routers import bulk_upload, files, preview, records, search
from .schemas import (
    AddTeamRequest,
    AllowedUser,
    ApproveRequest,
    ApproveResponse,
    CreateTokenRequest,
    CreateTokenResponse,
    HealthResponse,
    PendingListResponse,
    PendingUser,
    RequestAccessRequest,
    RequestAccessResponse,
    RevokeTokenResponse,
    TeamListResponse,
    TeamMembershipResponse,
    TeamSummary,
    TokenInfo,
    TokenListResponse,
    UpdateUserRequest,
    UserListResponse,
    UserTeamsResponse,
)
from .secrets_util import get_secret


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """アプリケーションのライフサイクル管理。"""
    # dev skip モードでは firebase-admin を初期化しない
    if os.environ.get("LABVAULT_DEV_SKIP_AUTH") != "1":
        init_firebase_admin()
    yield
    close_lab()


app = FastAPI(
    title="labvault API",
    description="実験データ基盤 REST API",
    version="0.1.0",
    lifespan=lifespan,
)

_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://labvault-web-355809880738.asia-northeast1.run.app",
]
_extra = os.environ.get("LABVAULT_CORS_ORIGINS", "").strip()
if _extra:
    _default_origins.extend(o.strip() for o in _extra.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 認証必須ルータ: 全ハンドラで Firebase ID token + allowed_users を検証
_auth_deps = [Depends(current_user)]
app.include_router(records.router, dependencies=_auth_deps)
app.include_router(bulk_upload.router, dependencies=_auth_deps)
app.include_router(preview.router, dependencies=_auth_deps)
app.include_router(files.router, dependencies=_auth_deps)
app.include_router(search.router, dependencies=_auth_deps)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """ヘルスチェック (認証不要)。team 横断のため lab には触らない。"""
    return HealthResponse(
        status="ok",
        team="",
        metadata_backend="FirestoreMetadataBackend",
        storage_backend="NextcloudStorage",
    )


@app.get("/api/auth/me")
def auth_me(
    auth_user: AuthenticatedUser = Depends(current_authenticated_user),
) -> dict[str, Any]:
    """現在のユーザーの認可状態を返す。

    認証 (Firebase) のみ通れば 200 を返す。レスポンスの `status` で 4 状態を返す:
      - "authorized": allowed_users 登録済み & active (teams / default_team を返す)
      - "deactivated": allowed_users にいるが active=False (admin による無効化)
      - "pending": pending_users にいる (申請中)
      - "unregistered": どこにもいない (申請フォームへ誘導)

    AuthGate がこれで分岐できる。teams[].name は teams/{team_id}.name から解決。
    """
    email = auth_user.email
    db = get_firestore_db()

    allowed_snap = allowed_users_ref().document(email).get()
    if allowed_snap.exists:
        data = allowed_snap.to_dict() or {}
        if data.get("active", True):
            teams_raw = data.get("teams") or []
            teams_list: list[dict[str, str]] = []
            for t in teams_raw:
                if not isinstance(t, dict) or not t.get("team_id"):
                    continue
                team_id = t["team_id"]
                role = t.get("role", "member")
                snap = db.collection("teams").document(team_id).get()
                name = (
                    (snap.to_dict() or {}).get("name") or team_id
                    if snap.exists
                    else team_id
                )
                teams_list.append({"team_id": team_id, "role": role, "name": name})
            default_team = data.get("default_team") or (
                teams_list[0]["team_id"] if teams_list else ""
            )
            return {
                "status": "authorized",
                "uid": data.get("uid", auth_user.uid),
                "email": email,
                "display_name": data.get("display_name") or auth_user.display_name,
                "role": data.get("role", "member"),
                "teams": teams_list,
                "default_team": default_team,
            }
        # active=False: pending / unregistered より優先して deactivated を返す。
        # ユーザーには「admin に連絡してください」を促し、re-apply フォームは出さない。
        return {
            "status": "deactivated",
            "email": email,
            "display_name": data.get("display_name") or auth_user.display_name,
        }

    pending_snap = pending_users_ref().document(email).get()
    if pending_snap.exists:
        d = pending_snap.to_dict() or {}
        return {
            "status": "pending",
            "email": email,
            "display_name": auth_user.display_name,
            "requested_team_name": d.get("requested_team_name", ""),
        }

    return {
        "status": "unregistered",
        "email": email,
        "display_name": auth_user.display_name,
    }


@app.post("/api/auth/request-access", response_model=RequestAccessResponse)
def request_access(
    body: RequestAccessRequest,
    auth_user: AuthenticatedUser = Depends(current_authenticated_user),
) -> RequestAccessResponse:
    """サインアップ申請。

    Firebase 認証は通っているが allowed_users 未登録のユーザーが叩く。
    既存ユーザー (allowed_users 登録済み) が叩いた場合は no-op で
    `already_allowed` を返す。pending_users/{email} に doc を upsert。
    """
    email = auth_user.email
    if not email:
        raise HTTPException(status_code=400, detail="email required")

    requested_name = body.requested_team_name.strip()
    if not requested_name:
        raise HTTPException(status_code=400, detail="requested_team_name is required")

    # 既に allowed_users にいる場合は申請不要
    existing = allowed_users_ref().document(email).get()
    if existing.exists and (existing.to_dict() or {}).get("active", True):
        return RequestAccessResponse(status="already_allowed", email=email)

    note = body.note.strip()
    pending_doc = pending_users_ref().document(email)
    is_new_request = not pending_doc.get().exists
    payload: dict[str, Any] = {
        "email": email,
        "display_name": auth_user.display_name,
        "requester_uid": auth_user.uid,
        "requested_team_name": requested_name,
        "note": note,
        "created_at": dt.datetime.now(dt.UTC),
    }
    pending_doc.set(payload, merge=True)

    # 初回申請のみ Slack 通知 (再送信時の重複通知を避ける)
    if is_new_request:
        notify_signup_request(
            email=email,
            display_name=auth_user.display_name,
            requested_team_name=requested_name,
            note=note,
        )

    return RequestAccessResponse(
        status="pending", email=email, requested_team_name=requested_name
    )


@app.get("/api/auth/nextcloud-credentials")
def nextcloud_credentials(
    user: User = Depends(current_user),
    team: str = Depends(current_team),
) -> dict[str, str]:
    """Nextcloud 接続情報を返す。認証済ユーザー & 所属 team のみアクセス可。

    group_folder は teams/{team_id}.nextcloud_group_folder から取得。
    SDK 側は Settings.team を X-Labvault-Team header に乗せて呼ぶ。

    注: 配布済 password はクライアント側にローカル保存される可能性があるため、
    完全な revoke は Nextcloud Web UI でパスワードをローテーションする必要がある。
    """
    from labvault.core.config import Settings

    password = get_secret("nextcloud-master-password")
    if not password:
        raise HTTPException(
            status_code=500,
            detail="nextcloud-master-password secret is not configured",
        )
    s = Settings()
    meta = get_team_meta(team)
    group_folder = meta.get("nextcloud_group_folder") or s.nextcloud_group_folder
    if not group_folder:
        raise HTTPException(
            status_code=500,
            detail=f"team {team!r} has no nextcloud_group_folder",
        )
    return {
        "url": s.nextcloud_url,
        "username": s.nextcloud_user,
        "password": password,
        "group_folder": group_folder,
    }


# --- Personal Access Tokens (PAT) ---


def _generate_pat() -> tuple[str, str, str]:
    """新しい PAT を生成する。

    Returns:
        (raw_token, sha256_hex, display_prefix)
        raw_token は ``lv_<base32>`` 形式 (~55 chars)。発行時のみ返却。
        sha256_hex は Firestore に保存する hash。
        display_prefix は表示用の先頭部分 (~12 chars)。
    """
    import base64
    import hashlib
    import secrets

    raw_bytes = secrets.token_bytes(32)
    body = base64.b32encode(raw_bytes).decode("ascii").rstrip("=").lower()
    raw = f"lv_{body}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return raw, h, raw[:12]


@app.post("/api/auth/tokens", response_model=CreateTokenResponse)
def create_token(
    body: CreateTokenRequest,
    user: User = Depends(current_user),
) -> CreateTokenResponse:
    """新しい Personal Access Token を発行する。

    raw token はこのレスポンスでのみ返却 (Firestore には hash のみ保存、
    再表示不可)。SDK / curl で `Authorization: Bearer <token>` として使う。
    """
    import uuid

    label = body.label.strip()[:100]
    raw, h, prefix = _generate_pat()
    token_id = uuid.uuid4().hex[:16]
    now = dt.datetime.now(dt.UTC)
    tokens_ref().document(token_id).set(
        {
            "id": token_id,
            "email": user.email,
            "label": label,
            "token_hash": h,
            "prefix": prefix,
            "created_at": now,
            "last_used_at": None,
            "revoked_at": None,
        }
    )
    return CreateTokenResponse(
        id=token_id,
        label=label,
        token=raw,
        prefix=prefix,
        created_at=now,
    )


@app.get("/api/auth/tokens", response_model=TokenListResponse)
def list_tokens(user: User = Depends(current_user)) -> TokenListResponse:
    """ログインユーザーの PAT 一覧を返す (失効済みは除く)。

    raw token は返さない (発行時のみ)。prefix で視覚的に識別する想定。
    """
    items: list[TokenInfo] = []
    for snap in tokens_ref().where("email", "==", user.email).stream():
        d = snap.to_dict() or {}
        if d.get("revoked_at"):
            continue
        items.append(
            TokenInfo(
                id=snap.id,
                label=d.get("label", ""),
                prefix=d.get("prefix", ""),
                created_at=d["created_at"],
                last_used_at=d.get("last_used_at"),
            )
        )
    items.sort(key=lambda t: t.created_at, reverse=True)
    return TokenListResponse(items=items)


@app.delete("/api/auth/tokens/{token_id}", response_model=RevokeTokenResponse)
def revoke_token(
    token_id: str,
    user: User = Depends(current_user),
) -> RevokeTokenResponse:
    """自分の PAT を失効させる。super-admin でも他人の PAT は失効不可。

    soft delete: revoked_at をセットするだけ (履歴を残す)。
    """
    snap = tokens_ref().document(token_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="token not found")
    d = snap.to_dict() or {}
    if d.get("email") != user.email:
        raise HTTPException(status_code=403, detail="not your token")
    if d.get("revoked_at"):
        return RevokeTokenResponse(status="ok", id=token_id)  # 冪等
    tokens_ref().document(token_id).update({"revoked_at": dt.datetime.now(dt.UTC)})
    return RevokeTokenResponse(status="ok", id=token_id)


@app.get("/api/admin/pending", response_model=PendingListResponse)
def admin_pending(
    _admin: User = Depends(require_super_admin),
) -> PendingListResponse:
    """サインアップ申請の一覧を返す。super-admin のみ。"""
    items: list[PendingUser] = []
    for snap in pending_users_ref().stream():
        d = snap.to_dict() or {}
        items.append(
            PendingUser(
                email=d.get("email") or snap.id,
                display_name=d.get("display_name", ""),
                requested_team_name=d.get("requested_team_name", ""),
                note=d.get("note", ""),
                created_at=d.get("created_at"),
            )
        )
    items.sort(key=lambda p: p.created_at or dt.datetime.min, reverse=False)
    return PendingListResponse(items=items)


@app.post("/api/admin/approve", response_model=ApproveResponse)
def admin_approve(
    body: ApproveRequest,
    admin: User = Depends(require_super_admin),
) -> ApproveResponse:
    """申請を承認する。super-admin のみ。

    action="assign": 既存 team に追加。
    action="create_team": 新規 team を作成して追加。
    どちらの場合も pending_users/{email} を削除し、allowed_users/{email} を作成。
    """
    email = body.email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="email required")
    if body.action not in ("assign", "create_team"):
        raise HTTPException(
            status_code=400, detail="action must be 'assign' or 'create_team'"
        )
    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(
            status_code=400, detail="role must be admin / member / viewer"
        )

    # 既に allowed_users にいる場合は別 endpoint (team 追加) を使うべき
    existing = allowed_users_ref().document(email).get()
    if existing.exists and (existing.to_dict() or {}).get("active", True):
        raise HTTPException(
            status_code=409,
            detail=f"{email} is already in allowed_users. Use team-add endpoint.",
        )

    db = get_firestore_db()

    if body.action == "create_team":
        if body.new_team is None:
            raise HTTPException(
                status_code=400, detail="new_team is required for create_team"
            )
        team_id = body.new_team.team_id.strip()
        if not team_id:
            raise HTTPException(status_code=400, detail="team_id required")
        team_ref = db.collection("teams").document(team_id)
        if team_ref.get().exists:
            raise HTTPException(
                status_code=409, detail=f"team {team_id!r} already exists"
            )
        if not body.new_team.nextcloud_group_folder.strip():
            raise HTTPException(
                status_code=400, detail="nextcloud_group_folder required"
            )
        team_ref.set(
            {
                "name": body.new_team.name.strip() or team_id,
                "nextcloud_group_folder": body.new_team.nextcloud_group_folder.strip(),
                "created_at": dt.datetime.now(dt.UTC),
                "created_by": admin.email,
            }
        )
        target_team = team_id
    else:  # assign
        target_team = body.team_id.strip()
        if not target_team:
            raise HTTPException(status_code=400, detail="team_id required for assign")
        if not db.collection("teams").document(target_team).get().exists:
            raise HTTPException(
                status_code=404, detail=f"team {target_team!r} not found"
            )

    # pending entry から display_name を持ってくる
    pending_snap = pending_users_ref().document(email).get()
    pending_data = pending_snap.to_dict() if pending_snap.exists else {}
    display_name = (pending_data or {}).get("display_name", "")

    allowed_users_ref().document(email).set(
        {
            "email": email,
            "display_name": display_name,
            "role": "member",  # legacy global role; team 単位 role は teams[].role
            "teams": [{"team_id": target_team, "role": body.role}],
            "default_team": target_team,
            "active": True,
            "created_at": dt.datetime.now(dt.UTC),
            "created_by": admin.email,
        },
        merge=True,
    )
    if pending_snap.exists:
        pending_users_ref().document(email).delete()

    # AR reader を付与 (LABVAULT_AR_REPO 未設定なら no-op)。
    # 失敗しても承認自体は成功扱い — レスポンスの ar_granted で admin に伝える。
    ar_granted = grant_reader(email)

    return ApproveResponse(
        status="ok", email=email, team_id=target_team, ar_granted=ar_granted
    )


def _team_name_map() -> dict[str, str]:
    """teams collection から {team_id: name} map を作る。"""
    db = get_firestore_db()
    out: dict[str, str] = {}
    for snap in db.collection("teams").stream():
        d = snap.to_dict() or {}
        out[snap.id] = d.get("name") or snap.id
    return out


def _resolve_teams(
    teams_raw: list[dict[str, Any]] | None,
    name_map: dict[str, str],
) -> list[TeamMembershipResponse]:
    """allowed_users.teams[] を name 解決済の response 形式に変換。"""
    out: list[TeamMembershipResponse] = []
    for t in teams_raw or []:
        if not isinstance(t, dict) or not t.get("team_id"):
            continue
        team_id = t["team_id"]
        out.append(
            TeamMembershipResponse(
                team_id=team_id,
                role=t.get("role", "member"),
                name=name_map.get(team_id, team_id),
            )
        )
    return out


@app.get("/api/admin/teams", response_model=TeamListResponse)
def admin_list_teams(
    _admin: User = Depends(require_super_admin),
) -> TeamListResponse:
    """teams collection の全 team を返す。super-admin のみ。

    UI で「既存 team に追加」のドロップダウンを作るのに使う。
    """
    items: list[TeamSummary] = []
    for snap in get_firestore_db().collection("teams").stream():
        d = snap.to_dict() or {}
        items.append(
            TeamSummary(
                team_id=snap.id,
                name=d.get("name", ""),
                nextcloud_group_folder=d.get("nextcloud_group_folder", ""),
            )
        )
    items.sort(key=lambda t: t.team_id)
    return TeamListResponse(items=items)


@app.get("/api/admin/users", response_model=UserListResponse)
def admin_list_users(
    _admin: User = Depends(require_super_admin),
) -> UserListResponse:
    """allowed_users 一覧を返す。super-admin のみ。

    各 user の teams[] には team の表示名 (teams/{team_id}.name) も含める。
    """
    name_map = _team_name_map()
    items: list[AllowedUser] = []
    for snap in allowed_users_ref().stream():
        d = snap.to_dict() or {}
        items.append(
            AllowedUser(
                email=d.get("email") or snap.id,
                display_name=d.get("display_name", ""),
                role=d.get("role", ""),
                teams=_resolve_teams(d.get("teams"), name_map),
                default_team=d.get("default_team", ""),
                active=bool(d.get("active", True)),
                created_at=d.get("created_at"),
                last_login_at=d.get("last_login_at"),
            )
        )
    items.sort(key=lambda u: u.email)
    return UserListResponse(items=items)


@app.post("/api/admin/users/{email}/teams", response_model=UserTeamsResponse)
def admin_add_user_team(
    email: str,
    body: AddTeamRequest,
    _admin: User = Depends(require_super_admin),
) -> UserTeamsResponse:
    """承認済ユーザーに team を追加する。super-admin のみ。

    冪等: 既に所属している team_id を渡した場合は role を上書きする。
    default_team が未設定なら、追加した team を default にする。
    """
    email = email.strip()
    target_team = body.team_id.strip()
    if not target_team:
        raise HTTPException(status_code=400, detail="team_id required")
    if body.role not in ("admin", "member", "viewer"):
        raise HTTPException(
            status_code=400, detail="role must be admin / member / viewer"
        )

    db = get_firestore_db()
    if not db.collection("teams").document(target_team).get().exists:
        raise HTTPException(status_code=404, detail=f"team {target_team!r} not found")

    user_ref = allowed_users_ref().document(email)
    snap = user_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"{email} is not in allowed_users")
    data = snap.to_dict() or {}

    teams_raw = list(data.get("teams") or [])
    found = False
    for t in teams_raw:
        if isinstance(t, dict) and t.get("team_id") == target_team:
            t["role"] = body.role
            found = True
            break
    if not found:
        teams_raw.append({"team_id": target_team, "role": body.role})

    default_team = data.get("default_team") or target_team

    user_ref.set(
        {"teams": teams_raw, "default_team": default_team},
        merge=True,
    )

    # 既存承認以前に作られた user (AR 未付与) の救済も兼ねて grant を呼ぶ。冪等。
    ar_granted = grant_reader(email)

    name_map = _team_name_map()
    return UserTeamsResponse(
        status="ok",
        email=email,
        teams=_resolve_teams(teams_raw, name_map),
        default_team=default_team,
        ar_granted=ar_granted,
    )


@app.delete(
    "/api/admin/users/{email}/teams/{team_id}",
    response_model=UserTeamsResponse,
)
def admin_remove_user_team(
    email: str,
    team_id: str,
    _admin: User = Depends(require_super_admin),
) -> UserTeamsResponse:
    """承認済ユーザーから team を外す。super-admin のみ。

    最後の team を外そうとした場合は 400 (代わりに PATCH /users/{email} で
    deactivate する想定)。
    default_team が削除対象だった場合は残った teams の先頭に振り替える。
    """
    email = email.strip()
    target_team = team_id.strip()
    if not target_team:
        raise HTTPException(status_code=400, detail="team_id required")

    user_ref = allowed_users_ref().document(email)
    snap = user_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"{email} is not in allowed_users")
    data = snap.to_dict() or {}
    teams_raw = list(data.get("teams") or [])
    new_teams = [
        t
        for t in teams_raw
        if not (isinstance(t, dict) and t.get("team_id") == target_team)
    ]
    if len(new_teams) == len(teams_raw):
        raise HTTPException(
            status_code=404,
            detail=f"{email} is not a member of {target_team!r}",
        )
    if not new_teams:
        raise HTTPException(
            status_code=400,
            detail=(
                f"cannot remove last team from {email}. deactivate the user instead."
            ),
        )

    default_team = data.get("default_team") or ""
    if default_team == target_team:
        first = new_teams[0]
        default_team = first.get("team_id", "") if isinstance(first, dict) else ""

    user_ref.set(
        {"teams": new_teams, "default_team": default_team},
        merge=True,
    )

    name_map = _team_name_map()
    return UserTeamsResponse(
        status="ok",
        email=email,
        teams=_resolve_teams(new_teams, name_map),
        default_team=default_team,
    )


def _count_active_super_admins(exclude_email: str | None = None) -> int:
    """role==admin かつ active==True なユーザー数 (exclude_email を除外可)。"""
    n = 0
    for snap in allowed_users_ref().stream():
        if exclude_email and snap.id == exclude_email:
            continue
        d = snap.to_dict() or {}
        if d.get("role") == "admin" and d.get("active", True):
            n += 1
    return n


def _to_allowed_user(snap: Any, name_map: dict[str, str]) -> AllowedUser:
    """allowed_users docsnapshot を AllowedUser に詰め替える。"""
    d = snap.to_dict() or {}
    return AllowedUser(
        email=d.get("email") or snap.id,
        display_name=d.get("display_name", ""),
        role=d.get("role", ""),
        teams=_resolve_teams(d.get("teams"), name_map),
        default_team=d.get("default_team", ""),
        active=bool(d.get("active", True)),
        created_at=d.get("created_at"),
        last_login_at=d.get("last_login_at"),
    )


@app.patch("/api/admin/users/{email}", response_model=AllowedUser)
def admin_update_user(
    email: str,
    body: UpdateUserRequest,
    admin: User = Depends(require_super_admin),
) -> AllowedUser:
    """ユーザーの属性を更新する。super-admin のみ。

    PATCH semantics: body で指定された field のみ更新する。
    現状は active と display_name に対応。

    安全策 (active 更新時のみ):
      - 自己 deactivate は禁止 (誤操作で締め出されるのを防ぐ)
      - 最後の active super-admin の deactivate も禁止 (admin 全員不在を防ぐ)

    副作用 (active 更新時):
      - deactivate → AR reader を revoke
      - reactivate → AR reader を再 grant
      - state 変更が無ければ何もしない (冪等)
    """
    email = email.strip()
    user_ref = allowed_users_ref().document(email)
    snap = user_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"{email} is not in allowed_users")
    data = snap.to_dict() or {}

    patch: dict[str, Any] = {}

    if body.display_name is not None:
        new_name = body.display_name.strip()
        if len(new_name) > 100:
            raise HTTPException(
                status_code=400, detail="display_name is too long (max 100)"
            )
        if new_name != (data.get("display_name") or ""):
            patch["display_name"] = new_name

    if body.active is not None:
        current_active = bool(data.get("active", True))
        if current_active != body.active:
            if not body.active:
                if email == admin.email:
                    raise HTTPException(
                        status_code=400,
                        detail="cannot deactivate yourself. ask another super-admin.",
                    )
                if data.get("role") == "admin":
                    others = _count_active_super_admins(exclude_email=email)
                    if others == 0:
                        raise HTTPException(
                            status_code=400,
                            detail="cannot deactivate the last active super-admin.",
                        )
            patch["active"] = body.active

    if patch:
        user_ref.set(patch, merge=True)
        # active 切替時のみ AR を更新 (display_name 変更だけなら no-op)
        if "active" in patch:
            if patch["active"]:
                grant_reader(email)
            else:
                revoke_reader(email)

    snap = user_ref.get()
    return _to_allowed_user(snap, _team_name_map())
