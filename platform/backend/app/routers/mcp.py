"""MCP Streamable HTTP エンドポイント。

`labvault.mcp.server.create_server()` で構築した FastMCP インスタンスを
``/mcp`` に mount し、Claude Desktop / Code から PAT 認証で直接利用できる
ようにする。

設計メモ: docs/design/mcp_remote_hosting.md
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from labvault import Lab
from labvault.mcp.server import create_server

from ..auth import (
    AuthenticatedUser,
    _verify_pat,
    allowed_users_ref,
)
from ..dependencies import get_lab_for_team

logger = logging.getLogger(__name__)


# per-request にバインドされる context。MCP ツール内 (lab_provider) から参照する。
_request_user: contextvars.ContextVar[AuthenticatedUser | None] = (
    contextvars.ContextVar("labvault_mcp_user", default=None)
)
_request_user_teams: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "labvault_mcp_user_teams", default=()
)
_request_default_team: contextvars.ContextVar[str] = contextvars.ContextVar(
    "labvault_mcp_default_team", default=""
)
_request_team_header: contextvars.ContextVar[str] = contextvars.ContextVar(
    "labvault_mcp_team_header", default=""
)


def _dev_skip() -> bool:
    return os.environ.get("LABVAULT_DEV_SKIP_AUTH") == "1"


def _resolve_user_teams(email: str) -> tuple[tuple[str, ...], str]:
    """allowed_users/{email} から (teams, default_team) を引く。

    `current_user` (auth.py) と同じロジックの subset。MCP は role を見ないので
    teams は team_id のタプルだけ返す。allowed_users 未登録 / active=False は
    `HTTPException(403)`。
    """
    snap = allowed_users_ref().document(email).get()
    if not snap.exists:
        raise HTTPException(status_code=403, detail=f"{email} is not allowed")
    data = snap.to_dict() or {}
    if not data.get("active", True):
        raise HTTPException(status_code=403, detail=f"{email} is deactivated")
    teams_raw = data.get("teams") or []
    teams = tuple(
        t["team_id"] for t in teams_raw if isinstance(t, dict) and t.get("team_id")
    )
    if not teams:
        raise HTTPException(status_code=403, detail=f"{email} has no team assignment")
    default_team = data.get("default_team") or teams[0]
    return teams, default_team


def _lab_provider(team_arg: str | None) -> Lab:
    """MCP ツールから呼ばれる。ツール引数 / ヘッダ / default の順で team を決め、
    認可した上で Lab を返す。"""
    user_teams = _request_user_teams.get()
    if not user_teams:
        # middleware を通っていない (= 想定外の経路で server に到達した)。
        raise RuntimeError("MCP lab_provider called without request context")
    requested = (
        (team_arg or "").strip()
        or _request_team_header.get().strip()
        or _request_default_team.get().strip()
    )
    if not requested:
        raise HTTPException(status_code=400, detail="team is required")
    if requested not in user_teams:
        raise HTTPException(
            status_code=403,
            detail=f"user has no access to team {requested!r}",
        )
    return get_lab_for_team(requested)


def _build_mcp_app() -> ASGIApp:
    """新しい FastMCP Streamable HTTP ASGI app を組む。

    FastMCP の session manager は ``run()`` を 1 度しか呼べないため、lifespan
    が走り直す (テストなど) 度に作り直す必要がある。production の lifecycle
    では 1 回だけ呼ばれる。
    """
    mcp = create_server(lab_provider=_lab_provider, stateless_http=True)
    mcp.settings.streamable_http_path = "/"
    # DNS rebinding 保護のデフォルト (localhost のみ) を Cloud Run でも通すために
    # 緩める。Authorization Bearer で別途認証しているのでホスト制限は不要。
    mcp.settings.transport_security.enable_dns_rebinding_protection = False
    return mcp.streamable_http_app()


class _MutableASGIApp:
    """lifespan 内でセットされた ASGI app に処理を委譲する単純なラッパ。

    middleware 側からは固定の参照に見える一方、内側の app は lifespan の
    出入りで差し替えられる。"""

    def __init__(self) -> None:
        self._app: ASGIApp | None = None

    def set(self, app: ASGIApp | None) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            if scope["type"] == "http":
                await _send_json(
                    send,
                    503,
                    {"error": "MCP server not started (lifespan not entered)"},
                )
                return
            raise RuntimeError("MCP app accessed before lifespan started")
        await self._app(scope, receive, send)


async def _send_json(send: Send, status: int, body: dict[str, Any]) -> None:
    payload = json.dumps(body).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode("ascii")),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload, "more_body": False})


class MCPAuthMiddleware:
    """ASGI middleware: ``Authorization: Bearer lv_*`` を検証し、
    PAT 所有ユーザの teams / default_team を contextvar にバインドする。

    FastAPI の ``Depends`` は mount された外部 ASGI app には適用されないため、
    middleware で直接処理する。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers") or []
        }

        if _dev_skip():
            user = AuthenticatedUser(uid="dev", email="dev@local", display_name="dev")
            teams: tuple[str, ...] = ("konishi-lab",)
            default_team = "konishi-lab"
        else:
            authz = headers.get("authorization", "")
            if not authz.startswith("Bearer "):
                await _send_json(
                    send,
                    401,
                    {"error": "missing Authorization Bearer"},
                )
                return
            token = authz.removeprefix("Bearer ").strip()
            if not token.startswith("lv_"):
                await _send_json(
                    send,
                    401,
                    {"error": "only labvault PAT (lv_*) is accepted on /mcp"},
                )
                return
            user = _verify_pat(token)
            if user is None:
                await _send_json(send, 401, {"error": "invalid PAT"})
                return
            try:
                teams, default_team = _resolve_user_teams(user.email)
            except HTTPException as e:
                await _send_json(send, e.status_code, {"error": e.detail})
                return

        team_header = headers.get("x-labvault-team", "").strip()
        if team_header and team_header not in teams:
            await _send_json(
                send,
                403,
                {"error": f"user has no access to team {team_header!r}"},
            )
            return

        tok_user = _request_user.set(user)
        tok_teams = _request_user_teams.set(teams)
        tok_default = _request_default_team.set(default_team)
        tok_header = _request_team_header.set(team_header)
        try:
            await self.app(scope, receive, send)
        finally:
            _request_user.reset(tok_user)
            _request_user_teams.reset(tok_teams)
            _request_default_team.reset(tok_default)
            _request_team_header.reset(tok_header)


_inner_ref = _MutableASGIApp()
asgi_app: ASGIApp = MCPAuthMiddleware(_inner_ref)
"""``app.mount("/mcp", asgi_app)`` で外部公開する ASGI アプリ。"""


@contextlib.asynccontextmanager
async def lifespan_context() -> AsyncIterator[None]:
    """FastMCP の Streamable HTTP に必要な lifespan context manager。

    外側 (FastAPI app) の lifespan の中で ``async with mcp_router.lifespan_context():``
    で囲うと、session manager の task group が起動し、tool 呼び出しが処理できる
    ようになる (stateless モードでも必須)。
    lifespan の入出りで内部 FastMCP インスタンスを作り直す。これは
    ``StreamableHTTPSessionManager.run()`` が 1 インスタンスあたり 1 回しか
    呼べない制約への対応 (production では lifecycle 1 回なので無関係)。
    """
    mcp_app = _build_mcp_app()
    async with mcp_app.router.lifespan_context(mcp_app):
        _inner_ref.set(mcp_app)
        try:
            yield
        finally:
            _inner_ref.set(None)


__all__ = ["asgi_app", "lifespan_context"]
