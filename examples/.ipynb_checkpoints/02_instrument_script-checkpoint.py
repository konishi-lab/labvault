"""装置制御スクリプトでの labvault 使用例。

Notebook ではなく .py スクリプトから実験データを記録するパターンです。
装置制御中に log_value() / log_event() でリアルタイムにデータを記録します。

使い方:
    python examples/02_instrument_script.py
"""

import random
import time

from labvault import Lab


def simulate_sputtering(exp):
    """スパッタ成膜プロセスのシミュレーション。

    実際の装置制御スクリプトでは、ここで GPIB/RS-232 通信や
    装置固有の SDK を使って装置を制御します。
    """
    # --- 成膜開始 ---
    exp.log_event("process_start", "チャンバー排気完了、成膜開始")

    exp.log_event("rf_on", "RF電源 ON, 200W")

    # --- 成膜中のモニタリング ---
    for i in range(5):
        # 装置からの読み値をシミュレート
        temp = 500 + random.gauss(0, 2)
        pressure = 0.5 + random.gauss(0, 0.02)
        rate = 12.5 + random.gauss(0, 0.5)

        exp.log_value("substrate_temperature_C", round(temp, 1))
        exp.log_value("chamber_pressure_Pa", round(pressure, 3))
        exp.log_value("deposition_rate_nm_min", round(rate, 2))

        print(f"  [{i * 60:>4d}s] T={temp:.1f}°C, P={pressure:.3f}Pa, Rate={rate:.2f}nm/min")
        time.sleep(0.2)  # 実際は数十秒〜数分間隔

    # --- 成膜終了 ---
    exp.log_event("rf_off", "RF電源 OFF")
    exp.log_event("process_end", "成膜完了、冷却開始")


def main():
    # --- Lab 初期化 ---
    # 引数なしで InMemoryBackend が使われる（本番では config.toml から設定を読む）
    lab = Lab("konishi-lab", user="taro")

    # --- レコード作成 ---
    # auto_log=False: スクリプトでは IPython hooks 不要
    exp = lab.new(
        "SiO2薄膜スパッタ成膜 #42",
        tags=["スパッタ", "SiO2", "Si基板"],
        temperature_C=500,
        pressure_Pa=0.5,
        rf_power_W=200,
        target="SiO2 (4inch)",
        substrate="Si(100) p-type",
        gas="Ar 20sccm",
    )

    print(f"Record created: {exp.id}")
    print(f"  Title: {exp.title}")
    print(f"  Conditions: {exp.get_conditions()}")
    print()

    # --- メモ ---
    exp.note("基板洗浄: アセトン超音波 5min → IPA 5min → UV-O3 10min")
    exp.note("ターゲット: 前回から連続使用（累積 12h）")

    # --- 成膜プロセス実行 ---
    print("Running sputtering process...")
    simulate_sputtering(exp)
    print()

    # --- 結果の記録 ---
    exp.results["film_thickness_nm"] = 62.5
    exp.results["uniformity_percent"] = 2.1
    exp.results["sheet_resistance_ohm_sq"] = 1.2e6

    # --- データファイルの保存 ---
    # 実際にはプロセスログファイルや測定データを保存する
    exp.save("process_log", {
        "events": exp.events,
        "conditions": exp.get_conditions(),
        "results": exp.results.to_dict(),
    })

    # --- 完了 ---
    exp.status = "success"

    print(f"Experiment completed: {exp.id}")
    print(f"  Status: {exp.status}")
    print(f"  Results: {exp.results}")
    print(f"  Events: {len(exp.events)} recorded")
    print(f"  Files: {[ref.name for ref in exp.data_refs]}")


if __name__ == "__main__":
    main()
