"""Sensofar PLUX ファイルのパーサー。

.plux ファイル (ZIP アーカイブ) から高さマップと光学画像を抽出する。
装置: Sensofar S neox シリーズ (CSI 干渉計)。
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from typing import Any


def parse_index(data: bytes) -> dict[str, Any]:
    """index.xml からメタデータを抽出する。"""
    zf = zipfile.ZipFile(io.BytesIO(data))
    xml_bytes = zf.read("index.xml")
    root = ET.fromstring(xml_bytes)

    general = root.find("GENERAL")
    if general is None:
        raise ValueError("index.xml に GENERAL 要素がありません")

    fov_x = float(general.findtext("FOV_X", "0"))
    fov_y = float(general.findtext("FOV_Y", "0"))
    width = int(general.findtext("IMAGE_SIZE_X", "0"))
    height = int(general.findtext("IMAGE_SIZE_Y", "0"))

    instrument = root.find("Instrument")
    manufacturer = instrument.findtext("Manufacturer", "") if instrument is not None else ""
    model = instrument.findtext("Model", "") if instrument is not None else ""

    probing = root.find("ProbingSystem")
    objective = probing.findtext("Id", "") if probing is not None else ""

    return {
        "fov_x_mm": fov_x,
        "fov_y_mm": fov_y,
        "width": width,
        "height": height,
        "manufacturer": manufacturer,
        "model": model,
        "objective": objective,
    }


def decode_height_map(data: bytes) -> Any:
    """PLUX バイトデータから高さマップを numpy 配列として抽出する。

    Returns
    -------
    numpy.ndarray
        (H, W) float32, 単位: µm
    """
    import numpy as np

    zf = zipfile.ZipFile(io.BytesIO(data))
    meta = parse_index(data)
    w, h = meta["width"], meta["height"]

    raw = zf.read("LAYER_0.raw")
    return np.frombuffer(raw, dtype=np.float32).reshape(h, w).copy()


def decode_optical_image(data: bytes) -> Any:
    """PLUX バイトデータから光学画像を numpy 配列として抽出する。

    Returns
    -------
    numpy.ndarray
        (H, W, 3) uint8, RGB
    """
    import numpy as np

    zf = zipfile.ZipFile(io.BytesIO(data))
    meta = parse_index(data)
    w, h = meta["width"], meta["height"]

    raw = zf.read("LAYER_0.stack.raw")
    return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3).copy()


def get_pixel_size_um(data: bytes) -> float:
    """PLUX バイトデータからピクセルサイズ (µm/pixel) を返す。"""
    meta = parse_index(data)
    # FOV は mm 単位
    return meta["fov_x_mm"] * 1000.0 / meta["width"]


def to_surface_data(data: bytes) -> Any:
    """PLUX バイトデータから SurfaceData を生成する。

    Returns
    -------
    SurfaceData
    """
    from labvault.parsers._analysis import SurfaceData

    return SurfaceData(
        height_map=decode_height_map(data),
        pixel_size_um=get_pixel_size_um(data),
        optical_image=decode_optical_image(data),
    )


def to_preview_png(data: bytes, *, max_size: int = 512) -> bytes:
    """PLUX バイトデータから光学画像のプレビュー PNG を生成する。"""
    from PIL import Image

    image_array = decode_optical_image(data)
    img = Image.fromarray(image_array)

    if max(img.size) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def diff_height_maps(before_data: bytes, after_data: bytes) -> Any:
    """照射前後の PLUX データから差分高さマップを生成する。

    Returns
    -------
    tuple[numpy.ndarray, float]
        (差分高さマップ (H, W) µm, ピクセルサイズ µm/pixel)
    """
    import numpy as np

    before = decode_height_map(before_data)
    after = decode_height_map(after_data)

    if before.shape != after.shape:
        raise ValueError(
            f"before/after の画像サイズが異なります: {before.shape} vs {after.shape}"
        )

    pixel_size = get_pixel_size_um(after_data)
    return np.subtract(after, before), pixel_size
