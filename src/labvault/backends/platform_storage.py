"""HTTP-based storage backend (PAT-friendly)。

PAT 認証で動く SDK 用の StorageBackend 実装。直接 Nextcloud に接続せず、
labvault platform backend の ``/api/metadata/storage/*`` 経由でアクセスする。

team は X-Labvault-Team header で渡す (コンストラクタで束縛)。
"""

from __future__ import annotations

import logging
from typing import Any

from .platform_client import PlatformClient, PlatformNotFound

logger = logging.getLogger(__name__)


class PlatformStorage:
    """labvault platform 経由のストレージバックエンド。

    Args:
        client: 認証済みの PlatformClient。
        team: この Storage が紐付く team_id (header に乗せる)。
    """

    def __init__(self, client: PlatformClient, team: str) -> None:
        self._client = client
        self._team = team

    def _headers(self) -> dict[str, str]:
        token = self._client._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "X-Labvault-Team": self._team,
        }

    def upload(self, path: str, data: bytes, content_type: str = "") -> str:
        """ファイルアップロード (multipart/form-data)。"""
        import httpx

        files = {
            "file": (
                path.split("/")[-1] or "data",
                data,
                content_type or "application/octet-stream",
            ),
        }
        form: dict[str, Any] = {"path": path, "content_type": content_type}
        resp = httpx.post(
            f"{self._client._url}/api/metadata/storage",
            headers=self._headers(),
            data=form,
            files=files,
            timeout=120.0,
        )
        resp.raise_for_status()
        body = resp.json() or {}
        return str(body.get("path", path))

    def download(self, path: str) -> bytes:
        import httpx

        resp = httpx.get(
            f"{self._client._url}/api/metadata/storage",
            headers=self._headers(),
            params={"path": path},
            timeout=120.0,
        )
        if resp.status_code == 404:
            raise FileNotFoundError(path)
        resp.raise_for_status()
        return resp.content

    def delete(self, path: str) -> None:
        import httpx

        resp = httpx.delete(
            f"{self._client._url}/api/metadata/storage",
            headers=self._headers(),
            params={"path": path},
            timeout=30.0,
        )
        if resp.status_code in (204, 200, 404):
            return
        resp.raise_for_status()

    def exists(self, path: str) -> bool:
        try:
            data = self._client.get_dict(
                "/api/metadata/storage/exists",
                team=self._team,
                params={"path": path},
            )
        except PlatformNotFound:
            return False
        return bool(data.get("exists"))

    def list_files(self, prefix: str) -> list[str]:
        data = self._client.get_dict(
            "/api/metadata/storage/list",
            team=self._team,
            params={"prefix": prefix},
        )
        raw = data.get("paths") or []
        return [str(p) for p in raw]
