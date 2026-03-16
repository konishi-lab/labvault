# v7 最終設計 統合ドキュメント

> v1-v6の全議論を統合した最終設計。
> **「Notebookで普通にコードを書くだけで、全実行履歴がLLMに理解可能な形で自動保存される」** が最大の差別化。
>
> 詳細:
> - [01_sdk_design.md](./01_sdk_design.md) — SDK最終設計：IPython hooks実装、ローカルバッファ、API (77KB)
> - [02_platform_design.md](./02_platform_design.md) — プラットフォーム最終設計：GCP、MCP、WebApp (58KB)
> - [03_final_validation.md](./03_final_validation.md) — 実験者による最終検証：Notebook例、要件充足 (38KB)

---

## 独自価値（他のツールにないもの）

```
MLflow:  mlflow.log_param("cutoff", 0.5)  ← 手動で書く必要がある
W&B:     wandb.config.cutoff = 0.5        ← 手動で書く必要がある
Sacred:  @ex.config で定義                  ← 設定ファイルが必要

mdxdb:   exp = lab.new("XRD解析")          ← これだけ。以降の全セル実行が自動記録。
         cutoff = 0.5                       ← 自動でキャプチャされる。手動記録不要。
```

---

## アーキテクチャ（v5-lite採用。5コンポーネント）

```
実験者 Notebook/Script
    │
    ▼
┌──────────────────────────────┐
│  SDK (pip install mdxdb)      │
│  ├── IPython hooks (自動ログ) │
│  ├── ローカルバッファ (SQLite) │  ← データは必ずローカルに先に保存
│  └── Firestore + Nextcloud    │
└──────────┬───────────────────┘
           │
    ┌──────┴──────┐
    ▼              ▼
Firestore      Nextcloud (30TB無料)
(メタデータ     (バイナリ実体)
 +Vector Search
 +セルログ)
    │
    ▼
Vertex AI Embeddings
    │
    ▼
MCP Server (Cloud Functions)  ←── LLM (Claude)
    │
    ▼
Streamlit WebApp（Phase 2）
```

**Phase 1 (MVP): 5コンポーネントのみ**
- Firestore、Vertex AI Embeddings、Cloud Functions、Secret Manager、Nextcloud
- 月額 $0-5

**v5の14コンポーネントから大幅削減。** Cloud Run、Firebase Auth、Firebase Hosting、TerraformはPhase 1不要。

---

## SDK設計の核心

### 自動ログ（IPython hooks）

```python
# セル1: これだけで自動ログ開始
from mdxdb import Lab
exp = Lab("konishi-lab").new("XRD解析")

# セル2: 普通にコードを書く → 自動記録
import numpy as np
data = np.loadtxt("xrd.csv", delimiter=",")
cutoff = 0.5

# → 自動記録: {cell: 2, new_vars: {data: "<ndarray (5000,2)>", cutoff: 0.5}}

# セル3: 前処理 → 自動記録
from scipy.signal import butter, filtfilt
b, a = butter(4, cutoff, btype='low')
filtered = filtfilt(b, a, data[:, 1])

# → 自動記録: {cell: 3, new_vars: {filtered: "<ndarray (5000,)>"}}

# セル4: 結果保存（これだけ明示的）
exp.results["n_peaks"] = 12
exp.results["lattice_a"] = 2.873
exp.save("filtered", filtered)
```

### ローカルバッファ（MVP必須）

```
exp.add("data.ras")
  → ① ローカルSQLiteに記録 + ローカルファイルにコピー（即座）
  → ② バックグラウンドでNextcloudにアップロード + Firestoreに登録
  → ネットワーク障害でも①は成功。データは消えない。
```

### 主要API

```python
# 記録
exp = lab.new("タイトル", sample="試料名")
exp.add("path/to/file")              # ファイル投入（→ Nextcloudに保存）
exp.add("path/to/directory/")        # ディレクトリごと投入
exp.save("name", data)               # 型自動判定（dict→JSON, ndarray→npy, Figure→PNG）
exp.sub("子レコード名")               # 子レコード
exp.tag("XRD", "Fe-Cr")
exp.status = "success"
exp.note("メモ")
exp.conditions(temperature_C=300)
exp.results["lattice_a"] = 2.873

# 大容量データ対応
exp.add_ref(                          # 転送せず参照だけ登録
    path="/hpc/scratch/WAVECAR",
    location="TSUBAME:/home/user/WAVECAR",
    size_gb=8.5,
    description="波動関数ファイル"
)
exp.add_ref(doi="10.5281/zenodo.12345")  # 外部リポジトリへのリンク

# 検索
lab.search(tag="XRD", sample__contains="Fe-Cr")
lab.search("温度300度以上の実験")      # セマンティック検索
lab.get("AB3F")                        # IDで取得
lab.recent(10)

# 自動ログ制御
exp.pause_logging()                    # 一時停止
exp.resume_logging()                   # 再開
```

### 大容量データ対応

```
データサイズに応じた3段階の保存戦略:

小 (~100MB):  exp.add("file.csv")
              → ローカルバッファ → Nextcloud (30TB) → Firestoreにメタデータ
              → 通常フロー。自動。

中 (100MB~数GB): exp.add("OUTCAR")
              → 同上。Nextcloudの30TBに収まる限り問題なし。
              → アップロードはバックグラウンド（非同期）。進捗表示あり。

大 (数GB~TB): exp.add_ref("/hpc/scratch/WAVECAR", location="TSUBAME:...")
              → 転送しない。Firestoreにメタデータ+場所の参照だけ登録。
              → LLMには description と size だけ渡す。
              → 必要に応じて部分取得: exp.get("WAVECAR", offset=0, size=1024)
```

| サイズ | 方法 | 保存先 | LLMへの情報 |
|--------|------|--------|------------|
| ~100MB | `exp.add()` | Nextcloud | ファイル内容（テキスト）or 統計サマリー（バイナリ） |
| 100MB~数GB | `exp.add()` | Nextcloud（非同期アップロード） | 統計サマリー + 先頭N行 |
| 数GB~TB | `exp.add_ref()` | **転送しない**（参照のみ） | description + size のみ |
| 外部リポジトリ | `exp.add_ref(doi=...)` | **リンクのみ** | DOI + description |

**Nextcloud 30TBの容量管理:**
- 研究室規模（月20GB新規）なら数年は余裕
- 大規模MD等を多用する場合は `add_ref()` で転送を回避
- `lab.storage_usage()` で使用量を確認可能

---

## MCPサーバー（14ツール）

| ツール | 概要 |
|--------|------|
| `search` | ハイブリッド検索（構造化+ベクトル） |
| `get_detail` | レコード詳細 |
| `compare` | 複数レコード比較 |
| `data_preview` | ファイル統計サマリー |
| `get_results` | 構造化結果の横断検索 |
| `aggregate` | 数値集約 |
| `get_timeline` | サンプルの実験履歴 |
| `get_trace` | @exp.track の関数トレース |
| `explain_result` | 結果の算出過程説明 |
| `compare_runs` | パラメータ差異の比較 |
| `get_notebook_log` | IPython セルログ取得 |
| **`execute_code`** | **LLMが生成したPythonコードを実データに対して実行** |
| **`batch_execute`** | **同一コードを複数レコードのデータに一括適用** |
| **`get_image`** | **実行結果の画像/グラフを取得** |

### LLMコード実行解析（v7の核心機能）

```
ユーザー: 「AB3FのXRDデータに正規分布でフィッティングして」

LLM → execute_code:
  record_id: "AB3F"
  file: "xrd.csv"
  code: |
    import numpy as np
    from scipy.optimize import curve_fit

    def gaussian(x, amp, center, sigma):
        return amp * np.exp(-(x - center)**2 / (2 * sigma**2))

    data = np.loadtxt(file_path, delimiter=",")
    x, y = data[:, 0], data[:, 1]
    popt, pcov = curve_fit(gaussian, x, y, p0=[y.max(), x[y.argmax()], 1.0])

    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    ax.plot(x, y, 'o', label='data')
    ax.plot(x, gaussian(x, *popt), '-', label='fit')
    ax.legend()

    result = {
        "amplitude": popt[0],
        "center": popt[1],
        "sigma": popt[2],
        "fwhm": 2.355 * popt[2]
    }

→ レスポンス:
  results: {amplitude: 15000, center: 28.4, sigma: 0.18, fwhm: 0.42}
  images: ["fit_plot.png"]  ← レコードに自動保存される

ユーザー: 「同じ解析をKL67とST45にもやって」

LLM → batch_execute:
  record_ids: ["AB3F", "KL67", "ST45"]
  file: "xrd.csv"
  code: (同上)

→ レスポンス:
  results: [
    {record: "AB3F", center: 28.4, sigma: 0.18, fwhm: 0.42},
    {record: "KL67", center: 28.6, sigma: 0.22, fwhm: 0.52},
    {record: "ST45", center: 28.3, sigma: 0.16, fwhm: 0.38}
  ]
  images: ["comparison_plot.png"]
  → 各レコードの results にも自動保存
```

**実行結果の自動保存と閲覧:**

`execute_code` の結果は**全て自動保存**され、後から「どんな解析をしたか」を完全に辿れる。

```
records/{record_id}/
  analyses/                          ← 解析履歴（自動保存）
    {analysis_id}/                   # Crockford's Base32 ユニークID（例: "AN7K"）
      id: "AN7K"                     # ユニークID（レコードIDと同じ方式）
      name: "gaussian_fit_001"       # 人間可読な名前（自動生成 or ユーザー指定）
      code: str                      # 実行したPythonコード全文
      input_files: ["xrd.csv"]       # 入力に使ったファイル
      input_analyses: ["AM3J"]       # 前の解析結果を入力にした場合、そのID
      results: {                     # 数値結果
        "center": 28.4,
        "sigma": 0.18,
        "fwhm": 0.42
      }
      images: ["AN7K_fit_plot.png"]  # 画像ファイル名にもIDプレフィックス
      executed_at: timestamp
      executed_by: "claude"          # LLM or ユーザー名
      prompt: "正規分布でフィッティングして"
      duration_sec: 1.2
      packages: {"scipy": "1.12.0", "numpy": "1.26.0"}
```

**名前のバッティング防止:**
- `analysis_id` はCrockford's Base32のユニークID（レコードIDと同じ方式）
- `name` は人間可読な名前。自動生成（`gaussian_fit_001`）or ユーザー/LLMが指定
- 画像ファイル名にもIDプレフィックス（`AN7K_fit_plot.png`）→ 複数解析の画像が混ざらない
- 同じレコードに何回フィッティングしても、各々が独立したIDを持つ

```python
# 名前の自動生成ルール:
# 1. LLMの指示から推測: "正規分布でフィッティング" → "gaussian_fit"
# 2. 同名がある場合は連番: "gaussian_fit_001", "gaussian_fit_002"
# 3. ユーザーが明示的に指定も可能:
exp.analyses(name="gaussian_fit")  # 名前で検索
exp.analyses(id="AN7K")            # IDで検索
```

**閲覧方法:**

```python
# SDK: レコードの解析履歴を確認
exp = lab.get("AB3F")
for a in exp.analyses():
    print(f"{a.executed_at} | {a.prompt} | {a.results}")

# MCP: LLMが過去の解析を参照
# → get_detail(record_id="AB3F", include_analyses=True) で取得可能

# WebApp: 解析履歴タブに時系列で表示
#   - コード（シンタックスハイライト付き）
#   - 結果の数値
#   - 生成グラフの画像
#   - 「同じ解析を再実行」ボタン
#   - 「同じ解析を他のレコードにも適用」ボタン
```

**LLMが過去の解析を活用する例:**

```
ユーザー: 「AB3Fに前にやったフィッティング、KL67にも同じようにやって」

LLM:
  1. get_detail("AB3F", include_analyses=True)
     → 過去の解析コードを取得
  2. execute_code("KL67", code=過去のコードをそのまま再利用)
  3. 結果を比較して回答
```

→ **解析の再現・再利用がコード付きで可能。**
→ 「誰がいつどんなコードでどんな結果を得たか」が全て記録される。

**実行環境の設計:**
- Cloud Functions or Cloud Run 上のサンドボックス
- numpy, scipy, matplotlib, pandas がプリインストール
- データファイルはNextcloudから一時取得 → 実行 → 結果返却
- 実行時間制限（60秒）、メモリ制限（2GB）
- 生成画像はNextcloudに自動保存
- **実行コード・結果・画像・元の指示が全てFirestoreに自動保存（解析の来歴）**

---

## WebApp: Streamlit（Phase 2）

- Python統一（Next.js/TypeScriptの学習コスト不要）
- 1画面1日の開発速度
- 主要画面: ダッシュボード、レコード詳細、検索、アップロード、LLMチャット

---

## Firestoreデータモデル

```
teams/{team_id}/
  records/{record_id}/
    meta: {title, type, status, tags, conditions, results, ...}
    embedding: vector(768)
    data_refs: {filename: {nextcloud_path, size, ...}}
    cell_logs/                    ← IPython hooks 自動記録
      {cell_log_id}: {cell_number, source, new_vars, changed_vars, duration}
    traces/                       ← @exp.track 関数トレース
      {trace_id}: {function, args, return, call_tree, env}
    sub_records/                  ← 子レコード（再帰）
  templates/{name}: {...}
```

---

## リポジトリ構成

```
kpro-arim-mdxdb/              ← SDK（独立。pip install用）
├── src/mdxdb/
│   ├── core/                  # Lab, Record, types, config, id
│   ├── backends/              # memory, firestore, nextcloud
│   ├── tracking/              # IPython hooks, @exp.track, snapshot
│   ├── buffer/                # ローカルバッファ（SQLite）
│   └── cli/                   # Click CLI
├── tests/
└── pyproject.toml

kpro-arim-platform/           ← モノレポ（プラットフォーム）
├── mcp-server/                # FastMCP (Cloud Functions)
├── webapp/                    # Streamlit
├── functions/                 # Cloud Functions（embedding生成、NC同期）
└── infra/                     # GCP設定スクリプト
```

---

## 実装ロードマップ

| Week | マイルストーン | 成果 |
|------|-------------|------|
| 1-2 | **M0: 基盤+POC** | GCPセットアップ、Firestore Vector Search性能検証、パッケージ名決定 |
| 2-4 | **M1: SDK Core** | Lab, Record, add, save, sub, search, Firestore+Nextcloud統合 |
| 4-5 | **M2: 自動ログ** | IPython hooks, ローカルバッファ, @exp.track |
| 5-6 | **M3: Embedding** | Vertex AI統合, Vector Search, セマンティック検索 |
| 6-7 | **M4: MCP+CLI** | 11ツール, Claude Desktop接続, CLIコマンド |
| **Week 7** | **★ MVP** | **チームAlpha利用開始** |
| 8-10 | M5: WebApp | Streamlit（ダッシュボード、検索、アップロード） |
| 10-12 | M6: LLMチャット | WebApp上のLLMチャット、BigQuery連携 |
| **Week 12** | **★ Beta** | **チーム本格利用** |

---

## 確定要件の充足状況

| # | 要件 | 状態 |
|---|------|------|
| 1 | チームでデータ共有 | ✅ Firestore + チームコレクション |
| 2 | LLMで検索→解析 | ✅ MCP 11ツール + セルログ + results構造化 |
| 3 | 使いやすいSDK | ✅ 3行開始 + 自動ログ + ローカルバッファ |
| 4 | 別PC紐付け | ✅ Crockford's Base32 ID + CLI + WebApp(Phase 2) |
| 5 | 子レコード階層 | ✅ .sub() + type |
| 6 | コード+変数の自動保存 | ✅ IPython hooks + @exp.track |
| 7 | Firestore + Nextcloud | ✅ |
| 8 | ローカルバッファ必須 | ✅ SQLite + ローカルファイル |

---

## 次のアクション

1. **パッケージ名を決定する**
2. **M0: GCPセットアップ + POC開始**
