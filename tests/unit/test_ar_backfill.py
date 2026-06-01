"""scripts/ar_backfill.py の純粋関数 (classify_missing) を検証する。

Firestore / AR への実呼び出しは伴わない。漏れ判定ロジックの回帰だけ守る。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ar_backfill.py"


@pytest.fixture()
def mod():
    spec = importlib.util.spec_from_file_location("ar_backfill_mod", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    sys.modules["ar_backfill_mod"] = m
    spec.loader.exec_module(m)
    return m


def test_classify_missing_returns_users_not_in_members(mod) -> None:
    users = [
        {"email": "alice@example.com"},
        {"email": "bob@example.com"},
        {"email": "carol@example.com"},
    ]
    # alice だけ AR reader に居る
    members = {"user:alice@example.com"}
    missing = mod.classify_missing(users, members)
    emails = {u["email"] for u in missing}
    assert emails == {"bob@example.com", "carol@example.com"}


def test_classify_missing_all_present(mod) -> None:
    users = [{"email": "alice@example.com"}, {"email": "bob@example.com"}]
    members = {"user:alice@example.com", "user:bob@example.com"}
    assert mod.classify_missing(users, members) == []


def test_classify_missing_empty_inputs(mod) -> None:
    assert mod.classify_missing([], set()) == []
    assert mod.classify_missing([], {"user:foo@bar"}) == []


def test_classify_missing_ignores_non_user_prefix(mod) -> None:
    # serviceAccount: や group: の binding が混ざっていても、user: prefix
    # 以外は比較に影響しない (= 該当 email は missing 扱いされる)
    users = [{"email": "alice@example.com"}]
    members = {
        "serviceAccount:alice@example.com",
        "group:alice@example.com",
    }
    missing = mod.classify_missing(users, members)
    assert len(missing) == 1
    assert missing[0]["email"] == "alice@example.com"
