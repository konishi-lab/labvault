# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**labvault** — Python/Notebookで実験する研究室のための実験データ基盤。測定から解析までのコード・データ・条件が自動で記録され、蓄積されたデータをLLMが横断検索・解析する。

- 実験者向けPython SDK + CLI + MCP サーバー（このリポジトリ）
- バックエンド: Firestore（メタデータ）+ Nextcloud（ARIM MDX, 30TBバイナリ）+ Vertex AI（Embedding）
- LLM連携: ローカル MCP サーバー（`labvault mcp`）でClaude Desktop/Codeがデータを検索・解析
- Web UI + Cloud Functions: `platform/` ディレクトリ（Next.js + FastAPI on Cloud Run）
- 月額GCPコスト: $1以下（Cloud Functions + Firestore + Vertex AI + Cloud Run 無料枠）

## 開発コマンド

```bash
# インストール
pip install -e ".[dev]"

# テスト（292テスト、カバレッジ89%）
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
├── core/          # Lab, Record, types, config, id生成, exceptions
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
├── mcp/           # MCP サーバー (6ツール: search, get_detail, compare等)
├── parsers/       # ファイルパーサープラグイン（.ras, .dm3等。M3で実装予定）
└── cli/           # Click CLI (init, new, add, list, show, search, doctor, mcp)

platform/          # デプロイ可能なサービス群
├── frontend/      # Next.js (Web UI。M6で実装予定)
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
| **M4** CLI (7コマンド) | 完了 |
| **M4** Embedding (Vertex AI) | 完了 (動作確認済) |
| **M4** MCP サーバー (6ツール) | 完了 (Claude Code 動作確認済) |
| **M3** テンプレート + パーサー | 未着手 |
| **M5** 拡張 (ProcessChain等) | 未着手 |
| **M6** WebApp (Next.js + FastAPI) | 未着手 (platform/ にディレクトリ準備済) |

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

Claude Code に設定済み。6ツール:
- `search` — レコード検索（テキスト + フィルタ）
- `get_detail` — レコード詳細（条件、結果、メモ、ファイル）
- `compare` — レコード横断比較
- `data_preview` — ファイルプレビュー（CSV, JSON, テキスト）
- `aggregate` — 数値結果の統計集計
- `get_timeline` — 時系列イベント一覧

## platform (Web UI + サービス)

- ディレクトリ: `platform/`
- 技術スタック: Next.js (frontend) + FastAPI (backend) on Cloud Run
- デプロイ先: Cloud Run (asia-northeast1, 無料枠内 $0/月)
- 状態: ディレクトリ準備済み、実装は M6

## インストール済みスキル

- **python-testing-patterns** — pytestのパターン・ベストプラクティス
- **python-performance-optimization** — Pythonパフォーマンス最適化
- **python-sdk** — Python SDK開発ガイドライン
