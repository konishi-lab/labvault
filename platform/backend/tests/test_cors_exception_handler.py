"""ハンドラ内の未捕捉例外が CORS ヘッダ付きで返ることの回帰テスト。

CLAUDE.md の既知ハマり「CORS error の真因が 500 のこと」を再発させない。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.main import app
from fastapi.testclient import TestClient

WEB_ORIGIN = "https://labvault-web-355809880738.asia-northeast1.run.app"


@pytest.fixture()
def client_with_500_route(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """既存ルートに通常起こり得ない例外を仕込む。

    `/api/health` ハンドラを差し替えて意図的に raise する。"""

    @app.get("/__test_exception")
    def _raise() -> None:  # pragma: no cover - 例外を出すだけ
        raise RuntimeError("intentional test failure")

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_500_carries_cors_header_when_origin_allowed(
    client_with_500_route: TestClient,
) -> None:
    resp = client_with_500_route.get(
        "/__test_exception", headers={"Origin": WEB_ORIGIN}
    )
    assert resp.status_code == 500
    assert resp.headers.get("access-control-allow-origin") == WEB_ORIGIN
    body = resp.json()
    assert body["detail"] == "internal server error"
    assert body["exception_type"] == "RuntimeError"


def test_500_omits_cors_header_for_unknown_origin(
    client_with_500_route: TestClient,
) -> None:
    """allow_origins に無い Origin には ACAO を付けない (= 通常の CORS 拒否)。"""
    resp = client_with_500_route.get(
        "/__test_exception", headers={"Origin": "https://evil.example.com"}
    )
    assert resp.status_code == 500
    assert "access-control-allow-origin" not in (
        k.lower() for k in resp.headers
    )
