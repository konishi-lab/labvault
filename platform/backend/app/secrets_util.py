"""Secret Manager ラッパー。ADC で認証、キャッシュあり。"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


def _default_secret_name(key: str) -> str:
    """project/secret/version の resource name を組み立てる。"""
    from labvault.core.config import Settings

    project = os.environ.get("LABVAULT_GCP_PROJECT") or Settings().gcp_project
    return f"projects/{project}/secrets/{key}/versions/latest"


@lru_cache(maxsize=8)
def get_secret(key: str) -> str | None:
    """Secret Manager から値を取得する。失敗時は None。

    key は短い名前（例: "nextcloud-master-password"）。resource name は自動組立。
    プロセス起動中キャッシュされる。
    """
    try:
        from google.cloud import secretmanager
    except ImportError:
        logger.warning("google-cloud-secret-manager not installed")
        return None

    try:
        client = secretmanager.SecretManagerServiceClient()
        name = _default_secret_name(key)
        resp = client.access_secret_version(name=name)
        return resp.payload.data.decode("utf-8")
    except Exception as e:
        logger.warning("failed to fetch secret %s: %s", key, e)
        return None
