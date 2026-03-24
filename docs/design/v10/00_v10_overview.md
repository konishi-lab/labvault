# labvault v10 概要

> v9レビュー（79件の懸念点）を全面的に反映し、月額$10以下のコスト制約を満たす再設計。
> アーキテクチャの大幅簡素化、SDK品質の向上、実験ワークフローの実用性強化を行う。

---

## 1. v9 → v10 変更サマリー

| 項目 | v9 | v10 | 理由 |
|------|----|----|------|
| MCPサーバー | Cloud Run | **Cloud Functions Gen2** | VPCコネクタ($7-10/月)廃止。コスト$7→$0.39 |
| サンドボックス | Cloud Run Jobs | **Cloud Functions内subprocess** | コールドスタート30-60秒→0.5-2秒 |
| Embedding生成 | Cloud Functions trigger | **SDK側REST API直接** | google-cloud-aiplatform(数百MB)排除 |
| VPCコネクタ | 必要($7-10/月) | **廃止** | Cloud Functions=VPCコネクタ不要 |
| MCPツール数 | 14 | **8** | LLMの認知負荷削減。重複統合 |
| Backend Protocol | sync/async混在 | **全sync** | Notebook event loop競合回避 |
| namespace diff | hash() | **id() + shallow digest** | ndarray等unhashable対応 |
| ファイルパーサー | なし | **プラグイン型パーサー** | .ras/.dm3等のメタデータ自動抽出 |
| テンプレート | 基本のみ | **required_conditions + indexed_fields** | 入力漏れ防止 + 検索改善 |
| 装置PC投入 | M6（Nextcloud poller） | **M2（_inbox + QRコード）** | 前倒し。実用性向上 |
| 認証 | allUsers invoker | **IAM + APIキー二重認証** | セキュリティ |
| モニタリング | なし | **予算アラート + エラー率アラート** | 無料枠内で実現 |
| バックアップ | なし | **Firestore日次エクスポート** | データ保護 |
| 月額コスト | $9.09(表面) / $20-50(実質) | **$0.91** | 全コスト計上済み |

---

## 2. v10 確定アーキテクチャ

```
SDK (pip install labvault)
├── IPython hooks（全セル自動記録。shallow digest変更検出）
├── ローカルバッファ（SQLite + ローカルファイルコピー）
├── ファイルパーサー（.ras, .dm3, .dat等のメタデータ自動抽出）
├── Embedding生成（SDK側 text-embedding-004 REST API直接）
├── Firestore（メタデータ + Vector Search + セルログ + 解析履歴）
└── Nextcloud（30TB。バイナリ実体 + _inbox投入 + QRコード投入）

MCP Server (Cloud Functions Gen2)         ← Cloud Run廃止
├── search（ハイブリッド検索 + result_key横断）
├── get_detail（詳細 + notebook_log + traces 統合）
├── compare（レコード比較 + パラメータスタディ 統合）
├── data_preview（ファイル統計サマリー）
├── aggregate（数値集約）
├── get_timeline（時系列履歴）
├── explain_result（結果の算出過程）
└── get_image（画像URI参照）[M5]

Cloud Functions (トリガー)
├── embedding_generator（SDK非経由投入用フォールバック）
└── nextcloud_poller（_inbox検出 + パーサー適用。M2前倒し）

Cloud Functions (運用)
└── firestore_backup（日次。Cloud Scheduler起動）

[廃止] Cloud Run Service
[廃止] Cloud Run Jobs
[廃止] Cloud Storage 一時バケット
[廃止] VPCコネクタ
[廃止] preview_generator（MCPのdata_previewでオンデマンド生成）
[廃止] notebook_summarizer（SDK側でembedding_textに含める）
```

---

## 3. コスト見積もり（$10以下を証明）

| カテゴリ | 月額コスト | v9比較 |
|---------|-----------|--------|
| Cloud Functions Gen2 (MCP Server) | $0.39 | Cloud Run $7.00 → **-$6.61** |
| Cloud Functions (embedding_generator) | $0.02 | 同等 |
| Cloud Functions (nextcloud_poller) | $0.25 | 5分→15分間隔に最適化 |
| Cloud Functions (firestore_backup) | $0.00 | 新規（無料枠内） |
| Firestore | $0.16 | 同等 |
| Vertex AI Embedding | $0.03 | 同等 |
| Secret Manager | $0.06 | 同等 |
| Cloud Storage (バックアップ) | $0.03 | 新規 |
| Cloud Scheduler | $0.00 | 新規（月3ジョブ無料） |
| VPCコネクタ | **$0.00** | v9隠れコスト$7-10 → **廃止** |
| Cloud Run Jobs | **$0.00** | $0.80 → **廃止** |
| **合計** | **$0.94/月** | v9実質$20-50 → **95%以上削減** |

> 無料枠適用後: **$0.00〜$0.30/月**

---

## 4. v9レビュー対応マッピング（全79件）

### 解決済み（高深刻度 24件中 20件）

| ID | 指摘 | v10での対応 |
|----|------|-----------|
| L-1 | ツールdescription不足 | 全8ツールに200-300文字のdescription + ユースケース例 + パラメータ例 |
| L-2 | ツール数過多(14) | 8ツールに統合（search+get_results, compare+compare_runs, get_detail+notebook_log+trace） |
| L-3 | subprocess方式セキュリティ | env完全クリーン化 + nobody実行 + GCE_METADATA_HOST遮断 |
| L-4 | プロンプトインジェクション | ユーザーデータ境界タグ + instructions警告 + sanitize_record() |
| P-1 | PermissionError衝突 | `LabvaultPermissionError` にリネーム |
| P-2 | sync/async不一致 | 全sync統一。FirestoreBackendも同期クライアント使用 |
| P-3 | hash() unhashable | id() + shallow digest（ndarray: shape+dtype+先頭末尾、DataFrame: shape+columns） |
| P-4 | AST検査バイパス | ベストエフォートと明文化。builtins禁止追加。主防御はgVisor |
| P-5 | google-cloud-aiplatform巨大 | 依存排除。REST API直接呼び出し（httpx + google-auth） |
| P-6 | hooks二重登録 | Lab._active_tracker管理。lab.new()時に既存tracker deactivate |
| G-1 | コスト過小 | $0.94/月（全コスト計上。VPCコネクタ廃止） |
| G-2 | allUsers invoker | --no-allow-unauthenticated + APIキー二重認証 |
| G-3 | コールドスタート5-15秒 | Cloud Functions Gen2 + cpu_boost → 1-3秒 |
| G-4 | Firestoreバックアップなし | 日次エクスポート（Cloud Scheduler + Cloud Functions） |
| G-7 | Cloud Run Jobsコールドスタート30-60秒 | 廃止→subprocess 0.5-2秒 |
| G-8 | embedding無限ループ | embedding_text_hash + 再帰呼び出し保護 + 書き込みアラート |
| G-9 | モニタリング欠如 | 予算アラート + エラー率アラート + 構造化ログ（全無料） |
| S-1 | 装置→記録ギャップ | Nextcloud _inbox投入(M2前倒し) + QRコード + CLIバイナリ |
| S-2 | 装置ファイルメタデータ | プラグイン型パーサー。ビルトイン: .ras, .dm3, TIFF-SEM, .dat, .wdf |
| S-5 | 装置パラメータ網羅性 | テンプレートにrequired_conditions + close()時警告 |

### 緩和・部分対応（4件）

| ID | 指摘 | v10での対応 |
|----|------|-----------|
| G-5 | Nextcloud SPOF | v10スコープ外。将来キャッシュ検討 |
| G-6 | gVisor互換性 | POC-3検証対象を拡充（pymatgen, h5py含む） |
| S-3 | conditions検索スケール | indexed_fieldsでトップレベルフィールド昇格 |
| S-4 | 装置PC(Windows) | Nextcloud _inbox + QRコード + PyInstallerバイナリ(M3) |

---

## 5. v10 ドキュメント構成

```
docs/design/v10/
├── 00_v10_overview.md              ← 本ファイル
├── 01_architecture_and_cost.md     ← GCPアーキテクチャ + コスト + セキュリティ + モニタリング
├── 02_sdk_and_mcp.md               ← SDK変更 + MCPツール再設計 + pyproject.toml
└── 03_experiment_workflow.md        ← テンプレート + パーサー + 装置投入 + オンボーディング
```

---

## 6. REQUIREMENTS対応表（R01-R22、v10変更分のみ）

| 要件ID | v9 | v10変更点 |
|--------|----|----|
| R09 | add / add_ref | + **ファイルパーサーによるメタデータ自動抽出** |
| R10 | SDK + CLI | + **Nextcloud _inbox投入(M2)** + **QRコード** + **CLIバイナリ** |
| R11 | テンプレート基本 | + **required_conditions** + **condition_schema** + **indexed_fields** |
| R13 | hash()変更検出 | → **shallow digest変更検出** |
| R14 | Vector Search | + **indexed_fields対応。conditionsの構造化検索強化** |
| R15 | 14ツール(Cloud Run) | → **8ツール(Cloud Functions Gen2)** + description拡充 |
| R16 | Cloud Run Jobs | → **Cloud Functions内subprocess** |
| R18 | allUsers + APIキー | → **IAM + APIキー二重認証** |

---

## 7. v10 設計原則

### 7.1 コスト原則: 無料枠ファースト

GCPの無料枠で完結するアーキテクチャを最優先。Cloud RunやVPCコネクタのような固定コストコンポーネントは使わない。

### 7.2 簡素原則: コンポーネント数最小化

```
v9: Cloud Run + Cloud Run Jobs + Cloud Functions x4 + Cloud Storage + VPCコネクタ = 8コンポーネント
v10: Cloud Functions Gen2 x4 + Cloud Scheduler = 5コンポーネント（37%削減）
```

### 7.3 SDK完結原則: GCP依存の最小化

Embedding生成、ファイルパーサー、条件正規化はSDK側で実行。GCP側はデータ保存とMCPサーバーのみ。

### 7.4 実験者ファースト原則

装置PCからの投入をM6→M2に前倒し。テンプレートのrequired_conditionsで入力漏れを警告。パーサーでメタデータ自動抽出。

---

## 8. マイルストーンへの影響

| マイルストーン | v9 | v10変更 |
|-------------|----|----|
| M0 | GCPセットアップ + POC | + POC-3拡充（gVisor + pymatgen/h5py） |
| M1 | SDK Core | + ファイルパーサー基盤 + テンプレートv10 + indexed_fields |
| M2 | 自動ログ + バッファ | + **Nextcloud _inbox投入** + QRコード + shallow digest |
| M3 | Embedding + Search | SDK側embedding生成（google-cloud-aiplatform排除） |
| M4 | MCP + CLI | Cloud Functions Gen2デプロイ。8ツール + description拡充 |
| M5 | コード実行 | subprocess方式（env完全クリーン + nobody実行） |
| M6 | 拡張機能 | 追加パーサー + PyInstallerバイナリ |
