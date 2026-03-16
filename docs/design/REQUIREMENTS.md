# 重要要件一覧

> ここまでの議論から抽出した、ユーザー（プロジェクトオーナー）の要件。
> スペシャリストレビューの指摘ではなく、**あなた自身が述べた要件**を優先。

---

## 核心の目的

**実験者がコードに組み込みやすく、結果としてのデータがLLMが扱いやすい形で貯まるライブラリ**

---

## Tier 1: 絶対に必要（あなたが明言した要件）

### 1. チームでデータを共有し、活用する
- 実験チーム（研究室）が1つのデータプールを共有
- 全メンバーのデータが検索・閲覧可能
- LLMがチーム全体のデータを横断的に解析

### 2. LLMによるデータの検索と解析
- データを入れる → LLMから呼び出す → 解析する、の全フローが設計されている
- **速さと正確さ**が最重要
- 数万件規模での検索性能

### 3. 実験者が使いやすいSDK
- 実験コードに組み込みやすい（最小限のboilerplate）
- 汎用的な実験用ライブラリ（特定プロジェクトに縛られない）

### 4. 別PC・別フェーズのデータを後から紐付け
- サンプル作製と測定が別PCで行われる前提
- 短いID（"ab3f"）で、どのPCからでもデータを追加できる
- 装置PCはPythonが使えないことがある → Nextcloudブラウザ経由でも投入可能

### 5. 子レコード（階層構造）
- 1回の実験で1サンプルに対し、複数の加工条件 × 複数の測定
- 測定はデータとして入れれば十分（独立した実験ではない）
- 測定条件が複雑な場合は孫レコードにもできる（柔軟）

### 6. 実験コード + 実行時の変数をセットで保存
- 分析コード（Python/Jupyter）をデータと一緒に保存
- **コード実行時の変数の値**もセットで保存（コードだけでは再現条件が不明）
- LLMがコード + 変数の値を読んで「何をどういう条件で計算したか」を正確に理解できる

```python
# === 基本: 1行呼ぶだけで全部自動キャプチャ ===
exp.snapshot()

# → 呼び出し時点のスタックフレームから自動取得:
#   - ローカル変数の値（シリアライズ可能なもの）
#   - コードのファイル名・行番号・関数名
#   - Python版・パッケージバージョン
#   - Git commit hash（リポジトリ内なら）

# === 実際の使い方 ===
cutoff_freq = 0.5
window_size = 1024
method = "butterworth"
order = 4

filtered = apply_filter(raw_data, cutoff_freq, window_size, method, order)

exp.snapshot()  # ← この時点の変数を全キャプチャ
exp.save("filtered_data", filtered)

# === 保存される内容（LLMが読める形） ===
{
  "snapshot_at": "2026-03-16T15:30:00",
  "caller": {
    "file": "analysis.py",
    "line": 42,
    "function": "process_xrd"
  },
  "locals": {
    "cutoff_freq": 0.5,
    "window_size": 1024,
    "method": "butterworth",
    "order": 4,
    "raw_data": "<ndarray shape=(5000,2) dtype=float64>",  # 大きいオブジェクトは要約
    "filtered": "<ndarray shape=(5000,2) dtype=float64>"
  },
  "env": {
    "python": "3.12.0",
    "packages": {"numpy": "1.26.0", "scipy": "1.12.0"},
    "git_commit": "abc123"
  }
}

# === 複数回呼べば実行の流れが追える ===
raw = load_data("xrd.ras")
exp.snapshot()  # snapshot #1: データ読み込み後

processed = remove_background(raw, poly_order=3)
exp.snapshot()  # snapshot #2: バックグラウンド除去後

peaks = find_peaks(processed, threshold=100)
exp.snapshot()  # snapshot #3: ピーク検出後

# → LLMは3つのsnapshotを時系列で辿り、
#   「poly_order=3でバックグラウンド除去→threshold=100でピーク検出」
#   という処理フローと各段階の変数値を完全に把握できる
```

**自動ログの設計思想: 実験者は何もしなくていい**

Notebookのコードは70%が関数化されていない（ベタ書き）。
デコレータは関数にしか付けられない。
→ **Jupyterのセル実行を自動で全部記録する**のが最もシンプル。

```python
# === これだけ。以降の全セル実行が自動記録される ===
from mdxdb import Lab
exp = Lab("konishi-lab").new("XRD解析")

# ↑ IPython環境を検出し、pre_run_cell / post_run_cell フックを自動登録。
# 以降、実験者が普通にNotebookを書くだけで全てログされる。
```

```python
# --- セル2（普通にデータ読み込み） ---
import numpy as np
data = np.loadtxt("xrd_data.csv", delimiter=",")
cutoff = 0.5

# → 自動記録:
# {
#   "cell_number": 2,
#   "source": "import numpy as np\ndata = np.loadtxt(...)\ncutoff = 0.5",
#   "new_vars": {
#     "data": "<ndarray shape=(5000,2) dtype=float64>",
#     "cutoff": 0.5
#   },
#   "duration_sec": 0.12
# }
```

```python
# --- セル3（前処理） ---
from scipy.signal import butter, filtfilt
b, a = butter(4, cutoff, btype='low')
filtered = filtfilt(b, a, data[:, 1])

# → 自動記録:
# {
#   "cell_number": 3,
#   "source": "from scipy.signal import ...\n...",
#   "new_vars": {"filtered": "<ndarray shape=(5000,) dtype=float64>"},
#   "changed_vars": {},  ← 前セルから変わった変数
#   "duration_sec": 0.05
# }
```

```python
# --- セル4（結果保存。これだけ明示的） ---
exp.results["n_peaks"] = 12
exp.results["lattice_a"] = 2.873
exp.save("filtered_data", filtered)
```

**実装の仕組み（IPython hooks）:**
```python
# IPython環境検出時に自動登録
ip = get_ipython()
ip.events.register('pre_run_cell', self._pre_cell)
ip.events.register('post_run_cell', self._post_cell)

def _pre_cell(self, info):
    # セル実行前のnamespace（変数一覧）をスナップショット
    self._pre_ns = {k: _summarize(v) for k, v in ip.user_ns.items()
                    if not k.startswith('_')}

def _post_cell(self, result):
    # セル実行後のnamespaceとdiffを取って、新規/変更変数を検出
    post_ns = {k: _summarize(v) for k, v in ip.user_ns.items()
               if not k.startswith('_')}
    new_vars = {k: v for k, v in post_ns.items() if k not in self._pre_ns}
    changed_vars = {k: v for k, v in post_ns.items()
                    if k in self._pre_ns and v != self._pre_ns[k]}
    # Firestoreに自動保存
    self._save_cell_log(source=info.raw_cell, new_vars=new_vars, ...)
```

**スクリプト(.py)の場合はデコレータも使える:**
```python
# Notebook: 自動（何もしなくていい）
# スクリプト: @exp.track で関数単位、または with exp.track_block() でブロック単位

@exp.track
def process_xrd(data, cutoff=0.5):
    ...
```

**3つのモード（環境に応じて自動選択）:**

| 環境 | 方法 | 実験者の手間 |
|------|------|------------|
| **Jupyter Notebook** | IPython hooksで全セル自動記録 | **ゼロ**（`exp = lab.new()` だけ） |
| **Pythonスクリプト** | `@exp.track` デコレータ or `with exp.track_block()` | デコレータ1行 |
| **どちらでも** | `exp.snapshot()` で明示的にキャプチャ | 1行 |

**LLMから見た価値:**
- Notebookの全セル実行履歴が残る → 「どの順番で何を実行したか」が完全にわかる
- 各セルの新規/変更変数が記録される → 「cutoffの値は何だったか」が正確
- 関数呼び出しツリー（@exp.track使用時）→ 処理パイプラインの構造把握
- **実験者が記録を忘れることが構造的にない**

**`conditions` との使い分け:**
- `conditions` = 実験者が意図的に記録する物理条件（温度、圧力）
- セル自動記録 / `@exp.track` = プログラムの実行状態の自動キャプチャ

### 7. 保存先はGCP + Nextcloud（30TB無料ストレージ）

**確定アーキテクチャ:**

```
Phase 1（初期）:
  Nextcloud (30TB無料) = バイナリ実体の倉庫 + ブラウザ投入口
  Firestore            = メタデータ、リアルタイム読み書き、ベクトル検索
  Vertex AI            = Embedding生成、Gemini

Phase 2（後から追加）:
  BigQuery             = Firestoreから自動同期。LLM向けSQL分析、横断集約
```

- **Nextcloud**: 30TBの無料ストレージ。バイナリ実体はここに保存。ブラウザ投入口にもなる
- **Firestore**: メタデータのリアルタイム読み書き。サーバーレス、月$5-20
- **BigQuery**: 後から追加。Firestoreの自動エクスポート機能で連携（設定だけ、コード変更ほぼ不要）
- **GCP内完結**: コンプライアンス審査が通りやすい

Phase 1 コスト: 月$5-20（Firestore）+ Nextcloud無料

---

### 8a. 大容量データ対応（Tier 1に昇格）
- 数GB~TBのデータは転送せず参照登録（`add_ref()`）
- 外部リポジトリ（DOI等）へのリンク
- 中サイズ（100MB~数GB）はNextcloudへの非同期アップロード
- LLMにはサマリー/統計量のみ渡す（バイナリ全体は渡さない）

### 8b. LLMによるコード実行解析（Tier 1に昇格）
- LLMがデータに対して**Pythonコードを生成・実行**し、結果をグラフ/画像で返す
- 具体的なユースケース:
  - 「hogehogeに正規分布でフィッティングして、各パラメータを結果として」
  - 「同じ解析をfugaにも適用して」
  - 「全サンプルのXRDデータにピークフィッティングを一括実行して、結果を比較表で」
- **任意のスクリプトを複数データに一括適用**し、結果をグラフ/画像で閲覧
- 設計上のポイント:
  - MCPサーバーにサンドボックス化されたPython実行環境を持たせる
  - LLMがコードを生成 → 実行環境で実行 → 結果（数値+画像）をLLMに返す → ユーザーに提示
  - 同一コードを複数レコードに一括適用する `batch_execute` ツール
  - 生成された画像/グラフはレコードに自動保存される
  - **解析履歴の自動保存**: 実行コード・入力ファイル・結果（数値+画像）・元の指示・実行日時が全てレコードに記録される
  - 「誰がいつどんなコードでどんな結果を得たか」を後から完全に辿れる
  - 過去の解析コードを再利用して他のレコードに適用できる
  - WebAppで解析履歴をコード+グラフ付きで閲覧可能
  - **解析の連鎖**: 過去の解析結果を入力にして次の解析を実行できる
    - フィッティング → 結果の横断比較 → 相関解析 → 統計検定 と積み重ね可能
    - 各ステップが全て自動保存され、解析の論理的な流れが追跡可能
    - LLMが過去の解析結果（数値・画像）を参照して次の解析コードを生成できる

### 8c. データ投入時の自動処理トリガー（Tier 1）
- ファイルがレコードに追加されたとき、ファイル種別に応じた前処理を自動実行
- 具体例:
  - **画像（SEM, 光学顕微鏡等）**: サムネイル/プレビュー画像の自動生成（大容量TIFFを小さなPNG/JPEGに）
  - **NumPy配列**: 統計サマリー（shape, dtype, min/max/mean/std）の自動計算
  - **CSV/TSV**: カラム名・行数・先頭数行のプレビューを自動抽出
  - **Notebook(.ipynb)**: セル一覧・出力サマリーの自動抽出
- トリガーの仕組み: Firestoreの `data_refs` フィールド更新 → Cloud Functions起動
- 生成物は `_preview/` 配下に自動保存（元データは変更しない）
- LLMは元の大容量ファイルではなくプレビュー/サマリーを参照（高速+コンテキスト節約）
- ユーザーが独自のトリガー処理を追加登録できる（将来）

```
exp.add("SEM_50000x.tif")  # 200MB の SEM画像

→ 自動で以下が生成される:
  _preview/SEM_50000x_thumb.jpg    (256x256, 数KB)
  _preview/SEM_50000x_preview.jpg  (1024x1024, 数十KB)
  _preview/SEM_50000x_meta.json    (解像度, ビット深度, サイズ等)

→ LLMやWebAppはプレビューを参照。元の200MBは触らない。
```

```
ユーザー: 「AB3FのXRDデータに正規分布でフィッティングして」

LLM:
  1. get_file_content("AB3F", "xrd.csv") でデータ取得
  2. Pythonコードを生成:
     from scipy.optimize import curve_fit
     popt, pcov = curve_fit(gaussian, x, y)
     fig = plot_fit(x, y, popt)
  3. execute_code(record_id="AB3F", code=上記) で実行
  4. 結果: popt=[center=28.4, sigma=0.18, amp=15000]
     + フィッティンググラフ画像

ユーザー: 「同じ解析をKL67とST45にも」

LLM:
  1. batch_execute(record_ids=["KL67","ST45"], code=同じコード)
  2. 3つの結果を比較表+重ね書きグラフで返す
```

---

## Tier 2: 高い優先度（議論の中で合意した要件）

### 8. ローカルバッファ必須（Tier 1に昇格）
- **`exp.add()` したデータは必ずローカルに先に保存してからリモートに送る**
- ネットワークエラーでデータが消失することは絶対にあってはならない
- オフライン時はローカルに保存、オンライン復帰時に自動同期
- 「データが消えるかも」という恐怖があると誰も使わない → MVP必須

### 9. 投入経路の多様性
- ① Python SDK（メイン）
- ② CLI
- ③ Nextcloudブラウザ（装置PCなどPythonなし環境）
- ④ Web UI（将来）

### 10. テンプレートシステム
- XRD, SEM等のよく使う測定のテンプレートを事前定義
- 装置条件やデフォルトタグが自動設定される

### 11. タグ・ステータス・メモ
- 失敗実験も記録（status: failed/partial/success）
- タグで分類、メモで後から情報追記
- 後付け可能（「まず記録、整理は後」）

### 12. MCPサーバー
- LLMからデータにアクセスするためのインターフェース
- Claude Desktop / Claude Code から接続

---

## Tier 3: スペシャリストレビューからの重要指摘

### 13. Recordモデルの汎用化
- `type` フィールドで用途を表現（experiment, sample, process, reaction, computation等）
- 材料科学だけでなく化学・計算科学にも対応可能に

### 14. バッチ操作
- パラメータスイープの一括登録（`sweep()`）
- ディレクトリ構造からの自動インポート

### 15. 大容量データの参照登録
- TB級データは転送せず参照（`add_ref()`）
- 外部リポジトリ（DOI等）へのリンク

### 16. LLMの役割の明確化
- LLM = オーケストレーター（検索・要約・提案）
- 数値計算・フィッティング → Python実行環境に委譲

### 17. エクスポート/バックアップ
- GCP非依存のローカルバックアップ
- `lab.export()` でフルエクスポート

### 18. FAIR原則への段階的対応
- ライセンス、DOI、メタデータ標準（将来的に）

---

### 19. ソフトデリート/ゴミ箱（UXシミュレーションで発見）
- 誤削除防止: 削除は即座に消さず、ゴミ箱（30日保持）に移動
- 管理者のみ完全削除可能
- 削除権限: 作成者 + 管理者のみ

---

---

## 確定事項

### パッケージ名: `labvault`
- PyPI名: `labvault`
- import: `from labvault import Lab`
- CLI: `labvault init`, `labvault new`, `labvault add`, ...
- SDKリポジトリ: `kpro-arim-mdxdb` → 将来的に `labvault` にリネームも検討
- プラットフォームリポジトリ: `labvault-platform`（モノレポ）

---

## 明示的にスコープ外とするもの

- Web UIの初期実装（将来対応）
- オントロジーマッピング（将来対応）
- HPC連携（将来対応）
- 全ての装置フォーマットのパーサー（プラグインとして将来対応）
