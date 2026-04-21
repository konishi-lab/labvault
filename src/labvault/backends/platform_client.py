"""labvault platform API クライアント。

SDK/CLI/MCP が platform 経由で Nextcloud 資格情報等を取得するための薄いラッパー。
認証は GCP ADC の access token を Authorization ヘッダに載せる。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class PlatformClient:
    """labvault platform backend クライアント。

    access_token は ADC から取得しキャッシュする (55分)。
    """

    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._credentials: Any = None
        self._token: str | None = None
        self._token_expiry: float = 0.0
        self._lock = threading.Lock()

    def _get_access_token(self) -> str:
        with self._lock:
            now = time.time()
            if self._token and now < self._token_expiry - 60:
                return self._token
            import google.auth
            import google.auth.transport.requests

            if self._credentials is None:
                self._credentials, _ = google.auth.default(
                    scopes=[
                        "https://www.googleapis.com/auth/userinfo.email",
                        "openid",
                    ]
                )
            request = google.auth.transport.requests.Request()
            self._credentials.refresh(request)
            self._token = self._credentials.token
            # google-auth does not always set expiry on user creds;
            # fall back to 55 分キャッシュ
            exp = getattr(self._credentials, "expiry", None)
            if exp is not None:
                self._token_expiry = exp.timestamp()
            else:
                self._token_expiry = now + 55 * 60
            assert self._token is not None
            return self._token

    def _get(self, path: str) -> dict[str, Any]:
        import httpx

        token = self._get_access_token()
        resp = httpx.get(
            f"{self._url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def get_nextcloud_credentials(self) -> dict[str, str]:
        """platform から Nextcloud 接続情報を取得する。

        返却: {"url", "username", "password", "group_folder"}
        """
        return self._get("/api/auth/nextcloud-credentials")

    def ping(self) -> dict[str, Any]:
        """疎通確認 (認証不要の /api/health)."""
        import httpx

        resp = httpx.get(f"{self._url}/api/health", timeout=10.0)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
