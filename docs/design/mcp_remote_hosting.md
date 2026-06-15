# MCP リモートホスティング設計

`labvault mcp` (現状はローカル stdio) を Cloud Run 上にホストし、PAT 認証で
Claude Desktop / Code から直接利用できるようにする提案。

## 背景

現状の MCP 導入手順:

1. `pip install labvault[all]` (Python 3.11+ が必要)
2. `labvault auth set-token` で `~/.labvault/credentials` を作る
3. Claude Desktop / Code の MCP 設定で `command: labvault mcp` を登録
4. SDK を更新したら各端末で `pip install -U labvault`

非エンジニアのラボメンバーがハマるのはほぼ 1 と 3。リモートにすると:

1. Web UI で PAT を発行
2. Claude に URL + PAT を貼る

の 2 ステップで済み、SDK バージョン管理も不要になる。

## ゴール / 非ゴール

**ゴール**

- `platform/backend` (Cloud Run) に MCP Streamable HTTP エンドポイントを mount
- PAT 認証 (`current_authenticated_user` を流用)
- 既存の 7 ツールをそのまま remote 経由でも動かす
- ローカル `labvault mcp` も並存させる (装置 PC や CI で生 Lab を触りたいケース)

**非ゴール**

- 新ツールの追加 (別議論)
- MCP プロトコル機能 (resources / prompts) の有効化
- 多人数同時セッションのスケーリング最適化 (ラボ規模で不要)

## アーキテクチャ

```
Claude Desktop / Code
        │  HTTP (POST /mcp, Authorization: Bearer lv_*)
        ▼
Cloud Run (asia-northeast1)
  platform/backend FastAPI
    ├─ /api/...      (既存 REST)
    ├─ /api/pypi/... (既存 PyPI proxy)
    └─ /mcp          (← 新規。FastMCP Streamable HTTP)
                        │
                        ▼
                  labvault SDK (Lab) → Firestore / Nextcloud
```

ポイントは「**既存の Cloud Run サービスに mount するだけ**」で済むこと。
新しい service を立てない:

- PAT 検証は `app/auth.py` の `_verify_pat()` をそのまま使う
- Lab シングルトンは `app/dependencies.py` (PAT 経由 `PlatformMetadataBackend`)
  と同じ機構で組む
- 単一 Cloud Run service なので CORS / IAM / ドメイン設定が増えない

## 認証

### Bearer ヘッダ

クライアント (Claude Desktop) から `Authorization: Bearer lv_xxx` を全 MCP
リクエストに付ける。FastMCP Streamable HTTP は ASGI middleware の上に乗るので、
FastAPI の `Depends(current_authenticated_user)` を経由して同じ machinery で
PAT を検証する。

### team の解決

PAT を持つユーザーは複数 team に所属しうるため、tool 呼び出しごとに team を
決める必要がある。優先順:

1. tool 引数の `team` (現状の MCP ツールの引数。明示的な切替用)
2. リクエストヘッダ `X-Labvault-Team`
3. PAT に紐付く user の primary team (Firestore `users/{email}.teams[0]`)
4. `Settings().team` (`LABVAULT_TEAM` 環境変数)

Claude Desktop からは tool 引数のほうが指定しやすいので、まずは (1) → (3) →
(4) を実装し、ヘッダ方式は後で必要なら足す。

### scope

将来 PAT に scope (read-only / write) を持たせる場合、MCP は全ツール read-only
なので `read` scope だけ要求する。今は scope 概念が無いので、PAT 1 種類で OK。

## トランスポート

MCP の現行推奨は **Streamable HTTP** (旧 SSE transport の後継。単一エンドポイントで
request / notification の双方向)。`mcp` Python パッケージは `FastMCP` 経由で
ASGI app を返す API を持つ。

### stateless モード

Cloud Run の特徴 (複数インスタンスへの分散、スケールイン時のセッション破棄) を
考えると、**stateless モードで動かす** のが安全:

- `Mcp-Session-Id` を使わない
- 1 リクエスト 1 ツール呼び出しが独立して完結
- スティッキールーティングや Redis セッションが不要

labvault の現行 7 ツールはすべて stateless (前のツールの戻り値を後続の呼び出しが
内部で記憶する必要なし) なので stateless モードで問題ない。

### Cold start

Cloud Run のデフォルト `min-instances=0` だと初回接続が 2〜3 秒遅れる。
許容できないなら `min-instances=1` (月数十円) に上げる。最初は 0 で start し、
体感で気になれば後で変える。

## 実装計画

### Phase 1: 最小エンドポイント

- `platform/backend/app/routers/mcp.py` を新設
- `src/labvault/mcp/server.py` の `create_server()` を再利用して FastMCP インスタンスを
  作る (Lab は per-team キャッシュ済み)
- `mcp.streamable_http_app()` (stateless) を FastAPI の `app.mount("/mcp", ...)` で接続
- PAT 検証は ASGI middleware で挟む (FastAPI の `Depends` は mount された ASGI app
  には適用されないため、middleware で `Authorization` を見て弾く)
- team は middleware で resolve して `contextvar` に積み、MCP ツール内から参照する

### Phase 2: team 引数とヘッダの整理

- 既存ツールの `team: str | None` 引数はそのまま残す
- 省略時の解決順序を確定 (上述)

### Phase 3: ドキュメント・配布

- `docs/onboarding.md` と `/account/tokens` ページに「Claude Desktop / Code に
  リモート MCP を登録する」セクション追加
- 設定例:

  ```bash
  # Claude Code
  claude mcp add --transport http labvault \
    https://labvault-api-355809880738.asia-northeast1.run.app/mcp \
    -H "Authorization: Bearer lv_xxx"
  ```

  Claude Desktop は `claude_desktop_config.json` に同等の URL + header を書く
  (公式 docs を参照)。

### Phase 4: ローカル mcp との関係整理 (完了 2026-06-15, PR TBD)

- ローカル `labvault mcp` (stdio) は引き続き残す。装置 PC や Firestore ADC 環境用
- README / onboarding では「**通常はリモート MCP を使ってください**」を default 動線にする
- ローカル MCP は「装置 PC で実行中の Lab を直接触りたい上級者向け」と位置付ける

反映先:

- `README.md` の MCP セクション — リモート優先、ローカルは 3 ケース (オフライン / 装置 PC dev / MCP ツール開発) と明記
- `src/labvault/cli/main.py` の `labvault mcp` docstring + stderr — 「通常はリモート推奨」を出力
- `docs/instrument_pc_setup.md` 末尾 — 「MCP は基本不要、リモート利用」を明示 + 例外用途に言及
- `docs/auth_design.md` の認証表 — MCP 行を「リモート (PAT)」「ローカル (ADC/PAT)」の 2 行に分割

## トレードオフ・リスク

| 項目 | リスク | 対応 |
|---|---|---|
| Claude 側の remote MCP 仕様変更 | SDK 側で transport が壊れる可能性 | 公式 `mcp` パッケージにロックし、CI で smoke test を回す |
| Cold start | 初回呼び出しが 2〜3 秒遅延 | 最初は許容。気になれば `min-instances=1` |
| PAT 漏洩時の被害範囲拡大 | リモートからも叩けるので影響大 | 既存と同様 `/account/tokens` の revoke で即無効化。`last_used_at` で棚卸し |
| Cloud Run egress | `data_preview` で Nextcloud → Cloud Run → Claude にファイルが流れる | プレビュー上限 (現状の text limit) で抑制済み。バイナリは流さない |
| team 誤指定 | 別 team のデータが見えるリスクは無い (PAT user の所属 team しか resolve しない) | resolver で「所属していない team を指定したら 403」をチェック |

## 検証

- `tests/integration/test_mcp_remote.py` を追加: `LABVAULT_DEV_SKIP_AUTH=1` で
  uvicorn を起動し、`mcp` パッケージのクライアントから `/mcp` を叩いて 7 ツール
  全部の round-trip を確認
- 実環境では `claude mcp add` → Claude Code から「最新の XRD 実験を 3 件出して」
  のような自然言語 prompt が通ることを手動確認

## 参考

- MCP Streamable HTTP transport: <https://modelcontextprotocol.io/docs/specification/2025-06-18/basic/transports>
- `mcp` Python パッケージ `FastMCP.streamable_http_app()` API
- 既存実装: `src/labvault/mcp/server.py`, `platform/backend/app/auth.py`,
  `platform/backend/app/routers/pypi_proxy.py` (PAT を Bearer で受ける既存例)
