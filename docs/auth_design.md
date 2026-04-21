# 認証設計

## 概要

labvault のコンポーネントごとに認証方式を分ける。
Web UI のみ Firebase Auth、SDK/CLI/MCP は GCP ADC で認証する。

## 設計方針

**「普段は認証を意識しない」が最優先。**

- SDK/CLI/MCP はローカル実行 → 毎回ログイン不要
- Web UI は公開 URL → Firebase Auth で保護
- 学生の卒業時にアクセス停止できること

## コンポーネント別の認証方式

| コンポーネント | 認証方式 | ログイン頻度 | 状態 |
|---|---|---|---|
| Web UI (Next.js + FastAPI) | Firebase Auth (Google ログイン) + ホワイトリスト | 初回のみ (セッション維持) | **未実装** |
| Python SDK (`Lab()`) | GCP ADC (`gcloud auth application-default login`) | 初回のみ (トークン自動更新) | 既に動作 |
| CLI (`labvault new` 等) | SDK と同じ (ADC) | 同上 | 既に動作 |
| MCP サーバー (`labvault mcp`) | SDK と同じ (ADC) | 同上 | 既に動作 |

## Web UI 認証フロー (未実装)

```
1. ユーザーが Web UI にアクセス
2. Firebase Auth で Google ログイン
3. Frontend が Firebase ID トークンを取得
4. API リクエストに Authorization: Bearer {token} を付与
5. Backend (FastAPI) がトークンを検証
6. Firestore の allowed_users コレクションにメールがあるか確認
7. OK → API レスポンス / NG → 403 Forbidden
```

### Firestore ホワイトリスト構造

```
allowed_users/{email}
  ├── email: string
  ├── role: string ("admin" | "member")
  └── added_at: timestamp
```

### 管理者がユーザーを追加

```bash
# CLI で追加 (将来 labvault team add-member で実装)
# 当面は Firestore コンソールから直接追加
```

### 学生の卒業時

Firebase Auth でユーザーを無効化 + allowed_users から削除。

## SDK/CLI の認証セットアップ

### 新メンバー向け手順

```bash
# 1. GCP CLI インストール
# https://cloud.google.com/sdk/docs/install

# 2. ログイン
gcloud auth login
gcloud auth application-default login

# 3. プロジェクト設定
gcloud config set project klab-laser-process
```

### 管理者がメンバーに権限を付与

```bash
gcloud projects add-iam-policy-binding klab-laser-process \
  --member="user:member@example.com" \
  --role="roles/datastore.user"
```

### 装置制御用の共有 PC

サービスアカウントキーを使用：

```bash
# 管理者が作成
gcloud iam service-accounts create labvault-instrument \
  --display-name="labvault instrument PC"

gcloud projects add-iam-policy-binding klab-laser-process \
  --member="serviceAccount:labvault-instrument@klab-laser-process.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud iam service-accounts keys create key.json \
  --iam-account=labvault-instrument@klab-laser-process.iam.gserviceaccount.com

# 装置 PC に配置
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
```

## Cloud Run のアクセス制御 (未実装)

Cloud Run の URL を知っていれば誰でもアクセスできる問題への対策：

- 方式 A: Backend で Firebase Auth トークンを検証 (推奨)
- 方式 B: Cloud Run の IAM Invoker 制限 + Identity-Aware Proxy

## Nextcloud 認証の改善 (将来)

現在: config.toml に平文パスワード保存
将来: `keyring` ライブラリまたは OS のシークレットストアに移行

```python
# 将来の実装イメージ
import keyring
password = keyring.get_password("labvault-nextcloud", username)
```

## 実装優先度

1. **Web UI に Firebase Auth を追加** — Cloud Run デプロイ前に必要
2. **allowed_users ホワイトリスト** — Firebase Auth と同時
3. **labvault team add-member CLI** — 管理者向けコマンド
4. **Firestore セキュリティルール** — team レベルの読み書き制限
5. **Nextcloud keyring 移行** — セキュリティ改善
