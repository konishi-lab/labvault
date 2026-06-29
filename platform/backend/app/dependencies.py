"""FastAPI 依存関係のうち、認証に依存しないユーティリティ。

`current_team` 依存付きの FastAPI dep (handler が直接受け取る `Depends(get_lab)`)
は循環参照を避けるため auth.py 側に置く。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from fastapi import HTTPException

from labvault import Lab

from .secrets_util import get_secret

logger = logging.getLogger(__name__)

_labs: dict[str, Lab] = {}
_labs_lock = threading.Lock()
_firestore_db: Any | None = None
_firestore_lock = threading.Lock()
_shared_metadata_backend: Any | None = None
_shared_metadata_lock = threading.Lock()


def get_firestore_db() -> Any:
    """Firestore client のシングルトン。teams / allowed_users 等の参照に使う。"""
    global _firestore_db
    with _firestore_lock:
        if _firestore_db is None:
            from google.cloud import firestore

            project = os.environ.get("LABVAULT_GCP_PROJECT")
            database = os.environ.get("LABVAULT_FIRESTORE_DATABASE", "(default)")
            _firestore_db = firestore.Client(project=project or None, database=database)
        return _firestore_db


def get_team_meta(team_id: str) -> dict[str, Any]:
    """teams/{team_id} ドキュメントを取得する。存在しなければ 404。"""
    snap = get_firestore_db().collection("teams").document(team_id).get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail=f"team {team_id!r} not found")
    return snap.to_dict() or {}


def _build_lab(team_id: str) -> Lab:
    """指定 team の Lab を構築する。

    nextcloud-master-password (Secret Manager) と
    teams/{team_id}.nextcloud_group_folder を組み合わせて NextcloudStorage を作る。
    Secret 未設定 / Settings 不完全なら SDK の自動選択 (`Lab(team=...)`) に任せる。
    """
    master = get_secret("nextcloud-master-password")
    if not master:
        logger.warning(
            "nextcloud-master-password not set, using Lab auto-config for %s",
            team_id,
        )
        return Lab(team=team_id)

    from labvault.backends.nextcloud import NextcloudStorage
    from labvault.core.config import Settings

    s = Settings()
    if not (s.nextcloud_url and s.nextcloud_user):
        return Lab(team=team_id)

    meta = get_team_meta(team_id)
    group_folder = meta.get("nextcloud_group_folder") or s.nextcloud_group_folder
    if not group_folder:
        raise HTTPException(
            status_code=500,
            detail=(
                f"team {team_id!r} has no nextcloud_group_folder "
                "and no fallback in Settings"
            ),
        )

    storage = NextcloudStorage(
        url=s.nextcloud_url,
        user=s.nextcloud_user,
        password=master,
        group_folder=group_folder,
    )
    return Lab(team=team_id, storage_backend=storage)


def get_lab_for_team(team_id: str) -> Lab:
    """team_id を指定して Lab を取得する (キャッシュ付き)。

    FastAPI handler からは auth.get_lab (current_team を Depends する FastAPI dep)
    経由で間接的に呼ばれる。
    """
    with _labs_lock:
        if team_id not in _labs:
            _labs[team_id] = _build_lab(team_id)
        return _labs[team_id]


def close_lab() -> None:
    """全 Lab を閉じる。lifespan で呼ぶ。"""
    with _labs_lock:
        for lab in _labs.values():
            try:
                lab.close()
            except Exception:
                logger.exception("close lab failed")
        _labs.clear()


def get_shared_metadata_backend() -> Any:
    """S1 Phase 1B (shared-with-me): cross-team query 用の MetadataBackend.

    通常の Lab は team を 1 つ固定するため、複数 team を横断する
    `list_records_shared_with` のためには team に紐付かない backend
    インスタンスが必要。本関数は Firestore client を再利用する形で
    `FirestoreMetadataBackend` を 1 回だけ作って返す (singleton)。

    Local 開発で Firestore ADC が無い場合は ``LABVAULT_DEV_SKIP_AUTH=1``
    と組み合わせ、tests からは monkeypatch で InMemoryMetadataBackend
    を返すように差し替えること。
    """
    global _shared_metadata_backend
    with _shared_metadata_lock:
        if _shared_metadata_backend is None:
            from labvault.backends.firestore import FirestoreMetadataBackend

            project = os.environ.get("LABVAULT_GCP_PROJECT", "")
            database = os.environ.get("LABVAULT_FIRESTORE_DATABASE", "(default)")
            _shared_metadata_backend = FirestoreMetadataBackend(
                project=project, database=database
            )
        return _shared_metadata_backend


def reset_shared_metadata_backend() -> bool:
    """`get_shared_metadata_backend()` シングルトンを破棄する。

    Firestore client が broken pipe 等で永続的に失敗するときの自動回復
    パスに組み込む (`reset_firestore_db` と並列に呼ばれる想定)。
    """
    global _shared_metadata_backend
    with _shared_metadata_lock:
        if _shared_metadata_backend is None:
            return False
        _shared_metadata_backend = None
        return True


def reset_lab(team_id: str | None = None) -> int:
    """Lab シングルトンキャッシュを破棄する (次回 get_lab_for_team で再生成)。

    `team_id=None` で全 team、指定すればその team だけ。Cloud Run の
    24h+ 連続稼働で Firestore client の broken pipe / idle timeout により
    永続的に 500 を返し続ける問題を、handler 側で検出した時に呼び出して
    回復させる。

    返り値: drop した team 数 (主に observability event の field 用)。
    """
    with _labs_lock:
        if team_id is None:
            dropped = list(_labs.keys())
            for lab in _labs.values():
                try:
                    lab.close()
                except Exception:
                    logger.exception("close lab failed during reset")
            _labs.clear()
            return len(dropped)
        if team_id in _labs:
            try:
                _labs[team_id].close()
            except Exception:
                logger.exception("close lab failed during reset")
            del _labs[team_id]
            return 1
        return 0


def reset_firestore_db() -> bool:
    """`get_firestore_db()` のシングルトンを破棄する (次回呼び出しで再生成)。

    auth / admin 系の handler が直接叩く `_firestore_db` 用。Lab の中の
    Firestore client とは別物なので、両方を独立に reset できる。

    返り値: 実際に reset したか (既に None なら False)。
    """
    global _firestore_db
    with _firestore_lock:
        if _firestore_db is None:
            return False
        try:
            _firestore_db.close()
        except Exception:
            # close 失敗は無視 (broken client を捨てるのが目的)
            logger.exception("close firestore_db failed during reset")
        _firestore_db = None
        return True


# Lab / Firestore client が「broken pipe / connection idle timeout」で
# 永続的に 500 を返し続ける状況を検出するための例外型集合。`main.py` の
# 例外ハンドラがこれを catch して reset_lab() + reset_firestore_db() を
# 呼び、次のリクエストで client を作り直す。
#
# 個別に import すると optional 依存が壊した時に backend 全体が起動しなく
# なるので、tuple は遅延構築する。
def transient_firestore_exceptions() -> tuple[type[BaseException], ...]:
    """**client 再生成が必要な** Firestore / gRPC 例外の type tuple。

    `_cors_safe_exception_handler` の catch トリガになり、reset_lab() +
    reset_firestore_db() を走らせる。client 自体が壊れている (broken pipe
    / idle timeout / DNS 失敗等) ことを示すシグナルを集める。

    google-cloud-firestore は内部で google-api-core を使い、idle 接続が
    切れた場合は通常 ServiceUnavailable (503) を投げる。grpc の生 RpcError
    (例: UNAVAILABLE) もここに含める。`BrokenPipeError` /
    `ConnectionResetError` は念のため (gRPC 層が catch する前に socket
    レイヤで raise される edge case 用)。

    N3 (PR #82): `Aborted` は **トランザクション衝突** で頻発しうるが
    client 自体は健全なので、ここから除外する。`retriable_firestore_exceptions()`
    で受けて 503 + Retry-After を返すが reset はしない。
    """
    excs: list[type[BaseException]] = [BrokenPipeError, ConnectionResetError]
    try:
        from google.api_core import exceptions as gax

        excs.extend(
            [
                gax.ServiceUnavailable,
                gax.DeadlineExceeded,
                gax.InternalServerError,
                gax.Unknown,
            ]
        )
    except ImportError:
        pass
    try:
        import grpc

        excs.append(grpc.RpcError)
    except ImportError:
        pass
    return tuple(excs)


def retriable_firestore_exceptions() -> tuple[type[BaseException], ...]:
    """**client は健全だが request 単位で retry すれば解消する** 例外型。

    N3 (PR #82): トランザクション衝突 (`Aborted`) はここに分離。Lab /
    Firestore singleton を破棄せず、503 + `Retry-After: 1` だけ返して
    クライアントの retry に任せる。複数ユーザー同時アクセスで cascading
    reset が起きるのを防ぐ。
    """
    excs: list[type[BaseException]] = []
    try:
        from google.api_core import exceptions as gax

        excs.append(gax.Aborted)
    except ImportError:
        pass
    return tuple(excs)
