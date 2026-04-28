"""labvault platform API サーバー。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import User, current_team, current_user, init_firebase_admin
from .dependencies import close_lab, get_firestore_db, get_team_meta
from .routers import bulk_upload, files, preview, records, search
from .schemas import HealthResponse
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
def auth_me(user: User = Depends(current_user)) -> dict[str, Any]:
    """現在のユーザー情報を返す。フロントで表示用。

    teams[].name は teams/{team_id}.name から解決する。doc が無い場合は team_id。
    """
    db = get_firestore_db()
    team_names: dict[str, str] = {}
    for team_id, _ in user.teams:
        snap = db.collection("teams").document(team_id).get()
        if snap.exists:
            team_names[team_id] = (snap.to_dict() or {}).get("name") or team_id
        else:
            team_names[team_id] = team_id
    return {
        "uid": user.uid,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "teams": [
            {"team_id": t, "role": r, "name": team_names[t]}
            for t, r in user.teams
        ],
        "default_team": user.default_team,
    }


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
