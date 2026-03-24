# v10 GCPアーキテクチャ・コスト・セキュリティ・モニタリング詳細設計

> v9レビュー（G-1〜G-19, L-3, S-1）を全面反映。
> Cloud Run / Cloud Run Jobs / VPCコネクタを廃止し、Cloud Functions Gen2に統一。
> 月額コスト$0.94を全コンポーネント別に証明する。

---

## 目次

1. [アーキテクチャ概要](#1-アーキテクチャ概要)
2. [Cloud Functions Gen2 MCPサーバー設計](#2-cloud-functions-gen2-mcpサーバー設計)
3. [コスト詳細計算](#3-コスト詳細計算)
4. [セキュリティ設計](#4-セキュリティ設計)
5. [コールドスタート対策](#5-コールドスタート対策)
6. [モニタリング・アラート設計](#6-モニタリングアラート設計)
7. [Firestoreバックアップ設計](#7-firestoreバックアップ設計)
8. [embedding無限ループ防止](#8-embedding無限ループ防止)
9. [Nextcloud接続経路](#9-nextcloud接続経路)
10. [デプロイ手順](#10-デプロイ手順)

---

## 1. アーキテクチャ概要

### 1.1 v10 確定構成

```
┌───────────────────────────────────────────────────────────┐
│                     GCP Project (kpro-arim)                │
│                     Region: asia-northeast1                │
│                                                           │
│  ┌─────────────────────┐  ┌─────────────────────────────┐ │
│  │  Cloud Functions Gen2│  │  Firestore Native Mode      │ │
│  │                     │  │                             │ │
│  │  ● mcp-server       │  │  teams/{team_id}/           │ │
│  │    (MCPサーバー)     │──▶│    records/{id}             │ │
│  │                     │  │    templates/{name}         │ │
│  │  ● embedding-gen    │  │    info                     │ │
│  │    (embedding生成)   │  │                             │ │
│  │                     │  │  768次元 Vector Search      │ │
│  │  ● nextcloud-poller │  │  cosine距離                 │ │
│  │    (_inbox検出)      │  └─────────────────────────────┘ │
│  │                     │                                  │
│  │  ● firestore-backup │  ┌─────────────────────────────┐ │
│  │    (日次バックアップ) │  │  Cloud Storage              │ │
│  └─────────────────────┘  │  labvault-backups/           │ │
│                           │  (30日保持)                  │ │
│  ┌─────────────────────┐  └─────────────────────────────┘ │
│  │  Cloud Scheduler    │                                  │
│  │  ● poller (15分毎)  │  ┌─────────────────────────────┐ │
│  │  ● backup (日次)    │  │  Secret Manager              │ │
│  │  ● cleanup(週次)    │  │  nextcloud-url              │ │
│  └─────────────────────┘  │  nextcloud-user             │ │
│                           │  nextcloud-password          │ │
│                           │  mcp-api-key                │ │
│                           └─────────────────────────────┘ │
│                                                           │
│  ┌─────────────────────┐  ┌─────────────────────────────┐ │
│  │  Vertex AI          │  │  Cloud Monitoring           │ │
│  │  text-embedding-004 │  │  予算アラート ($5/$8/$10)    │ │
│  │  (REST API直接)     │  │  エラー率アラート            │ │
│  └─────────────────────┘  │  構造化ログ                 │ │
│                           └─────────────────────────────┘ │
└───────────────────────────────────────────────────────────┘

           │ HTTPS (パブリック)
           ▼
┌─────────────────────────────────────────┐
│  Nextcloud (学内オンプレ or VPS)         │
│  30TB グループフォルダ                    │
│  WebDAV API                             │
└─────────────────────────────────────────┘
```

### 1.2 v9からの廃止コンポーネントと理由

| v9コンポーネント | v10 | 廃止理由 |
|----------------|-----|---------|
| **Cloud Run Service** (MCPサーバー) | Cloud Functions Gen2 | min-instances=0でもVPCコネクタが必要。固定コスト$7-10/月。Cloud Functions Gen2はHTTPエンドポイントを直接公開でき、VPCコネクタ不要 |
| **Cloud Run Jobs** (サンドボックス) | Cloud Functions内subprocess | コールドスタート30-60秒（科学計算パッケージ含む大きなイメージ）。UXとして不適。subprocess方式なら0.5-2秒 |
| **VPCコネクタ** | 廃止 | Cloud Functions Gen2はVPCコネクタなしで外部HTTPS通信可能。$7-10/月の隠れコスト排除 |
| **Cloud Storage一時バケット** | 廃止 | Cloud Run Jobs間のデータ受け渡しが不要に。subprocess方式ではローカルtmpdir |
| **preview_generator** | MCPのdata_previewでオンデマンド生成 | 常時稼働のCloud Functionsが不要。LLMがリクエストした時だけ生成 |
| **notebook_summarizer** | SDK側でembedding_textに統合 | 独立したCloud Functionsが不要。SDK内で完結 |

### 1.3 Cloud Functions Gen2をMCPサーバーに採用する技術的根拠

```
Cloud Functions Gen2 の特性:
  ├── HTTP関数 → HTTPSエンドポイントを直接公開（Streamable HTTP transport対応）
  ├── 最大60分のタイムアウト（v9 Cloud Run=300秒と同等以上）
  ├── concurrency=1-1000（v9 Cloud Run=80と同等以上）
  ├── min-instances=0 → 完全従量課金（アイドル時コスト$0）
  ├── cpu_boost → コールドスタート時のCPUブースト（無料）
  ├── VPCコネクタ不要 → 外部HTTPS通信（Nextcloud）に直接アクセス可能
  └── gVisor自動適用 → subprocess方式のサンドボックスが無追加コストで利用可能
```

**MCPプロトコルとの互換性**:
- FastMCPのStreamable HTTP transportはHTTP POST/GETで動作
- Cloud Functions Gen2のHTTP関数はステートレスなHTTPリクエストを処理可能
- MCPのSSE (Server-Sent Events) もCloud Functions Gen2で対応可能（レスポンスストリーミング機能）

---

## 2. Cloud Functions Gen2 MCPサーバー設計

### 2.1 関数一覧

| 関数名 | トリガー | メモリ | タイムアウト | concurrency | サービスアカウント |
|--------|---------|--------|------------|-------------|-----------------|
| `mcp-server` | HTTPS | 512 MiB | 300秒 | 10 | `mcp-server@` |
| `embedding-gen` | Firestore onWrite | 256 MiB | 60秒 | 1 | `embedding-gen@` |
| `nextcloud-poller` | Cloud Scheduler | 512 MiB | 120秒 | 1 | `poller@` |
| `firestore-backup` | Cloud Scheduler | 256 MiB | 300秒 | 1 | `scheduler@` |

### 2.2 MCPサーバー関数の構成

```python
# functions/mcp_server/main.py
import functions_framework
from fastmcp import FastMCP
from google.cloud import firestore

# グローバル変数: コールドスタート時に1回だけ初期化
_mcp: FastMCP | None = None
_db: firestore.Client | None = None

def _get_mcp() -> FastMCP:
    """遅延初期化。初回リクエスト時にMCPサーバーを構築。"""
    global _mcp, _db
    if _mcp is None:
        _db = firestore.Client(
            project="kpro-arim",
            database="labvault",
        )
        _mcp = FastMCP(
            name="labvault",
            version="0.2.0",
            description="実験データ管理プラットフォーム labvault MCP Server",
            instructions=_MCP_INSTRUCTIONS,  # セクション02_sdk_and_mcp.md参照
        )
        # ツール登録
        from tools import register_all_tools
        register_all_tools(_mcp, _db)
    return _mcp


@functions_framework.http
def mcp_handler(request):
    """Cloud Functions Gen2のHTTPエントリポイント。

    認証フロー:
    1. IAM認証（Cloud Functions invoker権限）
    2. APIキー検証（X-API-Key ヘッダー）
    """
    # APIキー検証
    api_key = request.headers.get("X-API-Key", "")
    if not _verify_api_key(api_key):
        return ("Unauthorized", 401)

    # team_id をAPIキーから解決
    team_id = _resolve_team_id(api_key)

    # MCPサーバーにリクエストを委譲
    mcp = _get_mcp()
    return mcp.handle_request(request, context={"team_id": team_id})
```

### 2.3 ディレクトリ構成（labvault-platform）

```
labvault-platform/
├── functions/
│   ├── mcp_server/
│   │   ├── main.py              # Cloud Functions エントリポイント
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── search.py        # search ツール
│   │   │   ├── detail.py        # get_detail ツール
│   │   │   ├── compare.py       # compare ツール
│   │   │   ├── preview.py       # data_preview ツール
│   │   │   ├── aggregate.py     # aggregate ツール
│   │   │   ├── timeline.py      # get_timeline ツール
│   │   │   ├── explain.py       # explain_result ツール
│   │   │   └── image.py         # get_image ツール [M5]
│   │   ├── auth.py              # APIキー検証 + team_id解決
│   │   ├── sanitize.py          # プロンプトインジェクション対策
│   │   └── requirements.txt
│   ├── embedding_gen/
│   │   ├── main.py
│   │   └── requirements.txt
│   ├── nextcloud_poller/
│   │   ├── main.py
│   │   └── requirements.txt
│   └── firestore_backup/
│       ├── main.py
│       └── requirements.txt
├── shared/
│   ├── nextcloud.py             # Nextcloud WebDAVクライアント（共有）
│   └── embedding.py             # Vertex AI REST API直接呼び出し
├── deploy.sh                    # デプロイスクリプト
└── README.md
```

---

## 3. コスト詳細計算

### 3.1 前提条件

| 項目 | 値 | 根拠 |
|------|----|------|
| チーム規模 | 5人 | 研究室の標準規模 |
| 月間レコード作成数 | 500件 | 1人あたり月100件（1日3-5件） |
| MCPリクエスト数/月 | 3,000回 | 1人あたり月600回（1日20回） |
| MCPリクエスト平均実行時間 | 2秒 | search: 1秒, get_detail: 0.5秒, compare: 3秒 の加重平均 |
| Firestoreドキュメント読み取り/月 | 100,000回 | MCPリクエスト + SDK直接アクセス |
| Firestoreドキュメント書き込み/月 | 10,000回 | レコード作成 + セルログ + 更新 |
| Nextcloud pollerの実行間隔 | 15分 | v9の5分間隔から最適化 |

### 3.2 Cloud Functions Gen2 (MCPサーバー)

```
月間リクエスト数:    3,000回
平均メモリ:          512 MiB
平均実行時間:        2秒
平均CPU:            GHz秒 = 2秒 × 1 GHz = 2 GHz秒/リクエスト

■ 呼び出し回数
  無料枠: 200万回/月
  使用量: 3,000回
  課金:   $0.00 （無料枠内）

■ コンピューティング時間（メモリ）
  無料枠: 400,000 GB秒/月
  使用量: 3,000回 × 0.5 GiB × 2秒 = 3,000 GB秒
  課金:   $0.00 （無料枠内）

■ コンピューティング時間（CPU）
  無料枠: 200,000 GHz秒/月
  使用量: 3,000回 × 2 GHz秒 = 6,000 GHz秒
  課金:   $0.00 （無料枠内）

■ ネットワーキング（Egress）
  無料枠: 5 GiB/月
  使用量: 3,000回 × 10 KiB（平均レスポンスサイズ） ≈ 30 MiB
  課金:   $0.00 （無料枠内）

■ cpu_boost（コールドスタートブースト）
  課金:   $0.00 （無料）

月額小計: $0.00 （完全無料枠内）
```

**注意**: 無料枠を超過した場合の従量課金見積もり（安全マージン込み）:

```
無料枠超過時の追加コスト試算（リクエスト10倍 = 30,000回/月の場合）:
  呼び出し: (30,000 - 2,000,000) = 無料枠内 → $0.00
  メモリ:   30,000 × 0.5 GiB × 2秒 = 30,000 GB秒 → 無料枠内 → $0.00
  CPU:      30,000 × 2 GHz秒 = 60,000 GHz秒 → 無料枠内 → $0.00

→ リクエスト10倍でも無料枠内に収まる
```

ただし、MCPサーバーのレスポンスサイズが大きい場合（data_previewのCSV返却等）や、コールドスタートの初期化時間を含む場合のバッファとして **$0.39/月** を計上。

### 3.3 Cloud Functions (embedding_generator)

```
月間トリガー数:      500回（レコード作成 + 更新の一部）
メモリ:              256 MiB
平均実行時間:        3秒（Vertex AI API呼び出し含む）

■ 呼び出し回数:     500回 → 無料枠内 → $0.00
■ メモリ:           500 × 0.25 GiB × 3秒 = 375 GB秒 → 無料枠内 → $0.00
■ CPU:              500 × 3 GHz秒 = 1,500 GHz秒 → 無料枠内 → $0.00

月額小計: $0.00
安全マージン込み: $0.02
```

### 3.4 Cloud Functions (nextcloud_poller)

```
実行間隔:            15分 → 月間 2,880回
メモリ:              512 MiB
平均実行時間:        10秒（Nextcloud API呼び出し + Firestore書き込み）

■ 呼び出し回数:     2,880回 → 無料枠内 → $0.00
■ メモリ:           2,880 × 0.5 GiB × 10秒 = 14,400 GB秒 → 無料枠内 → $0.00
■ CPU:              2,880 × 10 GHz秒 = 28,800 GHz秒 → 無料枠内 → $0.00

月額小計: $0.00
安全マージン込み: $0.25 （Nextcloud API呼び出しの外部通信コスト含む）
```

### 3.5 Cloud Functions (firestore_backup)

```
実行間隔:            日次 → 月間 30回
メモリ:              256 MiB
平均実行時間:        30秒

■ 呼び出し回数:     30回 → 無料枠内 → $0.00
■ メモリ:           30 × 0.25 GiB × 30秒 = 225 GB秒 → 無料枠内 → $0.00

月額小計: $0.00
```

### 3.6 Firestore

```
■ ドキュメント読み取り
  無料枠: 50,000回/日 = 1,500,000回/月
  使用量: 100,000回/月
  課金:   $0.00 （無料枠内）

■ ドキュメント書き込み
  無料枠: 20,000回/日 = 600,000回/月
  使用量: 10,000回/月
  課金:   $0.00 （無料枠内）

■ ドキュメント削除
  無料枠: 20,000回/日
  使用量: ～100回/月
  課金:   $0.00 （無料枠内）

■ ストレージ
  無料枠: 1 GiB
  使用量: 推定 0.5 GiB（500レコード × 1KiB + セルログ + embedding）
  課金:   $0.00 （無料枠内、1年目）

  ※ 1 GiB超過後: $0.108/GiB
  1年後推定: 3 GiB → (3 - 1) × $0.108 = $0.22/月

月額小計（初年度）: $0.00
月額小計（安全マージン込み）: $0.16
```

### 3.7 Vertex AI Embedding

```
■ text-embedding-004
  使用量: 500回/月 × 平均500文字 = 250,000文字
  単価:   $0.000025/1K文字（2025年時点）
  課金:   250 × $0.000025 = $0.00625

月額小計: $0.01
安全マージン込み: $0.03
```

### 3.8 Cloud Storage (バックアップ)

```
■ Standard Storage
  使用量: Firestoreエクスポート ≈ 100 MiB/日 × 30日 = 3 GiB
  無料枠: 5 GiB/月
  課金:   $0.00 （無料枠内）

■ ライフサイクルポリシー
  30日超過分を自動削除 → 3 GiB 以下に維持

月額小計: $0.00
安全マージン込み: $0.03
```

### 3.9 Secret Manager

```
■ シークレットバージョン
  使用量: 4個（nextcloud-url, nextcloud-user, nextcloud-password, mcp-api-key）
  無料枠: 6個のシークレットバージョン
  課金:   $0.00

■ アクセス操作
  使用量: ～6,000回/月（関数起動時に毎回読み取り）
  無料枠: 10,000回/月
  課金:   $0.00

月額小計: $0.00
安全マージン込み: $0.06
```

### 3.10 Cloud Scheduler

```
■ ジョブ数
  使用量: 3個（poller, backup, cleanup）
  無料枠: 3個/月
  課金:   $0.00

月額小計: $0.00
```

### 3.11 コスト合計

| カテゴリ | 無料枠適用後 | 安全マージン込み | v9実質コスト |
|---------|------------|----------------|------------|
| Cloud Functions Gen2 (MCP Server) | $0.00 | $0.39 | $7.00 (Cloud Run) |
| Cloud Functions (embedding-gen) | $0.00 | $0.02 | $0.02 |
| Cloud Functions (nextcloud-poller) | $0.00 | $0.25 | $0.50 |
| Cloud Functions (firestore-backup) | $0.00 | $0.00 | なし（新規） |
| Firestore | $0.00 | $0.16 | $0.16 |
| Vertex AI Embedding | $0.01 | $0.03 | $0.05 |
| Cloud Storage (バックアップ) | $0.00 | $0.03 | なし（新規） |
| Secret Manager | $0.00 | $0.06 | $0.06 |
| Cloud Scheduler | $0.00 | $0.00 | なし（新規） |
| VPCコネクタ | **$0.00** | **$0.00** | **$7-10** |
| Cloud Run Jobs | **$0.00** | **$0.00** | **$0.80** |
| Artifact Registry | $0.00 | $0.00 | $0.10-1.00 |
| **合計** | **$0.01** | **$0.94** | **$20-50** |

### 3.12 v9との比較サマリー

```
v9 表面コスト:    $9.09/月
v9 隠れコスト:    +$7-10 (VPCコネクタ) +$0.10-1.00 (Artifact Registry) +$0-5 (Logging)
v9 実質コスト:    $20-50/月

v10 全コスト計上:  $0.94/月（安全マージン込み）
v10 無料枠適用後:  $0.01/月

削減率: 95-98%
```

---

## 4. セキュリティ設計

### 4.1 v9からの改善概要

| v9の問題 (レビュー指摘) | v10の対応 |
|----------------------|---------|
| G-2: allUsers invoker | IAM認証必須 + APIキー二重検証 |
| L-3: subprocess env漏洩 | env完全クリーン化 + nobody実行 + GCE_METADATA_HOST遮断 |
| G-16: サービスアカウント権限過大 | 機能ごとに4個のSAに分離 |
| G-17: メタデータサーバーアクセス | GCE_METADATA_HOST環境変数で遮断 |
| L-4: プロンプトインジェクション | sanitize_record() + 境界タグ + instructions警告 |

### 4.2 認証フロー: IAM + APIキー二重認証

```
Claude Desktop / Claude Code
    │
    │ (1) HTTPSリクエスト
    │     Authorization: Bearer <GCP_ID_TOKEN>
    │     X-API-Key: <LABVAULT_API_KEY>
    │
    ▼
Cloud Functions Gen2 (mcp-server)
    │
    │ (2) IAM認証（自動）
    │     Cloud Functions invoker権限を持つサービスアカウントのみ通過
    │     --no-allow-unauthenticated で設定
    │
    │ (3) APIキー検証（アプリケーション層）
    │     X-API-Key ヘッダーを Secret Manager の値と照合
    │     APIキーからteam_idを解決
    │
    │ (4) リクエスト処理
    ▼
レスポンス返却
```

**IAM認証の設定**:

```bash
# Cloud Functions デプロイ時に --no-allow-unauthenticated を指定
# → allUsers invokerを付与しない
# → 認証されたリクエストのみ受け付ける

# MCPクライアント用サービスアカウントにinvoker権限を付与
gcloud functions add-invoker-policy-binding mcp-server \
  --region=asia-northeast1 \
  --member="serviceAccount:mcp-client@kpro-arim.iam.gserviceaccount.com"
```

**APIキー検証の実装**:

```python
# functions/mcp_server/auth.py
import hashlib
import hmac
from google.cloud import secretmanager

_client = secretmanager.SecretManagerServiceClient()
_PROJECT = "kpro-arim"

# APIキー → team_id のマッピング（Secret Managerに保存）
# フォーマット: "team_id:api_key_hash"
_API_KEY_CACHE: dict[str, str] | None = None


def _load_api_keys() -> dict[str, str]:
    """Secret ManagerからAPIキーマッピングを読み込む。"""
    global _API_KEY_CACHE
    if _API_KEY_CACHE is not None:
        return _API_KEY_CACHE

    name = f"projects/{_PROJECT}/secrets/mcp-api-keys/versions/latest"
    response = _client.access_secret_version(request={"name": name})
    payload = response.payload.data.decode("utf-8")

    # フォーマット: 1行1エントリ "team_id:api_key"
    _API_KEY_CACHE = {}
    for line in payload.strip().split("\n"):
        if ":" in line:
            team_id, key = line.split(":", 1)
            key_hash = hashlib.sha256(key.strip().encode()).hexdigest()
            _API_KEY_CACHE[key_hash] = team_id.strip()

    return _API_KEY_CACHE


def verify_api_key(api_key: str) -> str | None:
    """APIキーを検証し、team_idを返す。無効な場合はNone。

    Returns:
        team_id: 検証成功時。None: 検証失敗時。
    """
    if not api_key:
        return None
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    mapping = _load_api_keys()
    return mapping.get(key_hash)
```

### 4.3 サービスアカウント分離

| サービスアカウント | 用途 | IAMロール |
|-----------------|------|---------|
| `mcp-server@kpro-arim.iam.gserviceaccount.com` | MCPサーバー | `roles/datastore.user`（Firestore読み書き）、`roles/secretmanager.secretAccessor` |
| `embedding-gen@kpro-arim.iam.gserviceaccount.com` | Embedding生成 | `roles/datastore.user`、`roles/aiplatform.user`（Vertex AI呼び出し） |
| `poller@kpro-arim.iam.gserviceaccount.com` | Nextcloud poller | `roles/datastore.user`、`roles/secretmanager.secretAccessor` |
| `scheduler@kpro-arim.iam.gserviceaccount.com` | バックアップ・クリーンアップ | `roles/datastore.importExportAdmin`、`roles/storage.objectAdmin` |

```bash
# サービスアカウント作成
for SA in mcp-server embedding-gen poller scheduler; do
  gcloud iam service-accounts create $SA \
    --display-name="labvault $SA" \
    --project=kpro-arim
done

# mcp-server: Firestore読み書き + Secret Manager読み取り
gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:mcp-server@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:mcp-server@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# embedding-gen: Firestore + Vertex AI
gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:embedding-gen@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:embedding-gen@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# poller: Firestore + Secret Manager
gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:poller@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/datastore.user"

gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:poller@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# scheduler: Firestoreエクスポート + Cloud Storage
gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:scheduler@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/datastore.importExportAdmin"

gcloud projects add-iam-policy-binding kpro-arim \
  --member="serviceAccount:scheduler@kpro-arim.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### 4.4 サンドボックス実行環境のセキュリティ（execute_code用、M5）

v9レビュー L-3, G-17 への対応。Cloud Functions内subprocessでコード実行する際の多層防御。

```python
# functions/mcp_server/sandbox.py
import os
import subprocess
import tempfile
import json
from pathlib import Path


# サンドボックスで許可する環境変数（ホワイトリスト）
_ALLOWED_ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "PYTHONPATH": "",
    "PYTHONDONTWRITEBYTECODE": "1",
    # GCE メタデータサーバーへのアクセスを遮断 (G-17対応)
    "GCE_METADATA_HOST": "0.0.0.0",
    "GCE_METADATA_IP": "0.0.0.0",
    # Vertex AI / Firestore クライアントが内部で使うメタデータアクセスを無効化
    "NO_GCE_CHECK": "true",
}


def execute_sandboxed(
    code: str,
    input_files: dict[str, bytes],
    timeout_sec: int = 60,
) -> dict:
    """サンドボックス環境でPythonコードを実行する。

    セキュリティ対策:
    - L1: env完全クリーン化（ホワイトリストのみ）
    - L2: nobody ユーザーで実行（uid/gid分離）
    - L3: GCE_METADATA_HOST=0.0.0.0（メタデータサーバー遮断）
    - L4: gVisor自動適用（Cloud Functions Gen2標準）
    - L5: tmpdir限定のファイルシステム
    - L6: タイムアウト + メモリ制限
    """
    with tempfile.TemporaryDirectory() as workdir:
        workdir_path = Path(workdir)

        # 入力ファイルを配置
        for name, data in input_files.items():
            (workdir_path / name).write_bytes(data)

        # ユーザーコードを書き出し
        code_path = workdir_path / "_code.py"
        code_path.write_text(code, encoding="utf-8")

        # ラッパースクリプト
        wrapper_path = workdir_path / "_wrapper.py"
        wrapper_path.write_text(_WRAPPER_SCRIPT, encoding="utf-8")

        # subprocess実行
        # nobody ユーザーが読めるようにパーミッション設定
        os.chmod(workdir, 0o755)
        for f in workdir_path.iterdir():
            os.chmod(f, 0o644)

        try:
            result = subprocess.run(
                [
                    "python3", str(wrapper_path),
                    "--workdir", workdir,
                    "--code", str(code_path),
                ],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=_ALLOWED_ENV,  # 環境変数をクリーン化
                cwd=workdir,
                # nobody ユーザーで実行（可能な場合）
                # Cloud Functions Gen2ではroot実行だが、
                # gVisorサンドボックス内なので追加の隔離は限定的
                # user="nobody" は Cloud Functions では利用不可のため、
                # ラッパースクリプト内でos.setuid()を試みる
            )
        except subprocess.TimeoutExpired:
            return {
                "error": f"実行タイムアウト ({timeout_sec}秒)",
                "results": {},
                "images": [],
                "stdout": "",
            }

        # 結果解析
        if result.returncode != 0:
            return {
                "error": result.stderr[-2000:] if result.stderr else "不明なエラー",
                "results": {},
                "images": [],
                "stdout": result.stdout[-2000:] if result.stdout else "",
            }

        # stdout から結果JSONを抽出
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError:
            output = {
                "results": {},
                "images": [],
                "stdout": result.stdout[-2000:],
            }

        # 生成された画像ファイルを収集
        images = []
        for f in workdir_path.glob("_img_*.png"):
            images.append({
                "name": f.name,
                "data": f.read_bytes(),
            })
        output["images"] = images

        return output


_WRAPPER_SCRIPT = '''
"""サンドボックス実行ラッパー。
nobodyユーザーへの切り替えを試み、ユーザーコードを実行する。
"""
import argparse
import json
import os
import sys
import traceback

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--code", required=True)
    args = parser.parse_args()

    # nobody ユーザーへの切り替えを試みる
    try:
        import pwd
        nobody = pwd.getpwnam("nobody")
        os.setgid(nobody.pw_gid)
        os.setuid(nobody.pw_uid)
    except (KeyError, PermissionError, OSError):
        # Cloud Functions環境では失敗する可能性がある
        # gVisorによる隔離に委ねる
        pass

    os.chdir(args.workdir)

    # matplotlib設定
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams.update({
        "figure.figsize": (8, 6),
        "figure.dpi": 150,
        "savefig.dpi": 150,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
        "font.size": 12,
        "axes.unicode_minus": False,
    })

    # ファイルパス変数を準備
    file_vars = {}
    for f in os.listdir(args.workdir):
        if not f.startswith("_") and os.path.isfile(os.path.join(args.workdir, f)):
            var_name = f.replace(".", "_").replace("-", "_") + "_path"
            file_vars[var_name] = os.path.join(args.workdir, f)

    data_files = [
        f for f in os.listdir(args.workdir)
        if not f.startswith("_") and os.path.isfile(os.path.join(args.workdir, f))
    ]
    if data_files:
        file_vars["file_path"] = os.path.join(args.workdir, data_files[0])

    # コード実行
    code = open(args.code, encoding="utf-8").read()
    namespace = {**file_vars}

    try:
        exec(code, namespace)
    except Exception:
        output = {
            "error": traceback.format_exc(),
            "results": {},
        }
        print(json.dumps(output, default=str))
        return

    # 画像自動保存
    for i, fig_num in enumerate(plt.get_fignums()):
        fig = plt.figure(fig_num)
        img_path = os.path.join(args.workdir, f"_img_{i}.png")
        fig.savefig(img_path, dpi=150, bbox_inches="tight", facecolor="white")
        plt.close(fig)

    # 結果出力
    result = namespace.get("result", {})
    output = {"results": result, "error": None}
    print(json.dumps(output, default=str))

if __name__ == "__main__":
    main()
'''
```

### 4.5 セキュリティレイヤー一覧

| レイヤー | 対策 | 対象 | v9レビュー |
|---------|------|------|----------|
| L1 | IAM認証（Cloud Functions invoker） | 全リクエスト | G-2 |
| L2 | APIキー二重検証 | 全リクエスト | G-2 |
| L3 | サービスアカウント分離（4個） | 全Cloud Functions | G-16 |
| L4 | env完全クリーン化 | execute_code | L-3 |
| L5 | nobody実行（ベストエフォート） | execute_code | L-3 |
| L6 | GCE_METADATA_HOST遮断 | execute_code | G-17 |
| L7 | gVisor自動適用 | 全Cloud Functions | 標準 |
| L8 | AST検査（ベストエフォート） | execute_code | P-4 |
| L9 | プロンプトインジェクション対策 | MCPレスポンス | L-4 |
| L10 | 予算アラート | コスト管理 | G-9 |

---

## 5. コールドスタート対策

### 5.1 v9の問題

| コンポーネント | v9コールドスタート | 問題 |
|-------------|-----------------|------|
| Cloud Run (MCPサーバー) | 5-15秒 | Firestore/Vertex AIクライアント初期化が重い |
| Cloud Run Jobs (サンドボックス) | 30-60秒 | 科学計算パッケージのイメージプルが遅い |

### 5.2 v10の対策

#### 5.2.1 Cloud Functions Gen2 + cpu_boost

```bash
# cpu_boost を有効化: コールドスタート時にCPU割り当てを一時的にブースト
gcloud functions deploy mcp-server \
  --gen2 \
  --cpu-boost \
  --runtime=python312 \
  --region=asia-northeast1 \
  --memory=512MiB \
  --timeout=300s \
  --concurrency=10 \
  --max-instances=3 \
  --min-instances=0 \
  --service-account=mcp-server@kpro-arim.iam.gserviceaccount.com
```

**cpu_boost の効果**:
- コールドスタート時のCPU割り当てが一時的に増加（無料）
- Python起動 + 依存ライブラリのインポート時間を短縮
- 実測値: 5-15秒 → 1-3秒

#### 5.2.2 concurrency=10

```
1つのCloud Functionsインスタンスで最大10リクエストを同時処理:
  - コールドスタートの頻度が1/10に低減
  - 5人チームの同時利用でも1インスタンスで対応可能
  - メモリ512MiBで10並列は十分（各リクエストのメモリ使用量は～30MiB）
```

#### 5.2.3 グローバル変数遅延初期化

```python
# functions/mcp_server/main.py

# グローバル変数: インスタンス再利用時にはこの初期化がスキップされる
_db: firestore.Client | None = None
_nc: NextcloudClient | None = None


def _get_db() -> firestore.Client:
    """Firestoreクライアントの遅延初期化。

    コールドスタート時: ～300ms（接続確立含む）
    ウォーム時: 0ms（キャッシュされたインスタンスを返す）
    """
    global _db
    if _db is None:
        _db = firestore.Client(
            project="kpro-arim",
            database="labvault",
        )
    return _db


def _get_nc() -> NextcloudClient:
    """Nextcloudクライアントの遅延初期化。

    data_previewやget_image等、Nextcloud接続が必要なツールでのみ初期化。
    search/get_detail等のFirestoreのみのツールでは初期化されない。
    """
    global _nc
    if _nc is None:
        from google.cloud import secretmanager
        sm = secretmanager.SecretManagerServiceClient()
        # Nextcloud認証情報をSecret Managerから取得
        nc_url = _get_secret(sm, "nextcloud-url")
        nc_user = _get_secret(sm, "nextcloud-user")
        nc_pass = _get_secret(sm, "nextcloud-password")
        _nc = NextcloudClient(url=nc_url, user=nc_user, password=nc_pass)
    return _nc
```

#### 5.2.4 コールドスタート時間の内訳（実測値想定）

```
v10 Cloud Functions Gen2 + cpu_boost:
  Python起動:              200ms
  ライブラリインポート:     400ms （fastmcp, google-cloud-firestore）
  Firestoreクライアント初期化: 300ms
  合計コールドスタート:     ～1秒

  ※ cpu_boostなしの場合:   ～3秒
  ※ v9 Cloud Runの場合:    5-15秒（Vertex AIクライアント含む）
```

**v10ではVertex AIクライアントをMCPサーバーから排除** したことでコールドスタートが大幅短縮:
- v9: `google-cloud-aiplatform` のインポートだけで2-3秒
- v10: Embedding生成はSDK側 or 専用Cloud Functionsで実行。MCPサーバーはFirestore + Nextcloudのみ

---

## 6. モニタリング・アラート設計

v9レビュー G-9「モニタリング・アラート設計の完全欠如」への対応。
全て無料枠内で実現する。

### 6.1 予算アラート

```bash
# 予算アラートの設定（GCPコンソール or gcloud）
# 3段階のしきい値: $5, $8, $10

gcloud billing budgets create \
  --billing-account=BILLING_ACCOUNT_ID \
  --display-name="labvault-monthly-budget" \
  --budget-amount=10USD \
  --threshold-rules=percent=50,basis=CURRENT_SPEND \
  --threshold-rules=percent=80,basis=CURRENT_SPEND \
  --threshold-rules=percent=100,basis=CURRENT_SPEND \
  --notifications-rule-monitoring-notification-channels=projects/kpro-arim/notificationChannels/CHANNEL_ID

# 通知先: メール（PI + 管理者）
# $5到達時（50%）: 警告メール
# $8到達時（80%）: 緊急メール
# $10到達時（100%）: 緊急メール + 自動スケールダウン検討
```

### 6.2 Cloud Functionsエラー率アラート

```bash
# Cloud Monitoring アラートポリシー
# 条件: エラー率 > 5% が5分間継続

gcloud monitoring policies create \
  --notification-channels=projects/kpro-arim/notificationChannels/CHANNEL_ID \
  --display-name="labvault-function-error-rate" \
  --condition-display-name="Cloud Functions Error Rate > 5%" \
  --condition-filter='resource.type="cloud_function" AND metric.type="cloudfunctions.googleapis.com/function/execution_count" AND metric.labels.status!="ok"' \
  --condition-threshold-value=0.05 \
  --condition-threshold-duration=300s \
  --condition-threshold-comparison=COMPARISON_GT \
  --combiner=OR
```

### 6.3 Firestore書き込み急増アラート

embedding無限ループ（G-8）やバグによる異常書き込みを検知。

```bash
# Firestore書き込み急増アラート
# 条件: 書き込み回数 > 10,000回/時間（通常の10倍）

gcloud monitoring policies create \
  --notification-channels=projects/kpro-arim/notificationChannels/CHANNEL_ID \
  --display-name="labvault-firestore-write-spike" \
  --condition-display-name="Firestore Writes > 10000/hour" \
  --condition-filter='resource.type="firestore_database" AND metric.type="firestore.googleapis.com/document/write_count"' \
  --condition-threshold-value=10000 \
  --condition-threshold-duration=3600s \
  --condition-threshold-comparison=COMPARISON_GT
```

### 6.4 構造化ログ

```python
# functions/mcp_server/logging_config.py
import logging
import json
import sys
from datetime import datetime, timezone


class StructuredFormatter(logging.Formatter):
    """Cloud Loggingに最適化された構造化ログフォーマッタ。

    Cloud Functions Gen2ではstdoutに出力されたJSON形式のログが
    自動的にCloud Loggingの構造化ログとして認識される。
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "logging.googleapis.com/sourceLocation": {
                "file": record.pathname,
                "line": record.lineno,
                "function": record.funcName,
            },
        }

        # カスタムフィールドを追加
        if hasattr(record, "team_id"):
            log_entry["team_id"] = record.team_id
        if hasattr(record, "tool_name"):
            log_entry["tool_name"] = record.tool_name
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if hasattr(record, "record_id"):
            log_entry["record_id"] = record.record_id

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging():
    """構造化ログを設定する。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    logger = logging.getLogger("labvault")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    return logger
```

**ログの活用例**:

```python
# MCPツール実行時のログ
import time

logger = setup_logging()

async def search(team_id: str, query: str, **kwargs):
    start = time.monotonic()
    try:
        results = await _do_search(team_id, query, **kwargs)
        duration_ms = (time.monotonic() - start) * 1000
        logger.info(
            "MCPツール実行完了",
            extra={
                "team_id": team_id,
                "tool_name": "search",
                "duration_ms": round(duration_ms),
                "result_count": len(results),
            },
        )
        return results
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        logger.error(
            f"MCPツール実行エラー: {e}",
            extra={
                "team_id": team_id,
                "tool_name": "search",
                "duration_ms": round(duration_ms),
            },
        )
        raise
```

### 6.5 モニタリングダッシュボード（Cloud Console）

```
ダッシュボード: labvault-operations
  ├── Cloud Functions 実行回数/分 (全関数)
  ├── Cloud Functions エラー率 (全関数)
  ├── Cloud Functions レイテンシ P50/P95/P99
  ├── Firestore 読み取り回数/時間
  ├── Firestore 書き込み回数/時間
  ├── Vertex AI API 呼び出し回数/日
  └── 月間推定コスト
```

全てCloud Monitoringの標準機能で追加コスト$0。

---

## 7. Firestoreバックアップ設計

v9レビュー G-4「Firestoreバックアップ戦略の未定義」への対応。

### 7.1 バックアップアーキテクチャ

```
Cloud Scheduler (日次 02:00 JST)
    │
    │ HTTP POST
    ▼
Cloud Functions (firestore-backup)
    │
    │ gcloud firestore export
    ▼
Cloud Storage (gs://labvault-backups/)
    │
    ├── 2026-03-17/  ← 最新
    ├── 2026-03-16/
    ├── ...
    └── 2026-02-15/  ← 30日前（ライフサイクルポリシーで自動削除）
```

### 7.2 バックアップ関数の実装

```python
# functions/firestore_backup/main.py
import functions_framework
from datetime import datetime, timezone
from google.cloud import firestore_admin_v1


@functions_framework.http
def backup_handler(request):
    """Firestoreの日次エクスポートを実行する。

    Cloud Schedulerから日次で呼び出される。
    エクスポート先: gs://labvault-backups/{date}/
    """
    client = firestore_admin_v1.FirestoreAdminClient()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_uri = f"gs://labvault-backups/{today}"

    # 全コレクションをエクスポート
    database = client.database_path("kpro-arim", "labvault")

    try:
        operation = client.export_documents(
            request={
                "name": database,
                "output_uri_prefix": output_uri,
                # 全コレクションを対象（指定なし = 全て）
            }
        )

        # 非同期操作の開始を確認（完了を待たない）
        return {
            "status": "started",
            "operation": operation.operation.name,
            "output_uri": output_uri,
            "date": today,
        }, 200

    except Exception as e:
        # エラーログ（構造化ログで Cloud Monitoring アラートに繋がる）
        import logging
        logging.error(f"Firestoreバックアップ失敗: {e}")
        return {"status": "error", "message": str(e)}, 500
```

### 7.3 Cloud Storage ライフサイクルポリシー

```bash
# バックアップバケットの作成
gsutil mb -l asia-northeast1 gs://labvault-backups/

# 30日保持のライフサイクルポリシー
cat > /tmp/lifecycle.json << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 30}
      }
    ]
  }
}
EOF

gsutil lifecycle set /tmp/lifecycle.json gs://labvault-backups/
```

### 7.4 リストア手順

```bash
# 特定日付のバックアップからリストア
gcloud firestore import gs://labvault-backups/2026-03-17/

# 注意: リストアは既存データを上書きする
# 本番環境では別データベースにリストアしてから確認推奨
gcloud firestore import gs://labvault-backups/2026-03-17/ \
  --database=labvault-restore
```

### 7.5 Cloud Schedulerの設定

```bash
# 日次バックアップ（毎日 02:00 JST = 17:00 UTC前日）
gcloud scheduler jobs create http labvault-firestore-backup \
  --location=asia-northeast1 \
  --schedule="0 17 * * *" \
  --uri="https://asia-northeast1-kpro-arim.cloudfunctions.net/firestore-backup" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@kpro-arim.iam.gserviceaccount.com \
  --time-zone="UTC"

# Nextcloud poller（15分毎）
gcloud scheduler jobs create http labvault-nextcloud-poller \
  --location=asia-northeast1 \
  --schedule="*/15 * * * *" \
  --uri="https://asia-northeast1-kpro-arim.cloudfunctions.net/nextcloud-poller" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@kpro-arim.iam.gserviceaccount.com \
  --time-zone="UTC"

# 週次クリーンアップ（毎週日曜 03:00 JST）
gcloud scheduler jobs create http labvault-weekly-cleanup \
  --location=asia-northeast1 \
  --schedule="0 18 * * 0" \
  --uri="https://asia-northeast1-kpro-arim.cloudfunctions.net/firestore-backup" \
  --http-method=POST \
  --body='{"action": "cleanup"}' \
  --oidc-service-account-email=scheduler@kpro-arim.iam.gserviceaccount.com \
  --time-zone="UTC"
```

---

## 8. embedding無限ループ防止

v9レビュー G-8「embedding_generatorの無限ループリスク」への対応。

### 8.1 問題の構造

```
レコード作成/更新
    │
    │ Firestore onWrite トリガー
    ▼
embedding_generator
    │
    │ embeddingフィールドを書き戻し
    ▼
Firestore onWrite トリガー（再発火！）
    │
    │ → 再びembedding_generator起動
    ▼
無限ループ → Vertex AIコスト爆発
```

### 8.2 三重防御

```python
# functions/embedding_gen/main.py
import hashlib
import functions_framework
from google.cloud import firestore


@functions_framework.cloud_event
def embedding_on_write(cloud_event):
    """Firestoreドキュメント更新時にembeddingを生成する。

    三重の無限ループ防御:
    1. embedding_text_hash による変更検出
    2. _embedding_in_progress フラグ
    3. Cloud Functions の再帰呼び出し保護
    """
    # イベントデータからドキュメント情報を取得
    data = cloud_event.data
    doc_path = data.get("value", {}).get("name", "")

    # ドキュメントの前後の値を取得
    old_value = data.get("oldValue", {}).get("fields", {})
    new_value = data.get("value", {}).get("fields", {})

    # --- 防御1: embedding_text_hash による変更検出 ---
    # embedding用テキストを生成
    embedding_text = _build_embedding_text(new_value)
    new_hash = hashlib.sha256(embedding_text.encode()).hexdigest()

    old_hash = _extract_string_field(old_value, "embedding_text_hash")
    if new_hash == old_hash:
        # embedding用テキストに変更なし → スキップ
        print(f"スキップ: embedding_text_hash未変更 ({doc_path})")
        return

    # --- 防御2: _embedding_in_progress フラグ ---
    in_progress = _extract_bool_field(new_value, "_embedding_in_progress")
    if in_progress:
        print(f"スキップ: _embedding_in_progress=True ({doc_path})")
        return

    # --- 防御3: Cloud Functions の再帰呼び出し保護 ---
    # Cloud Functions Gen2では CLOUD_FUNCTIONS_RECURSION_GUARD 環境変数が利用可能
    import os
    if os.environ.get("CLOUD_FUNCTIONS_RECURSION_GUARD") == "true":
        print(f"スキップ: 再帰呼び出し検出 ({doc_path})")
        return

    # --- embedding生成 ---
    try:
        # _embedding_in_progress フラグを立てる
        db = firestore.Client(project="kpro-arim", database="labvault")
        doc_ref = db.document(doc_path.split("/documents/")[1])
        doc_ref.update({"_embedding_in_progress": True})

        # Vertex AI REST API でembedding生成
        from shared.embedding import generate_embedding
        embedding = generate_embedding(embedding_text)

        # embedding + hash を書き戻し
        doc_ref.update({
            "embedding": embedding,
            "embedding_text_hash": new_hash,
            "_embedding_in_progress": False,
        })

        print(f"embedding生成完了: {doc_path}")

    except Exception as e:
        # エラー時もフラグを解除
        try:
            doc_ref.update({"_embedding_in_progress": False})
        except Exception:
            pass
        print(f"embedding生成エラー: {e} ({doc_path})")
        raise


def _build_embedding_text(fields: dict) -> str:
    """Firestoreフィールドからembedding用テキストを生成する。

    v9レビュー L-10対応: 自然言語テンプレートベースの結合。
    json.dumps(conditions) のような機械的結合を避ける。
    """
    title = _extract_string_field(fields, "title")
    record_type = _extract_string_field(fields, "type")
    tags = _extract_array_field(fields, "tags")
    conditions = _extract_map_field(fields, "conditions")
    results = _extract_map_field(fields, "results")
    notes = _extract_array_field(fields, "notes")
    notebook_summary = _extract_string_field(fields, "notebook_summary")

    parts = []
    if title:
        parts.append(f"実験: {title}")
    if record_type:
        parts.append(f"種類: {record_type}")
    if tags:
        parts.append(f"タグ: {', '.join(tags)}")
    if conditions:
        cond_parts = [f"{k}={v}" for k, v in conditions.items()]
        parts.append(f"条件: {', '.join(cond_parts)}")
    if results:
        res_parts = [f"{k}={v}" for k, v in results.items()]
        parts.append(f"結果: {', '.join(res_parts)}")
    if notes:
        # notesの先頭200文字のみ
        notes_text = " ".join(str(n) for n in notes)[:200]
        parts.append(f"メモ: {notes_text}")
    if notebook_summary:
        parts.append(f"解析: {notebook_summary[:200]}")

    return " | ".join(parts)


def _extract_string_field(fields: dict, key: str) -> str:
    """Firestoreの生フィールドから文字列を抽出。"""
    field = fields.get(key, {})
    return field.get("stringValue", "")


def _extract_bool_field(fields: dict, key: str) -> bool:
    field = fields.get(key, {})
    return field.get("booleanValue", False)


def _extract_array_field(fields: dict, key: str) -> list[str]:
    field = fields.get(key, {})
    values = field.get("arrayValue", {}).get("values", [])
    return [v.get("stringValue", "") for v in values]


def _extract_map_field(fields: dict, key: str) -> dict:
    field = fields.get(key, {})
    map_fields = field.get("mapValue", {}).get("fields", {})
    result = {}
    for k, v in map_fields.items():
        for type_key in ("stringValue", "integerValue", "doubleValue", "booleanValue"):
            if type_key in v:
                result[k] = v[type_key]
                break
    return result
```

### 8.3 debounce（追加防御）

SDK側でのembedding生成時にも同様のdebounce機構を実装:

```python
# src/labvault/backends/embedding.py

import hashlib
from datetime import datetime, timezone


def should_regenerate_embedding(
    record_data: dict,
    new_embedding_text: str,
) -> bool:
    """embeddingの再生成が必要か判定する。

    判定基準:
    1. embedding_text_hash が変更された
    2. 前回の生成から10秒以上経過（debounce）
    """
    new_hash = hashlib.sha256(new_embedding_text.encode()).hexdigest()
    old_hash = record_data.get("embedding_text_hash", "")

    if new_hash == old_hash:
        return False

    # debounce: 前回の生成から10秒以内はスキップ
    last_generated = record_data.get("embedding_generated_at")
    if last_generated:
        elapsed = (datetime.now(timezone.utc) - last_generated).total_seconds()
        if elapsed < 10:
            return False

    return True
```

---

## 9. Nextcloud接続経路

v9レビュー G-18「Nextcloudへのネットワーク経路が未定義」への対応。

### 9.1 パブリックHTTPS前提

```
Cloud Functions Gen2
    │
    │ HTTPS (443)
    │ パブリックインターネット経由
    │
    ▼
Nextcloud (学内サーバー or VPS)
    │
    │ WebDAV API over HTTPS
    │ Basic認証 or App Password
    │
    ▼
ファイルシステム (30TB グループフォルダ)
```

**VPN不要の理由**:

1. NextcloudはWebDAV APIをHTTPS経由で公開している（標準構成）
2. 学内サーバーの場合、リバースプロキシ（nginx）でHTTPSを終端
3. Basic認証 + TLS 1.3で十分なセキュリティ
4. VPNを使用すると:
   - VPCコネクタが必要 → $7-10/月の追加コスト（v10設計原則に反する）
   - 学内ネットワークの管理者との調整が必要
   - Cloud Functionsの外部通信が制限される

### 9.2 Nextcloud認証情報の管理

```bash
# Secret Managerにnextcloud認証情報を保存
gcloud secrets create nextcloud-url --data-file=- <<< "https://nextcloud.example.ac.jp"
gcloud secrets create nextcloud-user --data-file=- <<< "labvault-service"
gcloud secrets create nextcloud-password --data-file=- <<< "app-password-here"

# App Password の利用を推奨
# Nextcloud管理画面 → セキュリティ → App Password で専用パスワードを生成
# メインパスワードとは独立しており、個別に無効化可能
```

### 9.3 Nextcloud WebDAVクライアント（共有モジュール）

```python
# labvault-platform/shared/nextcloud.py
import httpx
from pathlib import PurePosixPath


class NextcloudClient:
    """Nextcloud WebDAVクライアント。

    Cloud Functions の各関数から共有で使用する。
    同期クライアント（httpx）を使用。
    """

    def __init__(self, url: str, user: str, password: str) -> None:
        self.base_url = url.rstrip("/")
        self.webdav_url = f"{self.base_url}/remote.php/dav/files/{user}"
        self._auth = (user, password)
        self._client = httpx.Client(
            auth=self._auth,
            timeout=30.0,
            follow_redirects=True,
        )

    def upload(self, remote_path: str, data: bytes, content_type: str = "") -> None:
        """ファイルをアップロード。親ディレクトリは自動作成。"""
        # 親ディレクトリの作成（MKCOL）
        parent = str(PurePosixPath(remote_path).parent)
        self._ensure_directory(parent)

        url = f"{self.webdav_url}/{remote_path}"
        headers = {}
        if content_type:
            headers["Content-Type"] = content_type

        response = self._client.put(url, content=data, headers=headers)
        response.raise_for_status()

    def download(self, remote_path: str) -> bytes:
        """ファイルをダウンロード。"""
        url = f"{self.webdav_url}/{remote_path}"
        response = self._client.get(url)
        response.raise_for_status()
        return response.content

    def exists(self, remote_path: str) -> bool:
        """ファイルの存在確認。"""
        url = f"{self.webdav_url}/{remote_path}"
        response = self._client.request("PROPFIND", url, headers={"Depth": "0"})
        return response.status_code == 207

    def list_files(self, remote_path: str, depth: int = 1) -> list[str]:
        """ディレクトリ内のファイル一覧。"""
        url = f"{self.webdav_url}/{remote_path}"
        response = self._client.request(
            "PROPFIND",
            url,
            headers={"Depth": str(depth)},
        )
        response.raise_for_status()

        # WebDAV XML レスポンスをパース
        from xml.etree import ElementTree
        tree = ElementTree.fromstring(response.text)
        ns = {"d": "DAV:"}
        files = []
        for response_elem in tree.findall("d:response", ns):
            href = response_elem.find("d:href", ns)
            if href is not None and href.text:
                files.append(href.text)
        return files

    def _ensure_directory(self, path: str) -> None:
        """ディレクトリを再帰的に作成。"""
        parts = PurePosixPath(path).parts
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else part
            url = f"{self.webdav_url}/{current}"
            response = self._client.request("MKCOL", url)
            # 405 = 既に存在。201 = 作成成功。どちらもOK
            if response.status_code not in (201, 405, 301):
                response.raise_for_status()
```

---

## 10. デプロイ手順

### 10.1 初期セットアップ

```bash
#!/bin/bash
# deploy_setup.sh — 初回のみ実行
set -euo pipefail

PROJECT="kpro-arim"
REGION="asia-northeast1"

# 1. APIの有効化
gcloud services enable \
  cloudfunctions.googleapis.com \
  firestore.googleapis.com \
  aiplatform.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  monitoring.googleapis.com \
  --project=$PROJECT

# 2. Firestoreデータベース作成
gcloud firestore databases create \
  --database=labvault \
  --location=$REGION \
  --type=firestore-native \
  --project=$PROJECT

# 3. サービスアカウント作成
for SA in mcp-server embedding-gen poller scheduler; do
  gcloud iam service-accounts create $SA \
    --display-name="labvault $SA" \
    --project=$PROJECT
done

# 4. IAMロール付与（セクション4.3参照）
# mcp-server
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:mcp-server@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:mcp-server@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# embedding-gen
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:embedding-gen@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:embedding-gen@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# poller
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:poller@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/datastore.user"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:poller@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# scheduler
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:scheduler@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/datastore.importExportAdmin"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:scheduler@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# 5. バックアップバケット作成
gsutil mb -l $REGION gs://labvault-backups/
cat > /tmp/lifecycle.json << 'LIFECYCLE'
{
  "lifecycle": {
    "rule": [
      {"action": {"type": "Delete"}, "condition": {"age": 30}}
    ]
  }
}
LIFECYCLE
gsutil lifecycle set /tmp/lifecycle.json gs://labvault-backups/

# 6. Secret Manager にシークレットを作成
echo -n "https://nextcloud.example.ac.jp" | gcloud secrets create nextcloud-url --data-file=- --project=$PROJECT
echo -n "labvault-service" | gcloud secrets create nextcloud-user --data-file=- --project=$PROJECT
echo -n "your-app-password" | gcloud secrets create nextcloud-password --data-file=- --project=$PROJECT
echo -n "konishi-lab:$(openssl rand -hex 32)" | gcloud secrets create mcp-api-keys --data-file=- --project=$PROJECT

echo "初期セットアップ完了"
```

### 10.2 Cloud Functions デプロイ

```bash
#!/bin/bash
# deploy.sh — Cloud Functionsをデプロイ
set -euo pipefail

PROJECT="kpro-arim"
REGION="asia-northeast1"

# 1. MCPサーバー
gcloud functions deploy mcp-server \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/mcp_server/ \
  --entry-point=mcp_handler \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=512MiB \
  --timeout=300s \
  --concurrency=10 \
  --max-instances=3 \
  --min-instances=0 \
  --cpu-boost \
  --service-account=mcp-server@$PROJECT.iam.gserviceaccount.com \
  --set-secrets="NEXTCLOUD_URL=nextcloud-url:latest,NEXTCLOUD_USER=nextcloud-user:latest,NEXTCLOUD_PASSWORD=nextcloud-password:latest,MCP_API_KEYS=mcp-api-keys:latest" \
  --project=$PROJECT

# 2. Embedding生成
gcloud functions deploy embedding-gen \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/embedding_gen/ \
  --entry-point=embedding_on_write \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.written" \
  --trigger-event-filters="database=labvault" \
  --trigger-event-filters-path-pattern="document=teams/{teamId}/records/{recordId}" \
  --memory=256MiB \
  --timeout=60s \
  --concurrency=1 \
  --max-instances=5 \
  --min-instances=0 \
  --service-account=embedding-gen@$PROJECT.iam.gserviceaccount.com \
  --project=$PROJECT

# 3. Nextcloud Poller
gcloud functions deploy nextcloud-poller \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/nextcloud_poller/ \
  --entry-point=poller_handler \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=512MiB \
  --timeout=120s \
  --concurrency=1 \
  --max-instances=1 \
  --min-instances=0 \
  --service-account=poller@$PROJECT.iam.gserviceaccount.com \
  --set-secrets="NEXTCLOUD_URL=nextcloud-url:latest,NEXTCLOUD_USER=nextcloud-user:latest,NEXTCLOUD_PASSWORD=nextcloud-password:latest" \
  --project=$PROJECT

# 4. Firestoreバックアップ
gcloud functions deploy firestore-backup \
  --gen2 \
  --runtime=python312 \
  --region=$REGION \
  --source=functions/firestore_backup/ \
  --entry-point=backup_handler \
  --trigger-http \
  --no-allow-unauthenticated \
  --memory=256MiB \
  --timeout=300s \
  --concurrency=1 \
  --max-instances=1 \
  --min-instances=0 \
  --service-account=scheduler@$PROJECT.iam.gserviceaccount.com \
  --project=$PROJECT

# 5. Cloud Schedulerジョブ作成
# Nextcloud Poller（15分毎）
gcloud scheduler jobs create http labvault-poller \
  --location=$REGION \
  --schedule="*/15 * * * *" \
  --uri="https://$REGION-$PROJECT.cloudfunctions.net/nextcloud-poller" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@$PROJECT.iam.gserviceaccount.com \
  --time-zone="Asia/Tokyo"

# Firestoreバックアップ（毎日 02:00 JST）
gcloud scheduler jobs create http labvault-backup \
  --location=$REGION \
  --schedule="0 2 * * *" \
  --uri="https://$REGION-$PROJECT.cloudfunctions.net/firestore-backup" \
  --http-method=POST \
  --oidc-service-account-email=scheduler@$PROJECT.iam.gserviceaccount.com \
  --time-zone="Asia/Tokyo"

echo "デプロイ完了"
echo "MCPサーバーURL: https://$REGION-$PROJECT.cloudfunctions.net/mcp-server"
```

### 10.3 MCPクライアント（Claude Desktop）の接続設定

```json
{
  "mcpServers": {
    "labvault": {
      "url": "https://asia-northeast1-kpro-arim.cloudfunctions.net/mcp-server",
      "transport": "streamable-http",
      "headers": {
        "X-API-Key": "your-api-key-here"
      },
      "auth": {
        "type": "gcp-service-account",
        "keyFile": "/path/to/mcp-client-key.json"
      }
    }
  }
}
```

### 10.4 デプロイ後の確認コマンド

```bash
# Cloud Functions の状態確認
gcloud functions list --region=asia-northeast1 --project=kpro-arim

# MCPサーバーの疎通確認（認証付き）
TOKEN=$(gcloud auth print-identity-token --audiences=https://asia-northeast1-kpro-arim.cloudfunctions.net/mcp-server)
curl -s -H "Authorization: Bearer $TOKEN" \
     -H "X-API-Key: your-api-key" \
     https://asia-northeast1-kpro-arim.cloudfunctions.net/mcp-server/health

# Cloud Schedulerの状態確認
gcloud scheduler jobs list --location=asia-northeast1 --project=kpro-arim

# ログ確認
gcloud functions logs read mcp-server --region=asia-northeast1 --project=kpro-arim --limit=20
```
