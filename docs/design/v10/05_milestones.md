# v10 実装マイルストーン

> 実験物理学者・Pythonプロフェッショナルの視点で優先順位付け。
> 原則: **早く使い始められる → フィードバックで改善** のループを最速で回す。
> 開発体制: 開発者1名 + Claude Code。

---

## 優先順位の考え方

**実験物理学者の視点**: 「明日から使える」が最優先。装置制御→測定→解析の一連のフローが動くことが導入の鍵。テンプレートやLLM連携は「データが溜まってから」で十分。

**Pythonプロフェッショナルの視点**: テスト基盤（InMemoryBackend）を最初に作る。型安全性とプロトコル設計を固めてから機能を積む。GCP依存は後回しにし、ローカルで完結する状態を早期に作る。

**統合方針**: GCPなしでローカル完結する状態を最速で作り（M1）、そこにリモート同期を載せる（M2）。IPython hooksとローカルバッファが動けば、実験者はその日から使い始められる。

---

## 全体タイムライン

```
Week 1-2:   M0 プロジェクト基盤
Week 2-4:   M1 SDK Core（ローカル完結）      ← ★ ここで実験者が使い始められる
Week 4-5:   M2 リモート同期 + 自動ログ
Week 5-6:   M3 テンプレート + パーサー
Week 6-8:   M4 Embedding + 検索 + MCP
Week 8:     ★ MVP完成（チームAlpha利用開始）
Week 8-10:  M5 拡張（バッチ, エクスポート, コード実行）
Week 10-12: M6 WebApp + 運用整備
```

---

## M0: プロジェクト基盤（Week 1-2）

### ゴール
> pyproject.toml が v10 確定版になり、`pip install -e ".[dev]"` でインストール可能。テスト・lint が CI で通る。

### タスク

- [ ] **pyproject.toml を v10 確定版に更新**
  - `google-cloud-aiplatform` を除外（REST API直接に移行）
  - `google-auth` を gcp extra に追加
  - `pytest-asyncio` を除外（全sync化）
  - ruff select に `B`, `SIM`, `RUF` 追加
  - CLI エントリポイントを `labvault.cli.main:cli` に修正
- [ ] **ディレクトリ構造の作成**
  ```
  src/labvault/
  ├── __init__.py          # Lab, Record をre-export
  ├── py.typed
  ├── core/
  │   ├── __init__.py
  │   ├── config.py        # Settings (pydantic-settings)
  │   ├── lab.py           # Lab クラス
  │   ├── record.py        # Record クラス
  │   ├── types.py         # Status, RecordType, Note, Link, DataRef, CellLog 等
  │   ├── id.py            # Crockford's Base32 ID生成
  │   └── exceptions.py    # LabvaultError, LabvaultPermissionError 等
  ├── backends/
  │   ├── __init__.py
  │   ├── base.py          # MetadataBackend, StorageBackend, SearchBackend Protocol
  │   └── memory.py        # InMemoryMetadataBackend, InMemoryStorageBackend, InMemorySearchBackend
  ├── tracking/
  │   ├── __init__.py
  │   └── (M2で実装)
  ├── buffer/
  │   ├── __init__.py
  │   └── (M1で実装)
  ├── parsers/
  │   ├── __init__.py
  │   └── (M3で実装)
  └── cli/
      ├── __init__.py
      └── (M4で実装)
  tests/
  ├── conftest.py          # lab fixture (InMemoryBackend)
  ├── unit/
  └── integration/
  ```
- [ ] **CI設定（GitHub Actions）**: lint (ruff check + ruff format --check + mypy) + test (pytest)
- [ ] **例外クラス定義**: `LabvaultError`, `RecordNotFoundError`, `LabvaultPermissionError`, `SyncError`, `BackendError`, `ValidationError`
- [ ] **Backend Protocol定義（全sync）**: `MetadataBackend`, `StorageBackend`, `SearchBackend`
- [ ] **InMemoryBackend実装**: テストの基盤。全Protocolメソッドをメモリ上で実装
- [ ] **conftest.py**: `lab` fixture（InMemoryBackend）、`sample_record` fixture

### 完了条件
- `pip install -e ".[dev]"` が成功
- `pytest` が通る（テストケースは空でもOK）
- `ruff check` + `mypy` がエラーなし

---

## M1: SDK Core — ローカル完結（Week 2-4）

### ゴール
> GCPなしで `lab.new()` → `exp.conditions()` → `exp.add()` → `exp.results` → `exp.close()` が動く。InMemoryBackendでテスト完結。**実験者がこの時点で使い始められる。**

### タスク

- [ ] **types.py**: Status, RecordType, Note, Link, DataRef, ExternalRef, CellLog の dataclass
- [ ] **id.py**: Crockford's Base32 IDジェネレーター（4文字）+ normalize_id
- [ ] **config.py**: Settings (pydantic-settings)。環境変数 → config.toml → デフォルトの優先順位
- [ ] **record.py**: Record クラス
  - プロパティ: id, title, type, status, tags, notes, results, conditions
  - メソッド: conditions(), tag(), untag(), note(), close()
  - メソッドチェーン対応（全メソッドが self を返す）
  - コンテキストマネージャ（`with lab.new() as exp:`）
  - _ResultsProxy（dict-like アクセス）
  - **セル再実行の冪等性**: note() は同一テキスト重複防止
- [ ] **lab.py**: Lab クラス
  - new(), get(), list(), search(), recent(), today()
  - delete(), trash(), restore()
  - close(), \_\_enter\_\_, \_\_exit\_\_
  - `get(id, auto_log=True)` のシグネチャ（実装はM2）
- [ ] **record.py データ操作**: add(), add_dir(), save(), get_data(), list_data(), add_ref()
  - **add() の冪等性**: 同一ファイル（SHA256比較）の重複防止
  - save() の型自動判定（dict→JSON, ndarray→npy, DataFrame→CSV, Figure→PNG）
- [ ] **record.py 構造管理**: sub(), children(), link()
- [ ] **record.py 装置制御API**: log_value(), log_event()
- [ ] **buffer/sqlite.py**: ローカルバッファ（SQLite WAL）
  - pending_records, pending_files, pending_cell_logs テーブル
  - busy_timeout=5000
  - schema_version + マイグレーション機構
- [ ] **テスト**: Record CRUD、メソッドチェーン、コンテキストマネージャ、add/save/add_ref、sub/link、冪等性

### 完了条件
```python
from labvault import Lab
lab = Lab("test", metadata_backend=InMemoryMetadataBackend())
exp = lab.new("XRD測定")
exp.conditions(temperature_C=500)
exp.add("data.csv")
exp.results["lattice_a"] = 2.873
exp.tag("XRD")
exp.status = "success"
assert lab.get(exp.id).results["lattice_a"] == 2.873
```

---

## M2: リモート同期 + IPython hooks（Week 4-5）

### ゴール
> Firestore/Nextcloud連携。Notebookで `lab.new()` → 全セル自動記録 → Firestoreに同期。

### タスク

- [ ] **backends/firestore.py**: FirestoreBackend（同期クライアント）
- [ ] **backends/nextcloud.py**: NextcloudStorage（nc-py-api）
- [ ] **buffer/sync.py**: SyncManager
  - daemonスレッド + atexit登録
  - 指数バックオフリトライ（max 3回）
  - `lab.sync_status` プロパティ
  - **Notebook特化通知**: オフライン遷移時にIPython display hookでバナー表示
- [ ] **tracking/cell_tracker.py**: CellTracker（IPython hooks）
  - pre_run_cell / post_run_cell フック
  - **namespace diff**: id() + _shallow_digest()（ndarray, DataFrame対応）
  - namespaceフィルタ: `_` 始まり、モジュール、関数を除外
  - 機微情報マスク（*password*, *secret*, *token* 等）
  - **セッション分離**: Notebook名 + カーネルIDで自動グループ化
  - **セルログの冪等性**: execution_countベースで上書き更新
- [ ] **tracking/summarize.py**: _summarize() 関数（型別サマリー生成）
- [ ] **tracking/sensitive.py**: 機微情報フィルタ
- [ ] **lab.py 拡張**:
  - `lab.new()` でIPython hooks自動起動 + 前tracker自動deactivate + 通知表示
  - `lab.get(id, auto_log=True)` で既存Recordにhooks追記
  - `lab.active` プロパティ（現在アクティブなRecord）
- [ ] **record.py 拡張**: pause_logging(), resume_logging(), no_logging(), snapshot(), @exp.track
- [ ] **backends/embedding.py**: Vertex AI text-embedding-004 REST API直接呼び出し（httpx + google-auth）
- [ ] **テスト**: IPython hooks（ipython in-process kernel）、SyncManager、FirestoreBackend（integration_remote）、冪等性

### 完了条件
- Notebook で `lab.new()` → セル実行 → CellLog が Firestore に保存される
- `exp.add("file")` → Nextcloud にアップロードされる
- ネットワーク切断時にローカルバッファに蓄積 → 復帰時に自動同期

---

## M3: テンプレート + ファイルパーサー（Week 5-6）

### ゴール
> テンプレートで条件入力の品質を担保。.rasファイルから測定条件を自動抽出。

### タスク

- [ ] **core/types.py 拡張**: ConditionField, TemplateV10 dataclass
- [ ] **テンプレートシステム**:
  - lab.define_template(), lab.templates()
  - required_conditions + close()時の警告（warnings.warn）
  - aliases による条件キー自動正規化
  - indexed_fields（Firestoreトップレベル昇格用。idx_ プレフィックス）
  - ビルトイン5種: XRD, SEM, SQUID, TEM, Raman
- [ ] **parsers/base.py**: FileParser Protocol, ParseResult, ParserRegistry
- [ ] **parsers/builtin/ras.py**: Rigaku XRD .ras パーサー
- [ ] **parsers/builtin/tiff_sem.py**: SEM TIFF EXIFメタデータ抽出
- [ ] **record.py 統合**: add() でパーサー自動起動（手動入力優先）
- [ ] **テスト**: テンプレート適用、aliases正規化、required_conditions警告、パーサー

### 完了条件
```python
exp = lab.new("XRD測定", template="XRD")
exp.add("FeCr.ras")  # → conditionsに target, voltage_kV 等が自動抽出
exp.status = "success"
# → UserWarning: 必須条件 scan_speed_deg_per_min が未入力です
```

---

## M4: Embedding + 検索 + MCP + CLI（Week 6-8）

### ゴール
> セマンティック検索が動く。Claude Desktop から MCP 経由でデータ検索できる。CLIで基本操作。

### タスク

- [ ] **Embedding統合**: Record保存時にembedding_textを生成 → Vertex AI REST API → Firestoreに保存
- [ ] **Firestore Vector Search**: lab.search() でセマンティック検索
- [ ] **Cloud Functions embedding_generator**: SDK非経由投入用フォールバック
- [ ] **CLI**: labvault init / new / add / list / show / search / url / team
  - labvault doctor（設定の健全性チェック）
  - labvault team export-config（学生配布用）
- [ ] **labvault-platform リポジトリ作成**:
  - MCPサーバー（Cloud Functions Gen2, FastMCP, 8ツール）
  - 各ツールに200-300文字のdescription
  - IAM + APIキー二重認証
  - Cloud Scheduler + Firestore日次バックアップ
  - 予算アラート + エラー率アラート
- [ ] **テスト**: 検索、MCP各ツール（FastMCPテストクライアント）

### 完了条件
- `lab.search("結晶性が良い薄膜")` で関連レコードが返る
- Claude Desktop から「Fe-Crの実験を探して」が動く
- `labvault new "XRD" --template XRD && labvault add AB3F data.ras` が動く

### ★ MVP完成（Week 8）→ チームAlpha利用開始

---

## M5: 拡張機能（Week 8-10）

- [ ] ProcessChain（lab.new_chain(), chain.next()）
- [ ] エクスポート（lab.export()）
- [ ] バッチ測定対応（lab.new_batch()）
- [ ] execute_code MCPツール（Cloud Functions内subprocess）
- [ ] nextcloud_poller（_inbox検出 + パーサー適用）
- [ ] 追加パーサー: .dm3, .dat(MPMS/PPMS), .wdf(Raman)
- [ ] マイグレーションスクリプト（旧mdxdb → labvault）

## M6: WebApp + 運用整備（Week 10-12）

- [ ] Streamlit WebApp（Cloud Run）
- [ ] ダッシュボード / レコード詳細 / 検索 / アップロード
- [ ] 運用ドキュメント（Nextcloudグループフォルダ設定、卒業時引き継ぎ手順）
- [ ] PyInstallerバイナリ（Windows装置PC用CLI）

---

## 依存関係グラフ

```
M0 基盤
 │
 └──→ M1 SDK Core（ローカル完結）  ← ★ 実験者が使い始める
       │
       ├──→ M2 リモート同期 + IPython hooks
       │     │
       │     ├──→ M3 テンプレート + パーサー
       │     │     │
       │     │     └──→ M4 Embedding + MCP + CLI  ← ★ MVP
       │     │           │
       │     │           ├──→ M5 拡張機能
       │     │           └──→ M6 WebApp
       │     │
       │     └──（M2完了時点でNotebook自動ログが動く）
       │
       └──（M1完了時点でファイル保存+条件記録が動く）
```
