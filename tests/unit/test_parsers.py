"""パーサーおよび共通解析モジュールのテスト。

実データ (data_sample/) は使わず、合成データでテストする。
"""

from __future__ import annotations

import io
import struct
import xml.etree.ElementTree as ET
import zipfile

import pytest

np = pytest.importorskip("numpy", reason="numpy not installed")
pytest.importorskip("scipy", reason="scipy not installed")

from labvault.parsers._analysis import (  # noqa: E402
    CraterMetrics,
    SurfaceData,
    compute_volume,
    correct_tilt,
    detect_crater,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_crater_height_map(
    width: int = 100,
    height: int = 100,
    crater_x: int = 50,
    crater_y: int = 50,
    crater_radius: int = 10,
    crater_depth: float = 1.0,
) -> np.ndarray:
    """中央にガウシアンクレーターを持つ合成高さマップを生成する。"""
    y, x = np.mgrid[0:height, 0:width]
    r2 = (x - crater_x) ** 2 + (y - crater_y) ** 2
    sigma2 = (crater_radius / 2.0) ** 2
    hmap = -crater_depth * np.exp(-r2 / (2.0 * sigma2))
    return hmap.astype(np.float32)


def _make_tilted_height_map(
    width: int = 100, height: int = 100, a: float = 0.01, b: float = -0.005
) -> np.ndarray:
    """傾いた平面を生成する。"""
    rows, cols = np.mgrid[0:height, 0:width]
    return (a * rows + b * cols).astype(np.float32)


def _make_plux_bytes(
    width: int = 64,
    height: int = 48,
    fov_x_mm: float = 0.138,
    fov_y_mm: float = 0.138,
    height_map: np.ndarray | None = None,
    optical: np.ndarray | None = None,
) -> bytes:
    """テスト用の PLUX (ZIP) バイトデータを生成する。"""
    if height_map is None:
        height_map = np.zeros((height, width), dtype=np.float32)
    if optical is None:
        optical = np.zeros((height, width, 3), dtype=np.uint8)

    index_xml = ET.Element("xml")
    ET.SubElement(index_xml, "Version").text = "1.2"
    general = ET.SubElement(index_xml, "GENERAL")
    ET.SubElement(general, "FOV_X").text = str(fov_x_mm)
    ET.SubElement(general, "FOV_Y").text = str(fov_y_mm)
    ET.SubElement(general, "IMAGE_SIZE_X").text = str(width)
    ET.SubElement(general, "IMAGE_SIZE_Y").text = str(height)
    instrument = ET.SubElement(index_xml, "Instrument")
    ET.SubElement(instrument, "Manufacturer").text = "TestMfg"
    ET.SubElement(instrument, "Model").text = "TestModel"
    layer = ET.SubElement(index_xml, "LAYER_0")
    ET.SubElement(layer, "FILENAME_Z").text = "LAYER_0.raw"
    ET.SubElement(layer, "FILENAME_STACK").text = "LAYER_0.stack.raw"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("LAYER_0.raw", height_map.astype(np.float32).tobytes())
        zf.writestr("LAYER_0.stack.raw", optical.astype(np.uint8).tobytes())
        zf.writestr("index.xml", ET.tostring(index_xml, encoding="unicode"))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _analysis tests
# ---------------------------------------------------------------------------


class TestCorrectTilt:
    def test_removes_linear_tilt(self) -> None:
        tilted = _make_tilted_height_map(100, 100, a=0.05, b=-0.03)
        corrected = correct_tilt(tilted)
        # 補正後はほぼ平坦 (標準偏差が非常に小さい)
        assert np.std(corrected) < 0.01

    def test_preserves_flat_surface(self) -> None:
        flat = np.zeros((50, 50), dtype=np.float32)
        corrected = correct_tilt(flat)
        np.testing.assert_allclose(corrected, 0.0, atol=1e-6)

    def test_preserves_crater_shape(self) -> None:
        crater = _make_crater_height_map(crater_depth=2.0)
        tilted = crater + _make_tilted_height_map(100, 100, a=0.02, b=0.01)
        corrected = correct_tilt(tilted)
        # クレーターの深さがおおむね保存される
        assert np.min(corrected) < -1.5


class TestDetectCrater:
    def test_detects_single_crater(self) -> None:
        hmap = _make_crater_height_map(
            width=100, height=100,
            crater_x=50, crater_y=50,
            crater_radius=10, crater_depth=1.0,
        )
        pixel_size = 0.1  # µm/pixel
        result = detect_crater(hmap, pixel_size, threshold_um=0.1)

        assert result is not None
        assert isinstance(result, CraterMetrics)
        assert result.depth_um > 0.5
        assert result.diameter_um > 0.5
        assert result.volume_um3 > 0
        assert result.area_um2 > 0

    def test_returns_none_for_flat(self) -> None:
        flat = np.zeros((50, 50), dtype=np.float32)
        result = detect_crater(flat, 0.1, threshold_um=0.1)
        assert result is None

    def test_center_position(self) -> None:
        hmap = _make_crater_height_map(
            width=200, height=200,
            crater_x=150, crater_y=100,
            crater_radius=15, crater_depth=2.0,
        )
        pixel_size = 0.05
        result = detect_crater(hmap, pixel_size, threshold_um=0.1)
        assert result is not None
        # 中心位置がおおむね正しい (±2µm)
        assert abs(result.center_x_um - 150 * pixel_size) < 2.0
        assert abs(result.center_y_um - 100 * pixel_size) < 2.0


class TestComputeVolume:
    def test_positive_volume(self) -> None:
        hmap = _make_crater_height_map(crater_depth=1.0)
        vol = compute_volume(hmap, pixel_size_um=0.1)
        assert vol > 0

    def test_flat_has_zero_volume(self) -> None:
        flat = np.zeros((50, 50), dtype=np.float32)
        vol = compute_volume(flat, pixel_size_um=0.1)
        assert vol == pytest.approx(0.0, abs=1e-6)

    def test_with_mask(self) -> None:
        hmap = _make_crater_height_map(
            crater_x=50, crater_y=50, crater_radius=10, crater_depth=1.0
        )
        mask = hmap < -0.1
        vol = compute_volume(hmap, pixel_size_um=0.1, mask=mask)
        assert vol > 0


# ---------------------------------------------------------------------------
# PLUX parser tests
# ---------------------------------------------------------------------------


class TestPluxParser:
    def test_parse_index(self) -> None:
        from labvault.parsers.plux import parse_index

        data = _make_plux_bytes(width=64, height=48, fov_x_mm=0.2, fov_y_mm=0.15)
        meta = parse_index(data)
        assert meta["width"] == 64
        assert meta["height"] == 48
        assert meta["fov_x_mm"] == pytest.approx(0.2)
        assert meta["fov_y_mm"] == pytest.approx(0.15)
        assert meta["manufacturer"] == "TestMfg"

    def test_decode_height_map(self) -> None:
        from labvault.parsers.plux import decode_height_map

        original = np.random.randn(48, 64).astype(np.float32)
        data = _make_plux_bytes(width=64, height=48, height_map=original)
        result = decode_height_map(data)
        np.testing.assert_allclose(result, original, atol=1e-6)

    def test_decode_optical_image(self) -> None:
        from labvault.parsers.plux import decode_optical_image

        original = np.random.randint(0, 255, (48, 64, 3), dtype=np.uint8)
        data = _make_plux_bytes(width=64, height=48, optical=original)
        result = decode_optical_image(data)
        np.testing.assert_array_equal(result, original)

    def test_get_pixel_size_um(self) -> None:
        from labvault.parsers.plux import get_pixel_size_um

        data = _make_plux_bytes(width=100, height=80, fov_x_mm=0.1)
        pixel_size = get_pixel_size_um(data)
        # 0.1mm = 100µm, 100 pixels → 1.0 µm/pixel
        assert pixel_size == pytest.approx(1.0)

    def test_to_surface_data(self) -> None:
        from labvault.parsers.plux import to_surface_data

        hmap = np.ones((48, 64), dtype=np.float32) * 5.0
        data = _make_plux_bytes(width=64, height=48, height_map=hmap)
        sd = to_surface_data(data)
        assert isinstance(sd, SurfaceData)
        assert sd.height_map.shape == (48, 64)
        assert sd.optical_image is not None
        assert sd.pixel_size_um > 0

    def test_diff_height_maps(self) -> None:
        from labvault.parsers.plux import diff_height_maps

        before_hmap = np.zeros((48, 64), dtype=np.float32)
        after_hmap = np.ones((48, 64), dtype=np.float32) * -0.5
        before_data = _make_plux_bytes(width=64, height=48, height_map=before_hmap)
        after_data = _make_plux_bytes(width=64, height=48, height_map=after_hmap)

        diff, pixel_size = diff_height_maps(before_data, after_data)
        np.testing.assert_allclose(diff, -0.5, atol=1e-6)
        assert pixel_size > 0

    def test_to_preview_png(self) -> None:
        from labvault.parsers.plux import to_preview_png

        optical = np.random.randint(0, 255, (48, 64, 3), dtype=np.uint8)
        data = _make_plux_bytes(width=64, height=48, optical=optical)
        png = to_preview_png(data)
        assert png[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# VK4 parser tests
# ---------------------------------------------------------------------------


def _make_vk4_bytes_minimal(
    width: int = 32, height: int = 24
) -> tuple[bytes, np.ndarray]:
    """最低限の光学画像を持つ VK4 バイトデータを生成する。"""
    image = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    bgr = image[:, :, ::-1]  # RGB → BGR
    pixel_data = bgr.tobytes()
    # ブロックヘッダ: width, height, 0, 0, total_bytes
    block_header = struct.pack("<IIIII", width, height, 0, 0, len(pixel_data))
    block = block_header + pixel_data

    # 光学画像ブロックの開始位置
    offset = 300  # ヘッダ (264) + パディング

    # ファイルヘッダ: 264 bytes
    header = bytearray(offset)
    # offset to color image at position 16
    struct.pack_into("<I", header, 16, offset)
    # XY scale at 252: 100nm → stored as nm * 1000 = 100000
    struct.pack_into("<I", header, 252, 100000)  # 100 nm
    # Z scale at 260
    struct.pack_into("<I", header, 260, 10000)  # 10 nm

    result = bytes(header) + block
    return result, image


class TestVk4Parser:
    def test_decode_color_image(self) -> None:
        from labvault.parsers.vk4 import decode_color_image

        data, original = _make_vk4_bytes_minimal(32, 24)
        result = decode_color_image(data)
        np.testing.assert_array_equal(result, original)

    def test_get_scale(self) -> None:
        from labvault.parsers.vk4 import get_scale

        data, _ = _make_vk4_bytes_minimal()
        xy, z = get_scale(data)
        assert xy == pytest.approx(100.0)  # 100 nm
        assert z == pytest.approx(10.0)  # 10 nm

    def test_to_preview_png(self) -> None:
        from labvault.parsers.vk4 import to_preview_png

        data, _ = _make_vk4_bytes_minimal(32, 24)
        png = to_preview_png(data)
        assert png[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Integration: PLUX → 解析パイプライン
# ---------------------------------------------------------------------------


class TestPluxAnalysisPipeline:
    def test_full_pipeline(self) -> None:
        """PLUX before/after → 差分 → クレーター検出の全パイプライン。"""
        from labvault.parsers.plux import diff_height_maps

        w, h = 100, 100
        pixel_size_mm = 0.1  # FOV = 0.1mm → 100px → 1 µm/pixel

        # before: 平坦
        before_hmap = np.zeros((h, w), dtype=np.float32)
        # after: 中央にクレーター
        after_hmap = _make_crater_height_map(
            width=w, height=h,
            crater_x=50, crater_y=50,
            crater_radius=8, crater_depth=0.5,
        )

        before_data = _make_plux_bytes(w, h, fov_x_mm=pixel_size_mm, height_map=before_hmap)
        after_data = _make_plux_bytes(w, h, fov_x_mm=pixel_size_mm, height_map=after_hmap)

        diff, pixel_size = diff_height_maps(before_data, after_data)
        assert pixel_size == pytest.approx(1.0)

        corrected = correct_tilt(diff)
        result = detect_crater(corrected, pixel_size, threshold_um=0.05)

        assert result is not None
        assert result.depth_um > 0.3
        assert result.diameter_um > 2.0
        assert result.volume_um3 > 0
