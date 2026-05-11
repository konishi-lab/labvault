"""Artifact Registry IAM 操作。承認時に AR reader 権限を自動付与する。

REST API を直接叩く (依存軽量化のため google-cloud-artifact-registry library を
使わない)。失敗は握りつぶしてログのみ — admin 操作を AR 障害で止めない。

Backend SA (`labvault-api@klab-laser-process.iam.gserviceaccount.com`) に
対象 repo の `roles/artifactregistry.repoAdmin` を一度だけ付与しておく必要が
ある。手順は docs/multitenant_next_steps.md 参照。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx

logger = logging.getLogger(__name__)

AR_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
READER_ROLE = "roles/artifactregistry.reader"
REPO_ENV = "LABVAULT_AR_REPO"


def _repo_resource() -> str | None:
    """env から AR repo の full resource name を返す。

    例: ``projects/klab-laser-process/locations/asia-northeast1/repositories/labvault-pypi``
    """
    return (os.environ.get(REPO_ENV) or "").strip() or None


def _api_url(resource: str, verb: str) -> str:
    return f"https://artifactregistry.googleapis.com/v1/{resource}:{verb}"


def _get_token() -> str | None:
    try:
        creds, _ = google.auth.default(scopes=[AR_SCOPE])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token
    except Exception:
        logger.exception("AR auth failed")
        return None


def _modify_policy(email: str, *, add: bool) -> bool:
    """member を reader role に追加 / 削除する。

    冪等: 既に意図した状態なら no-op で True。
    LABVAULT_AR_REPO 未設定 / 認証失敗 / API エラー時は False (warning log 済)。
    """
    repo = _repo_resource()
    if not repo:
        logger.info("%s not set, skip AR IAM update for %s", REPO_ENV, email)
        return False

    token = _get_token()
    if not token:
        return False

    member = f"user:{email}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            _api_url(repo, "getIamPolicy"),
            headers=headers,
            json={},
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("AR getIamPolicy failed for %s", repo)
        return False
    policy: dict[str, Any] = resp.json()

    bindings: list[dict[str, Any]] = list(policy.get("bindings") or [])
    target: dict[str, Any] | None = None
    for b in bindings:
        if b.get("role") == READER_ROLE:
            target = b
            break

    members: list[str] = list(target.get("members") or []) if target else []
    if add:
        if member in members:
            logger.info("AR: %s already has reader on %s", member, repo)
            return True
        members.append(member)
    else:
        if member not in members:
            logger.info("AR: %s already absent from %s", member, repo)
            return True
        members.remove(member)

    if target is not None:
        target["members"] = members
        if not members:
            bindings.remove(target)
    elif add:
        bindings.append({"role": READER_ROLE, "members": members})

    policy["bindings"] = bindings

    try:
        resp = httpx.post(
            _api_url(repo, "setIamPolicy"),
            headers=headers,
            json={"policy": policy},
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception("AR setIamPolicy failed for %s", repo)
        return False

    logger.info(
        "AR: %s %s reader on %s", member, "granted" if add else "revoked", repo
    )
    return True


def grant_reader(email: str) -> bool:
    """AR repo に reader 権限を付与する。冪等、失敗時 False。"""
    return _modify_policy(email, add=True)


def revoke_reader(email: str) -> bool:
    """AR repo から reader 権限を剥奪する。冪等、失敗時 False。"""
    return _modify_policy(email, add=False)
