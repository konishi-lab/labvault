# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**labvault** — Python/Notebookで実験する研究室のための実験データ基盤。測定から解析までのコード・データ・条件が自動で記録され、蓄積されたデータをLLMが横断検索・解析する。

- 実験者向けPython SDK（このリポジトリ）
- バックエンド: Firestore（メタデータ）+ Nextcloud（大学提供、30TBバイナリ）+ Vertex AI（Embedding）
- LLM連携: MCPサーバー（Cloud Functions Gen2）経由でClaude/Geminiがデータを検索・解析
- 月額GCPコスト: $1以下（Cloud Functions + Firestore + Vertex AI）

## 開発コマンド

```bash
# インストール
pip install -e ".[dev]"

# テスト
pytest

# 単一テスト
pytest tests/unit/test_record.py

# リント・フォーマット
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

## アーキテクチャ

```
src/labvault/
├── core/          # Lab, Record, types, config, id生成, exceptions
├── backends/      # Backend Protocol (全sync), InMemory, Firestore, Nextcloud
├── tracking/      # IPython hooks自動ログ, @exp.track, snapshot, namespace diff
├── buffer/        # ローカルバッファ（SQLite WAL。データ消失防止）
├── parsers/       # ファイルパーサープラグイン（.ras, .dm3等のメタデータ自動抽出）
└── cli/           # Click CLI（labvault init/new/add/search等）
```

## 設計資料

- `docs/design/v10/` — **現行の設計仕様**（v10）
  - `00_v10_overview.md` — 概要・アーキテクチャ・コスト
  - `02_sdk_and_mcp.md` — SDK変更・MCPツール・pyproject.toml
  - `03_experiment_workflow.md` — テンプレート・パーサー・装置投入
  - `04_sdk_cookbook.md` — SDK使い方ガイド（全APIのコード例）
  - `05_milestones.md` — 実装マイルストーン
  - `v10-conceptual-review-revised.md` — コンセプトレビュー（最終版）
- `docs/design/v9/` — v9実装仕様（レビュー済み。v10の元）
- `docs/design/REQUIREMENTS.md` — 要件定義（R01-R22）

## 重要な規約

- **パッケージ名**: `labvault`（import: `from labvault import Lab`）
- **ID**: Crockford's Base32（4文字、大文字のみ。例: "AB3F"）
- **Backend Protocol**: **全sync**。Notebook event loop競合回避のため async は使わない
- **ローカルバッファ必須**: `exp.add()` は必ずローカルに先に保存してからリモートに送る
- **IPython hooks**: Notebook環境では `lab.new()` で全セル自動記録開始
- **既存Recordへの追記**: `lab.get(id, auto_log=True)` でhooks再起動（新APIは追加しない）
- **装置制御スクリプト(.py)**: `exp.log_value()` / `exp.log_event()` を使う
- **セル再実行の冪等性**: note()重複防止、add()ファイル重複防止、セルログexecution_count上書き
- **テスト**: InMemoryBackendで全テストがオフラインで動くこと
- **例外名**: `LabvaultPermissionError`（ビルトインPermissionErrorとの衝突回避）
- **依存軽量化**: `google-cloud-aiplatform` は使わない。Embedding は REST API 直接呼び出し

## インストール済みスキル

- **python-testing-patterns** — pytestのパターン・ベストプラクティス
- **python-performance-optimization** — Pythonパフォーマンス最適化
- **python-sdk** — Python SDK開発ガイドライン

## 関連リポジトリ

### labvault-platform（プラットフォーム）
- パス: /Users/hirosuke/ghq/github.com/konishi-lab/labvault-platform（未作成）
- 内容: MCPサーバー（Cloud Functions Gen2, 8ツール）+ Cloud Functions（embedding, poller）+ GCPインフラ
- 共有スキーマ: Firestoreのドキュメント構造はこのリポのtypes.pyが正（SSOT）
