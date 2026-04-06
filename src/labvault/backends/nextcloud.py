"""Nextcloud ストレージバックエンド (nc-py-api)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class NextcloudStorage:
    """Nextcloud グループフォルダへのファイル保存。

    パス変換:
        SDK パス ``{team}/{record_id}/{filename}``
        → Nextcloud ``{group_folder}/labvault/{team}/{record_id}/{filename}``
    """

    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        group_folder: str,
    ) -> None:
        self._url = url
        self._user = user
        self._password = password
        self._group_folder = group_folder
        self._base_path = f"{group_folder}/labvault"
        self._nc: Any | None = None

    def _get_client(self) -> Any:
        """nc-py-api クライアントを遅延初期化する。"""
        if self._nc is None:
            from nc_py_api import Nextcloud

            self._nc = Nextcloud(
                nextcloud_url=self._url,
                nc_auth_user=self._user,
                nc_auth_pass=self._password,
            )
        return self._nc

    def _full_path(self, path: str) -> str:
        """SDK パスを Nextcloud フルパスに変換する。"""
        return f"{self._base_path}/{path}"

    def upload(
        self, path: str, data: bytes, content_type: str = ""
    ) -> str:
        """ファイルをアップロードする。親ディレクトリは自動作成。"""
        nc = self._get_client()
        full = self._full_path(path)

        # 親ディレクトリを自動作成
        parent = "/".join(full.split("/")[:-1])
        if parent:
            nc.files.makedirs(parent, exist_ok=True)

        nc.files.upload(full, data)
        return path

    def download(self, path: str) -> bytes:
        """ファイルをダウンロードする。"""
        nc = self._get_client()
        full = self._full_path(path)
        result = nc.files.download(full)
        if not isinstance(result, bytes):
            msg = f"Unexpected download result type: {type(result)}"
            raise TypeError(msg)
        return result

    def delete(self, path: str) -> None:
        """ファイルを削除する。"""
        nc = self._get_client()
        full = self._full_path(path)
        nc.files.delete(full, not_fail=True)

    def exists(self, path: str) -> bool:
        """ファイルの存在を確認する。"""
        nc = self._get_client()
        full = self._full_path(path)
        try:
            return nc.files.by_path(full) is not None
        except Exception:
            return False

    def list_files(self, prefix: str) -> list[str]:
        """prefix 配下のファイル一覧を返す (SDK パスで返す)."""
        nc = self._get_client()
        full = self._full_path(prefix)

        try:
            nodes = nc.files.listdir(full)
        except Exception:
            return []

        result: list[str] = []
        for node in nodes:
            if not node.is_dir:
                # Nextcloud パスから SDK パスに戻す
                node_path = node.user_path.lstrip("/")
                base = self._base_path + "/"
                if node_path.startswith(base):
                    sdk_path = node_path[len(base) :]
                    result.append(sdk_path)
        return sorted(result)
