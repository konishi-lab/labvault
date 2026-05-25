"""ファイルパーサー群。

`PARSER_REGISTRY` は import 時にビルトインを自動登録する。外部 parser を
追加する場合は `PARSER_REGISTRY.register("my_parser", fn)` を呼ぶ。
"""

from __future__ import annotations

from labvault.parsers.base import PARSER_REGISTRY, ParserFunc, ParserRegistry
from labvault.parsers.builtin import register_builtins

register_builtins()

__all__ = [
    "PARSER_REGISTRY",
    "ParserFunc",
    "ParserRegistry",
    "register_builtins",
]
