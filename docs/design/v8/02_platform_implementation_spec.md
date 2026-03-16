# v8 プラットフォーム実装仕様書

> v7設計 + REQUIREMENTSに基づく、プラットフォーム側（MCPサーバー、Cloud Functions、WebApp、GCPインフラ）の実装レベル仕様。
> 対象リポジトリ: `kpro-arim-platform/`（モノレポ）

---

## 目次

1. [MCPサーバー実装仕様（14ツール）](#1-mcpサーバー実装仕様14ツール)
2. [Cloud Functions実装仕様](#2-cloud-functions実装仕様)
3. [Firestoreスキーマ（最終版）](#3-firestoreスキーマ最終版)
4. [Nextcloudディレクトリ構造（最終版）](#4-nextcloudディレクトリ構造最終版)
5. [WebApp（Streamlit）実装仕様](#5-webappstreamlit実装仕様)
6. [GCPインフラ設定](#6-gcpインフラ設定)
7. [モノレポのディレクトリ構成と各ファイル](#7-モノレポのディレクトリ構成と各ファイル)
8. [実装ロードマップ（Issue粒度）](#8-実装ロードマップissue粒度)

---

## 1. MCPサーバー実装仕様（14ツール）

### 1.1 サーバー基盤

```python
# mcp-server/src/server.py
from fastmcp import FastMCP
from google.cloud import firestore
from shared.nextcloud import NextcloudClient

mcp = FastMCP(
    name="mdxdb",
    version="0.1.0",
    description="実験データ管理プラットフォーム MCP Server",
)

# 共有リソース（起動時に1回初期化）
db = firestore.AsyncClient(project="kpro-arim", database="mdxdb")
nc = NextcloudClient()  # Nextcloud WebDAV クライアント
```

**デプロイ先**: Cloud Run（asia-northeast1）
**トランスポート**: Streamable HTTP（`/mcp` エンドポイント）
**認証**: Cloud Run IAM invoker + サービスアカウントトークン

### 1.2 全14ツール一覧と分類

| # | ツール名 | 分類 | Firestore | Nextcloud | Vertex AI |
|---|---------|------|-----------|-----------|-----------|
| 1 | `search` | 検索 | R | - | Embedding |
| 2 | `get_detail` | 取得 | R | - | - |
| 3 | `compare` | 分析 | R | - | - |
| 4 | `data_preview` | 取得 | R | R | - |
| 5 | `get_results` | 検索 | R | - | - |
| 6 | `aggregate` | 分析 | R | - | - |
| 7 | `get_timeline` | 取得 | R | - | - |
| 8 | `get_trace` | 取得 | R | - | - |
| 9 | `explain_result` | 分析 | R | - | - |
| 10 | `compare_runs` | 分析 | R | - | - |
| 11 | `get_notebook_log` | 取得 | R | - | - |
| 12 | `execute_code` | 実行 | R/W | R/W | - |
| 13 | `batch_execute` | 実行 | R/W | R/W | - |
| 14 | `get_image` | 取得 | R | R | - |

R=読み取り, W=書き込み

---

### 1.3 各ツール詳細仕様

#### Tool 1: `search`

**目的**: ハイブリッド検索（構造化フィルタ + ベクトル類似度）

```python
@mcp.tool()
async def search(
    team_id: str,
    query: str | None = None,           # 自然言語クエリ（ベクトル検索用）
    tags: list[str] | None = None,
    status: str | None = None,           # "success" | "failed" | "partial" | "in_progress"
    record_type: str | None = None,      # "experiment" | "sample" | "process" 等
    created_by: str | None = None,
    created_after: str | None = None,    # ISO 8601
    created_before: str | None = None,
    conditions_filter: dict | None = None,  # {"temperature_C": {">": 300}}
    limit: int = 20,
) -> list[SearchResult]:
    """レコードをハイブリッド検索する。"""
```

**出力スキーマ**:
```python
class SearchResult(TypedDict):
    id: str
    title: str
    type: str
    status: str
    tags: list[str]
    created_by: str
    created_at: str
    conditions_summary: dict        # 主要条件のサブセット
    results_summary: dict           # 主要結果のサブセット
    notebook_summary: str | None    # Notebookサマリー（あれば）
    relevance_score: float | None   # ベクトル検索時のスコア
```

**内部ロジック**:
```
1. query が指定されている場合:
   a. Vertex AI text-embedding-004 で query をベクトル化
   b. Firestore find_nearest() でベクトル類似度上位 limit*3 件を取得
   c. 取得結果に対して構造化フィルタを適用（tags, status, type, created_by, 日付範囲）
   d. conditions_filter がある場合、Python側で辞書フィルタリング

2. query が未指定の場合:
   a. Firestore の複合クエリで構造化フィルタのみ実行
   b. .where("tags", "array_contains_any", tags)
      .where("status", "==", status)
      .where("created_at", ">=", created_after)
      .order_by("created_at", direction=DESCENDING)
      .limit(limit)

3. conditions_filter の処理（Firestore側でサポートされない複雑条件）:
   a. Firestoreで基本フィルタ適用後、Python側でdict比較
   b. 例: {"temperature_C": {">": 300}} → doc["conditions"]["temperature_C"] > 300

4. 結果を SearchResult に整形して返却
```

**Firestoreアクセスパターン**:
- `teams/{team_id}/records` コレクションに対するクエリ
- ベクトル検索時: `find_nearest(vector_field="embedding", query_vector=..., limit=...)`
- `deleted_at == null` を常にフィルタ（ソフトデリート対応）

---

#### Tool 2: `get_detail`

**目的**: レコードの全詳細情報を取得

```python
@mcp.tool()
async def get_detail(
    team_id: str,
    record_id: str,
    include_sub_records: bool = False,
    include_notebook_log: bool = False,  # L2レベルのNotebookログを含む
    include_analyses: bool = False,      # 解析履歴を含む
    include_traces: bool = False,        # @exp.track トレースを含む
) -> RecordDetail:
    """レコードの詳細情報を取得する。"""
```

**出力スキーマ**:
```python
class RecordDetail(TypedDict):
    id: str
    title: str
    type: str
    status: str
    tags: list[str]
    conditions: dict
    results: dict
    notes: list[dict]               # [{text, by, at}]
    created_by: str
    created_at: str
    updated_at: str
    parent_id: str | None
    file_refs: list[dict]           # [{name, path, size, type, uploaded_at}]
    notebook_summary: str | None
    trace_summary: str | None
    # 以下はオプション（フラグで制御）
    sub_records: list[dict] | None
    notebook_log: dict | None       # L2レベル: summary + key_cells + final_variables
    analyses: list[dict] | None     # 解析履歴
    traces: list[dict] | None       # @exp.track トレース
```

**内部ロジック**:
```
1. Firestore から teams/{team_id}/records/{record_id} を取得
2. deleted_at が設定されていたら NotFoundError

3. include_sub_records の場合:
   teams/{team_id}/records で parent_id == record_id のドキュメントを取得

4. include_notebook_log の場合:
   teams/{team_id}/records/{record_id}/cell_logs を全件取得
   → _build_l2_notebook_log(cell_logs) で L2 サマリーに変換
     - cell_count, total_duration
     - key_cells: new_vars が多い or changed_vars がある or error があるセルを抽出
     - final_namespace: 最後のセルログ時点の変数一覧

5. include_analyses の場合:
   teams/{team_id}/records/{record_id}/analyses を時系列で取得

6. include_traces の場合:
   teams/{team_id}/records/{record_id}/traces を時系列で取得
```

---

#### Tool 3: `compare`

**目的**: 複数レコードの条件・結果を横並び比較

```python
@mcp.tool()
async def compare(
    team_id: str,
    record_ids: list[str],          # 2〜10件
    fields: list[str] | None = None,  # 比較するフィールド名（Noneなら自動検出）
) -> CompareResult:
    """複数レコードの条件・結果を比較表で返す。"""
```

**出力スキーマ**:
```python
class CompareResult(TypedDict):
    fields: list[str]                    # 比較フィールド名
    records: list[dict]                  # [{id, title, ...各フィールドの値}]
    differences: list[str]              # 値が異なるフィールド名
    common: dict                        # 全レコードで共通の値
```

**内部ロジック**:
```
1. record_ids の各レコードを並列取得（asyncio.gather）
2. fields が None の場合:
   全レコードの conditions + results のキーを union → fields とする
3. 各レコードから fields の値を抽出
4. 全レコードで同じ値のフィールド → common
5. 1つでも異なるフィールド → differences
6. 結果を表形式で返却
```

---

#### Tool 4: `data_preview`

**目的**: ファイルの統計サマリー/プレビューを取得

```python
@mcp.tool()
async def data_preview(
    team_id: str,
    record_id: str,
    filename: str,
) -> DataPreview:
    """レコードに紐づくファイルのプレビュー/統計サマリーを取得する。"""
```

**出力スキーマ**:
```python
class DataPreview(TypedDict):
    filename: str
    file_type: str                    # "csv" | "npy" | "image" | "text" | "binary"
    size_bytes: int
    preview: dict                     # ファイル種別に応じた内容（下記参照）
```

**内部ロジック**:
```
1. Firestore から file_refs を取得し、filename に一致するエントリを探す
2. _preview/ にプレビューが既に存在するか確認（Firestore の preview_refs フィールド）
   a. 存在する場合: Nextcloud から _preview/{filename}_meta.json を取得して返却
   b. 存在しない場合: 3へ

3. Nextcloud から元ファイルを取得（100MB超はヘッダのみ）
4. ファイル種別に応じてプレビュー生成:
   - CSV: pandas.read_csv → head(10) + describe() + columns + shape
   - npy: numpy.load → shape, dtype, min, max, mean, std
   - 画像: PIL → size, mode, format（サムネイルは preview_generator が生成済み）
   - テキスト: 先頭 2000 文字
   - バイナリ: サイズ + MIMEタイプのみ
5. 結果を返却
```

**preview の内容例**:
```json
// CSV
{"columns": ["2theta", "intensity"], "shape": [5000, 2],
 "head": [[10.0, 150], [10.1, 155], ...],
 "stats": {"2theta": {"min": 10.0, "max": 90.0}, "intensity": {"min": 50, "max": 15000}}}

// npy
{"shape": [5000, 2], "dtype": "float64",
 "stats": {"min": 10.0, "max": 15000.0, "mean": 3421.5, "std": 2100.3}}

// 画像
{"width": 4096, "height": 3072, "mode": "L", "format": "TIFF",
 "thumbnail_path": "_preview/SEM_50000x_thumb.jpg"}
```

---

#### Tool 5: `get_results`

**目的**: 構造化結果の横断検索

```python
@mcp.tool()
async def get_results(
    team_id: str,
    result_key: str,                   # "lattice_a", "n_peaks" 等
    tags: list[str] | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[ResultEntry]:
    """特定の結果キーを持つレコードを横断的に取得する。"""
```

**出力スキーマ**:
```python
class ResultEntry(TypedDict):
    record_id: str
    title: str
    value: Any                        # 結果の値
    conditions: dict                  # 主要条件
    created_at: str
```

**内部ロジック**:
```
1. Firestore クエリ:
   records コレクションで result_key フィールドの存在チェック
   → Firestore は「フィールド存在」クエリを直接サポートしないため、
     全件取得してPython側でフィルタ（数万件規模では非効率）

   代替戦略:
   a. records に result_keys: array<string> フィールドを追加（results の各キー名を保持）
   b. .where("result_keys", "array_contains", result_key) でフィルタ
   c. tags, status の追加フィルタを適用

2. 各ドキュメントから results[result_key] を抽出
3. ResultEntry のリストとして返却
```

---

#### Tool 6: `aggregate`

**目的**: 数値結果の集約統計

```python
@mcp.tool()
async def aggregate(
    team_id: str,
    result_key: str,                   # 集約対象の結果キー
    group_by: str | None = None,       # 条件キーでグループ化（例: "temperature_C"）
    tags: list[str] | None = None,
    status: str = "success",
) -> AggregateResult:
    """結果の数値を集約して統計量を返す。"""
```

**出力スキーマ**:
```python
class AggregateResult(TypedDict):
    result_key: str
    total_count: int
    overall: dict                      # {mean, std, min, max, median}
    groups: list[dict] | None          # group_by 指定時: [{group_value, count, mean, std, ...}]
```

**内部ロジック**:
```
1. get_results() と同じ方法でデータを取得
2. numpy で統計計算:
   values = [entry["value"] for entry in entries if isinstance(entry["value"], (int, float))]
   overall = {"mean": np.mean(values), "std": np.std(values), ...}

3. group_by 指定時:
   group_values = [entry["conditions"].get(group_by) for entry in entries]
   → pandas.DataFrame にして groupby → 統計量計算

4. 結果を返却
```

---

#### Tool 7: `get_timeline`

**目的**: サンプルの実験履歴を時系列で取得

```python
@mcp.tool()
async def get_timeline(
    team_id: str,
    sample: str | None = None,         # サンプル名でフィルタ
    record_id: str | None = None,      # 特定レコードの子レコード時系列
    limit: int = 50,
) -> list[TimelineEntry]:
    """実験の時系列履歴を取得する。"""
```

**出力スキーマ**:
```python
class TimelineEntry(TypedDict):
    record_id: str
    title: str
    type: str
    status: str
    created_at: str
    created_by: str
    conditions_summary: dict
    results_summary: dict
```

**内部ロジック**:
```
1. sample 指定時:
   .where("conditions.sample", "==", sample)
   .order_by("created_at")
   .limit(limit)

2. record_id 指定時:
   .where("parent_id", "==", record_id)
   .order_by("created_at")

3. 時系列順で返却
```

---

#### Tool 8: `get_trace`

**目的**: @exp.track の関数トレースを取得

```python
@mcp.tool()
async def get_trace(
    team_id: str,
    record_id: str,
    trace_id: str | None = None,       # 特定トレース（Noneなら全件）
    function_name: str | None = None,  # 関数名でフィルタ
) -> list[TraceEntry]:
    """@exp.track で記録された関数トレースを取得する。"""
```

**出力スキーマ**:
```python
class TraceEntry(TypedDict):
    trace_id: str
    type: str                          # "track" | "snapshot"
    timestamp: str
    function: str | None
    file: str
    line: int
    args: dict | None
    return_value: dict | None
    call_tree: dict | None             # ネストした関数呼び出し
    duration_sec: float
    summary: str
```

**内部ロジック**:
```
1. teams/{team_id}/records/{record_id}/traces サブコレクションを取得
2. trace_id 指定時: 単一ドキュメント取得
3. function_name 指定時: .where("function", "==", function_name)
4. TraceEntry に整形して返却
```

---

#### Tool 9: `explain_result`

**目的**: 特定の結果がどのように算出されたかを説明

```python
@mcp.tool()
async def explain_result(
    team_id: str,
    record_id: str,
    result_key: str,                   # "lattice_a" 等
) -> ExplanationResult:
    """結果の値がどのように算出されたか、セルログ・トレース・解析履歴から説明する。"""
```

**出力スキーマ**:
```python
class ExplanationResult(TypedDict):
    record_id: str
    result_key: str
    value: Any
    sources: list[dict]                # 算出に関連するセルログ/トレース/解析
    explanation: str                   # 人間可読な説明文
```

**内部ロジック**:
```
1. レコード本体から results[result_key] の値を取得
2. cell_logs を全件取得し、result_key を含むセルを逆順で探索:
   - new_vars または changed_vars に result_key が含まれるセル
   - source コードに result_key が含まれるセル
3. traces で return_value に result_key を含むものを探索
4. analyses で results に result_key を含むものを探索
5. 見つかったソースを時系列で並べ、explanation テキストを生成:
   「lattice_a = 2.873 は、セル8で np.mean(d_spacings) * sqrt(h^2+k^2+l^2)
    により算出されました。入力: d_spacings (セル6で算出)」
```

---

#### Tool 10: `compare_runs`

**目的**: 同一処理の異なるパラメータ実行を比較

```python
@mcp.tool()
async def compare_runs(
    team_id: str,
    record_ids: list[str],             # 比較対象（2〜10件）
    function_name: str | None = None,  # 関数名（@exp.track 使用時）
) -> RunComparisonResult:
    """同一関数/処理の異なるパラメータ実行を比較する。"""
```

**出力スキーマ**:
```python
class RunComparisonResult(TypedDict):
    function_name: str | None
    parameter_diffs: list[dict]        # [{param, values: {record_id: value}}]
    result_diffs: list[dict]           # [{result_key, values: {record_id: value}}]
    common_params: dict                # 全レコードで共通のパラメータ
```

**内部ロジック**:
```
1. 各レコードの traces（function_name 一致）または cell_logs を取得
2. function_name 指定時:
   各レコードのトレースから args を抽出 → パラメータ差分を計算
3. function_name 未指定時:
   各レコードの conditions を比較 → 差分を計算
4. results の差分も計算
5. 表形式で返却
```

---

#### Tool 11: `get_notebook_log`

**目的**: Notebookのセル実行履歴を取得

```python
@mcp.tool()
async def get_notebook_log(
    team_id: str,
    record_id: str,
    level: str = "L2",                 # "L1" | "L2" | "L3"
    cell_range: list[int] | None = None,  # [start, end] セル番号範囲
    filter_imports: list[str] | None = None,  # 特定ライブラリを使ったセルのみ
) -> NotebookLog:
    """Notebookのセル実行履歴を取得する。"""
```

**出力スキーマ**:
```python
class NotebookLog(TypedDict):
    record_id: str
    notebook_summary: str | None       # L1以上
    cell_count: int                    # L1以上
    execution_time_total_sec: float    # L1以上
    libraries_used: list[str]          # L1以上
    key_cells: list[dict] | None       # L2以上
    final_namespace: dict | None       # L2以上
    cells: list[dict] | None           # L3のみ（全セル）
```

**内部ロジック**:
```
1. teams/{team_id}/records/{record_id} から notebook_summary を取得
2. teams/{team_id}/records/{record_id}/cell_logs を取得:
   - L1: カウントと合計時間のみ → cell_logs の件数と duration_sec 合計
   - L2: key_cells を抽出（new_vars が2個以上 or changed_vars あり or error あり）
   - L3: 全セルの source + new_vars + changed_vars を返却

3. cell_range 指定時: cell_number でフィルタ
4. filter_imports 指定時: imports フィールドに該当ライブラリが含まれるセルのみ

5. final_namespace の計算（L2以上）:
   全セルの new_vars と changed_vars を時系列で適用 → 最終的な変数一覧
```

---

#### Tool 12: `execute_code` — コード実行（核心機能）

**目的**: LLMが生成したPythonコードを実データに対してサンドボックス実行

```python
@mcp.tool()
async def execute_code(
    team_id: str,
    record_id: str,
    code: str,                         # 実行するPythonコード
    files: list[str] | None = None,    # 使用するファイル名（record の file_refs から）
    input_analyses: list[str] | None = None,  # 前の解析結果を入力にする場合のID
    name: str | None = None,           # 解析名（Noneなら自動生成）
    prompt: str | None = None,         # 元の指示（LLMが自動セット）
    timeout_sec: int = 60,
) -> ExecuteResult:
    """Pythonコードをサンドボックスで実行し、結果を自動保存する。"""
```

**出力スキーマ**:
```python
class ExecuteResult(TypedDict):
    analysis_id: str                   # Crockford's Base32 ユニークID
    name: str                          # 人間可読な名前
    results: dict                      # code 内の result 変数の値
    stdout: str                        # 標準出力
    images: list[str]                  # 生成された画像ファイル名
    duration_sec: float
    error: str | None                  # エラー時のトレースバック
```

##### 1.3.12a サンドボックス実行環境の設計

**選定: Cloud Run Jobs（推奨）**

```
MCPサーバー (Cloud Run Service)
    │
    │ execute_code リクエスト
    ▼
Cloud Run Jobs (asia-northeast1)
    ├── コンテナイメージ: gcr.io/kpro-arim/code-executor:latest
    ├── CPU: 2 vCPU
    ├── メモリ: 2 GiB
    ├── タイムアウト: 120秒（余裕を持たせる）
    ├── ネットワーク: VPC内のみ（外部アクセス禁止）
    ├── サービスアカウント: code-executor@kpro-arim.iam.gserviceaccount.com
    │   └── 権限: Firestore読み書き + Nextcloud(Secret Manager)のみ
    └── 環境変数: TEAM_ID, RECORD_ID, EXECUTION_ID
```

**代替案の比較と選定理由**:

| 方式 | メリット | デメリット | 判断 |
|------|---------|----------|------|
| subprocess (同一インスタンス) | 実装最速 | セキュリティ弱い、メモリ共有 | NG（本番不可） |
| Cloud Run Jobs | コンテナ分離、VPC制限、IAM制御 | 起動に3-10秒 | **採用** |
| Cloud Functions (別インスタンス) | サーバーレス | タイムアウト制約、コールドスタート | 候補だがJobsのほうが制御しやすい |
| Docker-in-Docker | 完全分離 | Cloud Run上でDinD非推奨 | NG |
| gVisor (Cloud Run default) | Cloud RunはgVisor上で動作する | 追加設定不要 | Jobs採用で自動適用 |

**MVP段階の簡易実装（Phase 2a）**: subprocess + RestrictedPython

MVP時は Cloud Run Jobs の仕組みを用意するまでの間、以下の簡易実装で開始:

```python
import subprocess
import tempfile
import json

async def _execute_in_subprocess(code: str, file_paths: dict[str, str], timeout: int) -> dict:
    """subprocess でコードを実行する簡易サンドボックス。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. データファイルを tmpdir にコピー
        for name, local_path in file_paths.items():
            shutil.copy(local_path, Path(tmpdir) / name)

        # 2. ラッパースクリプトを生成
        wrapper = f"""
import sys, json, os
os.chdir("{tmpdir}")
_result = {{}}
_images = []

# ファイルパス変数を注入
{chr(10).join(f'{name.replace(".", "_")}_path = "{Path(tmpdir) / name}"'
              for name in file_paths)}
file_path = "{next(iter(file_paths.values()), "")}"

# ユーザーコード実行
exec(open("{tmpdir}/_code.py").read())

# matplotlib の Figure を自動保存
import matplotlib
for i, fig_num in enumerate(matplotlib.pyplot.get_fignums()):
    fig = matplotlib.pyplot.figure(fig_num)
    img_path = f"{tmpdir}/_img_{{i}}.png"
    fig.savefig(img_path, dpi=150, bbox_inches='tight')
    _images.append(img_path)

# result 変数を収集
if 'result' in dir():
    _result = result

print(json.dumps({{"results": _result, "images": _images}}, default=str))
"""
        (Path(tmpdir) / "_code.py").write_text(code)
        (Path(tmpdir) / "_wrapper.py").write_text(wrapper)

        # 3. subprocess で実行
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(tmpdir) / "_wrapper.py"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=tmpdir,
            env={
                "PATH": os.environ["PATH"],
                "HOME": tmpdir,
                # GCP認証情報は渡さない（Nextcloud/Firestoreへの直接アクセス不可）
            },
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": f"実行タイムアウト ({timeout}秒)", "results": {}, "images": []}

        if proc.returncode != 0:
            return {"error": stderr.decode(), "results": {}, "images": []}

        return json.loads(stdout.decode())
```

##### 1.3.12b セキュリティ対策

| リスク | 対策 |
|--------|------|
| ファイルシステムアクセス | tmpdir 内のみ。`os.chdir(tmpdir)` + 環境変数で HOME を tmpdir に |
| ネットワークアクセス | Cloud Run Jobs: VPC内のみ。subprocess: iptables or seccomp で制限 |
| 無限ループ | タイムアウト（デフォルト60秒、最大120秒） |
| メモリ爆発 | Cloud Run Jobs: 2GiB 上限。subprocess: `resource.setrlimit(RLIMIT_AS, 2*1024**3)` |
| os.system / subprocess | コード検査: `import os`, `import subprocess`, `import socket` を禁止 |
| ファイルシステムの書き込み爆発 | tmpdir のディスクサイズ制限（Cloud Run Jobs: ephemeral storage 設定） |

**禁止importリスト**:
```python
BANNED_IMPORTS = {
    "os", "subprocess", "socket", "http", "urllib",
    "requests", "shutil", "pathlib",  # pathlib は file_path 変数で代替
    "ctypes", "multiprocessing", "threading",
    "signal", "resource", "gc",
}
```

**コード検査（実行前）**:
```python
import ast

def validate_code(code: str) -> list[str]:
    """コードの安全性を検査する。違反があればエラーメッセージのリストを返す。"""
    violations = []
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if module in BANNED_IMPORTS:
                    violations.append(f"禁止されたモジュール: {module}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                if module in BANNED_IMPORTS:
                    violations.append(f"禁止されたモジュール: {module}")
    return violations
```

##### 1.3.12c 結果の自動保存フロー

```
execute_code 呼び出し
    │
    ├── 1. 解析IDの生成
    │   analysis_id = generate_crockford_base32(length=4)
    │   name = name or _auto_generate_name(code, prompt)
    │
    ├── 2. 入力ファイルの取得
    │   for f in files:
    │       Nextcloud → tmpdir にダウンロード
    │   for aid in input_analyses:
    │       Firestore analyses/{aid}/results → tmpdir に JSON として配置
    │
    ├── 3. コード実行（サンドボックス）
    │   result = await _execute_in_subprocess(code, file_paths, timeout_sec)
    │
    ├── 4. 画像の保存（Nextcloud）
    │   for img in result["images"]:
    │       dest = f"{record_nextcloud_path}/_analyses/{analysis_id}_{img.name}"
    │       Nextcloud にアップロード
    │
    ├── 5. 解析履歴の保存（Firestore）
    │   teams/{team_id}/records/{record_id}/analyses/{analysis_id}
    │   {
    │       id: analysis_id,
    │       name: name,
    │       code: code,
    │       input_files: files,
    │       input_analyses: input_analyses,
    │       results: result["results"],
    │       images: [保存後のファイル名リスト],
    │       executed_at: now,
    │       executed_by: "claude",
    │       prompt: prompt,
    │       duration_sec: result["duration_sec"],
    │       packages: _detect_packages(code),
    │       error: result.get("error"),
    │   }
    │
    └── 6. ExecuteResult を返却
```

##### 1.3.12d 解析IDの生成と名前バッティング防止

```python
import random
import string

# Crockford's Base32 文字セット（I, L, O, U を除く）
CROCKFORD_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def generate_analysis_id(length: int = 4) -> str:
    """Crockford's Base32 のランダムID（4文字 = 32^4 = 約100万通り）"""
    return "".join(random.choices(CROCKFORD_CHARS, k=length))

async def generate_unique_analysis_id(
    db: firestore.AsyncClient, team_id: str, record_id: str
) -> str:
    """レコード内で重複しないIDを生成する。"""
    analyses_ref = db.collection("teams").document(team_id) \
                     .collection("records").document(record_id) \
                     .collection("analyses")
    for _ in range(10):  # 最大10回リトライ
        aid = generate_analysis_id()
        doc = await analyses_ref.document(aid).get()
        if not doc.exists:
            return aid
    raise RuntimeError("解析IDの生成に失敗しました（重複回避リトライ上限）")

def auto_generate_name(code: str, prompt: str | None) -> str:
    """コードとプロンプトから人間可読な名前を自動生成する。"""
    # パターンマッチで推測
    if "curve_fit" in code or "fitting" in code.lower():
        base = "curve_fit"
    elif "peak" in code.lower():
        base = "peak_analysis"
    elif "plot" in code.lower() or "plt." in code:
        base = "visualization"
    elif prompt:
        # プロンプトの先頭20文字をスネークケースに
        base = re.sub(r'[^\w]', '_', prompt[:20]).strip('_').lower()
    else:
        base = "analysis"
    return base

async def ensure_unique_name(
    db: firestore.AsyncClient, team_id: str, record_id: str, base_name: str
) -> str:
    """レコード内で重複しない名前を返す。同名がある場合は連番を付与。"""
    analyses_ref = db.collection("teams").document(team_id) \
                     .collection("records").document(record_id) \
                     .collection("analyses")
    query = analyses_ref.where("name", ">=", base_name) \
                        .where("name", "<=", base_name + "\uf8ff")
    existing = [doc.to_dict()["name"] async for doc in query.stream()]

    if base_name not in existing:
        return base_name

    # 連番を付与: base_001, base_002, ...
    for i in range(1, 1000):
        candidate = f"{base_name}_{i:03d}"
        if candidate not in existing:
            return candidate
    return f"{base_name}_{generate_analysis_id()}"
```

---

#### Tool 13: `batch_execute`

**目的**: 同一コードを複数レコードのデータに一括適用

```python
@mcp.tool()
async def batch_execute(
    team_id: str,
    record_ids: list[str],             # 対象レコード（2〜20件）
    code: str,
    file: str,                         # 各レコードから取得するファイル名（共通）
    name: str | None = None,
    prompt: str | None = None,
    timeout_sec: int = 60,
) -> BatchExecuteResult:
    """同一Pythonコードを複数レコードのデータに一括適用する。"""
```

**出力スキーマ**:
```python
class BatchExecuteResult(TypedDict):
    results: list[dict]                # [{record_id, analysis_id, results, images, error}]
    summary: dict                      # 全体の集約結果
    total_duration_sec: float
```

**内部ロジック**:
```
1. 各 record_id について並列に execute_code を呼び出す（asyncio.gather、concurrency=5）
   - 各呼び出しは独立したサンドボックスで実行
   - 1つが失敗しても他は続行

2. 全結果を集約:
   summary = {
       "succeeded": 成功件数,
       "failed": 失敗件数,
       "results_table": [  # 横断比較表
           {"record_id": "AB3F", "center": 28.4, "sigma": 0.18},
           {"record_id": "KL67", "center": 28.6, "sigma": 0.22},
           ...
       ]
   }

3. BatchExecuteResult を返却
```

**並列実行の制御**:
```python
import asyncio

BATCH_CONCURRENCY = 5  # 同時実行数

async def batch_execute_impl(team_id, record_ids, code, file, name, prompt, timeout_sec):
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def execute_one(record_id):
        async with semaphore:
            return await execute_code(
                team_id=team_id,
                record_id=record_id,
                code=code,
                files=[file],
                name=name,
                prompt=prompt,
                timeout_sec=timeout_sec,
            )

    results = await asyncio.gather(
        *[execute_one(rid) for rid in record_ids],
        return_exceptions=True,
    )
    return results
```

---

#### Tool 14: `get_image`

**目的**: 実行結果の画像/グラフを取得

```python
@mcp.tool()
async def get_image(
    team_id: str,
    record_id: str,
    image_name: str | None = None,     # 特定画像（Noneならリスト取得）
    analysis_id: str | None = None,    # 特定解析の画像に限定
    as_base64: bool = True,            # base64エンコードで返す
) -> ImageResult:
    """レコードに保存された画像を取得する。"""
```

**出力スキーマ**:
```python
class ImageResult(TypedDict):
    images: list[dict]                 # [{name, analysis_id, content_base64, mime_type, size}]
```

**内部ロジック**:
```
1. image_name が None の場合:
   Firestore analyses サブコレクションから全画像名を収集
   + file_refs から画像ファイル（拡張子が .png, .jpg, .svg 等）を収集
   → 画像名リストを返却（content_base64 は空）

2. image_name が指定されている場合:
   a. analysis_id が指定されていれば、そのanalysisの画像パスを特定
   b. Nextcloud から画像をダウンロード:
      {record_nextcloud_path}/_analyses/{analysis_id}_{image_name}
      または
      {record_nextcloud_path}/_data/{image_name}
   c. as_base64=True なら base64エンコードして返却
   d. MIMEタイプを拡張子から推定

3. _preview/ にサムネイルがある場合はサムネイルを優先返却（オリジナルが大きい場合）
```

---

## 2. Cloud Functions実装仕様

### 2.1 embedding_generator

**トリガー**: Firestore `teams/{team_id}/records/{record_id}` の `onCreate` および `onUpdate`（embedding_text フィールド変更時）

**ランタイム**: Python 3.12, 256MB メモリ, 60秒タイムアウト

```python
# functions/embedding_generator/main.py
import functions_framework
from google.cloud import firestore
from vertexai.language_models import TextEmbeddingModel

model = TextEmbeddingModel.from_pretrained("text-embedding-004")
db = firestore.Client()

@functions_framework.cloud_event
def on_record_change(cloud_event):
    """レコード作成/更新時にembeddingを生成してFirestoreに書き戻す。"""
    # 1. イベントからドキュメントパスとデータを取得
    resource = cloud_event.data["value"]
    doc_path = cloud_event["subject"]  # teams/{team_id}/records/{record_id}
    fields = resource.get("fields", {})

    # 2. embedding_text を取得
    embedding_text = _extract_string(fields.get("embedding_text"))
    if not embedding_text:
        return  # embedding_text がなければスキップ

    # 3. 既存のembeddingと同じテキストなら再生成しない（無限ループ防止）
    existing_hash = _extract_string(fields.get("embedding_text_hash"))
    new_hash = hashlib.sha256(embedding_text.encode()).hexdigest()[:16]
    if existing_hash == new_hash:
        return

    # 4. Vertex AI でembedding生成
    embeddings = model.get_embeddings(
        [embedding_text],
        output_dimensionality=768,
    )
    vector = embeddings[0].values

    # 5. Firestore に書き戻し
    doc_ref = db.document(doc_path)
    doc_ref.update({
        "embedding": vector,
        "embedding_text_hash": new_hash,
        "embedding_updated_at": firestore.SERVER_TIMESTAMP,
    })
```

**デプロイコマンド**:
```bash
gcloud functions deploy embedding-generator \
  --gen2 \
  --region=asia-northeast1 \
  --runtime=python312 \
  --source=functions/embedding_generator/ \
  --entry-point=on_record_change \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.written" \
  --trigger-event-filters="database=mdxdb" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}" \
  --memory=256Mi \
  --timeout=60s \
  --service-account=functions-sa@kpro-arim.iam.gserviceaccount.com
```

---

### 2.2 nextcloud_poller

**トリガー**: Cloud Scheduler（5分間隔）→ HTTP

**ランタイム**: Python 3.12, 512MB メモリ, 120秒タイムアウト

```python
# functions/nextcloud_poller/main.py
import functions_framework
from google.cloud import firestore, secretmanager
from nc_py_api import Nextcloud
from datetime import datetime, timezone

db = firestore.Client()

@functions_framework.http
def poll_nextcloud(request):
    """Nextcloudの変更を検出してFirestoreを更新する。"""
    # 1. Nextcloud認証情報をSecret Managerから取得
    nc = _get_nextcloud_client()

    # 2. 前回チェック時刻を取得
    state_ref = db.collection("_system").document("poller_state")
    state = state_ref.get().to_dict() or {}
    last_check = state.get("last_check", datetime(2020, 1, 1, tzinfo=timezone.utc))

    # 3. チーム一覧を取得
    teams = db.collection("teams").stream()

    for team_doc in teams:
        team = team_doc.to_dict()
        group_folder = team.get("nextcloud_group_folder")
        if not group_folder:
            continue

        # 4. Nextcloud WebDAV で変更ファイルを検出
        base_path = f"large/{group_folder}/"
        try:
            changed = _find_modified_files(nc, base_path, last_check)
        except Exception as e:
            print(f"Nextcloud polling error for {group_folder}: {e}")
            continue

        # 5. 各ファイルについてFirestoreに登録
        for file_info in changed:
            record_id = _extract_record_id(file_info.path, base_path)
            if not record_id:
                continue

            record_ref = db.collection("teams").document(team_doc.id) \
                           .collection("records").document(record_id)
            record = record_ref.get()

            if not record.exists:
                # レコードが存在しない場合: 新規レコードを自動作成
                record_ref.set({
                    "title": f"Nextcloud投入: {record_id}",
                    "type": "experiment",
                    "status": "in_progress",
                    "tags": [],
                    "conditions": {},
                    "results": {},
                    "notes": [],
                    "created_by": "nextcloud_browser",
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "parent_id": None,
                    "visibility": "team",
                    "deleted_at": None,
                    "file_refs": [],
                })

            # file_refs に追加
            record_ref.update({
                "file_refs": firestore.ArrayUnion([{
                    "name": file_info.name,
                    "path": file_info.path,
                    "size": file_info.size,
                    "type": _guess_file_type(file_info.name),
                    "uploaded_at": file_info.last_modified.isoformat(),
                    "source": "nextcloud_browser",
                }]),
                "updated_at": firestore.SERVER_TIMESTAMP,
            })

    # 6. チェック時刻を更新
    state_ref.set({"last_check": datetime.now(timezone.utc)})
    return "OK", 200


def _find_modified_files(nc: Nextcloud, base_path: str, since: datetime) -> list:
    """Nextcloud WebDAV PROPFIND で変更ファイルを検出する。"""
    all_files = []
    # 再帰的にディレクトリを探索
    def walk(path):
        try:
            items = nc.files.listdir(path)
        except Exception:
            return
        for item in items:
            if item.is_dir:
                # _data ディレクトリ内のみ探索
                if item.name == "_data" or not item.name.startswith("_"):
                    walk(item.user_path)
            else:
                if item.last_modified and item.last_modified > since:
                    all_files.append(item)
    walk(base_path)
    return all_files


def _extract_record_id(file_path: str, base_path: str) -> str | None:
    """ファイルパスからレコードIDを抽出する。
    パス例: large/group/v1/db_name/AB3F/_data/xrd.csv → "AB3F"
    """
    relative = file_path.replace(base_path, "")
    parts = relative.split("/")
    # v{major}/{db_name}/{record_id}/...
    if len(parts) >= 3:
        return parts[2]  # record_id
    return None
```

**Cloud Scheduler 設定**:
```bash
gcloud scheduler jobs create http nextcloud-poller \
  --location=asia-northeast1 \
  --schedule="*/5 * * * *" \
  --uri="https://nextcloud-poller-XXXXX.asia-northeast1.run.app" \
  --http-method=POST \
  --oidc-service-account-email=scheduler-sa@kpro-arim.iam.gserviceaccount.com
```

---

### 2.3 preview_generator（新規）

**トリガー**: Firestore `teams/{team_id}/records/{record_id}` の `onUpdate`（`file_refs` フィールド変更時）

**ランタイム**: Python 3.12, 1024MB メモリ, 300秒タイムアウト

```python
# functions/preview_generator/main.py
import functions_framework
from google.cloud import firestore
from PIL import Image
import numpy as np
import pandas as pd
import io
import json
import tempfile

db = firestore.Client()

@functions_framework.cloud_event
def on_file_refs_update(cloud_event):
    """file_refs 更新時にプレビューを自動生成する。"""
    # 1. 変更されたドキュメントのパスとデータを取得
    doc_path = cloud_event["subject"]
    old_value = cloud_event.data.get("oldValue", {}).get("fields", {})
    new_value = cloud_event.data["value"]["fields"]

    # 2. 新しく追加された file_refs を特定
    old_refs = _extract_file_refs(old_value)
    new_refs = _extract_file_refs(new_value)
    added_refs = [r for r in new_refs if r["name"] not in {o["name"] for o in old_refs}]

    if not added_refs:
        return

    nc = _get_nextcloud_client()
    team_id, record_id = _parse_doc_path(doc_path)
    record_ref = db.document(doc_path)
    nextcloud_base = _get_nextcloud_base_path(record_ref)

    for ref in added_refs:
        try:
            _generate_preview(nc, ref, nextcloud_base, record_ref, team_id, record_id)
        except Exception as e:
            print(f"Preview generation failed for {ref['name']}: {e}")


def _generate_preview(nc, ref, nextcloud_base, record_ref, team_id, record_id):
    """ファイル種別に応じたプレビューを生成する。"""
    name = ref["name"]
    size = ref.get("size", 0)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    # 大容量ファイル（>100MB）はメタデータのみ
    if size > 100 * 1024 * 1024:
        meta = {
            "filename": name,
            "size_bytes": size,
            "type": _guess_type(ext),
            "note": "ファイルが100MBを超えるためプレビュー生成をスキップ",
        }
        _save_preview_meta(nc, nextcloud_base, name, meta)
        _update_preview_refs(record_ref, name, meta)
        return

    # ファイル種別に応じた処理
    if ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp"):
        _preview_image(nc, ref, nextcloud_base, record_ref)
    elif ext == "npy":
        _preview_npy(nc, ref, nextcloud_base, record_ref)
    elif ext in ("csv", "tsv"):
        _preview_csv(nc, ref, nextcloud_base, record_ref, delimiter="," if ext == "csv" else "\t")
    elif ext in ("txt", "log", "dat", "ras"):
        _preview_text(nc, ref, nextcloud_base, record_ref)
    # それ以外は基本メタデータのみ


def _preview_image(nc, ref, nextcloud_base, record_ref):
    """画像ファイルのプレビュー生成。サムネイルとメタデータ。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    # Nextcloudからダウンロード
    with tempfile.NamedTemporaryFile(suffix=f".{name.rsplit('.', 1)[-1]}") as tmp:
        nc.files.download(src_path, tmp.name)
        img = Image.open(tmp.name)

        meta = {
            "filename": name,
            "type": "image",
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "format": img.format,
            "size_bytes": ref.get("size", 0),
        }

        # サムネイル生成（256x256）
        thumb = img.copy()
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="JPEG", quality=85)
        thumb_bytes = thumb_buf.getvalue()

        stem = name.rsplit(".", 1)[0]
        thumb_name = f"{stem}_thumb.jpg"
        thumb_path = f"{nextcloud_base}/_preview/{thumb_name}"
        nc.files.upload(thumb_path, thumb_bytes)

        # プレビュー画像（1024x1024）
        preview = img.copy()
        preview.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        preview_buf = io.BytesIO()
        preview.save(preview_buf, format="JPEG", quality=90)
        preview_bytes = preview_buf.getvalue()

        preview_name = f"{stem}_preview.jpg"
        preview_path = f"{nextcloud_base}/_preview/{preview_name}"
        nc.files.upload(preview_path, preview_bytes)

        meta["thumbnail_path"] = thumb_path
        meta["preview_path"] = preview_path

    # メタデータJSON保存
    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


def _preview_npy(nc, ref, nextcloud_base, record_ref):
    """NumPy配列のプレビュー生成。統計情報を計算。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    with tempfile.NamedTemporaryFile(suffix=".npy") as tmp:
        nc.files.download(src_path, tmp.name)
        arr = np.load(tmp.name, allow_pickle=False)

        meta = {
            "filename": name,
            "type": "npy",
            "shape": list(arr.shape),
            "dtype": str(arr.dtype),
            "size_bytes": ref.get("size", 0),
            "nbytes": int(arr.nbytes),
            "stats": {
                "min": float(np.nanmin(arr)) if np.issubdtype(arr.dtype, np.number) else None,
                "max": float(np.nanmax(arr)) if np.issubdtype(arr.dtype, np.number) else None,
                "mean": float(np.nanmean(arr)) if np.issubdtype(arr.dtype, np.number) else None,
                "std": float(np.nanstd(arr)) if np.issubdtype(arr.dtype, np.number) else None,
                "nan_count": int(np.count_nonzero(np.isnan(arr))) if np.issubdtype(arr.dtype, np.floating) else 0,
            },
        }
        # 多次元の場合、各軸のサイズも記録
        if arr.ndim > 1:
            meta["stats"]["shape_description"] = f"{arr.ndim}次元配列: " + " x ".join(map(str, arr.shape))

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


def _preview_csv(nc, ref, nextcloud_base, record_ref, delimiter=","):
    """CSV/TSVファイルのプレビュー生成。head(10) + describe()。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    with tempfile.NamedTemporaryFile(suffix=f".{name.rsplit('.', 1)[-1]}", mode="wb") as tmp:
        nc.files.download(src_path, tmp.name)

        # まず先頭1000行だけ読んでカラムを特定（大容量対策）
        try:
            df_head = pd.read_csv(tmp.name, delimiter=delimiter, nrows=1000)
        except Exception:
            # パースエラーの場合はテキストプレビューにフォールバック
            _preview_text(nc, ref, nextcloud_base, record_ref)
            return

        # 全行数はチャンクで数える（メモリ節約）
        total_rows = 0
        for chunk in pd.read_csv(tmp.name, delimiter=delimiter, chunksize=10000):
            total_rows += len(chunk)

        meta = {
            "filename": name,
            "type": "csv",
            "size_bytes": ref.get("size", 0),
            "columns": list(df_head.columns),
            "total_rows": total_rows,
            "total_columns": len(df_head.columns),
            "head_10": df_head.head(10).to_dict(orient="records"),
            "describe": df_head.describe(include="all").to_dict(),
            "dtypes": {col: str(dtype) for col, dtype in df_head.dtypes.items()},
        }

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


def _preview_text(nc, ref, nextcloud_base, record_ref):
    """テキストファイルのプレビュー。先頭2000文字。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    content = nc.files.download(src_path)
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("shift_jis", errors="replace")
    else:
        text = str(content)

    meta = {
        "filename": name,
        "type": "text",
        "size_bytes": ref.get("size", 0),
        "line_count": text.count("\n") + 1,
        "preview_text": text[:2000],
        "encoding_detected": "utf-8",
    }

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


# --- ヘルパー ---

def _save_preview_meta(nc, nextcloud_base, original_name, meta):
    """プレビューメタデータJSONをNextcloudに保存する。"""
    stem = original_name.rsplit(".", 1)[0]
    meta_path = f"{nextcloud_base}/_preview/{stem}_meta.json"
    nc.files.upload(meta_path, json.dumps(meta, ensure_ascii=False, default=str).encode())


def _update_preview_refs(record_ref, original_name, meta):
    """Firestoreのレコードに preview_refs を追加する。"""
    record_ref.update({
        f"preview_refs.{original_name.replace('.', '_')}": meta,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })
```

**大容量ファイル（>100MB）のハンドリング**:
- 100MB超のファイルはダウンロードせず、メタデータ（ファイル名、サイズ、拡張子）のみ記録
- `note: "ファイルが100MBを超えるためプレビュー生成をスキップ"` をメタデータに含める
- 将来的には Cloud Run Jobs で非同期処理することも可能

**デプロイコマンド**:
```bash
gcloud functions deploy preview-generator \
  --gen2 \
  --region=asia-northeast1 \
  --runtime=python312 \
  --source=functions/preview_generator/ \
  --entry-point=on_file_refs_update \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.updated" \
  --trigger-event-filters="database=mdxdb" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}" \
  --memory=1024Mi \
  --timeout=300s \
  --service-account=functions-sa@kpro-arim.iam.gserviceaccount.com
```

---

### 2.4 notebook_summarizer

**トリガー**: Firestore `teams/{team_id}/records/{record_id}/cell_logs/{cell_log_id}` の `onCreate`（バッチ処理）

**実装方針**: セルログが追加されるたびに起動するが、実際のサマリー生成はデバウンスして行う（直近30秒以内にセルログが追加されなくなったら生成）。

```python
# functions/notebook_summarizer/main.py
import functions_framework
from google.cloud import firestore
import vertexai
from vertexai.generative_models import GenerativeModel

db = firestore.Client()
vertexai.init(project="kpro-arim", location="asia-northeast1")
gemini = GenerativeModel("gemini-2.0-flash-001")

@functions_framework.cloud_event
def on_cell_log_create(cloud_event):
    """セルログ追加時にNotebookサマリーの再生成をスケジュールする。"""
    doc_path = cloud_event["subject"]
    # teams/{team_id}/records/{record_id}/cell_logs/{cell_log_id}
    parts = doc_path.split("/")
    team_id, record_id = parts[1], parts[3]

    record_ref = db.collection("teams").document(team_id) \
                   .collection("records").document(record_id)

    # デバウンス: summary_pending フラグを立てる
    record_ref.update({
        "_summary_pending": True,
        "_summary_pending_at": firestore.SERVER_TIMESTAMP,
    })

    # 実際のサマリー生成は別のスケジュール実行で行う
    # （Cloud Scheduler で1分間隔で _summary_pending=True のレコードを処理）


def generate_summaries(request):
    """_summary_pending=True のレコードのNotebookサマリーを生成する。
    Cloud Scheduler から1分間隔で呼び出される。
    """
    # pending なレコードを取得
    teams = db.collection("teams").stream()
    for team_doc in teams:
        records = db.collection("teams").document(team_doc.id) \
                    .collection("records") \
                    .where("_summary_pending", "==", True) \
                    .stream()

        for record_doc in records:
            record = record_doc.to_dict()
            pending_at = record.get("_summary_pending_at")

            # 30秒以上経過していたら（デバウンス完了）サマリー生成
            if pending_at and (datetime.now(timezone.utc) - pending_at).total_seconds() > 30:
                _generate_summary_for_record(
                    team_doc.id, record_doc.id, record_doc.reference
                )


def _generate_summary_for_record(team_id, record_id, record_ref):
    """特定レコードのNotebookサマリーを生成する。"""
    # 1. 全セルログを取得
    cell_logs = list(
        record_ref.collection("cell_logs")
        .order_by("cell_number")
        .stream()
    )

    if not cell_logs:
        return

    # 2. セルログをテキスト化
    cells_text = "\n---\n".join([
        f"Cell {c.to_dict()['cell_number']}: "
        f"{c.to_dict().get('source', '')[:500]}\n"
        f"新規変数: {list(c.to_dict().get('new_vars', {}).keys())}\n"
        f"変更変数: {list(c.to_dict().get('changed_vars', {}).keys())}"
        for c in cell_logs
    ])

    # 3. Gemini Flash でサマリー生成
    prompt = f"""以下のJupyter Notebookのセル実行履歴から、
このNotebookで行われた処理を100文字以内で要約してください。
使用した手法名、主要パラメータ、最終結果を含めてください。
日本語で回答してください。

{cells_text}"""

    response = gemini.generate_content(prompt)
    summary = response.text.strip()

    # 4. embedding_text を再構築
    record = record_ref.get().to_dict()
    embedding_text = _build_embedding_text(record, summary)

    # 5. Firestore に書き戻し
    record_ref.update({
        "notebook_summary": summary,
        "embedding_text": embedding_text,
        "_summary_pending": firestore.DELETE_FIELD,
        "_summary_pending_at": firestore.DELETE_FIELD,
    })


def _build_embedding_text(record, notebook_summary):
    """embedding対象テキストを構築する。"""
    parts = []
    parts.append(record.get("title", ""))
    parts.append(record.get("title", ""))  # 2回繰り返し（重み付け）
    parts.append(" ".join(record.get("tags", [])))
    for k, v in record.get("results", {}).items():
        parts.append(f"{k}: {v}")
    for k, v in record.get("conditions", {}).items():
        parts.append(f"{k}={v}")
    for note in record.get("notes", [])[-3:]:
        parts.append(note.get("text", ""))
    if notebook_summary:
        parts.append(notebook_summary)
    return " ".join(filter(None, parts))
```

---

## 3. Firestoreスキーマ（最終版）

### 3.1 完全な構造

```
firestore/ (database: "mdxdb")
│
├── _system/                               # システム管理用
│   └── poller_state/
│       ├── last_check: timestamp          # Nextcloudポーラーの最終チェック時刻
│       └── version: string                # スキーマバージョン
│
├── teams/
│   └── {team_id}/                         # 例: "konishi-lab"
│       ├── team_name: string              # "小西研究室"
│       ├── members: map<uid, role>        # {"tanaka": "admin", "suzuki": "member"}
│       ├── nextcloud_group_folder: string # "konishi-lab"
│       ├── db_name: string                # "experiments"
│       ├── db_version: number             # 1 (メジャーバージョン)
│       ├── created_at: timestamp
│       │
│       ├── templates/ (サブコレクション)
│       │   └── {template_name}/           # "xrd", "sem", "thermal_treatment"
│       │       ├── display_name: string   # "XRD測定"
│       │       ├── type: string           # "experiment"
│       │       ├── default_tags: array<string>   # ["XRD"]
│       │       ├── condition_fields: array<map>  # [{name, type, unit, default}]
│       │       ├── result_fields: array<map>     # [{name, type, unit}]
│       │       └── description: string
│       │
│       └── records/ (サブコレクション)
│           └── {record_id}/               # "AB3F" (Crockford's Base32, 4文字)
│               │
│               │ === 基本メタデータ ===
│               ├── title: string                  # "Fe-10Cr XRD解析 500度焼鈍"
│               ├── type: string                   # "experiment" | "sample" | "process" | "computation"
│               ├── status: string                 # "success" | "failed" | "partial" | "in_progress"
│               ├── tags: array<string>            # ["XRD", "Fe-Cr", "BCC"]
│               ├── conditions: map                # {temperature_C: 500, atmosphere: "Ar", ...}
│               ├── results: map                   # {lattice_a: 2.873, n_peaks: 12, ...}
│               ├── result_keys: array<string>     # ["lattice_a", "n_peaks"] (検索用)
│               ├── notes: array<map>              # [{text: "BCC単相", by: "tanaka", at: timestamp}]
│               ├── created_by: string             # "tanaka"
│               ├── created_at: timestamp
│               ├── updated_at: timestamp
│               ├── parent_id: string | null       # 親レコードID（子レコードの場合）
│               ├── visibility: string             # "team" | "private"
│               ├── template_used: string | null   # 使用テンプレート名
│               ├── deleted_at: timestamp | null   # ソフトデリート（null=有効）
│               │
│               │ === ファイル参照 ===
│               ├── file_refs: array<map>
│               │   # [{
│               │   #   name: "xrd_raw.ras",
│               │   #   path: "large/konishi-lab/v1/experiments/AB3F/_data/xrd_raw.ras",
│               │   #   size: 245000,
│               │   #   type: "ras",
│               │   #   uploaded_at: "2026-03-16T10:00:00Z",
│               │   #   source: "sdk" | "nextcloud_browser" | "webapp",
│               │   # }]
│               ├── nextcloud_path: string         # "large/konishi-lab/v1/experiments/AB3F"
│               │
│               │ === 外部参照（add_ref） ===
│               ├── external_refs: array<map>
│               │   # [{
│               │   #   path: "/hpc/scratch/WAVECAR",
│               │   #   location: "TSUBAME:/home/user/WAVECAR",
│               │   #   size_gb: 8.5,
│               │   #   description: "波動関数ファイル",
│               │   #   doi: null,
│               │   # }]
│               │
│               │ === プレビュー ===
│               ├── preview_refs: map
│               │   # {
│               │   #   "xrd_raw_ras": {filename, type, stats...},
│               │   #   "SEM_50000x_tif": {filename, type, width, height, thumbnail_path...},
│               │   # }
│               │
│               │ === Embedding ===
│               ├── embedding: vector(768)         # Vertex AI text-embedding-004
│               ├── embedding_text: string          # embedding生成元テキスト
│               ├── embedding_text_hash: string     # 無限ループ防止用ハッシュ
│               ├── embedding_updated_at: timestamp
│               │
│               │ === 自動ログサマリー ===
│               ├── notebook_summary: string | null # Gemini生成のNotebookサマリー
│               ├── trace_summary: string | null    # トレースのL1サマリー
│               │
│               │ === サブコレクション ===
│               │
│               ├── cell_logs/ (サブコレクション)   ★ IPython hooks 自動記録
│               │   └── {cell_log_id}/             # auto-generated ID
│               │       ├── cell_number: number     # セル番号
│               │       ├── source: string          # セルのソースコード（最大5000文字）
│               │       ├── execution_count: number # IPythonの実行カウント
│               │       ├── timestamp: timestamp
│               │       ├── duration_sec: number
│               │       ├── new_vars: map           # {cutoff: 0.5, data: "<ndarray (5000,2)>"}
│               │       ├── changed_vars: map       # {cutoff: {before: 0.5, after: 0.3}}
│               │       ├── error: string | null    # エラートレースバック
│               │       ├── output_summary: string | null  # セル出力の要約
│               │       └── imports: array<string>  # ["numpy", "scipy.signal"]
│               │
│               ├── traces/ (サブコレクション)      ★ @exp.track 関数トレース
│               │   └── {trace_id}/                # auto-generated ID
│               │       ├── type: string            # "track" | "snapshot"
│               │       ├── timestamp: timestamp
│               │       ├── function: string | null # track型: "process_xrd"
│               │       ├── file: string            # "analysis.py"
│               │       ├── line: number            # 42
│               │       ├── args: map | null        # {data: "<ndarray>", cutoff: 0.5}
│               │       ├── return_value: map | null
│               │       ├── call_tree: map | null   # ネスト呼び出しツリー
│               │       ├── variables: map | null   # snapshot型: キャプチャ変数
│               │       ├── duration_sec: number
│               │       ├── env: map                # {python: "3.12", packages: {...}}
│               │       └── summary: string         # L1サマリー
│               │
│               └── analyses/ (サブコレクション)    ★ LLMコード実行履歴
│                   └── {analysis_id}/             # Crockford's Base32 (例: "AN7K")
│                       ├── id: string              # "AN7K"
│                       ├── name: string            # "gaussian_fit_001"
│                       ├── code: string            # 実行したPythonコード全文
│                       ├── input_files: array<string>    # ["xrd.csv"]
│                       ├── input_analyses: array<string> # ["AM3J"] (前の解析を入力にした場合)
│                       ├── results: map            # {center: 28.4, sigma: 0.18, fwhm: 0.42}
│                       ├── images: array<string>   # ["AN7K_fit_plot.png"]
│                       ├── stdout: string          # 標準出力
│                       ├── executed_at: timestamp
│                       ├── executed_by: string     # "claude" | ユーザー名
│                       ├── prompt: string | null   # "正規分布でフィッティングして"
│                       ├── duration_sec: number
│                       ├── packages: map           # {scipy: "1.12.0", numpy: "1.26.0"}
│                       └── error: string | null    # エラー時のトレースバック
```

### 3.2 インデックス定義

```
# 複合インデックス（Firestore コンソール or gcloud で作成）

# 1. レコード検索（タグ + ステータス + 日時）
Collection: teams/{team_id}/records
Fields: tags(ARRAY_CONTAINS), status(ASC), created_at(DESC)

# 2. レコード検索（作成者 + 日時）
Collection: teams/{team_id}/records
Fields: created_by(ASC), created_at(DESC)

# 3. レコード検索（タイプ + 日時）
Collection: teams/{team_id}/records
Fields: type(ASC), created_at(DESC)

# 4. レコード検索（親ID + 日時）— 子レコード取得用
Collection: teams/{team_id}/records
Fields: parent_id(ASC), created_at(ASC)

# 5. ソフトデリート除外
Collection: teams/{team_id}/records
Fields: deleted_at(ASC), created_at(DESC)

# 6. 結果キー検索
Collection: teams/{team_id}/records
Fields: result_keys(ARRAY_CONTAINS), status(ASC), created_at(DESC)

# 7. ベクトル検索（Firestore Vector Search）
Collection: teams/{team_id}/records
Vector field: embedding (768次元)
Distance: COSINE

# 8. セルログ（セル番号順）
Collection: teams/{team_id}/records/{record_id}/cell_logs
Fields: cell_number(ASC)

# 9. 解析履歴（日時順）
Collection: teams/{team_id}/records/{record_id}/analyses
Fields: executed_at(DESC)

# 10. サマリー保留レコード（ポーラー用）
Collection: teams/{team_id}/records
Fields: _summary_pending(ASC), _summary_pending_at(ASC)
```

**gcloud コマンドによるインデックス作成**:
```bash
# firestore.indexes.json から一括作成
gcloud firestore indexes composite create \
  --database=mdxdb \
  --collection-group=records \
  --field-config field-path=tags,array-config=CONTAINS \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=DESCENDING

# ベクトルインデックス
gcloud firestore indexes composite create \
  --database=mdxdb \
  --collection-group=records \
  --field-config=vector-config='{"dimension":"768","flat": {}}',field-path=embedding
```

### 3.3 セキュリティルール

```javascript
// infra/firestore.rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // システムコレクション: サービスアカウントのみ
    match /_system/{document=**} {
      allow read, write: if false;  // Admin SDK / サービスアカウントのみ
    }

    // チームコレクション
    match /teams/{teamId} {
      // チーム情報の読み取り: チームメンバーのみ
      allow read: if isTeamMember(teamId);
      // チーム情報の書き込み: 管理者のみ
      allow write: if isTeamAdmin(teamId);

      // レコード
      match /records/{recordId} {
        allow read: if isTeamMember(teamId);
        allow create: if isTeamMember(teamId);
        allow update: if isTeamMember(teamId);
        // 削除（ソフトデリート）: 作成者 or 管理者のみ
        allow delete: if isRecordOwner(teamId, recordId) || isTeamAdmin(teamId);

        // セルログ: レコードの作成者のみ書き込み可能
        match /cell_logs/{logId} {
          allow read: if isTeamMember(teamId);
          allow write: if isTeamMember(teamId);
        }

        // トレース: レコードの作成者のみ書き込み可能
        match /traces/{traceId} {
          allow read: if isTeamMember(teamId);
          allow write: if isTeamMember(teamId);
        }

        // 解析履歴: チームメンバーなら書き込み可能
        match /analyses/{analysisId} {
          allow read: if isTeamMember(teamId);
          allow write: if isTeamMember(teamId);
        }
      }

      // テンプレート
      match /templates/{templateId} {
        allow read: if isTeamMember(teamId);
        allow write: if isTeamAdmin(teamId);
      }
    }

    // ヘルパー関数
    function isTeamMember(teamId) {
      return request.auth != null &&
             request.auth.uid in get(/databases/$(database)/documents/teams/$(teamId)).data.members;
    }

    function isTeamAdmin(teamId) {
      return request.auth != null &&
             get(/databases/$(database)/documents/teams/$(teamId)).data.members[request.auth.uid] == "admin";
    }

    function isRecordOwner(teamId, recordId) {
      return request.auth != null &&
             get(/databases/$(database)/documents/teams/$(teamId)/records/$(recordId)).data.created_by == request.auth.uid;
    }
  }
}
```

**Phase 1 の簡易ルール（サービスアカウント認証のみ）**:
```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Phase 1: サービスアカウントのみアクセス（Admin SDKは自動バイパス）
    // クライアントSDKからの直接アクセスは全て拒否
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

---

次のセクション（4-8）は次のパートで続きます。
