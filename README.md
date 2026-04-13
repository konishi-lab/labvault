# labvault

**Python/Notebookで実験する研究室のための実験データ基盤。**

測定から解析までのコード・データ・条件が自動で記録され、蓄積されたデータをLLMが横断検索・解析する。

## 特徴

- **自動ログ**: `lab.new("XRD測定")` の1行で、以降のNotebookセル実行が全て自動記録される
- **ファイル管理**: `exp.add("data.ras")` でデータ保存。装置ファイル(.ras, .dm3等)からメタデータを自動抽出
- **ローカルファースト**: データは必ずローカルに先に保存。ネットワーク障害でもデータは消えない
- **テンプレート**: XRD/SEM/SQUID等の測定テンプレートで条件入力を標準化。必須項目チェック付き
- **装置制御対応**: `exp.log_value()` / `exp.log_event()` で.pyスクリプトからも記録可能
- **LLM横断検索**: MCP (7ツール) / CLI (16コマンド) 経由でClaude/Geminiが全実験データを検索・比較・集計・解析
- **チーム共有**: 研究室メンバー全員のデータが1つの検索可能なプールに
- **Web UI**: レコード閲覧、条件カラム表示、散布図、一括アップロード

## クイックスタート

```python
from labvault import Lab

lab = Lab()
exp = lab.new("Fe-Cr薄膜 XRD測定", template="XRD")

# 条件を記録
exp.conditions(target="Cu", voltage_kV=40, temperature_C=500)

# データを保存（.rasからメタデータを自動抽出）
exp.add("xrd_data.ras")

# 結果を記録
exp.results["lattice_a"] = 2.873
exp.results["phase"] = "BCC"

exp.status = "success"
```

## 装置制御スクリプトからの記録

```python
# instrument_control.py（Notebookではない通常の.py）
from labvault import Lab

lab = Lab()
exp = lab.new("スパッタ成膜", auto_log=False)
exp.conditions(temperature_C=500, pressure_Pa=0.5)

exp.log_event("deposition_start", "RF ON 200W")
for t in measure_temperature():
    exp.log_value("substrate_temperature_C", t)
exp.log_event("deposition_end", "RF OFF")

exp.add("process_log.csv")
```

## 別Notebookでの解析追記

```python
# analysis.ipynb（測定とは別のNotebook）
from labvault import Lab

lab = Lab()
exp = lab.get("AB3F", auto_log=True)  # 既存Recordに接続、セルログ記録開始
# → 以降のセルはAB3Fに記録される（セッション自動分離）

exp.results["fwhm"] = 0.429
exp.save("fit_plot", fig)
```

## LLM 連携（MCP / CLI）

labvault に蓄積されたデータを LLM が検索・分析できます。

### MCP サーバー（Claude Desktop / Claude Code）

```bash
labvault mcp  # 7ツール: search, get_detail, compare, data_preview, aggregate, get_overview, get_timeline
```

```
ユーザー: 「power が 50W 以上の実験で、angle 別の pulse_energy の傾向を見せて」
Claude: search(conditions={"power": {"gte": 50}}, include_conditions=True)
        → aggregate(key="pulse_energy", group_by="angle", parent_id="DE9Z7K")
        → 自然言語で分析結果を報告
```

### CLI（Claude Code が Bash 経由で利用可能、トークン効率が良い）

```bash
# 条件フィルタ付き検索
labvault search -p DE9Z7K -c "power>=50" --show-conditions

# 統計集計
labvault aggregate pulse_energy --group-by angle -p DE9Z7K

# シリーズ概要
labvault overview DE9Z7K
```

## インストール

```bash
pip install labvault

# GCPバックエンド付き
pip install labvault[gcp,nextcloud]

# 全部入り
pip install labvault[all]
```

## セットアップ

### 1. 開発環境

```bash
git clone https://github.com/konishi-lab/labvault.git
cd labvault
pip install -e ".[dev]"
pytest  # テストが通ることを確認
```

### 2. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集して接続情報を設定:

```bash
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
LABVAULT_NEXTCLOUD_URL=https://arim.mdx.jp/nextcloud
LABVAULT_NEXTCLOUD_USER=your-nextcloud-user
LABVAULT_NEXTCLOUD_PASSWORD=your-app-password
LABVAULT_NEXTCLOUD_GROUP_FOLDER=24UTARIM004
LABVAULT_GCP_PROJECT=your-gcp-project
LABVAULT_FIRESTORE_DATABASE=(default)
```

### 3. GCP (Firestore) セットアップ

```bash
# GCP CLI のインストール (未インストールの場合)
# https://cloud.google.com/sdk/docs/install

# ログイン
gcloud auth login
gcloud auth application-default login
gcloud config set project your-gcp-project

# Firestore API の有効化
gcloud services enable firestore.googleapis.com --project=your-gcp-project

# Firestore データベースの作成 (初回のみ)
gcloud firestore databases create --location=asia-northeast1 --project=your-gcp-project
```

### 4. 動作確認

```bash
# ユニットテスト (外部サービス不要)
pytest

# 結合テスト (Nextcloud)
pytest tests/integration/test_nextcloud_live.py -v -m integration

# 結合テスト (Firestore)
pytest tests/integration/test_firestore_live.py -v -m integration
```

### 5. examples を試す

```bash
pip install jupyter
jupyter lab examples/

# スクリプト版
python examples/02_instrument_script.py
```

## アーキテクチャ

```
labvault (このリポ)        = Python SDK（実験者が使う）
labvault-platform          = バックエンド（MCPサーバー + Cloud Functions + GCPインフラ）
```

| コンポーネント | 役割 |
|-------------|------|
| SDK (labvault) | Lab/Record API, IPython hooks, ローカルバッファ, パーサー |
| CLI | 16コマンド (検索・集計・概要分析・MCP起動等) |
| MCP サーバー | 7ツール (search, get_detail, compare, aggregate, get_overview 等) |
| Firestore | メタデータ, Vector Search, セルログ |
| Nextcloud (大学提供) | バイナリファイル (30TB) |
| Cloud Run | Web UI (Next.js) + REST API (FastAPI) |
| Vertex AI | text-embedding-004 (セマンティック検索) |

月額GCPコスト: **~$1** (5人チーム, 月500操作)

## 設計ドキュメント

- [SDK Cookbook](docs/design/v10/04_sdk_cookbook.md) — 全APIのコード例
- [v10 概要](docs/design/v10/00_v10_overview.md) — アーキテクチャ・コスト
- [マイルストーン](docs/design/v10/05_milestones.md) — 実装計画
- [要件定義](docs/design/REQUIREMENTS.md) — R01-R22

## License

MIT
