"""labvault platform API クライアント。

SDK/CLI/MCP が platform 経由で Nextcloud 資格情報、メタデータ等を取得するための
薄いラッパー。認証は以下のいずれか:

- 明示的に渡された PAT (``lv_*``) — コンストラクタ ``token`` 引数 or
  ``LABVAULT_TOKEN`` 環境変数から
- GCP ADC の access token (上記が無いとき)

PAT が利用可能なら ADC は完全に skip される (Google 認証不要のパス)。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

PAT_ENV = "LABVAULT_TOKEN"


class PlatformNotFound(Exception):
    """backend が 404 を返したとき発生。MetadataBackend 等で None に変換する。"""


class PlatformClient:
    """labvault platform backend クライアント。

    Args:
        url: backend のベース URL (例 "https://labvault-api-...run.app")。
        token: PAT (``lv_*``)。省略時は ``LABVAULT_TOKEN`` env を使い、
            それも無ければ ADC にフォールバック。
    """

    def __init__(self, url: str, token: str | None = None) -> None:
        self._url = url.rstrip("/")
        # PAT は env or 引数から
        self._pat = (token or os.environ.get(PAT_ENV) or "").strip() or None
        # ADC fallback 用 (PAT が無いときのみ使う)
        self._credentials: Any = None
        self._adc_token: str | None = None
        self._adc_expiry: float = 0.0
        self._lock = threading.Lock()

    def _get_access_token(self) -> str:
        """Authorization header に載せる token を返す。

        PAT があればそれを直接返す (cache 不要)。なければ ADC から取得。
        """
        if self._pat:
            return self._pat
        with self._lock:
            now = time.time()
            if self._adc_token and now < self._adc_expiry - 60:
                return self._adc_token
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
            self._adc_token = self._credentials.token
            # google-auth does not always set expiry on user creds;
            # fall back to 55 分キャッシュ
            exp = getattr(self._credentials, "expiry", None)
            if exp is not None:
                self._adc_expiry = exp.timestamp()
            else:
                self._adc_expiry = now + 55 * 60
            assert self._adc_token is not None
            return self._adc_token

    def _request(
        self,
        method: str,
        path: str,
        *,
        team: str = "",
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """汎用 HTTP リクエスト。404 は PlatformNotFound。"""
        import httpx

        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if team:
            headers["X-Labvault-Team"] = team
        url = f"{self._url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json,
                timeout=30.0,
            )
        except httpx.HTTPError as e:
            raise RuntimeError(f"platform request failed ({method} {path}): {e}") from e
        if resp.status_code == 404:
            raise PlatformNotFound(f"{method} {path} → 404")
        resp.raise_for_status()
        if not resp.content:
            return None
        return resp.json()

    # --- 後方互換: dict 専用 helper (既存呼出し維持) ---

    def _get(
        self,
        path: str,
        *,
        team: str = "",
    ) -> dict[str, Any]:
        result = self._request("GET", path, team=team)
        if not isinstance(result, dict):
            raise RuntimeError(
                f"expected dict from {path}, got {type(result).__name__}"
            )
        return result

    def get_dict(
        self,
        path: str,
        *,
        team: str = "",
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """dict response 用 (型を狭めて返す)."""
        result = self._request("GET", path, team=team, params=params)
        if not isinstance(result, dict):
            raise RuntimeError(
                f"expected dict from {path}, got {type(result).__name__}"
            )
        return result

    def get_list(
        self,
        path: str,
        *,
        team: str = "",
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """list[dict] response 用."""
        result = self._request("GET", path, team=team, params=params)
        if not isinstance(result, list):
            raise RuntimeError(
                f"expected list from {path}, got {type(result).__name__}"
            )
        return result

    def get_nextcloud_credentials(self, team: str = "") -> dict[str, str]:
        """platform から Nextcloud 接続情報を取得する。

        team を指定すると X-Labvault-Team header を載せる。未指定なら
        platform 側で user.default_team が使われる。

        返却: {"url", "username", "password", "group_folder"}
        """
        return self._get("/api/auth/nextcloud-credentials", team=team)

    def ping(self) -> dict[str, Any]:
        """疎通確認 (認証不要の /api/health)."""
        import httpx

        resp = httpx.get(f"{self._url}/api/health", timeout=10.0)
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]
