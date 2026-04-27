"""FastAPI 依存関係のうち、認証に依存しないユーティリティ。

`current_team` 依存付きの FastAPI dep (handler が直接受け取る `Depends(get_lab)`)
は循環参照を避けるため auth.py 側に置く。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from fastapi import HTTPException

from labvault import Lab

from .secrets_util import get_secret

logger = logging.getLogger(__name__)

_labs: dict[str, Lab] = {}
_labs_lock = threading.Lock()
_firestore_db: Any | None = None
_firestore_lock = threading.Lock()


def get_firestore_db() -> Any:
    """Firestore client のシングルトン。teams / allowed_users 等の参照に使う。"""
    global _firestore_db
    with _firestore_lock:
        if _firestore_db is None:
            from google.cloud import firestore

            project = os.environ.get("LABVAULT_GCP_PROJECT")
            database = os.environ.get(
                "LABVAULT_FIRESTORE_DATABASE", "(default)"
            )
            _firestore_db = firestore.Client(
                project=project or None, database=database
            )
        return _firestore_db


def get_team_meta(team_id: str) -> dict[str, Any]:
    """teams/{team_id} ドキュメントを取得する。存在しなければ 404。"""
    snap = get_firestore_db().collection("teams").document(team_id).get()
    if not snap.exists:
        raise HTTPException(
            status_code=404, detail=f"team {team_id!r} not found"
        )
    return snap.to_dict() or {}


def _build_lab(team_id: str) -> Lab:
    """指定 team の Lab を構築する。

    nextcloud-master-password (Secret Manager) と
    teams/{team_id}.nextcloud_group_folder を組み合わせて NextcloudStorage を作る。
    Secret 未設定 / Settings 不完全なら SDK の自動選択 (`Lab(team=...)`) に任せる。
    """
    master = get_secret("nextcloud-master-password")
    if not master:
        logger.warning(
            "nextcloud-master-password not set, using Lab auto-config for %s",
            team_id,
        )
        return Lab(team=team_id)

    from labvault.backends.nextcloud import NextcloudStorage
    from labvault.core.config import Settings

    s = Settings()
    if not (s.nextcloud_url and s.nextcloud_user):
        return Lab(team=team_id)

    meta = get_team_meta(team_id)
    group_folder = meta.get("nextcloud_group_folder") or s.nextcloud_group_folder
    if not group_folder:
        raise HTTPException(
            status_code=500,
            detail=(
                f"team {team_id!r} has no nextcloud_group_folder "
                "and no fallback in Settings"
            ),
        )

    storage = NextcloudStorage(
        url=s.nextcloud_url,
        user=s.nextcloud_user,
        password=master,
        group_folder=group_folder,
    )
    return Lab(team=team_id, storage_backend=storage)


def get_lab_for_team(team_id: str) -> Lab:
    """team_id を指定して Lab を取得する (キャッシュ付き)。

    FastAPI handler からは auth.get_lab (current_team を Depends する FastAPI dep)
    経由で間接的に呼ばれる。
    """
    with _labs_lock:
        if team_id not in _labs:
            _labs[team_id] = _build_lab(team_id)
        return _labs[team_id]


def close_lab() -> None:
    """全 Lab を閉じる。lifespan で呼ぶ。"""
    with _labs_lock:
        for lab in _labs.values():
            try:
                lab.close()
            except Exception:
                logger.exception("close lab failed")
        _labs.clear()
