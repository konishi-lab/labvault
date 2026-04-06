"""Keyence VK4 レーザー顕微鏡ファイルのデコーダー。

一時ファイル経由でデコードする (VK4 はバイナリ seek が必要)。
元コード: mdxdb-webapp/backend/app/lib/vk4_decorder.py
"""

from __future__ import annotations

import binascii
import io
import tempfile
from typing import Any


def _colorviewer(filename: str) -> Any:
    """光学顕微鏡画像の RGB データを numpy 配列として抽出。"""
    import numpy as np

    with open(filename, "rb") as f:
        header = f.read(30)
    offset = int(binascii.hexlify(header[16:20][::-1]), 16)
    with open(filename, "rb") as f:
        f.seek(offset)
        pre_data = f.read(20)
        width = int(binascii.hexlify(pre_data[0:4][::-1]), 16)
        height = int(binascii.hexlify(pre_data[4:8][::-1]), 16)
        points = int(binascii.hexlify(pre_data[16:20][::-1]), 16)
        data = f.read(points)
    data_array = np.frombuffer(data, dtype="B")
    return np.reshape(data_array, (height, width, 3))[:, :, ::-1]


def _getscale(filename: str) -> tuple[float, float]:
    """XY/Z スケール (nm) を返す。"""
    with open(filename, "rb") as f:
        header = f.read(264)
    xy = int(binascii.hexlify(header[252:256][::-1]), 16) / 1e3
    z = int(binascii.hexlify(header[260:264][::-1]), 16) / 1e3
    return xy, z


def to_preview_png(data: bytes, *, max_size: int = 512) -> bytes:
    """VK4 バイトデータから光学画像のプレビュー PNG を生成する。

    一時ファイルに書き出してからデコードする。

    Args:
        data: VK4 ファイルのバイトデータ
        max_size: 長辺の最大ピクセル数

    Returns:
        PNG 画像のバイトデータ
    """
    from PIL import Image

    with tempfile.NamedTemporaryFile(suffix=".vk4", delete=True) as tmp:
        tmp.write(data)
        tmp.flush()
        image_array = _colorviewer(tmp.name)

    img = Image.fromarray(image_array)

    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
