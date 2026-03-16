# v8 実装仕様 統合ドキュメント

> v7設計 + 新要件（大容量データ、LLMコード実行解析、自動トリガー）を統合した実装仕様。
> **このままコードを書き始められるレベル。**
>
> 詳細:
> - v7/01_sdk_design.md — SDK実装設計ベース（IPython hooks、ローカルバッファ、API）(77KB)
> - v7/02_platform_design.md — プラットフォーム設計ベース（GCP、MCP、WebApp）(58KB)
> - [03_final_milestones.md](./03_final_milestones.md) — 全要件充足マトリクス + マイルストーン (28KB)

---

## v7→v8 の追加要件

| # | 新要件 | MVP | 実現方法 |
|---|--------|:---:|---------|
| 8a | 大容量データ（`add_ref()`） | ✅ | 参照登録。Firestore にメタデータのみ |
| 8b | LLMコード実行解析 | M5 | `execute_code` / `batch_execute` + サンドボックス |
| 8c | 自動処理トリガー | M5 | Cloud Functions + `_preview/` 生成 |
| — | 解析履歴の自動保存・連鎖 | M5 | `analyses/` サブコレクション |
| — | ソフトデリート | ✅ | `status="deleted"` + 30日TTL |

---

## 確定アーキテクチャ

```
SDK (pip install mdxdb)
├── IPython hooks（全セル自動記録）
├── ローカルバッファ（SQLite。データ消失防止）
├── Firestore（メタデータ + Vector Search + セルログ + 解析履歴）
└── Nextcloud（30TB。バイナリ実体 + ブラウザ投入口）

MCP Server (Cloud Functions)
├── 検索系: search, get_detail, compare, data_preview, get_results, aggregate
├── 履歴系: get_timeline, get_trace, explain_result, compare_runs, get_notebook_log
└── 実行系: execute_code, batch_execute, get_image  ← v8追加

Cloud Functions (トリガー)
├── embedding_generator（レコード作成時 → Vertex AI → embedding書き戻し）
├── nextcloud_poller（5分間隔 → ブラウザ投入の自動認識）
└── preview_generator（ファイル追加時 → サムネイル/統計サマリー生成）← v8追加
```

---

## Firestoreスキーマ（v8最終版）

```
teams/{team_id}/
├── info: {name, nextcloud_group_folder, members, admin}
├── templates/{name}: {type, defaults, recommended_results}
└── records/{record_id}/
    ├── id: "AB3F"                     # Crockford's Base32
    ├── title: str
    ├── type: str                      # "experiment"|"sample"|"process"|etc.
    ├── status: str                    # "in_progress"|"success"|"failed"|"partial"|"deleted"
    ├── deleted_at: timestamp | null   # ソフトデリート用
    ├── tags: [str]
    ├── created_by: str
    ├── created_at: timestamp
    ├── updated_at: timestamp
    ├── visibility: "team"|"private"
    ├── conditions: {}                 # 物理条件（温度、圧力等）
    ├── results: {}                    # 構造化結果（lattice_a: 2.873等）
    ├── notes: [{text, author, timestamp}]
    ├── parent_id: str | null
    ├── links: [{target_id, relation}]
    ├── template_used: str | null
    ├── embedding: vector(768)
    ├── data_refs: {                   # ファイル参照
    │     "xrd.ras": {
    │       nextcloud_path: str,
    │       size_bytes: int,
    │       content_type: str,
    │       conditions: {},            # 測定条件（ファイル単位）
    │       preview: {                 # 自動生成プレビュー情報
    │         thumbnail: str,          # _preview/ のパス
    │         summary: {},             # 統計サマリー
    │       }
    │     }
    │   }
    ├── external_refs: [{              # 大容量データ参照・外部リンク
    │     location: str,               # "TSUBAME:/path/to/WAVECAR"
    │     doi: str | null,
    │     size_gb: float | null,
    │     description: str
    │   }]
    │
    ├── cell_logs/ (subcollection)     # IPython hooks自動記録
    │   └── {log_id}: {
    │       cell_number: int,
    │       source: str,               # セルのソースコード
    │       new_vars: {},              # 新規変数
    │       changed_vars: {},          # 変更変数
    │       duration_sec: float,
    │       timestamp: timestamp
    │     }
    │
    ├── traces/ (subcollection)        # @exp.track 関数トレース
    │   └── {trace_id}: {
    │       function: str,
    │       file: str, line: int,
    │       args: {}, return_value: {},
    │       call_tree: {},             # ネスト
    │       duration_sec: float,
    │       env: {python, packages, git_commit}
    │     }
    │
    ├── analyses/ (subcollection)      # LLMコード実行結果
    │   └── {analysis_id}: {           # Crockford's Base32 ("AN7K")
    │       id: str,
    │       name: str,                 # "gaussian_fit_001"（バッティング防止）
    │       code: str,                 # 実行したPythonコード全文
    │       prompt: str,               # 元の指示
    │       input_files: [str],
    │       input_analyses: [str],     # 前の解析結果を入力にした場合
    │       results: {},               # 数値結果
    │       images: [str],             # 生成画像のNextcloudパス
    │       executed_by: str,
    │       executed_at: timestamp,
    │       duration_sec: float,
    │       packages: {}
    │     }
    │
    └── sub_records/ (subcollection)   # 子レコード（再帰）
```

---

## MCPサーバー（14ツール最終版）

| # | ツール | 入力 | 出力 | Phase |
|---|--------|------|------|-------|
| 1 | `search` | query, tags, type, status, limit | レコード一覧（L1サマリー付き） | MVP |
| 2 | `get_detail` | record_id, include_analyses | レコード全メタデータ | MVP |
| 3 | `compare` | record_ids, fields | 差分テーブル | MVP |
| 4 | `data_preview` | record_id, filename | 統計サマリー + 先頭N行 | MVP |
| 5 | `get_results` | filters (key, range) | 構造化結果の横断検索 | MVP |
| 6 | `aggregate` | query, agg_field, agg_func | 集約結果（平均、件数等） | MVP |
| 7 | `get_timeline` | sample_name or record_id | 時系列の実験履歴 | MVP |
| 8 | `get_trace` | record_id, trace_id, level | 関数トレース（L1/L2/L3） | MVP |
| 9 | `explain_result` | record_id, result_key | 結果の算出過程 | MVP |
| 10 | `compare_runs` | record_ids, function_name | パラメータ差異 | MVP |
| 11 | `get_notebook_log` | record_id, level | セルログ（L1/L2/L3） | MVP |
| 12 | **`execute_code`** | record_id, file, code | 数値結果 + 画像パス | M5 |
| 13 | **`batch_execute`** | record_ids, file, code | 一括結果 + 比較画像 | M5 |
| 14 | **`get_image`** | record_id, analysis_id, image | 画像データ | M5 |

---

## SDK主要API（最終版）

```python
from mdxdb import Lab

# 初期化
lab = Lab("konishi-lab")

# レコードCRUD
exp = lab.new("タイトル", sample="試料名", type="experiment")
exp = lab.get("AB3F")
results = lab.search(tag="XRD", sample__contains="Fe-Cr")
results = lab.search("温度300度以上の実験")  # セマンティック検索
recent = lab.recent(10)

# データ追加
exp.add("path/to/file")                      # ファイル（→ローカルバッファ→Nextcloud）
exp.add("path/to/dir/")                       # ディレクトリ
exp.add("file.ras", conditions={"type":"XRD"})# 測定条件付き
exp.add_ref(location="HPC:/path", size_gb=8)  # 大容量参照
exp.add_ref(doi="10.5281/zenodo.12345")        # 外部リンク
exp.save("name", data)                         # 型自動判定

# 階層
child = exp.sub("加工条件A", type="process")
child.sub("測定", type="measurement")
exp.tree()                                     # ツリー表示
exp.link(other_exp, relation="compare")        # リンク

# メタデータ（後付け可能）
exp.tag("XRD", "Fe-Cr")
exp.status = "success"
exp.note("メモ")
exp.conditions(temperature_C=300, atmosphere="Ar")
exp.results["lattice_a"] = 2.873

# 解析履歴
exp.analyses()                                 # 一覧
exp.analyses(name="gaussian_fit")              # 名前検索
exp.analyses(id="AN7K")                        # ID検索

# 自動ログ制御
exp.pause_logging()
exp.resume_logging()

# エクスポート・削除
lab.export("./backup/")
lab.delete("AB3F")                             # ソフトデリート
lab.trash()                                    # ゴミ箱一覧
lab.restore("AB3F")                            # 復元

# CLI
# mdxdb init / new / add / search / show / today / url / export
```

---

## マイルストーン（確定版）

```
Week 1-2:   M0 基盤 + POC（GCP設定、性能検証）
Week 2-4:   M1 SDK Core（Lab, Record, Firestore, Nextcloud, ローカルバッファ）
Week 4-5:   M2 自動ログ（IPython hooks, @exp.track, snapshot）
Week 5-6:   M3 Embedding + Vector Search
Week 6-7:   M4 MCP Server + CLI

Week 7:     ★ MVP完成 → チームAlpha利用開始

Week 8-9:   M5 execute_code + 自動トリガー + 解析履歴
Week 10-11: M6 拡張（sweep, export, テンプレート拡充）
Week 12-14: M7 WebApp（Streamlit）
Week 14+:   M8 BigQuery連携
```

**MVP（Week 7）に含まれるもの:**
- SDK: Lab, Record, add, save, sub, search, tag, status, results, conditions
- 自動ログ: IPython hooks, @exp.track, snapshot
- ローカルバッファ: SQLite（データ消失防止）
- 大容量: add_ref
- ソフトデリート
- Embedding + Vector Search
- MCP: 11ツール（execute_code系3つはM5）
- CLI: init, new, add, search, show, today

**MVP後:**
- execute_code / batch_execute / get_image（M5）
- 自動トリガー preview_generator（M5）
- sweep, export（M6）
- WebApp Streamlit（M7）
- BigQuery（M8）

---

## 次のアクション

1. **パッケージ名を決定**（`mdxdb` が第1候補。PyPI空き確認）
2. **M0開始**: GCPプロジェクト作成 + POC（Firestore Vector Search性能、IPython hooks安定性）
3. **M1開始**: SDK Core実装（v7/01_sdk_design.md のコードをベースに）
