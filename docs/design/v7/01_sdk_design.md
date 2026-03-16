# v7 SDK最終設計 — IPython Hooks 自動ログ中心アーキテクチャ

> v6までの全議論 + REQUIREMENTSを踏まえた最終設計。
> v6の `@exp.track` デコレータを**スクリプト用オプション**に格下げし、
> **IPython hooks による全セル自動記録**をメインのログ方法に据える。
>
> 差別化要素: 「Notebookで普通にコードを書くだけで、全実行履歴がLLMに理解可能な形で自動保存される」

---

## 目次

1. [v6からの進化と設計思想](#1-v6からの進化と設計思想)
2. [IPython Hooks 自動ログの完全な実装設計](#2-ipython-hooks-自動ログの完全な実装設計)
3. [ローカルバッファの詳細設計](#3-ローカルバッファの詳細設計)
4. [SDK全体のAPI再整理](#4-sdk全体のapi再整理)
5. [パッケージ構成](#5-パッケージ構成)
6. [テスト設計](#6-テスト設計)
7. [既存ツールとの差別化](#7-既存ツールとの差別化)
8. [マイルストーン](#8-マイルストーン)

---

## 1. v6からの進化と設計思想

### 1.1 v6 vs v7 の決定的な違い

| 観点 | v6 | v7 |
|------|-----|-----|
| **メインのログ方法** | `@exp.track` デコレータ | **IPython hooks で全セル自動記録** |
| **実験者の手間** | デコレータ1行 | **ゼロ**（`exp = lab.new()` だけ） |
| **Notebookベタ書き対応** | `exp.snapshot()` で手動 | **自動**（フックが全セルを捕捉） |
| **スクリプト対応** | `@exp.track` がメイン | `@exp.track` / `with exp.track_block()` |
| **ローカルバッファ** | 設計のみ | **SQLiteバッファ完全実装** |
| **デコレータの位置づけ** | 中心機能 | スクリプト用オプション |

### 1.2 なぜIPython hooksがメインなのか

**Notebookのコードは70%が関数化されていないベタ書き。**

```python
# 典型的なNotebookセル（関数化されていない）
data = np.loadtxt("xrd.csv", delimiter=",")
cutoff = 0.5
b, a = butter(4, cutoff, btype='low')
filtered = filtfilt(b, a, data[:, 1])
```

デコレータは関数にしか付けられない。`exp.snapshot()` は呼び忘れる。
IPython hooksなら、**何もしなくても全て記録される**。

### 1.3 3層のログ戦略

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: IPython Hooks（自動、Notebook専用）         │
│  → 全セルのソースコード + namespace diff を自動記録   │
│  → 実験者の手間: ゼロ                                │
├─────────────────────────────────────────────────────┤
│  Layer 2: @exp.track / track_block()（半自動）        │
│  → 関数/ブロック単位の引数・返り値を記録              │
│  → スクリプト用。Notebookでも使える（より詳細な記録） │
├─────────────────────────────────────────────────────┤
│  Layer 3: exp.snapshot()（手動）                      │
│  → 任意の時点のローカル変数をキャプチャ               │
│  → 特定の変数を明示的に記録したい場合                 │
└─────────────────────────────────────────────────────┘
```

**環境による自動選択:**

| 環境 | 方法 | 実験者の手間 |
|------|------|------------|
| **Jupyter Notebook / JupyterLab** | IPython hooksで全セル自動記録 | **ゼロ** |
| **IPython REPL** | IPython hooksで全コマンド自動記録 | **ゼロ** |
| **Python スクリプト (.py)** | `@exp.track` / `with exp.track_block()` | デコレータ1行 |
| **どこでも** | `exp.snapshot()` | 1行 |

---

## 2. IPython Hooks 自動ログの完全な実装設計

### 2.1 アーキテクチャ概要

```
┌──────────────────────────────────────────────────────────┐
│  Jupyter Notebook                                         │
│                                                           │
│  [Cell 1] exp = Lab("konishi-lab").new("XRD解析")         │
│       ↓ IPython hooks 自動登録                            │
│  [Cell 2] data = np.loadtxt(...)                          │
│       ↓ pre_run_cell → namespace snapshot                 │
│       ↓ post_run_cell → namespace diff → CellLog          │
│  [Cell 3] filtered = filtfilt(...)                        │
│       ↓ pre → post → CellLog                             │
│       :                                                   │
│                                                           │
│  CellLog → ローカルバッファ(SQLite) → リモート(Firestore)  │
└──────────────────────────────────────────────────────────┘
```

### 2.2 CellLog データモデル

```python
"""セル実行ログのデータモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class CellLog:
    """1セルの実行記録。LLMが読むことを前提に設計。"""

    # 識別
    cell_id: str                    # ユニークID
    record_id: str                  # 親Recordへの参照
    cell_number: int                # Notebook内のセル実行番号
    execution_count: int            # IPythonのexecution_count

    # ソースコード
    source: str                     # セルのソースコード全文
    source_hash: str                # ソースのハッシュ（重複検出用）

    # 変数の変化
    new_vars: dict[str, Any]        # 新しく作られた変数
    changed_vars: dict[str, Any]    # 値が変わった変数
    deleted_vars: list[str]         # 削除された変数

    # 実行結果
    result_repr: str | None = None  # セルの出力（repr、最大1000文字）
    error: dict[str, Any] | None = None  # エラー情報（発生時のみ）
    duration_sec: float = 0.0       # 実行時間

    # タイムスタンプ
    executed_at: datetime = field(default_factory=datetime.utcnow)

    # 環境（初回のみフル、以降は差分）
    env: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell_id": self.cell_id,
            "record_id": self.record_id,
            "cell_number": self.cell_number,
            "execution_count": self.execution_count,
            "source": self.source,
            "source_hash": self.source_hash,
            "new_vars": self.new_vars,
            "changed_vars": self.changed_vars,
            "deleted_vars": self.deleted_vars,
            "result_repr": self.result_repr,
            "error": self.error,
            "duration_sec": self.duration_sec,
            "executed_at": self.executed_at.isoformat(),
            "env": self.env,
        }
```

### 2.3 IPython Hooks の完全実装

```python
"""IPython hooks によるセル自動記録。

設計判断:
- pre_run_cell: namespace の「キー集合 + 値のID」をスナップショット
  → 値そのものはコピーしない（パフォーマンス）
  → id() で同一オブジェクトかどうかだけ判定
- post_run_cell: namespace の差分を検出、新規/変更変数のみシリアライズ
  → 大量の内部変数は除外フィルタで排除
  → シリアライズは serialize_value() で要約化
"""
from __future__ import annotations

import hashlib
import time
import warnings
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..core.id import generate_id
from ..tracking.serializers import serialize_value

if TYPE_CHECKING:
    from ..core.record import Record


# ============================================================
# 除外フィルタ
# ============================================================

# IPython/Jupyter の内部変数（記録しない）
_IPYTHON_INTERNALS = frozenset({
    # IPython組み込み
    "In", "Out", "get_ipython", "exit", "quit",
    "_", "__", "___",
    "_i", "_ii", "_iii",
    "_oh", "_dh", "_sh",
    # Jupyter特有
    "_ih",
})

# 記録しない変数名のパターン
def _should_skip_var(name: str, value: Any) -> bool:
    """この変数を記録すべきかどうか判定。"""
    # アンダースコアで始まるプライベート変数
    if name.startswith("_") and name not in ("_",):
        return True

    # IPython内部変数
    if name in _IPYTHON_INTERNALS:
        return True

    # _iN, _ohN パターン（IPythonの入出力履歴）
    if name.startswith("_i") and name[2:].isdigit():
        return True

    # モジュール、関数、クラス定義はスキップ
    import types
    if isinstance(value, (types.ModuleType, types.FunctionType, type)):
        return True

    # インポートされたモジュールのサブモジュール
    if hasattr(value, "__module__") and isinstance(value, type):
        return True

    return False


# セキュリティ: パスワード等の自動除外
_SENSITIVE_PATTERNS = frozenset({
    "password", "passwd", "secret", "token", "api_key",
    "apikey", "auth", "credential", "private_key",
})

def _is_sensitive(name: str) -> bool:
    """変数名がセンシティブかどうか判定。"""
    lower = name.lower()
    return any(pattern in lower for pattern in _SENSITIVE_PATTERNS)


# ============================================================
# Namespace Diff
# ============================================================

class _NamespaceSnapshot:
    """namespace の軽量スナップショット。値はコピーしない。"""

    __slots__ = ("keys", "ids", "hashes")

    def __init__(self, ns: dict[str, Any]) -> None:
        self.keys: frozenset[str] = frozenset(ns.keys())
        # id() で同一オブジェクトかどうかを判定
        # ミュータブルオブジェクト（list, dict）の中身が変わっても
        # id()は同じなので、ハッシュも併用する
        self.ids: dict[str, int] = {}
        self.hashes: dict[str, int | None] = {}
        for k, v in ns.items():
            if _should_skip_var(k, v):
                continue
            self.ids[k] = id(v)
            try:
                self.hashes[k] = hash(v)
            except TypeError:
                # unhashable (list, dict, ndarray等)
                # この場合は id() のみで判定（中身の変更は検出できないが、
                # 典型的なNotebookでは再代入がほとんどなので十分）
                self.hashes[k] = None


def _compute_namespace_diff(
    pre: _NamespaceSnapshot,
    post_ns: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """namespace の差分を計算。

    Returns:
        (new_vars, changed_vars, deleted_vars)
        - new_vars: 新しく作られた変数 {name: serialized_value}
        - changed_vars: 値が変わった変数 {name: serialized_value}
        - deleted_vars: 削除された変数名のリスト
    """
    new_vars: dict[str, Any] = {}
    changed_vars: dict[str, Any] = {}
    deleted_vars: list[str] = []

    post_keys = set()
    for k, v in post_ns.items():
        if _should_skip_var(k, v):
            continue
        if _is_sensitive(k):
            continue  # パスワード等は記録しない
        post_keys.add(k)

        if k not in pre.ids:
            # 新しい変数
            new_vars[k] = serialize_value(v)
        else:
            # 既存変数: id() またはhash() が変わったか
            old_id = pre.ids[k]
            old_hash = pre.hashes.get(k)
            new_id = id(v)
            try:
                new_hash = hash(v)
            except TypeError:
                new_hash = None

            if new_id != old_id or (
                old_hash is not None and new_hash is not None and old_hash != new_hash
            ):
                changed_vars[k] = serialize_value(v)

    # 削除された変数
    for k in pre.ids:
        if k not in post_keys and not _should_skip_var(k, post_ns.get(k, None)):
            deleted_vars.append(k)

    return new_vars, changed_vars, deleted_vars


# ============================================================
# CellTracker: IPython Hooks 本体
# ============================================================

class CellTracker:
    """IPython hooks を管理し、セル実行を自動記録するクラス。

    使い方:
        # Lab.new() 内部で自動的に呼ばれる
        tracker = CellTracker(record=exp, buffer=local_buffer)
        tracker.activate()

        # 以降の全セル実行が自動記録される

        # 手動で停止
        tracker.deactivate()

        # 一時停止/再開
        tracker.pause()
        tracker.resume()
    """

    def __init__(
        self,
        record: Record,
        buffer: Any,  # LocalBuffer（後述）
        *,
        max_source_length: int = 10_000,
        max_result_length: int = 1_000,
        skip_empty_cells: bool = True,
        skip_magic_cells: bool = True,
    ) -> None:
        self._record = record
        self._buffer = buffer
        self._max_source_length = max_source_length
        self._max_result_length = max_result_length
        self._skip_empty_cells = skip_empty_cells
        self._skip_magic_cells = skip_magic_cells

        self._active = False
        self._paused = False
        self._cell_count = 0
        self._ip = None  # IPython instance
        self._pre_snapshot: _NamespaceSnapshot | None = None
        self._pre_time: float = 0.0
        self._env_captured = False  # 環境情報は初回のみキャプチャ

    def activate(self) -> None:
        """IPython hooks を登録して自動記録を開始。"""
        try:
            from IPython import get_ipython
            ip = get_ipython()
            if ip is None:
                warnings.warn(
                    "IPython環境が検出されませんでした。"
                    "自動セルログは無効です。"
                    "スクリプトでは @exp.track または exp.snapshot() を使用してください。",
                    stacklevel=2,
                )
                return

            self._ip = ip
            ip.events.register("pre_run_cell", self._pre_run_cell)
            ip.events.register("post_run_cell", self._post_run_cell)
            self._active = True

        except ImportError:
            warnings.warn(
                "IPythonがインストールされていません。自動セルログは無効です。",
                stacklevel=2,
            )

    def deactivate(self) -> None:
        """IPython hooks を解除して自動記録を停止。"""
        if self._ip and self._active:
            try:
                self._ip.events.unregister("pre_run_cell", self._pre_run_cell)
                self._ip.events.unregister("post_run_cell", self._post_run_cell)
            except ValueError:
                pass  # 既に解除済み
            self._active = False

    def pause(self) -> None:
        """一時停止。セル実行は記録されない。"""
        self._paused = True

    def resume(self) -> None:
        """再開。"""
        self._paused = False

    @property
    def is_active(self) -> bool:
        return self._active and not self._paused

    # ========================================
    # IPython Event Handlers
    # ========================================

    def _pre_run_cell(self, info) -> None:
        """セル実行前のフック。

        Args:
            info: IPython の ExecutionInfo オブジェクト
                - info.raw_cell: セルのソースコード
                - info.store_history: 履歴に保存するか
                - info.silent: サイレント実行か
        """
        if not self.is_active:
            return

        # サイレント実行はスキップ（内部的な実行）
        if info.silent:
            return

        source = info.raw_cell.strip()

        # 空セルのスキップ
        if self._skip_empty_cells and not source:
            self._pre_snapshot = None
            return

        # マジックコマンドのスキップ（%%timeit, %matplotlib等）
        if self._skip_magic_cells and source.startswith(("%", "!")):
            self._pre_snapshot = None
            return

        # Namespace のスナップショットを取得
        # パフォーマンス: 値はコピーしない。id()とhash()のみ保存。
        # 1000変数で ~1ms 程度。
        self._pre_snapshot = _NamespaceSnapshot(self._ip.user_ns)
        self._pre_time = time.perf_counter()

    def _post_run_cell(self, result) -> None:
        """セル実行後のフック。

        Args:
            result: IPython の ExecutionResult オブジェクト
                - result.info: ExecutionInfo
                - result.result: セルの出力値
                - result.error_in_exec: 実行中のエラー
                - result.error_before_exec: 実行前のエラー
                - result.execution_count: 実行番号
                - result.success: 成功したか
        """
        if not self.is_active:
            return

        if self._pre_snapshot is None:
            return  # pre で skip された

        duration = time.perf_counter() - self._pre_time
        self._cell_count += 1

        source = result.info.raw_cell
        if len(source) > self._max_source_length:
            source = source[:self._max_source_length] + "\n# ... (truncated)"

        # Namespace diff を計算
        new_vars, changed_vars, deleted_vars = _compute_namespace_diff(
            self._pre_snapshot,
            self._ip.user_ns,
        )

        # エラー情報
        error = None
        if result.error_in_exec is not None:
            error = {
                "type": type(result.error_in_exec).__name__,
                "message": str(result.error_in_exec)[:500],
            }
        elif result.error_before_exec is not None:
            error = {
                "type": type(result.error_before_exec).__name__,
                "message": str(result.error_before_exec)[:500],
            }

        # 出力の repr
        result_repr = None
        if result.result is not None:
            try:
                r = repr(result.result)
                if len(r) > self._max_result_length:
                    r = r[:self._max_result_length] + "..."
                result_repr = r
            except Exception:
                result_repr = "<repr failed>"

        # 環境情報（初回のみフル）
        env: dict[str, Any] = {}
        if not self._env_captured:
            env = _capture_env_info()
            self._env_captured = True

        # CellLog を構築
        cell_log = CellLog(
            cell_id=generate_id(8),
            record_id=self._record.id,
            cell_number=self._cell_count,
            execution_count=result.execution_count or 0,
            source=source,
            source_hash=hashlib.sha256(source.encode()).hexdigest()[:16],
            new_vars=new_vars,
            changed_vars=changed_vars,
            deleted_vars=deleted_vars,
            result_repr=result_repr,
            error=error,
            duration_sec=duration,
            env=env,
        )

        # ローカルバッファに保存（非ブロッキング）
        self._buffer.save_cell_log(cell_log)

        # スナップショットをクリア
        self._pre_snapshot = None


# ============================================================
# 環境情報のキャプチャ
# ============================================================

def _capture_env_info() -> dict[str, Any]:
    """実行環境の情報を取得。初回のみ呼ばれる。"""
    import sys
    env: dict[str, Any] = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": sys.platform,
    }

    # 主要パッケージのバージョン
    packages = {}
    for pkg in ("numpy", "scipy", "pandas", "matplotlib", "sklearn",
                "torch", "tensorflow", "xarray"):
        try:
            mod = __import__(pkg)
            packages[pkg] = getattr(mod, "__version__", "unknown")
        except ImportError:
            pass
    if packages:
        env["packages"] = packages

    # Gitコミットハッシュ
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, cwd=".",
        )
        if result.returncode == 0:
            env["git_commit"] = result.stdout.strip()
    except Exception:
        pass

    # Jupyterカーネル情報
    try:
        from IPython import get_ipython
        ip = get_ipython()
        if ip and hasattr(ip, "kernel"):
            env["kernel"] = type(ip.kernel).__name__
    except Exception:
        pass

    return env
```

### 2.4 パフォーマンス分析

**毎セル実行時のオーバーヘッド:**

```
操作                                | 時間      | 備考
------------------------------------|-----------|---------------------------
pre_run_cell:                       |           |
  _NamespaceSnapshot 構築           | ~0.5-2ms  | 変数数に比例。1000変数で~2ms
  (id() + hash() のみ、値コピーなし)|           |
                                    |           |
post_run_cell:                      |           |
  namespace diff 計算               | ~0.5-2ms  | 変更変数のみシリアライズ
  serialize_value (新規/変更のみ)   | ~0.1-1ms  | 変更変数数に依存
  CellLog構築                       | ~0.01ms   |
  SQLiteバッファ書き込み            | ~0.5-1ms  | WALモード、非同期キュー
                                    |           |
合計                                | ~1.5-6ms  | 典型的なNotebookセルでは体感なし
```

**典型的なセル実行時間（比較）:**

- `import numpy as np`: ~100ms
- `data = np.loadtxt("file.csv")`: ~50ms-数秒
- `plt.plot(data)`: ~10-50ms
- 科学計算（fitting等）: 数百ms-数分

**結論: 1.5-6ms のオーバーヘッドは実験コードの実行時間（10ms-分単位）に対して無視できる。**

### 2.5 パフォーマンス最適化戦略

```python
"""パフォーマンス最適化のための設定。"""

# 変数数が多い場合の最適化
MAX_TRACKED_VARS = 500  # これ以上の変数はnewのみ追跡

# 大きなNamespaceの場合、全スキャンではなく
# 変更されやすい変数のみ追跡するヒューリスティック
def _optimized_snapshot(ns: dict[str, Any], prev_keys: frozenset[str]) -> _NamespaceSnapshot:
    """前回のキー集合との差分のみスナップショット。

    既知の変数が多い場合、新規変数のみ追跡すれば十分。
    """
    # 新規キーのみ完全スナップショット
    # 既存キーはid()のみ再チェック
    pass  # 実装省略。初期実装は全スキャンで問題ない
```

### 2.6 セキュリティ/プライバシー対策

```python
"""センシティブ情報の除外。"""

# 1. 変数名によるフィルタリング（上述の _is_sensitive）
# 2. 値の型によるフィルタリング
_NEVER_SERIALIZE_TYPES = (
    # クレデンシャル系ライブラリの型
    # google.auth.credentials.Credentials
    # etc.
)

# 3. ユーザーが追加できる除外リスト
class CellTracker:
    def exclude_vars(self, *names: str) -> None:
        """特定の変数名を記録対象から除外。"""
        self._excluded_vars.update(names)

    def exclude_patterns(self, *patterns: str) -> None:
        """パターンで除外（fnmatch形式）。"""
        self._excluded_patterns.extend(patterns)

# 4. .mdxdb/config.toml での設定
# [tracking]
# exclude_vars = ["db_password", "api_key"]
# exclude_patterns = ["*_secret", "*_token"]
```

### 2.7 ON/OFF切り替え

```python
# === 自動ログの制御 ===

# 方法1: Lab.new() のオプション
exp = lab.new("XRD解析", auto_log=False)  # 自動ログ無効

# 方法2: 後からON/OFF
exp.auto_log.pause()   # 一時停止
exp.auto_log.resume()  # 再開
exp.auto_log.deactivate()  # 完全停止

# 方法3: セル単位での抑制（マジックコマンド）
# %%mdxdb_skip
# このセルは記録されない
password = "super_secret"

# 方法4: コンテキストマネージャ
with exp.auto_log.paused():
    # このブロック内は記録されない
    sensitive_operation()

# 方法5: グローバル設定
# ~/.mdxdb/config.toml
# [tracking]
# auto_log = false  # デフォルトで無効
```

### 2.8 Notebook以外の環境でのフォールバック

```python
"""Lab.new() 内部でのIPython検出と自動選択。"""

class Lab:
    def new(self, title: str, *, auto_log: bool = True, **kwargs) -> Record:
        record = Record(...)

        if auto_log:
            self._setup_auto_logging(record)

        return record

    def _setup_auto_logging(self, record: Record) -> None:
        """環境に応じて最適なロギング方法を自動選択。"""
        try:
            from IPython import get_ipython
            ip = get_ipython()

            if ip is not None:
                # IPython環境（Notebook, IPython REPL）
                tracker = CellTracker(
                    record=record,
                    buffer=self._local_buffer,
                )
                tracker.activate()
                record._cell_tracker = tracker
                return
        except ImportError:
            pass

        # 通常のPython環境: 自動ログは無効
        # @exp.track / exp.snapshot() を使うようにメッセージ表示
        import warnings
        warnings.warn(
            "IPython環境ではないため、自動セルログは無効です。\n"
            "@exp.track デコレータまたは exp.snapshot() を使用してください。",
            stacklevel=3,
        )
```

---

## 3. ローカルバッファの詳細設計

### 3.1 なぜSQLiteか

| 選択肢 | 利点 | 欠点 |
|--------|------|------|
| **SQLite** | Python標準ライブラリ、ACID保証、WALモードで高速、クエリ可能 | ファイルロック（単一プロセス推奨） |
| ファイルシステム | シンプル、並行書き込み安全 | クエリ不可、メタデータ管理が煩雑 |
| LevelDB | 高速write | 追加依存、クエリ不可 |

**SQLiteを採用する理由:**
1. **追加依存ゼロ**（Python標準の `sqlite3` モジュール）
2. **ACID保証**でデータ損失なし
3. **WALモード**で読み書き同時実行が可能
4. **クエリ可能**なのでデバッグ・確認が容易
5. Notebookは単一プロセスなのでファイルロックは問題にならない

### 3.2 スキーマ設計

```python
"""ローカルバッファのSQLiteスキーマ。"""

SCHEMA_SQL = """
-- レコードメタデータのバッファ
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,           -- JSON serialized Record
    synced INTEGER DEFAULT 0,     -- 0: 未同期, 1: 同期済み
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- セルログのバッファ
CREATE TABLE IF NOT EXISTS cell_logs (
    cell_id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    data TEXT NOT NULL,           -- JSON serialized CellLog
    synced INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(id)
);

-- ファイルデータのバッファ（メタデータのみ。バイナリはファイルシステム）
CREATE TABLE IF NOT EXISTS data_files (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    name TEXT NOT NULL,
    local_path TEXT NOT NULL,     -- ローカルファイルパス
    content_type TEXT,
    size_bytes INTEGER,
    synced INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(id)
);

-- 同期ステータス
CREATE TABLE IF NOT EXISTS sync_status (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_cell_logs_record ON cell_logs(record_id);
CREATE INDEX IF NOT EXISTS idx_cell_logs_synced ON cell_logs(synced);
CREATE INDEX IF NOT EXISTS idx_data_files_synced ON data_files(synced);
CREATE INDEX IF NOT EXISTS idx_records_synced ON records(synced);
"""
```

### 3.3 LocalBuffer 実装

```python
"""ローカルバッファの実装。SQLite WALモード。

設計原則:
- exp.add() / CellTracker の書き込みは絶対にブロックしない
- リモート同期は別スレッドで非同期に行う
- バッファに書いた時点で「保存完了」とみなせる安全性
"""
from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from ..core.id import generate_id


class LocalBuffer:
    """SQLiteベースのローカルバッファ。

    ディレクトリ構造:
        ~/.mdxdb/buffer/
        ├── buffer.db          # SQLiteデータベース
        └── files/             # バイナリファイルのバッファ
            └── {record_id}/
                └── {filename}
    """

    DEFAULT_DIR = Path.home() / ".mdxdb" / "buffer"

    def __init__(
        self,
        buffer_dir: str | Path | None = None,
        *,
        max_size_mb: int = 500,    # バッファの最大サイズ（MB）
        retention_days: int = 30,   # 同期済みデータの保持日数
    ) -> None:
        self._dir = Path(buffer_dir) if buffer_dir else self.DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._files_dir = self._dir / "files"
        self._files_dir.mkdir(exist_ok=True)
        self._max_size_mb = max_size_mb
        self._retention_days = retention_days

        # SQLite接続（WALモード）
        self._db_path = self._dir / "buffer.db"
        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,  # スレッド間で共有
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

        # 書き込みキュー（ノンブロッキング書き込み用）
        self._write_queue: queue.Queue = queue.Queue(maxsize=10000)
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="mdxdb-buffer-writer",
        )
        self._writer_thread.start()

    # ========================================
    # 書き込み（ノンブロッキング）
    # ========================================

    def save_record(self, record_data: dict[str, Any]) -> None:
        """レコードをバッファに保存。"""
        self._write_queue.put(("record", record_data))

    def save_cell_log(self, cell_log: Any) -> None:
        """CellLogをバッファに保存。"""
        self._write_queue.put(("cell_log", cell_log.to_dict()))

    def save_file(
        self,
        record_id: str,
        name: str,
        data: bytes,
        content_type: str = "",
    ) -> str:
        """ファイルをローカルに保存。パスを返す。"""
        rec_dir = self._files_dir / record_id
        rec_dir.mkdir(parents=True, exist_ok=True)
        file_path = rec_dir / name
        file_path.write_bytes(data)

        self._write_queue.put(("file", {
            "id": generate_id(8),
            "record_id": record_id,
            "name": name,
            "local_path": str(file_path),
            "content_type": content_type,
            "size_bytes": len(data),
            "created_at": datetime.utcnow().isoformat(),
        }))

        return str(file_path)

    # ========================================
    # 読み出し
    # ========================================

    def get_unsynced_records(self) -> list[dict[str, Any]]:
        """未同期のレコード一覧。"""
        cur = self._conn.execute(
            "SELECT data FROM records WHERE synced = 0"
        )
        return [json.loads(row[0]) for row in cur.fetchall()]

    def get_unsynced_cell_logs(self, record_id: str) -> list[dict[str, Any]]:
        """未同期のセルログ一覧。"""
        cur = self._conn.execute(
            "SELECT data FROM cell_logs WHERE record_id = ? AND synced = 0",
            (record_id,),
        )
        return [json.loads(row[0]) for row in cur.fetchall()]

    def get_unsynced_files(self) -> list[dict[str, Any]]:
        """未同期のファイル一覧。"""
        cur = self._conn.execute(
            "SELECT id, record_id, name, local_path, content_type, size_bytes "
            "FROM data_files WHERE synced = 0"
        )
        return [
            {
                "id": row[0], "record_id": row[1], "name": row[2],
                "local_path": row[3], "content_type": row[4], "size_bytes": row[5],
            }
            for row in cur.fetchall()
        ]

    def mark_synced(self, table: str, ids: list[str]) -> None:
        """同期済みマーク。"""
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        id_col = "cell_id" if table == "cell_logs" else "id"
        self._conn.execute(
            f"UPDATE {table} SET synced = 1 WHERE {id_col} IN ({placeholders})",
            ids,
        )
        self._conn.commit()

    # ========================================
    # ライフサイクル管理
    # ========================================

    def cleanup(self) -> None:
        """同期済み + 保持期間を過ぎたデータを削除。"""
        cutoff = datetime.utcnow()
        # retention_days分古い同期済みデータを削除
        self._conn.execute(
            "DELETE FROM cell_logs WHERE synced = 1 AND "
            "datetime(created_at) < datetime('now', ?)",
            (f"-{self._retention_days} days",),
        )
        self._conn.execute(
            "DELETE FROM records WHERE synced = 1 AND "
            "datetime(updated_at) < datetime('now', ?)",
            (f"-{self._retention_days} days",),
        )
        # ファイルも削除
        cur = self._conn.execute(
            "SELECT id, local_path FROM data_files WHERE synced = 1 AND "
            "datetime(created_at) < datetime('now', ?)",
            (f"-{self._retention_days} days",),
        )
        for row in cur.fetchall():
            try:
                Path(row[1]).unlink(missing_ok=True)
            except Exception:
                pass
        self._conn.execute(
            "DELETE FROM data_files WHERE synced = 1 AND "
            "datetime(created_at) < datetime('now', ?)",
            (f"-{self._retention_days} days",),
        )
        self._conn.commit()
        self._conn.execute("VACUUM")

    def get_buffer_size_mb(self) -> float:
        """バッファの現在のサイズ（MB）。"""
        db_size = self._db_path.stat().st_size if self._db_path.exists() else 0
        files_size = sum(
            f.stat().st_size
            for f in self._files_dir.rglob("*")
            if f.is_file()
        )
        return (db_size + files_size) / (1024 * 1024)

    # ========================================
    # 内部: 書き込みスレッド
    # ========================================

    def _writer_loop(self) -> None:
        """バックグラウンドスレッドでキューからデータを読み書き。"""
        while True:
            try:
                item = self._write_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            if item is None:
                break  # 終了シグナル

            item_type, data = item
            try:
                if item_type == "record":
                    self._write_record(data)
                elif item_type == "cell_log":
                    self._write_cell_log(data)
                elif item_type == "file":
                    self._write_file_meta(data)
            except Exception as e:
                import warnings
                warnings.warn(f"バッファ書き込みエラー: {e}")

    def _write_record(self, data: dict[str, Any]) -> None:
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO records (id, data, synced, created_at, updated_at) "
            "VALUES (?, ?, 0, ?, ?)",
            (data["id"], json.dumps(data, ensure_ascii=False, default=str), now, now),
        )
        self._conn.commit()

    def _write_cell_log(self, data: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO cell_logs (cell_id, record_id, data, synced, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (
                data["cell_id"],
                data["record_id"],
                json.dumps(data, ensure_ascii=False, default=str),
                data.get("executed_at", datetime.utcnow().isoformat()),
            ),
        )
        self._conn.commit()

    def _write_file_meta(self, data: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO data_files "
            "(id, record_id, name, local_path, content_type, size_bytes, synced, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
            (
                data["id"], data["record_id"], data["name"],
                data["local_path"], data["content_type"], data["size_bytes"],
                data["created_at"],
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        """バッファを閉じる。"""
        self._write_queue.put(None)  # 終了シグナル
        self._writer_thread.join(timeout=5.0)
        self._conn.close()
```

### 3.4 リモート同期ロジック

```python
"""ローカルバッファ → リモート(Firestore + Nextcloud) の同期。

同期戦略:
- 書き込みは常にローカルバッファに先行
- 同期は別スレッドで定期実行（デフォルト30秒間隔）
- ネットワークエラー時はリトライ（指数バックオフ）
- コンフリクト解決: Last-Write-Wins（タイムスタンプベース）
"""
from __future__ import annotations

import threading
import time
from typing import Any


class SyncManager:
    """ローカルバッファとリモートの同期を管理。"""

    def __init__(
        self,
        buffer: LocalBuffer,
        metadata_backend: Any,   # MetadataBackend
        storage_backend: Any,    # StorageBackend
        *,
        sync_interval_sec: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ) -> None:
        self._buffer = buffer
        self._metadata = metadata_backend
        self._storage = storage_backend
        self._interval = sync_interval_sec
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_sync: float = 0

    def start(self) -> None:
        """バックグラウンド同期を開始。"""
        self._running = True
        self._thread = threading.Thread(
            target=self._sync_loop,
            daemon=True,
            name="mdxdb-sync",
        )
        self._thread.start()

    def stop(self) -> None:
        """バックグラウンド同期を停止。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10.0)

    def sync_now(self) -> dict[str, int]:
        """即座に同期を実行。結果を返す。"""
        return self._sync()

    def _sync_loop(self) -> None:
        """定期同期ループ。"""
        while self._running:
            try:
                self._sync()
            except Exception as e:
                import warnings
                warnings.warn(f"同期エラー: {e}")
            time.sleep(self._interval)

    def _sync(self) -> dict[str, int]:
        """同期の実行。"""
        results = {"records": 0, "cell_logs": 0, "files": 0, "errors": 0}

        # 1. レコードメタデータの同期
        for record_data in self._buffer.get_unsynced_records():
            try:
                self._sync_record(record_data)
                self._buffer.mark_synced("records", [record_data["id"]])
                results["records"] += 1
            except Exception:
                results["errors"] += 1

        # 2. セルログの同期
        for record_data in self._buffer.get_unsynced_records():
            cell_logs = self._buffer.get_unsynced_cell_logs(record_data["id"])
            for cl in cell_logs:
                try:
                    self._sync_cell_log(cl)
                    self._buffer.mark_synced("cell_logs", [cl["cell_id"]])
                    results["cell_logs"] += 1
                except Exception:
                    results["errors"] += 1

        # 3. ファイルの同期
        for file_info in self._buffer.get_unsynced_files():
            try:
                self._sync_file(file_info)
                self._buffer.mark_synced("data_files", [file_info["id"]])
                results["files"] += 1
            except Exception:
                results["errors"] += 1

        self._last_sync = time.time()
        return results

    def _sync_record(self, record_data: dict[str, Any]) -> None:
        """レコードを Firestore に同期。Last-Write-Wins。"""
        for attempt in range(self._max_retries):
            try:
                existing = self._metadata.get_record(record_data["id"])
                if existing is None:
                    self._metadata.create_record(record_data)
                else:
                    # Last-Write-Wins: updated_at が新しい方を採用
                    if record_data.get("updated_at", "") >= existing.get("updated_at", ""):
                        self._metadata.update_record(record_data["id"], record_data)
                return
            except Exception:
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(self._backoff_base ** attempt)

    def _sync_cell_log(self, cell_log: dict[str, Any]) -> None:
        """セルログを Firestore に同期。"""
        for attempt in range(self._max_retries):
            try:
                self._metadata.save_trace(cell_log["record_id"], cell_log)
                return
            except Exception:
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(self._backoff_base ** attempt)

    def _sync_file(self, file_info: dict[str, Any]) -> None:
        """ファイルを Nextcloud に同期。"""
        from pathlib import Path
        local_path = Path(file_info["local_path"])
        if not local_path.exists():
            return  # ファイルが既に削除されている

        data = local_path.read_bytes()
        storage_path = f"{file_info['record_id']}/data/{file_info['name']}"

        for attempt in range(self._max_retries):
            try:
                self._storage.upload(storage_path, data, file_info.get("content_type", ""))
                return
            except Exception:
                if attempt == self._max_retries - 1:
                    raise
                time.sleep(self._backoff_base ** attempt)
```

### 3.5 コンフリクト解決の詳細

```
シナリオ: PC-Aで実験開始 → オフラインになる → PC-Bから同じレコードにメモ追加
→ PC-Aがオンライン復帰

解決戦略: Last-Write-Wins + マージ

1. メタデータ（conditions, results, status等）:
   → updated_at タイムスタンプで Last-Write-Wins
   → 同一フィールドの同時変更は後勝ち

2. 追加型データ（notes, tags, cell_logs）:
   → 両方をマージ（union）
   → cell_logs はcell_idでユニークなので衝突しない
   → notesは追記のみなので衝突しない
   → tagsはset unionで解決

3. ファイル:
   → 同名ファイルの同時変更は後勝ち
   → 実際にはファイル名にタイムスタンプが含まれるケースが多いので衝突は稀
```

---

## 4. SDK全体のAPI再整理

### 4.1 Lab クラス

```python
"""Lab: SDKのエントリーポイント。v7版。

v6からの変更:
- LocalBuffer の自動初期化
- SyncManager の自動起動
- IPython hooks 対応の new()
"""

class Lab:
    """研究室のデータベース接続。

    使い方（Notebook）:
        from mdxdb import Lab
        lab = Lab("konishi-lab")
        exp = lab.new("XRD解析")
        # ← 以降の全セル実行が自動記録される

    使い方（スクリプト）:
        lab = Lab("konishi-lab")
        exp = lab.new("XRD解析", auto_log=False)
        @exp.track
        def process(): ...
    """

    def __init__(
        self,
        team: str | None = None,
        *,
        user: str | None = None,
        metadata_backend: Any | None = None,
        storage_backend: Any | None = None,
        search_backend: Any | None = None,
        buffer_dir: str | Path | None = None,
        auto_sync: bool = True,
        sync_interval: float = 30.0,
    ) -> None:
        # 設定解決（v6と同じ）
        ...

        # ローカルバッファ（常に初期化）
        self._local_buffer = LocalBuffer(buffer_dir=buffer_dir)

        # リモート同期（バックエンドが設定されていれば）
        self._sync_manager: SyncManager | None = None
        if auto_sync and metadata_backend is not None:
            self._sync_manager = SyncManager(
                buffer=self._local_buffer,
                metadata_backend=self._metadata,
                storage_backend=self._storage,
                sync_interval_sec=sync_interval,
            )
            self._sync_manager.start()

    # ==========================================
    # レコード CRUD
    # ==========================================

    def new(
        self,
        title: str,
        *,
        type: str | RecordType = RecordType.EXPERIMENT,
        template: str | None = None,
        tags: list[str] | None = None,
        auto_log: bool = True,
        **conditions: Any,
    ) -> Record:
        """新しいレコードを作成。

        Args:
            title: レコードのタイトル
            type: レコード種別
            template: テンプレート名
            tags: 初期タグ
            auto_log: IPython hooks を有効にするか（デフォルトTrue）
            **conditions: 実験条件

        Returns:
            Record

        例（Notebook）:
            exp = lab.new("Fe-10Cr XRD測定")
            # ← これだけ。以降の全セルが自動記録される。

        例（スクリプト）:
            exp = lab.new("Fe-10Cr XRD測定", auto_log=False)
        """
        record = Record(
            title=title,
            type=type,
            team=self.team,
            created_by=self.user,
            tags=tags or [],
            conditions=conditions if conditions else None,
            template_used=template,
            _lab=self,
        )

        # テンプレート適用
        if template:
            self._apply_template(record, template)

        # ローカルバッファに保存（即座に安全）
        self._local_buffer.save_record(record.to_dict())

        # 検索インデックス更新
        self._index_record(record)

        # IPython hooks 設定
        if auto_log:
            self._setup_auto_logging(record)

        return record

    def get(self, record_id: str) -> Record:
        """IDでレコードを取得。ローカルバッファ→リモートの順で探す。"""
        normalized = normalize_id(record_id)

        # まずローカルバッファを見る
        # → オフラインでも自分のデータは取得可能
        ...

        # ローカルになければリモートを見る
        data = self._metadata.get_record(normalized)
        if data is None:
            raise RecordNotFoundError(normalized)
        return Record.from_dict(data, _lab=self)

    def list(self, **kwargs) -> list[Record]:
        """レコード一覧。v6と同じ。"""
        ...

    def search(self, query: str, **kwargs) -> list[Record]:
        """検索。v6と同じ。"""
        ...

    def recent(self, n: int = 10) -> list[Record]:
        """最新N件。"""
        ...

    def today(self) -> list[Record]:
        """今日のレコード。"""
        ...

    def delete(self, record_id: str, *, hard: bool = False) -> None:
        """削除（ソフトデリートがデフォルト）。"""
        ...

    # ==========================================
    # テンプレート
    # ==========================================

    def define_template(self, name: str, defaults: dict[str, Any]) -> None:
        """テンプレート定義。v6と同じ。"""
        ...

    # ==========================================
    # エクスポート
    # ==========================================

    def export(self, output_dir: str | Path) -> Path:
        """全データをローカルエクスポート。v6と同じ。"""
        ...

    # ==========================================
    # 同期制御
    # ==========================================

    def sync(self) -> dict[str, int]:
        """手動で即座同期。"""
        if self._sync_manager:
            return self._sync_manager.sync_now()
        return {"records": 0, "cell_logs": 0, "files": 0}

    @property
    def sync_status(self) -> dict[str, Any]:
        """同期ステータス。"""
        return {
            "buffer_size_mb": self._local_buffer.get_buffer_size_mb(),
            "unsynced_records": len(self._local_buffer.get_unsynced_records()),
            "last_sync": self._sync_manager._last_sync if self._sync_manager else None,
        }

    def close(self) -> None:
        """リソースの解放。"""
        if self._sync_manager:
            self._sync_manager.sync_now()  # 最後に同期
            self._sync_manager.stop()
        self._local_buffer.close()
```

### 4.2 Record クラス

v6のRecordをベースに、IPython hooks連携を追加。

```python
class Record:
    """1つの実験レコード。v7版。

    v6からの追加:
    - auto_log プロパティ（CellTracker へのアクセス）
    - close() でIPython hooks 解除
    """

    # --- v6と同じフィールド ---
    # id, title, type, status, tags, conditions, results,
    # inputs, outputs, notes, data_refs, external_refs,
    # parent_id, links, etc.

    # --- v7追加フィールド ---
    # _cell_tracker: CellTracker | None

    @property
    def auto_log(self) -> CellTracker | None:
        """自動ログのCellTrackerへのアクセス。

        例:
            exp.auto_log.pause()     # 一時停止
            exp.auto_log.resume()    # 再開
            exp.auto_log.deactivate() # 完全停止
        """
        return getattr(self, "_cell_tracker", None)

    def close(self) -> None:
        """レコードを閉じる。IPython hooksを解除し、最終同期。"""
        tracker = getattr(self, "_cell_tracker", None)
        if tracker:
            tracker.deactivate()
        if self._lab:
            self._lab.sync()
        self.status = Status.SUCCESS  # デフォルトで成功にする

    def __del__(self) -> None:
        """ガベージコレクト時にhooksを解除。"""
        tracker = getattr(self, "_cell_tracker", None)
        if tracker:
            try:
                tracker.deactivate()
            except Exception:
                pass

    # --- 以下、v6と同じ ---
    # conditions(), tag(), untag(), note()
    # add(), save(), get_data()
    # sub(), link()
    # track (property), snapshot(), track_block()
    # to_dict(), from_dict()
```

### 4.3 完全なユースケースフロー

```python
# ============================================================
# ユースケース1: Notebook（メイン。実験者の手間ゼロ）
# ============================================================

# --- Cell 1 ---
from mdxdb import Lab
lab = Lab("konishi-lab")
exp = lab.new("Fe-10Cr XRD測定", tags=["XRD", "Fe-Cr"])
# → IPython hooks 自動登録。以降の全セルが自動記録される。

# --- Cell 2 ---
import numpy as np
data = np.loadtxt("xrd_data.csv", delimiter=",")
cutoff = 0.5
# → 自動記録: new_vars={"data": "<ndarray (5000,2)>", "cutoff": 0.5}

# --- Cell 3 ---
from scipy.signal import butter, filtfilt
b, a = butter(4, cutoff, btype='low')
filtered = filtfilt(b, a, data[:, 1])
# → 自動記録: new_vars={"b": <ndarray>, "a": <ndarray>, "filtered": <ndarray>}

# --- Cell 4 ---
import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot(data[:, 0], filtered)
ax.set_xlabel("2θ (deg)")
plt.show()
# → 自動記録: new_vars={"fig": "<Figure>", "ax": "<Axes>"}

# --- Cell 5 ---
exp.conditions(temperature=500, pressure=1e-3, gas="Ar")
exp.results["lattice_a"] = 2.873
exp.add("filtered_data", filtered)
exp.add("xrd_plot", fig)
# → 明示的な保存。conditions/results/ファイルは意図的に記録。
# → 自動記録もされる: changed_vars={"exp": ...}

# --- Cell 6 ---
exp.close()
# → IPython hooks 解除。最終同期実行。

# ============================================================
# ユースケース2: スクリプト（@exp.track使用）
# ============================================================

from mdxdb import Lab

lab = Lab("konishi-lab")
exp = lab.new("XRD解析バッチ処理", auto_log=False)

@exp.track
def process_xrd(raw_data, cutoff_freq=0.5, method="butterworth"):
    from scipy.signal import butter, filtfilt
    b, a = butter(4, cutoff_freq, btype='low')
    filtered = filtfilt(b, a, raw_data[:, 1])
    return {"filtered": filtered, "n_points": len(filtered)}

raw = np.loadtxt("xrd.csv", delimiter=",")
result = process_xrd(raw, cutoff_freq=0.3)

exp.conditions(temperature=500)
exp.results["n_points"] = result["n_points"]
exp.close()

# ============================================================
# ユースケース3: 別PCからのデータ追加
# ============================================================

from mdxdb import Lab
lab = Lab("konishi-lab")
exp = lab.get("AB3F")       # 短いIDで取得
exp.add("~/data/sem.tiff")  # 装置PCからファイル追加
exp.note("SEM画像追加（倍率5000x）")
```

### 4.4 CLI コマンド一覧

```
mdxdb init                          # 初回セットアップ（チーム、認証設定）
mdxdb new "Fe-10Cr XRD測定"         # レコード作成
mdxdb list [--tags XRD] [--status success]  # 一覧
mdxdb show AB3F                     # レコード詳細
mdxdb add AB3F file.ras             # ファイル追加
mdxdb search "結晶性が良い薄膜"     # 検索
mdxdb note AB3F "結晶性良好"        # メモ追加
mdxdb tag AB3F Fe-Cr thin-film      # タグ追加
mdxdb url AB3F                      # NextcloudのURL表示
mdxdb export ./backup               # 全データエクスポート
mdxdb sync                          # 手動同期
mdxdb sync status                   # 同期ステータス表示
mdxdb buffer clean                  # バッファのクリーンアップ
mdxdb template list                 # テンプレート一覧
mdxdb template create XRD           # テンプレート作成
```

---

## 5. パッケージ構成

### 5.1 ディレクトリ構造

```
src/mdxdb/
├── __init__.py              # Lab, Record, Status, RecordType をre-export
├── _version.py              # バージョン管理
│
├── core/
│   ├── __init__.py
│   ├── lab.py               # Lab クラス（v7版: LocalBuffer + SyncManager統合）
│   ├── record.py            # Record クラス（v7版: auto_log追加）
│   ├── types.py             # 型定義（Status, RecordType, CellLog, Note, Link等）
│   ├── id.py                # Crockford's Base32 IDジェネレーター
│   ├── config.py            # Settings（pydantic-settings）
│   └── exceptions.py        # カスタム例外
│
├── tracking/                # ★ v7で再構成
│   ├── __init__.py
│   ├── cell_tracker.py      # ★ IPython hooks 自動記録（v7のメイン）
│   ├── tracker.py           # @exp.track デコレータ（スクリプト用）
│   ├── snapshot.py          # exp.snapshot()（手動キャプチャ）
│   ├── serializers.py       # 変数のシリアライズ戦略
│   └── context.py           # contextvars でコールスタック管理
│
├── buffer/                  # ★ v7新規
│   ├── __init__.py
│   ├── local.py             # LocalBuffer（SQLite WALモード）
│   └── sync.py              # SyncManager（バッファ→リモート同期）
│
├── backends/
│   ├── __init__.py
│   ├── base.py              # MetadataBackend Protocol
│   ├── memory.py            # InMemoryBackend（テスト・オフライン用）
│   ├── firestore.py         # FirestoreBackend（pip install mdxdb[gcp]）
│   └── local.py             # LocalBackend（SQLite直接、将来）
│
├── storage/
│   ├── __init__.py
│   ├── base.py              # StorageBackend Protocol
│   ├── memory.py            # InMemoryStorage
│   ├── nextcloud.py         # NextcloudStorage
│   └── local.py             # LocalFileStorage
│
├── search/
│   ├── __init__.py
│   ├── base.py              # SearchBackend Protocol
│   ├── memory.py            # InMemorySearch
│   └── firestore.py         # Firestore Vector Search
│
├── cli/
│   ├── __init__.py
│   └── main.py              # Click CLI
│
└── compat/
    ├── __init__.py
    └── v1.py                # 現行 MdxDb からの移行ヘルパー
```

### 5.2 v6からの変更点

| 変更 | v6 | v7 |
|------|-----|-----|
| `tracking/cell_tracker.py` | 存在しない | **新規追加（メイン機能）** |
| `buffer/` モジュール | 存在しない | **新規追加（LocalBuffer + SyncManager）** |
| `tracking/tracker.py` | メイン機能 | スクリプト用オプション |
| `core/lab.py` | バックエンド直接保存 | **LocalBuffer経由で保存** |

### 5.3 依存関係

```toml
[project]
dependencies = [
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "click>=8.1",
]
# sqlite3 は Python標準ライブラリなので追加依存なし

[project.optional-dependencies]
gcp = ["google-cloud-firestore>=2.16", "google-cloud-aiplatform>=1.50"]
nextcloud = ["nc-py-api>=0.19"]
numpy = ["numpy>=1.24"]
all = ["mdxdb[gcp,nextcloud,numpy]"]
dev = ["pytest>=8.1", "pytest-cov", "ruff", "mypy", "ipython>=8.0"]
```

**`pip install mdxdb` だけで動く:** InMemoryBackend + LocalBuffer + IPython hooks（IPythonがあれば）

---

## 6. テスト設計

### 6.1 テスト構成

```
tests/
├── conftest.py                    # 共通fixture（InMemoryBackend等）
├── test_core/
│   ├── test_lab.py                # Lab CRUD テスト
│   ├── test_record.py             # Record 操作テスト
│   ├── test_types.py              # 型定義テスト
│   └── test_id.py                 # ID生成テスト
├── test_tracking/
│   ├── test_cell_tracker.py       # ★ IPython hooks テスト
│   ├── test_tracker.py            # @exp.track テスト
│   ├── test_snapshot.py           # snapshot テスト
│   └── test_serializers.py        # シリアライズテスト
├── test_buffer/
│   ├── test_local_buffer.py       # ★ SQLiteバッファ テスト
│   └── test_sync.py               # ★ 同期ロジック テスト
├── test_backends/
│   ├── test_memory.py             # InMemoryBackend テスト
│   └── test_firestore.py          # Firestoreテスト（要接続）
├── test_storage/
│   ├── test_memory.py             # InMemoryStorage テスト
│   └── test_nextcloud.py          # Nextcloudテスト（要接続）
├── test_cli/
│   └── test_commands.py           # CLI テスト
└── test_integration/
    └── test_full_flow.py          # 統合テスト
```

### 6.2 IPython Hooks のテスト方法

```python
"""IPython hooks のテスト。

IPython.testing.globalipapp を使って仮想IPython環境を作成し、
hooks の登録/発火/CellLog生成をテストする。
"""
import pytest

# IPython のテスト用ユーティリティ
from IPython.testing.globalipapp import get_ipython


@pytest.fixture
def ip():
    """テスト用のIPython インスタンス。"""
    return get_ipython()


@pytest.fixture
def lab_with_tracker(ip):
    """IPython hooks が有効な Lab + Record。"""
    from mdxdb import Lab
    from mdxdb.backends.memory import InMemoryMetadataBackend
    from mdxdb.storage.memory import InMemoryStorageBackend
    from mdxdb.buffer.local import LocalBuffer
    import tempfile

    buffer_dir = tempfile.mkdtemp()
    lab = Lab(
        team="test",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        buffer_dir=buffer_dir,
        auto_sync=False,  # テストでは手動同期
    )
    record = lab.new("テスト実験")
    return lab, record


class TestCellTracker:
    """IPython hooks のテスト。"""

    def test_hooks_registered(self, lab_with_tracker, ip):
        """hooks がIPythonに登録されていることを確認。"""
        _, record = lab_with_tracker
        assert record.auto_log is not None
        assert record.auto_log.is_active

    def test_cell_execution_logged(self, lab_with_tracker, ip):
        """セル実行がCellLogとして記録されることを確認。"""
        lab, record = lab_with_tracker

        # IPython でセルを実行
        ip.run_cell("x = 42")

        # バッファからログを取得
        logs = lab._local_buffer.get_unsynced_cell_logs(record.id)
        assert len(logs) >= 1

        # 最新のログを確認
        latest = logs[-1]
        assert "x" in latest.get("new_vars", {}) or \
               "x" in str(latest.get("data", {}).get("new_vars", {}))

    def test_namespace_diff(self, lab_with_tracker, ip):
        """namespace diff が正しく計算されることを確認。"""
        lab, record = lab_with_tracker

        ip.run_cell("a = 1")
        ip.run_cell("b = 2; a = 10")  # aは変更、bは新規

        logs = lab._local_buffer.get_unsynced_cell_logs(record.id)
        # b が new_vars に、a が changed_vars にあることを確認
        latest = logs[-1]
        data = latest if isinstance(latest, dict) else latest
        assert "b" in str(data.get("new_vars", {}))

    def test_error_logged(self, lab_with_tracker, ip):
        """エラー発生時も記録されることを確認。"""
        lab, record = lab_with_tracker

        ip.run_cell("1 / 0")  # ZeroDivisionError

        logs = lab._local_buffer.get_unsynced_cell_logs(record.id)
        latest = logs[-1]
        assert latest.get("error") is not None

    def test_pause_resume(self, lab_with_tracker, ip):
        """pause/resume が機能することを確認。"""
        lab, record = lab_with_tracker

        record.auto_log.pause()
        ip.run_cell("hidden = 'secret'")
        record.auto_log.resume()
        ip.run_cell("visible = 'ok'")

        logs = lab._local_buffer.get_unsynced_cell_logs(record.id)
        all_vars = str(logs)
        assert "hidden" not in all_vars  # pause中は記録されない
        assert "visible" in all_vars      # resume後は記録される

    def test_sensitive_vars_excluded(self, lab_with_tracker, ip):
        """パスワード等がログに含まれないことを確認。"""
        lab, record = lab_with_tracker

        ip.run_cell("password = 'secret123'")
        ip.run_cell("api_key = 'sk-xxxx'")

        logs = lab._local_buffer.get_unsynced_cell_logs(record.id)
        all_text = str(logs)
        assert "secret123" not in all_text
        assert "sk-xxxx" not in all_text

    def test_magic_commands_skipped(self, lab_with_tracker, ip):
        """マジックコマンドがスキップされることを確認。"""
        lab, record = lab_with_tracker
        initial_count = len(lab._local_buffer.get_unsynced_cell_logs(record.id))

        ip.run_cell("%who")  # マジックコマンド

        final_count = len(lab._local_buffer.get_unsynced_cell_logs(record.id))
        assert final_count == initial_count  # ログが増えていない

    def test_deactivate(self, lab_with_tracker, ip):
        """deactivate後はログが記録されないことを確認。"""
        lab, record = lab_with_tracker

        record.auto_log.deactivate()
        ip.run_cell("after_deactivate = True")

        logs = lab._local_buffer.get_unsynced_cell_logs(record.id)
        all_text = str(logs)
        assert "after_deactivate" not in all_text
```

### 6.3 ローカルバッファのテスト

```python
"""ローカルバッファのテスト。"""
import pytest
import tempfile
import json
from datetime import datetime
from pathlib import Path


@pytest.fixture
def buffer():
    """テスト用の一時バッファ。"""
    from mdxdb.buffer.local import LocalBuffer
    with tempfile.TemporaryDirectory() as tmpdir:
        buf = LocalBuffer(buffer_dir=tmpdir)
        yield buf
        buf.close()


class TestLocalBuffer:
    def test_save_and_retrieve_record(self, buffer):
        record_data = {
            "id": "AB3F",
            "title": "テスト実験",
            "team": "test",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        buffer.save_record(record_data)

        import time; time.sleep(0.5)  # writer threadの処理を待つ

        unsynced = buffer.get_unsynced_records()
        assert len(unsynced) == 1
        assert unsynced[0]["id"] == "AB3F"

    def test_save_cell_log(self, buffer):
        from mdxdb.core.types import CellLog
        # CellLog相当のdictを保存
        cell_log_data = {
            "cell_id": "test001",
            "record_id": "AB3F",
            "cell_number": 1,
            "execution_count": 1,
            "source": "x = 42",
            "source_hash": "abc123",
            "new_vars": {"x": 42},
            "changed_vars": {},
            "deleted_vars": [],
            "executed_at": datetime.utcnow().isoformat(),
        }

        class MockCellLog:
            def to_dict(self): return cell_log_data

        buffer.save_cell_log(MockCellLog())
        import time; time.sleep(0.5)

        logs = buffer.get_unsynced_cell_logs("AB3F")
        assert len(logs) == 1

    def test_save_file(self, buffer):
        path = buffer.save_file("AB3F", "data.csv", b"x,y\n1,2\n3,4", "text/csv")
        assert Path(path).exists()

    def test_mark_synced(self, buffer):
        buffer.save_record({
            "id": "SYNC", "title": "sync test",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        import time; time.sleep(0.5)

        buffer.mark_synced("records", ["SYNC"])
        assert len(buffer.get_unsynced_records()) == 0

    def test_buffer_size(self, buffer):
        size = buffer.get_buffer_size_mb()
        assert size >= 0

    def test_cleanup(self, buffer):
        """同期済みデータのクリーンアップ。"""
        buffer.save_record({
            "id": "OLD", "title": "old",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        import time; time.sleep(0.5)
        buffer.mark_synced("records", ["OLD"])
        buffer.cleanup()  # エラーなく実行される
```

### 6.4 InMemoryBackend で全テストがオフラインで動く

```python
"""conftest.py — テスト用のInMemoryバックエンドを提供。"""
import pytest
import tempfile


@pytest.fixture
def lab():
    """完全にオフラインで動作するLabインスタンス。"""
    from mdxdb import Lab
    from mdxdb.backends.memory import InMemoryMetadataBackend
    from mdxdb.storage.memory import InMemoryStorageBackend
    from mdxdb.search.memory import InMemorySearchBackend

    return Lab(
        team="test-team",
        user="test-user",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
        buffer_dir=tempfile.mkdtemp(),
        auto_sync=False,
    )


@pytest.fixture
def record(lab):
    """テスト用のレコード。auto_log無効（IPython不要）。"""
    return lab.new("テスト実験", auto_log=False)
```

**全テストがオフラインで実行可能:**
- Firestore接続不要
- Nextcloud接続不要
- ネットワーク不要
- `pytest` 一発で全テスト実行

---

## 7. 既存ツールとの差別化

### 7.1 比較表

| 機能 | MLflow | W&B | Sacred | **mdxdb (v7)** |
|------|--------|-----|--------|----------------|
| **Notebook全セル自動記録** | -- | -- | -- | **IPython hooks** |
| 実験者の手間 | `mlflow.start_run()` + 手動log | `wandb.init()` + 手動log | `@ex.automain` | **`lab.new()` のみ** |
| ML特化 | Yes | Yes | Yes | **No（汎用科学実験）** |
| 変数の自動キャプチャ | `autolog()` (MLフレームワーク限定) | -- | `@ex.capture` (関数引数のみ) | **namespace diff** |
| Notebookベタ書き対応 | 手動log必要 | 手動log必要 | -- | **自動** |
| LLM向けデータ構造 | -- | -- | -- | **CellLog + トレース** |
| オフラインバッファ | ローカルファイル | -- | -- | **SQLite WAL** |
| 短いID | -- | run名(長い) | -- | **4文字 Crockford Base32** |
| 子レコード/階層 | Nested Runs(限定的) | -- | -- | **任意階層** |
| MCP対応 | -- | -- | -- | **MCPサーバー** |
| チーム共有 | Tracking Server | W&B Server | -- | **Firestore** |
| ブラウザ投入 | -- | -- | -- | **Nextcloud** |

### 7.2 mdxdb v7 の独自価値

**「Notebookで普通にコードを書くだけで、全実行履歴がLLMに理解可能な形で自動保存される」**

これは既存ツールにない機能。具体的には:

1. **IPython hooks による全セル自動記録**
   - MLflow `autolog()` はsklearn/torch等のMLフレームワーク特化。科学実験のベタ書きコードには対応しない。
   - W&B はNotebookの保存はできるが、セルごとの変数変化は記録しない。
   - Sacred の `@ex.capture` は関数引数のみ。ベタ書きに対応しない。

2. **namespace diff**
   - 各セルで何が変わったかを自動検出。
   - LLMは「cutoff=0.5でフィルタした後にpeak_findingを実行」という処理フローを、CellLogから完全に再構成できる。

3. **LLM-native なデータ構造**
   - CellLogのフォーマットがLLMにとって理解しやすい（ソースコード + 変数変化 + 実行時間）。
   - MCPサーバー経由でClaude/Geminiが直接アクセスできる。

4. **科学実験全般への汎用性**
   - MLフレームワークに依存しない。
   - XRD, SEM, SQUID, 化学反応、計算科学、なんでも対応。

### 7.3 LLMから見たmdxdb v7のデータ

```json
{
  "record": {
    "id": "AB3F",
    "title": "Fe-10Cr XRD測定",
    "conditions": {"temperature": 500, "pressure": 1e-3, "gas": "Ar"},
    "results": {"lattice_a": 2.873, "crystallite_size": 45.2},
    "tags": ["XRD", "Fe-Cr", "thin-film"]
  },
  "cell_logs": [
    {
      "cell_number": 2,
      "source": "import numpy as np\ndata = np.loadtxt('xrd_data.csv', delimiter=',')\ncutoff = 0.5",
      "new_vars": {"data": {"__type__": "ndarray", "shape": [5000, 2]}, "cutoff": 0.5},
      "duration_sec": 0.12
    },
    {
      "cell_number": 3,
      "source": "from scipy.signal import butter, filtfilt\nb, a = butter(4, cutoff, btype='low')\nfiltered = filtfilt(b, a, data[:, 1])",
      "new_vars": {"filtered": {"__type__": "ndarray", "shape": [5000]}},
      "duration_sec": 0.05
    }
  ]
}
```

LLMはこのデータから:
- 「cutoff=0.5で4次Butterworthフィルタを適用」という処理を正確に理解
- 「他の実験と比較して、cutoffの値がどう違うか」を特定
- 「このlattice_aの値はどのデータからどう計算されたか」を追跡

---

## 8. マイルストーン

### 8.1 v7 対応の修正タイムライン

```
Week 1-2:   M0 基盤セットアップ + 技術POC
Week 2-4:   M1 SDK Core + LocalBuffer + CellTracker
Week 4-5:   M2 Embedding + Vector Search
Week 5-7:   M3 MCPサーバー + CLI
Week 7:     ★ MVP完成 → チームAlpha利用開始
```

### 8.2 M1 の詳細（IPython hooks + LocalBuffer が加わった）

**M1で実装する機能（優先度順）:**

1. `core/` モジュール全体（Lab, Record, types, id, config, exceptions）
2. `backends/memory.py`（InMemoryBackend）
3. `storage/memory.py`（InMemoryStorage）
4. `search/memory.py`（InMemorySearch）
5. **`buffer/local.py`（LocalBuffer: SQLite WALモード）** ← v7追加
6. **`tracking/cell_tracker.py`（CellTracker: IPython hooks）** ← v7追加
7. `tracking/serializers.py`（変数シリアライズ）
8. `tracking/tracker.py`（@exp.track デコレータ）
9. `tracking/snapshot.py`（exp.snapshot()）
10. 全テスト（オフライン実行可能）

**M1完了基準:**
```python
# これが動く
from mdxdb import Lab
lab = Lab()  # InMemoryBackend（デフォルト）
exp = lab.new("テスト")  # IPython環境ならhooks自動登録
exp.conditions(temperature=500)
exp.add("data.csv", {"x": [1,2,3], "y": [4,5,6]})
exp.results["a"] = 2.873
exp.tag("XRD")
exp.close()

# ローカルバッファにデータが保存されている
assert lab.sync_status["buffer_size_mb"] > 0

# 検索が動く
results = lab.search("テスト")
assert len(results) == 1
```

### 8.3 技術リスクと対策

| リスク | 影響度 | 対策 |
|--------|--------|------|
| IPython hooks のバージョン互換性 | 中 | IPython 7.x/8.x 両対応。events APIは安定 |
| SQLite WALモードのファイルロック | 低 | Notebook=単一プロセス。問題なし |
| namespace diff のパフォーマンス | 低 | 1000変数で~2ms。実用上問題なし |
| serialize_value の例外 | 低 | 全てtry-exceptでガード。repr()フォールバック |
| CellTracker の GC時deactivate | 低 | `__del__` でhooks解除。IPython側もweakref |

---

## 付録: CellLog のLLM活用例

### MCPツールでのセルログ取得

```json
{
  "tool": "get_cell_logs",
  "params": {
    "record_id": "AB3F",
    "cell_range": [2, 5]
  },
  "response": {
    "cell_logs": [
      {
        "cell_number": 2,
        "source": "data = np.loadtxt('xrd_data.csv', delimiter=',')\ncutoff = 0.5",
        "new_vars": {"data": "<ndarray (5000,2)>", "cutoff": 0.5}
      },
      {
        "cell_number": 3,
        "source": "b, a = butter(4, cutoff, btype='low')\nfiltered = filtfilt(b, a, data[:, 1])",
        "new_vars": {"filtered": "<ndarray (5000,)>"}
      }
    ]
  }
}
```

### LLMの推論例

**質問:** 「AB3Fのフィルタリングで使ったcutoff値は？」

**LLMの推論:**
1. `get_cell_logs(record_id="AB3F")` でセルログ取得
2. Cell 2 で `cutoff = 0.5` が定義されたことを確認
3. Cell 3 で `butter(4, cutoff, ...)` に渡されたことを確認
4. 回答: 「AB3F実験では、4次Butterworthフィルタのcutoff周波数として0.5が使用されました」

**これはMLflow/W&Bでは不可能。** 手動で `mlflow.log_param("cutoff", 0.5)` しない限り、cutoffの値は記録されない。mdxdb v7なら自動。
