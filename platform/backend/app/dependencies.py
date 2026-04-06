"""FastAPI 依存関係。"""

from __future__ import annotations

from typing import Any

from labvault import Lab

_lab: Lab | None = None


def get_lab() -> Lab:
    """Lab シングルトン。Settings から自動バックエンド選択。"""
    global _lab  # noqa: PLW0603
    if _lab is None:
        _lab = Lab()
    return _lab


def close_lab() -> None:
    """Lab を閉じる。"""
    global _lab  # noqa: PLW0603
    if _lab is not None:
        _lab.close()
        _lab = None
