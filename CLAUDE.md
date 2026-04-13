# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**labvault** — Python/Notebookで実験する研究室のための実験データ基盤。測定から解析までのコード・データ・条件が自動で記録され、蓄積されたデータをLLMが横断検索・解析する。

- 実験者向けPython SDK + CLI (16コマンド) + MCP サーバー (7ツール)
- バックエンド: Firestore（メタデータ）+ Nextcloud（ARIM MDX, 30TBバイナリ）+ Vertex AI（Embedding）
- LLM連携: ローカル MCP サーバー（`labvault mcp`）でClaude Desktop/Codeがデータを検索・解析。CLI 経由でも同等の分析が可能（トークン効率が良い）
- Web UI: `platform/` ディレクトリ（Next.js + FastAPI on Cloud Run）
- 月額GCPコスト: $1以下（Firestore + Vertex AI + Cloud Run 無料枠）

## 開発コマンド

```bash
# インストール
pip install -e ".[dev]"

# テスト（319テスト）
pytest

# 単一テスト
pytest tests/unit/test_record.py

# 結合テスト（実サーバー接続）
pytest tests/integration/ -v -m integration

# リント・フォーマット
ruff check src/ tests/
ruff format src/ tests/
mypy src/

# CLI
labvault --help
labvault doctor

# MCP サーバー起動
labvault mcp
```

## アーキテクチャ

```
src/labvault/
├── core/          # Lab, Record, types, config, id生成, units, exceptions
├── backends/      # Backend Protocol (全sync)
│   ├── memory.py      # InMemory (テスト用)
│   ├── firestore.py   # Firestore (メタデータ永続化)
│   ├── nextcloud.py   # Nextcloud (ファイルストレージ)
│   └── embedding.py   # Vertex AI text-embedding-004 (セマンティック検索)
├── tracking/      # IPython hooks自動ログ
│   ├── cell_tracker.py  # pre/post_run_cell hooks, CellLog生成
│   ├── digest.py        # O(1) オブジェクトダイジェスト (ndarray, DataFrame等)
│   └── namespace.py     # namespace キャプチャ, diff, 機微情報マスク
├── buffer/        # ローカルバッファ + 自動同期
│   ├── database.py  # SQLite WAL (データ消失防止)
│   └── sync.py      # SyncManager (daemon スレッドで定期同期)
├── mcp/           # MCP サーバー (7ツール)
├── parsers/       # ファイルパーサープラグイン（.vk4 実装済、.ras等 M3で追加予定）
└── cli/           # Click CLI (16コマンド)

platform/          # デプロイ可能なサービス群
├── frontend/      # Next.js Web UI (レコード閲覧、散布図、一括アップロード等)
├── backend/       # FastAPI (labvault SDK ラッパー API)
└── README.md

examples/          # すぐ試せるサンプル
├── 01_quickstart.ipynb
├── 02_instrument_script.py
└── 03_search_and_organize.ipynb
```

## 設計資料

- `docs/design/v10/` — **現行の設計仕様**（v10）
  - `00_v10_overview.md` — 概要・アーキテクチャ・コスト
  - `01_architecture_and_cost.md` — インフラ設計・コスト詳細
  - `02_sdk_and_mcp.md` — SDK変更・MCPツール・pyproject.toml
  - `03_experiment_workflow.md` — テンプレート・パーサー・装置投入
  - `04_sdk_cookbook.md` — SDK使い方ガイド（全APIのコード例）
  - `05_milestones.md` — 実装マイルストーン
- `docs/design/analysis_traceability.md` — **解析トレーサビリティ設計**（解析=Record、コード保存、再実行）
- `docs/design/v9/` — v9実装仕様（レビュー済み。v10の元）
- `docs/design/REQUIREMENTS.md` — 要件定義（R01-R22）
- `docs/comparison_report.md` — mdxdb + webapp との比較資料

## 実装状況

| マイルストーン | 状態 |
|---|---|
| **M0** 基盤 (CI, pyproject.toml) | 完了 |
| **M1** SDK Core (Lab/Record, バッファ, ファイル操作) | 完了 |
| **M2a** Firestore バックエンド | 完了 (klab-proto 確認済) |
| **M2b** Nextcloud バックエンド | 完了 (ARIM MDX 確認済) |
| **M2c** SyncManager (自動同期) | 完了 |
| **M2d** IPython hooks (セル自動記録) | 完了 |
| **M4** CLI (16コマンド) | 完了 |
| **M4** Embedding (Vertex AI) | 完了 (動作確認済) |
| **M4** MCP サーバー (7ツール) | 完了 (Claude Code 動作確認済) |
| **M6** WebApp (Next.js + FastAPI) | 進行中 (レコード閲覧、条件カラム、散布図、一括アップロード) |
| **M3** テンプレート + パーサー | 未着手 |
| **M5** 拡張 (ProcessChain等) | 未着手 |

## 重要な規約

- **パッケージ名**: `labvault`（import: `from labvault import Lab`）
- **ID**: Crockford's Base32（6文字、大文字のみ。例: "AB3F7K"）※既存の4文字IDとの互換あり
- **Backend Protocol**: **全sync**。Notebook event loop競合回避のため async は使わない
- **ローカルバッファ**: `_persist()` はメタデータバックエンド + SQLite バッファの両方に書く
- **バックエンド自動選択**: .env / config.toml に設定があれば Firestore/Nextcloud を自動使用、なければ InMemory
- **IPython hooks**: Notebook環境では `lab.new()` で全セル自動記録開始
- **既存Recordへの追記**: `lab.get(id, auto_log=True)` でhooks再起動
- **装置制御スクリプト(.py)**: `exp.log_value()` / `exp.log_event()` を使う
- **セル再実行の冪等性**: note()重複防止、add()ファイル重複防止、セルログexecution_count上書き
- **テスト**: InMemoryBackendで全テストがオフラインで動くこと。`-m integration` で実サーバーテスト
- **例外名**: `LabvaultPermissionError`（ビルトインPermissionErrorとの衝突回避）
- **依存軽量化**: `google-cloud-aiplatform` は使わない。Embedding は REST API 直接呼び出し
- **MCP**: `mcp` パッケージはオプショナル依存。import は遅延 (lazy)

## 環境設定

```bash
# .env (カレントディレクトリ) または ~/.labvault/config.toml で設定
LABVAULT_TEAM=konishi-lab
LABVAULT_USER=your-name
LABVAULT_GCP_PROJECT=klab-proto
LABVAULT_NEXTCLOUD_URL=https://arim.mdx.jp/nextcloud
LABVAULT_NEXTCLOUD_USER=arim00065
LABVAULT_NEXTCLOUD_PASSWORD=...
LABVAULT_NEXTCLOUD_GROUP_FOLDER=large/24UTARIM004
```

## MCP サーバー

Claude Code に設定済み。7ツール:
- `search` — レコード検索（テキスト + フィルタ + 条件範囲指定）。`include_conditions=True` で条件も返す
- `get_detail` — レコード詳細（条件、結果、メモ、ファイル）
- `compare` — レコード横断比較（最大10件）
- `data_preview` — ファイルプレビュー（CSV, JSON, テキスト）
- `aggregate` — 数値キーの統計集計（conditions/results 両対応、parent_id フィルタ、group_by）
- `get_overview` — 実験シリーズの概要（子レコード数、条件ユニーク値/統計、結果統計を1回で取得）
- `get_timeline` — 時系列イベント一覧

### 条件フィルタの書式

```python
# 完全一致
search(conditions={"power": 20})

# 範囲指定 (gt, gte, lt, lte, eq, ne)
search(conditions={"power": {"gte": 50}})
search(conditions={"power": {"gte": 20, "lte": 40}})
```

## CLI コマンド

16コマンド: init, new, add, list, show, search, aggregate, overview, delete, restore, note, tag, status, export, doctor, mcp

### 分析系コマンド（MCP と同等の機能を CLI で提供）

```bash
# 条件フィルタ付き検索 + 条件表示
labvault search -p PARENT_ID -c "power>=50" -c "angle<=60" -C

# 数値キーの統計集計（conditions/results 両対応）
labvault aggregate power -p PARENT_ID
labvault aggregate pulse_energy --group-by angle -p PARENT_ID

# 実験シリーズの概要
labvault overview PARENT_ID
```

CLI はプレーンテキスト出力のため、LLM が Bash 経由で使う場合は MCP より低トークン消費。

## platform (Web UI + サービス)

- ディレクトリ: `platform/`
- 技術スタック: Next.js (frontend) + FastAPI (backend) on Cloud Run
- デプロイ先: Cloud Run (asia-northeast1, 無料枠内 $0/月)
- 機能: レコード閲覧・詳細、条件カラム表示、散布図、条件フィルタ、一括アップロード(NxMグリッド)、タグ/メモ/単位編集

## インストール済みスキル

- **python-testing-patterns** — pytestのパターン・ベストプラクティス
- **python-performance-optimization** — Pythonパフォーマンス最適化
- **python-sdk** — Python SDK開発ガイドライン
