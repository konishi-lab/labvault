# labvault v9 概要

> v8実装仕様をベースに、パッケージ名の `labvault` 統一、認証・チーム管理API追加、
> サンドボックス具体設計、マイグレーション要件、要件番号の線形化を行った最終設計。

---

## 1. v8 → v9 変更サマリー

| 変更点 | v8 | v9 |
|--------|----|----|
| パッケージ名 | `mdxdb` (import/CLI/設定ファイルすべて) | **`labvault`** に全面移行 |
| 認証・認可 | 設計なし（暗黙のGCP前提） | **R18**: GCP ADC + Cloud Run IAM + ロール設計を明文化 |
| チーム管理 | Firestoreスキーマのみ | **R19**: `labvault init` 対話フロー + admin/member権限API |
| コード実行サンドボックス | "Cloud Functions or Cloud Run" と曖昧 | **R16**: Cloud Run Jobs + gVisor の具体設計（`03_sandbox_design.md`） |
| マイグレーション | スコープ外 | **R22**: 旧 Nextcloud/mdxdb → labvault 変換スクリプト |
| 要件番号 | Tier 1/2/3 (#1-#19) + 8a/8b/8c | **R01-R22** 線形化（REQUIREMENTS.md と 1:1 対応） |
| MCPサーバー | Cloud Functions (Gen2) | **Cloud Run**（Streamable HTTP transport） |
| リポジトリ | `kpro-arim-mdxdb` / `kpro-arim-platform` | `konishi-lab/labvault` / `konishi-lab/labvault-platform` |

---

## 2. REQUIREMENTS 対応表（R01-R22）

| 要件ID | 要件名 | v9設計書の対応セクション | MVP | 実現方法（1行） |
|--------|--------|------------------------|:---:|----------------|
| R01 | チームデータ共有 | 01_sdk 1.6 Lab + 02_platform 3. Firestore | MVP | Firestore `teams/{team_id}/records/` |
| R02 | 子レコード | 01_sdk 1.7 Record.sub() | MVP | サブコレクション `sub_records/` |
| R03 | 別PC紐付け | 01_sdk 1.3 IDジェネレーター + 01_sdk 1.7 Record.add() | MVP | Crockford's Base32 4文字ID |
| R04 | タグ・ステータス | 01_sdk 1.7 Record | MVP | Firestoreフィールド操作 |
| R05 | Recordモデル汎用化 | 01_sdk 1.2 RecordType | MVP | typeフリーテキスト |
| R06 | ソフトデリート | 01_sdk 1.6 Lab.delete() | MVP | `status="deleted"` + 30日TTL |
| R07 | 使いやすいSDK | 01_sdk 1.6 Lab + 1.7 Record | MVP | 3行で開始 |
| R08 | ローカルバッファ | 01_sdk 3. バッファ仕様 | MVP | SQLite + ローカルファイルコピー |
| R09 | 大容量データ | 01_sdk 1.7 Record.add_ref() | MVP | 3段階（add / 非同期 / 参照） |
| R10 | 投入経路 | 01_sdk + 02_platform | MVP(SDK+CLI) | SDK / CLI / ブラウザ / WebApp |
| R11 | テンプレート | 01_sdk 1.6 Lab.define_template() | MVP | Firestore `templates/` |
| R12 | 自動トリガー | 02_platform Cloud Functions | M5 | `data_refs` 更新 → Cloud Functions |
| R13 | 自動ログ | 01_sdk 4. IPython hooks | MVP | 3層（hooks / track / snapshot） |
| R14 | LLM検索 | 02_platform 1. MCP search | MVP | Vector Search + 構造化フィルタ |
| R15 | MCPサーバー | 02_platform 1. 全14ツール | MVP(11) | FastMCP + Cloud Run |
| R16 | コード実行 | 03_sandbox_design | M5 | Cloud Run Jobs サンドボックス |
| R17 | LLMの役割 | 設計方針 | - | LLM = オーケストレーター |
| R18 | 認証・認可 | 01_sdk 1.8 認証 + 02_platform 認証 | MVP | GCP ADC + Cloud Run IAM |
| R19 | チーム管理 | 01_sdk 1.8 チーム管理 | MVP | Firestore `teams/{team_id}/info` |
| R20 | エクスポート | 01_sdk 1.6 Lab.export() | M6 | JSON Lines + ファイルコピー |
| R21 | バッチ操作 | 01_sdk 1.7 Record.sweep() | M6 | 子レコード一括生成 |
| R22 | マイグレーション | 05_milestones M6 | M6 | 変換スクリプト |

**MVP判定の凡例**: MVP = Week 7までに実装。M5/M6 = MVP後のマイルストーン。

---

## 3. ユーザーフロー（3シナリオ）

### シナリオA: 実験者（Jupyter Notebook）

実験者が日常的にデータを記録する最も典型的なフロー。

```python
# Step 1: Lab初期化（初回のみ team 設定が必要）
from labvault import Lab
lab = Lab("konishi-lab")

# Step 2: レコード作成
exp = lab.new("Fe-Cr薄膜 スパッタ成膜", type="experiment")
# → Crockford's Base32 ID が自動生成（例: "AB3F"）
# → IPython hooks が自動起動し、以降の全セルを記録

# Step 3: 実験条件の記録
exp.conditions(temperature_C=300, pressure_Pa=0.5, atmosphere="Ar")
exp.tag("sputtering", "Fe-Cr")

# Step 4: セル自動記録（実験者の手間ゼロ）
# ── 通常の実験コードを書くだけ ──
import numpy as np
data = np.loadtxt("xrd_result.csv", delimiter=",")
# → このセルのソースコード・変数変更・実行時間が自動で cell_logs/ に保存

# Step 5: データ保存
exp.add("xrd_result.csv", conditions={"type": "XRD", "2theta_range": "20-80"})
exp.add("sem_images/")                             # ディレクトリごと追加
exp.add_ref(location="TSUBAME:/work/vasp/WAVECAR", size_gb=12)  # 大容量は参照のみ

# Step 6: 結果記録
exp.results["lattice_a"] = 2.873
exp.results["phase"] = "BCC"
exp.status = "success"
exp.note("格子定数は文献値と一致。追加測定不要。")
```

**ポイント**: `lab.new()` の1行だけで IPython hooks が起動し、以降のセルは全て自動記録される。実験者は普段通りコードを書くだけでよい。

---

### シナリオB: 解析者（Claude Desktop MCP経由）

Claude DesktopやClaude CodeからMCPサーバー経由でデータにアクセスするフロー。
LLMがツールを自動選択し、自然言語で対話的に解析を進める。

```
ユーザー: 「先週のFe-Cr実験で格子定数が2.87以下のものを探して」

LLM の行動:
  1. search(query="Fe-Cr 格子定数", tags=["Fe-Cr"], limit=20)
     → 候補レコード一覧を取得

  2. get_results(filters={"lattice_a": {"lt": 2.87}})
     → 構造化結果から条件に合うレコードを絞り込み

  3. get_detail(record_id="AB3F", include_analyses=true)
     → 詳細メタデータ（条件・結果・解析履歴）を取得

  4. explain_result(record_id="AB3F", result_key="lattice_a")
     → 格子定数の算出過程（どのセルで、どのコードで計算されたか）を追跡

LLM → ユーザー:
  「AB3Fのレコード（Fe-Cr薄膜、300度成膜）で lattice_a=2.865 でした。
   XRDデータの (110) ピークからBragg式で算出されています。
   成膜温度を上げると格子定数が増加する傾向が見られます。
   他の温度条件と比較しますか？」
```

**ポイント**: LLMはオーケストレーターとして振る舞い、適切なツールを順番に呼び出す。数値計算が必要な場合は `execute_code`（M5）に委譲する。

---

### シナリオC: PI / 管理者

チームの初期セットアップとメンバー管理、進捗確認のフロー。

```bash
# Step 1: チーム作成（初回のみ）
$ labvault init
  Team name: konishi-lab
  GCP Project: kpro-arim
  Nextcloud group folder: large/konishi-lab
  Your name: konishi
  → ~/.labvault/config.toml に設定を保存
  → Firestore teams/konishi-lab/info を作成
  → あなたは admin として登録されました

# Step 2: メンバー招待
$ labvault team add-member tanaka
  → tanaka を konishi-lab の member として追加

$ labvault team add-member suzuki --role admin
  → suzuki を admin として追加
```

```
# Step 3: 進捗確認（Claude Desktop MCP経由）
ユーザー（PI）: 「今月の実験の進捗を見せて」

LLM の行動:
  1. aggregate(query="今月の実験", agg_field="status", agg_func="count")
     → { "success": 12, "in_progress": 3, "failed": 2, "partial": 1 }

  2. aggregate(query="今月の実験", agg_field="created_by", agg_func="count")
     → { "tanaka": 8, "suzuki": 5, "yamada": 5 }

  3. search(query="failed", status="failed", limit=5)
     → 失敗実験の一覧

LLM → PI:
  「今月は18件の実験が完了し、成功率は67%です。
   田中さんが8件と最も多く、失敗2件はいずれもスパッタ圧力の設定ミスでした。
   詳細を確認しますか？」
```

**ポイント**: PIはCLIでチーム管理、MCPで進捗把握。コードを書く必要はない。

---

## 4. v9 ディレクトリ構成

```
docs/design/v9/
├── 00_v9_overview.md              ← 本ファイル
├── 01_sdk_implementation.md       ← SDK実装仕様（Lab, Record, Buffer, IPython hooks）
├── 02_platform_implementation.md  ← プラットフォーム仕様（MCP, Cloud Functions, Firestore, GCP）
├── 03_sandbox_design.md           ← execute_code サンドボックス詳細設計（R16）
├── 04_auth_and_team.md            ← 認証・認可・チーム管理（R18, R19）
└── 05_milestones.md               ← マイルストーン計画 + 全要件充足マトリクス
```

### 推奨する読み順

1. **00_v9_overview.md**（本ファイル） -- 全体像と変更点の把握
2. **01_sdk_implementation.md** -- SDK APIの全クラス・全メソッド定義。開発の中心
3. **02_platform_implementation.md** -- MCPサーバー14ツール、Cloud Functions、Firestoreスキーマ
4. **04_auth_and_team.md** -- 認証フローとチーム管理。01/02の横断的な関心事
5. **03_sandbox_design.md** -- M5フェーズの execute_code 設計。MVP後に参照
6. **05_milestones.md** -- 実装順序とスケジュール。全要件の充足確認

### 各ファイルの概要

| ファイル | 内容 | 対応要件 |
|---------|------|---------|
| 01_sdk_implementation.md | Settings, Lab, Record, RecordType, IDジェネレーター, ローカルバッファ（SQLite）, IPython hooks, `@exp.track`, `exp.snapshot()` の型付きシグネチャ + テストケース | R01-R11, R13, R20-R21 |
| 02_platform_implementation.md | MCP 14ツールの入出力仕様, Cloud Functions（embedding, poller, preview）, Firestoreスキーマ最終版, Nextcloudディレクトリ構造, GCPインフラ設定 | R12, R14-R15, R17 |
| 03_sandbox_design.md | Cloud Run Jobs + gVisor によるサンドボックス環境。タイムアウト・メモリ制限・ネットワーク隔離・プリインストールパッケージ。解析履歴の自動保存フロー | R16 |
| 04_auth_and_team.md | GCP Application Default Credentials, Cloud Run IAM invoker, Bearer Token, admin/member ロール, `labvault init` フロー, データの visibility 制御 | R18, R19 |
| 05_milestones.md | M0-M8 の週次スケジュール, 各マイルストーンの成果物定義, 全R01-R22充足マトリクス, リスク一覧 | R22 + 全体 |

---

## 確定アーキテクチャ（v9）

```
SDK (pip install labvault)
├── IPython hooks（全セル自動記録）
├── ローカルバッファ（SQLite + ローカルファイルコピー）
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

## 次のアクション

1. **01_sdk_implementation.md** の作成 -- v8の `mdxdb` を `labvault` に置換し、認証・チーム管理APIを追加
2. **02_platform_implementation.md** の作成 -- MCPサーバーのデプロイ先をCloud Runに統一
3. **03_sandbox_design.md** の作成 -- execute_code の具体的な隔離方式を設計
4. **04_auth_and_team.md** の作成 -- R18/R19の詳細設計
5. **05_milestones.md** の作成 -- R22マイグレーションを含むスケジュール更新
