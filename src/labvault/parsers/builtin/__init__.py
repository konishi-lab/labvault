"""ビルトインファイルパーサー。

`labvault.parsers` の import 時に `register_builtins()` を呼び、
PARSER_REGISTRY にビルトイン parser を登録する。
"""

from __future__ import annotations

from labvault.parsers.base import PARSER_REGISTRY
from labvault.parsers.builtin.ras import parse_ras


def register_builtins() -> None:
    """ビルトイン parser を PARSER_REGISTRY に登録する。"""
    PARSER_REGISTRY.register("ras_parser", parse_ras)


__all__ = ["register_builtins"]
