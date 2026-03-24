# v9 テスト戦略書

> 作成日: 2026-03-17
> 対象: labvault v9（REQUIREMENTS.md R01-R22）

---

## 1. テスト方針

### 基本原則

1. **InMemoryBackendで全ユニット・統合テストがオフライン動作** — 実Firestore/Nextcloud接続なしでCIが回る
2. **実Firestore/Nextcloud接続テストはCI/CDの別ジョブ**（`@pytest.mark.integration_remote`）— 手動トリガー or nightly
3. **カバレッジ目標: 80%以上**（`src/labvault/` 配下）
4. **テスト実行コマンド**: `pytest`（pyproject.tomlで設定済み、`--cov=labvault --cov-report=term-missing`）
5. **全テストがCI上で60秒以内に完了**（InMemoryBackend使用時）

### テストピラミッド

```
        ┌─────────┐
        │  E2E    │  ← 少数（Notebook→MCP一気通貫）
       ┌┴─────────┴┐
       │ 統合テスト │  ← Lab→Record→Backend の結合
      ┌┴───────────┴┐
      │ ユニットテスト│  ← 大多数（モデル、関数、フィルタ）
      └─────────────┘
```

---

## 2. テストカテゴリ

### 2.1 ユニットテスト（`tests/unit/`）

InMemoryBackendまたはモック使用。外部依存なし。

| ファイル | 対象 | 要件 |
|---------|------|------|
| `test_record_model.py` | Record生成・シリアライズ・デシリアライズ | R01, R05 |
| `test_id_generator.py` | Crockford's Base32 IDジェネレーター | R03 |
| `test_settings.py` | Settings（環境変数 / config.toml / デフォルト） | R07 |
| `test_summarize.py` | `_summarize()` 関数（各型の要約） | R13 |
| `test_sensitive_filter.py` | 機微情報フィルタ | R13 |
| `test_local_buffer.py` | ローカルバッファ（SQLite CRUD） | R08 |
| `test_record_operations.py` | tag/untag/note/status/conditions/results | R04 |
| `test_sub_record.py` | 子レコード作成・階層構造 | R02 |
| `test_data_ref.py` | add_ref（大容量参照・DOIリンク） | R09 |
| `test_template.py` | テンプレート定義・適用・ビルトイン | R11 |
| `test_soft_delete.py` | ソフトデリート・復元ロジック | R06 |
| `test_serializer.py` | RecordSerializer（Firestore dict変換） | R01 |
| `test_cell_log_model.py` | CellLogデータモデル | R13 |
| `test_trace_model.py` | TraceLog（@exp.track）データモデル | R13 |
| `test_auth.py` | 認証ヘルパー・トークン検証 | R18 |

### 2.2 統合テスト（`tests/integration/`）

InMemoryBackendでの結合テスト + `@pytest.mark.integration_remote` で実バックエンド。

| ファイル | 対象 | 要件 |
|---------|------|------|
| `test_lab_crud.py` | Lab → Record → Backend の全CRUD | R01, R07 |
| `test_lab_search.py` | Lab.search()（テキスト＋セマンティック） | R14 |
| `test_file_upload.py` | Record.add() → Nextcloud アップロード/ダウンロード | R09 |
| `test_ipython_hooks.py` | IPython hooks → CellLog → Backend保存 | R13 |
| `test_buffer_sync.py` | ローカルバッファ → リモート同期 | R08 |
| `test_template_integration.py` | テンプレート適用 → Record作成 → 条件自動設定 | R11 |
| `test_soft_delete_integration.py` | ソフトデリート → ゴミ箱一覧 → 復元 | R06 |
| `test_sub_record_integration.py` | 親Record → 子Record → 孫Record のCRUD | R02 |
| `test_track_decorator.py` | @exp.track → traces保存 → 取得 | R13 |
| `test_snapshot.py` | exp.snapshot() → キャプチャ保存 | R13 |
| `test_team_management.py` | チーム作成・メンバー管理・ロール | R19 |
| `test_visibility.py` | team/private の可視性制御 | R18 |

### 2.3 MCPサーバーテスト（`tests/mcp/`）

FastMCPのテストクライアントを使用。実Cloud Functionsへの接続は不要。

| ファイル | 対象 | 要件 |
|---------|------|------|
| `test_mcp_search.py` | `search` ツール（ハイブリッド検索） | R14, R15 |
| `test_mcp_get_detail.py` | `get_detail` ツール（L1/L2/L3詳細度） | R15 |
| `test_mcp_compare.py` | `compare` ツール（複数レコード比較） | R15 |
| `test_mcp_data_preview.py` | `data_preview` ツール（統計サマリー） | R15 |
| `test_mcp_get_results.py` | `get_results` ツール（横断検索） | R15 |
| `test_mcp_aggregate.py` | `aggregate` ツール（数値集約） | R15 |
| `test_mcp_timeline.py` | `get_timeline` ツール | R15 |
| `test_mcp_trace.py` | `get_trace` ツール | R15 |
| `test_mcp_explain.py` | `explain_result` ツール | R15 |
| `test_mcp_compare_runs.py` | `compare_runs` ツール | R15 |
| `test_mcp_notebook_log.py` | `get_notebook_log` ツール | R15 |
| `test_mcp_execute.py` | `execute_code` / `batch_execute` / `get_image` | R16 |
| `test_mcp_auth.py` | 認証テスト（有効/無効/期限切れトークン） | R18 |
| `test_mcp_errors.py` | エラーケース（不正ID、権限不足、不正パラメータ） | R15 |

### 2.4 E2Eテスト（`tests/e2e/`）

実際の利用フローを一気通貫でテスト。CIでは `@pytest.mark.e2e` でスキップ可。

| ファイル | 対象 | 要件 |
|---------|------|------|
| `test_notebook_flow.py` | Notebook → Lab.new() → セル実行 → CellLog保存 → MCP search → get_detail | R07, R13, R14, R15 |
| `test_cli_flow.py` | CLI → `labvault new` → `labvault add` → `labvault search` → `labvault show` | R10 |
| `test_multi_pc_flow.py` | PC-A: Lab.new() → ID取得 → PC-B: `labvault add <ID> <file>` → 統合確認 | R03 |
| `test_offline_recovery.py` | オフラインで add() → ネットワーク復帰 → 自動同期確認 | R08 |

---

## 3. テストインフラ

### 3.1 テストフレームワーク・ツール

| ツール | 用途 |
|--------|------|
| `pytest` | テストランナー |
| `pytest-cov` | カバレッジ計測 |
| `pytest-asyncio` | 非同期テスト（Cloud Functions, MCP） |
| `pytest-mock` | モック/スタブ |
| `pytest-timeout` | テストタイムアウト（デフォルト30秒） |

### 3.2 InMemoryBackend

全テストの基盤。Firestore/Nextcloud APIと同じインターフェースをメモリ上で実装。

```python
class InMemoryBackend:
    """Firestore互換のインメモリバックエンド"""
    def __init__(self):
        self.records: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}
        self.templates: dict[str, dict] = {}
        self.teams: dict[str, dict] = {}

    # FirestoreBackendと同じメソッドシグネチャ
    async def create_record(self, team_id, record) -> str: ...
    async def get_record(self, team_id, record_id) -> dict: ...
    async def list_records(self, team_id, **filters) -> list[dict]: ...
    async def update_record(self, team_id, record_id, data) -> None: ...
    async def delete_record(self, team_id, record_id) -> None: ...
    async def search(self, team_id, query, limit) -> list[dict]: ...

class InMemoryStorage:
    """Nextcloud互換のインメモリストレージ"""
    async def upload(self, path, data) -> str: ...
    async def download(self, path) -> bytes: ...
    async def delete(self, path) -> None: ...
    async def list_files(self, path) -> list[str]: ...
```

### 3.3 conftest.py 共通fixture設計

```python
# tests/conftest.py

@pytest.fixture
def memory_backend():
    """InMemoryBackendインスタンス"""
    return InMemoryBackend()

@pytest.fixture
def memory_storage():
    """InMemoryStorageインスタンス"""
    return InMemoryStorage()

@pytest.fixture
def lab(memory_backend, memory_storage):
    """テスト用Labインスタンス（InMemoryBackend）"""
    return Lab("test-team", backend=memory_backend, storage=memory_storage)

@pytest.fixture
def sample_record(lab):
    """テスト用Record（基本的な実験レコード）"""
    exp = lab.new("Fe-10Cr XRD測定", type="experiment")
    exp.conditions(temperature_C=500, pressure_Pa=1e-3)
    exp.tag("XRD", "Fe-Cr", "thin-film")
    exp.note("テスト用サンプルレコード")
    return exp

@pytest.fixture
def sample_record_with_sub(sample_record):
    """子レコード付きのRecord"""
    sub = sample_record.sub("SEM観察", type="measurement")
    sub.conditions(magnification=50000, voltage_kV=15)
    return sample_record

@pytest.fixture
def tmp_sqlite(tmp_path):
    """一時SQLiteバッファDB"""
    return tmp_path / "buffer.db"

# tests/integration/conftest.py
@pytest.fixture
def firestore_lab():
    """実Firestore接続のLabインスタンス（integration_remoteマーク用）"""
    ...

# tests/mcp/conftest.py
@pytest.fixture
def mcp_client(lab):
    """FastMCPテストクライアント"""
    ...
```

### 3.4 GitHub Actions CI設定

```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  unit-integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest tests/unit/ tests/integration/ tests/mcp/ --cov=labvault --cov-report=xml
      - uses: codecov/codecov-action@v4

  e2e:
    runs-on: ubuntu-latest
    if: github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest tests/e2e/ -m e2e

  remote-integration:
    runs-on: ubuntu-latest
    if: github.event_name == 'workflow_dispatch' || github.event.schedule
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest tests/integration/ -m integration_remote
    env:
      GOOGLE_APPLICATION_CREDENTIALS: ${{ secrets.GCP_SA_KEY }}
      LABVAULT_NEXTCLOUD_URL: ${{ secrets.NEXTCLOUD_URL }}
      LABVAULT_NEXTCLOUD_USER: ${{ secrets.NEXTCLOUD_USER }}
      LABVAULT_NEXTCLOUD_PASSWORD: ${{ secrets.NEXTCLOUD_PASSWORD }}
```

### 3.5 pytestマーカー

```python
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "integration_remote: 実Firestore/Nextcloud接続が必要なテスト",
    "e2e: エンドツーエンドテスト",
    "slow: 実行に10秒以上かかるテスト",
]
```

---

## 4. テストケース詳細一覧

### 4.1 ユニットテスト

#### test_record_model.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_record_create_minimal` | 最小パラメータでRecord作成 | id, title, created_atが設定される | R05 |
| `test_record_create_full` | 全フィールド指定でRecord作成 | 全フィールドが正しく保持される | R05 |
| `test_record_serialize_to_dict` | RecordをFirestore用dictに変換 | datetimeがISO文字列、ndarrayが除外 | R01 |
| `test_record_deserialize_from_dict` | dictからRecord復元 | 全フィールドが元の値と一致 | R01 |
| `test_record_type_variants` | type="experiment"/"sample"/"process"等 | 任意の文字列typeが許容される | R05 |
| `test_record_status_transitions` | running→success/failed/partial | 各ステータス遷移が可能 | R04 |
| `test_record_updated_at_auto` | フィールド変更時にupdated_at更新 | タイムスタンプが最新に更新される | R01 |
| `test_record_method_chain` | `exp.tag().note().conditions()` | 全メソッドがselfを返す | R07 |
| `test_record_context_manager` | `with lab.new() as exp:` | __enter__でRecord、__exit__で自動保存 | R07 |

#### test_id_generator.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_generate_id_length` | 生成IDが4文字 | len(id) == 4 | R03 |
| `test_generate_id_charset` | Crockford's Base32文字のみ | 全文字が[0-9A-HJKMNP-TV-Z]に含まれる | R03 |
| `test_generate_id_uniqueness` | 1000回生成して重複なし | len(set(ids)) == 1000 | R03 |
| `test_generate_id_collision_retry` | 既存IDと衝突時にリトライ | 2回目の生成で別IDが返る | R03 |
| `test_generate_id_no_ambiguous_chars` | I/L/O/U を含まない | 紛らわしい文字が排除されている | R03 |
| `test_generate_id_uppercase` | 大文字のみ | id == id.upper() | R03 |

#### test_settings.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_settings_from_env` | 環境変数から読み込み | LABVAULT_TEAMが反映される | R07 |
| `test_settings_from_config_toml` | ~/.labvault/config.toml から読み込み | team, gcp_projectが反映される | R07 |
| `test_settings_default_values` | デフォルト値 | buffer_sync_interval=30等 | R07 |
| `test_settings_priority` | 環境変数 > config.toml > デフォルト | 環境変数が最優先 | R07 |
| `test_settings_missing_required` | 必須項目欠落でエラー | 適切なエラーメッセージ | R07 |
| `test_settings_config_path_override` | LABVAULT_CONFIG_PATHで設定ファイルパス変更 | 指定パスから読み込み | R07 |

#### test_summarize.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_summarize_int` | int型 | そのまま返却 | R13 |
| `test_summarize_float` | float型 | そのまま返却 | R13 |
| `test_summarize_str` | str型（短い） | そのまま返却 | R13 |
| `test_summarize_str_long` | str型（1KB超） | 先頭500文字 + "..." で切り詰め | R13 |
| `test_summarize_bool` | bool型 | そのまま返却 | R13 |
| `test_summarize_ndarray` | numpy.ndarray | `"<ndarray shape=(M,N) dtype=float64>"` | R13 |
| `test_summarize_dataframe` | pandas.DataFrame | `"<DataFrame (100 x 5) columns=[a, b, c, d, e]>"` | R13 |
| `test_summarize_list` | list（短い） | 要素数 + 先頭3要素プレビュー | R13 |
| `test_summarize_dict` | dict（短い） | キー数 + 先頭3キープレビュー | R13 |
| `test_summarize_figure` | matplotlib.Figure | `"<Figure 800x600>"` | R13 |
| `test_summarize_unknown_type` | カスタムクラス | `"<ClassName>"` | R13 |
| `test_summarize_size_limit` | 1KB超のオブジェクト | 結果が1KB以内に収まる | R13 |

#### test_sensitive_filter.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_filter_password_var` | `password = "secret"` | `"***REDACTED***"` に置換 | R13 |
| `test_filter_api_key_var` | `api_key = "sk-123"` | `"***REDACTED***"` に置換 | R13 |
| `test_filter_token_var` | `access_token = "abc"` | `"***REDACTED***"` に置換 | R13 |
| `test_filter_secret_var` | `my_secret = "xyz"` | `"***REDACTED***"` に置換 | R13 |
| `test_filter_credential_var` | `db_credential = "..."` | `"***REDACTED***"` に置換 | R13 |
| `test_filter_url_with_auth` | `https://user:pass@host/` | `"https://***@host/"` | R13 |
| `test_filter_os_environ` | `os.environ` 参照 | 除外される | R13 |
| `test_filter_pydantic_settings` | pydantic Settingsインスタンス | 除外される | R13 |
| `test_filter_normal_var_not_affected` | `temperature = 300` | そのまま保持 | R13 |
| `test_filter_exclude_vars` | `exp.exclude_vars("my_var")` | 指定変数が除外される | R13 |
| `test_filter_case_insensitive` | `API_KEY`, `Api_Key` | 全パターンでマスクされる | R13 |

#### test_local_buffer.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_buffer_create_tables` | SQLiteテーブル初期化 | pending_records/files/cell_logsテーブル存在 | R08 |
| `test_buffer_insert_record` | レコードのローカル保存 | SQLiteにレコードが保存される | R08 |
| `test_buffer_insert_file` | ファイルのローカルコピー | ローカルパスにファイルが存在 | R08 |
| `test_buffer_insert_cell_log` | セルログのローカル保存 | SQLiteにCellLogが保存される | R08 |
| `test_buffer_list_pending` | 未同期アイテム一覧 | FIFO順で返却される | R08 |
| `test_buffer_mark_synced` | 同期済みマーク | synced_atが設定される | R08 |
| `test_buffer_cleanup_old` | 同期済み7日超のデータ削除 | 古いデータが削除される | R08 |
| `test_buffer_concurrent_write` | 並行書き込み | WALモードでデッドロックしない | R08 |

#### test_record_operations.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_tag_add` | `exp.tag("XRD", "Fe-Cr")` | tagsに2つ追加 | R04 |
| `test_tag_duplicate` | 同じタグを2回追加 | 重複しない | R04 |
| `test_untag` | `exp.untag("XRD")` | tagsから削除 | R04 |
| `test_note` | `exp.note("メモ")` | notesに追加 | R04 |
| `test_note_append` | 複数回note() | 時系列で全て保持 | R04 |
| `test_status_set` | `exp.status = "success"` | ステータス変更 | R04 |
| `test_conditions_set` | `exp.conditions(T=300)` | conditionsに設定 | R04 |
| `test_conditions_update` | 既存条件の上書き | 新しい値で更新 | R04 |
| `test_results_dict_access` | `exp.results["lattice_a"] = 2.87` | dict-likeアクセス | R04 |

#### test_sub_record.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_sub_create` | `exp.sub("SEM", type="measurement")` | 子Recordが作成される | R02 |
| `test_sub_parent_id` | 子Recordのparent_id | 親のIDが設定される | R02 |
| `test_sub_nested` | 子→孫Record | 2階層目が正しく作成される | R02 |
| `test_sub_list` | 親から子一覧取得 | 子Recordがリストで返る | R02 |
| `test_sub_independent_operations` | 子Recordでtag/note/add | 親とは独立して操作可能 | R02 |

#### test_data_ref.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_add_ref_local` | `exp.add_ref(path="/data/large.h5", size_gb=8)` | data_refsに参照追加 | R09 |
| `test_add_ref_hpc` | `exp.add_ref(location="HPC:/work/data")` | location情報が保持 | R09 |
| `test_add_ref_doi` | `exp.add_ref(doi="10.5281/zenodo.12345")` | DOIリンクが保持 | R09 |
| `test_add_ref_description` | 参照に説明文を付加 | descriptionが保持 | R09 |

#### test_template.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_define_template` | テンプレート定義 | バックエンドに保存される | R11 |
| `test_apply_template` | `lab.new(template="XRD")` | デフォルト条件が設定される | R11 |
| `test_template_override` | テンプレート + 個別条件指定 | 個別指定が優先 | R11 |
| `test_template_recommended_results` | recommended_results フィールド | 推奨結果項目がRecordに設定 | R11 |
| `test_builtin_xrd` | ビルトインXRDテンプレート | 正しいデフォルト値 | R11 |
| `test_builtin_sem` | ビルトインSEMテンプレート | 正しいデフォルト値 | R11 |
| `test_builtin_squid` | ビルトインSQUIDテンプレート | 正しいデフォルト値 | R11 |

#### test_soft_delete.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_delete_sets_status` | `lab.delete(id)` | status="deleted" | R06 |
| `test_delete_sets_timestamp` | `lab.delete(id)` | deleted_atが設定される | R06 |
| `test_deleted_hidden_from_list` | 削除済みがlist()に含まれない | 通常検索から除外 | R06 |
| `test_trash_shows_deleted` | `lab.trash()` | 削除済みレコード一覧 | R06 |
| `test_restore` | `lab.restore(id)` | status復帰、deleted_at消去 | R06 |

#### test_auth.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_valid_token` | 有効なBearerトークン | 認証成功 | R18 |
| `test_invalid_token` | 無効なトークン | 認証失敗エラー | R18 |
| `test_expired_token` | 期限切れトークン | 認証失敗エラー | R18 |
| `test_role_admin` | admin権限の操作 | テンプレート管理・完全削除が可能 | R18 |
| `test_role_member` | member権限の操作 | CRUDのみ。完全削除は不可 | R18 |
| `test_visibility_team` | visibility="team" | チーム全員が閲覧可能 | R18 |
| `test_visibility_private` | visibility="private" | 作成者のみ閲覧可能 | R18 |

### 4.2 統合テスト

#### test_lab_crud.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_new_and_get` | Lab.new() → Lab.get() | 取得結果が作成時と一致 | R01, R07 |
| `test_list_all` | 複数Record作成 → Lab.list() | 全件取得 | R01 |
| `test_list_with_tag_filter` | Lab.list(tags=["XRD"]) | タグフィルタが機能 | R01, R04 |
| `test_list_with_type_filter` | Lab.list(type="experiment") | typeフィルタが機能 | R01, R05 |
| `test_list_with_status_filter` | Lab.list(status="success") | statusフィルタが機能 | R01, R04 |
| `test_list_pagination` | Lab.list(limit=5, offset=5) | ページネーション | R01 |
| `test_recent` | Lab.recent(5) | 最新5件が時系列順 | R07 |
| `test_three_line_start` | 3行コードでRecord作成 | from labvault → Lab() → lab.new() | R07 |
| `test_full_workflow` | 作成→条件設定→ファイル追加→タグ→結果→検索 | 一連の操作が正常完了 | R07 |

#### test_lab_search.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_search_by_title` | タイトルでテキスト検索 | 該当レコードが返る | R14 |
| `test_search_by_conditions` | 条件値で検索 | フィルタが機能 | R14 |
| `test_search_with_limit` | limit指定 | 指定件数以下 | R14 |
| `test_search_empty_result` | 該当なし | 空リスト | R14 |
| `test_search_semantic` | セマンティック検索（InMemoryでは簡易マッチ） | 関連レコードが返る | R14 |

#### test_buffer_sync.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_add_saves_locally_first` | exp.add() → ローカルに保存 | SQLite + ローカルファイルに即保存 | R08 |
| `test_flush_syncs_immediately` | exp.flush() | 全pending項目がリモートに同期 | R08 |
| `test_offline_accumulation` | バックエンドエラー時 | ローカルに蓄積、エラーにならない | R08 |
| `test_auto_sync_on_recovery` | バックエンド復帰時 | 蓄積データが自動同期される | R08 |
| `test_sync_fifo_order` | 複数アイテムの同期順序 | 追加順に同期 | R08 |
| `test_cell_log_batch_sync` | セルログのバッチ送信 | 複数CellLogがまとめて送信 | R08, R13 |

#### test_ipython_hooks.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_hooks_register` | IPython環境でフック登録 | pre_run_cell/post_run_cellが登録 | R13 |
| `test_cell_log_created` | セル実行後にCellLog生成 | cell_number, source, durationが設定 | R13 |
| `test_new_vars_detected` | 新規変数の検出 | new_varsに変数名と値サマリー | R13 |
| `test_changed_vars_detected` | 変更変数の検出 | changed_varsに変数名と新値サマリー | R13 |
| `test_pause_resume_logging` | pause/resumeの制御 | pause中はCellLog生成されない | R13 |
| `test_no_logging_context` | `with exp.no_logging():` | ブロック内はログなし | R13 |
| `test_sensitive_vars_masked` | 機微変数のマスク | `api_key` が `"***REDACTED***"` | R13 |

### 4.3 MCPサーバーテスト

#### test_mcp_search.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_search_text` | テキストクエリ | 関連レコードが返る | R14, R15 |
| `test_search_with_filters` | タグ・type・statusフィルタ | フィルタ適用済み結果 | R14, R15 |
| `test_search_with_limit` | limit指定 | 指定件数以下 | R15 |
| `test_search_empty` | 該当なし | 空結果 + 適切なメッセージ | R15 |
| `test_search_japanese` | 日本語クエリ | 日本語テキストで検索可能 | R14 |

#### test_mcp_get_detail.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_get_detail_l1` | L1（基本情報のみ） | title, status, tags, conditionsのみ | R15 |
| `test_get_detail_l2` | L2（+ results, data_refs） | 結果値とファイル一覧を含む | R15 |
| `test_get_detail_l3` | L3（+ cell_logs, traces） | 全セルログ・トレースを含む | R15 |
| `test_get_detail_not_found` | 存在しないID | 404相当のエラー | R15 |
| `test_get_detail_with_sub_records` | 子レコードを含む | sub_records一覧が含まれる | R15 |

#### test_mcp_auth.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_valid_bearer_token` | 有効なトークン | ツール実行成功 | R18 |
| `test_missing_token` | トークンなし | 401 Unauthorized | R18 |
| `test_invalid_token` | 不正なトークン | 401 Unauthorized | R18 |
| `test_expired_token` | 期限切れトークン | 401 Unauthorized | R18 |
| `test_wrong_team_access` | 他チームのデータアクセス | 403 Forbidden | R18 |

#### test_mcp_errors.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_invalid_record_id` | 存在しないID | 適切なエラーメッセージ | R15 |
| `test_missing_required_param` | 必須パラメータ欠落 | バリデーションエラー | R15 |
| `test_invalid_param_type` | 型不正パラメータ | バリデーションエラー | R15 |
| `test_rate_limit` | 連続リクエスト | 429 Too Many Requests | R15 |

### 4.4 E2Eテスト

#### test_notebook_flow.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_full_notebook_to_mcp` | Notebook→Lab.new()→セル実行→CellLog→MCP search→get_detail | 全フローが正常完了。MCPでセルログが取得できる | R07, R13, R14, R15 |

#### test_cli_flow.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_cli_full_workflow` | `labvault new` → `labvault add` → `labvault search` → `labvault show` | 全CLIコマンドが正常終了 | R10 |
| `test_cli_init` | `labvault init` の対話的セットアップ | config.tomlが生成される | R10 |

#### test_multi_pc_flow.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_cross_pc_data_linkage` | PC-A: lab.new() → ID → PC-B: `labvault add <ID> file` | 同一Recordにファイルが追加される | R03 |

#### test_offline_recovery.py

| テスト関数 | 検証内容 | 受け入れ条件 | 要件 |
|-----------|---------|-------------|------|
| `test_offline_add_and_sync` | オフラインでadd() → バックエンド復帰 → 自動同期 | リモートにデータが反映される | R08 |

---

## 5. テストデータ

### 5.1 テスト用Recordのfixture

```python
# tests/fixtures/records.py

SAMPLE_XRD_RECORD = {
    "title": "Fe-10Cr XRD測定",
    "type": "experiment",
    "conditions": {
        "temperature_C": 500,
        "pressure_Pa": 1e-3,
        "substrate": "Si(100)",
        "thickness_nm": 200,
    },
    "results": {
        "lattice_a": 2.873,
        "crystallinity": "good",
        "peak_2theta": [44.67, 65.02, 82.33],
    },
    "tags": ["XRD", "Fe-Cr", "thin-film"],
    "notes": ["結晶性良好。(110)ピークがシャープ"],
    "status": "success",
}

SAMPLE_SEM_RECORD = {
    "title": "Fe-10Cr SEM観察",
    "type": "measurement",
    "conditions": {
        "magnification": 50000,
        "voltage_kV": 15,
        "detector": "SE",
    },
    "tags": ["SEM", "Fe-Cr"],
    "status": "success",
}

SAMPLE_FAILED_RECORD = {
    "title": "Fe-10Cr スパッタリング（失敗）",
    "type": "process",
    "conditions": {"power_W": 300, "pressure_Pa": 5.0},
    "tags": ["sputtering", "Fe-Cr"],
    "status": "failed",
    "notes": ["ターゲット汚染のため中断"],
}

SAMPLE_CELL_LOGS = [
    {
        "cell_number": 1,
        "source": "import numpy as np\ndata = np.random.rand(100, 2)",
        "new_vars": {"data": "<ndarray shape=(100, 2) dtype=float64>"},
        "changed_vars": {},
        "duration_sec": 0.05,
    },
    {
        "cell_number": 2,
        "source": "filtered = data[data[:, 0] > 0.5]",
        "new_vars": {"filtered": "<ndarray shape=(48, 2) dtype=float64>"},
        "changed_vars": {},
        "duration_sec": 0.01,
    },
]
```

### 5.2 テスト用ファイル

| ファイル | 場所 | 用途 |
|---------|------|------|
| `tests/fixtures/files/sample.csv` | CSV | ファイルアップロード・CSVプレビューテスト |
| `tests/fixtures/files/sample.npy` | NumPy配列 | ndarray保存・統計サマリーテスト |
| `tests/fixtures/files/sample.png` | 画像 | 画像アップロード・サムネイル生成テスト |
| `tests/fixtures/files/sample.json` | JSON | JSON保存テスト |
| `tests/fixtures/files/sample.txt` | テキスト | テキストアップロードテスト |
| `tests/fixtures/files/xrd_data.csv` | XRDデータ | E2Eテスト用の実験データ |

### 5.3 テスト用ファイル生成（conftest.py）

```python
# tests/conftest.py

@pytest.fixture
def sample_csv(tmp_path):
    """テスト用CSVファイル"""
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text("2theta,intensity\n44.67,1000\n65.02,450\n82.33,200\n")
    return csv_path

@pytest.fixture
def sample_ndarray(tmp_path):
    """テスト用NumPy配列ファイル"""
    import numpy as np
    npy_path = tmp_path / "sample.npy"
    np.save(npy_path, np.random.rand(100, 2))
    return npy_path

@pytest.fixture
def sample_image(tmp_path):
    """テスト用PNGファイル（1x1ピクセル）"""
    png_path = tmp_path / "sample.png"
    # 最小のPNGバイナリ
    import struct, zlib
    def create_minimal_png():
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr = b'IHDR' + ihdr_data
        ihdr_chunk = struct.pack('>I', 13) + ihdr + struct.pack('>I', zlib.crc32(ihdr) & 0xffffffff)
        raw = b'\x00\xff\x00\x00'
        idat_data = zlib.compress(raw)
        idat = b'IDAT' + idat_data
        idat_chunk = struct.pack('>I', len(idat_data)) + idat + struct.pack('>I', zlib.crc32(idat) & 0xffffffff)
        iend = b'IEND'
        iend_chunk = struct.pack('>I', 0) + iend + struct.pack('>I', zlib.crc32(iend) & 0xffffffff)
        return sig + ihdr_chunk + idat_chunk + iend_chunk
    png_path.write_bytes(create_minimal_png())
    return png_path
```

---

## 6. カバレッジ目標の内訳

| モジュール | 目標 | 備考 |
|-----------|:----:|------|
| `labvault/core/record.py` | 90% | モデルの核心 |
| `labvault/core/lab.py` | 85% | SDK公開API |
| `labvault/core/id_generator.py` | 95% | 小さいモジュール、完全テスト可能 |
| `labvault/core/settings.py` | 85% | 設定読み込み |
| `labvault/core/serializer.py` | 90% | シリアライズ/デシリアライズ |
| `labvault/backends/memory.py` | 80% | テスト基盤自体 |
| `labvault/backends/firestore.py` | 70% | 実接続テストはnightly |
| `labvault/backends/nextcloud.py` | 70% | 実接続テストはnightly |
| `labvault/tracking/hooks.py` | 80% | IPython環境依存部分あり |
| `labvault/tracking/summarize.py` | 95% | 純粋関数、完全テスト可能 |
| `labvault/tracking/filter.py` | 95% | 純粋関数、完全テスト可能 |
| `labvault/buffer/sqlite.py` | 85% | ローカルバッファ |
| `labvault/buffer/sync.py` | 80% | 同期ロジック |
| `labvault/cli/` | 75% | CLI入出力のテストは限定的 |
| `labvault/mcp/` | 80% | FastMCPテストクライアント使用 |
| **全体** | **80%** | |
