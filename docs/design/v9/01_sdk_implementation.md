# v9 SDK実装仕様書

> v8設計をlabvault化し、認証・チーム管理APIを追加した実装仕様。
> 全クラス・全メソッドの型ヒント付きシグネチャ、Firestoreスキーマ、SQLiteテーブル定義、
> テストケース一覧、Issue一覧を含む。

---

## 目次

1. [全クラス・全メソッド定義](#1-全クラス全メソッド定義)
2. [Firestoreドキュメント構造](#2-firestoreドキュメント構造)
3. [ローカルバッファ実装仕様](#3-ローカルバッファ実装仕様)
4. [IPython hooks実装仕様](#4-ipython-hooks実装仕様)
5. [自動処理トリガー実装仕様](#5-自動処理トリガー実装仕様)
6. [pyproject.toml](#6-pyprojecttoml)
7. [テストケース一覧](#7-テストケース一覧)
8. [M0-M4 Issue一覧](#8-m0-m4-issue一覧)

---

## 1. 全クラス・全メソッド定義

### 1.1 Settings（pydantic-settings）

```python
# src/labvault/core/config.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SDK設定。環境変数 → ~/.labvault/config.toml → デフォルト の順で解決。"""

    model_config = SettingsConfigDict(
        env_prefix="LABVAULT_",
        toml_file=Path.home() / ".labvault" / "config.toml",
    )

    # チーム
    team: str = ""
    user: str = ""

    # GCP
    gcp_project: str = ""
    firestore_database: str = "(default)"

    # Nextcloud
    nextcloud_url: str = ""
    nextcloud_user: str = ""
    nextcloud_password: str = ""
    nextcloud_group_folder: str = ""

    # バッファ
    buffer_dir: Path = Path.home() / ".labvault" / "buffer"
    buffer_max_size_mb: int = 500
    buffer_retention_days: int = 30

    # 同期
    auto_sync: bool = True
    sync_interval_sec: float = 30.0

    # トラッキング
    auto_log: bool = True
    exclude_vars: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
```

### 1.2 型定義・Enum

```python
# src/labvault/core/types.py
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class Status(str, enum.Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class RecordType(str, enum.Enum):
    EXPERIMENT = "experiment"
    SAMPLE = "sample"
    PROCESS = "process"
    MEASUREMENT = "measurement"
    COMPUTATION = "computation"
    ANALYSIS = "analysis"


@dataclass
class Note:
    text: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    author: str = ""


@dataclass
class Link:
    target_id: str
    relation: str  # "derived_from", "related_to", "replaces" 等
    description: str = ""


@dataclass
class ExternalRef:
    """転送せず参照だけ登録するデータ。"""
    uri: str                         # パス, URL, DOI
    location: str = ""               # "TSUBAME:/home/...", "zenodo" 等
    size_bytes: int | None = None
    description: str = ""
    doi: str = ""


@dataclass
class DataRef:
    """Nextcloudに保存されたファイルのメタデータ。"""
    name: str
    nextcloud_path: str
    content_type: str = ""
    size_bytes: int = 0
    sha256: str = ""
    preview_path: str | None = None  # _preview/ 配下のパス


@dataclass
class CellLog:
    """1セルの実行記録。"""
    cell_id: str
    record_id: str
    cell_number: int
    execution_count: int
    source: str
    source_hash: str
    new_vars: dict[str, Any] = field(default_factory=dict)
    changed_vars: dict[str, Any] = field(default_factory=dict)
    deleted_vars: list[str] = field(default_factory=list)
    result_repr: str | None = None
    error: dict[str, Any] | None = None
    duration_sec: float = 0.0
    executed_at: datetime = field(default_factory=datetime.utcnow)
    env: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: ...


@dataclass
class Analysis:
    """LLM execute_code の結果1件。"""
    id: str                              # Crockford Base32 ユニークID
    record_id: str
    name: str                            # "gaussian_fit_001" 等
    code: str                            # 実行したPythonコード全文
    input_files: list[str] = field(default_factory=list)
    input_analyses: list[str] = field(default_factory=list)  # 前の解析IDチェーン
    results: dict[str, Any] = field(default_factory=dict)
    images: list[str] = field(default_factory=list)          # 画像ファイル名
    executed_at: datetime = field(default_factory=datetime.utcnow)
    executed_by: str = ""                # "claude", ユーザー名
    prompt: str = ""                     # 元の指示テキスト
    duration_sec: float = 0.0
    packages: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]: ...
```

### 1.3 IDジェネレーター

```python
# src/labvault/core/id.py
from __future__ import annotations

import secrets

# Crockford's Base32（I, L, O, U を除外）
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def generate_id(length: int = 4) -> str:
    """Crockford's Base32 のランダムID生成。

    Args:
        length: 文字数。4文字=約100万通り、8文字=約1兆通り。

    Returns:
        大文字の Base32 文字列。例: "AB3F"
    """
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def normalize_id(raw: str) -> str:
    """入力IDを正規化。小文字→大文字、O→0, I/L→1 に変換。"""
    table = str.maketrans("oilOIL", "011011")
    return raw.upper().translate(table)
```

### 1.4 例外

```python
# src/labvault/core/exceptions.py
class LabvaultError(Exception):
    """SDK基底例外。"""


class RecordNotFoundError(LabvaultError):
    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        super().__init__(f"Record not found: {record_id}")


class SyncError(LabvaultError):
    """同期失敗。"""


class BackendError(LabvaultError):
    """バックエンド操作失敗。"""


class ValidationError(LabvaultError):
    """バリデーションエラー。"""


class AuthError(LabvaultError):
    """認証・認可エラー。"""


class PermissionError(LabvaultError):
    """権限不足エラー。"""
```

### 1.5 Backend Protocol

```python
# src/labvault/backends/base.py
from __future__ import annotations
from typing import Any, Protocol


class MetadataBackend(Protocol):
    """メタデータストアの抽象。Firestore / InMemory / SQLite。"""

    def create_record(self, data: dict[str, Any]) -> None: ...
    def get_record(self, record_id: str) -> dict[str, Any] | None: ...
    def update_record(self, record_id: str, data: dict[str, Any]) -> None: ...
    def delete_record(self, record_id: str, *, hard: bool = False) -> None: ...
    def list_records(
        self,
        *,
        team: str = "",
        tags: list[str] | None = None,
        status: str | None = None,
        record_type: str | None = None,
        created_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "updated_at",
        order_dir: str = "desc",
    ) -> list[dict[str, Any]]: ...

    # セルログ
    def save_cell_log(self, record_id: str, data: dict[str, Any]) -> None: ...
    def get_cell_logs(self, record_id: str, *, limit: int = 100) -> list[dict[str, Any]]: ...

    # 解析履歴
    def save_analysis(self, record_id: str, data: dict[str, Any]) -> None: ...
    def get_analyses(self, record_id: str) -> list[dict[str, Any]]: ...

    # テンプレート
    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None: ...
    def get_template(self, team: str, name: str) -> dict[str, Any] | None: ...
    def list_templates(self, team: str) -> list[dict[str, Any]]: ...

    # チーム管理
    def create_team(self, team_id: str, data: dict[str, Any]) -> None: ...
    def get_team(self, team_id: str) -> dict[str, Any] | None: ...
    def update_team(self, team_id: str, data: dict[str, Any]) -> None: ...


# src/labvault/storage/base.py
class StorageBackend(Protocol):
    """バイナリストレージの抽象。Nextcloud / InMemory / LocalFS。"""

    def upload(self, path: str, data: bytes, content_type: str = "") -> str: ...
    def download(self, path: str) -> bytes: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def get_share_url(self, path: str) -> str: ...
    def list_files(self, prefix: str) -> list[str]: ...


# src/labvault/search/base.py
class SearchBackend(Protocol):
    """検索エンジンの抽象。Firestore Vector Search / InMemory。"""

    def index(self, record_id: str, text: str, embedding: list[float] | None = None) -> None: ...
    def search(
        self,
        query: str,
        *,
        embedding: list[float] | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]: ...
    def delete(self, record_id: str) -> None: ...
```

### 1.6 Lab クラス

```python
# src/labvault/core/lab.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import Settings
from .exceptions import RecordNotFoundError
from .id import generate_id, normalize_id
from .record import Record
from .types import RecordType, Status


class Lab:
    """研究室のデータベース接続。SDKのエントリーポイント。

    使い方（Notebook）::

        from labvault import Lab
        lab = Lab("konishi-lab")
        exp = lab.new("XRD解析")
        # ← 以降の全セル実行が自動記録

    使い方（スクリプト）::

        lab = Lab("konishi-lab")
        exp = lab.new("XRD解析", auto_log=False)
        @exp.track
        def process(): ...
    """

    # --- 初期化 ---

    def __init__(
        self,
        team: str | None = None,
        *,
        user: str | None = None,
        metadata_backend: MetadataBackend | None = None,
        storage_backend: StorageBackend | None = None,
        search_backend: SearchBackend | None = None,
        buffer_dir: str | Path | None = None,
        auto_sync: bool = True,
        sync_interval: float = 30.0,
    ) -> None:
        """初期化。認証フロー: GCP ADC → サービスアカウント → 設定ファイル。"""
        ...

    # --- プロパティ ---

    @property
    def team(self) -> str: ...

    @property
    def user(self) -> str: ...

    # --- レコード CRUD ---

    def new(
        self,
        title: str,
        *,
        type: str | RecordType = RecordType.EXPERIMENT,
        template: str | None = None,
        tags: list[str] | None = None,
        sample: str | None = None,
        auto_log: bool = True,
        **conditions: Any,
    ) -> Record:
        """新しいレコードを作成。IPython環境ではセル自動記録を自動開始。"""
        ...

    def get(self, record_id: str) -> Record:
        """IDでレコード取得。ローカルバッファ→リモートの順。

        Raises:
            RecordNotFoundError: レコードが見つからない場合
        """
        ...

    def list(
        self,
        *,
        tags: list[str] | None = None,
        status: str | Status | None = None,
        type: str | RecordType | None = None,
        created_by: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Record]:
        """レコード一覧。フィルタ付き。"""
        ...

    def search(
        self,
        query: str,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        type: str | None = None,
        limit: int = 20,
    ) -> list[Record]:
        """テキスト検索。セマンティック検索対応（M3以降）。"""
        ...

    def recent(self, n: int = 10) -> list[Record]:
        """最新 n 件を取得。"""
        ...

    def today(self) -> list[Record]:
        """今日作成されたレコード一覧。"""
        ...

    def delete(self, record_id: str, *, hard: bool = False) -> None:
        """削除（デフォルトはソフトデリート = ゴミ箱移動）。"""
        ...

    def trash(self) -> list[Record]:
        """ゴミ箱（deleted状態）のレコード一覧。"""
        ...

    def restore(self, record_id: str) -> Record:
        """ゴミ箱から復元。"""
        ...

    # --- テンプレート ---

    def define_template(
        self,
        name: str,
        *,
        type: str | RecordType = RecordType.EXPERIMENT,
        default_tags: list[str] | None = None,
        default_conditions: dict[str, Any] | None = None,
        recommended_results: list[str] | None = None,
        description: str = "",
    ) -> None:
        """テンプレート定義をチームに保存。"""
        ...

    def templates(self) -> list[dict[str, Any]]:
        """チームのテンプレート一覧。"""
        ...

    # --- チーム管理 [R19] ---

    def create_team(
        self,
        name: str,
        *,
        nextcloud_folder: str = "",
    ) -> dict[str, Any]:
        """新しいチームを作成。作成者がadminになる。

        Args:
            name: チーム名（team_idとしても使用）
            nextcloud_folder: Nextcloudのグループフォルダ名

        Returns:
            {"team_id": str, "name": str, "admin": [str], "members": {}}
        """
        ...

    def invite(self, email: str, *, role: str = "member") -> None:
        """チームにメンバーを招待。adminのみ実行可能。

        Args:
            email: 招待するユーザーのメールアドレス
            role: "admin" | "member"

        Raises:
            PermissionError: admin権限がない場合
        """
        ...

    def remove_member(self, email: str) -> None:
        """チームからメンバーを削除。adminのみ実行可能。"""
        ...

    def set_role(self, email: str, role: str) -> None:
        """メンバーのロールを変更。adminのみ実行可能。

        Args:
            email: 対象メンバーのメールアドレス
            role: "admin" | "member"
        """
        ...

    def team_info(self) -> dict[str, Any]:
        """現在のチーム情報を取得。

        Returns:
            {
                "team_id": str,
                "name": str,
                "nextcloud_group_folder": str,
                "members": {"email": "role", ...},
                "admin": [str],
                "created_at": str,
            }
        """
        ...

    # --- 同期 ---

    def sync(self) -> dict[str, int]:
        """手動で即座に同期実行。

        Returns:
            {"records": int, "cell_logs": int, "files": int, "errors": int}
        """
        ...

    @property
    def sync_status(self) -> dict[str, Any]:
        """同期ステータス。"""
        ...

    # --- エクスポート ---

    def export(self, output_dir: str | Path) -> Path:
        """全データをローカルにエクスポート（JSON Lines + ファイル）。"""
        ...

    # --- ストレージ使用量 ---

    def storage_usage(self) -> dict[str, Any]:
        """Nextcloudストレージ使用量。"""
        ...

    # --- ライフサイクル ---

    def close(self) -> None:
        """リソース解放。最終同期→バッファクローズ。"""
        ...

    def __enter__(self) -> Lab:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
```

### 1.7 Record クラス

```python
# src/labvault/core/record.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, TYPE_CHECKING

from .id import generate_id
from .types import (
    Analysis, CellLog, DataRef, ExternalRef, Link, Note, RecordType, Status,
)

if TYPE_CHECKING:
    from .lab import Lab
    from ..tracking.cell_tracker import CellTracker
    from ..tracking.tracker import Tracker


class _ResultsProxy:
    """record.results["key"] = value で自動保存するプロキシ。"""

    def __init__(self, record: Record) -> None: ...
    def __setitem__(self, key: str, value: Any) -> None: ...
    def __getitem__(self, key: str) -> Any: ...
    def __contains__(self, key: str) -> bool: ...
    def __repr__(self) -> str: ...
    def keys(self) -> Any: ...
    def values(self) -> Any: ...
    def items(self) -> Any: ...
    def to_dict(self) -> dict[str, Any]: ...
    def update(self, data: dict[str, Any]) -> None: ...


class Record:
    """1つの実験レコード。

    メソッドチェーン対応::

        exp.tag("XRD").conditions(temp=500).note("良好")

    コンテキストマネージャ対応::

        with lab.new("XRD") as exp:
            exp.add("data.csv")
        # ← close() 自動呼び出し
    """

    def __init__(
        self,
        *,
        id: str | None = None,
        title: str = "",
        type: str | RecordType = RecordType.EXPERIMENT,
        team: str = "",
        created_by: str = "",
        status: str | Status = Status.RUNNING,
        tags: list[str] | None = None,
        conditions_data: dict[str, Any] | None = None,
        results_data: dict[str, Any] | None = None,
        notes: list[Note] | None = None,
        data_refs: dict[str, DataRef] | None = None,
        external_refs: list[ExternalRef] | None = None,
        parent_id: str | None = None,
        links: list[Link] | None = None,
        template_used: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        deleted_at: datetime | None = None,
        _lab: Lab | None = None,
    ) -> None: ...

    # --- プロパティ（読み取り専用） ---

    @property
    def id(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def type(self) -> str: ...
    @property
    def team(self) -> str: ...
    @property
    def created_by(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def updated_at(self) -> datetime: ...
    @property
    def parent_id(self) -> str | None: ...

    # --- プロパティ（読み書き） ---

    @property
    def status(self) -> str: ...
    @status.setter
    def status(self, value: str | Status) -> None: ...

    @property
    def results(self) -> _ResultsProxy: ...

    # --- 実験条件 ---

    def conditions(self, **kwargs: Any) -> Record:
        """実験条件を設定。メソッドチェーン対応。"""
        ...

    def get_conditions(self) -> dict[str, Any]: ...

    # --- タグ ---

    def tag(self, *tags: str) -> Record: ...
    def untag(self, *tags: str) -> Record: ...

    @property
    def tags(self) -> list[str]: ...

    # --- メモ ---

    def note(self, text: str) -> Record: ...

    @property
    def notes(self) -> list[Note]: ...

    # --- データ追加（ファイル） ---

    def add(
        self,
        source: str | Path | bytes,
        name: str | None = None,
        *,
        content_type: str = "",
    ) -> Record:
        """ファイルを追加。ローカルバッファ→Nextcloud。"""
        ...

    def add_dir(self, dir_path: str | Path) -> Record:
        """ディレクトリ配下の全ファイルを再帰的に追加。"""
        ...

    # --- データ追加（型自動判定） ---

    def save(self, name: str, data: Any) -> Record:
        """データを型自動判定で保存。

        型判定ルール:
          - dict / list         → JSON (.json)
          - str                 → テキスト (.txt)
          - numpy.ndarray       → NumPy (.npy) + _meta.json
          - matplotlib.Figure   → PNG (.png)
          - pandas.DataFrame    → CSV (.csv)
          - bytes               → バイナリ
        """
        ...

    # --- データ取得 ---

    def get_data(self, name: str) -> bytes: ...
    def list_data(self) -> list[DataRef]: ...

    @property
    def nextcloud_url(self) -> str: ...

    # --- 外部参照（大容量データ） ---

    def add_ref(
        self,
        path: str = "",
        *,
        location: str = "",
        size_gb: float | None = None,
        description: str = "",
        doi: str = "",
    ) -> Record:
        """外部データの参照のみ登録（転送しない）。"""
        ...

    # --- 子レコード ---

    def sub(
        self,
        title: str,
        *,
        type: str | RecordType = RecordType.MEASUREMENT,
        **conditions: Any,
    ) -> Record:
        """子レコード作成。"""
        ...

    def children(self) -> list[Record]: ...

    # --- リンク ---

    def link(self, target: str | Record, relation: str = "related_to", description: str = "") -> Record: ...

    # --- 解析履歴 ---

    def analyses(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
    ) -> list[Analysis]:
        """解析履歴の取得。name: 名前フィルタ（部分一致）。id: IDで取得。"""
        ...

    # --- 自動ログ制御 ---

    @property
    def auto_log(self) -> CellTracker | None: ...

    def pause_logging(self) -> Record:
        """自動ログ一時停止のショートカット。"""
        ...

    def resume_logging(self) -> Record:
        """自動ログ再開のショートカット。"""
        ...

    # --- @exp.track デコレータ（スクリプト用） ---

    @property
    def track(self) -> Tracker: ...

    def track_block(self, name: str = "") -> _TrackBlockContext: ...

    # --- スナップショット（手動） ---

    def snapshot(self, *, include: list[str] | None = None, exclude: list[str] | None = None) -> Record:
        """現在のローカル変数をスナップショット。"""
        ...

    # --- シリアライズ ---

    def to_dict(self) -> dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, _lab: Lab | None = None) -> Record: ...

    # --- ライフサイクル ---

    def close(self) -> None:
        """レコードを閉じる。hooks解除 → 最終同期 → status=success。"""
        ...

    def __enter__(self) -> Record:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            self.status = Status.FAILED
        self.close()

    def __repr__(self) -> str:
        return f"Record(id={self.id!r}, title={self.title!r}, status={self.status!r})"

    def _mark_dirty(self) -> None: ...
    def _save_to_buffer(self) -> None: ...
```

### 1.8 認証・チーム管理 [R18, R19]

```python
# src/labvault/core/auth.py
from __future__ import annotations

from typing import Any


class AuthManager:
    """GCP認証管理。

    認証解決順序:
    1. GCP Application Default Credentials (ADC)
    2. サービスアカウントキーファイル（LABVAULT_SA_KEY_FILE 環境変数）
    3. 設定ファイル（~/.labvault/config.toml の credentials セクション）

    チーム内ロール:
    - admin: テンプレート管理、メンバー管理、完全削除（hard delete）
    - member: レコードのCRUD、自レコードの削除（soft delete）
    """

    def __init__(self, settings: Settings) -> None: ...

    def authenticate(self) -> Any:
        """認証を実行。成功時はCredentialsオブジェクトを返す。

        Raises:
            AuthError: 全認証方式が失敗した場合
        """
        ...

    def get_current_user(self) -> str:
        """現在の認証済みユーザー名/メールを返す。"""
        ...

    def get_role(self, team_id: str) -> str:
        """現在のユーザーのチーム内ロールを返す。

        Returns:
            "admin" | "member"

        Raises:
            AuthError: チームに所属していない場合
        """
        ...

    def require_admin(self, team_id: str) -> None:
        """admin権限を要求。admin以外はPermissionErrorを送出。"""
        ...
```

### 1.9 AutoLogger（CellTracker）

```python
# src/labvault/tracking/cell_tracker.py
from __future__ import annotations

import contextlib
from typing import Any, Iterator, TYPE_CHECKING

from ..core.types import CellLog

if TYPE_CHECKING:
    from ..buffer.local import LocalBuffer
    from ..core.record import Record


class CellTracker:
    """IPython hooks による全セル自動記録。Lab.new() 内部で自動インスタンス化。"""

    def __init__(
        self,
        record: Record,
        buffer: LocalBuffer,
        *,
        max_source_length: int = 10_000,
        max_result_length: int = 1_000,
        max_var_repr_length: int = 500,
        skip_empty_cells: bool = True,
        skip_magic_cells: bool = True,
        excluded_vars: set[str] | None = None,
        excluded_patterns: list[str] | None = None,
    ) -> None: ...

    # --- 制御 ---

    def activate(self) -> None:
        """IPython hooks を登録して自動記録を開始。"""
        ...

    def deactivate(self) -> None:
        """IPython hooks を解除して自動記録を停止。"""
        ...

    def pause(self) -> None: ...
    def resume(self) -> None: ...

    @contextlib.contextmanager
    def paused(self) -> Iterator[None]:
        """コンテキストマネージャで一時停止。"""
        ...

    @property
    def is_active(self) -> bool: ...

    @property
    def cell_count(self) -> int: ...

    # --- フィルタ ---

    def exclude_vars(self, *names: str) -> None: ...
    def exclude_patterns(self, *patterns: str) -> None: ...

    # --- 内部（IPython event handlers） ---

    def _pre_run_cell(self, info: Any) -> None: ...
    def _post_run_cell(self, result: Any) -> None: ...
```

### 1.10 Tracker（@exp.track デコレータ）

```python
# src/labvault/tracking/tracker.py
from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class Tracker:
    """@exp.track デコレータ。スクリプト(.py)用。"""

    def __init__(self, record: Any, buffer: Any) -> None: ...
    def __call__(self, func: F) -> F: ...
```

### 1.11 LocalBuffer

```python
# src/labvault/buffer/local.py
from __future__ import annotations

from pathlib import Path
from typing import Any


class LocalBuffer:
    """SQLite WALモードのローカルバッファ。

    ディレクトリ構造::

        ~/.labvault/buffer/
        ├── buffer.db          # SQLite
        └── files/
            └── {record_id}/
                └── {filename}
    """

    DEFAULT_DIR: Path = Path.home() / ".labvault" / "buffer"

    def __init__(
        self,
        buffer_dir: str | Path | None = None,
        *,
        max_size_mb: int = 500,
        retention_days: int = 30,
    ) -> None: ...

    # --- 書き込み（ノンブロッキング） ---

    def save_record(self, record_data: dict[str, Any]) -> None: ...
    def save_cell_log(self, cell_log: CellLog) -> None: ...
    def save_file(self, record_id: str, name: str, data: bytes, content_type: str = "") -> str: ...

    # --- 読み出し ---

    def get_unsynced_records(self) -> list[dict[str, Any]]: ...
    def get_unsynced_cell_logs(self, record_id: str) -> list[dict[str, Any]]: ...
    def get_unsynced_files(self) -> list[dict[str, Any]]: ...
    def get_record(self, record_id: str) -> dict[str, Any] | None: ...

    # --- 同期マーク ---

    def mark_synced(self, table: str, ids: list[str]) -> None: ...

    # --- ライフサイクル ---

    def cleanup(self) -> None: ...
    def get_buffer_size_mb(self) -> float: ...
    def close(self) -> None: ...
```

### 1.12 SyncManager

```python
# src/labvault/buffer/sync.py
from __future__ import annotations
from typing import Any


class SyncManager:
    """ローカルバッファ → リモート（Firestore + Nextcloud）同期。"""

    def __init__(
        self,
        buffer: LocalBuffer,
        metadata_backend: MetadataBackend,
        storage_backend: StorageBackend,
        *,
        sync_interval_sec: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ) -> None: ...

    def start(self) -> None: ...
    def stop(self) -> None: ...

    def sync_now(self) -> dict[str, int]:
        """即時同期。Returns: {"records", "cell_logs", "files", "errors"}"""
        ...

    @property
    def last_sync(self) -> float | None: ...
```

### 1.13 serialize_value

```python
# src/labvault/tracking/serializers.py
from __future__ import annotations
from typing import Any


def serialize_value(value: Any, *, max_repr_length: int = 500) -> Any:
    """変数の値をJSON互換の形に変換。

    変換ルール:
      - int, float, bool, None, str  → そのまま
      - list（要素10以下）           → 再帰的にシリアライズ
      - dict（キー10以下）           → 再帰的にシリアライズ
      - numpy.ndarray                → {"__type__": "ndarray", "shape": [...], "dtype": str, "min": ..., "max": ..., "mean": ...}
      - pandas.DataFrame             → {"__type__": "DataFrame", "shape": [...], "columns": [...], "dtypes": {...}}
      - matplotlib.Figure            → {"__type__": "Figure", "axes_count": int}
      - 大きなコレクション            → {"__type__": "list", "length": int, "first_3": [...]}
      - その他                        → repr()[:max_repr_length]
    """
    ...


def _summarize_ndarray(arr: Any) -> dict[str, Any]:
    """NumPy配列の統計要約。shape, dtype, min, max, mean, std, nbytes。"""
    ...


def _summarize_dataframe(df: Any) -> dict[str, Any]:
    """DataFrameの要約。shape, columns, dtypes, describe()サマリー。"""
    ...


def _is_sensitive(name: str) -> bool:
    """変数名が機微情報かどうか判定。

    マッチパターン:
      - *password*, *passwd*
      - *secret*
      - *token*
      - *api_key*, *apikey*
      - *credential*
      - *private_key*
      - *access_key*, *secret_key*
      - LABVAULT_*, AWS_*, GCP_*, AZURE_*
    """
    ...
```

### 1.14 CLI コマンド一覧

```python
# src/labvault/cli/main.py
import click


@click.group()
def cli() -> None:
    """labvault — 実験データ管理CLI"""
    ...


@cli.command()
def init() -> None:
    """初回セットアップ（チーム名、認証設定を対話的に入力）。"""
    ...


@cli.command()
@click.argument("title")
@click.option("--template", "-t", default=None)
@click.option("--tags", "-T", multiple=True)
def new(title: str, template: str | None, tags: tuple[str, ...]) -> None:
    """レコード作成。"""
    ...


@cli.command("list")
@click.option("--tags", "-T", multiple=True)
@click.option("--status", "-s", default=None)
@click.option("--limit", "-n", default=20)
def list_cmd(tags: tuple[str, ...], status: str | None, limit: int) -> None:
    """レコード一覧。"""
    ...


@cli.command()
@click.argument("record_id")
def show(record_id: str) -> None:
    """レコード詳細表示。"""
    ...


@cli.command()
@click.argument("record_id")
@click.argument("file_path", type=click.Path(exists=True))
def add(record_id: str, file_path: str) -> None:
    """ファイル追加。"""
    ...


@cli.command()
@click.argument("query")
@click.option("--limit", "-n", default=10)
def search(query: str, limit: int) -> None:
    """検索。"""
    ...


@cli.command()
@click.argument("record_id")
@click.argument("text")
def note(record_id: str, text: str) -> None:
    """メモ追加。"""
    ...


@cli.command()
@click.argument("record_id")
@click.argument("tags", nargs=-1)
def tag(record_id: str, tags: tuple[str, ...]) -> None:
    """タグ追加。"""
    ...


@cli.command()
@click.argument("record_id")
def url(record_id: str) -> None:
    """NextcloudのURL表示。"""
    ...


@cli.command()
@click.argument("output_dir", type=click.Path())
def export(output_dir: str) -> None:
    """全データエクスポート。"""
    ...


@cli.command("sync")
def sync_cmd() -> None:
    """手動同期。"""
    ...


@cli.command("sync-status")
def sync_status() -> None:
    """同期ステータス表示。"""
    ...


@cli.command("team")
def team_info() -> None:
    """チーム情報表示。"""
    ...


@cli.command("team-invite")
@click.argument("email")
@click.option("--role", "-r", default="member")
def team_invite(email: str, role: str) -> None:
    """チームにメンバー招待。"""
    ...
```

---

## 2. Firestoreドキュメント構造

### 2.1 完全スキーマ

```
teams/{team_id}                           # ドキュメント
  ├── name: string
  ├── created_at: timestamp
  ├── created_by: string                  # チーム作成者
  ├── nextcloud_group_folder: string
  ├── members: map<string, string>        # {"email": "admin" | "member"}
  │
  ├── records/{record_id}                 # ドキュメント（4文字 Crockford Base32）
  │     ├── id: string
  │     ├── title: string
  │     ├── type: string                  # "experiment" | "sample" | "process" | ...
  │     ├── status: string                # "running" | "success" | "failed" | "partial"
  │     ├── tags: array<string>
  │     ├── created_by: string
  │     ├── created_at: timestamp
  │     ├── updated_at: timestamp
  │     ├── deleted_at: timestamp | null
  │     ├── visibility: string            # "team" | "private"
  │     │
  │     ├── conditions: map<string, any>
  │     ├── results: map<string, any>
  │     ├── notes: array<map>             # [{text, created_at, author}]
  │     ├── data_refs: map<string, map>   # ファイル名 → メタデータ
  │     ├── external_refs: array<map>     # 大容量データ参照
  │     ├── parent_id: string | null
  │     ├── links: array<map>
  │     ├── template_used: string | null
  │     ├── embedding: vector(768)
  │     │
  │     ├── cell_logs/{cell_id}           # IPython hooks 自動記録
  │     ├── analyses/{analysis_id}        # LLM execute_code 結果
  │     └── traces/{trace_id}             # @exp.track 関数トレース
  │
  └── templates/{template_name}           # テンプレート
        ├── name, type, description
        ├── default_tags, default_conditions
        ├── recommended_results
        └── created_at
```

### 2.2 Nextcloud上のディレクトリ構造

```
{group_folder}/labvault/{team_id}/{record_id}/
├── data/
│   ├── xrd_data.csv
│   └── sem_50000x.tiff
├── _preview/                             # 自動処理トリガーで生成
│   ├── sem_50000x_thumb.jpg
│   └── xrd_data_preview.json
└── analyses/                             # execute_code 結果
    └── AN7K_fit_plot.png
```

---

## 3. ローカルバッファ実装仕様

### 3.1 SQLiteテーブル定義

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

CREATE TABLE IF NOT EXISTS records (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,           -- JSON serialized Record.to_dict()
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cell_logs (
    cell_id     TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    data        TEXT NOT NULL,
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS data_files (
    id          TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    local_path  TEXT NOT NULL,
    content_type TEXT DEFAULT '',
    size_bytes  INTEGER DEFAULT 0,
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS traces (
    trace_id    TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    data        TEXT NOT NULL,
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_status (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_synced ON records(synced);
CREATE INDEX IF NOT EXISTS idx_cell_logs_record ON cell_logs(record_id);
CREATE INDEX IF NOT EXISTS idx_cell_logs_synced ON cell_logs(synced);
CREATE INDEX IF NOT EXISTS idx_data_files_synced ON data_files(synced);
CREATE INDEX IF NOT EXISTS idx_traces_synced ON traces(synced);
```

### 3.2 ファイルシステム構造

```
~/.labvault/
├── config.toml                # 設定ファイル
└── buffer/
    ├── buffer.db              # SQLite WALモードDB
    └── files/                 # バイナリファイル実体
        └── {record_id}/
            └── {filename}
```

### 3.3 同期ロジック

1. `records` テーブルから `synced=0` を取得 → Firestoreに create/update（Last-Write-Wins）
2. `cell_logs` テーブルから `synced=0` を取得 → Firestore `cell_logs/{cell_id}` に保存（冪等）
3. `data_files` テーブルから `synced=0` を取得 → Nextcloudにアップロード → Firestore `data_refs` 更新
4. `traces` テーブルから `synced=0` を取得 → Firestore `traces/{trace_id}` に保存

各ステップで指数バックオフリトライ（最大3回、base=2秒）。

### 3.4 コンフリクト解決

| データ種別 | 戦略 | 理由 |
|-----------|------|------|
| メタデータ | Last-Write-Wins (updated_at) | 後勝ち |
| notes | マージ（union、created_at でソート） | 追記型 |
| tags | set union | 両方のタグを結合 |
| cell_logs | cell_id ユニーク → 衝突なし | 冪等 |
| data_files | 同名は後勝ち | 名前衝突稀 |

---

## 4. IPython hooks実装仕様

### 4.1 フック登録/解除のライフサイクル

```
Lab.new(title, auto_log=True)
  ├── Record を生成
  ├── IPython 検出: ip = get_ipython()
  ├── ip is not None → CellTracker(record, buffer).activate()
  │   ├── ip.events.register("pre_run_cell", tracker._pre_run_cell)
  │   └── ip.events.register("post_run_cell", tracker._post_run_cell)
  └── ip is None → warnings.warn("IPython環境ではない")

Record.close()
  └── tracker.deactivate()
      ├── ip.events.unregister("pre_run_cell", ...)
      └── ip.events.unregister("post_run_cell", ...)
```

### 4.2 namespace diff アルゴリズム

- `_pre_run_cell`: `ip.user_ns` の全キーについて `id(v)` + `hash(v)` をスナップショット
- `_post_run_cell`: diff計算 → new_vars / changed_vars / deleted_vars を検出
- 変更検出: `id()` が変わった or `hash()` が変わった場合

### 4.3 フィルタリング（除外ルール）

| ルール | 例 | 理由 |
|--------|---|------|
| `_` で始まる | `_temp`, `__name__` | 内部変数 |
| IPython内部変数 | `In`, `Out`, `get_ipython` | システム変数 |
| モジュール | `np`, `pd` | types.ModuleType |
| 関数/クラス定義 | `def f(): ...` | types.FunctionType |
| 機微情報 | `password`, `api_key`, `token`, `secret` | セキュリティ |
| ユーザー除外 | `exp.auto_log.exclude_vars("large_obj")` | 明示指定 |
| パターン除外 | `exp.auto_log.exclude_patterns("*_cache")` | fnmatch |

### 4.4 機微情報フィルタ 完全パターンリスト

```python
SENSITIVE_PATTERNS = [
    "*password*", "*passwd*",
    "*secret*",
    "*token*",
    "*api_key*", "*apikey*",
    "*credential*", "*cred_*",
    "*private_key*", "*privkey*",
    "*access_key*", "*secret_key*",
    "*auth*",
    "*connection_string*", "*conn_str*",
]

SENSITIVE_PREFIXES = [
    "LABVAULT_", "AWS_", "GCP_", "AZURE_",
    "GOOGLE_", "OPENAI_", "ANTHROPIC_",
]

# 型ベースフィルタ
SENSITIVE_TYPES = [
    "pydantic_settings.BaseSettings",  # Settings インスタンス
    "os._Environ",                     # os.environ
]
```

マスク値: `"***REDACTED***"`

### 4.5 バッファリング戦略

- CellLog → LocalBuffer（SQLite WAL、書き込みキュー経由、ノンブロッキング ~0.5ms）
- LocalBuffer → Firestore（SyncManager、30秒間隔 or `lab.sync()` で即時）
- パフォーマンス目標: pre+post 合計 ~1.5-6ms / セル

---

## 5. 自動処理トリガー実装仕様

| カテゴリ | 前処理内容 | 生成物 |
|---------|-----------|--------|
| image | サムネイル256x256 + プレビュー1024x1024 | `_preview/{name}_thumb.jpg`, `_preview/{name}_preview.jpg` |
| numpy | 統計サマリー（shape, dtype, min, max, mean, std） | `_preview/{name}_stats.json` |
| csv | カラム名・行数・先頭5行・基本統計 | `_preview/{name}_preview.json` |
| notebook | セル一覧・出力サマリー | `_preview/{name}_summary.json` |
| instrument | ファイルサイズ・フォーマット情報 | `_preview/{name}_meta.json` |

Phase 1: SDK内蔵（`Record.add()` 直後に同一プロセスで実行）
Phase 2: Cloud Functions トリガー（Firestore `data_refs` 更新検知）

---

## 6. pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "labvault"
version = "0.1.0"
description = "実験データ管理SDK — Notebook全セル自動記録 + LLMネイティブ"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [{ name = "Konishi Lab" }]
keywords = ["experiment", "data-management", "jupyter", "llm", "materials-science"]

dependencies = [
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "click>=8.1",
    "rich>=13.0",
]

[project.optional-dependencies]
gcp = [
    "google-cloud-firestore>=2.16",
    "google-cloud-aiplatform>=1.50",
    "google-auth>=2.29",
]
nextcloud = ["nc-py-api>=0.19"]
numpy = ["numpy>=1.24"]
preview = ["Pillow>=10.0", "numpy>=1.24"]
all = ["labvault[gcp,nextcloud,numpy,preview]"]
dev = [
    "pytest>=8.1",
    "pytest-cov>=5.0",
    "pytest-timeout>=2.3",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.10",
    "ipython>=8.0",
]

[project.scripts]
labvault = "labvault.cli.main:cli"

[project.urls]
Homepage = "https://github.com/konishi-lab/labvault"
Repository = "https://github.com/konishi-lab/labvault"

[tool.hatch.build.targets.wheel]
packages = ["src/labvault"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=labvault --cov-report=term-missing -v --timeout=30"
markers = [
    "integration: Firestore/Nextcloud接続が必要なテスト",
    "slow: 実行に時間がかかるテスト",
]

[tool.ruff]
target-version = "py310"
line-length = 120
select = ["E", "F", "I", "W", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.10"
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = true
```

---

## 7. テストケース一覧

### 7.1 test_core/test_id.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_generate_id_length` | 指定長のIDが生成される |
| `test_generate_id_alphabet` | Crockford Base32の文字のみ含む |
| `test_generate_id_uniqueness` | 1000個生成して重複なし |
| `test_normalize_id_uppercase` | 小文字→大文字変換 |
| `test_normalize_id_confusable` | O→0, I→1, L→1 変換 |

### 7.2 test_core/test_lab.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_new_creates_record` | lab.new() でRecordが返る、IDが4文字 |
| `test_new_with_conditions` | **conditions がRecordに設定される |
| `test_new_with_template` | テンプレート適用でタグ・条件がデフォルト設定 |
| `test_get_existing` | lab.get(id) で取得可能 |
| `test_get_nonexistent` | RecordNotFoundError が発生 |
| `test_get_normalize_id` | 小文字ID、O/I入力でも取得可能 |
| `test_list_filter_tags` | タグフィルタ |
| `test_list_filter_status` | ステータスフィルタ |
| `test_search_text` | テキスト検索 |
| `test_recent` | 最新N件が新しい順 |
| `test_delete_soft` | ソフトデリート |
| `test_trash_and_restore` | ゴミ箱一覧と復元 |
| `test_create_team` | チーム作成 |
| `test_invite_member` | メンバー招待 |
| `test_invite_requires_admin` | 非adminは PermissionError |
| `test_set_role` | ロール変更 |
| `test_team_info` | チーム情報取得 |
| `test_context_manager` | with Lab() as lab: が動く |

### 7.3 test_core/test_record.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_conditions_sets_values` | conditions()で値が設定される |
| `test_conditions_method_chain` | conditions() が self を返す |
| `test_results_setitem` | results["key"] = value が動く |
| `test_tag_add` | tag() でタグ追加 |
| `test_tag_duplicate_ignored` | 同じタグを2回追加しても1つ |
| `test_untag` | untag() でタグ削除 |
| `test_note_add` | note() でメモ追加 |
| `test_status_setter` | status = "success" で変更 |
| `test_add_file_path` | add(path) でファイルがバッファに保存 |
| `test_add_bytes` | add(bytes, name=...) が動く |
| `test_save_dict_as_json` | save(name, dict) → JSON保存 |
| `test_save_ndarray_as_npy` | save(name, ndarray) → npy保存 |
| `test_add_ref` | add_ref() で外部参照登録 |
| `test_sub_creates_child` | sub() で子レコード作成 |
| `test_sub_has_parent_id` | 子レコードのparent_idが親ID |
| `test_link` | link() でリンク作成 |
| `test_to_dict_roundtrip` | to_dict() → from_dict() が復元 |
| `test_close_sets_success` | close() でstatus=success |
| `test_context_manager_error` | 例外時 status=failed |
| `test_method_chain` | tag().conditions().note() が連鎖 |

### 7.4 test_tracking/test_cell_tracker.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_hooks_registered` | activate() 後に is_active == True |
| `test_new_vars_detected` | 新しい変数が new_vars に入る |
| `test_changed_vars_detected` | 変更された変数が changed_vars に入る |
| `test_pause_resume` | pause中はログされない |
| `test_sensitive_vars_excluded` | password, api_key が記録されない |
| `test_module_vars_excluded` | import np の np が記録されない |
| `test_magic_commands_skipped` | %who 等がスキップされる |
| `test_exclude_vars` | exclude_vars() で指定変数が除外 |
| `test_exclude_patterns` | exclude_patterns("*_cache") が動く |

### 7.5 test_buffer/test_local_buffer.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_save_record` | save_record → get_unsynced_records |
| `test_save_cell_log` | save_cell_log → get_unsynced_cell_logs |
| `test_save_file` | save_file でローカルファイルが作成される |
| `test_mark_synced` | mark_synced 後に unsynced から消える |
| `test_cleanup` | cleanup で古い同期済みデータが削除される |
| `test_concurrent_writes` | 複数の連続書き込みが欠損しない |

### 7.6 test_integration/test_full_flow.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_notebook_flow` | Lab.new → セル実行 → CellLog確認 → close |
| `test_script_flow` | Lab.new(auto_log=False) → @track → close |
| `test_multi_pc_flow` | lab.new → lab.get(id) → add → 紐付け確認 |
| `test_child_record_flow` | exp.sub() → 子にadd → 親から children() |
| `test_offline_then_sync` | バッファ書き込み → sync() → バックエンド確認 |

---

## 8. M0-M4 Issue一覧

### M0: 基盤セットアップ + POC（Week 1-2）

| Issue | 受け入れ条件 | 要件 |
|-------|------------|------|
| M0-1: GCPプロジェクトセットアップ | Firestoreにドキュメント読み書き可能 | R01 |
| M0-2: SDKリポジトリ刷新 | `pip install -e .` + `pytest` 通過。`src/labvault/` 構造 | R07 |
| M0-3: POC — Firestore Vector Search | 10K件 <200ms | R14 |
| M0-4: POC — Vertex AI Embedding日本語品質 | 類似実験が上位3件 | R14 |
| M0-5: POC — MCP接続 | Claude Desktopから接続確認 | R15 |
| M0-6: POC — Nextcloud速度 | 10MB/s以上 | R01 |

### M1: SDK Core（Week 2-4）

| Issue | 受け入れ条件 | 要件 |
|-------|------------|------|
| M1-1: IDジェネレーター | test_id.py 全通過 | R03 |
| M1-2: 型定義 | test_types.py 全通過 | R05 |
| M1-3: 例外クラス | LabvaultError等 定義 | R07 |
| M1-4: Settings | 環境変数/config.toml/デフォルト 読み込み | R07 |
| M1-5: Backend Protocol | MetadataBackend, StorageBackend, SearchBackend 定義 | R07 |
| M1-6: InMemoryBackend | test_memory.py 全通過 | R07 |
| M1-7: Recordクラス | test_record.py 全通過 | R02-R06 |
| M1-8: Labクラス | test_lab.py 全通過 | R01, R07 |
| M1-9: LocalBuffer | test_local_buffer.py 全通過 | R08 |
| M1-10: SyncManager | test_sync.py 全通過 | R08 |
| M1-11: serialize_value | test_serializers.py 全通過 | R13 |
| M1-12: CellTracker | test_cell_tracker.py 全通過 | R13 |
| M1-13: @exp.track | test_tracker.py 全通過 | R13 |
| M1-14: exp.snapshot() | test_snapshot.py 全通過 | R13 |
| M1-15: 認証・チーム管理 | create_team, invite, set_role, team_info 動作 | R18, R19 |
| M1-16: 統合テスト | test_full_flow.py 全通過、カバレッジ80%以上 | 全体 |

### M2: Embedding + Vector Search（Week 4-5）

| Issue | 受け入れ条件 | 要件 |
|-------|------------|------|
| M2-1: EmbeddingService | 日本語実験記述 → 768次元ベクトル生成 | R14 |
| M2-2: Firestore Vector Search統合 | lab.search("クエリ") でセマンティック検索動作 | R14 |
| M2-3: 自動Embedding生成 | Record作成/更新時に自動生成 | R14 |

### M3: MCPサーバー + CLI（Week 5-7）

| Issue | 受け入れ条件 | 要件 |
|-------|------------|------|
| M3-1: CLIコマンド | `labvault --help` + 全コマンド動作 | R10 |
| M3-2: MCPサーバー Core | Claude Desktopから接続確認 | R15 |
| M3-3: MCPツール11個 | 検索・閲覧全ツールのテスト通過 | R15 |
| M3-4: Claude Desktop接続ガイド | 新規ユーザーが接続可能 | R15 |

### M4: Firestore/Nextcloud本番実装（Week 6-7）

| Issue | 受け入れ条件 | 要件 |
|-------|------------|------|
| M4-1: FirestoreBackend | 実Firestoreで全CRUD動作 | R01 |
| M4-2: NextcloudStorage | 実Nextcloudでアップロード/ダウンロード動作 | R01 |
| M4-3: 自動処理トリガー Phase 1 | 画像→サムネイル、CSV→プレビュー生成 | R12 |
| M4-4: MVP統合テスト | フルフロー + チームメンバー2名利用テスト | 全体 |
