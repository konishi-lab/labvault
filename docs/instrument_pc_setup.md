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

### 1. labvault SDK をインストール

`pip install` は private な Artifact Registry から wheel を取得するため、**この 1 ステップだけは GCP 認証が必要**。PAT モードであっても pip 自体は Google 認証で読みに行く (PAT は SDK 実行時の認証であって AR の認証ではない)。

```bash
# 装置 PC で gcloud が使える場合:
gcloud auth login
gcloud auth application-default login
pip install keyring keyrings.google-artifactregistry-auth
pip install --extra-index-url https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi/simple/ \
  labvault
```

gcloud が入らない / ブラウザが無くて ADC ログインも難しい装置 PC では:

1. ブラウザのある別マシンで wheel を download
   ```bash
   pip download --no-deps --dest ~/wheels \
     --extra-index-url https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi/simple/ \
     labvault
   ```
2. `scp ~/wheels/labvault-*.whl instrument-pc:/tmp/`
3. 装置 PC で `pip install /tmp/labvault-*.whl httpx pydantic pydantic-settings click` (依存も同様に持参)

インストール後は PAT が認証を担うので、GCP credentials は装置 PC に残す必要なし。

### 2. PAT を発行

ブラウザのある別マシン (自分の Mac など) で:

1. <https://labvault-web-355809880738.asia-northeast1.run.app/account/tokens> にアクセス
2. ラベルを入力 (例: `装置 PC (XRD-1)`) して「発行」
3. 表示された `lv_xxxxxxxx...` をコピー (**この画面を閉じると再表示できません**)

### 3. 装置 PC の `~/.labvault/credentials` に設定

```bash
mkdir -p ~/.labvault
cat > ~/.labvault/credentials << 'EOF'
LABVAULT_TOKEN=lv_ここに先ほどの token を貼り付け
LABVAULT_PLATFORM_URL=https://labvault-api-355809880738.asia-northeast1.run.app
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=instrument-xrd-1
EOF
chmod 600 ~/.labvault/credentials
```

- `LABVAULT_TOKEN` — 認証に使う PAT
- `LABVAULT_PLATFORM_URL` — backend の URL (固定)
- `LABVAULT_TEAM` — 書き込む team。複数 team 所属の場合のみ意味あり (single team なら省略可)
- `LABVAULT_USER` — Record の `created_by` に入る装置識別子。後で「どの装置から投入されたか」を絞り込むのに使う。`instrument-xrd-1` `sputter-A` 等、装置単位の名前を推奨

`chmod 600` は他ユーザーから読めなくするための重要なステップ。

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
