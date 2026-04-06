# labvault platform

labvault SDK のデプロイ可能なサービス群。

## 構成

```
platform/
├── frontend/      Next.js (Web UI)
├── backend/       FastAPI (API サーバー、labvault SDK を直接利用)
├── functions/     Cloud Functions (将来: MCP サーバー、embedding 生成、Nextcloud ポーラー)
├── infra/         Terraform (将来: GCP インフラ定義)
├── Dockerfile     Cloud Run 用 (frontend + backend 同居)
└── README.md
```

## 技術スタック

| コンポーネント | 技術 | 役割 |
|---|---|---|
| Frontend | Next.js + TypeScript | 実験データの閲覧・検索・テンプレート管理 |
| Backend | FastAPI + Python | labvault SDK のラッパー API |
| デプロイ | Cloud Run | 1コンテナに frontend + backend を同居 |
| リージョン | asia-northeast1 (東京) | |
| コスト | $0/月 (無料枠内) | 最小インスタンス 0、研究室規模 |

## ローカル開発

```bash
# Backend
cd platform/backend
pip install -e "../../.[dev]"   # labvault SDK
uvicorn main:app --reload --port 8000

# Frontend
cd platform/frontend
npm install
npm run dev   # http://localhost:3000
```

## デプロイ

```bash
# Cloud Run にデプロイ
cd platform
gcloud run deploy labvault-web \
  --source . \
  --region asia-northeast1 \
  --allow-unauthenticated \
  --min-instances 0
```

## 予定機能

### Web UI (M6)
- ダッシュボード (最近の実験一覧)
- レコード詳細表示
- テキスト検索 + フィルタリング
- テンプレート管理 (XRD/SEM 等の入力フォーム)
- ファイルアップロード

### Cloud Functions (将来)
- チーム共有 MCP サーバー (8ツール)
- embedding_generator (SDK 非経由投入のフォールバック)
- nextcloud_poller (_inbox フォルダ監視 + 自動取込)
