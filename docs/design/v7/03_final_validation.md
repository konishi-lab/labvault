# v7 最終検証: 実験者 + LLM解析者の視点から

> 検証者の立場: 実験物理学者（実験者兼解析者）。Jupyter Notebookで日常的にXRD・磁化測定のデータ解析を行う。
> 対象: REQUIREMENTS.md最新版、v6全設計ドキュメント、v5-review UXシミュレーション
> 日付: 2026-03-16

---

## 目次

1. [IPython hooks自動ログの実験者体験](#1-ipython-hooks自動ログの実験者体験)
2. [完全なNotebook例（v7最終版）](#2-完全なnotebook例v7最終版)
3. [LLMがセルログをどう使うか](#3-llmがセルログをどう使うか)
4. [全REQUIREMENTS要件の最終充足確認](#4-全requirements要件の最終充足確認)
5. [残る課題と妥協点](#5-残る課題と妥協点)

---

## 1. IPython hooks自動ログの実験者体験

### 1.1 「本当に何もしなくていいのか」の検証

REQUIREMENTS.md #6の設計では、`exp = lab.new()` を実行した時点でIPython環境を検出し、`pre_run_cell` / `post_run_cell` フックを自動登録する。以降の全セル実行が自動記録される。

**結論: ほぼ何もしなくていい。ただし「ほぼ」に注意。**

自動ログが記録するのは「セルのソースコード」と「新規/変更変数のスナップショット」。これだけでコードの実行履歴と変数値は完全に追える。

ただし、以下は自動ログでは**記録されない**:

| 項目 | 自動記録される？ | 補足 |
|------|-----------------|------|
| セルのソースコード | はい | そのまま記録 |
| 新規/変更変数 | はい | シリアライズ可能なもの |
| 実験の物理条件（温度、圧力） | **いいえ** | `exp.conditions()` で明示的に記録する必要あり |
| 結果の構造化データ | **いいえ** | `exp.results[...] = ...` で明示的に記録する必要あり |
| 生データファイル | **いいえ** | `exp.add()` で明示的に保存する必要あり |
| 図のファイル | **いいえ** | `exp.save("fig", fig)` で明示的に保存する必要あり |

つまり「プログラムの実行履歴の記録」は自動だが、「実験のメタデータと成果物の保存」は手動。これは正しい設計判断である。自動ログはあくまでLLMが「何をどの順番でどんなパラメータで処理したか」を再構成するための素材であり、実験者が意図的に残すべき情報（conditions, results, ファイル）の代替にはならない。

### 1.2 パフォーマンスへの懸念

**懸念: セル実行のたびにnamespace全体をスキャンするオーバーヘッド**

`_post_cell` フックでは `ip.user_ns` の全変数をイテレートし、`_summarize()` を適用する。

**見積もり:**
- 典型的なNotebookの変数数: 20〜50個
- `_summarize()` のコスト: 単純型(int, float, str)は即座。ndarray/DataFrameはshape/dtypeの取得のみ（O(1)）
- 合計: **数ミリ秒以下**

セル実行時間が通常0.1秒〜数分なので、数ミリ秒のオーバーヘッドは無視できる。

**ただし危険なケース:**
- 変数に巨大なリスト（100万要素のlist）が入っている場合、`_summarize()` で `len()` を呼ぶだけでもO(1)だが、内容のハッシュ計算（変更検出）でO(n)になる可能性がある
- **対策**: 変更検出は `id()` + `type()` + (ndarrayなら `shape`) のみで行い、値の比較はしない。値が同じでも再代入されていたら「変更あり」とみなす設計が安全

**結論: 通常のNotebook利用ではパフォーマンス問題なし。** 変更検出のアルゴリズムを軽量に保つ実装ガイドラインを明記すべき。

### 1.3 機微な情報（パスワード、APIキー）の扱い

**これは重大な懸念事項である。**

実験者がNotebookで以下のようなコードを書くことは日常的にある:

```python
# よくあるパターン
api_key = "sk-abc123..."
password = "my_secret_password"
nc_client = NextcloudClient(url, user, password)
```

自動ログがONの場合、`api_key` や `password` が `new_vars` として記録され、Firestoreに保存される。チーム全体が閲覧可能な状態になる。

**必須対策（MVP段階から実装すべき）:**

1. **変数名ベースのフィルタリング**: `password`, `secret`, `token`, `key`, `api_key`, `credential` 等を含む変数名は自動的にマスクする
2. **型ベースのフィルタリング**: 環境変数(`os.environ`)、設定オブジェクト(`pydantic.Settings`インスタンス)はデフォルトで除外
3. **明示的な除外設定**: `exp.exclude_vars("api_key", "password")` または `.mdxdbignore` ファイルでパターン指定
4. **ログ保存前のサニタイズ**: URLに含まれる認証情報（`https://user:pass@host/`）を自動検出してマスク

```python
# 自動マスクの例
# 実際の変数: api_key = "sk-abc123def456"
# 記録される値: api_key = "***REDACTED***"
```

**これが実装されていないと、セキュリティインシデントになる。MVP必須。**

### 1.4 自動ログを一時停止したい場合

**ユースケース:**
- 一時的に大量のセルを試行錯誤する（ゴミログを増やしたくない）
- 機微な操作をしている（上記のセキュリティ問題への一時対策）
- デバッグ中で無意味な実行を繰り返している

**提案するAPI:**

```python
# 一時停止
exp.pause_logging()

# ... この間のセル実行は記録されない ...

# 再開
exp.resume_logging()

# コンテキストマネージャでも使える
with exp.no_logging():
    # この中のセル実行は記録されない
    debug_output = some_debug_function()
```

**加えて、Jupyter上のトグルウィジェット（ON/OFF）があると直感的:**

```
[🔴 Auto-log: ON] ← クリックでOFF
```

### 1.5 100セル以上の長いNotebookでのログ量

**見積もり:**

| 項目 | 1セルあたり | 100セルで |
|------|-----------|----------|
| ソースコード | ~500バイト | ~50KB |
| new_vars (5個平均) | ~200バイト | ~20KB |
| changed_vars (3個平均) | ~120バイト | ~12KB |
| メタデータ(cell_number, duration等) | ~100バイト | ~10KB |
| **合計** | **~920バイト** | **~92KB** |

Firestoreの1ドキュメント上限は1MBなので、100セルを1ドキュメントに入れると余裕がある。ただし、セルログをサブコレクションに分けてトレースと同じ構造にする場合、100件のドキュメント書き込みが発生する。

**懸念:**
- Firestoreの書き込みコスト: 100件 x $0.18/100,000件 = ほぼ無料
- ネットワーク転送: 92KB = 無視できる
- **LLMへの転送**: 100セルのログを全部LLMに渡すと ~25,000トークン。コンテキストの10-25%を消費

**対策:**
- セルログも3段階の詳細度（L1/L2/L3）を導入
- L1: 「cell 5: cutoff=0.5を設定、filteredを計算」（1セル ~20トークン、100セルで ~2,000トークン）
- LLMはまずL1で全体を把握し、必要なセルだけL3で取得

**結論: ログ量自体は問題ない。LLMへの提供方法に工夫が必要。**

---

## 2. 完全なNotebook例（v7最終版）

### シナリオ: XRDデータの解析（Fe-10Cr合金、焼鈍温度依存性）

```python
# ============================================================
# セル1: セットアップ
# ============================================================
from mdxdb import Lab
import numpy as np
import matplotlib.pyplot as plt

lab = Lab("konishi-lab")

# → 自動記録: なし（lab.new() 前なのでフックは未登録）
```

```python
# ============================================================
# セル2: 実験レコード作成 + 自動ログ開始
# ============================================================
exp = lab.new("Fe-10Cr XRD 焼鈍温度依存性")
exp.conditions(
    sample="Fe-10at%Cr",
    instrument="Rigaku SmartLab",
    radiation="Cu-Ka",
    voltage_kV=40,
    current_mA=30,
    scan_range_deg=[20, 90],
    step_deg=0.02,
)
print(f"実験ID: {exp.id}")  # → "AB3F"

# → 自動記録: {
#     "cell_number": 2,
#     "source": "exp = lab.new(...)  exp.conditions(...) ...",
#     "new_vars": {"exp": "<Record id=AB3F title='Fe-10Cr XRD 焼鈍温度依存性'>"},
#     "duration_sec": 0.8
#   }
# ※ IPython hooksが exp = lab.new() で自動登録される
#   このセル自体が最初の記録対象
```

```python
# ============================================================
# セル3: 300°Cサンプルのデータ読み込み
# ============================================================
raw_300 = np.loadtxt("Fe10Cr_300C.csv", delimiter=",")
two_theta = raw_300[:, 0]
intensity_300 = raw_300[:, 1]

exp.add("Fe10Cr_300C.csv")  # 生データを保存

# → 自動記録: {
#     "cell_number": 3,
#     "source": "raw_300 = np.loadtxt(...) ...",
#     "new_vars": {
#       "raw_300": "<ndarray shape=(3501,2) dtype=float64>",
#       "two_theta": "<ndarray shape=(3501,) dtype=float64>",
#       "intensity_300": "<ndarray shape=(3501,) dtype=float64>"
#     },
#     "duration_sec": 0.05
#   }
```

```python
# ============================================================
# セル4: 500°C, 700°Cサンプルの読み込み
# ============================================================
raw_500 = np.loadtxt("Fe10Cr_500C.csv", delimiter=",")
intensity_500 = raw_500[:, 1]

raw_700 = np.loadtxt("Fe10Cr_700C.csv", delimiter=",")
intensity_700 = raw_700[:, 1]

exp.add("Fe10Cr_500C.csv")
exp.add("Fe10Cr_700C.csv")

# → 自動記録: {
#     "cell_number": 4,
#     "source": "raw_500 = np.loadtxt(...) ...",
#     "new_vars": {
#       "raw_500": "<ndarray shape=(3501,2) dtype=float64>",
#       "intensity_500": "<ndarray shape=(3501,) dtype=float64>",
#       "raw_700": "<ndarray shape=(3501,2) dtype=float64>",
#       "intensity_700": "<ndarray shape=(3501,) dtype=float64>"
#     },
#     "duration_sec": 0.08
#   }
```

```python
# ============================================================
# セル5: バックグラウンド除去（ベタ書き。関数化されていない）
# ============================================================
bg_order = 3

def remove_bg(theta, intensity):
    coeffs = np.polyfit(theta, intensity, bg_order)
    bg = np.polyval(coeffs, theta)
    return intensity - bg

int_300_nobg = remove_bg(two_theta, intensity_300)
int_500_nobg = remove_bg(two_theta, intensity_500)
int_700_nobg = remove_bg(two_theta, intensity_700)

# → 自動記録: {
#     "cell_number": 5,
#     "source": "bg_order = 3 ...",
#     "new_vars": {
#       "bg_order": 3,
#       "remove_bg": "<function remove_bg at 0x...>",
#       "int_300_nobg": "<ndarray shape=(3501,) dtype=float64>",
#       "int_500_nobg": "<ndarray shape=(3501,) dtype=float64>",
#       "int_700_nobg": "<ndarray shape=(3501,) dtype=float64>"
#     },
#     "duration_sec": 0.02
#   }
# ※ bg_order=3 が自動記録される。LLMは「3次多項式でバックグラウンド除去」と把握可能
```

```python
# ============================================================
# セル6: ピーク検出（関数化＋@exp.track）
# ============================================================
from scipy.signal import find_peaks

@exp.track
def detect_peaks(theta, intensity, height_threshold=100, distance_deg=0.5):
    """XRDピークの検出"""
    distance_pts = int(distance_deg / 0.02)
    peaks_idx, props = find_peaks(intensity, height=height_threshold, distance=distance_pts)
    return {
        "positions_deg": theta[peaks_idx].tolist(),
        "intensities": intensity[peaks_idx].tolist(),
        "n_peaks": len(peaks_idx)
    }

peaks_300 = detect_peaks(two_theta, int_300_nobg, height_threshold=80)
peaks_500 = detect_peaks(two_theta, int_500_nobg, height_threshold=80)
peaks_700 = detect_peaks(two_theta, int_700_nobg, height_threshold=80)

# → 自動記録（セルログ）: {
#     "cell_number": 6,
#     "source": "from scipy.signal import find_peaks ...",
#     "new_vars": {
#       "detect_peaks": "<tracked function detect_peaks>",
#       "peaks_300": {"positions_deg": [...], "intensities": [...], "n_peaks": 11},
#       "peaks_500": {"positions_deg": [...], "intensities": [...], "n_peaks": 12},
#       "peaks_700": {"positions_deg": [...], "intensities": [...], "n_peaks": 12}
#     },
#     "duration_sec": 0.15
#   }
#
# → @exp.track による追加記録（トレース x3）:
#   trace_1: detect_peaks(height_threshold=80, distance_deg=0.5) -> {n_peaks: 11}
#   trace_2: detect_peaks(height_threshold=80, distance_deg=0.5) -> {n_peaks: 12}
#   trace_3: detect_peaks(height_threshold=80, distance_deg=0.5) -> {n_peaks: 12}
```

```python
# ============================================================
# セル7: 格子定数の計算
# ============================================================
@exp.track
def calc_lattice_bcc(peak_positions_deg, wavelength_nm=0.15406):
    """BCC構造の格子定数をNelson-Riley法で計算"""
    theta_rad = np.radians(np.array(peak_positions_deg) / 2)
    d = wavelength_nm / (2 * np.sin(theta_rad))

    # BCC: h^2+k^2+l^2 = 2,4,6,8,10,12,...
    hkl_sum = [2, 4, 6, 8, 10, 12, 14, 16][:len(d)]
    a_vals = d * np.sqrt(hkl_sum)

    # Nelson-Riley外挿
    nr = np.cos(theta_rad)**2 / np.sin(theta_rad) + np.cos(theta_rad)**2 / theta_rad
    coeffs = np.polyfit(nr, a_vals, 1)
    a_0 = coeffs[1]

    return {"lattice_a_nm": float(a_0), "a_values": a_vals.tolist()}

lat_300 = calc_lattice_bcc(peaks_300["positions_deg"])
lat_500 = calc_lattice_bcc(peaks_500["positions_deg"])
lat_700 = calc_lattice_bcc(peaks_700["positions_deg"])

print(f"300°C: a = {lat_300['lattice_a_nm']:.4f} nm")
print(f"500°C: a = {lat_500['lattice_a_nm']:.4f} nm")
print(f"700°C: a = {lat_700['lattice_a_nm']:.4f} nm")

# → 自動記録（セルログ）: {
#     "cell_number": 7,
#     "new_vars": {
#       "calc_lattice_bcc": "<tracked function>",
#       "lat_300": {"lattice_a_nm": 0.2871, "a_values": [...]},
#       "lat_500": {"lattice_a_nm": 0.2873, "a_values": [...]},
#       "lat_700": {"lattice_a_nm": 0.2876, "a_values": [...]}
#     }
#   }
# → @exp.track トレース x3:
#   trace_4: calc_lattice_bcc(peak_positions_deg=[28.4,...], wavelength_nm=0.15406) -> {lattice_a_nm: 0.2871}
#   trace_5: calc_lattice_bcc(...) -> {lattice_a_nm: 0.2873}
#   trace_6: calc_lattice_bcc(...) -> {lattice_a_nm: 0.2876}
```

```python
# ============================================================
# セル8: 可視化 — 3温度の比較プロット
# ============================================================
fig, axes = plt.subplots(2, 1, figsize=(10, 10))

# 上段: XRDパターン重ね書き
for temp, intensity, peaks, color in [
    ("300°C", int_300_nobg, peaks_300, "blue"),
    ("500°C", int_500_nobg, peaks_500, "green"),
    ("700°C", int_700_nobg, peaks_700, "red"),
]:
    axes[0].plot(two_theta, intensity, color=color, alpha=0.7, label=temp)
    for p in peaks["positions_deg"]:
        axes[0].axvline(p, color=color, alpha=0.2, linestyle="--")

axes[0].set_xlabel("2θ (deg)")
axes[0].set_ylabel("Intensity (a.u.)")
axes[0].set_title("Fe-10Cr XRD: 焼鈍温度依存性")
axes[0].legend()

# 下段: 格子定数 vs 温度
temps = [300, 500, 700]
a_values = [lat_300["lattice_a_nm"], lat_500["lattice_a_nm"], lat_700["lattice_a_nm"]]
axes[1].plot(temps, a_values, "ko-", markersize=8)
axes[1].set_xlabel("焼鈍温度 (°C)")
axes[1].set_ylabel("格子定数 a (nm)")
axes[1].set_title("格子定数の温度依存性")

plt.tight_layout()
plt.show()

exp.save("xrd_comparison", fig)

# → 自動記録: {
#     "cell_number": 8,
#     "new_vars": {
#       "fig": "<Figure 10x10>",
#       "axes": "<ndarray shape=(2,) of Axes>",
#       "temps": [300, 500, 700],
#       "a_values": [0.2871, 0.2873, 0.2876]
#     },
#     "duration_sec": 0.45
#   }
```

```python
# ============================================================
# セル9: 結果の構造化保存
# ============================================================
exp.results["temperatures_C"] = [300, 500, 700]
exp.results["lattice_a_nm"] = {
    "300C": lat_300["lattice_a_nm"],
    "500C": lat_500["lattice_a_nm"],
    "700C": lat_700["lattice_a_nm"],
}
exp.results["n_peaks"] = {
    "300C": peaks_300["n_peaks"],
    "500C": peaks_500["n_peaks"],
    "700C": peaks_700["n_peaks"],
}
exp.results["phases"] = ["BCC"]
exp.results["trend"] = "格子定数は温度上昇に伴い微増（熱膨張+Cr拡散の効果）"

# → 自動記録: {
#     "cell_number": 9,
#     "source": "exp.results[...] = ...",
#     "changed_vars": {
#       "exp": "<Record id=AB3F results updated>"
#     }
#   }
```

```python
# ============================================================
# セル10: タグ付けとメモ
# ============================================================
exp.tag("Fe-Cr", "XRD", "annealing", "temperature-dependence", "BCC")
exp.note("300-700°Cの焼鈍温度依存性を測定。BCC単相を全温度で確認。"
         "格子定数は温度上昇に伴い0.2871→0.2876nmへ微増。"
         "700°Cでもσ相の析出なし。")

# → 自動記録: {
#     "cell_number": 10,
#     "source": "exp.tag(...) exp.note(...)",
#     "changed_vars": {"exp": "<Record id=AB3F tags/notes updated>"}
#   }
```

```python
# ============================================================
# セル11: Notebookの保存と完了
# ============================================================
exp.log_notebook()     # 現在のNotebook全体を保存
exp.status = "success"

print(f"実験 {exp.id} を記録しました")
print(f"  格子定数: 300°C={lat_300['lattice_a_nm']:.4f}, "
      f"500°C={lat_500['lattice_a_nm']:.4f}, "
      f"700°C={lat_700['lattice_a_nm']:.4f} nm")
print(f"  URL: {exp.url}")

# → 自動記録: {
#     "cell_number": 11,
#     "changed_vars": {"exp": "<Record id=AB3F status=success>"}
#   }
```

```python
# ============================================================
# セル12: LLMに質問（MCP経由のClaude Desktop、またはWebAppチャット）
# ============================================================
# このセルはNotebook内ではなく、Claude Desktop / WebAppチャットで実行する。
#
# ユーザー: 「Fe-10Crの最適な焼鈍温度は？過去の全データを踏まえて。」
#
# LLMの処理:
#   1. search("Fe-10Cr 焼鈍 XRD", filters={tags: ["Fe-Cr"]})
#   2. get_results("lattice_a_nm", filters={tags: ["Fe-10Cr"]})
#   3. aggregate("crystallite_size_nm", group_by="conditions.temperature_C")
#   4. 今回のAB3Fのデータ + 過去データを統合して回答
#
# LLMの回答:
#   「過去15件のFe-10Cr実験データ（300-800°C）を分析しました。
#    結晶子サイズは700°Cで最大（67.8nm）。
#    格子定数は温度上昇に伴い単調増加。
#    800°Cでは酸化層形成のため結晶性が低下（レコードHG9Wの所見）。
#
#    結論: 最適焼鈍温度は700°C付近。
#    ただし今回のAB3Fデータは700°Cまでしかなく、
#    750°Cの追加実験で最適温度をより精密に決定することを推奨します。」
```

**記録内容のまとめ:**

| セル | 明示的操作 | 自動記録 | @exp.track |
|------|-----------|---------|------------|
| 1 | なし | なし（フック未登録） | — |
| 2 | `lab.new()`, `conditions()` | セルログ（exp変数） | — |
| 3 | `exp.add()` | セルログ（raw_300等） | — |
| 4 | `exp.add()` x2 | セルログ（raw_500, raw_700等） | — |
| 5 | なし | セルログ（bg_order=3, nobg配列） | — |
| 6 | なし | セルログ + **トレースx3** | detect_peaks x3 |
| 7 | なし | セルログ + **トレースx3** | calc_lattice_bcc x3 |
| 8 | `exp.save()` | セルログ（fig, a_values） | — |
| 9 | `exp.results[...]` | セルログ | — |
| 10 | `exp.tag()`, `exp.note()` | セルログ | — |
| 11 | `exp.log_notebook()` | セルログ | — |
| 12 | （Claude Desktop） | — | — |

**実験者が明示的に書くコードの総行数: 約15行**（conditions, add, save, results, tag, note, log_notebook, status）。残りの解析コードは普通に書くだけ。

---

## 3. LLMがセルログをどう使うか

### 3a) 「この実験の処理手順を説明して」

```
ユーザー: AB3Fの処理手順を説明して。

LLM → MCP: get_detail(id="AB3F", include_traces=true, trace_level="L2")

MCP → LLM:
  セルログ:
    cell 2: 実験作成。conditions: Fe-10Cr, SmartLab, Cu-Ka
    cell 3: Fe10Cr_300C.csv 読み込み。raw_300 shape=(3501,2)
    cell 4: Fe10Cr_500C.csv, Fe10Cr_700C.csv 読み込み
    cell 5: bg_order=3 でバックグラウンド除去。int_300_nobg等を生成
    cell 6: detect_peaks(height_threshold=80, distance_deg=0.5)。
            300°C: 11本, 500°C: 12本, 700°C: 12本
    cell 7: calc_lattice_bcc(wavelength_nm=0.15406)。
            300°C: 0.2871nm, 500°C: 0.2873nm, 700°C: 0.2876nm
    cell 8: XRDパターン比較プロット + 格子定数vs温度プロットを作成
    cell 9: results に構造化データを保存
    cell 10: タグ付け + 所見メモ
    cell 11: Notebook保存、status=success

LLM → ユーザー:
  「AB3Fの処理手順は以下の通りです:

   1. データ読み込み: 3つの温度（300, 500, 700°C）のXRDデータ（各3501点）を
      CSVファイルから読み込み
   2. バックグラウンド除去: 3次多項式フィッティングでバックグラウンドを除去
   3. ピーク検出: 閾値80、最小間隔0.5°でピーク検出
      → 300°C: 11本、500/700°C: 12本のピーク
   4. 格子定数算出: Nelson-Riley法（Cu-Ka線、λ=0.15406nm）で
      BCC格子定数を外挿計算
   5. 可視化: 3温度のXRDパターン重ね書き + 格子定数の温度依存性プロット

   使用した解析パラメータ:
   - バックグラウンド: poly_order=3
   - ピーク検出: threshold=80, distance=0.5°
   - 波長: Cu-Ka 0.15406nm（デフォルト）

   参照: セルログ cell 3-8, トレース tr_001-006」
```

**ポイント**: セルログだけでも処理の流れが追える。`@exp.track` のトレースがあることで、関数の引数値（`height_threshold=80`）がより正確に記録される。

### 3b) 「田中さんのcutoffと鈴木さんのcutoffを比較して」

```
ユーザー: 田中さん(AB3F)と鈴木さん(CD5G)はXRD解析のフィルタリングで
          異なるcutoffを使っているらしい。比較して。

LLM → MCP: compare_runs(
    record_ids=["AB3F", "CD5G"],
    function_name="detect_peaks",
    show_diff_only=true
)

MCP → LLM:
  parameter_diff:
    - detect_peaks.height_threshold: AB3F=80, CD5G=120
    - detect_peaks.distance_deg: AB3F=0.5, CD5G=0.3
  result_diff:
    - n_peaks: AB3F=12, CD5G=15

LLM（@exp.track がない場合、セルログのみで対応）:
  → セルログの cell 5 を比較:
    AB3F cell 5: bg_order=3
    CD5G cell 5: bg_order=5, cutoff_freq=0.4 ← 変数名から拾える
  → セルログの cell 6 を比較:
    AB3F cell 6: height_threshold=80 ← 変数として記録されている
    CD5G cell 6: height_threshold=120 ← 同上

LLM → ユーザー:
  「田中さん(AB3F)と鈴木さん(CD5G)の解析パラメータ比較:

   | パラメータ | 田中(AB3F) | 鈴木(CD5G) | 影響 |
   |-----------|-----------|-----------|------|
   | bg_order | 3 | 5 | 高次多項式はピーク裾を削るリスク |
   | height_threshold | 80 | 120 | 鈴木さんの方が弱いピークを見落とす可能性 |
   | distance_deg | 0.5 | 0.3 | 鈴木さんの方が近接ピークを分離できる |

   結果として:
   - 田中さん: 12本検出（閾値が低いため弱いピークも拾う）
   - 鈴木さん: 15本検出（最小間隔が小さいため近接ピークを分離）

   推奨: チームで標準パラメータを決めることを推奨します。
   特にheight_thresholdの統一は比較可能性のために重要です。」
```

**ポイント**: `@exp.track` があればパラメータ差分が構造化データとして正確に得られる。セルログのみの場合でも、変数値が `new_vars` に記録されているため、LLMが変数名からパラメータを推定できる。ただしセルログだけでは「どの変数がどの関数の引数か」の対応関係が曖昧になるリスクがある。

### 3c) 「この結果は正しい？他の実験と比較して」

```
ユーザー: AB3Fの格子定数 a=0.2876nm（700°C焼鈍）は正しいですか？
          他の実験結果と比較してください。

LLM → MCP: get_results(
    result_key="lattice_a_nm",
    filters={tags: ["Fe-10Cr"], status: "success"},
    sort_by="value"
)

MCP → LLM:
  entries:
    EF2H: Fe-10Cr 600°C a=0.2874 (tanaka, 2025-11)
    GH4J: Fe-10Cr 700°C a=0.2875 (suzuki, 2025-12)
    KL6M: Fe-10Cr 700°C a=0.2877 (yamada, 2026-01)
    AB3F: Fe-10Cr 700°C a=0.2876 (tanaka, 2026-03) ← 今回
  statistics: mean=0.2876, std=0.0001 (700°Cのみ, n=3)

LLM → MCP: explain_result(record_id="AB3F", result_key="lattice_a_nm.700C")

MCP → LLM:
  produced_by: calc_lattice_bcc
  input_chain:
    1. remove_bg(bg_order=3)
    2. detect_peaks(threshold=80)
    3. calc_lattice_bcc(wavelength=0.15406) -> 0.2876

LLM → ユーザー:
  「AB3Fの格子定数 a=0.2876nm（700°C焼鈍）の妥当性評価:

   ■ 他の実験との比較
   Fe-10Cr 700°C焼鈍の過去データ（n=3）:
   - GH4J(鈴木): 0.2875nm
   - KL6M(山田): 0.2877nm
   - AB3F(田中): 0.2876nm ← 今回
   → 平均: 0.2876nm, 標準偏差: 0.0001nm

   AB3Fは平均値とほぼ一致しており、正常範囲内です。

   ■ 文献値との比較
   Fe-10at%Crの格子定数（BCC）: 0.2870-0.2878nm（700°C焼鈍後）
   → AB3Fの値は文献値の範囲内です。

   ■ 解析パラメータの確認
   バックグラウンド除去(3次) → ピーク検出(閾値80) → Nelson-Riley法で算出。
   パラメータは過去実験と同等であり、系統誤差の懸念はありません。

   結論: 信頼性は高い。値は妥当です。」
```

**ポイント**: `get_results` による横断検索で同条件の過去データを即座に集約。`explain_result` で算出過程を確認し、解析パラメータの一貫性も検証。これはセルログ + `@exp.track` + `results` の3層のデータが揃って初めて可能になる回答品質。

---

## 4. 全REQUIREMENTS要件の最終充足確認

### Tier 1: 絶対に必要な7要件

| # | 要件 | 評価 | 詳細 |
|---|------|------|------|
| 1 | チームでデータを共有し活用 | **OK** | Firestore + Nextcloudでチーム共有。search / MCPで横断検索。設計上問題なし |
| 2 | LLMによる検索と解析 | **OK** | MCPツール10種、トレース3段階詳細度、embedding戦略が明確。v6で大幅に具体化された |
| 3 | 実験者が使いやすいSDK | **OK（懸念あり）** | 基本操作は3行で完結。ただしIPython hooks自動ログの機微情報フィルタが未設計（1.3節参照）。MVP段階でのsanitize実装が必須 |
| 4 | 別PC・別フェーズのデータ紐付け | **OK** | 4文字IDでどのPCからもアクセス。WebApp/CLI/Nextcloudブラウザの3経路。設計上問題なし |
| 5 | 子レコード（階層構造） | **OK** | `exp.sub()` で子レコード作成。再帰的な階層も可能。v6のSDK設計で型定義済み |
| 6 | 実行コード+変数をセットで保存 | **OK** | IPython hooks自動ログ（セルソース+変数diff）+ `@exp.track`（関数引数・返り値）+ `snapshot()` の3層。REQUIREMENTSの要件を完全に満たす |
| 7 | 保存先はGCP + Nextcloud | **OK** | Firestore(メタデータ) + Nextcloud(バイナリ) + Vertex AI(embedding)。Phase 2でBigQuery追加。アーキテクチャ確定済み |

### Tier 2: 高い優先度の追加要件

| # | 要件 | 評価 | 詳細 |
|---|------|------|------|
| 8 | ローカルバッファ必須 | **OK（実装設計が必要）** | REQUIREMENTS.mdでTier 1に昇格済み。設計方針は確定しているが、具体的な実装設計（SQLiteか、JSONか、同期キューの仕組み）がまだ詳細化されていない |
| 9 | 投入経路の多様性 | **OK** | SDK / CLI / Nextcloudブラウザの3経路。WebAppは将来 |
| 10 | テンプレートシステム | **OK** | `template="XRD"` で自動設定。設計済みだがビルトインテンプレートの内容は未定義 |
| 11 | タグ・ステータス・メモ | **OK** | `exp.tag()`, `exp.status`, `exp.note()` で対応。設計上問題なし |
| 12 | MCPサーバー | **OK** | 10種のツール仕様がv6で完全に定義済み |

### Tier 3からの重要指摘

| # | 要件 | 評価 | 詳細 |
|---|------|------|------|
| 13 | Recordモデルの汎用化 | **OK** | `type` フィールドで experiment/sample/process/measurement等を表現 |
| 19 | ソフトデリート/ゴミ箱 | **懸念あり** | v5-review UXシミュレーションで発見された重要要件。REQUIREMENTSには追加されたが、SDK設計やFirestoreスキーマへの反映がまだ不明確 |

---

## 5. 残る課題と妥協点

### 5.1 これだけ議論しても解決できていない問題

#### 問題1: IPython hooks自動ログの機微情報フィルタリング

v6までの議論では「自動ログで変数を全キャプチャする」設計になっているが、パスワード・APIキー等の機微情報が変数に含まれる場合の処理が未設計。

**解決方針**: 変数名パターンマッチ（`*password*`, `*secret*`, `*token*`, `*key*`, `*credential*`）でのデフォルトマスク + `exp.exclude_vars()` での明示的除外。これはMVPで必須。

#### 問題2: ローカルバッファの具体的な実装

「ローカルバッファ必須」はTier 1に昇格したが、以下が未定:
- SQLite vs JSON vs Pickle の選択
- 同期キューの管理（FIFO? 優先度?）
- コンフリクト解決（オフライン中に同じレコードを別PCから更新した場合）
- ローカルバッファのサイズ制限と清掃ポリシー

**解決方針**: 実装しながら決める。最初はJSON + ファイルベースの単純な方式で開始し、問題が出たらSQLiteに移行。

#### 問題3: `snapshot()` vs `@exp.track` vs セル自動ログの使い分け

v6の議論で「初心者には `snapshot()` だけ教える」方針になったが、REQUIREMENTSの最新版ではIPython hooks自動ログが追加されたため、**4つの記録方法**が存在する:

1. IPython hooks自動ログ（完全自動）
2. `snapshot()`（明示的）
3. `@exp.track`（関数デコレータ）
4. `track_block()`（ブロック単位）

自動ログがあるなら、`snapshot()` は基本的に不要になる。ただしスクリプト(.py)実行時には自動ログがないため、`snapshot()` が必要。

**解決方針**: 使い分けマトリクスを明確にドキュメント化する。

| 環境 | 自動記録 | 追加で推奨 |
|------|---------|-----------|
| Jupyter Notebook | セル自動ログ（何もしない） | `@exp.track`（関数化済みのコードに） |
| Pythonスクリプト | なし | `@exp.track` or `snapshot()` |
| ループ/スイープ | セル自動ログ | `track_block()` |

#### 問題4: セル自動ログとFirestoreの書き込みタイミング

セル実行のたびにFirestoreに書き込むと:
- 100セルのNotebookで100回のAPI呼び出し
- ネットワーク遅延がセル実行体験に影響する可能性

**解決方針**: ローカルバッファに蓄積し、バッチで非同期送信。送信間隔はデフォルト30秒。`exp.flush()` で即時送信も可能。

#### 問題5: Nextcloud認証とSDK認証の統合

v5-review UXシミュレーションでも指摘されている。SDKはFirestore（GCP認証）とNextcloud（独自認証）の両方にアクセスするが、認証フローの統合が不明確。

**解決方針**: `mdxdb login` でGCP認証を行い、Nextcloud認証情報は管理者が`.env` / `config.toml`で配布。個別のNextcloudアカウントではなく、チーム共有のサービスアカウントを使用する方式が現実的。

### 5.2 「完璧を求めて実装が始まらない」リスクの評価

**リスクは高い。**

v1からv6まで6イテレーションの設計議論を重ね、多角的なレビュー（実験物理学者、理論物理学者、化学者、エンジニア、UXデザイナー）を経ている。設計の完成度は高いが、**まだ1行もコードが書かれていない**。

設計段階で解決すべき問題と、実装しながら解決すべき問題を明確に分ける必要がある:

**設計段階で確定すべき（完了済み）:**
- Firestoreのスキーマ構造
- MCPツールのインターフェース
- SDKの公開API（`lab.new()`, `exp.add()` 等）
- トレースの3段階詳細度

**実装しながら決めるべき:**
- ローカルバッファの実装方式
- `_summarize()` のシリアライズ戦略の詳細
- 機微情報フィルタのパターンリスト
- embeddingの品質チューニング（同義語辞書の内容等）
- セル自動ログのバッチ送信間隔の最適値
- テンプレートのビルトイン内容

### 5.3 「ここは実装しながら決める」項目の仕分け

| 項目 | 設計完了? | 実装しながら決める | 備考 |
|------|---------|-----------------|------|
| **SDK公開API** | 完了 | — | v6で型定義まで詳細化済み |
| **Firestoreスキーマ** | 完了 | — | Record, traces サブコレクション確定 |
| **MCPツール仕様** | 完了 | — | 10種のリクエスト/レスポンスが定義済み |
| **Backend Protocol** | 完了 | — | 抽象インターフェース確定 |
| **ローカルバッファ** | 方針のみ | **要** | JSON→SQLiteの段階的移行で開始 |
| **機微情報フィルタ** | 未着手 | **要（ただしMVP必須）** | 変数名パターンマッチから開始 |
| **セルログのバッチ送信** | 方針のみ | **要** | 30秒間隔で開始、フィードバックで調整 |
| **embedding品質** | 方針のみ | **要** | テストセットを作って計測しながら改善 |
| **テンプレート内容** | 未着手 | **要** | XRD, SEM, SQUIDの3種から開始 |
| **WebApp** | スコープ外 | **要** | MVP後に開始。Streamlit or Next.js |
| **ソフトデリート** | 方針のみ | **要** | status="deleted" + 30日保持。Firestore TTLで実現可能 |

### 5.4 実装開始への推奨事項

1. **今すぐ開始できる**: SDK Core（lab.py, record.py, types.py）+ InMemoryBackend + テスト
2. **Week 1で着手すべき**: ローカルバッファの最小実装（JSON + ファイルベース）
3. **Week 2で着手すべき**: IPython hooksの実装（機微情報フィルタ含む）
4. **Week 3-4**: FirestoreBackend + NextcloudBackend
5. **Week 5-6**: MCPサーバー + CLI
6. **Week 7**: Alpha版リリース

**最も重要なこと**: v6の設計は十分に成熟している。これ以上設計を重ねるよりも、**InMemoryBackendでSDK Coreを実装し、実際のNotebookで動かしてフィードバックを得る**ことの方が、設計の不備を早期に発見できる。

---

## 総合評価

### 実験者として

この設計は**使える**。IPython hooks自動ログにより、Notebookでの日常的な解析作業に追加負担がほぼゼロで実行履歴が残る。`conditions` と `results` の手動入力は必要だが、これは実験ノートに記入するのと同じ作業であり、本質的に省略できないものである。

最も心配なのは「機微情報が自動ログに混入する問題」と「ローカルバッファなしではデータ消失の恐怖がある問題」の2点。この2つがMVPで解決されていれば、Alphaユーザーとして日常利用を開始できる。

### LLM解析者として

セルログは**十分に活用できる**。セルのソースコード + 変数のdiff が記録されていれば、処理パイプラインの再構成、パラメータの比較、結果の妥当性検証がすべて可能。`@exp.track` のトレースがあればさらに精度が上がるが、セルログだけでも基本的な質問には回答できる。

MCPツールの設計（特に `explain_result` と `compare_runs`）は、LLMのコンテキストウィンドウを効率的に使うための適切な抽象化であり、実用的な設計になっている。

### 最終判断

**設計フェーズを終了し、実装を開始すべき。**

v1-v6で6回のイテレーションを経て、SDK API、Firestoreスキーマ、MCPツール仕様、トレース設計が十分に具体化されている。残る未決事項（ローカルバッファ実装、機微情報フィルタ、embedding品質）はすべて実装しながら決められる性質のものである。

これ以上の設計議論は、実装からのフィードバックがない限り、同じ論点を異なる角度から繰り返すだけになるリスクが高い。
