"""Namespace のキャプチャと差分検出。"""

from __future__ import annotations

import types
from typing import Any

from labvault.tracking.digest import _shallow_digest

# 除外する変数名プレフィックス
_EXCLUDE_PREFIXES = ("_",)

# 除外する型
_EXCLUDE_TYPES = (
    types.ModuleType,
    types.FunctionType,
    types.MethodType,
    type,
)

# IPython 内部変数
_IPYTHON_VARS = frozenset({"In", "Out", "get_ipython", "exit", "quit"})

# 機微情報パターン (case-insensitive)
_SENSITIVE_PATTERNS = (
    "password",
    "secret",
    "token",
    "key",
    "credential",
    "api_key",
    "apikey",
    "auth",
)
REDACTED = "***REDACTED***"


def capture_namespace(
    namespace: dict[str, Any],
) -> dict[str, tuple[int, str]]:
    """namespace の各変数について (id, shallow_digest) をキャプチャする。

    フィルタ:
    - ``_`` で始まる変数を除外
    - モジュール、関数、クラスオブジェクトを除外
    - IPython 内部変数を除外
    - 機微情報パターンに一致する変数名はマスク
    """
    result: dict[str, tuple[int, str]] = {}

    for name, obj in namespace.items():
        if any(name.startswith(p) for p in _EXCLUDE_PREFIXES):
            continue

        if isinstance(obj, _EXCLUDE_TYPES):
            continue

        if name in _IPYTHON_VARS:
            continue

        name_lower = name.lower()
        if any(pat in name_lower for pat in _SENSITIVE_PATTERNS):
            result[name] = (id(obj), REDACTED)
            continue

        try:
            digest = _shallow_digest(obj)
        except Exception:
            digest = f"error:{id(obj)}"

        result[name] = (id(obj), digest)

    return result


def diff_namespaces(
    before: dict[str, tuple[int, str]],
    after: dict[str, tuple[int, str]],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """2 つの namespace スナップショットの差分を検出する。

    Returns:
        (new_vars, changed_vars, deleted_vars)
    """
    new_vars: dict[str, Any] = {}
    changed_vars: dict[str, Any] = {}
    deleted_vars: list[str] = []

    for name, (after_id, after_digest) in after.items():
        if after_digest == REDACTED:
            continue

        if name not in before:
            new_vars[name] = after_digest
        else:
            before_id, before_digest = before[name]
            if before_digest == REDACTED:
                continue
            if after_id != before_id or after_digest != before_digest:
                changed_vars[name] = {
                    "before": before_digest,
                    "after": after_digest,
                }

    for name in before:
        if name not in after:
            deleted_vars.append(name)

    return new_vars, changed_vars, deleted_vars
