"""labvault 単位記号の標準リストとバリデーション。

接頭辞の ASCII 表記ルール
==========================
SI 接頭辞を ASCII 1文字で表す。大文字/小文字で区別する。

    f = femto  (1e-15)
    p = pico   (1e-12)
    n = nano   (1e-9)
    u = micro  (1e-6)   ※ μ の ASCII 代替
    m = milli  (1e-3)
    c = centi  (1e-2)
    k = kilo   (1e3)
    M = mega   (1e6)
    G = giga   (1e9)
    T = tera   (1e12)

注意: "m" は milli、"M" は Mega。大文字小文字で意味が変わる。
"""

from __future__ import annotations

import warnings
from typing import Final

# ---------------------------------------------------------------------------
# 標準単位セット (frozenset)
# ---------------------------------------------------------------------------
# fmt: off

# === エネルギー ===
ENERGY_UNITS: Final[frozenset[str]] = frozenset({
    "J",            # ジュール
    "mJ",           # ミリジュール
    "uJ",           # マイクロジュール
    "nJ",           # ナノジュール
    "pJ",           # ピコジュール
    "fJ",           # フェムトジュール
    "kJ",           # キロジュール
    "eV",           # 電子ボルト
    "meV",          # ミリ電子ボルト
    "keV",          # キロ電子ボルト
    "MeV",          # メガ電子ボルト
})

# === パワー (仕事率) ===
POWER_UNITS: Final[frozenset[str]] = frozenset({
    "W",            # ワット
    "mW",           # ミリワット
    "uW",           # マイクロワット
    "nW",           # ナノワット
    "kW",           # キロワット
    "MW",           # メガワット
    "GW",           # ギガワット
    "TW",           # テラワット
})

# === 時間 ===
TIME_UNITS: Final[frozenset[str]] = frozenset({
    "s",            # 秒
    "ms",           # ミリ秒
    "us",           # マイクロ秒
    "ns",           # ナノ秒
    "ps",           # ピコ秒
    "fs",           # フェムト秒
    "min",          # 分
    "h",            # 時間
})

# === 周波数・繰り返し率 ===
FREQUENCY_UNITS: Final[frozenset[str]] = frozenset({
    "Hz",           # ヘルツ
    "kHz",          # キロヘルツ
    "MHz",          # メガヘルツ
    "GHz",          # ギガヘルツ
    "THz",          # テラヘルツ
})

# === 長さ ===
LENGTH_UNITS: Final[frozenset[str]] = frozenset({
    "m",            # メートル
    "mm",           # ミリメートル
    "um",           # マイクロメートル
    "nm",           # ナノメートル
    "pm",           # ピコメートル
    "cm",           # センチメートル
    "km",           # キロメートル
    "A",            # オングストローム (Angstrom)
})

# === 面積 ===
AREA_UNITS: Final[frozenset[str]] = frozenset({
    "m^2",          # 平方メートル
    "cm^2",         # 平方センチメートル
    "mm^2",         # 平方ミリメートル
    "um^2",         # 平方マイクロメートル
})

# === 体積 ===
VOLUME_UNITS: Final[frozenset[str]] = frozenset({
    "m^3",          # 立方メートル
    "cm^3",         # 立方センチメートル
    "mm^3",         # 立方ミリメートル
    "um^3",         # 立方マイクロメートル
    "L",            # リットル
    "mL",           # ミリリットル
    "uL",           # マイクロリットル
})

# === 温度 ===
TEMPERATURE_UNITS: Final[frozenset[str]] = frozenset({
    "K",            # ケルビン
    "degC",         # 摂氏 (degree Celsius)
    "degF",         # 華氏 (degree Fahrenheit)
})

# === 圧力 ===
PRESSURE_UNITS: Final[frozenset[str]] = frozenset({
    "Pa",           # パスカル
    "kPa",          # キロパスカル
    "MPa",          # メガパスカル
    "GPa",          # ギガパスカル
    "hPa",          # ヘクトパスカル
    "bar",          # バール
    "mbar",         # ミリバール
    "atm",          # 標準気圧
    "Torr",         # トル
    "mTorr",        # ミリトル
    "psi",          # ポンド毎平方インチ
})

# === 質量 ===
MASS_UNITS: Final[frozenset[str]] = frozenset({
    "kg",           # キログラム
    "g",            # グラム
    "mg",           # ミリグラム
    "ug",           # マイクログラム
    "ng",           # ナノグラム
})

# === 角度 ===
ANGLE_UNITS: Final[frozenset[str]] = frozenset({
    "deg",          # 度
    "rad",          # ラジアン
    "mrad",         # ミリラジアン
    "urad",         # マイクロラジアン
    "sr",           # ステラジアン
})

# === 電圧 ===
VOLTAGE_UNITS: Final[frozenset[str]] = frozenset({
    "V",            # ボルト
    "mV",           # ミリボルト
    "uV",           # マイクロボルト
    "kV",           # キロボルト
})

# === 電流 ===
CURRENT_UNITS: Final[frozenset[str]] = frozenset({
    "A",            # アンペア
    "mA",           # ミリアンペア
    "uA",           # マイクロアンペア
    "nA",           # ナノアンペア
    "pA",           # ピコアンペア
})

# === 抵抗 ===
RESISTANCE_UNITS: Final[frozenset[str]] = frozenset({
    "ohm",          # オーム
    "kohm",         # キロオーム
    "Mohm",         # メガオーム
})

# === 電荷 ===
CHARGE_UNITS: Final[frozenset[str]] = frozenset({
    "C",            # クーロン
    "mC",           # ミリクーロン
    "uC",           # マイクロクーロン
    "nC",           # ナノクーロン
})

# === 電力密度・フルエンス (レーザー加工特有) ===
FLUENCE_UNITS: Final[frozenset[str]] = frozenset({
    "J/cm^2",       # フルエンス (ジュール毎平方センチメートル)
    "mJ/cm^2",      # ミリジュール毎平方センチメートル
    "J/m^2",        # ジュール毎平方メートル
    "W/cm^2",       # パワー密度 (ワット毎平方センチメートル)
    "kW/cm^2",      # キロワット毎平方センチメートル
    "MW/cm^2",      # メガワット毎平方センチメートル
    "GW/cm^2",      # ギガワット毎平方センチメートル
    "W/m^2",        # ワット毎平方メートル
})

# === 表面粗さ・プロファイル ===
ROUGHNESS_UNITS: Final[frozenset[str]] = frozenset({
    # 粗さパラメータ (Ra, Rz 等) は長さ単位 (nm, um) を使用
    # ここではレート・速度系の複合単位のみ
    "um/s",         # マイクロメートル毎秒 (走査速度)
    "mm/s",         # ミリメートル毎秒
    "m/s",          # メートル毎秒
    "mm/min",       # ミリメートル毎分 (加工送り速度)
})

# === 光学 ===
OPTICAL_UNITS: Final[frozenset[str]] = frozenset({
    "dB",           # デシベル
    "dBm",          # デシベルミリワット
    "1/cm",         # 波数 (逆センチメートル)
    "rad/s",        # 角周波数
})

# === 無次元・比率 ===
DIMENSIONLESS_UNITS: Final[frozenset[str]] = frozenset({
    "%",            # パーセント
    "ppm",          # 百万分率
    "ppb",          # 十億分率
    "count",        # カウント (パルス数等)
    "a.u.",         # 任意単位 (arbitrary unit)
    "pixel",        # ピクセル
    "shot",         # ショット数 (レーザーパルス照射回数)
    "pass",         # パス回数 (レーザー走査回数)
})

# fmt: on

# ---------------------------------------------------------------------------
# 全単位の統合セット
# ---------------------------------------------------------------------------
ALL_UNITS: Final[frozenset[str]] = (
    ENERGY_UNITS
    | POWER_UNITS
    | TIME_UNITS
    | FREQUENCY_UNITS
    | LENGTH_UNITS
    | AREA_UNITS
    | VOLUME_UNITS
    | TEMPERATURE_UNITS
    | PRESSURE_UNITS
    | MASS_UNITS
    | ANGLE_UNITS
    | VOLTAGE_UNITS
    | CURRENT_UNITS
    | RESISTANCE_UNITS
    | CHARGE_UNITS
    | FLUENCE_UNITS
    | ROUGHNESS_UNITS
    | OPTICAL_UNITS
    | DIMENSIONLESS_UNITS
)

# カテゴリ名 → 単位セット のマッピング
UNIT_CATEGORIES: Final[dict[str, frozenset[str]]] = {
    "energy": ENERGY_UNITS,
    "power": POWER_UNITS,
    "time": TIME_UNITS,
    "frequency": FREQUENCY_UNITS,
    "length": LENGTH_UNITS,
    "area": AREA_UNITS,
    "volume": VOLUME_UNITS,
    "temperature": TEMPERATURE_UNITS,
    "pressure": PRESSURE_UNITS,
    "mass": MASS_UNITS,
    "angle": ANGLE_UNITS,
    "voltage": VOLTAGE_UNITS,
    "current": CURRENT_UNITS,
    "resistance": RESISTANCE_UNITS,
    "charge": CHARGE_UNITS,
    "fluence": FLUENCE_UNITS,
    "roughness": ROUGHNESS_UNITS,
    "optical": OPTICAL_UNITS,
    "dimensionless": DIMENSIONLESS_UNITS,
}


# ---------------------------------------------------------------------------
# バリデーション
# ---------------------------------------------------------------------------
def validate_unit(unit: str, *, strict: bool = False) -> bool:
    """単位記号が標準リストに含まれるかチェックする。

    Args:
        unit: チェックする単位記号。
        strict: True なら ValueError を送出。False なら warning のみ。

    Returns:
        True なら標準単位。False なら非標準。
    """
    if unit in ALL_UNITS:
        return True

    msg = (
        f"非標準の単位記号です: {unit!r}。"
        f"labvault.core.units.ALL_UNITS に追加するか、正しい記号を確認してください。"
    )
    if strict:
        raise ValueError(msg)
    warnings.warn(msg, UserWarning, stacklevel=2)
    return False


def find_category(unit: str) -> str | None:
    """単位が属するカテゴリ名を返す。見つからなければ None。"""
    for category, units in UNIT_CATEGORIES.items():
        if unit in units:
            return category
    return None
