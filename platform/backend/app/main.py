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
)
from .dependencies import close_lab, get_firestore_db, get_team_meta
from .notifications import notify_signup_request
from .routers import bulk_upload, files, preview, records, search
from .schemas import (
    ApproveRequest,
    ApproveResponse,
    HealthResponse,
    PendingListResponse,
    PendingUser,
    RequestAccessRequest,
    RequestAccessResponse,
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

    認証 (Firebase) のみ通れば 200 を返す。レスポンスの `status` で 3 状態を返す:
      - "authorized": allowed_users 登録済み (teams / default_team を返す)
      - "pending": pending_users にいる (申請中)
      - "unregistered": どちらにもいない (申請フォームへ誘導)

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
                teams_list.append(
                    {"team_id": team_id, "role": role, "name": name}
                )
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
        raise HTTPException(
            status_code=400, detail="requested_team_name is required"
        )

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
            raise HTTPException(
                status_code=400, detail="team_id required for assign"
            )
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

    return ApproveResponse(status="ok", email=email, team_id=target_team)
