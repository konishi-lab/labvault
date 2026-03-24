# labvault 要件定義書

> 実験者がコードに組み込みやすく、結果としてのデータがLLMが扱いやすい形で貯まるライブラリ。
> パッケージ名: `labvault` / import: `from labvault import Lab`

---

## 要件一覧

| ID | カテゴリ | 要件名 | MVP | Phase |
|----|---------|--------|:---:|-------|
| R01 | データ管理 | チームデータ共有 | ✅ | M1 |
| R02 | データ管理 | 子レコード（階層構造） | ✅ | M1 |
| R03 | データ管理 | 別PC・別フェーズのデータ紐付け | ✅ | M1 |
| R04 | データ管理 | タグ・ステータス・メモ | ✅ | M1 |
| R05 | データ管理 | Recordモデルの汎用化 | ✅ | M1 |
| R06 | データ管理 | ソフトデリート/ゴミ箱 | ✅ | M1 |
| R07 | データ投入 | 使いやすいSDK（3行で開始） | ✅ | M1 |
| R08 | データ投入 | ローカルバッファ（データ消失防止） | ✅ | M2 |
| R09 | データ投入 | 大容量データ対応 | ✅ | M1 |
| R10 | データ投入 | 投入経路の多様性（SDK/CLI/ブラウザ） | ✅ | M4 |
| R11 | データ投入 | テンプレートシステム | ✅ | M1 |
| R12 | データ投入 | データ投入時の自動処理トリガー | - | M5 |
| R13 | 自動記録 | 実験コード+変数の自動保存 | ✅ | M2 |
| R14 | LLM連携 | LLMによるデータ検索と解析 | ✅ | M3-M4 |
| R15 | LLM連携 | MCPサーバー（14ツール） | ✅ | M4 |
| R16 | LLM連携 | LLMによるコード実行解析 | - | M5 |
| R17 | LLM連携 | LLMの役割の明確化 | ✅ | 設計方針 |
| R18 | 運用・管理 | 認証・認可 | ✅ | M1-M4 |
| R19 | 運用・管理 | チーム管理 | ✅ | M1 |
| R20 | 運用・管理 | エクスポート/バックアップ | - | M6 |
| R21 | 運用・管理 | バッチ操作 | - | M6 |
| R22 | 運用・管理 | マイグレーション（旧mdxdb→labvault） | - | M6 |

---

## データ管理

### R01: チームデータ共有 [MVP]

実験チーム（研究室）が1つのデータプールを共有し、全メンバーのデータが検索・閲覧可能であること。

- Firestore `teams/{team_id}/records/` + Nextcloud共有フォルダ構成
- 全メンバーが同一コレクションに読み書き
- LLMがチーム全体のデータを横断的に解析可能

### R02: 子レコード（階層構造） [MVP]

1回の実験で1サンプルに対し、複数の加工条件×複数の測定を階層的に記録できること。

- `exp.sub("加工条件A", type="process")` で子レコード作成
- Firestoreサブコレクション `sub_records/{sub_id}` で再帰的階層
- 測定条件が複雑な場合は孫レコードにも対応（実用上2-3階層）

### R03: 別PC・別フェーズのデータ紐付け [MVP]

サンプル作製と測定が別PCで行われる前提で、短いIDで紐付けできること。

- Crockford's Base32 4文字ID（約100万通り。例: "AB3F"）
- CLI `labvault add <ID> <file>` でどのPCからでもデータ追加
- Nextcloudブラウザ経由の投入にも対応（装置PCなどPythonなし環境）

### R04: タグ・ステータス・メモ [MVP]

失敗実験も記録でき、後からメタデータを付加できること。

- `exp.tag("XRD", "Fe-Cr")` / `exp.status = "success"` / `exp.note("メモ")`
- ステータス: `running` / `success` / `failed` / `partial`
- 後付け可能（「まず記録、整理は後」の運用）

### R05: Recordモデルの汎用化 [MVP]

`type` フィールドで用途を表現し、材料科学以外にも対応できること。

- type: `experiment`, `sample`, `process`, `measurement`, `computation`, `analysis` 等
- typeはフリーテキスト（enumではない。拡張自由）

### R06: ソフトデリート/ゴミ箱 [MVP]

誤削除防止のため、削除は即座に消さずゴミ箱に移動すること。

- `lab.delete(id)` → `status="deleted"` + `deleted_at` タイムスタンプ
- 30日後に完全削除（Cloud Scheduler）
- `lab.trash()` でゴミ箱一覧、`lab.restore(id)` で復元
- 削除権限: 作成者 + 管理者のみ

---

## データ投入

### R07: 使いやすいSDK（3行で開始） [MVP]

実験コードに組み込みやすく、最小限のboilerplateであること。

- `from labvault import Lab` → `lab = Lab("konishi-lab")` → `exp = lab.new("タイトル")` の3行で開始
- 汎用的な実験用ライブラリ（特定プロジェクトに縛られない）
- `exp.add("file")` / `exp.save("name", data)` でデータ保存（型自動判定）

### R08: ローカルバッファ（データ消失防止） [MVP]

`exp.add()` したデータは必ずローカルに先に保存し、ネットワークエラーでデータが消失しないこと。

- SQLiteローカルDB + ローカルファイルコピー
- `exp.add()` → ローカル即保存 → バックグラウンドでリモート同期
- オフライン時はローカルに蓄積、復帰時に自動同期
- `exp.flush()` で即時送信

### R09: 大容量データ対応 [MVP]

小～TB級のデータに対して適切な保存・参照方式を提供すること。

- 小（~100MB）: `exp.add()` → Nextcloudアップロード
- 中（100MB~数GB）: `exp.add()` → 非同期アップロード（進捗表示はPost-MVP）
- 大（数GB~TB）: `exp.add_ref(location="HPC:/path", size_gb=8)` で参照のみ
- DOIリンク: `exp.add_ref(doi="10.5281/zenodo.12345")`
- LLMにはサマリー/統計量のみ渡す

### R10: 投入経路の多様性 [MVP: SDK+CLI]

Python SDK以外からもデータを投入できること。

- ① Python SDK（メイン経路）
- ② CLI: `labvault new` / `labvault add` 等
- ③ Nextcloudブラウザ（フォルダ直接投入 → ポーラーで自動認識）[Post-MVP: M6]
- ④ WebApp [Post-MVP: M7]

### R11: テンプレートシステム [MVP]

よく使う測定のテンプレートを事前定義し、装置条件やデフォルトタグを自動設定できること。

- `lab.define_template("XRD", defaults={...}, recommended_results=[...])`
- `lab.new(template="XRD")` でテンプレート適用
- ビルトイン: XRD, SEM, SQUID（内容は実データで調整）

### R12: データ投入時の自動処理トリガー [Post-MVP: M5]

ファイル追加時にファイル種別に応じた前処理を自動実行すること。

- 画像（SEM, 光学顕微鏡等）: サムネイル/プレビュー画像を `_preview/` に自動生成
- NumPy配列: 統計サマリー（shape, dtype, min/max/mean/std）を自動計算
- CSV/TSV: カラム名・行数・先頭行のプレビューを自動抽出
- トリガー: Firestore `data_refs` 更新 → Cloud Functions起動

---

## 自動記録

### R13: 実験コード+変数の自動保存 [MVP]

実験者が何もしなくても、コード実行の全履歴がLLMに理解可能な形で保存されること。

**3層の自動ログ戦略:**

| 環境 | 方法 | 実験者の手間 |
|------|------|------------|
| Jupyter Notebook | IPython hooksで全セル自動記録 | **ゼロ**（`exp = lab.new()` だけ） |
| Pythonスクリプト | `@exp.track` デコレータ or `with exp.track_block()` | デコレータ1行 |
| どちらでも | `exp.snapshot()` で明示的にキャプチャ | 1行 |

- 各セルのソースコード・新規/変更変数・実行時間を自動記録
- 変数値もキャプチャ（LLMが「何をどういう条件で計算したか」を理解可能）
- 機微情報フィルタ必須（`*password*`, `*secret*`, `*token*` 等を自動マスク）
- 詳細設計: v9/01_sdk_implementation.md 参照

---

## LLM連携

### R14: LLMによるデータ検索と解析 [MVP]

数万件規模で速さと正確さを兼ね備えた検索をLLMから利用できること。

- Firestore Vector Search（768次元）+ 構造化フィルタのハイブリッド検索
- Vertex AI `text-embedding-004` によるセマンティック検索
- `lab.search("温度300度以上の実験")` でSDKからも利用可能

### R15: MCPサーバー（14ツール） [MVP: 11ツール]

LLMからデータにアクセスするためのMCPインターフェースを提供すること。

- Claude Desktop / Claude Code から接続（Streamable HTTP transport）
- 検索系: `search`, `get_detail`, `compare`, `data_preview`, `get_results`, `aggregate`
- 履歴系: `get_timeline`, `get_trace`, `explain_result`, `compare_runs`, `get_notebook_log`
- 実行系（M5）: `execute_code`, `batch_execute`, `get_image`

### R16: LLMによるコード実行解析 [Post-MVP: M5]

LLMがデータに対してPythonコードを生成・実行し、結果をグラフ/画像で返せること。

- MCPツール `execute_code` / `batch_execute` でサンドボックス実行
- 解析履歴の自動保存（コード・結果・画像・元の指示を `analyses/` に記録）
- 解析の連鎖（過去の解析結果を入力にして次の解析を実行）
- 同一コードを複数レコードに一括適用して比較表+グラフで返す

### R17: LLMの役割の明確化 [設計方針]

LLM = オーケストレーター（検索・要約・提案）。数値計算・フィッティング → Python実行環境（`execute_code`）に委譲。

---

## 運用・管理

### R18: 認証・認可 [MVP]

適切な認証と権限管理を提供すること。

- **SDK認証**: GCPサービスアカウント or ユーザー認証（Application Default Credentials）
- **MCPサーバー認証**: Cloud Run IAM invoker + サービスアカウントトークン
- **チーム内ロール**: admin（テンプレート管理・完全削除権限）/ member（CRUD）
- **データの可視性**: `visibility: "team" | "private"`（デフォルト: team）
- **APIキー**: MCPサーバー接続用Bearer Token

### R19: チーム管理 [MVP]

チーム（研究室）の作成・メンバー管理ができること。

- Firestore `teams/{team_id}/info` にチーム情報を保存
- フィールド: `name`, `nextcloud_group_folder`, `members: [str]`, `admin: [str]`
- `labvault init` で対話的にチーム作成・設定
- メンバーの招待・削除はadminのみ

### R20: エクスポート/バックアップ [Post-MVP: M6]

GCP非依存のローカルバックアップを作成できること。

- `lab.export(path="./backup/")` で全メタデータ+バイナリをローカルエクスポート
- JSON Lines + ファイルコピー
- 差分エクスポート対応

### R21: バッチ操作 [Post-MVP: M6]

パラメータスイープの一括登録やディレクトリからの自動インポートができること。

- `exp.sweep("temperature_C", [300, 500, 700])` → 子レコード一括生成
- `lab.import_dir("path/to/experiments/")` → ディレクトリ構造から自動インポート

### R22: マイグレーション（旧mdxdb→labvault） [Post-MVP: M6]

旧Nextcloud/mdxdbフォーマットからlabvault形式への移行ツールを提供すること。

- 旧フォーマット（`v{major}/{db_name}/`）からの変換スクリプト
- Firestoreへの一括登録 + embedding一括生成
- ドライランモード

---

## 非機能要件

### NF01: 検索性能

- 数万件規模でのVector Search応答: 200ms以下（10K件）、500ms以下（50K件）
- POCで検証。NG時はPinecone Serverlessにフォールバック

### NF02: データ消失ゼロ

- ローカルバッファ（SQLite）により、ネットワーク切断時もデータ消失しない
- Firestore + Nextcloudの二重保存でバックエンド障害にも耐性

### NF03: オフライン動作

- ネットワーク切断時も `exp.add()` / `exp.save()` が即座に成功（ローカル保存）
- オンライン復帰時に自動同期

### NF04: GCP内完結

- バックエンドはGCPサービスのみ（Firestore, Vertex AI, Cloud Functions, Cloud Run）
- コンプライアンス審査が通りやすい構成
- Nextcloud（オンプレ or 学内）+ GCP のハイブリッド

### NF05: 運用ゼロ

- サーバーレス構成（Firestore + Cloud Functions）でパッチ・バックアップ・スケーリング全自動
- 研究室にDB管理者がいない前提
- コスト: Phase 1で月$5-20（Firestore） + Nextcloud無料

---

## 確定アーキテクチャ

```
SDK (pip install labvault)
├── IPython hooks（全セル自動記録）
├── ローカルバッファ（SQLite。データ消失防止）
├── Firestore（メタデータ + Vector Search + セルログ + 解析履歴）
└── Nextcloud（30TB。バイナリ実体 + ブラウザ投入口）

MCP Server (Cloud Run)
├── 検索系: search, get_detail, compare, data_preview, get_results, aggregate
├── 履歴系: get_timeline, get_trace, explain_result, compare_runs, get_notebook_log
└── 実行系: execute_code, batch_execute, get_image

Cloud Functions (トリガー)
├── embedding_generator（レコード作成時 → Vertex AI → embedding書き戻し）
├── nextcloud_poller（5分間隔 → ブラウザ投入の自動認識）
└── preview_generator（ファイル追加時 → サムネイル/統計サマリー生成）
```

---

## 保存先: GCP + Nextcloud

- **Nextcloud**: 30TBの無料ストレージ。バイナリ実体+ブラウザ投入口
- **Firestore**: メタデータのリアルタイム読み書き。サーバーレス、月$5-20
- **Vertex AI**: Embedding生成（text-embedding-004）
- **BigQuery**: Phase 2で追加。Firestoreの自動エクスポート機能で連携（追加コードほぼ不要）
- DB選定根拠: `DB_SELECTION.md` 参照

---

## 確定事項

- **パッケージ名**: `labvault`（PyPI）
- **import**: `from labvault import Lab`
- **CLI**: `labvault init`, `labvault new`, `labvault add`, ...
- **SDKリポジトリ**: `github.com/konishi-lab/labvault`
- **プラットフォームリポジトリ**: `github.com/konishi-lab/labvault-platform`（モノレポ）
- **ID**: Crockford's Base32（4文字、大文字。例: "AB3F"）

---

## 明示的にスコープ外

- Web UIの初期実装（M7で対応）
- オントロジーマッピング（将来対応）
- HPC連携（将来対応）
- 全ての装置フォーマットのパーサー（プラグインとして将来対応）
- FAIR原則への完全対応（段階的に対応。ライセンス・DOI・メタデータ標準）

---

## 設計資料

- `docs/design/v9/` — 最新の実装仕様（v8をlabvault化+補完）
- `docs/design/v8/` — v8実装仕様（議論の経緯として保存）
- `docs/design/v7/` — v7 SDK詳細設計
- `docs/design/DB_SELECTION.md` — DB選定根拠
