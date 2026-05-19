"""labvault -- Python/Notebook 実験データ基盤。"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from labvault.core.lab import Lab
from labvault.core.record import Record

try:
    __version__ = _pkg_version("labvault")
except PackageNotFoundError:
    # editable install 等でメタデータが取れない場合のフォールバック。
    # 通常は pyproject.toml の version が importlib.metadata 経由で読まれる。
    __version__ = "0.0.0+unknown"

__all__ = ["Lab", "Record"]
