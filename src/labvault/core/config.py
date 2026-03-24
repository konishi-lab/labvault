"""labvault 設定管理。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """labvault SDK 設定。

    読み込み順: 環境変数 (LABVAULT_ prefix) > config.toml
    """

    model_config = SettingsConfigDict(
        env_prefix="LABVAULT_",
        toml_file=str(Path.home() / ".labvault" / "config.toml"),
        extra="ignore",
    )

    team: str = ""
    user: str = ""
    gcp_project: str = ""
    firestore_database: str = "(default)"
    nextcloud_url: str = ""
    nextcloud_user: str = ""
    nextcloud_password: str = ""
    nextcloud_group_folder: str = ""
    buffer_dir: Path = Field(
        default_factory=lambda: Path.home() / ".labvault" / "buffer"
    )
    auto_sync: bool = True
    sync_interval_sec: float = 30.0
    auto_log: bool = True
