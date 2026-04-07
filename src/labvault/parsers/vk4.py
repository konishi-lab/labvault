"""Keyence VK4 レーザー顕微鏡ファイルのデコーダー。

バイトデータから光学画像を抽出し、PNG に変換する。
元コード: mdxdb-webapp/backend/app/lib/vk4_decorder.py
"""

from __future__ import annotations

import io
import struct
from typing import Any


def decode_color_image(data: bytes) -> Any:
    """VK4 バイトデータから光学画像を numpy 配列として抽出する。"""
    import numpy as np

    offset = struct.unpack_from("<I", data, 16)[0]
    pre = data[offset : offset + 20]
    width = struct.unpack_from("<I", pre, 0)[0]
    height = struct.unpack_from("<I", pre, 4)[0]
    points = struct.unpack_from("<I", pre, 16)[0]

    pixel_data = data[offset + 20 : offset + 20 + points]
    arr = np.frombuffer(pixel_data, dtype=np.uint8)
    return arr.reshape((height, width, 3))[:, :, ::-1]


def get_scale(data: bytes) -> tuple[float, float]:
    """VK4 バイトデータから XY/Z スケール (nm) を返す。"""
    xy = struct.unpack_from("<I", data, 252)[0] / 1e3
    z = struct.unpack_from("<I", data, 260)[0] / 1e3
    return xy, z


def to_preview_png(data: bytes, *, max_size: int = 512) -> bytes:
    """VK4 バイトデータから光学画像のプレビュー PNG を生成する。"""
    from PIL import Image

    image_array = decode_color_image(data)
    img = Image.fromarray(image_array)

    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
