"""ファイルパーサーのレジストリ。

template の `FileParserConfig.parser_name` から実装関数を引く。
parser は `(data: bytes, file_name: str) -> dict[str, Any]` のシグネチャで、
抽出できた conditions の dict を返す。何も取れなかったら空 dict。

`Record.add()` は紐付いた template の `file_parsers` を見て、拡張子が
マッチする parser を起動し、戻り値を conditions にマージする。**ただし手動
入力 (既に conditions に入っている key) は parser 値で上書きしない**。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

ParserFunc = Callable[[bytes, str], dict[str, Any]]


class ParserRegistry:
    """parser_name → parser 関数 のレジストリ。"""

    def __init__(self) -> None:
        self._parsers: dict[str, ParserFunc] = {}

    def register(self, name: str, fn: ParserFunc) -> None:
        self._parsers[name] = fn

    def get(self, name: str) -> ParserFunc | None:
        return self._parsers.get(name)

    def names(self) -> list[str]:
        return sorted(self._parsers.keys())


PARSER_REGISTRY = ParserRegistry()
