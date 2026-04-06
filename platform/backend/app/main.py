"""labvault platform API サーバー。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .dependencies import close_lab, get_lab
from .routers import bulk_upload, files, preview, records, search
from .schemas import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """アプリケーションのライフサイクル管理。"""
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

app.include_router(records.router)
app.include_router(bulk_upload.router)
app.include_router(preview.router)
app.include_router(files.router)
app.include_router(search.router)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """ヘルスチェック。"""
    lab = get_lab()
    return HealthResponse(
        status="ok",
        team=lab._team,
        metadata_backend=type(lab._metadata).__name__,
        storage_backend=type(lab._storage).__name__,
    )
