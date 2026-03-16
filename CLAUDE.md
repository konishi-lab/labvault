# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

**labvault** — 実験データ管理SDK。Notebookで普通にコードを書くだけで、全実行履歴がLLMに理解可能な形で自動保存される。

- 実験者向けPython SDK（このリポジトリ）
- バックエンド: Firestore（メタデータ）+ Nextcloud（30TBバイナリ）+ Vertex AI（Embedding）
- LLM連携: MCPサーバー経由でClaude/Geminiがデータを検索・解析

## 開発コマンド

```bash
# インストール
pip install -e ".[dev]"

# テスト
pytest

# 単一テスト
pytest tests/test_record.py

# リント・フォーマット
ruff check src/ tests/
ruff format src/ tests/
mypy src/
```

## アーキテクチャ

```
src/labvault/
├── core/          # Lab, Record, types, config, id生成
├── backends/      # Backend Protocol, InMemory, Firestore, Nextcloud
├── tracking/      # IPython hooks自動ログ, @exp.track, snapshot
├── buffer/        # ローカルバッファ（SQLite。データ消失防止）
└── cli/           # Click CLI（labvault init/new/add/search等）
```

## 関連リポジトリ

### labvault-platform（プラットフォーム）
- パス: /Users/hirosuke/ghq/github.com/konishi-lab/labvault-platform（未作成）
- 内容: MCPサーバー + WebApp(Streamlit) + Cloud Functions + GCPインフラ
- 共有スキーマ: Firestoreのドキュメント構造はこのリポのmodels.pyが正（SSOT）

## 設計資料

- `docs/design/REQUIREMENTS.md` — 確定要件
- `docs/design/v8/` — 実装仕様（最終版）
- `docs/design/v7/` — SDK詳細設計（実装コード付き）

## 重要な規約

- **パッケージ名**: `labvault`（import: `from labvault import Lab`）
- **ID**: Crockford's Base32（4文字、大文字のみ。例: "AB3F"）
- **ローカルバッファ必須**: `exp.add()` は必ずローカルに先に保存してからリモートに送る
- **IPython hooks**: Notebook環境では `lab.new()` だけで全セル自動記録
- **テスト**: InMemoryBackendで全テストがオフラインで動くこと
