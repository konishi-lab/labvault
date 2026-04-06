"""オブジェクトの浅いダイジェスト生成。

unhashable オブジェクト (ndarray, DataFrame, list, dict) に対応。
オブジェクトの「形状」と「先頭・末尾の値」から O(1) でハッシュを生成する。
"""

from __future__ import annotations

import hashlib
from typing import Any


def _shallow_digest(obj: Any) -> str:
    """オブジェクトの浅いダイジェストを生成する。

    全データのハッシュではないため、稀に変更を見逃す可能性がある
    (ベストエフォート)。性能: O(1)。
    """
    # numpy.ndarray
    try:
        import numpy as np

        if isinstance(obj, np.ndarray):
            parts = [
                f"ndarray:{obj.shape}:{obj.dtype}",
                str(obj.flat[:4].tolist()) if obj.size > 0 else "[]",
                str(obj.flat[-4:].tolist()) if obj.size > 4 else "",
                str(obj.size),
            ]
            return _md5("|".join(parts))
    except ImportError:
        pass

    # pandas.DataFrame / Series
    try:
        import pandas as pd  # type: ignore[import-untyped]

        if isinstance(obj, pd.DataFrame):
            cols = list(obj.columns[:10])
            parts = [
                f"df:{obj.shape}",
                str(cols),
                str(obj.head(2).values.tolist()) if len(obj) > 0 else "[]",
                str(obj.tail(2).values.tolist()) if len(obj) > 2 else "",
            ]
            return _md5("|".join(parts))

        if isinstance(obj, pd.Series):
            parts = [
                f"series:{obj.shape}:{obj.dtype}:{obj.name}",
                str(obj.head(4).tolist()),
                str(obj.tail(4).tolist()) if len(obj) > 4 else "",
            ]
            return _md5("|".join(parts))
    except ImportError:
        pass

    if isinstance(obj, dict):
        keys = sorted(str(k) for k in list(obj.keys())[:10])
        value_types = [type(obj[k]).__name__ for k in list(obj.keys())[:10]]
        parts = [f"dict:{len(obj)}", str(keys), str(value_types)]
        return _md5("|".join(parts))

    if isinstance(obj, list):
        head = [f"{type(x).__name__}:{repr(x)[:50]}" for x in obj[:4]]
        tail = (
            [f"{type(x).__name__}:{repr(x)[:50]}" for x in obj[-4:]]
            if len(obj) > 4
            else []
        )
        parts = [f"list:{len(obj)}", str(head), str(tail)]
        return _md5("|".join(parts))

    if isinstance(obj, set):
        sorted_items = sorted(str(x) for x in list(obj)[:10])
        parts = [f"set:{len(obj)}", str(sorted_items)]
        return _md5("|".join(parts))

    if isinstance(obj, (int, float, str, bool, type(None))):
        return _md5(repr(obj))

    # fallback: type + id
    return _md5(f"{type(obj).__name__}:{id(obj)}")


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()[:16]
