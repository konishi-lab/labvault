# v8 最終マイルストーン計画

> 作成日: 2026-03-17
> 前提: REQUIREMENTS.md全要件（Tier 1 #1-#8c, Tier 2 #8-#12, Tier 3 #13-#19）、v7設計、v5-reviewの批判を統合。
> 開発体制: 開発者1名 + Claude Code。

---

## 1. REQUIREMENTS全要件の充足マトリクス

### Tier 1: 絶対に必要な要件

| # | 要件 | v8での実現方法 | MVP (Week 7) | リスク |
|---|------|---------------|:---:|--------|
| **1** | チームでデータ共有・活用 | Firestore `teams/{team_id}/records/` + Nextcloud共有フォルダ。全メンバーが同一コレクションに読み書き | **含む** | Firestoreの複合インデックス上限（200個）。実験条件の多様化で上限に近づく可能性 → 条件はMap型で格納しフィルタ対象を限定 |
| **2** | LLMによる検索と解析 | MCP Server 14ツール（Cloud Functions）。Firestore Vector Search（768次元）+ 構造化フィルタのハイブリッド検索。セルログ・トレースの3段階詳細度（L1/L2/L3） | **含む**（検索11ツール）。execute_code/batch_execute/get_imageはMVP後 | Firestore Vector Searchのレイテンシ（1万件超で300ms以上の可能性）→ POCで検証、NGならPineconeフォールバック |
| **3** | 使いやすいSDK | `Lab` / `Record` クラス。3行で開始: `from mdxdb import Lab` → `exp = Lab("team").new("title")` → `exp.add("file")`。IPython hooks自動ログで手間ゼロ | **含む** | IPython hooksの環境差異（JupyterLab, Colab, VS Code Notebook）→ POCで各環境テスト |
| **4** | 別PC・別フェーズのデータ紐付け | Crockford's Base32 4文字ID（約100万通り）。CLI `mdxdb add <ID> <file>` / Nextcloudブラウザで `{record_id}/` フォルダに直接投入 | **含む** | 4文字IDの衝突確率。1万レコードで約5%の衝突リスク → 衝突時リトライ、将来的に5文字拡張 |
| **5** | 子レコード（階層構造） | `exp.sub("子レコード名", type="measurement")` → Firestoreサブコレクション `sub_records/{sub_id}`。再帰的階層可能 | **含む** | サブコレクションの深さ制限（Firestore推奨は3階層まで）→ 実用上2階層で十分 |
| **6** | コード+変数をセットで保存 | **3層**: (1) IPython hooks全セル自動記録（`cell_logs/`）、(2) `@exp.track` デコレータ（`traces/`）、(3) `exp.snapshot()` 手動キャプチャ。機微情報フィルタ（変数名パターンマッチ `*password*`, `*secret*` 等）はMVP必須 | **含む** | namespaceスキャンのオーバーヘッド → `id()` + `type()` のみで変更検出（O(1)）。巨大変数のシリアライズ → サイズ制限+サマリー化 |
| **7** | GCP + Nextcloud | Firestore（メタデータ+Vector Search+セルログ）、Vertex AI（Embedding）、Cloud Functions（トリガー）、Nextcloud（30TBバイナリ）。Phase 2でBigQuery追加 | **含む** | Nextcloud WebDAVの不安定さ → 既存リトライ+フォールバックロジック移植、ローカルバッファで消失防止 |
| **8a** | 大容量データ対応 | 3段階: 小(~100MB) `exp.add()` → Nextcloud、中(100MB~数GB) `exp.add()` 非同期アップロード、大(数GB~TB) `exp.add_ref(location=..., size_gb=...)` 参照のみ。DOIリンク `exp.add_ref(doi="...")` | **含む**（add + add_ref）。非同期アップロードの進捗表示はMVP後 | 大容量ファイルのNextcloudアップロード速度 → POCで100MB/1GBの速度計測 |
| **8b** | LLMによるコード実行解析 | MCPツール `execute_code` / `batch_execute` / `get_image`。Cloud Functions or Cloud Runのサンドボックス環境。numpy/scipy/matplotlib/pandasプリインストール。解析履歴 `analyses/{analysis_id}` をFirestoreに自動保存。解析の連鎖（`input_analyses` で前の結果を参照） | **MVP後**（M5） | サンドボックスのセキュリティ（任意コード実行）→ gVisor / nsjail で隔離。実行時間制限60秒、メモリ2GB |
| **8c** | データ投入時の自動処理トリガー | Firestoreの `data_refs` フィールド更新 → Cloud Functions起動。画像→サムネイル/プレビュー自動生成（`_preview/`）、NumPy→統計サマリー、CSV→カラム名+先頭行プレビュー | **MVP後**（M5） | Cloud Functionsのタイムアウト（540秒）。大容量TIFFの処理時間 → 画像はリサイズのみ（解析はしない）、タイムアウト超過時はスキップしてログ |

### Tier 2: 高い優先度

| # | 要件 | v8での実現方法 | MVP (Week 7) | リスク |
|---|------|---------------|:---:|--------|
| **8** | ローカルバッファ必須（Tier 1昇格） | SQLiteローカルDB + ローカルファイルコピー。`exp.add()` → (1) ローカルに即保存 (2) バックグラウンドでリモート同期。同期キュー（FIFO）、`exp.flush()` で即時送信。オフライン時はローカルに蓄積、復帰時に自動同期 | **含む** | コンフリクト解決（同一レコードを別PCから同時更新）→ Last Write Wins + 競合検出ログ。ローカルバッファのサイズ管理 → 同期済みファイルの定期削除（デフォルト7日保持） |
| **9** | 投入経路の多様性 | (1) Python SDK（メイン）、(2) CLI `mdxdb` コマンド、(3) Nextcloudブラウザ（フォルダ直接投入 → Cloud Functionsポーラーで自動認識）、(4) WebApp（Phase 2 Streamlit） | **含む**（SDK+CLI）。Nextcloudポーラー・WebAppはMVP後 | Nextcloudポーラーの検出遅延（5分間隔）→ 許容。即時性が必要ならSDK/CLI使用 |
| **10** | テンプレートシステム | `Lab.define_template("XRD", defaults={...})`、`lab.new(template="XRD")`。`recommended_results` フィールドで推奨出力項目を定義。Firestoreの `teams/{team_id}/templates/` に保存。ビルトイン: XRD, SEM, SQUID | **含む**（基本機能） | ビルトインテンプレートの内容定義が未確定 → 実装しながら研究室の実データで調整 |
| **11** | タグ・ステータス・メモ | `exp.tag("XRD", "Fe-Cr")`、`exp.status = "success" / "failed" / "partial"`、`exp.note("メモ")`。後付け可能。失敗実験も記録推奨 | **含む** | なし（単純なフィールド操作） |
| **12** | MCPサーバー | Cloud Functions (Gen2) ベースの FastMCP サーバー。14ツール。Claude Desktop / Claude Code から接続（Streamable HTTP transport） | **含む**（11ツール） | MCPプロトコルの仕様変更 → Anthropic公式SDKに追従。Cloud Functionsのコールドスタート（1-3秒） |

### Tier 3: スペシャリストレビューからの重要指摘

| # | 要件 | v8での実現方法 | MVP (Week 7) | リスク |
|---|------|---------------|:---:|--------|
| **13** | Recordモデルの汎用化 | `Record.type` フィールド: `experiment`, `sample`, `process`, `measurement`, `computation`, `reaction` 等。typeはフリーテキスト（enumではない） | **含む** | なし |
| **14** | バッチ操作 | `exp.sweep(param_name, values)` でパラメータスイープ子レコード一括生成。ディレクトリインポート `lab.import_dir("path/")` | **MVP後**（M6） | なし（便利機能） |
| **15** | 大容量データの参照登録 | #8aに統合。`exp.add_ref()` | **含む** | #8aと同じ |
| **16** | LLMの役割の明確化 | LLM = オーケストレーター（MCPツールで検索・要約・比較）。数値計算 = `execute_code` で Python実行環境に委譲。LLMが直接計算しない設計 | **含む**（設計方針として） | なし |
| **17** | エクスポート/バックアップ | `lab.export(path="./backup/")` で全メタデータ+バイナリをローカルエクスポート。JSON Lines + ファイルコピー | **MVP後**（M6） | 大量データのエクスポート時間 → 差分エクスポートオプション |
| **18** | FAIR原則への段階的対応 | Phase 2以降。ライセンスフィールド、DOI登録連携、メタデータ標準（Dublin Core等） | **MVP後** | なし（将来対応） |
| **19** | ソフトデリート/ゴミ箱 | `lab.delete(id)` → `status="deleted"` + `deleted_at` タイムスタンプ。30日後に完全削除（Firestore TTL or Cloud Scheduler）。削除権限: 作成者 + 管理者。`lab.trash()` でゴミ箱一覧、`lab.restore(id)` で復元 | **含む**（基本機能） | TTL削除の実装。Firestore TTLはドキュメント単位で設定可能だが、サブコレクションの連鎖削除が必要 → Cloud Functionsで定期クリーンアップ |

---

## 2. 最終マイルストーン（確定版）

### 全体タイムライン

```
Week 1-2:   M0 基盤+POC
Week 2-4:   M1 SDK Core
Week 4-5:   M2 自動ログ + ローカルバッファ
Week 5-6:   M3 Embedding + Vector Search
Week 6-7:   M4 MCP Server + CLI
Week 7:     ★ MVP完成 → チームAlpha利用開始
Week 8-9:   M5 LLMコード実行 + 自動トリガー
Week 9-11:  M6 拡張機能（バッチ、エクスポート、Nextcloud同期）
Week 11-13: M7 WebApp（Streamlit）
Week 13+:   M8 BigQuery連携・FAIR対応等
```

---

### M0: 基盤セットアップ + 技術POC（Week 1-2）

#### ゴール
> 「GCPプロジェクトが動作し、技術リスクの高い4項目のPOCが完了している」

#### 成果物
- GCPプロジェクト（asia-northeast1: Firestore, Vertex AI, Cloud Functions有効化）
- SDKリポジトリの新ディレクトリ構造（`src/mdxdb/`）
- POC検証結果（4項目の合否判定）
- パッケージ名の確定

#### タスク（GitHub Issue化粒度）

**Issue: GCPプロジェクトセットアップ**
- GCPプロジェクト作成（asia-northeast1）
- Firestore Native Modeデータベース作成
- Vertex AI API有効化
- サービスアカウント作成 + IAMロール設定
- Secret Manager にNextcloud認証情報を登録
- 受け入れ条件: Firestoreにドキュメントの読み書きがPythonから可能

**Issue: SDKリポジトリ再構成**
- `src/mdxdb/` 以下にcore/, backends/, tracking/, buffer/, cli/ を作成
- `pyproject.toml` 刷新（依存: google-cloud-firestore, nc_py_api, vertexai）
- CLAUDE.md更新（新アーキテクチャ情報）
- CI設定（GitHub Actions: lint + test + coverage）
- 受け入れ条件: `pip install -e .` でインストール可能、pytest通過

**Issue: POC-1 Firestore Vector Search性能検証**
- テストデータ 1K/10K/50K件で768次元 Vector Search の応答時間を計測
- team_id フィルタ付きVector Search の性能確認
- 受け入れ条件: 10K件で200ms以下

**Issue: POC-2 IPython hooks安定性検証**
- JupyterLab, Google Colab, VS Code Notebook の3環境でIPython hooks動作確認
- `pre_run_cell` / `post_run_cell` の登録・発火確認
- namespace取得のオーバーヘッド計測（50変数で数ms以下）
- 受け入れ条件: 3環境中2環境以上で安定動作

**Issue: POC-3 Nextcloud WebDAVアップロード速度検証**
- 1MB / 10MB / 100MB / 1GB ファイルのアップロード時間計測
- 並行アップロードの性能確認
- 受け入れ条件: 10MB/s以上

**Issue: POC-4 パッケージ名決定**
- PyPI上の空き確認（候補3つ）
- `pip install <name>` で衝突しないことを確認
- チーム内投票で最終決定
- 受け入れ条件: PyPI名が確保済み

#### 検証方法
- GCPコンソールでFirestore/Vertex AIが動作確認可能
- 各POCスクリプトが正常終了し、合否が記録されている
- リポジトリにCIが通った状態でpush済み

#### リスク
- GCP課金アカウントの大学決裁プロセスに時間がかかる可能性（数日〜数週間）
- Firestore Vector Searchが想定レイテンシを超過 → Pinecone or Weaviate にフォールバック
- パッケージ名が全候補PyPIで取得不可 → スコープ付き名前（`konishi-mdxdb` 等）

#### 期間
- 5営業日（Claude Code併用）

---

### M1: SDK Core（Week 2-4）

#### ゴール
> 「`pip install mdxdb` して、3行でレコード作成 → Firestore保存 → Nextcloudにファイルアップロードができる」

#### 成果物
- `mdxdb` Pythonパッケージ（PyPI公開可能状態）
- `Lab` / `Record` クラス（完全なCRUD API）
- FirestoreBackend + NextcloudStorage
- InMemoryBackend（テスト用）
- 設定管理（`~/.mdxdb/config.toml`）

#### タスク

**Issue: Recordモデル + ID生成**
- `Record` dataclass（id, title, type, status, tags, conditions, results, notes, data_refs, parent_id, created_at, updated_at, created_by）
- Crockford's Base32 IDジェネレーター（4文字、衝突リトライ付き）
- RecordSerializer（Firestore dict変換）
- 受け入れ条件: Record生成・シリアライズのユニットテスト全通過

**Issue: Lab クラス Core API**
- `Lab.__init__(team, config)` — 設定読み込み、バックエンド初期化
- `Lab.new(title, type, template, **conditions)` → Record作成
- `Lab.get(id)` → Record取得
- `Lab.list(tags, status, type, limit, offset)` → Record一覧
- `Lab.search(query)` → テキスト検索（M3でセマンティック検索に拡張）
- `Lab.delete(id)` → ソフトデリート（status="deleted", deleted_at設定）
- `Lab.trash()` → 削除済みレコード一覧
- `Lab.restore(id)` → 削除取消
- `Lab.recent(n)` → 最近のn件
- 受け入れ条件: InMemoryBackendで全APIが動作

**Issue: Record操作API**
- `record.conditions(**kwargs)` — 実験条件設定
- `record.results[key] = value` — 結果保存（dict-like access）
- `record.tag(*tags)` / `record.untag(*tags)` — タグ操作
- `record.note(text)` — メモ追加
- `record.status = "success"` — ステータス変更
- `record.sub(title, type)` → 子Record作成
- メソッドチェーン対応（`exp.tag("XRD").note("memo").conditions(T=300)`）
- コンテキストマネージャ対応（`with lab.new(...) as exp:`）
- 受け入れ条件: 全操作のユニットテスト + メソッドチェーンのテスト

**Issue: データ保存API**
- `record.add(path)` — ファイルアップロード（型自動判定）
- `record.add(directory_path)` — ディレクトリごとアップロード
- `record.save(name, data)` — 型自動判定保存（dict→JSON, ndarray→npy, Figure→PNG）
- `record.add_ref(path, location, size_gb, description)` — 大容量データ参照登録
- `record.add_ref(doi="...")` — DOIリンク登録
- `record.log_notebook()` — 実行中Notebookの保存
- 受け入れ条件: テキスト/JSON/ndarray/Figureの保存・取得のテスト通過

**Issue: FirestoreBackend実装**
- `teams/{team_id}/records/{id}` CRUD
- サブコレクション `sub_records/{sub_id}`
- インデックス設計（team_id + updated_at, team_id + tags, team_id + type + status）
- バッチ書き込み対応
- 受け入れ条件: 実Firestoreに接続して10レコードのCRUDテスト通過

**Issue: NextcloudStorage実装**
- 既存 `client.py` からのリトライ・フォールバックロジック移植
- パス: `{group_folder}/mdxdb/{team_id}/{record_id}/{filename}`
- アップロード / ダウンロード / 削除
- 共有リンク自動生成（`record.url`）
- `Path(...).as_posix()` 統一
- 受け入れ条件: 実Nextcloudに接続してファイルアップロード・ダウンロードテスト通過

**Issue: 設定管理**
- `~/.mdxdb/config.toml` 設定ファイル
- 環境変数 `MDXDB_TEAM`, `MDXDB_GCP_PROJECT`, Nextcloud接続情報
- pydantic-settings対応
- `Lab()` 引数なしで設定ファイルから自動読み込み
- `mdxdb init` で対話的に設定ファイル生成（CLI側はM4で実装、ここはconfig読み書きのみ）
- 受け入れ条件: config.toml / 環境変数 / 引数の3方式で設定が読み込まれることのテスト

**Issue: テンプレートシステム**
- `Lab.define_template(name, defaults, recommended_results)` — テンプレート定義
- `Lab.new(template="XRD")` — テンプレート適用
- Firestoreの `teams/{team_id}/templates/` に保存
- ビルトインテンプレート3種: XRD, SEM, SQUID
- 受け入れ条件: テンプレート適用でconditionsにデフォルト値が設定されるテスト

#### 検証方法
```python
from mdxdb import Lab

lab = Lab()  # config.tomlから読み込み
exp = lab.new("Fe-10Cr XRD", template="XRD")
exp.conditions(temperature_C=500, pressure_Pa=1e-3)
exp.add("xrd_data.csv")
exp.save("processed", filtered_array)
exp.results["lattice_a"] = 2.873
exp.tag("Fe-Cr", "thin-film")
exp.note("結晶性良好")

sem = exp.sub("SEM観察", type="measurement")
sem.add("sem_image.tiff")

assert lab.get(exp.id).title == "Fe-10Cr XRD"
assert len(lab.list(tags=["Fe-Cr"])) >= 1
```
上記コードが正常動作し、Firestore + Nextcloudにデータが保存されること。

#### リスク
- Firestoreサブコレクション設計の判断ミス → POC段階で実クエリパターンを確認
- 既存SDKユーザーへの移行 → マイグレーションガイドをM4で作成

#### 期間
- 2週間（Claude Code併用）

---

### M2: 自動ログ + ローカルバッファ（Week 4-5）

#### ゴール
> 「Notebookで `exp = lab.new()` するだけで全セル実行が自動記録される。ネットワーク切断時もデータが消えない」

#### 成果物
- IPython hooks自動ログ（`tracking/` モジュール）
- `@exp.track` デコレータ + `exp.snapshot()`
- ローカルバッファ（`buffer/` モジュール、SQLite）
- 機微情報フィルタ

#### タスク

**Issue: IPython hooks自動ログ実装**
- IPython環境検出 (`get_ipython()`)
- `pre_run_cell` / `post_run_cell` フック登録
- namespace diff（`id()` + `type()` ベースの軽量変更検出）
- CellLog データモデル（cell_number, source, new_vars, changed_vars, duration_sec）
- `exp.pause_logging()` / `exp.resume_logging()` / `with exp.no_logging():`
- Firestoreの `cell_logs/` サブコレクションへの保存
- 受け入れ条件: JupyterLabでセル5つ実行 → 5つのCellLogがFirestoreに保存されている

**Issue: 機微情報フィルタ（MVP必須）**
- 変数名パターンマッチ（`*password*`, `*secret*`, `*token*`, `*key*`, `*credential*`, `*api_key*`）
- 型ベースフィルタ（`os.environ` 参照、pydantic Settings インスタンスは除外）
- URL内認証情報のマスク（`https://user:pass@host/` → `https://***@host/`）
- `exp.exclude_vars("var_name")` による明示的除外
- マスク値: `"***REDACTED***"`
- 受け入れ条件: `api_key = "sk-123"` が `"***REDACTED***"` として記録されるテスト

**Issue: 変数サマリー関数 `_summarize()`**
- 基本型（int, float, str, bool）→ そのまま
- ndarray → `"<ndarray shape=(M,N) dtype=float64>"`
- DataFrame → `"<DataFrame (rows x cols) columns=[...]>"`
- list/dict → 要素数 + 先頭3要素のプレビュー
- Figure → `"<Figure WxH>"`
- その他 → `"<ClassName>"`
- サイズ制限: 1変数あたり最大1KB
- 受け入れ条件: 各型のサマリー出力が仕様通りのテスト

**Issue: @exp.track デコレータ + snapshot()**
- `@exp.track` — 関数の引数・返り値・実行時間を記録
- `exp.snapshot()` — 呼び出し時点のローカル変数をキャプチャ
- `with exp.track_block("name"):` — ブロック単位の記録
- Firestoreの `traces/` サブコレクションへの保存
- 受け入れ条件: デコレータ付き関数呼び出しのトレースがFirestoreに保存されるテスト

**Issue: ローカルバッファ実装（SQLite）**
- `~/.mdxdb/buffer.db` SQLiteデータベース
- テーブル: `pending_records`, `pending_files`, `pending_cell_logs`
- `exp.add()` → (1) ローカルファイルコピー + SQLite記録（即座） (2) バックグラウンドでリモート同期
- 同期キュー（FIFO）、バックグラウンドスレッド
- セルログのバッチ送信（デフォルト30秒間隔）
- `exp.flush()` で即時送信
- オフライン検出 → ローカルに蓄積、復帰時に自動同期
- 同期済みファイルの定期削除（7日保持）
- 受け入れ条件: ネットワーク切断状態で `exp.add()` → ローカルに保存 → ネットワーク復帰 → リモートに同期

#### 検証方法
```python
# JupyterLab で実行
from mdxdb import Lab
exp = Lab("konishi-lab").new("テスト")

# セル2
import numpy as np
data = np.random.rand(100, 2)
cutoff = 0.5

# セル3
filtered = data[data[:, 0] > cutoff]

# → Firestoreに cell_logs が2件保存されている
# → cutoff=0.5 が new_vars に記録されている
# → api_key 等の変数名はマスクされている
```

#### リスク
- Google Colabの制限（IPython hooksが一部制限される可能性）→ Colabは「ベストエフォート」対応
- セルログのFirestore書き込み頻度 → バッチ送信で軽減

#### 期間
- 1.5週間

---

### M3: Embedding + Vector Search（Week 5-6）

#### ゴール
> 「`lab.search('結晶性が良い薄膜')` でセマンティック検索ができる」

#### 成果物
- Vertex AI Embedding統合
- Firestore Vector Search統合
- embedding自動生成パイプライン（Cloud Functions onCreateトリガー）

#### タスク

**Issue: EmbeddingService実装**
- Vertex AI `text-embedding-004` クライアント
- Recordからembedding用テキスト生成（title + conditions + results + tags + notesの結合）
- 日本語+英語混在テキストの前処理
- バッチembedding生成（複数レコード一括）
- 受け入れ条件: 日本語実験記述のembeddingが768次元ベクトルとして生成される

**Issue: Firestore Vector Search統合**
- `embedding` フィールドへのベクトル保存
- Vector Search用インデックス作成（768次元、cosine）
- `Lab.search(query, limit, filters)` のセマンティック検索実装
- team_id フィルタ付きVector Search
- 検索結果のスコアリング・ランキング
- 受け入れ条件: 10件のテストデータで類似実験が上位に返る

**Issue: embedding自動生成 Cloud Function**
- Firestore `records/{id}` のonCreate / onUpdateトリガー
- Record作成/更新時にembedding自動生成
- SDK経由で既にembedding設定済みの場合はスキップ
- エラー時のリトライ（最大3回）
- 受け入れ条件: レコード作成後30秒以内にembeddingフィールドが設定される

#### 検証方法
```python
lab = Lab()
# 事前にXRD実験を10件登録
results = lab.search("結晶性が良い薄膜")
assert len(results) > 0
# 上位にXRD実験が来ることを目視確認
```

#### リスク
- Vertex AI Embeddingの日本語品質 → POC-1で検証済み。NGならmultilingual modelに切替

#### 期間
- 1週間

---

### M4: MCP Server + CLI（Week 6-7）

#### ゴール
> 「Claude Desktopから『XRDの実験を探して』と聞くと検索結果が返る。CLIで基本操作ができる」

#### 成果物
- MCPサーバー（Cloud Functions Gen2）
- CLI `mdxdb` コマンド
- Claude Desktop接続設定ガイド

#### タスク

**Issue: MCPサーバー Core**
- FastMCP (Python) ベース
- Cloud Functions Gen2 デプロイ
- 認証: API Key (Bearer Token)
- Streamable HTTP transport
- 受け入れ条件: Claude Desktopから接続してechoツールが応答

**Issue: MCPサーバー 検索・閲覧ツール（11ツール）**
- `search` — ハイブリッド検索（構造化+ベクトル）
- `get_detail` — レコード詳細（include_traces, include_cell_logs オプション）
- `compare` — 複数レコード比較
- `data_preview` — ファイル統計サマリー
- `get_results` — 構造化結果の横断検索
- `aggregate` — 数値集約（平均、標準偏差、グループ化）
- `get_timeline` — サンプルの実験履歴
- `get_trace` — @exp.track の関数トレース
- `explain_result` — 結果の算出過程説明（セルログ+トレースから再構成）
- `compare_runs` — パラメータ差異の比較
- `get_notebook_log` — IPythonセルログ取得（L1/L2/L3詳細度指定）
- 受け入れ条件: 各ツールのリクエスト/レスポンスのテスト通過

**Issue: CLI基本コマンド**
- `mdxdb init` — 対話的セットアップ（チーム名、GCPプロジェクト、Nextcloud設定）
- `mdxdb new <title>` — レコード作成
- `mdxdb list` — レコード一覧
- `mdxdb show <ID>` — レコード詳細
- `mdxdb search <query>` — 検索
- `mdxdb add <ID> <file>` — ファイル追加
- `mdxdb url <ID>` — NextcloudのURL表示
- click + rich でリッチ出力
- 受け入れ条件: 全コマンドの正常・エラーケーステスト通過

**Issue: Claude Desktop接続ガイド**
- `claude_desktop_config.json` サンプル
- API Key発行手順
- 接続テスト手順
- トラブルシューティング
- 受け入れ条件: ガイドに従って新規ユーザーがClaude Desktopから接続可能

#### 検証方法
1. Claude Desktopで「Fe-Cr合金のXRD実験を探して」と質問
2. MCPサーバーが `search` ツールを呼び出し、結果を返す
3. Claudeが検索結果を自然言語で説明する

#### リスク
- Cloud Functions Gen2のSSE/Streamable HTTP対応 → POCで検証済み。NGならCloud Run
- コールドスタート遅延（1-3秒）→ 許容範囲

#### 期間
- 1.5週間

---

### ★ MVP完成（Week 7）→ チームAlpha利用開始

この時点で動作するもの:
- Python SDKでレコード作成・ファイル保存（ローカルバッファ付き）
- IPython hooks自動ログ（機微情報フィルタ付き）
- セマンティック検索
- Claude Desktop/Code からMCP経由でデータ検索・解析
- CLIで基本操作
- ソフトデリート/ゴミ箱
- テンプレートシステム（基本）

---

### M5: LLMコード実行 + 自動トリガー（Week 8-9）

#### ゴール
> 「LLMが『このデータにフィッティングして』と言われたら、Pythonコードを生成・実行し、結果をグラフ付きで返せる。画像投入時にサムネイルが自動生成される」

#### 成果物
- `execute_code` / `batch_execute` / `get_image` MCPツール
- サンドボックス実行環境（Cloud Run Jobs or Cloud Functions）
- 解析履歴の自動保存（`analyses/` サブコレクション）
- 自動処理トリガー（Cloud Functions: 画像リサイズ、NumPyサマリー、CSVプレビュー）

#### タスク

**Issue: サンドボックス実行環境**
- Cloud Run Jobs ベースのPython実行環境
- numpy, scipy, matplotlib, pandas プリインストール
- gVisor or nsjail によるサンドボックス化
- 実行時間制限60秒、メモリ制限2GB
- データファイルはNextcloudから一時取得 → 実行 → 結果返却
- 生成画像はNextcloudに自動保存
- 受け入れ条件: 任意のPythonコードが隔離環境で実行され、結果が返る

**Issue: execute_code / batch_execute MCPツール**
- `execute_code(record_id, file, code)` — 単一レコードのデータに対してコード実行
- `batch_execute(record_ids, file, code)` — 複数レコードに同一コード適用
- 解析結果の自動保存: Firestore `analyses/{analysis_id}` にコード・結果・画像・元の指示を記録
- `input_analyses` フィールドで解析の連鎖を追跡
- 受け入れ条件: XRDデータに対するフィッティングコードが実行され、結果+グラフが返る

**Issue: get_image MCPツール**
- `get_image(record_id, analysis_id, image_name)` — 解析結果の画像取得
- Nextcloudからの画像ダウンロード + Base64エンコード
- 受け入れ条件: execute_codeで生成された画像がClaude Desktopに表示される

**Issue: 自動処理トリガー**
- Firestoreの `data_refs` フィールド更新 → Cloud Functions起動
- 画像（TIFF, PNG, JPEG）→ サムネイル256x256 + プレビュー1024x1024 を `_preview/` に生成
- NumPy配列 → shape, dtype, min/max/mean/std の統計サマリーを `_preview/{name}_meta.json` に生成
- CSV/TSV → カラム名・行数・先頭5行のプレビューを `_preview/{name}_preview.json` に生成
- 受け入れ条件: SEM画像アップロード後、30秒以内にサムネイルが `_preview/` に生成される

#### 検証方法
```
ユーザー（Claude Desktop）: 「AB3FのXRDデータに正規分布でフィッティングして」
LLM → execute_code → 結果: {center: 28.4, sigma: 0.18} + フィッティンググラフ

ユーザー: 「同じ解析をKL67とST45にも」
LLM → batch_execute → 3レコードの比較表 + 重ね書きグラフ
```

#### リスク
- サンドボックスのセキュリティ。任意コード実行は本質的に危険 → ネットワーク遮断 + ファイルシステム制限 + 実行時間制限で緩和
- Cloud Run Jobsのコールドスタート → プリウォーム or Cloud Functions Gen2で代替

#### 期間
- 2週間

---

### M6: 拡張機能（Week 9-11）

#### ゴール
> 「バッチ操作、エクスポート、Nextcloudブラウザ投入の自動認識ができる」

#### 成果物
- バッチ操作（sweep, import_dir）
- エクスポート/バックアップ（`lab.export()`）
- Nextcloud同期ポーラー（Cloud Functions + Cloud Scheduler）
- 既存データマイグレーションスクリプト

#### タスク

**Issue: バッチ操作**
- `exp.sweep("temperature_C", [300, 500, 700])` → 子レコード3件一括生成
- `lab.import_dir("path/to/experiments/")` → ディレクトリ構造から自動インポート
- CSV一括登録 `lab.import_csv("experiments.csv")`
- 受け入れ条件: sweepで子レコードが正しく生成される

**Issue: エクスポート/バックアップ**
- `lab.export(path="./backup/")` → JSON Lines + バイナリファイルのフルエクスポート
- 差分エクスポート（前回エクスポート以降の変更のみ）
- 受け入れ条件: エクスポートしたデータからレコードを復元できる

**Issue: Nextcloud同期ポーラー**
- Cloud Functions + Cloud Scheduler（5分間隔）
- Nextcloudの `mdxdb/{team_id}/` 以下のファイル変更を検知
- 新規ファイル → Firestoreにメタデータ自動登録 + embedding生成
- 受け入れ条件: Nextcloudブラウザでファイルアップロード → 5分以内にFirestoreに反映

**Issue: 既存データマイグレーション**
- 旧フォーマット（`v{major}/{db_name}/`）からの変換スクリプト
- Firestoreへの一括登録 + embedding一括生成
- ドライランモード
- 受け入れ条件: 既存データがv8フォーマットに移行済み

#### 期間
- 2週間

---

### M7: WebApp — Streamlit（Week 11-13）

#### ゴール
> 「ブラウザでダッシュボード閲覧、レコード検索、装置PCからのファイルアップロードができる」

#### 成果物
- Streamlit WebApp（Cloud Runデプロイ）
- ダッシュボード / レコード一覧 / レコード詳細 / 検索 / アップロード画面
- 解析履歴の閲覧（コード+グラフ付き）

#### タスク

**Issue: Streamlit基盤**
- Cloud Run デプロイ設定
- 認証（Streamlit Authenticator or Basic Auth）
- SDK統合（`Lab` クラスをStreamlitから呼び出し）
- 受け入れ条件: ブラウザでログインしてダッシュボードが表示される

**Issue: ダッシュボード + レコード一覧**
- チーム統計（総レコード数、今週の登録数）
- 最近のレコード一覧
- フィルタ（タイプ、ステータス、タグ）、ソート
- 受け入れ条件: レコード一覧がフィルタ付きで表示される

**Issue: レコード詳細 + 解析履歴**
- メタデータ表示（conditions, results）
- ファイル一覧 + プレビュー（テキスト、画像、CSV先頭行）
- サブレコード一覧
- セルログの時系列表示
- 解析履歴タブ（コードのシンタックスハイライト + 生成グラフの画像表示）
- 受け入れ条件: レコードの全情報が1画面で閲覧可能

**Issue: 検索 + アップロード**
- セマンティック検索 + フィルタ
- ファイルアップロード（ID入力 → ファイルドロップ）
- 装置PC向けシンプルモード
- 受け入れ条件: Pythonなし環境のブラウザからファイルアップロードが完了

#### 期間
- 2週間

---

### M8: 拡張・安定化（Week 13+）

- BigQuery連携（Firestoreの自動エクスポート設定）
- LLMチャット（WebApp上。Gemini統合）
- FAIR対応（ライセンス、DOI）
- パフォーマンスチューニング
- ドキュメント整備

---

## 3. MVP定義（最終版）

### MVPの判定基準

**「チーム（研究室メンバー2-3名）が日常の実験記録に使い始められる」**

### MVPに含むもの

| 機能 | 理由 |
|------|------|
| SDK Core（Lab, Record, add, save, sub, search） | 核心機能。これがないと何も始まらない |
| IPython hooks自動ログ | 最大の差別化。「手間ゼロ」がなければMLflow/W&Bで十分 |
| ローカルバッファ | 「データが消えるかも」の恐怖があると誰も使わない |
| 機微情報フィルタ | セキュリティ必須。なしだとパスワード漏洩リスク |
| セマンティック検索 | LLMによるデータ活用の基盤 |
| MCP Server（検索・閲覧11ツール） | Claude Desktop/Codeからの利用。「LLMが使える」がTier 1要件 |
| CLI基本コマンド | 装置PCなど非Notebook環境からの操作 |
| ソフトデリート | 誤削除防止。安心して使える基盤 |
| テンプレート（基本） | 繰り返し実験の効率化 |

### MVPに含まないもの（判断理由付き）

| 機能 | 判断 | 理由 |
|------|------|------|
| **execute_code / batch_execute** | **MVP後** | 強力だが複雑。サンドボックス構築に時間がかかる。MVPではLLMは検索・閲覧に専念。コード実行はユーザーのローカル環境で手動実行 |
| **自動処理トリガー（8c）** | **MVP後** | Cloud Functions追加開発が必要。MVPではプレビュー/サムネイルなしでも運用可能 |
| **WebApp** | **MVP後** | SDK + CLI + MCP で基本フローが成立。ブラウザUIはUX改善であり必須ではない |
| **Nextcloud同期ポーラー** | **MVP後** | SDK/CLI経由が主経路。Nextcloudブラウザ投入は緊急時の代替 |
| **バッチ操作（sweep等）** | **MVP後** | 便利機能。手動で子レコード作成すれば代替可能 |
| **エクスポート/バックアップ** | **MVP後** | Firestore + Nextcloudにデータがあるので即座の消失リスクは低い |
| **BigQuery連携** | **MVP後** | Firestoreの直接クエリで当面十分 |
| **FAIR対応** | **MVP後** | 規模拡大後に対応 |

### MVP完了条件

1. `pip install mdxdb` でインストール可能
2. 3行でレコード作成・ファイル保存ができる
3. Notebookで全セル実行が自動記録される
4. ネットワーク切断時もデータが消えない（ローカルバッファ）
5. パスワード等の機微情報が自動マスクされる
6. Claude DesktopからMCP経由で「○○の実験を探して」が動く
7. チームメンバー（2-3名）が1週間使って致命的問題がない

---

## 4. 技術POC一覧（M0で検証すべきこと）

### POC-1: Firestore Vector Search の性能

| 項目 | 内容 |
|------|------|
| **検証内容** | テストデータ1K/10K/50K件で768次元ベクトルのVector Search応答時間。team_idフィルタ付き |
| **合格ライン** | 10K件で200ms以下、50K件で500ms以下 |
| **NGライン** | 10K件で1000ms超過 |
| **フォールバック** | Pinecone Serverless（月$0〜。1Mベクトルまで無料枠）or Weaviate Cloud |
| **検証コード** | 768次元ランダムベクトル投入 → cosine検索 + team_idフィルタ → レイテンシ計測 |
| **所要時間** | 1日 |

### POC-2: IPython hooks の安定性

| 項目 | 内容 |
|------|------|
| **検証内容** | JupyterLab, Google Colab, VS Code Notebook の3環境で `pre_run_cell` / `post_run_cell` の動作確認 |
| **合格ライン** | 3環境中2環境以上で安定動作（フック発火、namespace取得成功、50変数でオーバーヘッド5ms以下） |
| **NGライン** | JupyterLabで動作しない（メイン環境で使えない） |
| **フォールバック** | JupyterLab拡張（TypeScript）でのセル実行キャプチャ。ただし開発コスト大。最悪の場合 `exp.snapshot()` 手動方式に退行 |
| **検証コード** | 各環境でフック登録 → セル5つ実行 → CellLog 5件生成確認 → オーバーヘッド計測 |
| **所要時間** | 1日 |

### POC-3: execute_code のサンドボックス実行方式

| 項目 | 内容 |
|------|------|
| **検証内容** | Cloud Run Jobs / Cloud Functions Gen2 でのPythonコード実行。gVisorサンドボックスの有効性 |
| **合格ライン** | scipy.optimize.curve_fit を含むコードが10秒以内に完了。ネットワーク遮断状態で外部通信不可 |
| **NGライン** | 実行に30秒以上。またはサンドボックス突破可能 |
| **フォールバック** | Docker-in-Docker方式（Cloud Runインスタンス内でDockerコンテナ起動）。セキュリティは高いが遅い |
| **補足** | MVP後の機能だが、設計に影響するためM0で方式だけ検証 |
| **所要時間** | 1日 |

### POC-4: Nextcloud WebDAV アップロード速度

| 項目 | 内容 |
|------|------|
| **検証内容** | 1MB / 10MB / 100MB / 1GB ファイルのアップロード時間。並行アップロード性能 |
| **合格ライン** | 10MB/s以上（100MBが10秒以内） |
| **NGライン** | 1MB/s未満（100MBに2分以上） |
| **フォールバック** | GCS (Google Cloud Storage) をバイナリストレージに変更。Nextcloudはブラウザ閲覧用リンクのみ |
| **検証コード** | 既存 `nc_py_api` クライアントで各サイズのファイルアップロード → 速度計測 |
| **所要時間** | 0.5日 |

### POC-5: Cloud Functions での画像リサイズ性能

| 項目 | 内容 |
|------|------|
| **検証内容** | 50MB TIFF画像の読み込み → 256x256サムネイル + 1024x1024プレビュー生成の所要時間 |
| **合格ライン** | 30秒以内（Cloud Functions Gen2、メモリ1GB） |
| **NGライン** | 540秒（Cloud Functionsタイムアウト）に近い |
| **フォールバック** | Cloud Run Jobsで処理。またはリサイズスキップ（元画像のみ保存） |
| **補足** | MVP後の機能だが、#8cの実現可能性判断のためM0で計測 |
| **所要時間** | 0.5日 |

### POC判定まとめ

| POC | 合格 | NG | フォールバック | MVP影響 |
|-----|------|----|--------------|---------|
| Firestore Vector Search | 10K件 <200ms | >1000ms | Pinecone | **高**（検索の核心） |
| IPython hooks | 2/3環境OK | JupyterLab NG | snapshot()退行 | **高**（差別化の核心） |
| execute_code sandbox | <10秒、隔離OK | >30秒 or 突破 | Docker-in-Docker | 低（MVP後） |
| Nextcloud速度 | >10MB/s | <1MB/s | GCS | **中** |
| 画像リサイズ | <30秒 | タイムアウト | Cloud Run Jobs | 低（MVP後） |

---

## 5. 「実装しながら決める」リスト

完璧を求めて実装が始まらないリスクを避けるため、以下の項目は**設計段階で確定しなくていい**。実装しながらフィードバックで決定する。

### 確定済み（これ以上議論しない）

| 項目 | 確定内容 |
|------|---------|
| SDK公開API | `Lab`, `Record`, `exp.add()`, `exp.save()`, `exp.sub()` 等。v7で型定義まで詳細化済み |
| Firestoreスキーマ | `teams/{team_id}/records/{id}` + サブコレクション（cell_logs, traces, sub_records, analyses） |
| MCPツール仕様 | 14ツールのリクエスト/レスポンス定義済み |
| アーキテクチャ | Firestore + Nextcloud + Vertex AI + Cloud Functions。Phase 1は5コンポーネント |
| WebApp技術 | Streamlit（Python統一） |
| ログの3層構造 | IPython hooks（自動）→ @exp.track（半自動）→ snapshot()（手動） |

### 実装しながら決めること

| 項目 | 初期方針 | 調整タイミング |
|------|---------|--------------|
| ローカルバッファの同期間隔 | 30秒 | M2実装時にNotebook利用体験でチューニング |
| `_summarize()` の型別シリアライズ詳細 | 基本型そのまま、ndarray→shape/dtype、DataFrame→shape/columns | M2実装時に実データで調整 |
| 機微情報フィルタのパターンリスト | `*password*`, `*secret*`, `*token*`, `*key*`, `*credential*` | Alpha利用時のフィードバックで拡充 |
| embeddingのテキスト結合方式 | `f"{title} {' '.join(tags)} {json.dumps(conditions)}"` | M3実装時にテストセットで品質計測 |
| セルログのバッチ送信サイズ | 10件 or 30秒のいずれか早い方 | M2実装時に調整 |
| テンプレートのビルトイン内容 | XRD, SEM, SQUIDの3種。条件フィールドは研究室の実データから抽出 | M1実装後、Alpha利用開始時に実データで調整 |
| CellLogのFirestoreドキュメント構造 | 1セル=1ドキュメント（サブコレクション） | M2実装時にクエリパターンで判断。100セル超のNotebookでの性能次第 |
| ソフトデリートの完全削除タイミング | 30日後。Cloud Scheduler + Cloud Functions | M6で実装 |
| ID長（4文字 vs 5文字） | 4文字で開始 | レコード数1万件超過時に5文字への拡張を検討 |
| Nextcloudのパス設計詳細 | `{group_folder}/mdxdb/{team_id}/{record_id}/{filename}` | M1実装時に確定 |

---

## 6. パッケージ名の最終候補

### 選定基準
- PyPIで空いている（`pip install` で衝突しない）
- 短く覚えやすい
- 実験データ管理ライブラリであることが直感的にわかる
- 特定プロジェクトに縛られない汎用的な名前

### 候補3つ

| # | 名前 | import文 | 特徴 | 懸念 |
|---|------|---------|------|------|
| **1** | `mdxdb` | `from mdxdb import Lab` | 現リポジトリ名に由来。短い。MDXプロジェクトとの関連が明確 | MDX固有に見える。汎用ライブラリ感が薄い。PyPIで空いているか要確認 |
| **2** | `labvault` | `from labvault import Lab` | "研究室の金庫"。実験データの安全な保管を想起。汎用的 | やや長い（8文字）。vault = HashiCorp Vaultとの混同リスク |
| **3** | `labdb` | `from labdb import Lab` | 最短。"研究室のDB"。直感的 | 既にPyPIに存在する可能性が高い。一般的すぎる |

### 推奨

**第1候補: `mdxdb`**
- 理由: 既にリポジトリ名として使用中。import文が短い。チーム内で既に認知されている
- リスク: PyPIでの空き確認が必要

**第2候補: `labvault`**
- 理由: 汎用的かつ記憶に残る。「データが安全に保管される」イメージ

**第3候補: `expdb`**
- 理由: "experiment database"の略。短い。`from expdb import Lab`

**M0のタスクとしてPyPIの空き確認を行い、最終決定する。**

---

## 依存関係グラフ

```
M0 基盤+POC (Week 1-2)
 │
 ├──→ M1 SDK Core (Week 2-4)
 │     │
 │     ├──→ M2 自動ログ+バッファ (Week 4-5)
 │     │     │
 │     │     ├──→ M3 Embedding+Search (Week 5-6)
 │     │     │     │
 │     │     │     ├──→ M4 MCP+CLI (Week 6-7)
 │     │     │     │     │
 │     │     │     │     │   ★ MVP (Week 7)
 │     │     │     │     │
 │     │     │     │     ├──→ M5 LLMコード実行+トリガー (Week 8-9)
 │     │     │     │     │
 │     │     │     │     ├──→ M6 拡張機能 (Week 9-11)
 │     │     │     │     │
 │     │     │     │     └──→ M7 WebApp (Week 11-13)
 │     │     │     │           │
 │     │     │     │           └──→ M8 BigQuery等 (Week 13+)
```

### 並行実行可能な組み合わせ

| ペア | 条件 |
|------|------|
| M1のRecordモデル と M1のFirestoreBackend | モデルのインターフェース確定後 |
| M4のCLI と M4のMCPサーバー | SDKの検索APIが共通基盤 |
| M5のexecute_code と M5の自動トリガー | 独立した機能 |
| M6のバッチ と M6のエクスポート | 独立した機能 |
| M7の各Streamlit画面 | 独立したページ |

---

## 付録: ステージング計画

| ステージ | 時期 | 対象ユーザー | 使える機能 | フィードバック方法 |
|---------|------|------------|-----------|-----------------|
| **POC** | Week 1-2 | 開発者のみ | 技術検証 | -- |
| **Alpha** | Week 7 (MVP) | 開発者 + メンバー2-3名 | SDK + CLI + MCP | GitHub Issues / Slack |
| **Beta** | Week 13 (WebApp完成) | 研究室全員（5-10名） | 全機能 | WebApp上のフィードバックフォーム |
| **GA** | Week 16+ | 他チーム・外部 | 全機能 + ドキュメント | 公式ドキュメント + サポート |

### Alpha（Week 7〜）利用イメージ

```
実験者A:
  pip install mdxdb && mdxdb init
  → JupyterでNotebook実行 → 全セル自動記録

解析者B:
  Claude Desktop にMCP接続
  → 「今週のXRD実験で結晶性が良かったのは？」→ 即座に回答

PI（教員）:
  Claude Desktop から
  → 「今月のチーム全体の進捗をまとめて」→ 横断サマリー
```

### オンボーディング必要物

| ステージ | ドキュメント |
|---------|------------|
| Alpha | クイックスタート（5分で使い始める手順）、Claude Desktop MCP設定手順 |
| Beta | WebApp利用ガイド、装置PCからのアップロード手順、FAQ |
| GA | 完全ドキュメント、APIリファレンス、テンプレートカタログ |
