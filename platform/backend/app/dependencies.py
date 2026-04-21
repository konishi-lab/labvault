"""FastAPI 依存関係。"""

from __future__ import annotations

from labvault import Lab

from .secrets_util import get_secret

_lab: Lab | None = None


def _build_lab() -> Lab:
    """Lab を構築する。Secret Manager の master password を優先、無ければ .env。"""
    master = get_secret("nextcloud-master-password")
    if not master:
        return Lab()

    # Settings から url/user/group_folder を取り、password のみ Secret Manager で上書き
    from labvault.backends.nextcloud import NextcloudStorage
    from labvault.core.config import Settings

    s = Settings()
    if not (s.nextcloud_url and s.nextcloud_user):
        # Nextcloud 設定が不完全なら自動選択に任せる
        return Lab()

    storage = NextcloudStorage(
        url=s.nextcloud_url,
        user=s.nextcloud_user,
        password=master,
        group_folder=s.nextcloud_group_folder,
    )
    return Lab(storage_backend=storage)


def get_lab() -> Lab:
    """Lab シングルトン。"""
    global _lab
    if _lab is None:
        _lab = _build_lab()
    return _lab


def close_lab() -> None:
    """Lab を閉じる。"""
    global _lab
    if _lab is not None:
        _lab.close()
        _lab = None
