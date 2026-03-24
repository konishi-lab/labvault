"""Crockford's Base32 IDジェネレーター。"""

from __future__ import annotations

import secrets

# Crockford's Base32: I, L, O, U を除外した32文字
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_id(length: int = 4) -> str:
    """ランダムIDを生成する。

    Args:
        length: 文字数。4文字で約100万通り。

    Returns:
        大文字の Base32 文字列 (例: "AB3F").
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def normalize_id(raw: str) -> str:
    """入力IDを正規化する。小文字→大文字、O→0, I/L→1 に変換。"""
    table = str.maketrans("oilOIL", "011011")
    return raw.upper().translate(table)
