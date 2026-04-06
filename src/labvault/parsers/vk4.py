"""Keyence VK4 レーザー顕微鏡ファイルのデコーダー。

バイトデータから光学画像を抽出し、PNG に変換する。
"""

from __future__ import annotations

import io
import struct
from typing import Any


def decode_color_image(data: bytes) -> Any:
    """VK4 バイトデータから光学画像を numpy 配列として抽出する。

    Returns:
        numpy.ndarray: (height, width, 3) RGB 画像
    """
    import numpy as np

    header = data[:30]
    offset = struct.unpack_from("<I", header, 16)[0]

    pre_data = data[offset : offset + 20]
    width = struct.unpack_from("<I", pre_data, 0)[0]
    height = struct.unpack_from("<I", pre_data, 4)[0]
    points = struct.unpack_from("<I", pre_data, 16)[0]

    pixel_data = data[offset + 20 : offset + 20 + points]
    arr = np.frombuffer(pixel_data, dtype=np.uint8)
    image = arr.reshape((height, width, 3))[:, :, ::-1]  # BGR → RGB
    return image


def decode_height_image(data: bytes) -> Any:
    """VK4 バイトデータから高さ情報を numpy 配列として抽出する。

    Returns:
        numpy.ndarray: (height, width) 高さマップ
    """
    import numpy as np

    header = data[:40]
    offset = struct.unpack_from("<I", header, 36)[0]

    pre_data = data[offset : offset + 28]
    width = struct.unpack_from("<I", pre_data, 0)[0]
    height = struct.unpack_from("<I", pre_data, 4)[0]
    databytes = struct.unpack_from("<I", pre_data, 8)[0] // 8

    pixel_start = offset + 28 + 256 * 3  # skip LZW table
    pixel_data = data[pixel_start : pixel_start + width * height * databytes]

    arr = np.empty(width * height)
    for i in range(width * height):
        chunk = pixel_data[i * databytes : (i + 1) * databytes]
        arr[i] = int.from_bytes(chunk, byteorder="little")
    return arr.reshape((height, width))


def get_scale(data: bytes) -> tuple[float, float]:
    """VK4 バイトデータから XY/Z スケール (nm) を返す。"""
    header = data[:264]
    xy = struct.unpack_from("<I", header, 252)[0] / 1e3
    z = struct.unpack_from("<I", header, 260)[0] / 1e3
    return xy, z


def to_preview_png(
    data: bytes, *, max_size: int = 512
) -> bytes:
    """VK4 バイトデータから光学画像のプレビュー PNG を生成する。

    Args:
        data: VK4 ファイルのバイトデータ
        max_size: 長辺の最大ピクセル数

    Returns:
        PNG 画像のバイトデータ
    """
    from PIL import Image

    image_array = decode_color_image(data)
    img = Image.fromarray(image_array)

    # ダウンサイズ
    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
