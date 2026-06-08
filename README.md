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

**リモート (推奨, Python install 不要)** — Cloud Run でホスト中の MCP サーバーに PAT で繋ぐ。接続情報はどの client でも同じ:

- URL: `https://labvault-api-355809880738.asia-northeast1.run.app/mcp/`
- Header: `Authorization: Bearer lv_xxx` (PAT は Web UI `/account/tokens` で発行)

| Client | 登録方法 |
|---|---|
| Claude Code | `claude mcp add --transport http labvault <URL> -H "Authorization: Bearer lv_xxx"` |
| Claude Desktop | `claude_desktop_config.json` の `mcpServers` に `type:"http"` + URL + headers |
| Cursor | `~/.cursor/mcp.json` に `type:"streamable-http"` + URL + headers |
| Gemini CLI | `gemini mcp add --transport http labvault <URL> -H "Authorization: Bearer lv_xxx"` |
| ChatGPT | Developer Mode で Custom MCP server を追加 (Plus / Pro / Team / Enterprise / Edu 限定) |
| その他 | Streamable HTTP transport で同じ URL + Bearer を渡せば OK |

詳細は [docs/onboarding.md §3-B](docs/onboarding.md#3-b-llm-mcp-から使う-python-install-不要)。

**ローカル (装置 PC など SDK が入っている環境)** — stdio で起動:

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

### 認証方式の選び方

| 環境 | 推奨 | 理由 |
|---|---|---|
| **Mac / Linux の開発機 / Notebook** | **ADC** | 監査ログが個人 Google アカウントと紐付く / token 流出時の被害が小さい / 失効が組織側で一括 / `gcloud` で済む |
| **CI で Workload Identity が使える環境** | ADC (SA) | 同上 |
| **装置 PC (Windows + gcloud 不可)** | PAT | gcloud が入らない / SSH 越し / ブラウザなし環境向けの代替 |
| **CI で gcloud が立たない環境** | PAT | 同上 |

以下、まず **ADC 方式 (推奨)** を説明し、続いて **PAT 方式 (装置 PC / CI 等)** を説明する。共通で先に Web UI 承認が必要。

### 1. アカウント承認 (初回のみ)

Web UI <https://labvault-web-355809880738.asia-northeast1.run.app> にログインして「申請」フォームを送信。admin が approve すると、Slack に通知が飛び、ログイン後の Dashboard から API 機能が使えるようになる (同時に Artifact Registry の reader 権限も自動付与)。

---

### 2. ADC 方式 (推奨): pip install + SDK ランタイム

#### 2.1 pip install (一度だけ)

`pip install` は private な Artifact Registry から wheel を取得するため、Google 認証が必要。

```bash
# 一度だけ: GCP ログイン
gcloud auth login
gcloud auth application-default login

# AR 認証 helper
pip install keyring keyrings.google-artifactregistry-auth

# labvault 本体
pip install \
  --extra-index-url https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi/simple/ \
  "labvault[all]"
```

エクストラ:

| 名前 | 内容 |
|---|---|
| `gcp` | Firestore メタデータ + Vertex AI Embedding |
| `nextcloud` | Nextcloud ストレージ |
| `numpy` | `save()` の自動変換 (ndarray / DataFrame / matplotlib Figure) |
| `mcp` | MCP サーバー (`labvault mcp`) |
| `keyring` | AR 認証 helper を SDK 経由でも入れたい時 |
| `all` | 上記まとめて (**研究室メンバーは基本これ**) |

更新は `pip install -U labvault`。サーバー / CI のように依存を絞り
たいときだけ `labvault[gcp,nextcloud]` 等を選んでください。

#### 2.2 SDK ランタイム認証

カレントディレクトリ (or `~/.labvault/config.toml`) の `.env`:

```bash
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
```

→ `gcloud auth application-default login` の credential を使って Firestore/Vertex AI にアクセス。Nextcloud credential は backend 経由で都度取得。`labvault doctor` で `mode: Direct mode` か `Mixed mode` と出れば OK。

> `LABVAULT_GCP_PROJECT` / `LABVAULT_FIRESTORE_DATABASE` /
> `LABVAULT_PLATFORM_URL` / `LABVAULT_NEXTCLOUD_URL` /
> `LABVAULT_NEXTCLOUD_GROUP_FOLDER` は **konishi-lab 本番運用の値が SDK の
> default に組み込まれている** ので、特に他研究室や別 GCP project に向け
> たい場合だけ env で上書きしてください (0.2.2 以降)。

---

### 3. PAT 方式 (装置 PC / CI 等の代替): pip install + SDK ランタイム

装置 PC で gcloud が入らない、SSH 越しで OAuth flow が踏めない、ブラウザなど — そんな環境では PAT (Personal Access Token) で代替する。**1 つの PAT で pip install もランタイムも完結**。

#### 3.1 Web UI で PAT を発行

Dashboard 右上の「トークン」または `/account/tokens` から発行。**ラベル必須** (例: `装置 PC: XRD A 号機`)。発行された `lv_xxx...` は **この画面でしか見えない** ので必ずコピー。

#### 3.2 pip install (PAT 経由、gcloud 不要)

labvault platform が AR を proxy するので、PAT 1 つで install できる。

**Mac / Linux**:

```bash
PAT=lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # Web UI で発行したもの
PROXY=https://__token__:${PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/

python -m venv .venv && source .venv/bin/activate

pip install \
  --index-url https://pypi.org/simple/ \
  --extra-index-url "${PROXY}" \
  "labvault[all]"
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
  "labvault[all]"
```

> PAT を shell 履歴やプロセス一覧に残したくない場合は `pip.conf` (Unix) /
> `pip.ini` (Windows) に書く方法もある:
>
> ```bash
> # Mac/Linux: ~/.config/pip/pip.conf
> # Windows: %APPDATA%\pip\pip.ini
> [global]
> extra-index-url = https://__token__:lv_xxx@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/
> ```

#### 3.3 SDK ランタイム認証 (`labvault auth set-token`)

install と同じ PAT で SDK も認証する。CLI が一括でやる:

```bash
# 個人用 (Mac / Linux ノート PC など) — --user 省略で PAT 発行者の email が default に
echo "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" | labvault auth set-token --token-stdin

# 装置 PC / CI — `--user` を明示して識別子を入れる
echo "$PAT" | labvault auth set-token --token-stdin --user instrument-xrd-1
```

> **装置 PC では `--user` を明示** することを強く推奨します。複数人で
> 1 つの credentials を共有する場合、`--user` 省略のままだと **全 record
> の `created_by` が PAT 発行者 1 人になり**、「どの装置で誰が測定したか」
> が後で追えなくなります。

挙動:
- `~/.labvault/credentials` に `LABVAULT_TOKEN` / `LABVAULT_PLATFORM_URL` / `LABVAULT_TEAM` を書く
- `--user` 省略時は backend に `/api/auth/me` を投げて取れた email を default
  として `LABVAULT_USER` に書く (`--no-verify` だと default なし)
- 既存の credentials があれば `--force` を要求
- Unix では `chmod 600`、Windows では `icacls` で本人のみに絞る

> **手書きでも可** (0.2.2 以降): `platform_url` が SDK の default に
> 入っているので、自分でファイルを書く場合は最小で
> `LABVAULT_TOKEN=lv_xxx` + `LABVAULT_TEAM=konishi-lab` の 2 行で PAT
> モードが成立します。`auth set-token` は検証 + 安全な書き込み + 推奨
> 注釈までやるので CLI 経由を推奨ですが、手書き派の方の最小例は:
>
> ```bash
> cat > ~/.labvault/credentials << 'EOF'
> LABVAULT_TOKEN=lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
> LABVAULT_TEAM=konishi-lab
> LABVAULT_USER=your-name
> EOF
> chmod 600 ~/.labvault/credentials
> ```

設定後の確認:

```bash
labvault auth status   # token 末尾は伏字
labvault doctor        # mode: PAT mode と出れば OK
```

詳細は [docs/instrument_pc_setup.md](docs/instrument_pc_setup.md)。

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

# 以下の 5 つは konishi-lab 本番運用の値が SDK の default に組み込
# まれているため、本リポジトリで開発する限りは設定不要 (上書きしたい
# ときだけコメントを外す)。
# LABVAULT_GCP_PROJECT=klab-laser-process
# LABVAULT_FIRESTORE_DATABASE=labvault
# LABVAULT_PLATFORM_URL=https://labvault-api-355809880738.asia-northeast1.run.app
# LABVAULT_NEXTCLOUD_URL=https://arim.mdx.jp/nextcloud
# LABVAULT_NEXTCLOUD_GROUP_FOLDER=large/24UTARIM004

# 開発用: platform を経由せず直接 Nextcloud に繋ぐ場合のみ設定
# LABVAULT_NEXTCLOUD_USER=arim00065
# LABVAULT_NEXTCLOUD_PASSWORD=...
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
