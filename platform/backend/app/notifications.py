"""Slack 通知。webhook URL は Secret Manager から取得。

呼び出し側は失敗を気にしなくて良い (例外は握りつぶしてログのみ)。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .secrets_util import get_secret

logger = logging.getLogger(__name__)

SIGNUP_WEBHOOK_SECRET_KEY = "slack-signup-webhook-url"


def _post_to_webhook(url: str, payload: dict[str, Any]) -> None:
    try:
        resp = httpx.post(url, json=payload, timeout=5.0)
        if resp.status_code >= 300:
            logger.warning(
                "slack webhook returned %s: %s", resp.status_code, resp.text
            )
    except Exception:
        logger.exception("slack webhook post failed")


def notify_signup_request(
    email: str,
    display_name: str,
    requested_team_name: str,
    note: str = "",
) -> None:
    """サインアップ申請が来たときに super-admin Slack に通知する。

    secret 未設定なら no-op。webhook 失敗もログのみで握りつぶす。
    """
    url = get_secret(SIGNUP_WEBHOOK_SECRET_KEY)
    if not url:
        logger.info(
            "slack webhook secret %s not set, skip notify",
            SIGNUP_WEBHOOK_SECRET_KEY,
        )
        return

    lines = [
        ":wave: *labvault サインアップ申請*",
        f"• ユーザー: {display_name or '(未設定)'} <{email}>",
        f"• 申請した研究室: {requested_team_name or '(空)'}",
    ]
    if note:
        lines.append(f"• 備考: {note}")
    lines.append("承認: <https://labvault-web-355809880738.asia-northeast1.run.app/admin/pending|/admin/pending>")

    _post_to_webhook(url, {"text": "\n".join(lines)})
