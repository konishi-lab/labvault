"""Keyence VK4 レーザー顕微鏡ファイルのデコーダー。

バイトデータから光学画像・レーザー画像・高さデータを抽出し、PNG に変換する。
元コード: klab-device-library/analysis/vk4_decoder.py
"""

from __future__ import annotations

import io
import struct
from typing import Any

# ---------------------------------------------------------------------------
# 低レベルデコーダー
# ---------------------------------------------------------------------------


def _read_block_header(data: bytes, offset: int) -> tuple[int, int, int]:
    """データブロックのヘッダから width, height, total_bytes を読む。"""
    width = struct.unpack_from("<I", data, offset)[0]
    height = struct.unpack_from("<I", data, offset + 4)[0]
    total_bytes = struct.unpack_from("<I", data, offset + 16)[0]
    return width, height, total_bytes


def _decode_rgb_block(data: bytes, header_offset_pos: int) -> Any:
    """RGB 画像ブロックをデコードする (BGR → RGB)。"""
    import numpy as np

    offset = struct.unpack_from("<I", data, header_offset_pos)[0]
    width, height, points = _read_block_header(data, offset)
    pixel_data = data[offset + 20 : offset + 20 + points]
    arr = np.frombuffer(pixel_data, dtype=np.uint8)
    return arr.reshape((height, width, 3))[:, :, ::-1]


def _decode_intensity_block(data: bytes, header_offset_pos: int) -> Any:
    """輝度/高さブロックをデコードする (可変バイト長整数)。"""
    import numpy as np

    offset = struct.unpack_from("<I", data, header_offset_pos)[0]
    pre = data[offset : offset + 28]
    width = struct.unpack_from("<I", pre, 0)[0]
    height = struct.unpack_from("<I", pre, 4)[0]
    databytes = struct.unpack_from("<I", pre, 8)[0] // 8

    # LZW テーブル (768 bytes) をスキップ
    raw_start = offset + 28 + 768
    raw = data[raw_start : raw_start + width * height * databytes]

    arr = np.empty(width * height, dtype=np.float64)
    for i in range(width * height):
        chunk = raw[i * databytes : (i + 1) * databytes]
        arr[i] = int.from_bytes(chunk, byteorder="little")

    return arr.reshape((height, width))


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------


def decode_color_image(data: bytes) -> Any:
    """VK4 バイトデータから光学画像を numpy 配列として抽出する。

    Returns
    -------
    numpy.ndarray
        (H, W, 3) uint8, RGB
    """
    return _decode_rgb_block(data, header_offset_pos=16)


def decode_laser_color_image(data: bytes) -> Any:
    """VK4 バイトデータからレーザー+光学合成画像を numpy 配列として抽出する。

    Returns
    -------
    numpy.ndarray
        (H, W, 3) uint8, RGB
    """
    return _decode_rgb_block(data, header_offset_pos=20)


def decode_laser_image(data: bytes) -> Any:
    """VK4 バイトデータからレーザー輝度画像を numpy 配列として抽出する。

    Returns
    -------
    numpy.ndarray
        (H, W) float64
    """
    return _decode_intensity_block(data, header_offset_pos=24)


def decode_height_map(data: bytes) -> Any:
    """VK4 バイトデータから高さデータを numpy 配列として抽出する。

    値は生のカウント値。実寸への変換には get_scale() の Z スケールを掛ける。

    Returns
    -------
    numpy.ndarray
        (H, W) float64, 単位: カウント値 (x Z_scale_nm で nm)
    """
    return _decode_intensity_block(data, header_offset_pos=36)


def get_scale(data: bytes) -> tuple[float, float]:
    """VK4 バイトデータから XY/Z スケール (nm) を返す。"""
    xy = struct.unpack_from("<I", data, 252)[0] / 1e3
    z = struct.unpack_from("<I", data, 260)[0] / 1e3
    return xy, z


def to_surface_data(data: bytes) -> Any:
    """VK4 バイトデータから SurfaceData を生成する。

    高さマップは nm → µm に変換される。

    Returns
    -------
    SurfaceData
    """
    from labvault.parsers._analysis import SurfaceData

    xy_nm, z_nm = get_scale(data)
    height_counts = decode_height_map(data)
    height_um = height_counts * z_nm / 1000.0  # nm → µm

    return SurfaceData(
        height_map=height_um,
        pixel_size_um=xy_nm / 1000.0,  # nm → µm
        optical_image=decode_color_image(data),
    )


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
