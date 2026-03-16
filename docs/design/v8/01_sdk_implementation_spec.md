# v8 SDK実装仕様書

> v7設計 + REQUIREMENTS を統合した、**コードを書き始められるレベル**の実装仕様。
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
# src/mdxdb/core/config.py
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """SDK設定。環境変数 → ~/.mdxdb/config.toml → デフォルト の順で解決。"""

    model_config = SettingsConfigDict(
        env_prefix="MDXDB_",
        toml_file=Path.home() / ".mdxdb" / "config.toml",
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
    buffer_dir: Path = Path.home() / ".mdxdb" / "buffer"
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
# src/mdxdb/core/types.py
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "record_id": self.record_id,
            "name": self.name,
            "code": self.code,
            "input_files": self.input_files,
            "input_analyses": self.input_analyses,
            "results": self.results,
            "images": self.images,
            "executed_at": self.executed_at.isoformat(),
            "executed_by": self.executed_by,
            "prompt": self.prompt,
            "duration_sec": self.duration_sec,
            "packages": self.packages,
        }
```

### 1.3 IDジェネレーター

```python
# src/mdxdb/core/id.py
from __future__ import annotations

import secrets
import string

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
    """入力IDを正規化。小文字→大文字、O→0, I/L→1 に変換。

    Args:
        raw: ユーザー入力のID文字列

    Returns:
        正規化された大文字ID
    """
    table = str.maketrans("oilOIL", "011011")
    return raw.upper().translate(table)
```

### 1.4 例外

```python
# src/mdxdb/core/exceptions.py
class MdxdbError(Exception):
    """SDK基底例外。"""


class RecordNotFoundError(MdxdbError):
    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        super().__init__(f"Record not found: {record_id}")


class SyncError(MdxdbError):
    """同期失敗。"""


class BackendError(MdxdbError):
    """バックエンド操作失敗。"""


class ValidationError(MdxdbError):
    """バリデーションエラー。"""
```

### 1.5 Backend Protocol

```python
# src/mdxdb/backends/base.py
from __future__ import annotations

from typing import Any, Protocol, Sequence


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
    def get_cell_logs(
        self, record_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]: ...

    # 解析履歴
    def save_analysis(self, record_id: str, data: dict[str, Any]) -> None: ...
    def get_analyses(self, record_id: str) -> list[dict[str, Any]]: ...

    # テンプレート
    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None: ...
    def get_template(self, team: str, name: str) -> dict[str, Any] | None: ...
    def list_templates(self, team: str) -> list[dict[str, Any]]: ...


# src/mdxdb/storage/base.py
class StorageBackend(Protocol):
    """バイナリストレージの抽象。Nextcloud / InMemory / LocalFS。"""

    def upload(self, path: str, data: bytes, content_type: str = "") -> str:
        """アップロード。戻り値はストレージ上のパス。"""
        ...

    def download(self, path: str) -> bytes: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def get_share_url(self, path: str) -> str: ...
    def list_files(self, prefix: str) -> list[str]: ...


# src/mdxdb/search/base.py
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
# src/mdxdb/core/lab.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .exceptions import RecordNotFoundError
from .id import generate_id, normalize_id
from .record import Record
from .types import RecordType, Status


class Lab:
    """研究室のデータベース接続。SDKのエントリーポイント。

    使い方（Notebook）::

        from mdxdb import Lab
        lab = Lab("konishi-lab")
        exp = lab.new("XRD解析")
        # ← 以降の全セル実行が自動記録

    使い方（スクリプト）::

        lab = Lab("konishi-lab")
        exp = lab.new("XRD解析", auto_log=False)
        @exp.track
        def process(): ...
    """

    # ------------------------------------------------------------------
    # 初期化
    # ------------------------------------------------------------------

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
        """
        Args:
            team: チーム名。省略時は Settings から読む。
            user: ユーザー名。省略時は Settings / 環境変数。
            metadata_backend: 省略時は InMemoryMetadataBackend。
            storage_backend: 省略時は InMemoryStorageBackend。
            search_backend: 省略時は InMemorySearchBackend。
            buffer_dir: ローカルバッファのディレクトリ。
            auto_sync: バックグラウンド同期を有効にするか。
            sync_interval: 同期間隔（秒）。
        """
        ...

    # ------------------------------------------------------------------
    # プロパティ
    # ------------------------------------------------------------------

    @property
    def team(self) -> str: ...

    @property
    def user(self) -> str: ...

    # ------------------------------------------------------------------
    # レコード CRUD
    # ------------------------------------------------------------------

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
        """新しいレコードを作成。

        Args:
            title: レコードタイトル
            type: レコード種別
            template: テンプレート名（"XRD", "SEM" 等）
            tags: 初期タグ
            sample: サンプル名（conditions に sample として追加）
            auto_log: IPython hooks を有効にするか
            **conditions: 実験条件キーワード引数

        Returns:
            Record: 作成されたレコード（ID自動生成済み）
        """
        ...

    def get(self, record_id: str) -> Record:
        """IDでレコード取得。ローカルバッファ→リモートの順。

        Args:
            record_id: 4文字ID（大文字小文字不問、O→0, I→1 自動変換）

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
        """テキスト検索。セマンティック検索対応（M2以降）。

        Args:
            query: 検索テキスト（"結晶性が良い薄膜" 等）
        """
        ...

    def recent(self, n: int = 10) -> list[Record]:
        """最新 n 件を取得。"""
        ...

    def today(self) -> list[Record]:
        """今日作成されたレコード一覧。"""
        ...

    def delete(self, record_id: str, *, hard: bool = False) -> None:
        """削除（デフォルトはソフトデリート = ゴミ箱移動）。

        Args:
            record_id: 対象ID
            hard: True の場合は完全削除（管理者のみ）
        """
        ...

    # ------------------------------------------------------------------
    # テンプレート
    # ------------------------------------------------------------------

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
        """テンプレート定義をチームに保存。

        Args:
            name: テンプレート名（"XRD", "SEM" 等）
            type: デフォルトのレコード種別
            default_tags: 自動付与するタグ
            default_conditions: デフォルト条件値
            recommended_results: 結果として記録を推奨するキー名
            description: テンプレートの説明
        """
        ...

    def templates(self) -> list[dict[str, Any]]:
        """チームのテンプレート一覧。"""
        ...

    # ------------------------------------------------------------------
    # 同期
    # ------------------------------------------------------------------

    def sync(self) -> dict[str, int]:
        """手動で即座に同期実行。

        Returns:
            {"records": int, "cell_logs": int, "files": int, "errors": int}
        """
        ...

    @property
    def sync_status(self) -> dict[str, Any]:
        """同期ステータス。

        Returns:
            {
                "buffer_size_mb": float,
                "unsynced_records": int,
                "unsynced_files": int,
                "last_sync": float | None,  # Unix timestamp
            }
        """
        ...

    # ------------------------------------------------------------------
    # エクスポート
    # ------------------------------------------------------------------

    def export(self, output_dir: str | Path) -> Path:
        """全データをローカルにエクスポート（JSON Lines + ファイル）。

        Args:
            output_dir: 出力先ディレクトリ

        Returns:
            出力ディレクトリのPath
        """
        ...

    # ------------------------------------------------------------------
    # ストレージ使用量
    # ------------------------------------------------------------------

    def storage_usage(self) -> dict[str, Any]:
        """Nextcloudストレージ使用量。

        Returns:
            {"used_gb": float, "total_gb": float, "record_count": int}
        """
        ...

    # ------------------------------------------------------------------
    # ライフサイクル
    # ------------------------------------------------------------------

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
# src/mdxdb/core/record.py
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

    def __init__(self, record: Record) -> None:
        self._record = record
        self._data: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._record._mark_dirty()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return repr(self._data)

    def keys(self) -> Any:
        return self._data.keys()

    def values(self) -> Any:
        return self._data.values()

    def items(self) -> Any:
        return self._data.items()

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)

    def update(self, data: dict[str, Any]) -> None:
        self._data.update(data)
        self._record._mark_dirty()


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

    # ------------------------------------------------------------------
    # プロパティ（読み取り専用）
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # プロパティ（読み書き）
    # ------------------------------------------------------------------

    @property
    def status(self) -> str: ...

    @status.setter
    def status(self, value: str | Status) -> None:
        """ステータス変更。自動保存。"""
        ...

    @property
    def results(self) -> _ResultsProxy:
        """results["key"] = value で自動保存。"""
        ...

    # ------------------------------------------------------------------
    # 実験条件
    # ------------------------------------------------------------------

    def conditions(self, **kwargs: Any) -> Record:
        """実験条件を設定。メソッドチェーン対応。

        Args:
            **kwargs: 条件キーワード引数

        Returns:
            self（メソッドチェーン用）

        例::

            exp.conditions(temperature_C=500, pressure_Pa=1e-3, gas="Ar")
        """
        ...

    def get_conditions(self) -> dict[str, Any]:
        """現在の条件辞書を返す。"""
        ...

    # ------------------------------------------------------------------
    # タグ
    # ------------------------------------------------------------------

    def tag(self, *tags: str) -> Record:
        """タグ追加。メソッドチェーン対応。

        例::

            exp.tag("XRD", "Fe-Cr", "thin-film")
        """
        ...

    def untag(self, *tags: str) -> Record:
        """タグ削除。"""
        ...

    @property
    def tags(self) -> list[str]:
        """現在のタグ一覧。"""
        ...

    # ------------------------------------------------------------------
    # メモ
    # ------------------------------------------------------------------

    def note(self, text: str) -> Record:
        """メモ追加。メソッドチェーン対応。

        例::

            exp.note("結晶性良好。次回は温度を上げてみる")
        """
        ...

    @property
    def notes(self) -> list[Note]:
        """メモ一覧（時系列順）。"""
        ...

    # ------------------------------------------------------------------
    # データ追加（ファイル）
    # ------------------------------------------------------------------

    def add(
        self,
        source: str | Path | bytes,
        name: str | None = None,
        *,
        content_type: str = "",
    ) -> Record:
        """ファイルを追加。ローカルバッファ→Nextcloud。

        Args:
            source: ファイルパス or バイトデータ
            name: 保存名（省略時はファイル名）
            content_type: MIME type

        Returns:
            self

        例::

            exp.add("xrd_data.csv")
            exp.add("/path/to/sem_image.tiff")
            exp.add(b"raw bytes", name="data.bin")
        """
        ...

    def add_dir(self, dir_path: str | Path) -> Record:
        """ディレクトリ配下の全ファイルを再帰的に追加。

        Args:
            dir_path: ディレクトリパス
        """
        ...

    # ------------------------------------------------------------------
    # データ追加（型自動判定）
    # ------------------------------------------------------------------

    def save(self, name: str, data: Any) -> Record:
        """データを型自動判定で保存。

        型判定ルール:
          - dict / list         → JSON (.json)
          - str                 → テキスト (.txt)
          - numpy.ndarray       → NumPy (.npy) + _meta.json
          - matplotlib.Figure   → PNG (.png)
          - pandas.DataFrame    → CSV (.csv)
          - bytes               → バイナリ

        Args:
            name: ファイル名（拡張子自動付与）
            data: 保存するデータ

        Returns:
            self
        """
        ...

    # ------------------------------------------------------------------
    # データ取得
    # ------------------------------------------------------------------

    def get_data(self, name: str) -> bytes:
        """保存済みファイルのバイトデータを取得。"""
        ...

    def list_data(self) -> list[DataRef]:
        """保存済みファイル一覧。"""
        ...

    @property
    def nextcloud_url(self) -> str:
        """NextcloudのファイルブラウザURL。"""
        ...

    # ------------------------------------------------------------------
    # 外部参照（大容量データ）
    # ------------------------------------------------------------------

    def add_ref(
        self,
        path: str = "",
        *,
        location: str = "",
        size_gb: float | None = None,
        description: str = "",
        doi: str = "",
    ) -> Record:
        """外部データの参照のみ登録（転送しない）。

        Args:
            path: ファイルパス or URL
            location: データの所在 ("TSUBAME:/home/user/WAVECAR" 等)
            size_gb: サイズ（GB）
            description: 説明
            doi: DOI（外部リポジトリ）

        例::

            exp.add_ref(
                path="/hpc/scratch/WAVECAR",
                location="TSUBAME:/home/user/WAVECAR",
                size_gb=8.5,
                description="波動関数ファイル",
            )
            exp.add_ref(doi="10.5281/zenodo.12345")
        """
        ...

    # ------------------------------------------------------------------
    # 子レコード
    # ------------------------------------------------------------------

    def sub(
        self,
        title: str,
        *,
        type: str | RecordType = RecordType.MEASUREMENT,
        **conditions: Any,
    ) -> Record:
        """子レコード作成。

        Args:
            title: 子レコードのタイトル
            type: 種別
            **conditions: 条件

        Returns:
            子レコード（IDは別途自動生成）

        例::

            sem = exp.sub("SEM観察", type="measurement")
            sem.add("sem_50000x.tiff")
        """
        ...

    def children(self) -> list[Record]:
        """子レコード一覧。"""
        ...

    # ------------------------------------------------------------------
    # リンク
    # ------------------------------------------------------------------

    def link(self, target: str | Record, relation: str = "related_to", description: str = "") -> Record:
        """他レコードへのリンク。

        Args:
            target: 対象レコードID or Record
            relation: "derived_from", "related_to", "replaces"
            description: リンクの説明
        """
        ...

    # ------------------------------------------------------------------
    # 解析履歴
    # ------------------------------------------------------------------

    def analyses(
        self,
        *,
        name: str | None = None,
        id: str | None = None,
    ) -> list[Analysis]:
        """解析履歴の取得。

        Args:
            name: 名前でフィルタ（部分一致）
            id: IDで取得
        """
        ...

    # ------------------------------------------------------------------
    # 自動ログ制御
    # ------------------------------------------------------------------

    @property
    def auto_log(self) -> CellTracker | None:
        """CellTracker へのアクセス。

        例::

            exp.auto_log.pause()
            exp.auto_log.resume()
            exp.auto_log.deactivate()
        """
        ...

    def pause_logging(self) -> Record:
        """自動ログ一時停止のショートカット。"""
        ...

    def resume_logging(self) -> Record:
        """自動ログ再開のショートカット。"""
        ...

    # ------------------------------------------------------------------
    # @exp.track デコレータ（スクリプト用）
    # ------------------------------------------------------------------

    @property
    def track(self) -> Tracker:
        """関数デコレータ。

        例::

            @exp.track
            def process_xrd(data, cutoff=0.5):
                ...
        """
        ...

    def track_block(self, name: str = "") -> _TrackBlockContext:
        """ブロック単位のトラッキング。

        例::

            with exp.track_block("前処理"):
                filtered = apply_filter(data)
        """
        ...

    # ------------------------------------------------------------------
    # スナップショット（手動）
    # ------------------------------------------------------------------

    def snapshot(self, *, include: list[str] | None = None, exclude: list[str] | None = None) -> Record:
        """現在のローカル変数をスナップショット。

        Args:
            include: 記録する変数名リスト（省略時は全変数）
            exclude: 除外する変数名リスト

        例::

            cutoff = 0.5
            method = "butterworth"
            exp.snapshot()  # ← cutoff, method がキャプチャされる
        """
        ...

    # ------------------------------------------------------------------
    # シリアライズ
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Firestore保存用の辞書に変換。"""
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, _lab: Lab | None = None) -> Record:
        """辞書から復元。"""
        ...

    # ------------------------------------------------------------------
    # ライフサイクル
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _mark_dirty(self) -> None:
        """変更フラグを立てて、バッファに保存をスケジュール。"""
        ...

    def _save_to_buffer(self) -> None:
        """ローカルバッファに現在の状態を保存。"""
        ...
```

### 1.8 AutoLogger（CellTracker）

```python
# src/mdxdb/tracking/cell_tracker.py
from __future__ import annotations

import contextlib
import hashlib
import time
import warnings
from datetime import datetime
from typing import Any, Iterator, TYPE_CHECKING

from ..core.id import generate_id
from ..core.types import CellLog
from .serializers import serialize_value

if TYPE_CHECKING:
    from ..buffer.local import LocalBuffer
    from ..core.record import Record


class CellTracker:
    """IPython hooks による全セル自動記録。

    Lab.new() 内部で自動的にインスタンス化される。
    """

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
        """IPython hooks を登録して自動記録を開始。

        IPython環境でなければ UserWarning を出して何もしない。
        """
        ...

    def deactivate(self) -> None:
        """IPython hooks を解除して自動記録を停止。"""
        ...

    def pause(self) -> None:
        """一時停止。"""
        ...

    def resume(self) -> None:
        """再開。"""
        ...

    @contextlib.contextmanager
    def paused(self) -> Iterator[None]:
        """コンテキストマネージャで一時停止。

        例::

            with exp.auto_log.paused():
                password = "secret"
        """
        ...

    @property
    def is_active(self) -> bool: ...

    @property
    def cell_count(self) -> int:
        """記録したセル数。"""
        ...

    # --- フィルタ ---

    def exclude_vars(self, *names: str) -> None:
        """特定の変数名を除外。"""
        ...

    def exclude_patterns(self, *patterns: str) -> None:
        """fnmatch パターンで除外。"""
        ...

    # --- 内部（IPython event handlers） ---

    def _pre_run_cell(self, info: Any) -> None:
        """pre_run_cell フック。namespace スナップショット取得。"""
        ...

    def _post_run_cell(self, result: Any) -> None:
        """post_run_cell フック。diff計算 → CellLog → バッファ保存。"""
        ...
```

### 1.9 Tracker（@exp.track デコレータ）

```python
# src/mdxdb/tracking/tracker.py
from __future__ import annotations

import functools
import time
from typing import Any, Callable, TypeVar

from ..core.id import generate_id
from .serializers import serialize_value

F = TypeVar("F", bound=Callable[..., Any])


class Tracker:
    """@exp.track デコレータ。スクリプト(.py)用。

    例::

        @exp.track
        def process_xrd(data, cutoff=0.5):
            return filtered

        # → 自動記録: 関数名, 引数, 返り値, 実行時間, 環境
    """

    def __init__(self, record: Any, buffer: Any) -> None: ...

    def __call__(self, func: F) -> F:
        """デコレータとして使用。"""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # 1. 引数のシリアライズ
            # 2. 実行 + 計時
            # 3. 返り値のシリアライズ
            # 4. トレースをバッファに保存
            ...

        return wrapper  # type: ignore[return-value]
```

### 1.10 LocalBuffer

```python
# src/mdxdb/buffer/local.py
from __future__ import annotations

import json
import queue
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.id import generate_id


class LocalBuffer:
    """SQLite WALモードのローカルバッファ。

    ディレクトリ構造::

        ~/.mdxdb/buffer/
        ├── buffer.db          # SQLite
        └── files/
            └── {record_id}/
                └── {filename}
    """

    DEFAULT_DIR: Path = Path.home() / ".mdxdb" / "buffer"

    def __init__(
        self,
        buffer_dir: str | Path | None = None,
        *,
        max_size_mb: int = 500,
        retention_days: int = 30,
    ) -> None: ...

    # --- 書き込み（ノンブロッキング） ---

    def save_record(self, record_data: dict[str, Any]) -> None:
        """レコードメタデータをバッファに保存。"""
        ...

    def save_cell_log(self, cell_log: CellLog) -> None:
        """CellLogをバッファに保存。"""
        ...

    def save_file(
        self,
        record_id: str,
        name: str,
        data: bytes,
        content_type: str = "",
    ) -> str:
        """ファイルをローカルに保存。ローカルパスを返す。"""
        ...

    # --- 読み出し ---

    def get_unsynced_records(self) -> list[dict[str, Any]]: ...
    def get_unsynced_cell_logs(self, record_id: str) -> list[dict[str, Any]]: ...
    def get_unsynced_files(self) -> list[dict[str, Any]]: ...
    def get_record(self, record_id: str) -> dict[str, Any] | None: ...

    # --- 同期マーク ---

    def mark_synced(self, table: str, ids: list[str]) -> None: ...

    # --- ライフサイクル ---

    def cleanup(self) -> None:
        """同期済み + 保持期間超過データを削除。"""
        ...

    def get_buffer_size_mb(self) -> float: ...

    def close(self) -> None:
        """バッファを閉じる。書き込みスレッド停止。"""
        ...
```

### 1.11 SyncManager

```python
# src/mdxdb/buffer/sync.py
from __future__ import annotations

import threading
import time
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

    def start(self) -> None:
        """バックグラウンド同期開始（daemon スレッド）。"""
        ...

    def stop(self) -> None:
        """停止。"""
        ...

    def sync_now(self) -> dict[str, int]:
        """即時同期。

        Returns:
            {"records": int, "cell_logs": int, "files": int, "errors": int}
        """
        ...

    @property
    def last_sync(self) -> float | None:
        """最後の同期時刻（Unix timestamp）。"""
        ...
```

### 1.12 serialize_value

```python
# src/mdxdb/tracking/serializers.py
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
    """NumPy配列の統計要約。"""
    ...


def _summarize_dataframe(df: Any) -> dict[str, Any]:
    """DataFrameの要約。"""
    ...
```

### 1.13 CLI コマンド一覧

```python
# src/mdxdb/cli/main.py
import click


@click.group()
def cli() -> None:
    """mdxdb — 実験データ管理CLI"""
    ...


@cli.command()
def init() -> None:
    """初回セットアップ（チーム名、認証設定を対話的に入力）。"""
    ...


@cli.command()
@click.argument("title")
@click.option("--template", "-t", default=None, help="テンプレート名")
@click.option("--tags", "-T", multiple=True, help="タグ")
def new(title: str, template: str | None, tags: tuple[str, ...]) -> None:
    """レコード作成。"""
    ...


@cli.command()
@click.option("--tags", "-T", multiple=True)
@click.option("--status", "-s", default=None)
@click.option("--limit", "-n", default=20)
def list(tags: tuple[str, ...], status: str | None, limit: int) -> None:
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


@cli.command("buffer-clean")
def buffer_clean() -> None:
    """バッファクリーンアップ。"""
    ...


@cli.group("template")
def template_group() -> None:
    """テンプレート管理。"""
    ...


@template_group.command("list")
def template_list() -> None:
    """テンプレート一覧。"""
    ...


@template_group.command("create")
@click.argument("name")
def template_create(name: str) -> None:
    """テンプレート作成（対話的）。"""
    ...
```

---

## 2. Firestoreドキュメント構造

### 2.1 完全スキーマ

```
teams/{team_id}                           # ドキュメント
  ├── name: string
  ├── created_at: timestamp
  ├── members: map<string, role>          # {"user_id": "admin" | "member"}
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
  │     ├── deleted_at: timestamp | null  # ソフトデリート
  │     │
  │     ├── conditions: map<string, any>  # {"temperature_C": 500, "gas": "Ar"}
  │     ├── results: map<string, any>     # {"lattice_a": 2.873, "n_peaks": 12}
  │     │
  │     ├── notes: array<map>
  │     │     └── {text, created_at, author}
  │     │
  │     ├── data_refs: map<string, map>   # ファイル名 → メタデータ
  │     │     └── "xrd.csv": {
  │     │           nextcloud_path: string,
  │     │           content_type: string,
  │     │           size_bytes: number,
  │     │           sha256: string,
  │     │           preview_path: string | null
  │     │         }
  │     │
  │     ├── external_refs: array<map>     # 大容量データ参照
  │     │     └── {uri, location, size_bytes, description, doi}
  │     │
  │     ├── parent_id: string | null
  │     ├── links: array<map>
  │     │     └── {target_id, relation, description}
  │     │
  │     ├── template_used: string | null
  │     │
  │     ├── embedding: vector(768)        # Vertex AI text-embedding-004
  │     ├── summary: string               # Gemini Flash自動生成サマリー
  │     │
  │     │   # ===== サブコレクション =====
  │     │
  │     ├── cell_logs/{cell_id}           # IPython hooks 自動記録
  │     │     ├── cell_id: string
  │     │     ├── record_id: string
  │     │     ├── cell_number: number
  │     │     ├── execution_count: number
  │     │     ├── source: string          # セルのソースコード
  │     │     ├── source_hash: string
  │     │     ├── new_vars: map<string, any>
  │     │     ├── changed_vars: map<string, any>
  │     │     ├── deleted_vars: array<string>
  │     │     ├── result_repr: string | null
  │     │     ├── error: map | null       # {type, message}
  │     │     ├── duration_sec: number
  │     │     ├── executed_at: timestamp
  │     │     └── env: map                # 初回のみフル
  │     │
  │     ├── analyses/{analysis_id}        # LLM execute_code 結果
  │     │     ├── id: string              # Crockford Base32
  │     │     ├── name: string            # "gaussian_fit_001"
  │     │     ├── code: string            # Pythonコード全文
  │     │     ├── input_files: array<string>
  │     │     ├── input_analyses: array<string>  # 解析チェーン
  │     │     ├── results: map<string, any>
  │     │     ├── images: array<string>   # ファイル名
  │     │     ├── executed_at: timestamp
  │     │     ├── executed_by: string
  │     │     ├── prompt: string
  │     │     ├── duration_sec: number
  │     │     └── packages: map<string, string>
  │     │
  │     └── traces/{trace_id}             # @exp.track 関数トレース
  │           ├── function_name: string
  │           ├── args: map
  │           ├── kwargs: map
  │           ├── return_value: any
  │           ├── duration_sec: number
  │           ├── executed_at: timestamp
  │           └── env: map
  │
  └── templates/{template_name}           # ドキュメント
        ├── name: string
        ├── type: string
        ├── description: string
        ├── default_tags: array<string>
        ├── default_conditions: map
        ├── recommended_results: array<string>
        └── created_at: timestamp
```

### 2.2 Firestoreインデックス

```
# 複合インデックス（firestore.indexes.json）
[
  # レコード一覧（チーム内、更新順）
  { collection: "records", fields: ["deleted_at ASC", "updated_at DESC"] },

  # タグフィルタ
  { collection: "records", fields: ["deleted_at ASC", "tags ARRAY_CONTAINS", "updated_at DESC"] },

  # ステータスフィルタ
  { collection: "records", fields: ["deleted_at ASC", "status ASC", "updated_at DESC"] },

  # タイプフィルタ
  { collection: "records", fields: ["deleted_at ASC", "type ASC", "updated_at DESC"] },

  # Vector Search（768次元, cosine）
  { collection: "records", fields: ["embedding VECTOR(768)"], queryScope: "COLLECTION" },

  # セルログ（レコード内、時系列）
  { collection: "cell_logs", fields: ["executed_at ASC"] },
]
```

### 2.3 Nextcloud上のディレクトリ構造

```
{group_folder}/mdxdb/{team_id}/{record_id}/
├── data/
│   ├── xrd_data.csv
│   ├── sem_50000x.tiff
│   └── filtered.npy
├── _preview/                             # 自動処理トリガーで生成
│   ├── sem_50000x_thumb.jpg              # サムネイル 256x256
│   ├── sem_50000x_preview.jpg            # プレビュー 1024x1024
│   ├── sem_50000x_meta.json              # 画像メタ
│   ├── xrd_data_preview.json             # CSV先頭行+統計
│   └── filtered_stats.json               # ndarray統計
└── analyses/                             # execute_code 結果
    ├── AN7K_fit_plot.png
    └── BM4P_comparison.png
```

---

## 3. ローカルバッファ実装仕様

### 3.1 SQLiteテーブル定義

```sql
-- PRAGMA設定
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- レコードメタデータ
CREATE TABLE IF NOT EXISTS records (
    id          TEXT PRIMARY KEY,
    data        TEXT NOT NULL,           -- JSON serialized Record.to_dict()
    synced      INTEGER DEFAULT 0,       -- 0: 未同期, 1: 同期済み
    created_at  TEXT NOT NULL,           -- ISO8601
    updated_at  TEXT NOT NULL
);

-- セルログ
CREATE TABLE IF NOT EXISTS cell_logs (
    cell_id     TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    data        TEXT NOT NULL,           -- JSON serialized CellLog.to_dict()
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(id)
);

-- ファイルメタ（バイナリ実体はファイルシステム上）
CREATE TABLE IF NOT EXISTS data_files (
    id          TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    name        TEXT NOT NULL,
    local_path  TEXT NOT NULL,
    content_type TEXT DEFAULT '',
    size_bytes  INTEGER DEFAULT 0,
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(id)
);

-- 同期メタデータ
CREATE TABLE IF NOT EXISTS sync_status (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- トレース（@exp.track）
CREATE TABLE IF NOT EXISTS traces (
    trace_id    TEXT PRIMARY KEY,
    record_id   TEXT NOT NULL,
    data        TEXT NOT NULL,
    synced      INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (record_id) REFERENCES records(id)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_records_synced ON records(synced);
CREATE INDEX IF NOT EXISTS idx_cell_logs_record ON cell_logs(record_id);
CREATE INDEX IF NOT EXISTS idx_cell_logs_synced ON cell_logs(synced);
CREATE INDEX IF NOT EXISTS idx_data_files_record ON data_files(record_id);
CREATE INDEX IF NOT EXISTS idx_data_files_synced ON data_files(synced);
CREATE INDEX IF NOT EXISTS idx_traces_synced ON traces(synced);
```

### 3.2 ファイルシステム構造

```
~/.mdxdb/
├── config.toml                # 設定ファイル
└── buffer/
    ├── buffer.db              # SQLite WALモードDB
    ├── buffer.db-wal          # WALファイル（SQLite自動管理）
    ├── buffer.db-shm          # 共有メモリ（SQLite自動管理）
    └── files/                 # バイナリファイル実体
        ├── AB3F/
        │   ├── xrd_data.csv
        │   └── sem.tiff
        └── KL67/
            └── output.npy
```

### 3.3 同期ロジック

```
同期フロー（SyncManager._sync()）:

  1. records テーブルから synced=0 のレコードを取得
     ├── Firestoreに既存？
     │     ├── YES: updated_at 比較 → ローカルが新しければ update（Last-Write-Wins）
     │     └── NO:  create
     └── 成功したら mark_synced("records", [id])

  2. cell_logs テーブルから synced=0 を取得
     ├── Firestore の records/{record_id}/cell_logs/{cell_id} に保存
     │   （cell_id はユニークなので衝突しない。冪等操作）
     └── 成功したら mark_synced("cell_logs", [cell_id])

  3. data_files テーブルから synced=0 を取得
     ├── local_path からバイトデータ読み込み
     ├── Nextcloud の {team}/{record_id}/data/{name} にアップロード
     ├── Firestore の records/{record_id}.data_refs に追記
     └── 成功したら mark_synced("data_files", [id])

  4. traces テーブルから synced=0 を取得（同上の流れ）

  各ステップで例外発生時:
    - 指数バックオフリトライ（最大3回、base=2秒）
    - 全リトライ失敗 → errors カウント +1、次回同期で再試行
```

### 3.4 コンフリクト解決ルール

| データ種別 | 戦略 | 理由 |
|-----------|------|------|
| **メタデータ** (conditions, results, status) | Last-Write-Wins (updated_at) | 同一フィールド同時変更は後勝ち |
| **notes** | マージ（union、created_at でソート） | 追記型データ。衝突しない |
| **tags** | set union | 両方のタグを結合 |
| **cell_logs** | cell_id ユニーク → 衝突なし | 冪等書き込み |
| **data_files** | 同名ファイルは後勝ち | 実際は名前衝突稀（タイムスタンプ等） |

---

## 4. IPython hooks実装仕様

### 4.1 フック登録/解除のライフサイクル

```
Lab.new(title, auto_log=True)
  │
  ├── Record を生成
  ├── IPython 検出:
  │     from IPython import get_ipython
  │     ip = get_ipython()
  │
  ├── ip is not None の場合:
  │     tracker = CellTracker(record, buffer)
  │     tracker.activate()
  │       ├── ip.events.register("pre_run_cell", tracker._pre_run_cell)
  │       └── ip.events.register("post_run_cell", tracker._post_run_cell)
  │     record._cell_tracker = tracker
  │
  └── ip is None の場合:
        warnings.warn("IPython環境ではない。@exp.track を使ってください")

Record.close() / Record.__exit__() / Record.__del__()
  │
  └── tracker.deactivate()
        ├── ip.events.unregister("pre_run_cell", tracker._pre_run_cell)
        └── ip.events.unregister("post_run_cell", tracker._post_run_cell)
```

### 4.2 namespace diff アルゴリズム

```
_pre_run_cell(info):
  1. info.silent == True → SKIP
  2. source = info.raw_cell.strip()
  3. source が空 → SKIP（_pre_snapshot = None）
  4. source が "%" or "!" 始まり → SKIP（マジックコマンド）
  5. _NamespaceSnapshot を作成:
     a. ip.user_ns の全キー k に対して:
        - _should_skip_var(k, v) == True → SKIP
        - ids[k] = id(v)          # オブジェクトID（コピー不要）
        - hashes[k] = hash(v)     # hashable なら。TypeError → None
     b. 保存: self._pre_snapshot = snapshot
     c. self._pre_time = time.perf_counter()

_post_run_cell(result):
  1. is_active == False or _pre_snapshot is None → RETURN
  2. duration = perf_counter() - _pre_time
  3. post_ns = ip.user_ns
  4. _compute_namespace_diff(pre_snapshot, post_ns):
     a. new_vars = {}
     b. changed_vars = {}
     c. deleted_vars = []
     d. post_ns の全キー k に対して:
        - _should_skip_var(k, v)  → SKIP
        - _is_sensitive(k)        → SKIP
        - k not in pre.ids        → new_vars[k] = serialize_value(v)
        - k in pre.ids:
            new_id = id(v), new_hash = hash(v) or None
            old_id != new_id OR (both hashable and old_hash != new_hash)
            → changed_vars[k] = serialize_value(v)
     e. pre.ids の k で post にない → deleted_vars.append(k)
  5. CellLog を構築
  6. buffer.save_cell_log(cell_log)
```

### 4.3 フィルタリング（除外する変数のルール）

| ルール | 例 | 理由 |
|--------|---|------|
| `_` で始まる | `_temp`, `__name__` | 内部変数 |
| IPython内部変数 | `In`, `Out`, `get_ipython`, `_i`, `_oh` | Jupyterシステム変数 |
| `_iN` パターン | `_i1`, `_i2` | IPython入力履歴 |
| モジュール | `import numpy as np` の `np` | types.ModuleType |
| 関数/クラス定義 | `def f(): ...` の `f` | types.FunctionType, type |
| センシティブ名 | `password`, `api_key`, `token`, `secret` | セキュリティ |
| ユーザー除外リスト | `exp.auto_log.exclude_vars("large_obj")` | 明示指定 |
| ユーザー除外パターン | `exp.auto_log.exclude_patterns("*_cache")` | fnmatch |

### 4.4 バッファリング戦略

```
CellLog → LocalBuffer（SQLite WAL、書き込みキュー経由。ノンブロッキング）
  │
  └── 書き込みスレッド（daemon）が queue.get() で処理
        └── SQLite INSERT（即座、~0.5ms）

LocalBuffer → Firestore（SyncManager、別 daemon スレッド）
  │
  ├── デフォルト: 30秒間隔
  ├── lab.sync() で手動即時実行
  └── Record.close() / Lab.close() で最終同期

パフォーマンス目標:
  pre_run_cell:  ~0.5-2ms（1000変数）
  post_run_cell: ~1-4ms（diff + serialize + SQLite write）
  合計:          ~1.5-6ms / セル（実験コード10ms-分単位に対して無視可能）
```

---

## 5. 自動処理トリガー実装仕様

### 5.1 ファイル種別判定ロジック

```python
# src/mdxdb/processing/detector.py
import mimetypes
from pathlib import Path

# 拡張子 → 処理カテゴリのマッピング
_FILE_CATEGORIES: dict[str, str] = {
    # 画像
    ".tif": "image", ".tiff": "image",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".bmp": "image", ".gif": "image",
    # NumPy
    ".npy": "numpy", ".npz": "numpy",
    # CSV/TSV
    ".csv": "csv", ".tsv": "csv", ".txt": "csv",  # txtはヒューリスティック判定
    # Notebook
    ".ipynb": "notebook",
    # 計測器データ
    ".ras": "instrument", ".raw": "instrument",
}

def detect_category(filename: str) -> str:
    """ファイル名から処理カテゴリを判定。

    Returns:
        "image" | "numpy" | "csv" | "notebook" | "instrument" | "other"
    """
    ext = Path(filename).suffix.lower()
    return _FILE_CATEGORIES.get(ext, "other")
```

### 5.2 各種別の前処理内容

| カテゴリ | 前処理内容 | 生成物 |
|---------|-----------|--------|
| **image** | サムネイル生成（256x256 JPEG）、プレビュー生成（1024x1024 JPEG）、メタデータ抽出 | `_preview/{name}_thumb.jpg`, `_preview/{name}_preview.jpg`, `_preview/{name}_meta.json` |
| **numpy** | 統計サマリー（shape, dtype, min, max, mean, std, percentiles） | `_preview/{name}_stats.json` |
| **csv** | カラム名、行数、先頭5行、数値列の基本統計 | `_preview/{name}_preview.json` |
| **notebook** | セル一覧、出力サマリー、使用パッケージ | `_preview/{name}_summary.json` |
| **instrument** | ファイルサイズ、フォーマット情報のみ（パーサーは将来プラグイン） | `_preview/{name}_meta.json` |

### 5.3 Cloud Functionsトリガー設計

```
Phase 1（SDK内蔵）:
  Record.add() / Record.save() の直後に、同一プロセス内で前処理を実行。
  → 追加依存を最小化。Pillow はオプショナル（pip install mdxdb[preview]）。

Phase 2（Cloud Functions）:
  Firestoreトリガー:
    onDocumentUpdate("teams/{team}/records/{record}")
      └── data_refs フィールドの変更を検知
          └── 新規追加ファイルに対して前処理を実行
          └── 結果を _preview/ に保存 + Firestore の data_refs.{name}.preview_path を更新
```

### 5.4 `_preview/` 保存パス規則

```
{record_id}/
  _preview/
    {basename_without_ext}_{suffix}.{ext}

例:
  sem_50000x.tiff → _preview/sem_50000x_thumb.jpg
                   → _preview/sem_50000x_preview.jpg
                   → _preview/sem_50000x_meta.json

  xrd_data.csv    → _preview/xrd_data_preview.json

  filtered.npy    → _preview/filtered_stats.json
```

---

## 6. pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mdxdb"
version = "0.1.0"
description = "実験データ管理SDK — Notebook全セル自動記録 + LLMネイティブ"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
authors = [
    { name = "Konishi Lab" },
]
keywords = ["experiment", "data-management", "jupyter", "llm", "materials-science"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Science/Research",
    "Framework :: Jupyter",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering",
]

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
]
nextcloud = [
    "nc-py-api>=0.19",
]
numpy = [
    "numpy>=1.24",
]
preview = [
    "Pillow>=10.0",
    "numpy>=1.24",
]
all = [
    "mdxdb[gcp,nextcloud,numpy,preview]",
]
dev = [
    "pytest>=8.1",
    "pytest-cov>=5.0",
    "pytest-timeout>=2.3",
    "ruff>=0.4",
    "mypy>=1.10",
    "ipython>=8.0",
    "black>=24.0",
]

[project.scripts]
mdxdb = "mdxdb.cli.main:cli"

[project.urls]
Homepage = "https://github.com/konishi-lab/kpro-arim-mdxdb"
Documentation = "https://github.com/konishi-lab/kpro-arim-mdxdb#readme"
Repository = "https://github.com/konishi-lab/kpro-arim-mdxdb"

[tool.hatch.build.targets.wheel]
packages = ["src/mdxdb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=mdxdb --cov-report=term-missing -v --timeout=30"
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

[tool.black]
line-length = 120
target-version = ["py310"]
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

### 7.2 test_core/test_types.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_cell_log_to_dict` | CellLog.to_dict() のシリアライズ |
| `test_analysis_to_dict` | Analysis.to_dict() のシリアライズ |
| `test_status_enum_values` | Status enumの値が正しい |
| `test_record_type_enum_values` | RecordType enumの値が正しい |

### 7.3 test_core/test_lab.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_new_creates_record` | lab.new() でRecordが返る、IDが4文字 |
| `test_new_with_conditions` | **conditions がRecordに設定される |
| `test_new_with_template` | テンプレート適用でタグ・条件がデフォルト設定 |
| `test_new_with_tags` | 初期タグ設定 |
| `test_get_existing` | lab.get(id) で取得可能 |
| `test_get_nonexistent` | RecordNotFoundError が発生 |
| `test_get_normalize_id` | 小文字ID、O/I入力でも取得可能 |
| `test_list_all` | 全レコード一覧 |
| `test_list_filter_tags` | タグフィルタ |
| `test_list_filter_status` | ステータスフィルタ |
| `test_list_limit_offset` | ページネーション |
| `test_search_text` | テキスト検索（InMemory: 部分一致） |
| `test_recent` | 最新N件が新しい順 |
| `test_today` | 今日のレコードのみ |
| `test_delete_soft` | ソフトデリート（deleted_at設定） |
| `test_delete_soft_excludes_from_list` | 削除後にlistに出ない |
| `test_define_template` | テンプレート保存・取得 |
| `test_sync_returns_counts` | sync()の戻り値 |
| `test_sync_status` | sync_statusのキー |
| `test_context_manager` | with Lab() as lab: が動く |
| `test_export` | export()がディレクトリに出力 |

### 7.4 test_core/test_record.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_conditions_sets_values` | conditions()で値が設定される |
| `test_conditions_method_chain` | conditions() が self を返す |
| `test_results_setitem` | results["key"] = value が動く |
| `test_results_getitem` | results["key"] で取得 |
| `test_tag_add` | tag() でタグ追加 |
| `test_tag_duplicate_ignored` | 同じタグを2回追加しても1つ |
| `test_untag` | untag() でタグ削除 |
| `test_tag_method_chain` | tag() が self を返す |
| `test_note_add` | note() でメモ追加 |
| `test_note_has_timestamp` | メモにcreated_atがある |
| `test_status_setter` | status = "success" で変更 |
| `test_status_invalid_raises` | 不正なステータスでエラー |
| `test_add_file_path` | add(path) でファイルがバッファに保存 |
| `test_add_bytes` | add(bytes, name=...) が動く |
| `test_add_dir` | add_dir() でディレクトリ配下全追加 |
| `test_save_dict_as_json` | save(name, dict) → JSON保存 |
| `test_save_str_as_text` | save(name, str) → テキスト保存 |
| `test_save_ndarray_as_npy` | save(name, ndarray) → npy保存 |
| `test_save_figure_as_png` | save(name, Figure) → PNG保存 |
| `test_add_ref` | add_ref() で外部参照登録 |
| `test_add_ref_doi` | add_ref(doi=...) |
| `test_sub_creates_child` | sub() で子レコード作成 |
| `test_sub_has_parent_id` | 子レコードのparent_idが親ID |
| `test_children_returns_subs` | children() で子一覧 |
| `test_link` | link() でリンク作成 |
| `test_to_dict_roundtrip` | to_dict() → from_dict() が復元 |
| `test_close_sets_success` | close() でstatus=success |
| `test_context_manager_success` | with exp: → close() |
| `test_context_manager_error` | 例外時 status=failed |
| `test_repr` | repr(record) が読める文字列 |
| `test_method_chain` | tag().conditions().note() が連鎖 |

### 7.5 test_tracking/test_cell_tracker.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_hooks_registered` | activate() 後に is_active == True |
| `test_cell_execution_logged` | セル実行後にCellLogがバッファに保存 |
| `test_new_vars_detected` | 新しい変数が new_vars に入る |
| `test_changed_vars_detected` | 変更された変数が changed_vars に入る |
| `test_deleted_vars_detected` | del した変数が deleted_vars に入る |
| `test_error_logged` | エラー発生セルもログされる |
| `test_pause_resume` | pause中はログされない、resume後はログされる |
| `test_paused_context_manager` | with paused(): 内はログされない |
| `test_deactivate` | deactivate後はログされない |
| `test_sensitive_vars_excluded` | password, api_key が記録されない |
| `test_module_vars_excluded` | import np の np が記録されない |
| `test_ipython_internals_excluded` | In, Out 等が記録されない |
| `test_magic_commands_skipped` | %who 等がスキップされる |
| `test_empty_cell_skipped` | 空セルがスキップされる |
| `test_source_truncation` | 長いソースが切り詰められる |
| `test_env_captured_once` | env は初回セルのみ |
| `test_exclude_vars` | exclude_vars() で指定変数が除外 |
| `test_exclude_patterns` | exclude_patterns("*_cache") が動く |
| `test_cell_count` | cell_count が正しくインクリメント |
| `test_non_ipython_warns` | IPython環境外で UserWarning |

### 7.6 test_tracking/test_serializers.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_serialize_int` | int → int（そのまま） |
| `test_serialize_float` | float → float |
| `test_serialize_str` | str → str |
| `test_serialize_bool` | bool → bool |
| `test_serialize_none` | None → None |
| `test_serialize_small_list` | list（10以下）→ 再帰シリアライズ |
| `test_serialize_large_list` | list（11以上）→ {__type__, length, first_3} |
| `test_serialize_dict` | dict → 再帰シリアライズ |
| `test_serialize_ndarray` | ndarray → {__type__, shape, dtype, stats} |
| `test_serialize_dataframe` | DataFrame → {__type__, shape, columns} |
| `test_serialize_figure` | Figure → {__type__, axes_count} |
| `test_serialize_unknown` | 未知の型 → repr() |
| `test_serialize_nested` | ネスト構造の再帰 |

### 7.7 test_tracking/test_tracker.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_track_decorator` | @exp.track で関数の引数・返り値が記録 |
| `test_track_captures_args` | 引数値がシリアライズされる |
| `test_track_captures_return` | 返り値がシリアライズされる |
| `test_track_captures_duration` | 実行時間が記録される |
| `test_track_error_logged` | 例外発生時もログされる |

### 7.8 test_tracking/test_snapshot.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_snapshot_captures_locals` | スタックフレームのlocalsがキャプチャされる |
| `test_snapshot_include_filter` | include で指定変数のみ |
| `test_snapshot_exclude_filter` | exclude で指定変数を除外 |

### 7.9 test_buffer/test_local_buffer.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_save_record` | save_record → get_unsynced_records |
| `test_save_cell_log` | save_cell_log → get_unsynced_cell_logs |
| `test_save_file` | save_file でローカルファイルが作成される |
| `test_get_record` | get_record(id) で特定レコード取得 |
| `test_mark_synced` | mark_synced 後に unsynced から消える |
| `test_cleanup` | cleanup で古い同期済みデータが削除される |
| `test_buffer_size` | get_buffer_size_mb() >= 0 |
| `test_close` | close() でエラーなし |
| `test_concurrent_writes` | 複数の連続書き込みが欠損しない |

### 7.10 test_buffer/test_sync.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_sync_records` | 未同期レコードがバックエンドに保存される |
| `test_sync_cell_logs` | 未同期セルログがバックエンドに保存される |
| `test_sync_files` | 未同期ファイルがストレージにアップロード |
| `test_sync_marks_synced` | 同期後に synced=1 になる |
| `test_sync_retry_on_error` | エラー時にリトライされる |
| `test_sync_returns_counts` | 戻り値に件数が含まれる |
| `test_conflict_last_write_wins` | updated_at が新しい方が勝つ |

### 7.11 test_backends/test_memory.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_create_and_get` | create → get で復元 |
| `test_update` | update でフィールド変更 |
| `test_delete` | delete で取得不可 |
| `test_list_all` | list で全件取得 |
| `test_list_filter_tags` | タグフィルタ |
| `test_save_and_get_cell_log` | セルログの保存・取得 |
| `test_save_and_get_analysis` | 解析の保存・取得 |
| `test_template_crud` | テンプレートの保存・取得・一覧 |

### 7.12 test_cli/test_commands.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_cli_new` | `mdxdb new "title"` が正常終了 |
| `test_cli_list` | `mdxdb list` が出力を返す |
| `test_cli_show` | `mdxdb show ID` がレコード詳細表示 |
| `test_cli_add` | `mdxdb add ID file` が正常終了 |
| `test_cli_search` | `mdxdb search "query"` が結果表示 |
| `test_cli_tag` | `mdxdb tag ID tag1` が正常終了 |
| `test_cli_note` | `mdxdb note ID "text"` が正常終了 |
| `test_cli_sync` | `mdxdb sync` が正常終了 |
| `test_cli_sync_status` | `mdxdb sync-status` がJSON出力 |

### 7.13 test_integration/test_full_flow.py

| テスト名 | 検証内容 |
|---------|---------|
| `test_notebook_flow` | Lab.new → セル実行 → CellLog確認 → close |
| `test_script_flow` | Lab.new(auto_log=False) → @track → close |
| `test_multi_pc_flow` | lab.new → lab.get(id) → add → 紐付け確認 |
| `test_child_record_flow` | exp.sub() → 子にadd → 親から children() |
| `test_offline_then_sync` | バッファ書き込み → sync() → バックエンド確認 |
| `test_context_manager_flow` | with lab.new() as exp: の全フロー |

---

## 8. M0-M4 Issue一覧

### M0: 基盤セットアップ + POC（Week 1-2）

#### Issue M0-1: GCPプロジェクトセットアップ
**受け入れ条件:**
- [ ] GCPプロジェクト作成（asia-northeast1）
- [ ] Firestore Native Mode データベース作成
- [ ] Vertex AI API 有効化
- [ ] サービスアカウント作成（SDK用、Cloud Functions用）
- [ ] IAMロール設定（Firestore読み書き、Vertex AI呼び出し）
- [ ] Secret Manager にNextcloud認証情報を保存

#### Issue M0-2: SDKリポジトリ刷新
**受け入れ条件:**
- [ ] `pyproject.toml` を本仕様書のセクション6の通りに刷新
- [ ] `src/mdxdb/` ディレクトリ構造を作成（core/, backends/, tracking/, buffer/, storage/, search/, cli/, compat/）
- [ ] 各ディレクトリに `__init__.py` を配置
- [ ] `src/mdxdb/__init__.py` で `Lab`, `Record`, `Status`, `RecordType` を re-export
- [ ] CLAUDE.md を新アーキテクチャに更新
- [ ] GitHub Actions CI 設定（lint + test）
- [ ] `pip install -e .` でインストール確認
- [ ] `pytest` で空テストが通る

#### Issue M0-3: POC — Firestore Vector Search性能検証
**受け入れ条件:**
- [ ] テストデータ1,000 / 10,000 / 50,000件でVector Search応答時間を計測
- [ ] 768次元（text-embedding-004）でのクエリレイテンシ < 200ms（10K件）
- [ ] team_id フィルタ付きVector Searchの性能を確認
- [ ] 結果を `docs/poc/firestore_vector_search.md` に記録

#### Issue M0-4: POC — Vertex AI Embedding日本語品質検証
**受け入れ条件:**
- [ ] `text-embedding-004` で日本語実験記述10-20件のembeddingを生成
- [ ] 類似実験が上位3件に入ることを確認
- [ ] `text-multilingual-embedding-002` との比較結果を記録
- [ ] 英語混じり記述（化学式、装置名）での品質を確認
- [ ] 採用モデルを決定し記録

#### Issue M0-5: POC — MCP接続検証
**受け入れ条件:**
- [ ] 最小MCPサーバー（echo ツール1つ）を作成
- [ ] Claude Desktopから SSE transport で接続確認
- [ ] Claude Codeから接続確認
- [ ] レスポンス形式・エラーハンドリング確認

#### Issue M0-6: POC — Nextcloud WebDAV速度検証
**受け入れ条件:**
- [ ] 1MB / 10MB / 100MB ファイルのアップロード時間を計測
- [ ] 10MB/s 以上であること
- [ ] 既存 nc_py_api クライアントのリトライ動作確認

---

### M1: SDK Core + LocalBuffer + CellTracker（Week 2-4）

#### Issue M1-1: Crockford Base32 IDジェネレーター
**受け入れ条件:**
- [ ] `generate_id(length)` が指定長のIDを生成
- [ ] `normalize_id(raw)` で O→0, I→1, L→1, 小文字→大文字 変換
- [ ] Crockford Base32 アルファベットのみ使用
- [ ] テスト: `test_core/test_id.py` の全テスト通過

#### Issue M1-2: 型定義（types.py）
**受け入れ条件:**
- [ ] Status, RecordType enum 定義
- [ ] Note, Link, ExternalRef, DataRef dataclass 定義
- [ ] CellLog dataclass + to_dict() 定義
- [ ] Analysis dataclass + to_dict() 定義
- [ ] テスト: `test_core/test_types.py` の全テスト通過

#### Issue M1-3: 例外クラス（exceptions.py）
**受け入れ条件:**
- [ ] MdxdbError, RecordNotFoundError, SyncError, BackendError, ValidationError

#### Issue M1-4: Settings（config.py）
**受け入れ条件:**
- [ ] pydantic-settings ベースの Settings クラス
- [ ] 環境変数 MDXDB_TEAM, MDXDB_USER 等から読み込み
- [ ] `~/.mdxdb/config.toml` から読み込み
- [ ] デフォルト値が設定されている

#### Issue M1-5: Backend Protocol定義
**受け入れ条件:**
- [ ] MetadataBackend Protocol（base.py）全メソッド定義
- [ ] StorageBackend Protocol 全メソッド定義
- [ ] SearchBackend Protocol 全メソッド定義

#### Issue M1-6: InMemoryBackend実装
**受け入れ条件:**
- [ ] InMemoryMetadataBackend — MetadataBackend の全メソッド実装
- [ ] InMemoryStorageBackend — StorageBackend の全メソッド実装
- [ ] InMemorySearchBackend — SearchBackend 全メソッド実装（部分一致検索）
- [ ] テスト: `test_backends/test_memory.py` 全テスト通過
- [ ] テスト用 conftest.py に lab fixture 定義

#### Issue M1-7: Recordクラス実装
**受け入れ条件:**
- [ ] 本仕様書の Record クラス全メソッド実装
- [ ] _ResultsProxy 実装
- [ ] conditions(), tag(), untag(), note() メソッドチェーン対応
- [ ] add(), save(), add_ref(), add_dir() 実装
- [ ] sub(), children(), link() 実装
- [ ] to_dict() / from_dict() ラウンドトリップ
- [ ] コンテキストマネージャ対応（__enter__, __exit__）
- [ ] close() で status=success 設定
- [ ] テスト: `test_core/test_record.py` 全テスト通過

#### Issue M1-8: Labクラス実装
**受け入れ条件:**
- [ ] new(), get(), list(), search(), recent(), today(), delete() 実装
- [ ] define_template(), templates() 実装
- [ ] sync(), sync_status 実装
- [ ] LocalBuffer 自動初期化
- [ ] IPython 環境検出 → CellTracker 自動起動
- [ ] close() / コンテキストマネージャ
- [ ] テスト: `test_core/test_lab.py` 全テスト通過

#### Issue M1-9: LocalBuffer実装（SQLite WAL）
**受け入れ条件:**
- [ ] 本仕様書のSQLiteスキーマで初期化
- [ ] save_record(), save_cell_log(), save_file() ノンブロッキング書き込み
- [ ] 書き込みキュー + daemon スレッド
- [ ] get_unsynced_*, mark_synced() 実装
- [ ] cleanup() 実装
- [ ] get_buffer_size_mb() 実装
- [ ] close() でスレッド停止
- [ ] テスト: `test_buffer/test_local_buffer.py` 全テスト通過

#### Issue M1-10: SyncManager実装
**受け入れ条件:**
- [ ] start(), stop(), sync_now() 実装
- [ ] 30秒間隔のバックグラウンド同期（daemon スレッド）
- [ ] 指数バックオフリトライ（最大3回）
- [ ] Last-Write-Wins コンフリクト解決
- [ ] テスト: `test_buffer/test_sync.py` 全テスト通過

#### Issue M1-11: serialize_value 実装
**受け入れ条件:**
- [ ] 本仕様書の型判定ルール全実装
- [ ] ndarray → 統計サマリー
- [ ] DataFrame → shape + columns
- [ ] Figure → axes_count
- [ ] 大きなコレクション → length + first_3
- [ ] 未知の型 → repr()
- [ ] テスト: `test_tracking/test_serializers.py` 全テスト通過

#### Issue M1-12: CellTracker実装（IPython hooks）
**受け入れ条件:**
- [ ] activate() で pre_run_cell / post_run_cell フック登録
- [ ] deactivate() でフック解除
- [ ] pause() / resume() / paused() 動作
- [ ] _NamespaceSnapshot: id() + hash() でdiff検出
- [ ] 除外フィルタ全種（IPython内部変数、センシティブ、モジュール等）
- [ ] exclude_vars(), exclude_patterns() 動作
- [ ] env キャプチャは初回のみ
- [ ] テスト: `test_tracking/test_cell_tracker.py` 全テスト通過

#### Issue M1-13: @exp.track デコレータ実装
**受け入れ条件:**
- [ ] Tracker クラス実装
- [ ] 関数引数、返り値、実行時間のキャプチャ
- [ ] バッファへの保存
- [ ] テスト: `test_tracking/test_tracker.py` 全テスト通過

#### Issue M1-14: exp.snapshot() 実装
**受け入れ条件:**
- [ ] スタックフレームからローカル変数をキャプチャ
- [ ] include / exclude フィルタ
- [ ] テスト: `test_tracking/test_snapshot.py` 全テスト通過

#### Issue M1-15: 統合テスト
**受け入れ条件:**
- [ ] `test_integration/test_full_flow.py` の全テスト通過
- [ ] `pytest` で全テストがオフライン実行可能
- [ ] カバレッジ80%以上

---

### M2: Embedding + Vector Search（Week 4-5）

#### Issue M2-1: EmbeddingService実装
**受け入れ条件:**
- [ ] Vertex AI `text-embedding-004`（or POCで決定したモデル）統合
- [ ] Record → embedding用テキスト生成（title + conditions + results + tags + notes 結合）
- [ ] バッチembedding生成（複数レコード一括）
- [ ] テスト: モックでのユニットテスト

#### Issue M2-2: Firestore Vector Search統合
**受け入れ条件:**
- [ ] FirestoreBackend に embedding フィールド書き込み追加
- [ ] Vector Search用インデックス作成（768次元, cosine）
- [ ] `lab.search("クエリ")` でセマンティック検索が動作
- [ ] フィルタ付きVector Search（tags, status等）
- [ ] テスト: 実Firestore接続テスト（integration marker）

#### Issue M2-3: 自動Embedding生成
**受け入れ条件:**
- [ ] Record作成時に自動embedding生成
- [ ] conditions/results/tags 変更時にembedding再生成
- [ ] 生成失敗時のリトライ
- [ ] 非同期生成オプション

#### Issue M2-4: Summary自動生成
**受け入れ条件:**
- [ ] Gemini 2.0 Flash でRecordサマリーを自動生成
- [ ] Firestore の summary フィールドに保存
- [ ] embedding テキストにsummaryを含める

---

### M3: MCPサーバー + CLI（Week 5-6）

#### Issue M3-1: CLIコマンド実装
**受け入れ条件:**
- [ ] 本仕様書のCLI全コマンド実装（init, new, list, show, add, search, note, tag, url, export, sync, sync-status, buffer-clean, template list/create）
- [ ] click + rich でリッチ出力
- [ ] テスト: `test_cli/test_commands.py` 全テスト通過
- [ ] `mdxdb --help` が動作

#### Issue M3-2: MCPサーバー Core実装
**受け入れ条件:**
- [ ] FastMCP ベースの MCPサーバー
- [ ] SSE transport
- [ ] API Key認証（Bearer Token）
- [ ] Cloud Functions デプロイ設定

#### Issue M3-3: MCPサーバー ツール実装
**受け入れ条件:**
- [ ] search — セマンティック検索
- [ ] get_detail — レコード詳細
- [ ] compare — 複数レコード比較
- [ ] data_preview — ファイル統計サマリー
- [ ] get_results — 構造化結果の横断検索
- [ ] aggregate — 数値集約
- [ ] get_timeline — サンプルの実験履歴
- [ ] get_notebook_log — セルログ取得
- [ ] execute_code — Pythonコード実行
- [ ] batch_execute — 複数レコードに一括適用
- [ ] get_image — 画像取得
- [ ] 各ツールのJSON Schema 定義

#### Issue M3-4: Claude Desktop接続ガイド
**受け入れ条件:**
- [ ] claude_desktop_config.json サンプル
- [ ] API Key発行手順
- [ ] 接続テスト手順
- [ ] トラブルシューティング

---

### M4: FirestoreBackend + NextcloudStorage 本番実装（Week 6-7）

#### Issue M4-1: FirestoreBackend実装
**受け入れ条件:**
- [ ] MetadataBackend Protocol 全メソッド実装
- [ ] `teams/{team_id}/records/{record_id}` CRUD
- [ ] サブコレクション cell_logs, analyses, traces の CRUD
- [ ] テンプレート CRUD
- [ ] バッチ書き込み対応
- [ ] テスト: 実Firestore接続テスト（integration marker）

#### Issue M4-2: NextcloudStorage実装
**受け入れ条件:**
- [ ] StorageBackend Protocol 全メソッド実装
- [ ] パス: `{group_folder}/mdxdb/{team_id}/{record_id}/data/{filename}`
- [ ] アップロード / ダウンロード / 削除 / exists / list_files
- [ ] 共有リンク自動生成（get_share_url）
- [ ] Path.as_posix() 統一
- [ ] 指数バックオフリトライ（既存ロジック移植）
- [ ] テスト: 実Nextcloud接続テスト（integration marker）

#### Issue M4-3: 自動処理トリガー（Phase 1: SDK内蔵）
**受け入れ条件:**
- [ ] detect_category() でファイル種別判定
- [ ] 画像 → サムネイル + プレビュー生成（Pillow。pip install mdxdb[preview]）
- [ ] ndarray → 統計サマリーJSON
- [ ] CSV → プレビューJSON（先頭5行 + 統計）
- [ ] `_preview/` への保存パス規則どおり
- [ ] Firestore の data_refs.{name}.preview_path を更新

#### Issue M4-4: MVP統合テスト
**受け入れ条件:**
- [ ] 実Firestore + Nextcloud でのフルフロー
- [ ] Lab.new → add → conditions → results → close → search → get
- [ ] CellTracker の Firestore 同期確認
- [ ] MCP search ツールでの検索確認
- [ ] チームメンバー2名が1日使って致命的問題なし
