"""labvault 設定管理。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    """labvault SDK 設定。

    読み込み優先順位:
    1. 環境変数 (LABVAULT_ prefix)
    2. .env ファイル (カレントディレクトリ)
    3. ~/.labvault/config.toml
    """

    model_config = SettingsConfigDict(
        env_prefix="LABVAULT_",
        env_file=".env",
        env_file_encoding="utf-8",
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
    platform_url: str = ""
    buffer_dir: Path = Field(
        default_factory=lambda: Path.home() / ".labvault" / "buffer"
    )
    auto_sync: bool = True
    sync_interval_sec: float = 30.0
    buffer_cleanup: bool = True
    buffer_retention_days: int = 7
    auto_log: bool = True

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
        **kwargs: Any,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """設定ソースの優先順位を定義する。"""
        sources: list[PydanticBaseSettingsSource] = [
            init_settings,
            env_settings,
            dotenv_settings,
        ]

        # toml サポートがある場合のみ追加
        try:
            from pydantic_settings import TomlConfigSettingsSource

            toml_path = Path.home() / ".labvault" / "config.toml"
            if toml_path.exists():
                sources.append(
                    TomlConfigSettingsSource(settings_cls, toml_file=toml_path)
                )
        except ImportError:
            pass

        sources.append(file_secret_settings)
        return tuple(sources)
