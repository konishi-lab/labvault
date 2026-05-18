"""ビルトインテンプレート定義 (XRD / SEM / SQUID / TEM / Raman)。

`Lab.new(title, template="XRD")` で参照される。template 名が backend に
登録されていなければ、ここで定義された TemplateV10 が lazy に save される。

XRD は設計書 (docs/design/v10/03_experiment_workflow.md) の完全版。
それ以外 4 種は代表フィールドのみの暫定定義 — 実フィールドは現場で必要に
なった時点で拡充する想定。
"""

from __future__ import annotations

from labvault.core.types import (
    ConditionField,
    FileParserConfig,
    TemplateV10,
)

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
            description="X線管のターゲット材。CuKα=1.5418Å",  # noqa: RUF001
        ),
        ConditionField(
            name="wavelength_A",
            display_name="X線波長",
            type="float",
            unit="A",
            default=1.5418,
            min_value=0.5,
            max_value=3.0,
            aliases=["lambda", "wavelength", "wave_length"],
            description="Kα1の波長。Cu=1.5418, Mo=0.7107, Co=1.7902",  # noqa: RUF001
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
    required_conditions=[
        "target",
        "two_theta_start_deg",
        "two_theta_end_deg",
        "sample_name",
    ],
    recommended_results=[
        "peak_positions_deg",
        "d_spacings_A",
        "lattice_a_A",
        "lattice_c_A",
        "phase",
        "crystallinity",
        "crystallite_size_nm",
        "preferred_orientation",
    ],
    indexed_fields=["target", "method", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".ras", parser_name="ras_parser"),
        FileParserConfig(extension=".raw", parser_name="bruker_raw_parser"),
        FileParserConfig(extension=".xy", parser_name="xy_parser"),
    ],
)


TEMPLATE_SEM = TemplateV10(
    name="SEM",
    display_name="走査型電子顕微鏡",
    description="SEM観察テンプレート (SE/BSE像、簡易EDS)。詳細フィールドは順次拡充。",
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
            type="float",
            required=True,
            aliases=["mag", "zoom"],
        ),
        ConditionField(
            name="working_distance_mm",
            display_name="作動距離",
            type="float",
            unit="mm",
            aliases=["WD", "wd", "working_dist"],
        ),
        ConditionField(
            name="detector",
            display_name="検出器",
            type="str",
            choices=["SE", "BSE", "EDS"],
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
    ],
    required_conditions=["acceleration_voltage_kV", "magnification", "sample_name"],
    indexed_fields=["sample_name"],
    file_parsers=[
        FileParserConfig(extension=".tif", parser_name="tiff_sem_parser"),
        FileParserConfig(extension=".tiff", parser_name="tiff_sem_parser"),
    ],
)


TEMPLATE_SQUID = TemplateV10(
    name="SQUID",
    display_name="SQUID磁化測定",
    description="SQUID磁化測定テンプレート (MH/MT)。詳細フィールドは順次拡充。",
    type="measurement",
    default_tags=["SQUID"],
    condition_fields=[
        ConditionField(
            name="measurement_mode",
            display_name="測定モード",
            type="str",
            required=True,
            choices=["MH", "MT", "MHT"],
            aliases=["mode"],
        ),
        ConditionField(
            name="temperature_K",
            display_name="温度",
            type="float",
            unit="K",
            aliases=["temp", "T"],
        ),
        ConditionField(
            name="field_T",
            display_name="磁場",
            type="float",
            unit="T",
            aliases=["H", "magnetic_field"],
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
        ConditionField(
            name="sample_mass_mg",
            display_name="試料質量",
            type="float",
            unit="mg",
            aliases=["mass"],
        ),
    ],
    required_conditions=["measurement_mode", "sample_name"],
    indexed_fields=["measurement_mode", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".dat", parser_name="mpms_dat_parser"),
    ],
)


TEMPLATE_TEM = TemplateV10(
    name="TEM",
    display_name="透過型電子顕微鏡",
    description="TEM観察テンプレート (BF/DF/HRTEM/SAED)。詳細フィールドは順次拡充。",
    type="measurement",
    default_tags=["TEM"],
    condition_fields=[
        ConditionField(
            name="acceleration_voltage_kV",
            display_name="加速電圧",
            type="float",
            unit="kV",
            required=True,
            min_value=10.0,
            max_value=400.0,
            aliases=["acc_voltage", "kV", "voltage"],
        ),
        ConditionField(
            name="mode",
            display_name="観察モード",
            type="str",
            required=True,
            choices=["BF", "DF", "HRTEM", "SAED", "STEM"],
        ),
        ConditionField(
            name="magnification",
            display_name="倍率",
            type="float",
            aliases=["mag"],
        ),
        ConditionField(
            name="sample_name",
            display_name="サンプル名",
            type="str",
            required=True,
            aliases=["sample", "specimen"],
        ),
    ],
    required_conditions=["acceleration_voltage_kV", "mode", "sample_name"],
    indexed_fields=["mode", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".dm3", parser_name="dm3_parser"),
        FileParserConfig(extension=".dm4", parser_name="dm3_parser"),
    ],
)


TEMPLATE_RAMAN = TemplateV10(
    name="Raman",
    display_name="ラマン分光",
    description="ラマン分光測定テンプレート。詳細フィールドは順次拡充。",
    type="measurement",
    default_tags=["Raman"],
    condition_fields=[
        ConditionField(
            name="laser_wavelength_nm",
            display_name="励起波長",
            type="float",
            unit="nm",
            required=True,
            choices=None,
            aliases=["excitation", "laser", "wavelength"],
        ),
        ConditionField(
            name="laser_power_mW",
            display_name="レーザーパワー",
            type="float",
            unit="mW",
            aliases=["power"],
        ),
        ConditionField(
            name="exposure_sec",
            display_name="露光時間",
            type="float",
            unit="s",
            aliases=["exposure", "exposure_time"],
        ),
        ConditionField(
            name="accumulations",
            display_name="積算回数",
            type="int",
            aliases=["n_acc", "acc"],
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
    indexed_fields=["laser_wavelength_nm", "sample_name"],
    file_parsers=[
        FileParserConfig(extension=".wdf", parser_name="wdf_parser"),
    ],
)


BUILTIN_TEMPLATES: dict[str, TemplateV10] = {
    t.name: t
    for t in (
        TEMPLATE_XRD,
        TEMPLATE_SEM,
        TEMPLATE_SQUID,
        TEMPLATE_TEM,
        TEMPLATE_RAMAN,
    )
}
