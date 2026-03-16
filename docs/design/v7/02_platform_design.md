# v7 プラットフォーム最終設計

> v1-v6の全議論を統合した最終設計。
> v5-reviewの「複雑すぎる」批判を全面的に受け入れ、**v5-liteアプローチ**を基本とする。
> IPython hooks自動ログ（セルログ）がLLMにどう活用されるかを核心に据える。

---

## 目次

1. [設計の基本方針](#1-設計の基本方針)
2. [GCPアーキテクチャ最終版](#2-gcpアーキテクチャ最終版)
3. [セルログデータのLLM活用設計](#3-セルログデータのllm活用設計)
4. [MCPサーバー最終ツール一覧](#4-mcpサーバー最終ツール一覧)
5. [WebApp設計の最終判断](#5-webapp設計の最終判断)
6. [Nextcloud連携の最終設計](#6-nextcloud連携の最終設計)
7. [リポジトリ構成の最終版](#7-リポジトリ構成の最終版)
8. [実装ロードマップ最終版](#8-実装ロードマップ最終版)

---

## 1. 設計の基本方針

### 1.1 v5-reviewの批判の受容

v5-reviewの核心的指摘は「14コンポーネントは研究室ツールとして複雑すぎる」こと。これは正しい。

**v7の判断: v5-liteアプローチを全面採用。**

理由:
- 開発者1-2人で維持可能なスコープに限定する
- 言語をPythonに統一する（TypeScript排除）
- YAGNIの原則を徹底する
- 「最初から完璧」ではなく「動くものを早く出して改善」

### 1.2 v6のトレース設計は維持

v6で追加された `@exp.track` とIPython hooks自動ログは、このプロジェクトの**最大の差別化要素**であり、LLM活用の核心。設計はv6をそのまま引き継ぐ。

ただしREQUIREMENTSで明確化された通り、**Notebookの自動セルログがメインの記録手段**であり、`@exp.track` はスクリプト用の補助手段。Notebookユーザーの「手間ゼロ」を最優先する。

### 1.3 確定した設計判断の一覧

| 判断事項 | v5 | v5-review指摘 | **v7最終判断** |
|---------|-----|--------------|---------------|
| WebApp | Next.js | Streamlit推奨 | **Streamlit（Python統一）** |
| API Server | Cloud Run (FastAPI) | 最初は不要 | **Phase 2で追加** |
| 認証 | Firebase Auth | 過剰 | **Phase 1: サービスアカウントのみ** |
| Terraform | 必要 | 不要 | **gcloud CLIで十分** |
| モノレポ言語 | Python + TypeScript | Python統一 | **Python統一** |
| コンポーネント数 | 14 | 半減すべき | **Phase 1: 5コンポーネント** |
| Embedding | Vertex AI | ローカル併用 | **ローカル優先 + Vertex AIフォールバック** |
| 自動ログ | @exp.track | - | **IPython hooks自動ログをメインに** |

---

## 2. GCPアーキテクチャ最終版

### 2.1 Phase別アーキテクチャ

#### Phase 1（MVP）: 5コンポーネント — 月$0-5

```
┌──────────────┐  ┌──────────┐
│  Python SDK  │  │   CLI    │
│  (研究者PC)  │  │ (mdxdb)  │
└──────┬───────┘  └────┬─────┘
       │               │
       │  直接アクセス   │  直接アクセス
       ▼               ▼
┌─────────────────────────────────────────────┐
│              GCP (asia-northeast1)           │
│                                             │
│  ┌────────────┐  ┌────────────────────────┐ │
│  │  Firestore  │  │  Cloud Functions       │ │
│  │  メタデータ  │  │  (Embedding生成        │ │
│  │  +Vector    │  │   onCreate トリガー)   │ │
│  │  +セルログ   │  │                       │ │
│  └────────────┘  └────────────────────────┘ │
│                                             │
│  ┌────────────┐                             │
│  │  Vertex AI  │                             │
│  │  Embedding  │                             │
│  └────────────┘                             │
└─────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────┐
│  Nextcloud (arim.mdx.jp) — 30TB無料         │
│  バイナリ実体の倉庫                           │
└─────────────────────────────────────────────┘
```

**Phase 1で使うGCPサービス:**

| # | サービス | 役割 | コスト |
|---|---------|------|-------|
| 1 | Firestore | メタデータ + Vector Search + セルログ | $0-5/月 |
| 2 | Cloud Functions (Gen2) | Embedding生成トリガー | $0/月（無料枠内） |
| 3 | Vertex AI Embedding | text-embedding-004 | $0-0.50/月 |
| 4 | Secret Manager | Nextcloud認証情報 | $0/月 |
| 5 | Nextcloud | バイナリストレージ（GCP外） | $0（30TB無料） |

**Phase 1で使わないもの（v5からの削除）:**
- Cloud Run（API Server不要。SDK/CLIがFirestore直接アクセス）
- Firebase Auth（サービスアカウントで十分）
- Firebase Hosting（WebAppはPhase 2以降）
- Cloud Scheduler（ポーラー不要。Phase 2以降）
- BigQuery（Phase 3以降）
- Terraform（gcloud CLIで管理）
- Next.js / TypeScript（Streamlit + Pythonに統一）

**合計: 月$0-5**（Firestoreの無料枠: 50K読み取り/日、20K書き込み/日で収まる規模なら$0）

#### Phase 2（MCP + WebApp）: 8コンポーネント — 月$0-15

```
┌──────────┐ ┌─────┐ ┌──────────┐ ┌──────────────┐
│Python SDK│ │ CLI │ │ WebApp   │ │Claude Desktop│
│(研究者PC)│ │     │ │(Streamlit│ │/ Claude Code │
└────┬─────┘ └──┬──┘ │ブラウザ)  │ └──────┬───────┘
     │          │    └────┬─────┘        │
     │直接      │直接     │REST          │MCP
     ▼          ▼        ▼              ▼
┌──────────────────────────────────────────────┐
│             GCP (asia-northeast1)             │
│                                              │
│  ┌──────────────────────────────────────┐    │
│  │  Cloud Run — 統合サーバー (Python)    │    │
│  │  ├── MCPサーバー (FastMCP)           │    │
│  │  ├── REST API (FastAPI) ← WebApp用   │    │
│  │  └── Streamlit WebApp                │    │
│  └──────────────────────────────────────┘    │
│                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │Firestore │ │Vertex AI │ │Cloud Functions│ │
│  │メタデータ │ │Embedding │ │Embedding生成 │ │
│  │+Vector   │ │+Gemini   │ │Nextcloudポーラ│ │
│  │+セルログ  │ │          │ │              │ │
│  └──────────┘ └──────────┘ └──────────────┘ │
└──────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────┐
│  Nextcloud (arim.mdx.jp) — 30TB無料          │
└──────────────────────────────────────────────┘
```

**Phase 2で追加:**

| # | サービス | 役割 | 追加コスト |
|---|---------|------|----------|
| 6 | Cloud Run | MCPサーバー + REST API + Streamlit | $0-5/月 |
| 7 | Cloud Scheduler | Nextcloudポーラー（5分間隔） | $0/月 |
| 8 | Vertex AI Gemini | LLMチャット（WebApp用） | $0-5/月 |

**合計: 月$0-15**

#### Phase 3（拡張）: 必要になってから

| 追加候補 | トリガー | 追加コスト |
|---------|---------|----------|
| BigQuery | 集約分析が頻繁になったとき | +$1-5/月 |
| Firebase Auth | 外部ユーザーがWebAppを使うとき | +$0/月（50MAUまで無料） |
| Cloud Armor | セキュリティ要件が上がったとき | +$5-10/月 |

### 2.2 Firestoreコレクション設計（セルログ対応）

```
firestore/
├── teams/
│   └── {team_id}/                          # "konishi-lab"
│       ├── team_name: string
│       ├── members: map<uid, role>
│       ├── created_at: timestamp
│       │
│       └── records/ (サブコレクション)
│           └── {record_id}/                # "AB3F"
│               ├── title: string
│               ├── type: string            # "experiment"
│               ├── status: string          # "success"
│               ├── tags: array<string>
│               ├── conditions: map         # 実験条件（自由スキーマ）
│               ├── results: map            # 実験結果（自由スキーマ）
│               ├── notes: array<map>       # [{text, by, at}]
│               ├── created_by: string
│               ├── created_at: timestamp
│               ├── updated_at: timestamp
│               ├── parent_id: string|null  # 親レコードID
│               ├── visibility: string      # "team" | "private"
│               ├── template_used: string|null
│               ├── deleted_at: timestamp|null  # ソフトデリート
│               │
│               ├── embedding: vector(768)  # Vertex AI embedding
│               ├── embedding_text: string  # embedding生成元テキスト
│               │
│               ├── file_refs: array<map>   # [{name, path, size, type}]
│               ├── nextcloud_path: string  # Nextcloud上のディレクトリパス
│               │
│               ├── trace_summary: string   # L1サマリー（自動生成）
│               │
│               ├── traces/ (サブコレクション)
│               │   └── {trace_id}/
│               │       ├── type: string            # "track" | "snapshot"
│               │       ├── timestamp: timestamp
│               │       ├── function: string|null    # track型: 関数名
│               │       ├── file: string
│               │       ├── line: number
│               │       ├── args: map|null           # track型: 引数
│               │       ├── return_value: map|null   # track型: 返り値
│               │       ├── call_tree: map|null      # track型: ネスト呼出
│               │       ├── variables: map|null      # snapshot型: 変数
│               │       ├── duration_sec: number
│               │       ├── env: map
│               │       └── summary: string          # L1サマリー
│               │
│               └── cell_logs/ (サブコレクション)  ★IPython hooks用
│                   └── {cell_log_id}/
│                       ├── cell_number: number
│                       ├── source: string          # セルのソースコード
│                       ├── execution_count: number # IPythonの実行カウント
│                       ├── timestamp: timestamp
│                       ├── duration_sec: number
│                       ├── new_vars: map           # 新規作成された変数
│                       ├── changed_vars: map       # 変更された変数
│                       ├── error: string|null      # エラーが出た場合
│                       ├── output_summary: string|null  # 出力の要約
│                       └── imports: array<string>  # このセルのimport文
```

### 2.3 セルログの格納戦略

**なぜ `traces/` とは別に `cell_logs/` を設けるか:**

| 観点 | `traces/`（@exp.track） | `cell_logs/`（IPython hooks） |
|------|------------------------|------------------------------|
| 粒度 | 関数単位（構造化された呼び出しツリー） | セル単位（ベタ書きコードの断片） |
| データ形状 | ツリー構造（children配列） | フラットなリスト（時系列） |
| 1レコードあたり件数 | ~10件 | ~50-200件（Notebook全セル） |
| サイズ | 各1-10KB | 各0.5-5KB（ソースコード含む） |
| 用途 | パイプライン解析、パラメータ比較 | 「Notebookで何をしたか」の再現 |

`traces/` はv6設計通り。`cell_logs/` はIPython hooks自動記録専用のサブコレクションとして新設する。

**サイズ制約の対策:**
- Firestoreの1ドキュメント上限は1MB
- `source` フィールドが長い場合（巨大なセル）は最初の5000文字で切り捨て
- `new_vars` / `changed_vars` の各値は `_summarize()` で要約（ndarrayはshape/dtype/sizeのみ）
- 1レコードあたりのセルログが200件を超えた場合、古いものから `source` を削除してサマリーのみ保持

### 2.4 コスト最終見積もり

**前提: チーム5-20人、月間500レコード登録、各レコード平均30セルログ**

| 項目 | 読み取り/月 | 書き込み/月 | コスト |
|------|-----------|-----------|-------|
| レコード本体 | 50,000 | 500 | $0.03 + $0.009 |
| セルログ | 30,000 | 15,000 | $0.02 + $0.27 |
| traces | 10,000 | 2,000 | $0.006 + $0.036 |
| embedding生成 | - | 500回 | ~$0.01 |
| Vector Search | 5,000 | - | $0.003 |
| **合計** | | | **$0.37/月** |

Firestoreの無料枠（50K読み取り/日、20K書き込み/日）でほぼ賄える。
最悪ケースでも月$5以内。

---

## 3. セルログデータのLLM活用設計

### 3.1 IPython hooksで記録されるデータの構造

```python
# SDKが自動記録するセルログの例
{
    "cell_number": 3,
    "execution_count": 5,
    "timestamp": "2026-03-16T14:30:00",
    "source": "from scipy.signal import butter, filtfilt\nb, a = butter(4, cutoff, btype='low')\nfiltered = filtfilt(b, a, data[:, 1])",
    "duration_sec": 0.05,
    "new_vars": {
        "b": "<ndarray shape=(5,) dtype=float64>",
        "a": "<ndarray shape=(5,) dtype=float64>",
        "filtered": "<ndarray shape=(5000,) dtype=float64>"
    },
    "changed_vars": {},
    "error": null,
    "output_summary": null,
    "imports": ["scipy.signal.butter", "scipy.signal.filtfilt"]
}
```

### 3.2 Firestoreでのセルログ保存フロー

```
Notebook実行中:
  セル実行
    ↓ IPython post_run_cell hook
  SDKがdiff検出（new_vars, changed_vars）
    ↓
  ローカルバッファに保存（SQLite or JSONファイル）
    ↓ 非同期バッチ（5秒 or 10セルごと）
  Firestoreに書き込み
    teams/{team}/records/{id}/cell_logs/{cell_log_id}
    ↓ Cloud Functions onCreateトリガー
  全セルログが揃った時点でNotebookサマリーを生成
    ↓
  Record本体の embedding_text にサマリーを追記
    ↓
  Vertex AI Embeddingで再生成
```

**ローカルバッファの重要性:**
- REQUIREMENTS #8で「ローカルバッファ必須」と明記されている
- セルログはNotebook実行中にリアルタイムで溜まるため、ネットワーク遅延を挟めない
- ローカルバッファ（`~/.mdxdb/buffer/`）にまず保存し、バックグラウンドでFirestoreに送る
- オフライン時はバッファに蓄積、オンライン復帰時に自動同期

### 3.3 セルログのEmbedding戦略

**判断: セルごとにembeddingは作らない。Notebookサマリーを生成してRecord本体のembeddingに統合する。**

理由:
- 個々のセルは断片的すぎてembeddingの意味が薄い（`cutoff = 0.5` だけのセルなど）
- セルログ50件 x 768次元 = 巨大なベクトルストレージはコスト非効率
- Notebook全体の「何をしたか」がわかるサマリー1本のembeddingのほうが検索精度が高い

**Notebookサマリーの自動生成:**

```python
def generate_notebook_summary(cell_logs: list[dict]) -> str:
    """セルログからNotebookサマリーを生成する。

    Cloud Functions内で実行。Gemini 2.0 Flashを使用。
    """
    # セルログを時系列で結合
    cells_text = "\n---\n".join([
        f"Cell {c['cell_number']}: {c['source'][:500]}\n"
        f"新規変数: {list(c['new_vars'].keys())}"
        for c in cell_logs
    ])

    prompt = f"""以下のJupyter Notebookのセル実行履歴から、
このNotebookで行われた処理を100文字以内で要約してください。
使用した手法名、主要パラメータ、最終結果を含めてください。

{cells_text}"""

    # Gemini 2.0 Flashで要約
    summary = gemini_flash.generate(prompt)
    return summary
    # 例: "XRDデータにButterworthフィルタ(cutoff=0.3)を適用し、
    #      ピーク検出(threshold=100)で12本同定。格子定数a=2.873A算出。"
```

**embedding対象テキストの構成（v6から拡張）:**

```python
def build_embedding_text(record, traces, cell_logs_summary):
    parts = []

    # 高重要度: タイトル（2回繰り返し）
    parts.append(record.title)
    parts.append(record.title)

    # 高重要度: タグ
    parts.append(" ".join(record.tags))

    # 高重要度: 結果サマリー
    for key, value in record.results.items():
        parts.append(f"{key}: {value}")

    # 中重要度: 条件
    for key, value in record.conditions.items():
        parts.append(f"{key}={value}")

    # 中重要度: ノート
    for note in record.notes[-3:]:
        parts.append(note["text"])

    # 中重要度: トレースL1サマリー（@exp.track使用時）
    for trace in traces[:3]:
        parts.append(trace["summary"])

    # ★新規: Notebookサマリー（IPython hooks使用時）
    if cell_logs_summary:
        parts.append(cell_logs_summary)

    # 低重要度: 使用ライブラリ（セルログのimportsから抽出）
    imports = set()
    for log in cell_logs[:50]:
        imports.update(log.get("imports", []))
    if imports:
        parts.append("使用ライブラリ: " + " ".join(sorted(imports)))

    return " ".join(parts)
```

### 3.4 MCPツールでセルログを返す際のフォーマット

#### (a) 検索結果での表示（L1レベル）

```json
{
    "id": "AB3F",
    "title": "Fe-10Cr XRD解析",
    "notebook_summary": "XRDデータにButterworthフィルタ(cutoff=0.3)を適用、ピーク12本検出、格子定数a=2.873A算出",
    "cell_count": 12,
    "total_duration_sec": 45.3
}
```

#### (b) レコード詳細での表示（L2レベル）

```json
{
    "id": "AB3F",
    "notebook_log": {
        "summary": "XRDデータにButterworthフィルタ(cutoff=0.3)を適用...",
        "cell_count": 12,
        "total_duration_sec": 45.3,
        "key_cells": [
            {
                "cell_number": 2,
                "description": "データ読み込み",
                "new_vars": ["data", "cutoff"],
                "imports": ["numpy"]
            },
            {
                "cell_number": 3,
                "description": "Butterworthフィルタ適用",
                "new_vars": ["b", "a", "filtered"],
                "imports": ["scipy.signal"]
            },
            {
                "cell_number": 5,
                "description": "ピーク検出",
                "new_vars": ["peaks", "n_peaks"],
                "key_values": {"n_peaks": 12}
            }
        ],
        "final_variables": {
            "lattice_a": 2.873,
            "n_peaks": 12,
            "filtered": "<ndarray shape=(5000,) dtype=float64>"
        }
    }
}
```

#### (c) 全セルログ取得（L3レベル）

```json
{
    "id": "AB3F",
    "notebook_log": {
        "cells": [
            {
                "cell_number": 1,
                "source": "from mdxdb import Lab\nexp = Lab('konishi-lab').new('XRD解析')",
                "duration_sec": 0.5,
                "new_vars": {"exp": "<Record AB3F>"},
                "changed_vars": {}
            },
            {
                "cell_number": 2,
                "source": "import numpy as np\ndata = np.loadtxt('xrd_data.csv', delimiter=',')\ncutoff = 0.5",
                "duration_sec": 0.12,
                "new_vars": {
                    "data": "<ndarray shape=(5000,2) dtype=float64>",
                    "cutoff": 0.5
                },
                "changed_vars": {}
            }
        ]
    }
}
```

### 3.5 「このNotebookで何をしたか」をLLMが要約するフロー

```
ユーザー: 「AB3Fの実験ではどんな処理をした？」

LLM → MCP get_detail(id="AB3F", include_notebook_log=true, log_level="L2")

MCP → LLM:
  notebook_summary + key_cells + final_variables

LLM → ユーザー:
  「AB3Fでは以下の処理を行っています:
   1. XRDデータ(5000点×2列)を読み込み
   2. Butterworthフィルタ(4次, cutoff=0.5)でローパスフィルタリング
   3. 閾値100でピーク検出 → 12本のピークを同定
   4. 格子定数を算出: a = 2.873 Å
   使用ライブラリ: numpy, scipy.signal」
```

**L2で不十分な場合（詳細調査）:**

```
ユーザー: 「cutoffの値をどこで変更した？」

LLM → MCP get_notebook_log(id="AB3F", level="L3")

MCP → LLM:
  全セルのsource + new_vars + changed_vars

LLM → ユーザー:
  「セル2でcutoff=0.5として初期設定した後、
   セル7でcutoff=0.3に変更しています（changed_varsに記録あり）。
   最終的にフィルタに適用されたのはcutoff=0.3です。」
```

---

## 4. MCPサーバー最終ツール一覧

### 4.1 ツール再整理（v6の10ツール → v7の11ツール）

v6の `get_trace` をセルログ対応で拡張し、`get_notebook_log` を追加。`get_trace` も残す（@exp.track用）。

| # | ツール名 | 概要 | v6からの変更 |
|---|---------|------|-------------|
| 1 | `search` | ハイブリッド検索（構造化+ベクトル） | notebook_summary をレスポンスに追加 |
| 2 | `get_detail` | レコード詳細 | notebook_log セクション追加 |
| 3 | `compare` | 複数レコードの条件・結果比較 | 変更なし |
| 4 | `data_preview` | ファイルの統計サマリー | 変更なし |
| 5 | `get_results` | 構造化結果の横断検索 | 変更なし |
| 6 | `aggregate` | 数値集約 | 変更なし |
| 7 | `get_timeline` | サンプルの実験履歴 | 変更なし |
| 8 | `get_trace` | @exp.trackの実行トレース取得 | 変更なし（関数トレース専用） |
| 9 | `explain_result` | 結果の算出過程を説明 | セルログも参照するよう拡張 |
| 10 | `compare_runs` | 同一関数の異なるパラメータ実行比較 | 変更なし |
| 11 | **`get_notebook_log`** | **Notebookのセル実行履歴取得** | **v7新規** |

### 4.2 `get_notebook_log` 詳細仕様

```json
// リクエスト
{
    "tool": "get_notebook_log",
    "params": {
        "record_id": "AB3F",
        "level": "L2",
        "cell_range": null,
        "filter_imports": null
    }
}
```

**パラメータ:**

| パラメータ | 型 | 説明 |
|-----------|-----|------|
| `record_id` | string | 必須。レコードID |
| `level` | "L1"\|"L2"\|"L3" | 詳細度。L1=サマリーのみ、L2=主要セル、L3=全セル |
| `cell_range` | [int, int]\|null | セル番号の範囲指定。L3時に特定セルだけ取得 |
| `filter_imports` | string[]\|null | 特定ライブラリを使ったセルだけ取得 |

**レスポンス（L2）:**

```json
{
    "record_id": "AB3F",
    "notebook_summary": "XRDデータにButterworthフィルタ(cutoff=0.3)を適用...",
    "cell_count": 12,
    "execution_time_total_sec": 45.3,
    "libraries_used": ["numpy", "scipy.signal", "matplotlib"],
    "key_cells": [
        {
            "cell_number": 2,
            "source_preview": "data = np.loadtxt('xrd_data.csv', ...)",
            "new_vars": {"data": "<ndarray (5000,2)>", "cutoff": 0.5},
            "duration_sec": 0.12
        },
        {
            "cell_number": 3,
            "source_preview": "b, a = butter(4, cutoff, ...)\nfiltered = filtfilt(b, a, ...)",
            "new_vars": {"filtered": "<ndarray (5000,)>"},
            "duration_sec": 0.05
        },
        {
            "cell_number": 7,
            "source_preview": "cutoff = 0.3  # 変更",
            "changed_vars": {"cutoff": {"before": 0.5, "after": 0.3}},
            "duration_sec": 0.001
        }
    ],
    "final_namespace": {
        "lattice_a": 2.873,
        "n_peaks": 12,
        "cutoff": 0.3,
        "data": "<ndarray (5000,2)>",
        "filtered": "<ndarray (5000,)>"
    }
}
```

### 4.3 `get_trace` と `get_notebook_log` の使い分け

| 質問の種類 | 使うツール | 理由 |
|-----------|----------|------|
| 「このNotebookで何をした？」 | `get_notebook_log` | セル単位の履歴が必要 |
| 「この関数はどうやって結果を出した？」 | `get_trace` | 関数の呼び出しツリーが必要 |
| 「cutoffの値はいくつ？」 | `get_notebook_log` | 変数の変更履歴が必要 |
| 「処理パイプラインの構造は？」 | `get_trace` | ネスト構造が必要 |
| 「田中さんと鈴木さんの処理の違いは？」 | 両方 | 下記フロー参照 |

### 4.4 「田中さんと鈴木さんのNotebookの処理の違いを比較して」のフロー

```
ユーザー: 「田中さん(AB3F)と鈴木さん(XY7P)のNotebookの処理の違いを比較して」

Step 1: 両方のNotebookサマリーを取得
  LLM → MCP get_notebook_log(record_id="AB3F", level="L2")
  LLM → MCP get_notebook_log(record_id="XY7P", level="L2")

Step 2 (必要に応じて): @exp.trackのトレースも比較
  LLM → MCP compare_runs(record_ids=["AB3F","XY7P"], function_name="full_analysis")

Step 3: LLMが統合的に回答

LLM → ユーザー:
  「田中さんと鈴木さんのNotebookを比較しました:

   ■ 共通点:
   - どちらもXRDデータの読み込み→フィルタリング→ピーク検出→格子定数算出
   - 使用ライブラリ: numpy, scipy.signal

   ■ 相違点:

   | 処理 | 田中さん(AB3F) | 鈴木さん(XY7P) |
   |------|---------------|---------------|
   | フィルタ cutoff | 0.3 | 0.5 |
   | BG除去 poly_order | 3 | 5 |
   | ピーク閾値 | 100 | 80 |
   | 結果: n_peaks | 12 | 14 |
   | 結果: lattice_a | 2.873 | 2.881 |

   ■ 注目点:
   - 田中さんはセル7でcutoffを0.5→0.3に変更しています
   - 鈴木さんはピーク閾値を低く設定(80)しており、2本多くピークを検出
   - パラメータの違いが結果差の一因です」
```

---

## 5. WebApp設計の最終判断

### 5.1 最終判断: Streamlit

**判断: Streamlitを採用。Next.jsは採用しない。**

| 判断基準 | Next.js | Streamlit | **判断** |
|---------|---------|-----------|---------|
| 開発言語 | TypeScript + Python | Pythonのみ | **Streamlit勝ち。言語統一** |
| 開発速度 | 1画面1週間 | 1画面1日 | **Streamlit勝ち** |
| デプロイ | Firebase Hosting + Cloud Run | Cloud Run 1つ | **Streamlit勝ち** |
| UI品質 | 高い（shadcn/ui） | 中 | Next.js勝ち |
| 保守コスト | 高い（半年ごとの破壊的変更） | 低い | **Streamlit勝ち** |
| TypeScript人材 | チームにいない可能性 | Python人材で十分 | **Streamlit勝ち** |
| Notebook再生 | カスタム実装が必要 | `st.code()` で十分 | **同等** |

**Next.jsが勝つのはUI品質のみ。** 研究室の内部ツールにshadcn/uiの美しいUIは不要。データが見やすく、操作が直感的であれば十分。

### 5.2 Streamlit画面設計

**4画面構成（MVP）:**

#### 画面1: ダッシュボード

```
┌─────────────────────────────────────────────┐
│  konishi-lab ダッシュボード                    │
├─────────────────────────────────────────────┤
│                                             │
│  最近の実験 (30日)                            │
│  ┌─────┬──────────────────┬──────┬───────┐  │
│  │ ID  │ タイトル          │ 作成者│ 状態  │  │
│  ├─────┼──────────────────┼──────┼───────┤  │
│  │AB3F │ Fe-10Cr XRD解析  │田中  │成功   │  │
│  │XY7P │ Fe-15Cr XRD解析  │鈴木  │成功   │  │
│  │KM2R │ Fe-10Cr 700度焼鈍│佐藤  │進行中 │  │
│  └─────┴──────────────────┴──────┴───────┘  │
│                                             │
│  チーム統計: 実験 142件 / メンバー 8人        │
│  今月: +23件 / 先月比 +15%                   │
└─────────────────────────────────────────────┘
```

#### 画面2: レコード詳細 + Notebookログビューア

```
┌─────────────────────────────────────────────┐
│  AB3F: Fe-10Cr XRD解析                       │
├─────────────────────────────────────────────┤
│ [条件] [結果] [ファイル] [Notebookログ] [子レコード] │
│                                             │
│  ── Notebookログ ──                          │
│                                             │
│  サマリー: Butterworthフィルタ(cutoff=0.3)で  │
│  前処理、ピーク12本検出、格子定数a=2.873A算出  │
│                                             │
│  Cell 1 [0.5s]                              │
│  ┌─────────────────────────────────────┐    │
│  │ from mdxdb import Lab               │    │
│  │ exp = Lab('konishi-lab').new('XRD')  │    │
│  └─────────────────────────────────────┘    │
│  → 新規: exp                                │
│                                             │
│  Cell 2 [0.12s]                             │
│  ┌─────────────────────────────────────┐    │
│  │ import numpy as np                   │    │
│  │ data = np.loadtxt('xrd.csv', ...)    │    │
│  │ cutoff = 0.5                         │    │
│  └─────────────────────────────────────┘    │
│  → 新規: data <ndarray (5000,2)>, cutoff=0.5│
│                                             │
│  Cell 7 [0.001s]                            │
│  ┌─────────────────────────────────────┐    │
│  │ cutoff = 0.3  # パラメータ変更       │    │
│  └─────────────────────────────────────┘    │
│  → 変更: cutoff 0.5→0.3                     │
└─────────────────────────────────────────────┘
```

これがRead-only Notebook viewerの実装。Streamlitの `st.code()` でセルのソースコードを表示し、`st.expander()` で変数の変更を折りたたみ表示する。

#### 画面3: 検索

```
┌─────────────────────────────────────────────┐
│  検索                                        │
├─────────────────────────────────────────────┤
│  [Fe-Cr合金の焼鈍でBCC構造__________] [検索]  │
│                                             │
│  フィルタ:                                   │
│  タグ: [Fe-Cr] [XRD]  状態: [成功]           │
│  期間: [2025-01 ～ 2026-03]                  │
│                                             │
│  結果 23件:                                  │
│  ┌─────┬──────────────────┬─────────────┐   │
│  │AB3F │ Fe-10Cr 500度焼鈍│cutoff=0.3   │   │
│  │XY7P │ Fe-15Cr 600度焼鈍│cutoff=0.5   │   │
│  │KM2R │ Fe-10Cr 700度焼鈍│cutoff=0.4   │   │
│  └─────┴──────────────────┴─────────────┘   │
└─────────────────────────────────────────────┘
```

#### 画面4: LLMチャット

```
┌─────────────────────────────────────────────┐
│  LLMアシスタント                              │
├─────────────────────────────────────────────┤
│                                             │
│  [ユーザー] Fe-Cr合金で最適な焼鈍温度は？      │
│                                             │
│  [LLM] 過去23件のデータを分析しました。       │
│  温度ごとの結晶子サイズ:                      │
│  - 400度: 28.5nm                            │
│  - 500度: 43.1nm                            │
│  - 600度: 56.2nm                            │
│  - 700度: 67.8nm ← 最大                     │
│  - 800度: 45.2nm（酸化層形成）               │
│                                             │
│  最適焼鈍温度は700度付近と推定されます。       │
│                                             │
│  [質問を入力...____________________] [送信]   │
└─────────────────────────────────────────────┘
```

### 5.3 Streamlit + FastAPI の同居構成

```python
# Cloud Run上のエントリーポイント
# Dockerfile内で supervisord を使い、2プロセスを起動

# プロセス1: Streamlit (port 8501)
# プロセス2: FastAPI (port 8000) ← MCP Server + REST API

# Cloud Runのポートは8080。nginx or traefikでルーティング:
# /api/* → FastAPI (8000)
# /mcp/* → FastAPI (8000)
# /*     → Streamlit (8501)
```

もしくはより簡素に:

```python
# FastAPI内にStreamlitをマウント（streamlit-server-state使用）
# または単純にCloud Runサービスを2つに分ける:
# - cloudrun-webapp: Streamlit
# - cloudrun-api: FastAPI (MCP + REST)
```

**推奨: Cloud Runサービス2つに分離。** 理由: Streamlitとfastapi-mcpはプロセスモデルが異なるため、同居はトラブルの元。分離してもCloud Runのコストは最小インスタンス0なら追加コストは実質ゼロ。

---

## 6. Nextcloud連携の最終設計

### 6.1 データフローの全体像

#### 経路A: SDK → ローカルバッファ → Nextcloud + Firestore

```
実験者のPC (Notebook/Script)
    │
    ▼
SDK exp.add("data.npy", array)
    │
    ├── ① ローカルバッファに保存
    │   ~/.mdxdb/buffer/{record_id}/data.npy
    │   ~/.mdxdb/buffer/{record_id}/_meta.json
    │
    ├── ② Nextcloudにアップロード（非同期）
    │   WebDAV PUT → large/{group_folder}/v1/{db_name}/{record_id}/data.npy
    │   成功したらバッファから削除
    │
    └── ③ Firestoreにメタデータ書き込み
        teams/{team}/records/{record_id}/file_refs に追加
        {name: "data.npy", path: "nextcloud://...", size: 12345}
```

**セルログの場合:**

```
Notebook実行中（IPython hooks）
    │
    ├── ① ローカルバッファに蓄積
    │   ~/.mdxdb/buffer/{record_id}/cell_logs/cell_001.json
    │   ~/.mdxdb/buffer/{record_id}/cell_logs/cell_002.json
    │   ...
    │
    └── ② Firestoreにバッチ書き込み（5秒 or 10セルごと）
        teams/{team}/records/{record_id}/cell_logs/{id}
        ※ セルログのソースコードはFirestoreのみ（Nextcloudには保存しない）
```

**セルログをNextcloudに保存しない理由:**
- セルログは構造化データ（JSON）であり、Firestoreに直接格納するのが自然
- Nextcloudはバイナリファイルのストレージであり、細かいJSONの出し入れは非効率
- セルログの検索・集約はFirestore側で行うため、Nextcloudに置く意味がない

#### 経路B: Nextcloudブラウザ投入 → Firestore自動インデックス

```
装置PC (Pythonなし)
    │
    ▼
Nextcloudブラウザでファイルをドラッグ&ドロップ
    large/{group_folder}/v1/{db_name}/{record_id}/_data/measurement.ras
    │
    ▼ Cloud Functions (Nextcloudポーラー、5分間隔)
    │
    ├── Nextcloud WebDAV PROPFIND で変更を検出
    ├── 新規ファイルを発見
    │
    └── Firestoreに自動登録
        teams/{team}/records/{record_id}/file_refs に追加
        {name: "measurement.ras", path: "nextcloud://...", size: 245000,
         source: "nextcloud_browser"}
```

**ポーラーの設計:**

```python
# Cloud Functions (Gen2) + Cloud Scheduler (5分間隔)

def nextcloud_poller(request):
    """Nextcloudの変更を検出してFirestoreを更新する。"""

    # 1. 前回チェック時刻を取得（Firestoreに保存）
    last_check = get_last_check_time()

    # 2. Nextcloud WebDAV PROPFIND で変更ファイル一覧を取得
    changed_files = nc_client.find_modified_since(last_check)

    # 3. 各ファイルについて
    for file in changed_files:
        record_id = extract_record_id_from_path(file.path)
        if record_id:
            # Firestoreのfile_refsに追加（存在しなければ）
            add_file_ref_if_not_exists(record_id, file)

    # 4. チェック時刻を更新
    update_last_check_time()
```

#### 経路C: WebApp投入 → Nextcloud + Firestore

```
ブラウザ (Streamlit WebApp)
    │
    ▼
アップロード画面: ID入力 + ファイルドロップ
    │
    ├── ① REST API (Cloud Run FastAPI) にPOST
    │   POST /api/v1/records/{record_id}/files
    │   Body: multipart/form-data
    │
    ├── ② API Server → Nextcloud WebDAVにアップロード
    │   large/{group_folder}/v1/{db_name}/{record_id}/_data/file.ras
    │
    └── ③ API Server → Firestoreにメタデータ書き込み
        teams/{team}/records/{record_id}/file_refs に追加
```

### 6.2 Nextcloud上のディレクトリ構造（v1からの変更なし）

```
large/{group_folder}/v{major}/{db_name}/
├── _db_meta.json
├── schemas/{schema_name}.json
└── {record_id}/
    ├── _record_meta.json      ← Firestore同期用（Nextcloud単体でも読める）
    ├── _data/
    │   ├── xrd_raw.ras
    │   ├── xrd_processed.csv
    │   └── analysis.py
    └── {sub_record_id}/
        ├── _record_meta.json
        └── _data/
            └── sem_image.tif
```

**Nextcloud上の `_record_meta.json` とFirestoreの関係:**
- FirestoreがSingle Source of Truth（真実の唯一の源）
- `_record_meta.json` はFirestoreからの「エクスポート」であり、Nextcloud単体閲覧時の参照用
- SDK/CLIの `exp.save()` / `exp.close()` 時にFirestoreの内容を `_record_meta.json` に書き出す

---

## 7. リポジトリ構成の最終版

### 7.1 2リポジトリ構成

```
kpro-arim-mdxdb/          ← SDK（このリポジトリ）
kpro-arim-platform/       ← プラットフォーム（モノレポ）
```

### 7.2 kpro-arim-mdxdb（SDK）

```
kpro-arim-mdxdb/
├── src/mdxdb/
│   ├── __init__.py               # Lab, Record をre-export
│   ├── _version.py
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── lab.py                # Lab クラス（エントリーポイント）
│   │   ├── record.py             # Record クラス
│   │   ├── types.py              # Status, RecordType, Note等
│   │   ├── id.py                 # Crockford's Base32 ID
│   │   ├── config.py             # Settings (pydantic-settings)
│   │   └── exceptions.py         # カスタム例外
│   │
│   ├── tracking/
│   │   ├── __init__.py
│   │   ├── tracker.py            # @exp.track デコレータ
│   │   ├── notebook.py           # ★ IPython hooks自動セルログ
│   │   ├── snapshot.py           # exp.snapshot()
│   │   ├── serializers.py        # 変数のシリアライズ
│   │   └── context.py            # contextvars コールスタック管理
│   │
│   ├── backends/
│   │   ├── __init__.py
│   │   ├── base.py               # MetadataBackend Protocol
│   │   ├── memory.py             # InMemoryBackend（テスト用）
│   │   └── firestore.py          # FirestoreBackend
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── base.py               # StorageBackend Protocol
│   │   ├── memory.py             # InMemoryStorage
│   │   ├── local.py              # LocalFileStorage（バッファ）
│   │   └── nextcloud.py          # NextcloudStorage
│   │
│   ├── search/
│   │   ├── __init__.py
│   │   ├── base.py               # SearchBackend Protocol
│   │   ├── memory.py             # InMemorySearch
│   │   └── firestore_vector.py   # Firestore Vector Search
│   │
│   ├── buffer/
│   │   ├── __init__.py
│   │   └── local_buffer.py       # ★ ローカルバッファ管理
│   │
│   ├── cli/
│   │   ├── __init__.py
│   │   └── main.py               # click CLI
│   │
│   └── compat/
│       ├── __init__.py
│       └── v1.py                 # 現行MdxDbからの移行ヘルパー
│
├── tests/
│   ├── conftest.py
│   ├── test_lab.py
│   ├── test_record.py
│   ├── test_tracking.py
│   ├── test_notebook_hooks.py    # ★ IPython hooksのテスト
│   ├── test_buffer.py
│   ├── test_serializers.py
│   └── test_firestore.py         # 要Nextcloud接続
│
├── pyproject.toml
├── CLAUDE.md
└── README.md
```

### 7.3 kpro-arim-platform（プラットフォーム）

```
kpro-arim-platform/
├── packages/
│   ├── mcp-server/               # MCPサーバー (FastMCP + FastAPI)
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── server.py         # FastMCPサーバー定義
│   │   │   ├── tools/
│   │   │   │   ├── search.py
│   │   │   │   ├── get_detail.py
│   │   │   │   ├── compare.py
│   │   │   │   ├── data_preview.py
│   │   │   │   ├── get_results.py
│   │   │   │   ├── aggregate.py
│   │   │   │   ├── get_timeline.py
│   │   │   │   ├── get_trace.py
│   │   │   │   ├── explain_result.py
│   │   │   │   ├── compare_runs.py
│   │   │   │   └── get_notebook_log.py  # ★ v7新規
│   │   │   └── api/              # REST API (WebApp用)
│   │   │       ├── routes.py
│   │   │       └── auth.py
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   ├── webapp/                   # Streamlit WebApp
│   │   ├── app.py                # メインエントリーポイント
│   │   ├── pages/
│   │   │   ├── 1_dashboard.py
│   │   │   ├── 2_record_detail.py
│   │   │   ├── 3_search.py
│   │   │   └── 4_chat.py
│   │   ├── components/
│   │   │   ├── notebook_viewer.py  # ★ セルログビューア
│   │   │   ├── record_table.py
│   │   │   └── chat_interface.py
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   └── functions/                # Cloud Functions
│       ├── embedding_trigger/
│       │   └── main.py           # Firestore onCreate → Embedding生成
│       ├── nextcloud_poller/
│       │   └── main.py           # 5分間隔Nextcloud変更検出
│       └── notebook_summarizer/
│           └── main.py           # ★ セルログ→Notebookサマリー生成
│
├── infra/
│   ├── setup.sh                  # gcloud CLIでの初期セットアップスクリプト
│   ├── deploy.sh                 # デプロイスクリプト
│   └── firestore.rules           # Firestoreセキュリティルール
│
├── shared/
│   └── types.py                  # SDK・MCP・WebApp間の共有型定義
│
├── pyproject.toml                # ルートプロジェクト（開発ツール設定）
└── README.md
```

**v5との主な違い:**
- `webapp/` が Next.js → Streamlit（Pythonのみ）
- `infra/terraform/` → `infra/setup.sh`（gcloud CLIスクリプトに簡素化）
- `shared/types/` が TypeScript → Python
- `package.json`（turborepo/nx）不要。Pythonのワークスペース管理は `pyproject.toml` で完結

---

## 8. 実装ロードマップ最終版

### 8.1 Phase概要

| Phase | 期間 | 目標 | コンポーネント数 |
|-------|------|------|----------------|
| **0** | Week 1 | SDK骨格 + InMemoryBackend | 1 |
| **1a** | Week 2-3 | SDK Core + IPython hooks + ローカルバッファ | 2 |
| **1b** | Week 4-5 | Firestore + Nextcloud統合 | 4 |
| **1c** | Week 6 | Embedding + Vector Search | 5 |
| **Alpha** | Week 7 | **チーム内利用開始** | 5 |
| **2a** | Week 8-9 | MCPサーバー | 6 |
| **2b** | Week 10-12 | Streamlit WebApp | 8 |
| **3** | Month 4+ | BigQuery, 高度な機能 | 9+ |

### 8.2 Issue粒度のタスクリスト

#### Phase 0: SDK骨格（Week 1）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| P0-1 | pyproject.toml作成、パッケージ構造、CI設定 | 0.5日 | なし |
| P0-2 | `core/types.py` — Status, RecordType, Note等の型定義 | 0.5日 | P0-1 |
| P0-3 | `core/id.py` — Crockford's Base32 IDジェネレーター | 0.5日 | P0-1 |
| P0-4 | `core/exceptions.py` — カスタム例外定義 | 0.25日 | P0-1 |
| P0-5 | `backends/base.py` — MetadataBackend Protocol定義 | 0.5日 | P0-2 |
| P0-6 | `storage/base.py` — StorageBackend Protocol定義 | 0.25日 | P0-1 |
| P0-7 | `backends/memory.py` — InMemoryBackend実装 | 1日 | P0-5 |
| P0-8 | `storage/memory.py` — InMemoryStorage実装 | 0.5日 | P0-6 |
| P0-9 | `core/record.py` — Record クラス基本実装 | 1日 | P0-5,P0-6 |
| P0-10 | `core/lab.py` — Lab クラス基本実装 | 1日 | P0-9 |
| P0-11 | テスト: Lab + Record + InMemory の基本操作 | 1日 | P0-10 |

**Week 1完了時点:** `pip install -e .` して `lab = Lab("test"); exp = lab.new("test")` が動く。

#### Phase 1a: IPython hooks + ローカルバッファ（Week 2-3）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| P1a-1 | `tracking/serializers.py` — 変数シリアライズ（ndarray要約等） | 1日 | P0-11 |
| P1a-2 | `tracking/context.py` — contextvarsコールスタック管理 | 0.5日 | P0-11 |
| P1a-3 | `tracking/tracker.py` — @exp.track デコレータ実装 | 2日 | P1a-1,P1a-2 |
| P1a-4 | `tracking/snapshot.py` — exp.snapshot() 実装 | 1日 | P1a-1 |
| P1a-5 | **`tracking/notebook.py` — IPython hooks自動セルログ** | 2日 | P1a-1 |
| P1a-6 | `buffer/local_buffer.py` — ローカルバッファ管理（SQLite or JSON） | 2日 | P0-11 |
| P1a-7 | テスト: @exp.track のユニットテスト | 1日 | P1a-3 |
| P1a-8 | テスト: IPython hooks のユニットテスト（IPython mock） | 1日 | P1a-5 |
| P1a-9 | テスト: ローカルバッファの耐障害性テスト | 0.5日 | P1a-6 |
| P1a-10 | `core/record.py` にtracking統合（add, save, close時のフック） | 1日 | P1a-3,P1a-5 |

**Week 3完了時点:** Notebookで `exp = Lab("test").new("XRD")` するだけで全セルが自動記録される。

#### Phase 1b: Firestore + Nextcloud統合（Week 4-5）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| P1b-1 | GCPプロジェクト初期設定（gcloud CLI） | 1日 | なし |
| P1b-2 | Firestoreデータベース作成 + インデックス設計 | 0.5日 | P1b-1 |
| P1b-3 | `backends/firestore.py` — FirestoreBackend実装 | 3日 | P1b-2,P0-5 |
| P1b-4 | `storage/nextcloud.py` — NextcloudStorage実装（現行client.pyベース） | 2日 | P0-6 |
| P1b-5 | `storage/local.py` — LocalFileStorage実装 | 1日 | P0-6 |
| P1b-6 | `core/config.py` — Settings（pydantic-settings、環境変数） | 0.5日 | P0-1 |
| P1b-7 | バッファ→Firestore同期ロジック | 1日 | P1b-3,P1a-6 |
| P1b-8 | バッファ→Nextcloud同期ロジック | 1日 | P1b-4,P1a-6 |
| P1b-9 | テスト: Firestore統合テスト | 1日 | P1b-3 |
| P1b-10 | テスト: Nextcloud統合テスト | 0.5日 | P1b-4 |
| P1b-11 | `cli/main.py` — CLI基本コマンド（init, new, add, list, search） | 2日 | P1b-3 |

**Week 5完了時点:** SDK→Firestore→Nextcloudの全フローが動作。CLIでも操作可能。

#### Phase 1c: Embedding + Vector Search（Week 6）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| P1c-1 | `search/firestore_vector.py` — Firestore Vector Search実装 | 1日 | P1b-3 |
| P1c-2 | Cloud Functions: Embedding生成トリガー | 1日 | P1b-2 |
| P1c-3 | embedding対象テキスト生成ロジック（Notebookサマリー含む） | 1日 | P1a-5 |
| P1c-4 | Cloud Functions: Notebookサマリー生成（Gemini Flash） | 1日 | P1c-3 |
| P1c-5 | テスト: Vector Searchの検索精度評価（テストクエリセット） | 1日 | P1c-1,P1c-2 |

**Week 6完了時点:** セマンティック検索が動作。セルログもembeddingに反映。

#### Alpha Release（Week 7）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| A-1 | `compat/v1.py` — 現行MdxDbからのデータ移行スクリプト | 1日 | P1b-3 |
| A-2 | チーム向けドキュメント（クイックスタートガイド） | 1日 | 全Phase 1 |
| A-3 | .envファイルテンプレート + セットアップスクリプト | 0.5日 | P1b-6 |
| A-4 | チームメンバーへの導入・フィードバック収集 | 2日 | A-2,A-3 |

**Week 7: チーム内Alpha利用開始。** SDK + CLI + Firestore + Nextcloud + Embedding。WebAppなし、MCPなし。

#### Phase 2a: MCPサーバー（Week 8-9）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| P2a-1 | MCPサーバー骨格（FastMCP + FastAPI） | 1日 | P1b-3 |
| P2a-2 | `search` ツール実装 | 1日 | P2a-1,P1c-1 |
| P2a-3 | `get_detail` ツール実装 | 0.5日 | P2a-1 |
| P2a-4 | `get_notebook_log` ツール実装 | 1日 | P2a-1 |
| P2a-5 | `compare` / `compare_runs` ツール実装 | 1日 | P2a-1 |
| P2a-6 | `get_trace` / `explain_result` ツール実装 | 1日 | P2a-1 |
| P2a-7 | `data_preview` / `get_results` / `aggregate` / `get_timeline` 実装 | 2日 | P2a-1 |
| P2a-8 | Cloud Run デプロイ + Claude Desktop接続テスト | 1日 | P2a-2〜P2a-7 |
| P2a-9 | テスト: 全MCPツールの統合テスト | 1日 | P2a-8 |

**Week 9完了時点:** Claude Desktop/Claude CodeからMCPでデータにアクセス可能。

#### Phase 2b: Streamlit WebApp（Week 10-12）

| # | Issue | 見積もり | 依存 |
|---|-------|---------|------|
| P2b-1 | Streamlit基本構成 + 認証（Basic Auth or streamlit-authenticator） | 1日 | P2a-1 |
| P2b-2 | ダッシュボード画面 | 2日 | P2b-1 |
| P2b-3 | レコード詳細画面 | 2日 | P2b-1 |
| P2b-4 | **Notebookログビューア（Read-only）** | 2日 | P2b-3 |
| P2b-5 | 検索画面 | 2日 | P2b-1 |
| P2b-6 | LLMチャット画面（Gemini API直結） | 2日 | P2b-1 |
| P2b-7 | ファイルアップロード画面（装置PC向け） | 1日 | P2b-1 |
| P2b-8 | Cloud Run デプロイ | 0.5日 | P2b-2〜P2b-7 |
| P2b-9 | Nextcloudポーラー（Cloud Functions + Scheduler） | 1日 | P1b-4 |

**Week 12完了時点:** 全機能が利用可能。ブラウザからデータ閲覧・検索・LLMチャットが可能。

#### Phase 3: 拡張（Month 4+）

| # | Issue | 条件 |
|---|-------|------|
| P3-1 | BigQuery連携（Firestoreエクスポート設定） | 集約分析の需要が出たとき |
| P3-2 | Firebase Auth導入（WebAppの外部公開時） | 外部ユーザーが使うとき |
| P3-3 | テンプレートシステム（XRD, SEM等の定義） | チームからの要望があったとき |
| P3-4 | バッチ操作（sweep, ディレクトリインポート） | パラメータスイープの需要があったとき |
| P3-5 | 参照登録（add_ref）大容量データ | TB級データの扱いが必要になったとき |
| P3-6 | エクスポート機能（lab.export） | バックアップ要件が上がったとき |

### 8.3 スケジュール表

```
Week  1: ████ Phase 0 — SDK骨格 + InMemoryBackend
Week  2: ████ Phase 1a — tracking (セルログ、@exp.track)
Week  3: ████ Phase 1a — ローカルバッファ + テスト
Week  4: ████ Phase 1b — GCP設定 + Firestore
Week  5: ████ Phase 1b — Nextcloud統合 + CLI
Week  6: ████ Phase 1c — Embedding + Vector Search
Week  7: ▓▓▓▓ Alpha Release — チーム利用開始
Week  8: ████ Phase 2a — MCPサーバー (ツール実装)
Week  9: ████ Phase 2a — MCPサーバー (デプロイ + テスト)
Week 10: ████ Phase 2b — Streamlit (ダッシュボード + 詳細)
Week 11: ████ Phase 2b — Streamlit (検索 + Notebookビューア)
Week 12: ████ Phase 2b — Streamlit (チャット + デプロイ)
         ---- Beta Release ----
Month 4+: Phase 3 — 必要に応じて拡張
```

**開発者1人の場合:** 各Weekに+0.5週間のバッファを加えて、Alpha: Week 10、Beta: Week 18が現実的。

---

## 付録A: 設計判断のトレーサビリティ

| 判断 | 根拠 | 参照 |
|------|------|------|
| v5-lite採用 | v5-reviewの指摘「14コンポーネントは非現実的」 | v5-review/01_critical_review.md |
| Streamlit採用 | Python統一、開発速度、保守コスト | v5-review/01_critical_review.md 5.3節 |
| セルログを`cell_logs/`に分離 | tracesとは粒度・構造・用途が異なる | REQUIREMENTS.md #6 |
| ローカルバッファ必須 | 「データが消えるかも」は致命的 | REQUIREMENTS.md #8 |
| Notebookサマリーでembedding | セル単位embeddingはノイズ | v6/03_llm_analysis_final_design.md 1.2節 |
| `get_notebook_log` 新設 | `get_trace`は関数トレース用。セルログは別の表現が必要 | v6/03_llm_analysis_final_design.md |
| Cloud Run 2サービス分離 | Streamlit + FastMCPのプロセスモデルの違い | 実装上の判断 |
| Phase 1でAPI Server不要 | SDK/CLIはFirestore直接アクセス | v5/00_v5_synthesis.md |
| Firestore選定 | 階層データ x スキーマレス x 運用ゼロ x 安い | DB_SELECTION.md |

## 付録B: コスト比較サマリー

| 構成 | 月額コスト | コンポーネント数 |
|------|----------|----------------|
| v5-full (Next.js + Cloud Run + Firebase Auth + ...) | $2-15 | 14 |
| **v7 Phase 1** | **$0-5** | **5** |
| **v7 Phase 2** | **$0-15** | **8** |
| v7 Phase 3 | $5-25 | 9+ |
| 案C: SQLite + ローカルLLM | $0 | 4（チーム共有不可） |
