# labvault SDK Cookbook

> SDK の使い勝手が一目で分かる実践ガイド。
> 全コード例は v10 確定 API に基づく。コピペしてそのまま動く想定。

---

## 目次

1. [30秒で始める](#1-30秒で始める)
2. [Lab — チームデータベース](#2-lab--チームデータベース)
3. [Record — 実験レコード](#3-record--実験レコード)
4. [データの保存と取得](#4-データの保存と取得)
5. [自動ログ（IPython hooks）](#5-自動ログipython-hooks)
6. [テンプレート](#6-テンプレート)
7. [子レコードとリンク](#7-子レコードとリンク)
8. [検索](#8-検索)
9. [CLI](#9-cli)
10. [よくあるパターン集](#10-よくあるパターン集)

---

## 1. 30秒で始める

```python
from labvault import Lab

lab = Lab()                                    # config.toml から自動読み込み
exp = lab.new("Fe-Cr薄膜 XRD測定")             # レコード作成（ID自動生成）
exp.conditions(temperature_C=500, pressure_Pa=0.5)
exp.add("xrd_data.csv")                        # ファイル保存
exp.results["lattice_a"] = 2.873               # 結果記録
exp.status = "success"                         # 完了
```

**3行で最小限**:

```python
from labvault import Lab
exp = Lab().new("実験メモ")
exp.add("data.csv")
```

---

## 2. Lab — チームデータベース

### 2.1 初期化

```python
from labvault import Lab

# config.toml から自動読み込み（推奨）
lab = Lab()

# チーム名を明示
lab = Lab("konishi-lab")

# テスト用（InMemoryBackend。GCP接続なし）
lab = Lab("test", metadata_backend=InMemoryMetadataBackend())
```

### 2.2 レコードの取得・一覧

```python
# IDで取得（読み取りのみ）
exp = lab.get("AB3F")

# 既存Recordに追記（IPython hooks ON。解析Notebookでの追記や、カーネル再起動後の復帰に使う）
exp = lab.get("AB3F", auto_log=True)

# 最新10件
recent = lab.recent(10)

# 今日のレコード
today = lab.today()

# フィルタ付き一覧
xrd_records = lab.list(tags=["XRD"], status="success", limit=50)
my_records = lab.list(created_by="tanaka")
samples = lab.list(type="sample")
```

### 2.3 検索

```python
# セマンティック検索（自然言語）
results = lab.search("結晶性が良い薄膜")

# フィルタ付き検索
results = lab.search("Fe-Cr", tags=["XRD"], status="success")
```

### 2.4 削除と復元

```python
# ソフトデリート（ゴミ箱に移動。30日後に自動削除）
lab.delete("AB3F")

# ゴミ箱の確認
trashed = lab.trash()

# 復元
lab.restore("AB3F")
```

### 2.5 同期ステータス

```python
# バッファの状態を確認
print(lab.sync_status)
# → {"pending": 3, "errors": [], "last_sync": "2026-03-17T10:30:00"}

# 手動で即時同期
result = lab.sync()
# → {"records": 2, "cell_logs": 15, "files": 1, "errors": 0}
```

### 2.6 コンテキストマネージャ

```python
with Lab() as lab:
    exp = lab.new("実験")
    exp.add("data.csv")
# ← Lab.close() が自動呼び出し（最終同期 + リソース解放）
```

---

## 3. Record — 実験レコード

### 3.1 作成

```python
# 基本
exp = lab.new("Fe-Cr薄膜 スパッタ成膜")

# type指定（デフォルトは "experiment"）
sample = lab.new("Fe-Cr #001", type="sample")
measurement = lab.new("XRD測定", type="measurement")
process = lab.new("アニール処理", type="process")

# テンプレート使用
exp = lab.new("XRD測定", template="XRD")

# 作成時に条件も指定
exp = lab.new("XRD測定", template="XRD", temperature_C=500, target="Cu")
```

### 3.2 条件の記録

```python
# キーワード引数
exp.conditions(
    temperature_C=500,
    pressure_Pa=0.5,
    atmosphere="Ar",
    power_W=200,
)

# 追加・上書き
exp.conditions(duration_min=30)

# 辞書で指定（Pythonの予約語やハイフンを含むキーに有用）
exp.conditions(**{"2theta_range": "20-80"})

# 確認
print(exp.get_conditions())
# → {"temperature_C": 500, "pressure_Pa": 0.5, ...}
```

### 3.3 タグ

```python
# 追加
exp.tag("XRD", "Fe-Cr", "thin-film")

# 削除
exp.untag("thin-film")

# 確認
print(exp.tags)  # → ["XRD", "Fe-Cr"]
```

### 3.4 メモ

```python
exp.note("結晶性良好。(110)ピークがシャープ")
exp.note("追加測定不要と判断")

# メモは時系列で全て保持
for n in exp.notes:
    print(f"[{n.created_at}] {n.text}")
```

### 3.5 結果

```python
# dict-like アクセス
exp.results["lattice_a"] = 2.873
exp.results["phase"] = "BCC"
exp.results["peak_2theta"] = [44.67, 65.02, 82.33]

# まとめて更新
exp.results.update({
    "crystallinity": "good",
    "grain_size_nm": 45.2,
})

# 確認
print(exp.results["lattice_a"])  # → 2.873
print(dict(exp.results.items()))
```

### 3.6 ステータス

```python
# 設定
exp.status = "success"     # 成功
exp.status = "failed"      # 失敗
exp.status = "partial"     # 一部成功

# 確認
print(exp.status)  # → "success"
```

### 3.7 メソッドチェーン

全てのメソッドが `self` を返すので、連続して書ける。

```python
exp.tag("XRD", "Fe-Cr") \
   .conditions(temperature_C=500, pressure_Pa=0.5) \
   .note("結晶性良好")
```

### 3.8 コンテキストマネージャ

```python
with lab.new("XRD測定") as exp:
    exp.conditions(temperature_C=500)
    exp.add("xrd_data.csv")
    exp.results["lattice_a"] = 2.873
# ← exp.close() 自動呼び出し
#    status が RUNNING のままなら SUCCESS に変更
#    例外発生時は FAILED に変更
```

### 3.9 プロパティ一覧

```python
exp.id            # "AB3F"（Crockford's Base32 4文字）
exp.title         # "Fe-Cr薄膜 XRD測定"
exp.type          # "experiment"
exp.team          # "konishi-lab"
exp.created_by    # "tanaka"
exp.created_at    # datetime(2026, 3, 17, ...)
exp.updated_at    # datetime(2026, 3, 17, ...)
exp.parent_id     # None（子レコードの場合は親のID）
exp.status        # "running"
exp.tags          # ["XRD", "Fe-Cr"]
exp.notes         # [Note(text="...", created_at=...), ...]
exp.results       # {"lattice_a": 2.873, ...}
exp.nextcloud_url # "https://nextcloud.example.com/f/12345"
```

---

## 4. データの保存と取得

### 4.1 ファイルの追加

```python
# 単一ファイル
exp.add("xrd_data.csv")
exp.add("/path/to/sem_image.tiff")

# ディレクトリごと
exp.add_dir("sem_images/")

# バイナリデータ直接
exp.add(raw_bytes, name="spectrum.dat")
```

### 4.2 型自動判定の保存

```python
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# dict → JSON
exp.save("params", {"center": 28.4, "sigma": 0.18})

# ndarray → .npy + メタ情報
exp.save("spectrum", np.array([1.0, 2.0, 3.0]))

# DataFrame → CSV
exp.save("summary", pd.DataFrame({"x": [1, 2], "y": [3, 4]}))

# Figure → PNG
fig, ax = plt.subplots()
ax.plot([1, 2, 3])
exp.save("xrd_plot", fig)

# テキスト → .txt
exp.save("memo", "特記事項: なし")
```

### 4.3 データ取得

```python
# バイナリ取得
data = exp.get_data("xrd_data.csv")

# ファイル一覧
for ref in exp.list_data():
    print(f"{ref.name}  {ref.size_bytes}B  {ref.content_type}")
```

### 4.4 大容量データ（参照のみ）

```python
# HPC上の巨大ファイル（転送しない）
exp.add_ref(
    location="TSUBAME:/work/vasp/WAVECAR",
    size_gb=12,
    description="VASP WAVECAR（全電子波動関数）",
)

# DOIリンク
exp.add_ref(doi="10.5281/zenodo.12345", description="公開データセット")
```

### 4.5 ファイルパーサー（v10新機能）

対応ファイル形式を `exp.add()` すると、測定条件が自動抽出される。

```python
# Rigaku XRD .ras ファイル
exp.add("FeCr_001.ras")
# → conditionsに自動追加: target="Cu", voltage_kV=40, current_mA=30, ...

# 手動入力は上書きしない（手動入力が優先）
exp.conditions(target="Cu")  # 先に手動設定
exp.add("FeCr_001.ras")      # .rasからtargetを抽出しても上書きしない
```

対応形式:

| 拡張子 | 装置 | 抽出される情報 |
|--------|------|---------------|
| `.ras` | Rigaku XRD | target, voltage_kV, current_mA, 2θ範囲, スキャン速度 |
| `.dm3` `.dm4` | Gatan TEM | 加速電圧, 倍率, カメラ長 |
| `.tiff`(SEM) | SEM各社 | EXIFから加速電圧, 倍率, WD |
| `.dat`(MPMS/PPMS) | Quantum Design | 測定モード, 磁場範囲, 温度範囲 |
| `.wdf` | Renishaw Raman | レーザー波長, パワー, 対物レンズ |

パーサーの追加:

```python
from labvault.parsers import get_registry

class MyParser:
    @property
    def name(self): return "my_format"
    @property
    def extensions(self): return [".xyz"]
    def can_parse(self, path, content=None): return True
    def parse(self, path, content=None):
        return ParseResult(conditions={"key": "value"})

get_registry().register(MyParser())
```

---

## 5. 自動ログ（IPython hooks）

### 5.1 基本動作

`lab.new()` をJupyter Notebookで呼ぶだけで、以降の全セル実行が自動記録される。

```python
# セル1
from labvault import Lab
exp = Lab().new("解析テスト")
# → IPython hooks が自動起動

# セル2（自動記録される）
import numpy as np
data = np.loadtxt("xrd.csv", delimiter=",")
# → CellLog: source="import numpy as np\ndata = ...",
#             new_vars={"data": "<ndarray shape=(100,2) dtype=float64>"}

# セル3（自動記録される）
filtered = data[data[:, 1] > 100]
# → CellLog: source="filtered = data[...]",
#             new_vars={"filtered": "<ndarray shape=(42,2) dtype=float64>"}
```

何もしなくてOK。コードを書くだけで全履歴がFirestoreに保存される。

### 5.2 ログの一時停止

```python
# 一時停止
exp.pause_logging()

# 機密データの処理など
api_key = "sk-..."
result = call_external_api(api_key)

# 再開
exp.resume_logging()
```

コンテキストマネージャ版:

```python
with exp.no_logging():
    # このブロック内はログされない
    secret_process()
```

### 5.3 機微情報の自動マスク

変数名に `password`, `secret`, `token`, `key`, `credential` を含む変数は自動でマスクされる。

```python
api_key = "sk-1234567890"
# → CellLogには {"api_key": "***REDACTED***"} と記録
```

明示的に除外:

```python
exp.exclude_vars("my_private_var")
```

### 5.4 既存Recordへの追記・カーネル復帰

`lab.get(id, auto_log=True)` で既存Recordにセルログを追記できる。カーネル再起動後の復帰や、別Notebookでの解析追記に使う。

```python
# カーネルが死んだ後の復帰
from labvault import Lab
lab = Lab()
exp = lab.get("AB3F", auto_log=True)
# → IPython hooksが再起動。以降のセルはAB3Fに記録される

# 別Notebook（analysis.ipynb）からの追記
exp = lab.get("AB3F", auto_log=True)
# → セルログは自動的にセッション分離される
#    measurement.ipynb のログと analysis.ipynb のログが区別される
```

読み取りだけの場合は `auto_log` なし（デフォルト `False`）:

```python
exp = lab.get("AB3F")  # 読み取りのみ。hooksは起動しない
print(exp.results["lattice_a"])
```

### 5.5 2つ目のレコードへの切り替え

```python
exp1 = lab.new("実験1")
# → exp1のセルログが記録される

exp2 = lab.new("実験2")
# → exp1のログは自動停止、exp2のログが開始
```

### 5.6 装置制御スクリプト向けAPI（.py用）

IPython hooksが効かない `.py` スクリプトでは、明示的なログAPIを使う。

```python
# instrument_control.py（Notebookではなく通常のPythonスクリプト）
from labvault import Lab

lab = Lab()
exp = lab.new("スパッタ成膜", auto_log=False)  # hooksは不要
exp.conditions(temperature_C=500, pressure_Pa=0.5)

# 装置パラメータの時系列記録
exp.log_value("substrate_temperature_C", 501.2)
exp.log_value("chamber_pressure_Pa", 0.48)

# イベント記録
exp.log_event("rf_on", "RF電源 ON, 200W")
# ... 成膜中 ...
exp.log_event("rf_off", "RF電源 OFF")

exp.add("process_log.csv")
exp.status = "success"
```

### 5.7 @exp.track デコレータ（関数単位のトラッキング）

Notebook以外の環境では、関数単位でトラッキングする。

```python
exp = lab.new("バッチ処理", auto_log=False)

@exp.track
def fit_gaussian(data, initial_guess):
    from scipy.optimize import curve_fit
    popt, _ = curve_fit(gaussian, data[:, 0], data[:, 1], p0=initial_guess)
    return {"center": popt[0], "sigma": popt[1]}

# 関数呼び出し時に引数・戻り値・実行時間が自動記録
result = fit_gaussian(data, [28, 0.2])
```

ブロック単位:

```python
with exp.track_block("前処理"):
    data = load_and_clean(raw_path)
    # → ブロック内の変数変化がトレースに記録
```

### 5.6 手動スナップショット

```python
# 現在のローカル変数をキャプチャ
exp.snapshot()

# 特定の変数のみ
exp.snapshot(include=["data", "params"])

# 特定の変数を除外
exp.snapshot(exclude=["large_array"])
```

---

## 6. テンプレート

### 6.1 テンプレートの利用

```python
# テンプレート一覧を確認
for t in lab.templates():
    print(f"{t['name']}: {t['description']}")

# テンプレートを使ってレコード作成
exp = lab.new("XRD測定", template="XRD")
# → default_tagsが自動設定（["XRD"]）
# → required_conditionsが設定され、close()時に未入力チェック
```

### 6.2 必須条件の警告

```python
exp = lab.new("XRD測定", template="XRD")
exp.conditions(target="Cu")
# voltage_kV, current_mA 等は未入力

exp.status = "success"
# → UserWarning: テンプレート 'XRD' の必須条件が未入力です:
#     voltage_kV, current_mA, two_theta_range_start, two_theta_range_end
#   （警告のみ。エラーにはなりません）
```

### 6.3 エイリアス正規化

テンプレートの `aliases` に設定されたキー名は自動で正規化される。

```python
exp = lab.new("XRD測定", template="XRD")
exp.conditions(kV=40, mA=30, speed=2.0)
# → 内部的に正規化:
#    voltage_kV=40, current_mA=30, scan_speed_deg_per_min=2.0
```

### 6.4 チーム独自テンプレートの定義

```python
from labvault.core.types import ConditionField

lab.define_template(
    "sputter",
    type="process",
    default_tags=["sputtering"],
    condition_fields=[
        ConditionField(
            name="substrate_temperature_C",
            display_name="基板温度",
            type="float", unit="C",
            required=True,
            aliases=["temp", "T_sub"],
        ),
        ConditionField(
            name="rf_power_W",
            display_name="RF電力",
            type="float", unit="W",
            required=True,
            aliases=["power", "P_rf"],
        ),
        ConditionField(
            name="pressure_Pa",
            display_name="成膜圧力",
            type="float", unit="Pa",
            required=True,
        ),
        ConditionField(
            name="atmosphere",
            display_name="雰囲気",
            type="str",
            choices=["Ar", "N2", "O2", "Ar+O2"],
            default="Ar",
        ),
    ],
    recommended_results=["thickness_nm", "deposition_rate_nm_per_min"],
    indexed_fields=["substrate_temperature_C", "rf_power_W"],
)
```

---

## 7. 子レコードとリンク

### 7.1 子レコード

```python
# 親レコード（実験全体）
exp = lab.new("Fe-Cr薄膜 総合評価", type="experiment")

# 子レコード（個別の測定）
xrd = exp.sub("XRD測定", type="measurement")
xrd.conditions(target="Cu", voltage_kV=40)
xrd.add("xrd_data.ras")

sem = exp.sub("SEM観察", type="measurement")
sem.conditions(accelerating_voltage_kV=15, magnification=50000)
sem.add("sem_50k.tiff")

# 子レコード一覧
for child in exp.children():
    print(f"{child.id}: {child.title} [{child.status}]")
```

### 7.2 リンク

レコード間の関係を明示的に記録する。

```python
# サンプルと測定の紐付け
sample = lab.new("Fe-Cr #001", type="sample")
xrd = lab.new("XRD測定", template="XRD")
xrd.link(sample, relation="measured_on", description="Fe-Cr #001をXRD測定")
# → 逆方向リンク (sample → xrd: "measured_by") も自動作成

# やり直し実験
exp_v1 = lab.new("成膜 v1")
exp_v1.status = "failed"
exp_v1.note("圧力設定ミス")

exp_v2 = lab.new("成膜 v2")
exp_v2.link(exp_v1, relation="replaces")

# 利用可能なリレーション型
# derived_from  — このレコードの元データ
# produces      — このレコードが生成したデータ
# measured_on   — このサンプルを測定した
# replaces      — やり直し
# continues     — 同一サンプルの継続測定
# same_batch    — 同一バッチで作製
# compared_with — 比較対象
# references    — 参考文献・先行実験
# related_to    — その他（デフォルト）
```

### 7.3 プロセスチェーン（v10新機能）

多段階プロセスの順序関係を明示的に管理する。

```python
chain = lab.new_chain("セラミックス焼結", [
    "原料秤量", "混合", "仮焼", "粉砕", "本焼成", "研磨", "XRD"
])

# Step 1
step1 = chain.next("原料秤量", type="process")
step1.conditions(Fe2O3_g=5.0, Cr2O3_g=3.0)
step1.status = "success"

# Step 2（自動的に step1 → step2 の derived_from リンクが作成）
step2 = chain.next("遊星ミル混合", type="process")
step2.conditions(rotation_rpm=300, duration_min=60, media="ZrO2")
step2.status = "success"

# Step 3
step3 = chain.next("仮焼 800C", type="process")
step3.conditions(temperature_C=800, duration_h=2, atmosphere="air")
step3.status = "success"

# ... 以降同様
```

---

## 8. 検索

### 8.1 テキスト検索

```python
# 自然言語でセマンティック検索
results = lab.search("結晶性が良い薄膜")
results = lab.search("lattice constant Fe-Cr")  # 英語もOK

for r in results:
    print(f"{r.id}: {r.title} [{r.status}]")
```

### 8.2 フィルタ付き検索

```python
# タグ + ステータスでフィルタ
results = lab.search("XRD", tags=["Fe-Cr"], status="success")

# typeでフィルタ
results = lab.search("", type="sample")
```

### 8.3 一覧のフィルタ

```python
# 検索ではなく一覧のフィルタリング
records = lab.list(tags=["XRD"], status="success", limit=50)
records = lab.list(created_by="tanaka", type="experiment")
```

---

## 9. CLI

### 9.1 セットアップ

```bash
# 初期設定（対話形式）
labvault init

# 管理者から受け取った設定で初期化
labvault init --config konishi-lab-setup.toml

# 設定の健全性チェック
labvault doctor
# ✓ config.toml: OK
# ✓ GCP認証: OK
# ✓ Nextcloud接続: OK
# ✓ チーム "konishi-lab": メンバーとして登録済み
```

### 9.2 レコード操作

```bash
# レコード作成
labvault new "XRD測定" --template XRD --tag XRD --tag Fe-Cr
# → Created: AB3F "XRD測定"

# ファイル追加（装置PCから）
labvault add AB3F xrd_data.ras

# レコード一覧
labvault list
labvault list --tag XRD --status success

# レコード詳細
labvault show AB3F

# 検索
labvault search "Fe-Cr 格子定数"

# Nextcloud URL表示
labvault url AB3F
```

### 9.3 チーム管理（管理者のみ）

```bash
# メンバー追加
labvault team add-member tanaka
labvault team add-member suzuki --role admin

# メンバー一覧
labvault team members

# 設定テンプレートのエクスポート（新入生に配布用）
labvault team export-config > konishi-lab-setup.toml
```

---

## 10. よくあるパターン集

### パターン A: 単発XRD測定

```python
from labvault import Lab

lab = Lab()
exp = lab.new("Fe-50Cr XRD", template="XRD")
exp.conditions(target="Cu", voltage_kV=40, current_mA=30)
exp.add("FeCr50.ras")  # パーサーが残りのconditionsを自動抽出
exp.results["phase"] = "BCC"
exp.results["lattice_a"] = 2.873
exp.tag("Fe-Cr")
exp.status = "success"
```

### パターン B: 温度依存性（パラメータスイープ）

```python
lab = Lab()
sweep = lab.new("Fe-Cr 成膜温度依存性")
sweep.tag("temperature_sweep", "Fe-Cr")

for temp in [300, 500, 700]:
    dep = sweep.sub(f"成膜 {temp}C", type="process")
    dep.conditions(temperature_C=temp, pressure_Pa=0.5, power_W=200)
    dep.status = "success"

    xrd = dep.sub(f"XRD {temp}C", type="measurement", template="XRD")
    xrd.add(f"xrd_{temp}C.ras")
    xrd.status = "success"

sweep.note("300CはBCC、700CでFCC相が出現")
sweep.status = "success"
```

### パターン C: 同一サンプルの経時変化

```python
lab = Lab()

# サンプルレコード（一度だけ作成）
sample = lab.new("Fe-Cr #001", type="sample")
sample.conditions(composition="Fe-50at%Cr")
sample.tag("aging_study")
print(f"サンプルID: {sample.id}")  # → "AB3F"（メモしておく）

# 1週目の測定
m1 = lab.new("Week 1 XRD", template="XRD", sample=sample.id)
m1.conditions(aging_days=7)
m1.add("week1.ras")
m1.status = "success"

# 2週目の測定
m2 = lab.new("Week 2 XRD", template="XRD", sample=sample.id)
m2.link(m1, relation="continues")
m2.conditions(aging_days=14)
m2.add("week2.ras")
m2.status = "success"
```

### パターン D: 装置PCからのデータ投入

解析PCでレコードを作成し、装置PCからファイルだけ追加する。

```python
# 解析PC（自分のNotebook）
exp = lab.new("SEM観察", template="SEM")
exp.conditions(accelerating_voltage_kV=15, magnification=50000)
print(f"ID: {exp.id}")  # → "KL67"（装置PCの人に伝える）
```

```bash
# 装置PC（CLIまたはNextcloud）

# 方法1: CLI
labvault add KL67 sem_50k.tiff

# 方法2: Nextcloud ブラウザで _inbox/KL67/ にドラッグ&ドロップ

# 方法3: QRコードをスマホで読み取り → アップロード
```

### パターン E: 失敗実験の記録

失敗実験もきちんと記録する。将来のLLM検索で「なぜ失敗したか」を学べる。

```python
exp = lab.new("RF スパッタ（失敗）", template="sputter")
exp.conditions(temperature_C=300, pressure_Pa=5.0, rf_power_W=300)
exp.tag("sputtering", "Fe-Cr")
exp.note("ターゲット汚染のため膜質不良。研磨後に再実施")
exp.status = "failed"
```

### パターン F: Notebook での解析（自動ログ）

```python
# セル1
from labvault import Lab
import numpy as np
from scipy.optimize import curve_fit

lab = Lab()
exp = lab.new("XRDピークフィッティング")

# セル2（自動記録される）
data = np.loadtxt("xrd_data.csv", delimiter=",")
x, y = data[:, 0], data[:, 1]

# セル3（自動記録される）
def gaussian(x, amp, center, sigma):
    return amp * np.exp(-(x - center)**2 / (2 * sigma**2))

popt, pcov = curve_fit(gaussian, x, y, p0=[y.max(), x[y.argmax()], 1.0])

# セル4
exp.results["center"] = float(popt[1])
exp.results["sigma"] = float(popt[2])
exp.results["fwhm"] = float(2.355 * popt[2])

# セル5
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.scatter(x, y, s=5, label="data")
ax.plot(x, gaussian(x, *popt), "r-", label="fit")
ax.legend()
exp.save("fit_plot", fig)

exp.status = "success"
# → 全セルの実行履歴、変数変化、フィッティング結果、グラフが自動保存
# → LLMが「このフィッティングはどうやったの？」に答えられる
```

### パターン G: 装置制御（.py）→ 解析（.ipynb）の連携

装置制御スクリプトでRecordを作成し、解析Notebookで同じRecordに追記する。

```python
# ===== instrument_control.py（装置制御スクリプト）=====
from labvault import Lab

lab = Lab()
exp = lab.new("スパッタ成膜 Fe-Cr", template="sputter", auto_log=False)
exp.conditions(temperature_C=500, pressure_Pa=0.5, rf_power_W=200)

# 装置パラメータの時系列記録
exp.log_event("process_start", "基板加熱開始")
for t in measure_temperature_series():
    exp.log_value("substrate_temperature_C", t)
exp.log_event("deposition_start", "RF ON")
# ... 成膜 ...
exp.log_event("deposition_end", "RF OFF")

exp.add("process_log.csv")
exp.note(f"成膜完了。膜厚推定: 200nm")
# statusはまだ設定しない（解析後に判断）
print(f"Record ID: {exp.id}")  # → "AB3F"（解析Notebookで使う）
```

```python
# ===== analysis.ipynb（解析Notebook）=====
from labvault import Lab
lab = Lab()

# 既存Recordに接続（auto_log=True でセルログ記録開始）
exp = lab.get("AB3F", auto_log=True)
# → 以降のセルは AB3F に記録される（セッション自動分離）

# セル2: XRDデータ解析
import numpy as np
data = np.loadtxt("xrd_data.csv", delimiter=",")
# ... フィッティング ...

exp.results["lattice_a"] = 2.873
exp.results["phase"] = "BCC"
exp.save("fit_plot", fig)
exp.status = "success"
```

### パターン H: テスト（InMemoryBackend）

```python
import pytest
from labvault import Lab
from labvault.backends.memory import InMemoryMetadataBackend, InMemoryStorageBackend

@pytest.fixture
def lab():
    return Lab(
        "test-team",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
    )

def test_create_and_get(lab):
    exp = lab.new("テスト実験")
    exp.conditions(temperature_C=300)
    exp.tag("test")

    got = lab.get(exp.id)
    assert got.title == "テスト実験"
    assert got.get_conditions()["temperature_C"] == 300
    assert "test" in got.tags

def test_search(lab):
    lab.new("Fe-Cr XRD").tag("XRD")
    lab.new("Fe-Ni SEM").tag("SEM")

    results = lab.list(tags=["XRD"])
    assert len(results) == 1
    assert results[0].title == "Fe-Cr XRD"
```

---

## API クイックリファレンス

### Lab

| メソッド | 説明 |
|---------|------|
| `Lab(team?)` | 初期化 |
| `.new(title, template?, type?, **conditions)` | レコード作成 |
| `.get(id, auto_log=False)` | ID取得。`auto_log=True` で既存Recordにhooks追記 |
| `.list(tags?, status?, type?, limit?)` | 一覧 |
| `.search(query, tags?, status?)` | 検索 |
| `.recent(n)` | 最新n件 |
| `.today()` | 今日のレコード |
| `.delete(id)` | ソフトデリート |
| `.trash()` | ゴミ箱一覧 |
| `.restore(id)` | 復元 |
| `.sync()` | 手動同期 |
| `.sync_status` | 同期ステータス |
| `.templates()` | テンプレート一覧 |
| `.define_template(name, ...)` | テンプレート定義 |
| `.new_chain(name, steps)` | プロセスチェーン作成 |
| `.close()` | リソース解放 |

### Record

| メソッド/プロパティ | 説明 | チェーン |
|-------------------|------|:------:|
| `.id` | 4文字ID | - |
| `.title` | タイトル | - |
| `.status` | ステータス (get/set) | - |
| `.results` | 結果 (dict-like) | - |
| `.tags` | タグ一覧 | - |
| `.notes` | メモ一覧 | - |
| `.conditions(**kw)` | 条件設定 | ✓ |
| `.tag(*tags)` | タグ追加 | ✓ |
| `.untag(*tags)` | タグ削除 | ✓ |
| `.note(text)` | メモ追加 | ✓ |
| `.add(path)` | ファイル追加 | ✓ |
| `.add_dir(path)` | ディレクトリ追加 | ✓ |
| `.save(name, data)` | 型自動判定保存 | ✓ |
| `.add_ref(path?, doi?)` | 外部参照登録 | ✓ |
| `.sub(title, type?)` | 子レコード作成 | - |
| `.children()` | 子レコード一覧 | - |
| `.link(target, relation?)` | リンク作成 | ✓ |
| `.log_value(key, value)` | 時系列値記録（装置制御用） | ✓ |
| `.log_event(type, description)` | イベント記録（装置制御用） | ✓ |
| `.snapshot()` | 手動スナップショット | ✓ |
| `.pause_logging()` | 自動ログ停止 | ✓ |
| `.resume_logging()` | 自動ログ再開 | ✓ |
| `.close()` | 完了 | - |
