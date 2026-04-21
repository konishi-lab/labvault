"""labvault platform API サーバー。"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from fastapi import HTTPException

from .auth import User, current_user, init_firebase_admin
from .dependencies import close_lab, get_lab
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
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
    """ヘルスチェック (認証不要)。"""
    lab = get_lab()
    return HealthResponse(
        status="ok",
        team=lab._team,
        metadata_backend=type(lab._metadata).__name__,
        storage_backend=type(lab._storage).__name__,
    )


@app.get("/api/auth/me")
def auth_me(user: User = Depends(current_user)) -> dict[str, str]:
    """現在のユーザー情報を返す。フロントで表示用。"""
    return {
        "uid": user.uid,
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
    }


@app.get("/api/auth/nextcloud-credentials")
def nextcloud_credentials(user: User = Depends(current_user)) -> dict[str, str]:
    """Nextcloud 接続情報を返す。認証済ユーザーのみアクセス可。

    SDK/装置PC が直接 Nextcloud にアクセスするための共有 app password を
    Secret Manager から取得して配布する。ユーザーを allowed_users から外すと
    このエンドポイントが 403 を返すようになる。

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
    return {
        "url": s.nextcloud_url,
        "username": s.nextcloud_user,
        "password": password,
        "group_folder": s.nextcloud_group_folder,
    }
