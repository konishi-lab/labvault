"""顕微鏡データの共通解析モジュール。

VK4 / PLUX 等のパーサーが返す高さマップに対して、
傾き補正・クレーター検出・体積計算を行う。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SurfaceData:
    """パーサーが返す統一データ構造。"""

    height_map: np.ndarray
    """高さマップ (H, W) float, 単位: µm"""

    pixel_size_um: float
    """ピクセルサイズ (µm/pixel)"""

    optical_image: np.ndarray | None = None
    """光学画像 (H, W, 3) uint8, RGB。なければ None"""


@dataclass
class CraterMetrics:
    """クレーター計測結果。"""

    diameter_um: float
    """等価円径 (µm)"""

    depth_um: float
    """最大深さ (µm)、正の値"""

    mean_depth_um: float
    """平均深さ (µm)、正の値"""

    volume_um3: float
    """除去体積 (µm³)"""

    center_x_um: float
    """クレーター中心 X (µm)"""

    center_y_um: float
    """クレーター中心 Y (µm)"""

    bbox_width_um: float
    """バウンディングボックス幅 (µm)"""

    bbox_height_um: float
    """バウンディングボックス高さ (µm)"""

    area_um2: float
    """クレーター面積 (µm²)"""


def correct_tilt(height_map: np.ndarray) -> np.ndarray:
    """平面フィットによる傾き補正。

    最小二乗法で平面 z = ax + by + c をフィットし、差し引く。
    klab-device-library の fix_tilt() と同等。
    """
    h, w = height_map.shape
    rows, cols = np.mgrid[0:h, 0:w]
    # 設計行列 [row, col, 1]
    A = np.column_stack([rows.ravel(), cols.ravel(), np.ones(h * w)])
    z = height_map.ravel()

    # NaN を除外してフィット
    mask = np.isfinite(z)
    if mask.sum() < 3:
        return height_map

    coeffs, *_ = np.linalg.lstsq(A[mask], z[mask], rcond=None)
    plane = coeffs[0] * rows + coeffs[1] * cols + coeffs[2]
    return height_map - plane


def detect_crater(
    height_map: np.ndarray,
    pixel_size_um: float,
    *,
    threshold_um: float = 0.05,
) -> CraterMetrics | None:
    """高さマップからクレーターを検出し、計測値を返す。

    Parameters
    ----------
    height_map:
        傾き補正済みの高さマップ (µm)。差分マップでも単体マップでもよい。
        クレーターは負の値 (凹み) として検出される。
    pixel_size_um:
        ピクセルサイズ (µm/pixel)。
    threshold_um:
        クレーター検出閾値 (µm)。中央値からこの値以上深い領域を検出する。

    Returns
    -------
    CraterMetrics or None
        検出できなかった場合は None。
    """
    from scipy import ndimage

    level = np.nanmedian(height_map)
    mask = height_map < (level - threshold_um)

    labeled, n_features = ndimage.label(mask)
    if n_features == 0:
        return None

    # 最大面積の連結領域をクレーターとする
    sizes = np.bincount(labeled.ravel())
    sizes[0] = 0  # 背景を除外
    crater_label = int(np.argmax(sizes))
    region = labeled == crater_label

    area_pixels = int(region.sum())
    if area_pixels == 0:
        return None

    pixel_area = pixel_size_um**2
    area_um2 = area_pixels * pixel_area

    crater_values = height_map[region]
    max_depth = float(level - np.nanmin(crater_values))
    mean_depth = float(level - np.nanmean(crater_values))

    rows, cols = np.where(region)
    center_y = float(rows.mean() * pixel_size_um)
    center_x = float(cols.mean() * pixel_size_um)
    bbox_h = float((rows.max() - rows.min() + 1) * pixel_size_um)
    bbox_w = float((cols.max() - cols.min() + 1) * pixel_size_um)

    diameter = float(2.0 * np.sqrt(area_um2 / np.pi))

    volume = compute_volume(height_map, pixel_size_um, mask=region)

    return CraterMetrics(
        diameter_um=diameter,
        depth_um=max_depth,
        mean_depth_um=mean_depth,
        volume_um3=volume,
        center_x_um=center_x,
        center_y_um=center_y,
        bbox_width_um=bbox_w,
        bbox_height_um=bbox_h,
        area_um2=area_um2,
    )


def compute_volume(
    height_map: np.ndarray,
    pixel_size_um: float,
    *,
    mask: np.ndarray | None = None,
) -> float:
    """除去体積を計算する (µm³)。

    Parameters
    ----------
    height_map:
        高さマップ (µm)。
    pixel_size_um:
        ピクセルサイズ (µm/pixel)。
    mask:
        クレーター領域のブールマスク。None の場合はエッジ平均を基準にする。
    """
    if mask is not None:
        # マスク外の領域の中央値を基準レベルとする
        outside = height_map[~mask]
        if outside.size == 0:
            return 0.0
        level = float(np.nanmedian(outside))
        diff = level - height_map[mask]
        diff = diff[diff > 0]  # 凹みのみ
        return float(np.sum(diff) * pixel_size_um**2)

    # マスクなし: エッジ平均を基準 (klab-device-library の extract_volume 方式)
    edges = np.concatenate(
        [
            height_map[0, :],
            height_map[1:, -1],
            height_map[-1, :-1],
            height_map[1:-1, 0],
        ]
    )
    level = float(np.nanmean(edges))
    diff = level - height_map
    diff = diff[diff > 0]
    return float(np.sum(diff) * pixel_size_um**2)
