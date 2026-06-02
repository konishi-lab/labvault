# 装置 PC セットアップ手順

実験装置 PC (Notebook なし、SSH or 直操作の Linux/Windows/Mac) で labvault SDK を動かす標準手順。

## 前提

- Python 3.11 以上
- ネットワーク到達性: `https://labvault-api-355809880738.asia-northeast1.run.app` (Cloud Run backend)
- labvault Web UI で labvault 利用が承認済み (admin による approve 完了)

## 認証方式の選択

| 方式 | 向いている場面 | セットアップ手間 |
|---|---|---|
| **PAT (Personal Access Token)** | 装置 PC・CI・unattended スクリプト全般 (推奨) | Web UI で発行 → 1 ファイル配置 |
| GCP ADC (`gcloud auth application-default login`) | ローカル Mac / Notebook で対話的に使う場合 | ブラウザログイン必要 |
| サービスアカウント JSON key | 完全自動運用、長期運用、PAT を使いたくない場合 | SA 作成 + IAM 設定が必要 |

装置 PC はブラウザが無い・SSH 越しが多いので **PAT 方式が圧倒的に楽**。本書は PAT 方式を中心に説明する。

## 手順 (PAT 方式)

### 1. PAT を発行

ブラウザのある別マシン (自分の Mac など) で:

1. <https://labvault-web-355809880738.asia-northeast1.run.app/account/tokens> にアクセス
2. ラベルを入力 (例: `装置 PC (XRD-1)`) して「発行」
3. 表示された `lv_xxxxxxxx...` をコピー (**この画面を閉じると再表示できません**)

### 2. labvault SDK をインストール (gcloud 不要)

labvault platform が Artifact Registry を proxy するので、**同じ PAT** で pip install もできる。装置 PC に gcloud / Google 認証は一切不要。

**Mac / Linux**:

```bash
PAT=lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  # ↑で発行したもの
PROXY=https://__token__:${PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/

python -m venv ~/labvault-venv && source ~/labvault-venv/bin/activate

pip install \
  --index-url https://pypi.org/simple/ \
  --extra-index-url "${PROXY}" \
  "labvault[gcp,nextcloud]"
```

**Windows (PowerShell)**:

```powershell
$env:PAT = "lv_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$PROXY = "https://__token__:${env:PAT}@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/"

python -m venv $HOME\labvault-venv
$HOME\labvault-venv\Scripts\Activate.ps1

pip install `
  --index-url https://pypi.org/simple/ `
  --extra-index-url "$PROXY" `
  "labvault[gcp,nextcloud]"
```

依存ライブラリ (httpx / pydantic 等) は public PyPI から取られるので、labvault wheel 本体だけが proxy 経由。装置 PC は public PyPI と `labvault-api-...run.app` への HTTPS 到達性があれば OK。

> PAT を shell 履歴 / プロセス一覧に残したくない場合は `~/.config/pip/pip.conf` (Mac/Linux) または `%APPDATA%\pip\pip.ini` (Windows) に書く:
>
> ```
> [global]
> extra-index-url = https://__token__:lv_xxx@labvault-api-355809880738.asia-northeast1.run.app/api/pypi/simple/
> ```
>
> その上で `pip install "labvault[gcp,nextcloud]"` で済む。

### 3. 装置 PC の `~/.labvault/credentials` に設定

`labvault auth set-token` で 1 行で書ける (chmod / token 検証も自動):

```bash
# Mac / Linux / Windows 共通。--token-stdin で shell 履歴に残らない:
echo "lv_ここに先ほどの token を貼り付け" \
  | labvault auth set-token --token-stdin --user instrument-xrd-1
```

挙動:
- `~/.labvault/credentials` に書く (内容は下記)
- backend に `/api/auth/me` を投げて token を検証
- Unix では `chmod 600`、Windows では `icacls` で本人のみに絞る
- 既存ファイルがあると拒否 (`--force` で上書き)

設定後に `labvault auth status` で確認:

```
$ labvault auth status
  credentials file: /home/you/.labvault/credentials
  LABVAULT_TOKEN:        lv_abcde...
  LABVAULT_PLATFORM_URL: https://labvault-api-355809880738.asia-northeast1.run.app
  LABVAULT_TEAM:         konishi-lab
  LABVAULT_USER:         instrument-xrd-1
```

書かれる内容:

- `LABVAULT_TOKEN` — 認証に使う PAT
- `LABVAULT_PLATFORM_URL` — backend の URL (固定)
- `LABVAULT_TEAM` — 書き込む team。複数 team 所属の場合のみ意味あり (single team なら省略可)
- `LABVAULT_USER` — Record の `created_by` に入る装置識別子。後で「どの装置から投入されたか」を絞り込むのに使う。`instrument-xrd-1` `sputter-A` 等、装置単位の名前を推奨

> **手書きで作りたい場合** (CLI が使えない最小環境など):
>
> ```bash
> mkdir -p ~/.labvault
> cat > ~/.labvault/credentials << 'EOF'
> LABVAULT_TOKEN=lv_xxxxx...
> LABVAULT_PLATFORM_URL=https://labvault-api-355809880738.asia-northeast1.run.app
> LABVAULT_TEAM=konishi-lab
> LABVAULT_USER=instrument-xrd-1
> EOF
> chmod 600 ~/.labvault/credentials
> ```
>
> `chmod 600` は他ユーザーから読めなくするための重要なステップ。

### 4. 動作確認

```bash
python -c "from labvault import Lab; lab = Lab(); print(lab); print(type(lab._metadata).__name__)"
```

期待出力:

```
Lab(team='konishi-lab')
PlatformMetadataBackend
```

`PlatformMetadataBackend` と表示されれば PAT モードで動いている。`FirestoreMetadataBackend` だった場合は credentials 読込が失敗しているので確認。

### 5. 簡単な書き込みテスト

```python
from labvault import Lab

lab = Lab()
rec = lab.new("setup-test", auto_log=False)
print(f"created: {rec.id}")
rec.note("instrument PC setup OK")
lab.delete(rec.id)  # soft delete
```

`/admin/users` の自分のページで `last_used_at` が更新されていれば成功。

## トークンの管理

- **失効**: `/account/tokens` で「失効」ボタン → 即時無効化。装置 PC 側は次回 API 呼出しで 401 が返る
- **更新**: 古い token を失効して新規発行 → `~/.labvault/credentials` を上書き
- **複数装置**: 装置ごとに別の token を発行 (個別に失効・トラッキング可能)
- **last_used_at** で「使われてない token」を見つけて棚卸できる

## トラブルシューティング

### `Token verification failed` (401)

token が古い、または失効されている。`/account/tokens` で確認 → 必要なら再発行。

### `not allowed` / `is deactivated` (403)

ユーザー本人が deactivate されている。admin に連絡。

### `team … not found` (404)

`LABVAULT_TEAM` の値が typo か、ユーザーがそのチームに所属していない。`/admin/users` で自分の所属 team を確認。

### `Connection refused` / DNS error

`LABVAULT_PLATFORM_URL` が typo か、ネットワーク到達不可。curl で疎通確認:

```bash
curl https://labvault-api-355809880738.asia-northeast1.run.app/api/health
```

## 代替: サービスアカウント方式 (上級者向け)

GCP プロジェクトに装置専用 SA を作成し、JSON key を装置 PC に配置:

```bash
# Mac 側で
gcloud iam service-accounts create instrument-xrd-1 \
  --project=klab-laser-process
gcloud projects add-iam-policy-binding klab-laser-process \
  --member=serviceAccount:instrument-xrd-1@klab-laser-process.iam.gserviceaccount.com \
  --role=roles/datastore.user
gcloud iam service-accounts keys create ~/instrument-xrd-1.json \
  --iam-account=instrument-xrd-1@klab-laser-process.iam.gserviceaccount.com

# 装置 PC に key をコピー
scp ~/instrument-xrd-1.json instrument-pc:/etc/labvault/sa-key.json

# 装置 PC 側
export GOOGLE_APPLICATION_CREDENTIALS=/etc/labvault/sa-key.json
# allowed_users にも SA email を追加 (admin が Web UI から承認)
```

ただし PAT より煩雑なので、特別な理由が無ければ PAT 方式を推奨。

## 参考

- [auth_design.md](./auth_design.md) — 認証全体設計
- [multitenant_next_steps.md](./multitenant_next_steps.md) — 認証拡張 Phase 1〜5 の経緯
