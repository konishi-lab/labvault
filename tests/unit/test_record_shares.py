"""`Record.grant_share` / `revoke_share` / `shares` accessor の検証 (S1)。

backend の認可は別途 `platform/backend/tests/test_record_shares.py` で
担保。ここでは SDK 側の dataclass + persistence 部分だけを最小担保。
"""

from __future__ import annotations

import pytest

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
    ):
        monkeypatch.setenv(k, "")
    return Lab(
        "teamA",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


def test_grant_share_persists_after_reload(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    rec.grant_share("bob@b.com", "viewer")

    # 別 reference で fetch して永続化を確認
    rec2 = lab.get(rec.id)
    assert rec2.shares == {"bob@b.com": "viewer"}


def test_grant_lowercases_email(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    rec.grant_share("Bob@B.com", "viewer")
    assert "bob@b.com" in rec.shares


def test_revoke_removes_entry(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    rec.grant_share("bob@b.com", "viewer")
    rec.revoke_share("bob@b.com")
    assert rec.shares == {}


def test_revoke_unknown_email_is_noop(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    # 例外を投げない
    rec.revoke_share("ghost@nowhere.com")
    assert rec.shares == {}


def test_grant_invalid_role_raises(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    with pytest.raises(ValueError):
        rec.grant_share("bob@b.com", "destroyer")


def test_grant_empty_email_raises(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    with pytest.raises(ValueError):
        rec.grant_share("", "viewer")
    with pytest.raises(ValueError):
        rec.grant_share("   ", "viewer")


def test_shared_with_emails_is_sorted_copy(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    rec.grant_share("zach@z.com", "viewer")
    rec.grant_share("alice@a.com", "analyst")
    emails = rec.shared_with_emails()
    assert emails == ["alice@a.com", "zach@z.com"]
    # 返り値を変更しても rec の state には影響しない (コピー)
    emails.append("evil@evil.com")
    assert "evil@evil.com" not in rec.shared_with_emails()


def test_shares_property_returns_copy(lab: Lab) -> None:
    rec = lab.new("r", auto_log=False)
    rec.grant_share("bob@b.com", "viewer")
    snapshot = rec.shares
    snapshot["evil@evil.com"] = "analyst"
    # rec 内の state は変わらない
    assert "evil@evil.com" not in rec.shares
