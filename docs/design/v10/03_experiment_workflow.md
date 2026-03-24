# v10 実験ワークフロー改善

> v9レビュー（S-1〜S-13）を全面反映。
> テンプレートの実用性強化、装置PCからの投入手段、ファイルパーサー、リンクセマンティクス、
> オンボーディングの改善を含む。

---

## 目次

1. [テンプレートv10仕様](#1-テンプレートv10仕様)
2. [キー名正規化ルール](#2-キー名正規化ルール)
3. [装置PCからの投入（4案）](#3-装置pcからの投入4案)
4. [ファイルパーサープラグイン](#4-ファイルパーサープラグイン)
5. [indexed_fieldsによる検索改善](#5-indexed_fieldsによる検索改善)
6. [link()セマンティクス](#6-linkセマンティクス)
7. [ProcessChain](#7-processchain)
8. [典型的な実験パターン](#8-典型的な実験パターン)
9. [オンボーディング](#9-オンボーディング)

---

## 1. テンプレートv10仕様

v9レビュー S-5「装置パラメータの網羅性」、S-9「conditionsのキー名揺れ」への対応。

### 1.1 テンプレートのデータモデル

```python
# src/labvault/core/types.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConditionField:
    """テンプレートの条件フィールド定義。

    型・単位・範囲・別名を定義し、入力の品質を保証する。
    """
    name: str                          # 正規化されたフィールド名（snake_case + 単位サフィックス）
    display_name: str                  # 日本語表示名
    type: str                          # "float", "int", "str", "bool"
    unit: str = ""                     # 単位（"C", "Pa", "deg", "nm" 等）
    required: bool = False             # 必須フィールド
    default: Any = None                # デフォルト値
    min_value: float | None = None     # 最小値（数値の場合）
    max_value: float | None = None     # 最大値（数値の場合）
    choices: list[str] | None = None   # 選択肢（strの場合）
    aliases: list[str] | None = None   # 別名（正規化に使用）
    description: str = ""              # 説明


@dataclass
class FileParserConfig:
    """テンプレートのファイルパーサー設定。"""
    extension: str                     # ".ras", ".dm3", ".wdf" 等
    parser_name: str                   # パーサーの登録名
    auto_extract_conditions: bool = True  # メタデータをconditionsに自動抽出するか


@dataclass
class TemplateV10:
    """v10テンプレート仕様。

    v9からの追加:
    - required_conditions: 必須条件フィールド（close()時に未入力を警告）
    - condition_fields: フィールドごとの型・単位・範囲定義
    - indexed_fields: Firestoreトップレベルに昇格するフィールド（検索高速化）
    - file_parsers: 対応ファイルパーサー設定
    """
    name: str                                        # テンプレート名
    display_name: str                                # 日本語表示名
    description: str = ""                            # テンプレートの説明
    type: str = "experiment"                         # デフォルトのRecordType
    default_tags: list[str] = field(default_factory=list)
    condition_fields: list[ConditionField] = field(default_factory=list)
    required_conditions: list[str] = field(default_factory=list)  # 必須フィールド名のリスト
    recommended_results: list[str] = field(default_factory=list)
    indexed_fields: list[str] = field(default_factory=list)       # Firestoreトップレベル昇格
    file_parsers: list[FileParserConfig] = field(default_factory=list)
```

### 1.2 5テンプレートの完全なフィールド定義

#### テンプレート1: XRD（X線回折）

```python
TEMPLATE_XRD = TemplateV10(
    name="XRD",
    display_name="X線回折",
    description="粉末XRDおよび薄膜XRDの測定テンプレート。2θ-θスキャン、薄膜法対応。",
    type="measurement",
    default_tags=["XRD"],
    condition_fields=[
        ConditionField(
            name="target",
            display_name="X線ターゲット",
            type="str",
            required=True,
            choices=["Cu", "Mo", "Co", "Fe", "Cr"],
            aliases=["x_ray_target", "anode", "tube"],
            description="X線管のターゲット材。CuKα=1.5418Å",
        ),
        ConditionField(
            name="wavelength_A",
            display_name="X線波長",
            type="float",
            unit="A",  # Ångström
            default=1.5418,
            min_value=0.5,
            max_value=3.0,
            aliases=["lambda", "wavelength", "wave_length"],
            description="Kα1の波長。Cu=1.5418, Mo=0.7107, Co=1.7902",
        ),
        ConditionField(
            name="two_theta_start_deg",
            display_name="2θ開始角",
            type="float",
            unit="deg",
            required=True,
            min_value=0.0,
            max_value=170.0,
            aliases=["2theta_start", "start_angle", "theta_start"],
        ),
        ConditionField(
            name="two_theta_end_deg",
            display_name="2θ終了角",
            type="float",
            unit="deg",
            required=True,
            min_value=0.0,
            max_value=170.0,
            aliases=["2theta_end", "end_angle", "theta_end"],
        ),
        ConditionField(
            name="scan_speed_deg_per_min",
            display_name="スキャン速度",
            type="float",
            unit="deg/min",
            min_value=0.01,
            max_value=100.0,
            aliases=["scan_speed", "speed"],
        ),
        ConditionField(
            name="step_deg",
            display_name="ステップ幅",
            type="float",
            unit="deg",
            default=0.02,
            aliases=["step", "step_size", "step_width"],
        ),
        ConditionField(
            name="voltage_kV",
            display_name="管電圧",
            type="float",
            unit="kV",
            default=40.0,
            aliases=["voltage", "tube_voltage", "kV"],
        ),
        ConditionField(
            name="current_mA",
            display_name="管電流",
            type="float",
            unit="mA",
            default=40.0,
            aliases=["current", "tube_current", "mA"],
        ),
        ConditionField(
            name="method",
            display_name="測定法",
            type="str",
            choices=["powder", "thin_film", "grazing_incidence", "in_situ"],
            aliases=["measurement_method", "scan_type"],
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
    ],
    required_conditions=["target", "two_theta_start_deg", "two_theta_end_deg", "sample_name"],
    recommended_results=[
        "peak_positions_deg",    # ピーク位置（2θ、list[float]）
        "d_spacings_A",          # 面間隔（list[float]）
        "lattice_a_A",           # 格子定数a（Å）
        "lattice_c_A",           # 格子定数c（Å）
        "phase",                 # 同定された相
        "crystallinity",         # 結晶性（定性: "good", "poor"）
        "crystallite_size_nm",   # 結晶子サイズ（Scherrer式）
        "preferred_orientation", # 配向性
    ],
    indexed_fields=["target", "method", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".ras", parser_name="ras_parser"),
        FileParserConfig(extension=".raw", parser_name="bruker_raw_parser"),
        FileParserConfig(extension=".xy", parser_name="xy_parser"),
    ],
)
```

#### テンプレート2: SEM（走査型電子顕微鏡）

```python
TEMPLATE_SEM = TemplateV10(
    name="SEM",
    display_name="走査型電子顕微鏡",
    description="SEM観察テンプレート。SE/BSE像、EDS分析対応。",
    type="measurement",
    default_tags=["SEM"],
    condition_fields=[
        ConditionField(
            name="acceleration_voltage_kV",
            display_name="加速電圧",
            type="float",
            unit="kV",
            required=True,
            min_value=0.1,
            max_value=30.0,
            aliases=["acc_voltage", "kV", "voltage", "accel_voltage"],
        ),
        ConditionField(
            name="magnification",
            display_name="倍率",
            type="int",
            required=True,
            min_value=10,
            max_value=1000000,
            aliases=["mag", "zoom"],
        ),
        ConditionField(
            name="working_distance_mm",
            display_name="作動距離",
            type="float",
            unit="mm",
            min_value=1.0,
            max_value=50.0,
            aliases=["WD", "wd", "working_dist"],
        ),
        ConditionField(
            name="detector",
            display_name="検出器",
            type="str",
            choices=["SE", "BSE", "InLens", "EDS", "EBSD"],
            aliases=["det", "signal"],
            description="SE=二次電子、BSE=反射電子、InLens=レンズ内検出器",
        ),
        ConditionField(
            name="coating",
            display_name="コーティング",
            type="str",
            choices=["none", "Au", "Pt", "Pt-Pd", "C", "Os"],
            default="none",
            aliases=["sputter_coating"],
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
        ConditionField(
            name="instrument",
            display_name="装置名",
            type="str",
            aliases=["machine", "model", "sem_model"],
        ),
    ],
    required_conditions=["acceleration_voltage_kV", "magnification", "sample_name"],
    recommended_results=[
        "morphology",          # 形態の記述（テキスト）
        "particle_size_nm",    # 粒径（nm）
        "grain_size_um",       # 結晶粒径（μm）
        "porosity_percent",    # 気孔率（%）
        "composition",         # EDS組成（dict）
    ],
    indexed_fields=["acceleration_voltage_kV", "magnification", "detector", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".tif", parser_name="sem_tiff_parser"),
        FileParserConfig(extension=".tiff", parser_name="sem_tiff_parser"),
        FileParserConfig(extension=".dm3", parser_name="dm3_parser"),
        FileParserConfig(extension=".dm4", parser_name="dm4_parser"),
    ],
)
```

#### テンプレート3: SQUID（磁気特性測定）

```python
TEMPLATE_SQUID = TemplateV10(
    name="SQUID",
    display_name="SQUID磁化測定",
    description="SQUID/VSM磁化測定テンプレート。M-H曲線、M-T曲線対応。",
    type="measurement",
    default_tags=["SQUID", "magnetic"],
    condition_fields=[
        ConditionField(
            name="measurement_type",
            display_name="測定タイプ",
            type="str",
            required=True,
            choices=["M-H", "M-T", "AC-susceptibility", "ZFC-FC"],
            aliases=["meas_type", "mode"],
        ),
        ConditionField(
            name="temperature_K",
            display_name="測定温度",
            type="float",
            unit="K",
            min_value=1.8,
            max_value=1000.0,
            aliases=["temp", "T", "temperature"],
            description="M-H測定時の温度。M-T測定ではstart/endを使用",
        ),
        ConditionField(
            name="temperature_start_K",
            display_name="温度開始",
            type="float",
            unit="K",
            min_value=1.8,
            max_value=1000.0,
            aliases=["T_start", "temp_start"],
        ),
        ConditionField(
            name="temperature_end_K",
            display_name="温度終了",
            type="float",
            unit="K",
            min_value=1.8,
            max_value=1000.0,
            aliases=["T_end", "temp_end"],
        ),
        ConditionField(
            name="field_max_Oe",
            display_name="最大磁場",
            type="float",
            unit="Oe",
            min_value=0,
            max_value=70000,
            aliases=["H_max", "max_field", "field"],
        ),
        ConditionField(
            name="sample_mass_mg",
            display_name="試料質量",
            type="float",
            unit="mg",
            required=True,
            min_value=0.01,
            aliases=["mass", "weight", "sample_weight"],
            description="磁化量の正規化に必要。必ず秤量すること。",
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
        ConditionField(
            name="instrument",
            display_name="装置名",
            type="str",
            choices=["MPMS3", "MPMS-XL", "PPMS-VSM", "VersaLab"],
            aliases=["machine", "model"],
        ),
    ],
    required_conditions=["measurement_type", "sample_mass_mg", "sample_name"],
    recommended_results=[
        "saturation_magnetization_emu_per_g",  # 飽和磁化
        "remanence_emu_per_g",                  # 残留磁化
        "coercivity_Oe",                        # 保磁力
        "curie_temperature_K",                  # キュリー温度
        "neel_temperature_K",                   # ネール温度
        "magnetic_moment_uB",                   # 磁気モーメント
        "susceptibility_emu_per_mol_Oe",        # 帯磁率
    ],
    indexed_fields=["measurement_type", "temperature_K", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".dat", parser_name="mpms_dat_parser"),
        FileParserConfig(extension=".rso", parser_name="mpms_rso_parser"),
    ],
)
```

#### テンプレート4: TEM（透過型電子顕微鏡）

```python
TEMPLATE_TEM = TemplateV10(
    name="TEM",
    display_name="透過型電子顕微鏡",
    description="TEM/STEM観察テンプレート。明視野/暗視野/回折パターン/HAADF-STEM対応。",
    type="measurement",
    default_tags=["TEM"],
    condition_fields=[
        ConditionField(
            name="acceleration_voltage_kV",
            display_name="加速電圧",
            type="float",
            unit="kV",
            required=True,
            choices_hint=[80, 100, 120, 200, 300],
            aliases=["acc_voltage", "kV", "voltage"],
        ),
        ConditionField(
            name="imaging_mode",
            display_name="撮像モード",
            type="str",
            required=True,
            choices=["BF", "DF", "HAADF-STEM", "ABF-STEM", "diffraction", "HRTEM"],
            aliases=["mode", "observation_mode"],
            description="BF=明視野、DF=暗視野、HAADF=高角散乱暗視野、HRTEM=高分解能",
        ),
        ConditionField(
            name="camera_length_mm",
            display_name="カメラ長",
            type="float",
            unit="mm",
            aliases=["CL", "camera_length"],
            description="回折パターン撮影時のカメラ長",
        ),
        ConditionField(
            name="specimen_preparation",
            display_name="試料作製法",
            type="str",
            choices=["ion_milling", "FIB", "ultramicrotome", "crushing", "electropolishing"],
            aliases=["prep", "preparation"],
        ),
        ConditionField(
            name="zone_axis",
            display_name="晶帯軸",
            type="str",
            aliases=["ZA", "zone"],
            description="回折パターンの晶帯軸。例: [001], [110]",
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
        ConditionField(
            name="instrument",
            display_name="装置名",
            type="str",
            aliases=["machine", "model", "tem_model"],
        ),
    ],
    required_conditions=["acceleration_voltage_kV", "imaging_mode", "sample_name"],
    recommended_results=[
        "d_spacings_A",            # 面間隔
        "crystal_structure",       # 結晶構造
        "lattice_parameter_A",     # 格子定数
        "defect_density_per_cm2",  # 欠陥密度
        "grain_size_nm",           # 結晶粒径
        "composition",             # EDS/EELS組成
    ],
    indexed_fields=["acceleration_voltage_kV", "imaging_mode", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".dm3", parser_name="dm3_parser"),
        FileParserConfig(extension=".dm4", parser_name="dm4_parser"),
        FileParserConfig(extension=".emd", parser_name="emd_parser"),
    ],
)
```

#### テンプレート5: Raman（ラマン分光）

```python
TEMPLATE_RAMAN = TemplateV10(
    name="Raman",
    display_name="ラマン分光",
    description="ラマン分光測定テンプレート。単点測定、マッピング対応。",
    type="measurement",
    default_tags=["Raman"],
    condition_fields=[
        ConditionField(
            name="laser_wavelength_nm",
            display_name="レーザー波長",
            type="float",
            unit="nm",
            required=True,
            choices_hint=[325, 488, 514, 532, 633, 785, 1064],
            aliases=["wavelength", "laser", "excitation"],
        ),
        ConditionField(
            name="laser_power_mW",
            display_name="レーザー出力",
            type="float",
            unit="mW",
            min_value=0.01,
            max_value=500.0,
            aliases=["power", "laser_power"],
        ),
        ConditionField(
            name="objective",
            display_name="対物レンズ",
            type="str",
            choices=["5x", "10x", "20x", "50x", "100x"],
            aliases=["lens", "magnification"],
        ),
        ConditionField(
            name="grating_lines_per_mm",
            display_name="回折格子",
            type="int",
            unit="lines/mm",
            choices_hint=[300, 600, 1200, 1800, 2400],
            aliases=["grating", "groove"],
        ),
        ConditionField(
            name="exposure_sec",
            display_name="露光時間",
            type="float",
            unit="sec",
            min_value=0.1,
            aliases=["exposure", "integration_time"],
        ),
        ConditionField(
            name="accumulations",
            display_name="積算回数",
            type="int",
            default=1,
            min_value=1,
            aliases=["accum", "scans", "num_scans"],
        ),
        ConditionField(
            name="spectral_range_cm_inv",
            display_name="スペクトル範囲",
            type="str",
            aliases=["range", "wavenumber_range"],
            description="例: '100-3000' (cm^-1)",
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
    ],
    required_conditions=["laser_wavelength_nm", "sample_name"],
    recommended_results=[
        "peak_positions_cm_inv",     # ピーク位置（cm^-1、list[float]）
        "peak_assignments",          # ピーク帰属（list[str]）
        "d_band_cm_inv",             # Dバンド位置（炭素系）
        "g_band_cm_inv",             # Gバンド位置（炭素系）
        "id_ig_ratio",               # ID/IG比（炭素系）
        "fwhm_cm_inv",               # 半値全幅（代表ピーク）
        "phase_identification",      # 相同定
    ],
    indexed_fields=["laser_wavelength_nm", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".wdf", parser_name="wdf_parser"),
        FileParserConfig(extension=".spc", parser_name="spc_parser"),
        FileParserConfig(extension=".txt", parser_name="raman_txt_parser"),
    ],
)
```

### 1.3 テンプレート適用時のバリデーション

```python
# src/labvault/core/template_validator.py
from __future__ import annotations

import warnings
from typing import Any

from .types import TemplateV10, ConditionField
from .exceptions import LabvaultTemplateError


def validate_conditions(
    template: TemplateV10,
    conditions: dict[str, Any],
    on_close: bool = False,
) -> list[str]:
    """テンプレートに基づいて条件をバリデーションする。

    Args:
        template: テンプレート定義
        conditions: 入力された条件
        on_close: True の場合、required_conditionsの未入力を警告

    Returns:
        警告メッセージのリスト
    """
    warnings_list = []

    for field_def in template.condition_fields:
        value = conditions.get(field_def.name)

        # 必須チェック（close時のみ）
        if on_close and field_def.name in template.required_conditions:
            if value is None:
                warnings_list.append(
                    f"必須条件 '{field_def.display_name}' ({field_def.name}) が未入力です"
                )
                continue

        if value is None:
            continue

        # 型チェック
        if field_def.type == "float" and not isinstance(value, (int, float)):
            warnings_list.append(
                f"'{field_def.display_name}' は数値を期待しますが、{type(value).__name__} が入力されました"
            )

        # 範囲チェック
        if isinstance(value, (int, float)):
            if field_def.min_value is not None and value < field_def.min_value:
                warnings_list.append(
                    f"'{field_def.display_name}' = {value} は最小値 {field_def.min_value} を下回っています"
                )
            if field_def.max_value is not None and value > field_def.max_value:
                warnings_list.append(
                    f"'{field_def.display_name}' = {value} は最大値 {field_def.max_value} を超えています"
                )

        # 選択肢チェック
        if field_def.choices and value not in field_def.choices:
            warnings_list.append(
                f"'{field_def.display_name}' = '{value}' は推奨値 {field_def.choices} に含まれません"
            )

    return warnings_list


def normalize_conditions(
    template: TemplateV10,
    conditions: dict[str, Any],
) -> dict[str, Any]:
    """エイリアスを正規化名に変換する。

    例: {"temp": 300, "2theta_start": 20} → {"temperature_K": 300, "two_theta_start_deg": 20}
    """
    # エイリアス→正規名のマッピングを構築
    alias_map: dict[str, str] = {}
    for field_def in template.condition_fields:
        if field_def.aliases:
            for alias in field_def.aliases:
                alias_map[alias.lower()] = field_def.name

    # 正規化
    normalized = {}
    for key, value in conditions.items():
        normalized_key = alias_map.get(key.lower(), key)
        normalized[normalized_key] = value

    return normalized
```

---

## 2. キー名正規化ルール

v9レビュー S-9「conditionsのキー名揺れ」への対応。

### 2.1 正規化ルール

| ルール | 例 | 説明 |
|--------|-----|------|
| **snake_case統一** | `temperature_C` | 全てsnake_case。CamelCase・ケバブケースは自動変換 |
| **単位サフィックス** | `_C`, `_K`, `_Pa`, `_deg`, `_nm`, `_A`, `_kV`, `_mA` | フィールド名の末尾に単位を付ける |
| **aliases自動正規化** | `temp` → `temperature_C` | テンプレートのaliasesに基づいて自動変換 |
| **日本語キー禁止** | `温度` → `temperature_C` | キー名は英語のみ。値は日本語OK |

### 2.2 単位サフィックス一覧

| サフィックス | 単位 | 例 |
|------------|------|-----|
| `_C` | 摂氏度 | `temperature_C`, `substrate_temperature_C` |
| `_K` | ケルビン | `temperature_K`, `curie_temperature_K` |
| `_Pa` | パスカル | `pressure_Pa`, `base_pressure_Pa` |
| `_Torr` | トール | `pressure_Torr` |
| `_deg` | 度 | `two_theta_start_deg`, `angle_deg` |
| `_nm` | ナノメートル | `thickness_nm`, `wavelength_nm` |
| `_um` | マイクロメートル | `grain_size_um` |
| `_A` | オングストローム | `lattice_a_A`, `d_spacing_A` |
| `_kV` | キロボルト | `acceleration_voltage_kV`, `voltage_kV` |
| `_mA` | ミリアンペア | `current_mA` |
| `_Oe` | エルステッド | `coercivity_Oe`, `field_max_Oe` |
| `_emu_per_g` | emu/g | `saturation_magnetization_emu_per_g` |
| `_mW` | ミリワット | `laser_power_mW` |
| `_sec` | 秒 | `exposure_sec`, `duration_sec` |
| `_min` | 分 | `deposition_time_min` |
| `_cm_inv` | cm^-1 | `peak_positions_cm_inv` |

### 2.3 自動正規化の実装

```python
# src/labvault/core/normalize.py
import re
from typing import Any


def normalize_key(key: str) -> str:
    """フィールド名をsnake_caseに正規化する。

    変換ルール:
    1. CamelCase → snake_case
    2. ケバブケース → snake_case
    3. スペース → アンダースコア
    4. 連続アンダースコア → 単一
    5. 先頭末尾アンダースコア除去
    """
    # CamelCase → snake_case
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", key)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)

    # ケバブケース・スペース → アンダースコア
    s = s.replace("-", "_").replace(" ", "_")

    # 小文字化
    s = s.lower()

    # 連続アンダースコア → 単一
    s = re.sub(r"_+", "_", s)

    # 先頭末尾アンダースコア除去
    s = s.strip("_")

    return s


def normalize_conditions(conditions: dict[str, Any]) -> dict[str, Any]:
    """全キーをsnake_caseに正規化する。"""
    return {normalize_key(k): v for k, v in conditions.items()}
```

---

## 3. 装置PCからの投入（4案）

v9レビュー S-1「装置操作からデータ記録までのギャップ」、S-4「装置PC(Windows)での利用」への対応。

### 3.1 4案の比較

| # | 方式 | マイルストーン | 装置PC要件 | 利点 | 制限 |
|---|------|-------------|-----------|------|------|
| 1 | **Nextcloud _inbox** (推奨) | M2 | ブラウザのみ | 何もインストール不要 | 15分の検出遅延 |
| 2 | **QRコード + スマホ** | M2 | スマホ | 装置PCすら不要 | 小ファイルのみ |
| 3 | **CLIバイナリ (PyInstaller)** | M3 | なし（.exeを配布） | リアルタイム、大ファイル対応 | 管理者がexe配置を許可する必要 |
| 4 | **メール投入** | M4以降 | メールクライアント | 最もハードル低い | 添付ファイルサイズ制限 |

### 3.2 案1: Nextcloud _inbox（推奨、M2）

```
装置PC（Windows、ブラウザのみ）
    │
    │ (1) Nextcloudにブラウザでアクセス
    │     https://nextcloud.example.ac.jp
    │
    │ (2) _inbox/{record_id}/ フォルダにファイルをドラッグ&ドロップ
    │     例: _inbox/AB3F/xrd_data.ras
    │
    ▼
Nextcloud (ファイルシステム)
    │
    │ (3) 15分毎のポーラーが検出
    ▼
Cloud Functions (nextcloud-poller)
    │
    │ (4) ファイルを正規パスに移動
    │     _inbox/AB3F/xrd_data.ras → labvault/{team_id}/AB3F/xrd_data.ras
    │
    │ (5) Firestoreにメタデータ登録
    │     data_refs にファイル情報を追加
    │
    │ (6) ファイルパーサー適用（.rasの場合 → XRD条件自動抽出）
    │
    │ (7) embedding再生成
    ▼
完了（SDKやClaude Desktopから参照可能に）
```

**_inbox の命名規約**:

```
Nextcloudのグループフォルダ/
├── labvault/
│   └── {team_id}/
│       ├── _inbox/              ← 投入用フォルダ
│       │   ├── AB3F/            ← レコードID名のフォルダ
│       │   │   ├── xrd_data.ras
│       │   │   └── sem_image.tif
│       │   └── NEW/             ← "NEW" は新規レコード自動作成
│       │       └── measurement_20260317.csv
│       ├── AB3F/                ← 正規保存先
│       │   ├── xrd_data.ras
│       │   └── sem_image.tif
│       └── KL67/
```

**ポーラーの実装**:

```python
# functions/nextcloud_poller/main.py
import functions_framework
from shared.nextcloud import NextcloudClient


@functions_framework.http
def poller_handler(request):
    """Nextcloud _inboxフォルダを監視し、新規ファイルを検出・処理する。"""
    nc = _get_nextcloud_client()
    db = _get_firestore_client()

    # 全チームの_inboxをスキャン
    teams = _get_all_teams(db)

    processed = 0
    for team_id in teams:
        inbox_path = f"labvault/{team_id}/_inbox"

        if not nc.exists(inbox_path):
            continue

        # _inbox直下のフォルダ一覧（各フォルダ = レコードID or "NEW"）
        folders = nc.list_files(inbox_path)

        for folder_href in folders:
            folder_name = folder_href.rstrip("/").split("/")[-1]

            if folder_name == "_inbox":
                continue  # 自身をスキップ

            # フォルダ内のファイル一覧
            files = nc.list_files(f"{inbox_path}/{folder_name}")

            for file_href in files:
                filename = file_href.rstrip("/").split("/")[-1]
                if filename.startswith(".") or filename == folder_name:
                    continue

                # レコードIDの決定
                if folder_name == "NEW":
                    # 新規レコード作成
                    from labvault.core.id import generate_id
                    record_id = generate_id()
                    _create_record_from_inbox(db, team_id, record_id, filename)
                else:
                    record_id = folder_name

                # ファイルを正規パスに移動
                src = f"{inbox_path}/{folder_name}/{filename}"
                dst = f"labvault/{team_id}/{record_id}/{filename}"
                _move_file(nc, src, dst)

                # Firestoreにdata_ref登録
                _register_data_ref(db, team_id, record_id, filename, dst)

                # ファイルパーサー適用
                _apply_parser(nc, db, team_id, record_id, filename, dst)

                processed += 1

    return {"status": "ok", "processed": processed}, 200
```

### 3.3 案2: QRコード + スマホ（M2）

```
実験者のスマホ
    │
    │ (1) Notebook or CLIでQRコードを表示
    │     lab.qr("AB3F")
    │     → QRコード表示（Nextcloud共有リンク + レコードID）
    │
    │ (2) スマホのカメラでQRを読み取り
    │     → Nextcloudの_inboxフォルダが開く
    │
    │ (3) スマホで撮影した写真を直接アップロード
    │     例: サンプル外観写真、実験ノートの写真
    │
    ▼
Nextcloud _inbox
    │
    │ ポーラーで自動処理（案1と同じフロー）
    ▼
完了
```

```python
# src/labvault/core/lab.py

def qr(self, record_id: str) -> None:
    """レコードのNextcloud _inboxへのQRコードを表示する。

    JupyterLab環境ではインラインで表示。
    ターミナル環境ではASCII QRコードで表示。
    """
    inbox_url = (
        f"{self._settings.nextcloud_url}/apps/files/"
        f"?dir=/labvault/{self.team}/_inbox/{record_id}"
    )

    try:
        import qrcode
        from IPython.display import display, Image as IPImage
        import io

        # Notebook環境: 画像QRコード
        qr_img = qrcode.make(inbox_url)
        buf = io.BytesIO()
        qr_img.save(buf, format="PNG")
        buf.seek(0)
        display(IPImage(data=buf.read(), width=200))
        print(f"レコード {record_id} の投入URL:")
        print(inbox_url)

    except ImportError:
        # ターミナル環境: URLのみ表示
        print(f"レコード {record_id} の投入URL:")
        print(inbox_url)
        print("上記URLにブラウザでアクセスし、ファイルをアップロードしてください。")
```

### 3.4 案3: CLIバイナリ PyInstaller（M3）

```bash
# 装置PCにPython不要。スタンドアロンexeを配布。

# ビルド（開発PCで実行）
pyinstaller --onefile \
  --name=labvault \
  --hidden-import=labvault.cli \
  src/labvault/cli/main.py

# 配布
# → dist/labvault.exe を装置PCに配置（USBメモリ or ネットワーク共有）

# 装置PCでの使用
labvault.exe add AB3F xrd_data.ras
labvault.exe add AB3F sem_images/
```

**最小限CLI（装置PC用）**:

```python
# src/labvault/cli/minimal.py
"""装置PC向けの最小限CLI。

PyInstallerでスタンドアロンexeにビルド可能。
依存: httpx のみ（Nextcloud WebDAV直接アップロード）。
Firestore不要、GCP不要。
"""
import sys
from pathlib import Path

import click
import httpx


@click.group()
def cli():
    """labvault 装置PC用ファイル投入ツール"""
    pass


@cli.command()
@click.argument("record_id")
@click.argument("files", nargs=-1, type=click.Path(exists=True))
@click.option("--config", type=click.Path(), default=None,
              help="設定ファイルのパス")
def add(record_id: str, files: tuple[str, ...], config: str | None):
    """ファイルをレコードに追加する。

    使用例:
      labvault add AB3F xrd_data.ras
      labvault add AB3F *.tif
      labvault add AB3F data_folder/
    """
    settings = _load_config(config)

    for file_path in files:
        p = Path(file_path)

        if p.is_dir():
            # ディレクトリの場合、再帰的にアップロード
            for f in p.rglob("*"):
                if f.is_file():
                    _upload_file(settings, record_id, f)
        else:
            _upload_file(settings, record_id, p)

    click.echo(f"完了: {len(files)} ファイルを {record_id} にアップロードしました")


def _upload_file(settings: dict, record_id: str, local_path: Path):
    """Nextcloud _inboxにファイルをアップロードする。"""
    remote_path = (
        f"{settings['nextcloud_group_folder']}/labvault/"
        f"{settings['team']}/_inbox/{record_id}/{local_path.name}"
    )
    webdav_url = (
        f"{settings['nextcloud_url']}/remote.php/dav/files/"
        f"{settings['nextcloud_user']}/{remote_path}"
    )

    with httpx.Client(auth=(settings["nextcloud_user"], settings["nextcloud_password"])) as client:
        # 親ディレクトリ作成
        parent_url = webdav_url.rsplit("/", 1)[0]
        client.request("MKCOL", parent_url)

        # ファイルアップロード
        data = local_path.read_bytes()
        response = client.put(webdav_url, content=data)
        response.raise_for_status()

    click.echo(f"  アップロード: {local_path.name} ({len(data)} bytes)")
```

### 3.5 案4: メール投入（M4以降）

```
装置PC or スマホ
    │
    │ メール送信
    │ To: lab@konishi-lab.example.ac.jp
    │ Subject: AB3F (レコードID)
    │ 添付: xrd_data.ras
    │
    ▼
Cloud Functions (メールトリガー or Gmail API)
    │
    │ (1) メール受信 → 添付ファイル抽出
    │ (2) SubjectからレコードID解決
    │ (3) Nextcloudに保存 + Firestore登録
    ▼
完了
```

M4以降のスコープ。メール送信は装置PCの制限が最も少ない（メールクライアントは大抵入っている）。

---

## 4. ファイルパーサープラグイン

v9レビュー S-2「測定装置固有ファイル形式への対応」への対応。

### 4.1 FileParser Protocol

```python
# src/labvault/parsers/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class ParseResult:
    """ファイルパーサーの結果。"""
    conditions: dict[str, Any] = field(default_factory=dict)  # 抽出された測定条件
    metadata: dict[str, Any] = field(default_factory=dict)    # その他のメタデータ
    preview: dict[str, Any] = field(default_factory=dict)     # プレビュー情報
    errors: list[str] = field(default_factory=list)           # パースエラー


@runtime_checkable
class FileParser(Protocol):
    """ファイルパーサーのプロトコル。"""

    @property
    def name(self) -> str:
        """パーサーの登録名。"""
        ...

    @property
    def extensions(self) -> list[str]:
        """対応する拡張子のリスト（ドット付き）。例: [".ras", ".raw"]"""
        ...

    @property
    def description(self) -> str:
        """パーサーの説明。"""
        ...

    def parse(self, file_path: Path) -> ParseResult:
        """ファイルをパースし、メタデータを抽出する。

        Args:
            file_path: パース対象のファイルパス

        Returns:
            ParseResult: 抽出された条件・メタデータ・プレビュー
        """
        ...

    def can_parse(self, file_path: Path) -> bool:
        """このパーサーが対象ファイルをパース可能か判定する。

        拡張子だけでなく、マジックバイトなどでも判定可能。
        """
        ...
```

### 4.2 ParserRegistry

```python
# src/labvault/parsers/registry.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import FileParser, ParseResult


class ParserRegistry:
    """ファイルパーサーの登録・検索。

    ビルトインパーサーは自動登録。
    ユーザー定義パーサーは register() で追加可能。
    """

    def __init__(self) -> None:
        self._parsers: dict[str, FileParser] = {}  # {name: parser}
        self._extension_map: dict[str, list[str]] = {}  # {.ext: [parser_names]}

        # ビルトインパーサーの登録
        self._register_builtins()

    def register(self, parser: FileParser) -> None:
        """パーサーを登録する。"""
        self._parsers[parser.name] = parser
        for ext in parser.extensions:
            if ext not in self._extension_map:
                self._extension_map[ext] = []
            self._extension_map[ext].append(parser.name)

    def parse(self, file_path: Path) -> ParseResult | None:
        """ファイルを自動判定してパースする。

        対応するパーサーが見つからない場合はNoneを返す。
        """
        ext = file_path.suffix.lower()

        # 拡張子からパーサー候補を取得
        parser_names = self._extension_map.get(ext, [])

        for name in parser_names:
            parser = self._parsers[name]
            if parser.can_parse(file_path):
                try:
                    return parser.parse(file_path)
                except Exception as e:
                    return ParseResult(errors=[f"パースエラー ({name}): {e}"])

        return None

    def get_parser(self, name: str) -> FileParser | None:
        """名前でパーサーを取得する。"""
        return self._parsers.get(name)

    def list_parsers(self) -> list[dict[str, Any]]:
        """登録済みパーサーの一覧。"""
        return [
            {
                "name": p.name,
                "extensions": p.extensions,
                "description": p.description,
            }
            for p in self._parsers.values()
        ]

    def _register_builtins(self) -> None:
        """ビルトインパーサーを登録する。"""
        from .ras_parser import RasParser
        from .tiff_parser import SemTiffParser

        self.register(RasParser())
        self.register(SemTiffParser())
        # 以下はM3以降で追加
        # self.register(Dm3Parser())
        # self.register(WdfParser())
        # self.register(MpmsDatParser())


# グローバルレジストリ
_registry = ParserRegistry()


def get_registry() -> ParserRegistry:
    """グローバルパーサーレジストリを取得する。"""
    return _registry
```

### 4.3 ビルトインRasParser実装例

```python
# src/labvault/parsers/ras_parser.py
"""Rigaku .ras ファイルパーサー。

RAS (Rigaku Automated System) ファイルフォーマット:
- ヘッダー部: *RAS_HEADER_START 〜 *RAS_HEADER_END
- データ部: *RAS_DATA_START 〜 *RAS_DATA_END
- ヘッダーにはキー=値 形式で測定条件が記録されている
"""
from __future__ import annotations

from pathlib import Path

from .base import FileParser, ParseResult


class RasParser:
    """Rigaku .ras ファイルパーサー。

    XRDの測定データと条件を自動抽出する。
    """

    @property
    def name(self) -> str:
        return "ras_parser"

    @property
    def extensions(self) -> list[str]:
        return [".ras"]

    @property
    def description(self) -> str:
        return "Rigaku XRD .ras ファイルから測定条件（ターゲット、2θ範囲、管電圧/電流等）を自動抽出"

    def can_parse(self, file_path: Path) -> bool:
        """マジックバイトで判定。"""
        try:
            with open(file_path, "r", encoding="shift_jis", errors="replace") as f:
                first_line = f.readline().strip()
                return first_line.startswith("*RAS_")
        except Exception:
            return False

    def parse(self, file_path: Path) -> ParseResult:
        """RASファイルをパースする。"""
        conditions = {}
        metadata = {}
        preview = {}
        errors = []

        try:
            with open(file_path, "r", encoding="shift_jis", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return ParseResult(errors=[f"ファイル読み込みエラー: {e}"])

        in_header = False
        in_data = False
        data_lines = []
        header_dict = {}

        for line in lines:
            line = line.strip()

            if line == "*RAS_HEADER_START":
                in_header = True
                continue
            elif line == "*RAS_HEADER_END":
                in_header = False
                continue
            elif line == "*RAS_DATA_START":
                in_data = True
                continue
            elif line == "*RAS_DATA_END":
                in_data = False
                continue

            if in_header and "=" in line:
                # ヘッダー行: *KEY "VALUE" or *KEY VALUE
                if line.startswith("*"):
                    line = line[1:]  # 先頭の * を除去
                parts = line.split("=", 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().strip('"')
                    header_dict[key] = value

            if in_data:
                data_lines.append(line)

        # ヘッダーから測定条件を抽出
        _extract_conditions(header_dict, conditions, metadata)

        # データのプレビュー（先頭10行）
        if data_lines:
            preview["data_points"] = len(data_lines)
            preview["first_lines"] = data_lines[:10]

            # 2θ範囲の推定
            try:
                first_vals = data_lines[0].split()
                last_vals = data_lines[-1].split()
                if first_vals and last_vals:
                    preview["two_theta_range"] = f"{first_vals[0]}-{last_vals[0]}"
            except (IndexError, ValueError):
                pass

        return ParseResult(
            conditions=conditions,
            metadata=metadata,
            preview=preview,
            errors=errors,
        )


def _extract_conditions(header: dict, conditions: dict, metadata: dict) -> None:
    """RASヘッダーから測定条件を抽出する。"""

    # X線ターゲット
    target_map = {
        "CU": "Cu",
        "MO": "Mo",
        "CO": "Co",
        "FE": "Fe",
        "CR": "Cr",
    }
    hw_target = header.get("HW_XG_TARGET_NAME", "").upper()
    if hw_target in target_map:
        conditions["target"] = target_map[hw_target]

    # 波長
    wavelength = header.get("HW_XG_WAVE_LENGTH_ALPHA1")
    if wavelength:
        try:
            conditions["wavelength_A"] = float(wavelength)
        except ValueError:
            pass

    # 管電圧・管電流
    voltage = header.get("HW_XG_VOLTAGE")
    if voltage:
        try:
            conditions["voltage_kV"] = float(voltage)
        except ValueError:
            pass

    current = header.get("HW_XG_CURRENT")
    if current:
        try:
            conditions["current_mA"] = float(current)
        except ValueError:
            pass

    # 2θ範囲
    start = header.get("MEAS_SCAN_START")
    end = header.get("MEAS_SCAN_END")
    if start:
        try:
            conditions["two_theta_start_deg"] = float(start)
        except ValueError:
            pass
    if end:
        try:
            conditions["two_theta_end_deg"] = float(end)
        except ValueError:
            pass

    # スキャン速度
    speed = header.get("MEAS_SCAN_SPEED")
    if speed:
        try:
            conditions["scan_speed_deg_per_min"] = float(speed)
        except ValueError:
            pass

    # ステップ幅
    step = header.get("MEAS_SCAN_STEP")
    if step:
        try:
            conditions["step_deg"] = float(step)
        except ValueError:
            pass

    # 装置名
    instrument = header.get("HW_GONIOMETER_NAME", "")
    if instrument:
        metadata["instrument"] = instrument

    # サンプル名
    sample = header.get("MEAS_SAMPLE", "")
    if sample:
        conditions["sample_name"] = sample

    # 測定日時
    date = header.get("MEAS_SCAN_START_TIME", "")
    if date:
        metadata["measurement_date"] = date
```

### 4.4 SDK統合（exp.add()での自動抽出）

```python
# src/labvault/core/record.py (抜粋)

def add(
    self,
    path: str | Path,
    *,
    conditions: dict[str, Any] | None = None,
    parse: bool = True,  # ファイルパーサーを自動適用
) -> Record:
    """ファイルをレコードに追加する。

    parse=True の場合、対応するファイルパーサーが自動適用され、
    測定条件がconditionsに自動マージされる。

    手動で指定したconditionsはパーサーの結果より優先される。
    """
    file_path = Path(path)

    # ファイルパーサーの自動適用
    if parse:
        from labvault.parsers.registry import get_registry
        registry = get_registry()
        parse_result = registry.parse(file_path)

        if parse_result is not None:
            # パーサーで抽出された条件をマージ（手動指定が優先）
            merged_conditions = {**parse_result.conditions}
            if conditions:
                merged_conditions.update(conditions)  # 手動指定で上書き

            # テンプレートが設定されている場合、正規化
            if self._template:
                from .template_validator import normalize_conditions as norm_cond
                merged_conditions = norm_cond(self._template, merged_conditions)

            self._data["conditions"].update(merged_conditions)

            # メタデータも保存
            if parse_result.metadata:
                self._data.setdefault("parser_metadata", {})
                self._data["parser_metadata"][file_path.name] = parse_result.metadata

            # パースエラーがあれば警告
            if parse_result.errors:
                import warnings
                for err in parse_result.errors:
                    warnings.warn(f"ファイルパーサー警告 ({file_path.name}): {err}")

    elif conditions:
        self._data["conditions"].update(conditions)

    # ファイルのアップロード処理（既存のロジック）
    ...

    return self
```

---

## 5. indexed_fieldsによる検索改善

v9レビュー S-3「conditionsフィールドの構造化検索がスケールしない」への対応。

### 5.1 設計概要

```
問題: Firestoreのconditionsフィールドはmap型。
      map型の動的キーにはインデックスが貼れない。
      conditions.temperature_C > 300 のようなクエリが全件スキャンになる。

解決: テンプレートの indexed_fields で指定されたフィールドを
      Firestoreドキュメントのトップレベルに idx_ プレフィックスで昇格する。
      → Firestore複合インデックスが利用可能になる。
```

### 5.2 Firestoreトップレベルフィールド昇格

```python
# Firestoreドキュメント構造の例（XRDテンプレート使用時）

{
    "id": "AB3F",
    "title": "Fe-10Cr XRD測定",
    "type": "measurement",
    "status": "success",
    "tags": ["XRD", "Fe-Cr"],
    "conditions": {                       # 元の全条件（変更なし）
        "target": "Cu",
        "wavelength_A": 1.5418,
        "two_theta_start_deg": 20.0,
        "two_theta_end_deg": 80.0,
        "sample_name": "Fe-10Cr-001",
        ...
    },
    "results": { ... },

    # ↓ indexed_fields で昇格されたフィールド
    "idx_target": "Cu",                   # conditions.target のコピー
    "idx_method": "powder",               # conditions.method のコピー
    "idx_sample_name": "Fe-10Cr-001",     # conditions.sample_name のコピー
}
```

### 5.3 SDK自動ミラー

```python
# src/labvault/core/record.py (抜粋)

def _mirror_indexed_fields(self) -> dict[str, Any]:
    """テンプレートの indexed_fields を idx_ プレフィックスでトップレベルに昇格する。

    conditions() が呼ばれるたびに自動実行。
    """
    if not self._template or not self._template.indexed_fields:
        return {}

    mirrors = {}
    conditions = self._data.get("conditions", {})

    for field_name in self._template.indexed_fields:
        value = conditions.get(field_name)
        if value is not None:
            mirrors[f"idx_{field_name}"] = value

    return mirrors


def conditions(self, **kwargs: Any) -> Record:
    """実験条件を設定する。"""
    # 正規化（テンプレートがある場合）
    if self._template:
        from .template_validator import normalize_conditions
        kwargs = normalize_conditions(self._template, kwargs)

    self._data["conditions"].update(kwargs)

    # indexed_fieldsの自動ミラー
    mirrors = self._mirror_indexed_fields()
    if mirrors:
        self._data.update(mirrors)

    # ローカルバッファに即時書き込み
    self._save_to_buffer()

    return self
```

### 5.4 MCPサーバーでの高速フィルタ

```python
# functions/mcp_server/tools/search.py (抜粋)

def _build_firestore_query(db, team_id, filters):
    """検索クエリを構築する。

    idx_ プレフィックスのフィールドが利用可能な場合、
    Firestoreのネイティブクエリで高速フィルタリングする。
    conditions_filter はPython側全件スキャンのフォールバック。
    """
    q = (
        db.collection("teams").document(team_id).collection("records")
        .where("deleted_at", "==", None)
    )

    conditions_filter = filters.get("conditions_filter", {})

    # idx_ フィールドが使える条件はFirestoreクエリに組み込む
    remaining_filter = {}
    for key, constraint in conditions_filter.items():
        idx_key = f"idx_{key}"

        if isinstance(constraint, dict):
            # 範囲クエリ: {"temperature_C": {">": 300}}
            for op, value in constraint.items():
                firestore_op = {
                    ">": ">", ">=": ">=", "<": "<", "<=": "<=", "==": "=="
                }.get(op)
                if firestore_op:
                    q = q.where(idx_key, firestore_op, value)
                else:
                    remaining_filter[key] = constraint
        else:
            # 完全一致: {"target": "Cu"}
            q = q.where(idx_key, "==", constraint)

    return q, remaining_filter
```

### 5.5 Firestoreインデックス定義

```
# firestore.indexes.json
{
  "indexes": [
    {
      "collectionGroup": "records",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "deleted_at", "order": "ASCENDING"},
        {"fieldPath": "idx_target", "order": "ASCENDING"},
        {"fieldPath": "created_at", "order": "DESCENDING"}
      ]
    },
    {
      "collectionGroup": "records",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "deleted_at", "order": "ASCENDING"},
        {"fieldPath": "idx_sample_name", "order": "ASCENDING"},
        {"fieldPath": "created_at", "order": "DESCENDING"}
      ]
    }
  ]
}
```

---

## 6. link()セマンティクス

v9レビュー S-6「多段階合成プロセスの表現力」、S-7「サンプル-実験の多対多関係」への対応。

### 6.1 LinkRelation定義

```python
# src/labvault/core/types.py

from enum import Enum


class LinkRelation(str, Enum):
    """レコード間のリンク関係。"""

    # プロセスチェーン
    DERIVED_FROM = "derived_from"      # このレコードは元レコードから派生した
    PRODUCES = "produces"               # このプロセスが結果レコードを生産した

    # 測定
    MEASURED_ON = "measured_on"         # この測定は対象サンプルに対して行われた
    SAMPLE_OF = "sample_of"            # このサンプルがこの測定の対象

    # 時系列
    CONTINUES = "continues"            # このレコードは前のレコードの続き
    CONTINUED_BY = "continued_by"      # このレコードの続きが存在する

    # 参照
    REPLACES = "replaces"              # このレコードは古いレコードを置き換える
    REPLACED_BY = "replaced_by"        # このレコードは新しいレコードに置き換えられた
    RELATED_TO = "related_to"          # 一般的な関連（双方向）
    REFERS_TO = "refers_to"            # 参照（片方向）

    # バッチ
    BATCH_MEMBER = "batch_member"      # バッチのメンバー
    BATCH_OF = "batch_of"              # このバッチに属する


# 逆関係のマッピング
INVERSE_RELATIONS: dict[LinkRelation, LinkRelation] = {
    LinkRelation.DERIVED_FROM: LinkRelation.PRODUCES,
    LinkRelation.PRODUCES: LinkRelation.DERIVED_FROM,
    LinkRelation.MEASURED_ON: LinkRelation.SAMPLE_OF,
    LinkRelation.SAMPLE_OF: LinkRelation.MEASURED_ON,
    LinkRelation.CONTINUES: LinkRelation.CONTINUED_BY,
    LinkRelation.CONTINUED_BY: LinkRelation.CONTINUES,
    LinkRelation.REPLACES: LinkRelation.REPLACED_BY,
    LinkRelation.REPLACED_BY: LinkRelation.REPLACES,
    LinkRelation.RELATED_TO: LinkRelation.RELATED_TO,  # 対称
    LinkRelation.BATCH_MEMBER: LinkRelation.BATCH_OF,
    LinkRelation.BATCH_OF: LinkRelation.BATCH_MEMBER,
}
```

### 6.2 双方向リンク自動作成

```python
# src/labvault/core/record.py (抜粋)

def link(
    self,
    target: str | Record,
    relation: str | LinkRelation = LinkRelation.RELATED_TO,
    description: str = "",
) -> Record:
    """別レコードとの関係を登録する。

    双方向リンクを自動作成する。
    例: A.link(B, "derived_from") → A→B(derived_from) + B→A(produces)
    """
    target_id = target.id if isinstance(target, Record) else target
    relation = LinkRelation(relation) if isinstance(relation, str) else relation

    # 自分→ターゲットのリンク
    link_data = {
        "target_id": target_id,
        "relation": relation.value,
        "description": description,
    }
    self._data.setdefault("links", [])
    self._data["links"].append(link_data)

    # ターゲット→自分の逆リンク（双方向自動作成）
    inverse_relation = INVERSE_RELATIONS.get(relation, LinkRelation.RELATED_TO)
    inverse_link = {
        "target_id": self.id,
        "relation": inverse_relation.value,
        "description": description,
    }

    # ターゲットレコードの更新（バッファ経由）
    self._lab._add_link_to_record(target_id, inverse_link)

    self._save_to_buffer()
    return self
```

---

## 7. ProcessChain

v9レビュー S-6「多段階合成プロセスの表現力」への対応。

### 7.1 設計概要

```
セラミックス合成の例:
  秤量 → 混合 → 仮焼 → 粉砕 → 本焼 → 研磨 → XRD測定 → SEM観察

各工程をRecordとして記録し、chain.next() で自動リンクする。
```

### 7.2 API設計

```python
# src/labvault/core/lab.py (抜粋)

def new_chain(
    self,
    title: str,
    *,
    steps: list[str] | None = None,
    template: str | None = None,
    tags: list[str] | None = None,
) -> ProcessChain:
    """多段階プロセスチェーンを開始する。

    使用例:
        chain = lab.new_chain(
            "BaTiO3合成",
            steps=["秤量", "混合", "仮焼", "粉砕", "本焼", "研磨"],
            tags=["BaTiO3", "ceramics"],
        )

        # 各工程を順番に記録
        weighing = chain.current()
        weighing.conditions(BaCO3_g=19.7, TiO2_g=8.0)
        weighing.status = "success"

        mixing = chain.next("混合")
        mixing.conditions(method="ball_mill", duration_min=120)

        calcination = chain.next("仮焼")
        calcination.conditions(temperature_C=1000, duration_min=120)
    """
    ...


# src/labvault/core/chain.py

class ProcessChain:
    """多段階プロセスチェーン。

    Recordのシーケンスを管理し、自動リンクを付与する。
    """

    def __init__(
        self,
        lab: Lab,
        title: str,
        steps: list[str] | None = None,
        template: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        self._lab = lab
        self._title = title
        self._planned_steps = steps or []
        self._tags = tags or []
        self._records: list[Record] = []
        self._current_index: int = -1

        # ルートレコード（チェーン全体を表す）
        self._root = lab.new(
            title=title,
            type="process_chain",
            tags=self._tags,
        )
        if self._planned_steps:
            self._root._data["planned_steps"] = self._planned_steps

        # 最初のステップを開始
        if self._planned_steps:
            self._start_step(self._planned_steps[0])

    def current(self) -> Record:
        """現在のステップのRecordを返す。"""
        if not self._records:
            raise ValueError("チェーンにステップがありません")
        return self._records[self._current_index]

    def next(self, title: str | None = None, **conditions) -> Record:
        """次のステップに進む。前のステップを自動でcloseし、次のRecordを作成。

        Args:
            title: ステップのタイトル。省略時はplanned_stepsから取得
            **conditions: 次のステップの条件
        """
        # 現在のステップを完了
        if self._records:
            current = self._records[self._current_index]
            if current._data.get("status") == "running":
                current.status = "success"

        # 次のステップのタイトルを決定
        if title is None:
            next_index = self._current_index + 1
            if next_index < len(self._planned_steps):
                title = self._planned_steps[next_index]
            else:
                title = f"ステップ {next_index + 1}"

        return self._start_step(title, **conditions)

    def _start_step(self, title: str, **conditions) -> Record:
        """新しいステップを開始する。"""
        step_record = self._lab.new(
            title=f"{self._title} - {title}",
            type="process",
            tags=self._tags,
        )

        if conditions:
            step_record.conditions(**conditions)

        # ルートレコードとのリンク
        step_record.link(self._root.id, LinkRelation.DERIVED_FROM)

        # 前のステップとのリンク
        if self._records:
            prev = self._records[-1]
            step_record.link(prev.id, LinkRelation.CONTINUES)

        self._records.append(step_record)
        self._current_index = len(self._records) - 1

        return step_record

    @property
    def root(self) -> Record:
        """チェーン全体を表すルートレコード。"""
        return self._root

    @property
    def steps(self) -> list[Record]:
        """全ステップのRecordリスト。"""
        return list(self._records)

    def summary(self) -> dict:
        """チェーンのサマリーを返す。"""
        return {
            "title": self._title,
            "total_steps": len(self._records),
            "planned_steps": self._planned_steps,
            "completed": sum(1 for r in self._records if r._data.get("status") == "success"),
            "current_step": self._records[self._current_index]._data.get("title", "") if self._records else "",
        }
```

---

## 8. 典型的な実験パターン

### 8.1 パターン1: 単発測定

```python
# XRDの単発測定
from labvault import Lab

lab = Lab("konishi-lab")

# テンプレートを使ってレコード作成
exp = lab.new("Fe-10Cr XRD", template="XRD")

# ファイル追加（.ras → 自動パースで条件抽出）
exp.add("xrd_data.ras")  # target, 2theta範囲, 管電圧等が自動設定

# 手動で追加条件を設定
exp.conditions(sample_name="Fe-10Cr-001")

# 結果を記録
exp.results["lattice_a_A"] = 2.873
exp.results["phase"] = "BCC"
exp.results["crystallite_size_nm"] = 45.2

exp.status = "success"
exp.note("格子定数は文献値2.870Åと一致。結晶性良好。")
```

**推奨Record構造**:
```
Record: "Fe-10Cr XRD" (type=measurement, template=XRD)
├── conditions: {target: "Cu", two_theta_start_deg: 20, ..., sample_name: "Fe-10Cr-001"}
├── results: {lattice_a_A: 2.873, phase: "BCC", crystallite_size_nm: 45.2}
├── data_refs: [{name: "xrd_data.ras", ...}]
├── tags: ["XRD", "Fe-Cr"]
└── notes: ["格子定数は文献値2.870Åと一致。結晶性良好。"]
```

### 8.2 パターン2: 条件スイープ

```python
# 基板温度を変えたスパッタ成膜
from labvault import Lab

lab = Lab("konishi-lab")

# 親レコード（スイープ全体）
sweep = lab.new("Fe-Cr 基板温度依存性", type="experiment", tags=["sputtering", "Fe-Cr"])
sweep.conditions(
    target="Fe-10Cr",
    base_pressure_Pa=5e-6,
    ar_pressure_Pa=0.5,
    power_W=100,
)

# 各温度条件をサブレコードとして記録
temperatures = [200, 300, 400, 500, 600]

for temp in temperatures:
    sub = sweep.sub(f"基板温度 {temp}°C", type="process")
    sub.conditions(substrate_temperature_C=temp, duration_min=30)

    # XRD測定をリンク
    xrd = lab.new(f"XRD T={temp}°C", template="XRD")
    xrd.add(f"xrd_T{temp}.ras")
    xrd.link(sub, "measured_on")

    # 結果
    xrd.results["lattice_a_A"] = ...  # 解析結果
    sub.results["film_thickness_nm"] = ...  # 膜厚測定結果

sweep.status = "success"
sweep.note(f"5条件のスイープ完了。{temperatures[0]}-{temperatures[-1]}°Cの範囲。")
```

**推奨Record構造**:
```
Record: "Fe-Cr 基板温度依存性" (type=experiment)
├── sub: "基板温度 200°C" (type=process)
│   └── linked: "XRD T=200°C" (type=measurement, relation=measured_on)
├── sub: "基板温度 300°C" (type=process)
│   └── linked: "XRD T=300°C" (type=measurement, relation=measured_on)
├── sub: "基板温度 400°C" ...
├── sub: "基板温度 500°C" ...
└── sub: "基板温度 600°C" ...
```

### 8.3 パターン3: 長期時系列

```python
# 高温耐久試験（1000時間）
from labvault import Lab
import time

lab = Lab("konishi-lab")

# 耐久試験レコード
test = lab.new("Fe-Cr 高温酸化耐久試験", type="experiment")
test.conditions(
    temperature_C=800,
    atmosphere="air",
    sample_name="Fe-10Cr-005",
    planned_duration_hours=1000,
)

# 定期観測をサブレコードとして記録
observation_hours = [0, 10, 50, 100, 250, 500, 750, 1000]

for hours in observation_hours:
    obs = test.sub(f"観察 {hours}h", type="measurement")
    obs.conditions(elapsed_hours=hours)
    obs.tag("weight_change")

    # 重量変化測定
    obs.results["weight_change_mg_per_cm2"] = ...  # 測定値
    obs.add(f"sem_{hours}h.tif")  # SEM画像

    obs.status = "success"

test.results["total_weight_gain_mg_per_cm2"] = ...
test.results["oxidation_rate_constant"] = ...
test.status = "success"
```

**推奨Record構造**:
```
Record: "Fe-Cr 高温酸化耐久試験" (type=experiment)
├── conditions: {temperature_C: 800, atmosphere: "air", sample_name: "Fe-10Cr-005"}
├── results: {total_weight_gain_mg_per_cm2: ..., oxidation_rate_constant: ...}
├── sub: "観察 0h" (type=measurement)
│   ├── results: {weight_change_mg_per_cm2: 0.0}
│   └── data_refs: [sem_0h.tif]
├── sub: "観察 10h" ...
├── sub: "観察 50h" ...
...
└── sub: "観察 1000h"
```

### 8.4 パターン4: 複数装置横断

```python
# セラミックス合成の全工程
from labvault import Lab

lab = Lab("konishi-lab")

# ProcessChainを使用
chain = lab.new_chain(
    "BaTiO3合成",
    steps=["秤量", "混合", "仮焼", "粉砕", "本焼", "研磨"],
    tags=["BaTiO3", "ceramics"],
)

# 秤量
weighing = chain.current()
weighing.conditions(BaCO3_g=19.7, TiO2_g=8.0, mortar="agate")
weighing.status = "success"

# 混合
mixing = chain.next()
mixing.conditions(method="ball_mill", duration_min=120, medium="ethanol")
mixing.status = "success"

# 仮焼（装置PC: _inbox経由で投入）
calcination = chain.next()
calcination.conditions(temperature_C=1000, duration_min=120, atmosphere="air")
# 装置PCからQRコード経由でデータ投入
lab.qr(calcination.id)
# → 装置PCからNextcloud _inboxにファイルをアップロード

# 粉砕
grinding = chain.next()
grinding.conditions(method="ball_mill", duration_min=60)

# 本焼
sintering = chain.next()
sintering.conditions(temperature_C=1350, duration_min=240, atmosphere="air")
sintering.add("sintering_profile.csv")

# 研磨
polishing = chain.next()
polishing.conditions(paper_grit=[400, 800, 1200, 2000, 4000])

# 測定（各装置で実施）
xrd = lab.new("BaTiO3 XRD", template="XRD")
xrd.add("xrd_bto.ras")
xrd.link(chain.root, "measured_on")

sem = lab.new("BaTiO3 SEM", template="SEM")
sem.add("sem_bto_5000x.tif")
sem.link(chain.root, "measured_on")

raman = lab.new("BaTiO3 Raman", template="Raman")
raman.add("raman_bto.wdf")
raman.link(chain.root, "measured_on")

# チェーンのサマリー
print(chain.summary())
# → {title: "BaTiO3合成", total_steps: 6, completed: 6, ...}
```

**推奨Record構造**:
```
Record: "BaTiO3合成" (type=process_chain)
├── linked: "BaTiO3合成 - 秤量" (type=process, relation=derived_from)
│   └── linked: "BaTiO3合成 - 混合" (continues)
│       └── linked: "BaTiO3合成 - 仮焼" (continues)
│           └── linked: "BaTiO3合成 - 粉砕" (continues)
│               └── linked: "BaTiO3合成 - 本焼" (continues)
│                   └── linked: "BaTiO3合成 - 研磨" (continues)
├── linked: "BaTiO3 XRD" (relation=measured_on)
├── linked: "BaTiO3 SEM" (relation=measured_on)
└── linked: "BaTiO3 Raman" (relation=measured_on)
```

---

## 9. オンボーディング

v9レビュー S-11「Python初心者へのハードル」への対応。

### 9.1 5分クイックスタート

```
所要時間: 5分
前提: Python 3.10+がインストール済み
対象: 新入研究室メンバー（学部4年〜）

手順:

1. インストール (30秒)
   $ pip install labvault

2. 初期設定 (2分)
   $ labvault init --from-url https://config.konishi-lab.example/setup
   → チーム名、GCPプロジェクト、Nextcloud設定が自動ダウンロード
   → ~/.labvault/config.toml が生成される

3. 最初の実験記録 (2分)
   Jupyter Notebookで:

   from labvault import Lab
   lab = Lab()
   exp = lab.new("初めてのXRD測定", template="XRD")
   exp.add("xrd_data.ras")  # → 条件が自動抽出される
   exp.results["lattice_a_A"] = 2.873
   exp.status = "success"

   # → 完了! Firestore + Nextcloudに保存されている

4. 確認 (30秒)
   $ labvault list
   → 作成したレコードが一覧に表示される
```

### 9.2 labvault init --from-url

```python
# src/labvault/cli/init.py

@cli.command()
@click.option("--from-url", help="管理者が共有した設定URLから初期化")
def init(from_url: str | None):
    """labvaultの初期設定を行う。

    --from-url: 管理者が共有したURLから設定をダウンロード。
                URLなしの場合は対話的に設定。
    """
    if from_url:
        # URLから設定テンプレートをダウンロード
        import httpx
        response = httpx.get(from_url)
        response.raise_for_status()
        config_template = response.json()

        # ユーザー名のみ対話的に入力
        user = click.prompt("あなたの名前（英字）", default="")

        # config.toml 生成
        config = {
            "team": config_template["team"],
            "user": user,
            "gcp_project": config_template["gcp_project"],
            "firestore_database": config_template.get("firestore_database", "labvault"),
            "nextcloud_url": config_template["nextcloud_url"],
            "nextcloud_user": click.prompt("Nextcloudユーザー名"),
            "nextcloud_password": click.prompt("Nextcloudパスワード (App Password推奨)", hide_input=True),
            "nextcloud_group_folder": config_template["nextcloud_group_folder"],
        }

        _write_config(config)
        click.echo("設定完了! labvault list で接続を確認してください。")

    else:
        # 対話的セットアップ（既存のフロー）
        ...
```

### 9.3 labvault doctor

```python
# src/labvault/cli/doctor.py

@cli.command()
def doctor():
    """labvaultの設定と接続状態を診断する。

    チェック項目:
    1. config.toml の存在と内容
    2. GCP認証の状態
    3. Firestoreへの接続
    4. Nextcloudへの接続
    5. Python環境（バージョン、必要パッケージ）
    """
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="labvault 診断結果")
    table.add_column("項目", style="bold")
    table.add_column("状態")
    table.add_column("詳細")

    # 1. config.toml
    config_path = Path.home() / ".labvault" / "config.toml"
    if config_path.exists():
        table.add_row("設定ファイル", "[green]OK[/green]", str(config_path))
    else:
        table.add_row("設定ファイル", "[red]NG[/red]", "~/.labvault/config.toml が見つかりません。labvault init を実行してください。")

    # 2. GCP認証
    try:
        import google.auth
        credentials, project = google.auth.default()
        table.add_row("GCP認証", "[green]OK[/green]", f"Project: {project}")
    except Exception as e:
        table.add_row("GCP認証", "[red]NG[/red]", f"gcloud auth application-default login を実行してください。({e})")

    # 3. Firestore接続
    try:
        from google.cloud import firestore
        from labvault.core.config import Settings
        settings = Settings()
        db = firestore.Client(project=settings.gcp_project, database=settings.firestore_database)
        # テスト読み取り
        db.collection("teams").document(settings.team).get()
        table.add_row("Firestore", "[green]OK[/green]", f"Team: {settings.team}")
    except Exception as e:
        table.add_row("Firestore", "[red]NG[/red]", str(e))

    # 4. Nextcloud接続
    try:
        from labvault.core.config import Settings
        settings = Settings()
        import httpx
        response = httpx.get(
            f"{settings.nextcloud_url}/status.php",
            timeout=10.0,
        )
        if response.status_code == 200:
            table.add_row("Nextcloud", "[green]OK[/green]", settings.nextcloud_url)
        else:
            table.add_row("Nextcloud", "[yellow]警告[/yellow]", f"HTTP {response.status_code}")
    except Exception as e:
        table.add_row("Nextcloud", "[red]NG[/red]", str(e))

    # 5. Python環境
    import sys
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        table.add_row("Python", "[green]OK[/green]", f"v{py_version}")
    else:
        table.add_row("Python", "[red]NG[/red]", f"v{py_version} (3.10以上が必要)")

    console.print(table)
```

### 9.4 管理者の設定共有フロー

```
管理者（PI or 管理者）のフロー:

1. GCPプロジェクト設定（初回のみ）
   $ labvault init
   → config.toml が生成される

2. 設定テンプレートの作成
   $ labvault team export-config > team_config.json
   → チーム設定（パスワード除く）がJSON出力される

3. テンプレートの共有
   - GitHub Gist にアップロード
   - 学内Webサーバーに配置
   - Slackで共有
   → URL: https://gist.github.com/.../team_config.json

4. メンバーへの案内
   「以下のコマンドを実行してください:
    pip install labvault
    labvault init --from-url https://gist.github.com/.../team_config.json」

メンバーのフロー:

1. $ pip install labvault
2. $ labvault init --from-url <共有URL>
   → ユーザー名とNextcloudパスワードのみ入力
3. $ labvault doctor
   → 全チェックOKを確認
4. Notebook で lab = Lab() して実験開始
```
