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
