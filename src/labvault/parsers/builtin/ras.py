"""Rigaku .ras XRD ファイルからメタデータを抽出する parser。

ASCII (cp932 / utf-8) のヘッダブロックに `*KEY "VALUE"` または `*KEY VALUE`
形式でメタデータが入っている。読めたものだけ conditions に返す。
"""

from __future__ import annotations

from typing import Any

# .ras ヘッダキー → XRD テンプレートの conditions キー
_RAS_KEY_MAP: dict[str, str] = {
    "HW_XG_TARGET_NAME": "target",
    "HW_XG_WAVE_LENGTH_ALPHA1": "wavelength_A",
    "MEAS_SCAN_START": "two_theta_start_deg",
    "MEAS_SCAN_STOP": "two_theta_end_deg",
    "MEAS_SCAN_SPEED": "scan_speed_deg_per_min",
    "MEAS_SCAN_STEP": "step_deg",
    "FILE_SAMPLE": "sample_name",
}

# 数値として扱うキー
_FLOAT_KEYS = {
    "wavelength_A",
    "two_theta_start_deg",
    "two_theta_end_deg",
    "scan_speed_deg_per_min",
    "step_deg",
}


def _decode(data: bytes) -> str:
    """utf-8 → cp932 → latin-1 (lossy) の順でデコードする。"""
    for enc in ("utf-8", "cp932"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _parse_lines(text: str) -> dict[str, str]:
    """`*KEY "VALUE"` 形式の行を dict に変換する。"""
    pairs: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("*") or line.startswith("*RAS_") or " " not in line:
            continue
        # 先頭の "*" を取り除いてから最初のスペースで分割
        body = line[1:]
        key, _, val = body.partition(" ")
        if not key:
            continue
        # "VALUE" や 'VALUE' のクォートを剥がす
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        # 同じ key が複数回出現する場合は最初の値を採用 (走査範囲の主成分)
        if key not in pairs:
            pairs[key] = val
    return pairs


def parse_ras(data: bytes, file_name: str) -> dict[str, Any]:
    """Rigaku .ras ファイルから XRD テンプレート用 conditions を抽出する。

    Returns
    -------
    dict[str, Any]
        抽出できた conditions のみ含む。失敗キーは黙ってスキップする。
    """
    text = _decode(data)
    raw = _parse_lines(text)

    out: dict[str, Any] = {}
    for ras_key, cond_key in _RAS_KEY_MAP.items():
        if ras_key not in raw:
            continue
        val: Any = raw[ras_key]
        if cond_key in _FLOAT_KEYS:
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
        out[cond_key] = val
    return out
