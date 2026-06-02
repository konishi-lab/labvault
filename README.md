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
exp = lab.new("Fe-Cr薄膜 XRD測定")

# 条件を記録
exp.conditions(target="Cu", voltage_kV=40, temperature_C=500)

# データを保存
exp.add("xrd_data.ras")

# 結果を記録
exp.results["lattice_a"] = 2.873
exp.results["phase"] = "BCC"

exp.status = "success"
```

> 測定テンプレート (`template="XRD"` で必須条件チェック + 装置ファイル自動パース) は **M3 で対応予定**。

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

Web UI: **<https://labvault-web-355809880738.asia-northeast1.run.app>**

新規ユーザーは **3 ステップ**: ① Web UI でアカウント承認 → ② Web UI で PAT 発行 → ③ pip install + ランタイムに PAT を渡す (gcloud 不要)。

```
[Web UI でログイン] ──► [申請フォーム] ──► (admin が approve)
                                                │
                                                ▼
                                  [Web UI /account/tokens で PAT 発行]
                                                │
                                                ▼
                          [pip install (PAT 1 つ)] ──► lab = Lab() が動く
```

### 1. アカウント承認 (初回のみ)

Web UI <https://labvault-web-355809880738.asia-northeast1.run.app> にログインして「申請」フォームを送信。admin が approve すると、Slack に通知が飛び、ログイン後の Dashboard から API 機能が使えるようになる。

### 2. Web UI で Personal Access Token (PAT) を発行

Dashboard 右上の「トークン」または `/account/tokens` から発行する。**ラベル必須** (装置 PC: XRD A 号機 など、後で識別できる名前)。発行された `lv_xxx...` は **この画面でしか見えない** ので必ずコピー。

### 3. pip install (PAT 経由、gcloud 不要)

labvault platform が AR を proxy するので、PAT 1 つで install できる。**装置 PC でも CI でも同じ手順** (Google 認証不要)。

**Mac / Linux**:

```bash
PAT=lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # Web UI で発行したもの
PROXY=https://__token__:${PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/

# clean venv
python -m venv .venv && source .venv/bin/activate

pip install \
  --index-url https://pypi.org/simple/ \
  --extra-index-url "${PROXY}" \
  "labvault[gcp,nextcloud]"
```

**Windows (PowerShell)**:

```powershell
$env:PAT = "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$PROXY = "https://__token__:${env:PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/"

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install `
  --index-url https://pypi.org/simple/ `
  --extra-index-url "$PROXY" `
  "labvault[gcp,nextcloud]"
```

エクストラ:

| 名前 | 内容 |
|---|---|
| `gcp` | Firestore メタデータ + Vertex AI Embedding |
| `nextcloud` | Nextcloud ストレージ |
| `mcp` | MCP サーバー |
| `all` | 全部入り |

更新は同じコマンドの `-U labvault`。

> PAT を shell 履歴やプロセス一覧に残したくない場合は `pip.conf` (Unix) /
> `pip.ini` (Windows) に書く方法もある:
>
> ```bash
> # Mac/Linux: ~/.config/pip/pip.conf
> # Windows: %APPDATA%\pip\pip.ini
> [global]
> extra-index-url = https://__token__:lv_xxx@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/
> ```

### 4. SDK ランタイムに PAT を渡す

install と同じ PAT で SDK も認証する。CLI コマンドが付属するので 1 行で済む:

```bash
# Mac / Linux / Windows 共通。--token-stdin で shell 履歴に残さない:
echo "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" | labvault auth set-token --token-stdin

# 装置 PC では識別子を付ける:
echo "$PAT" | labvault auth set-token --token-stdin --user instrument-xrd-1
```

挙動:
- `~/.labvault/credentials` に `LABVAULT_TOKEN` / `LABVAULT_PLATFORM_URL` / `LABVAULT_TEAM` を書く
- 既存の credentials があれば `--force` を要求
- backend に `/api/auth/me` を投げて token が valid か検証 (`--no-verify` で skip)
- Unix では `chmod 600`、Windows では `icacls` で本人のみに絞る

設定後の確認:

```bash
labvault auth status   # token 末尾は伏字
labvault doctor        # mode: PAT mode と出れば OK
```

> 手書きで `~/.labvault/credentials` を作っても同じ。`labvault auth set-token` は
> 「OS 差分の吸収 + 検証 + パーミッション設定」を一括でやるラッパーです。

→ `Lab()` 1 行で Firestore/Nextcloud/Vertex AI に Platform 経由でアクセス。Google ライブラリ無しでも動く。詳細: [docs/instrument_pc_setup.md](docs/instrument_pc_setup.md)。

### (任意) ADC 方式

開発機で `gcloud auth application-default login` 済の Google 認証を使いたい場合。装置 PC では非推奨 (token expire 管理が面倒)。

カレントディレクトリの `.env`:

```bash
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
LABVAULT_GCP_PROJECT=klab-laser-process
LABVAULT_FIRESTORE_DATABASE=labvault
LABVAULT_PLATFORM_URL=https://labvault-api-355809880738.asia-northeast1.run.app
```

→ ADC credential を直接使って Firestore/Vertex AI にアクセス。Nextcloud credential は backend 経由で都度取得。

### 4. 動作確認

```bash
labvault doctor
```

`team` / `user` / `gcp_project` / Nextcloud 疎通をまとめて表示。`[!!]` が無ければ環境設定は OK。`Lab()` が成立するかは↓:

```bash
python -c "from labvault import Lab; lab = Lab(); print(lab); print(type(lab._metadata).__name__)"
```

PAT モードなら `PlatformMetadataBackend`、ADC モードなら `FirestoreMetadataBackend` と表示される。

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
LABVAULT_GCP_PROJECT=klab-laser-process
LABVAULT_FIRESTORE_DATABASE=labvault

# 推奨: Nextcloud credentials を platform 経由で取得 (ADC 認証)。
# ローカルに Nextcloud password を置く必要なし。
LABVAULT_PLATFORM_URL=https://labvault-api-355809880738.asia-northeast1.run.app

# 開発用: platform を経由せず直接 Nextcloud に繋ぐ場合のみ設定
# LABVAULT_NEXTCLOUD_URL=https://arim.mdx.jp/nextcloud
# LABVAULT_NEXTCLOUD_USER=arim00065
# LABVAULT_NEXTCLOUD_PASSWORD=...
# LABVAULT_NEXTCLOUD_GROUP_FOLDER=large/24UTARIM004
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
