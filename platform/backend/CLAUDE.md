# platform/backend

labvault SDK のラッパー REST API。FastAPI で実装。

## 技術スタック

- FastAPI + Uvicorn
- labvault SDK を直接 import (`from labvault import Lab`)
- Pydantic v2 でリクエスト/レスポンススキーマ定義

## 開発コマンド

```bash
# 依存インストール
pip install -e "../../.[dev]" -r requirements.txt

# 起動
uvicorn app.main:app --reload --port 8000

# API ドキュメント
# http://localhost:8000/docs (Swagger UI)
```

## ディレクトリ構成

```
app/
├── main.py          # FastAPI app, CORS, lifespan, health endpoint
├── dependencies.py  # Lab シングルトン (get_lab)
├── schemas.py       # Pydantic request/response モデル
└── routers/
    ├── records.py   # Record CRUD + 操作 (/api/records/...)
    ├── files.py     # ファイル upload/download (/api/records/{id}/files/...)
    └── search.py    # 検索 (/api/search)
```

## 規約

- Lab インスタンスはシングルトン (`dependencies.py`)。Settings から自動バックエンド選択
- 全エンドポイントは `/api/` prefix
- RecordNotFoundError → HTTP 404 に変換
- ファイルアップロードは `multipart/form-data`
- CORS: localhost:3000 を許可 (frontend 開発用)
- auto_log=False で Lab を使う (Web API にIPython hooks は不要)

## ローカル開発の env

| 変数 | 用途 |
|---|---|
| `LABVAULT_DEV_SKIP_AUTH=1` | Firebase token 検証をスキップ。`/api/auth/me` は固定の dev (admin / konishi-lab) を返す。Firestore ADC が無い環境でも UI を起動できる |
| `LABVAULT_CORS_ORIGINS=http://localhost:3001,http://localhost:3765` | デフォルト (`localhost:3000` のみ) 以外の port で frontend dev server を立てる時に追加 |
| `LABVAULT_AR_REPO=projects/<p>/locations/<l>/repositories/labvault-pypi` | approve / add team / 活性化 で AR reader を grant する先 |
| `LABVAULT_AR_QUOTA_PROJECT=<gcp_project>` | user-credential ADC で AR を叩く時の consumer project header 用 (SA 認証では不要) |

### ハマりどころ

- **CORS error の真因が 500 のことがある**: `Authorization` ヘッダ付きリクエスト
  への 500 レスポンスには `CORSMiddleware` が origin ヘッダを付けないため、
  ブラウザには「CORS error」と表示される。CORS 設定を疑う前に backend ログで
  500 が出ていないかを確認する。
- **dev_skip と Firestore**: `LABVAULT_DEV_SKIP_AUTH=1` は認証だけスキップする
  ので、handler 内で Firestore を引く処理はそのまま走る。Firestore ADC が
  無い場合は handler ごとに dev_skip 分岐が必要 (例: `auth_me`)。
