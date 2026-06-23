"""Firestore client lifecycle (broken pipe 対策、C4) を検証する。

Cloud Run の 24h 連続稼働で起きる問題:
- Firestore client が idle timeout / broken pipe で接続を失う
- get_lab / get_firestore_db は singleton キャッシュなので、壊れた
  client が永続的に再利用され、500 を返し続ける

PR #80 で:
1. `dependencies.reset_lab()` / `reset_firestore_db()` で singleton を
   明示破棄できる経路を作る
2. `main.py` の例外 handler で `transient_firestore_exceptions()` を
   catch して reset → 503 を返す
3. observability に `firestore.client_reset` event を出す
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from app import dependencies as deps
from app.dependencies import (
    reset_firestore_db,
    reset_lab,
    retriable_firestore_exceptions,
    transient_firestore_exceptions,
)
from app.main import app
from fastapi import APIRouter
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


# ---- reset_lab / reset_firestore_db -----------------------------------------


def _fresh_lab() -> Lab:
    return Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


def test_reset_lab_drops_all_when_no_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "_labs", {"a": _fresh_lab(), "b": _fresh_lab()})
    assert reset_lab() == 2
    assert deps._labs == {}


def test_reset_lab_specific_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "_labs", {"a": _fresh_lab(), "b": _fresh_lab()})
    assert reset_lab("a") == 1
    assert set(deps._labs.keys()) == {"b"}


def test_reset_lab_missing_team_returns_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "_labs", {"a": _fresh_lab()})
    assert reset_lab("nonexistent") == 0
    assert "a" in deps._labs


def test_reset_firestore_db_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deps, "_firestore_db", None)
    assert reset_firestore_db() is False


def test_reset_firestore_db_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """壊れた client を捨てる動作。close() が例外を吐いても singleton を None に
    戻すこと (broken な client を残さない)。"""

    class _BrokenClient:
        def close(self) -> None:
            raise RuntimeError("simulated broken pipe at close()")

    monkeypatch.setattr(deps, "_firestore_db", _BrokenClient())
    assert reset_firestore_db() is True
    assert deps._firestore_db is None


# ---- transient_firestore_exceptions -----------------------------------------


def test_transient_includes_socket_errors() -> None:
    excs = transient_firestore_exceptions()
    assert BrokenPipeError in excs
    assert ConnectionResetError in excs


def test_transient_includes_google_api_core_when_available() -> None:
    """google-api-core が import できる環境なら ServiceUnavailable 等を含む。"""
    try:
        from google.api_core import exceptions as gax
    except ImportError:
        pytest.skip("google-api-core not installed")
    excs = transient_firestore_exceptions()
    assert gax.ServiceUnavailable in excs
    assert gax.DeadlineExceeded in excs


def test_transient_excludes_aborted() -> None:
    """N3 (PR #82): Aborted は transient から除外。cascading reset 防止。

    Aborted は Firestore transaction 衝突で client は健全 (request retry
    で済む) のに reset で全 team Lab を破棄する形になっていた。
    `retriable_firestore_exceptions` 側に分離した。
    """
    try:
        from google.api_core import exceptions as gax
    except ImportError:
        pytest.skip("google-api-core not installed")
    assert gax.Aborted not in transient_firestore_exceptions()
    assert gax.Aborted in retriable_firestore_exceptions()


# ---- 例外ハンドラ ----------------------------------------------------------


@pytest.fixture()
def lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(k, "")
    return _fresh_lab()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: lab,
    )
    # raise_server_exceptions=False で TestClient が exception を ASGI 層に
    # 通し、こちらの exception_handler が走るようにする (デフォルトは
    # テスト fail に再 raise してしまい handler を通らない)。
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# テスト用の handler を一時的に mount してそこで意図した例外を raise する。
# 既存 endpoint で簡単に Firestore transient を起こす方法が無いため。
_test_router = APIRouter()


def _install_test_routes(app_obj: Any) -> None:
    # 既に install 済みなら skip
    for r in app_obj.routes:
        if getattr(r, "path", None) == "/__test/raise_transient":
            return
    app_obj.include_router(_test_router)


@_test_router.get("/__test/raise_transient")
def _raise_transient() -> None:
    try:
        from google.api_core import exceptions as gax

        raise gax.ServiceUnavailable("simulated broken pipe")
    except ImportError:
        # google-api-core が無ければ BrokenPipeError で代替
        raise BrokenPipeError("simulated broken pipe") from None


@_test_router.get("/__test/raise_generic")
def _raise_generic() -> None:
    raise RuntimeError("not transient, should be 500")


@_test_router.get("/__test/raise_aborted")
def _raise_aborted() -> None:
    """N3: Firestore transaction 衝突 (Aborted)。reset せず 503 retry に
    倒すべき (cascading reset 防止)。"""
    try:
        from google.api_core import exceptions as gax

        raise gax.Aborted("simulated transaction conflict")
    except ImportError:
        # 環境に google-api-core が無い CI ではこのテストは skip 扱い
        raise NotImplementedError("google-api-core not available") from None


def test_transient_exception_returns_503_and_resets(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    lab: Lab,
) -> None:
    """ServiceUnavailable / BrokenPipeError 等が raise されると 503 が返り、
    `_labs` キャッシュと `_firestore_db` が破棄される。次のリクエストで
    Lab が再生成されることで永続 500 を回避する。"""
    _install_test_routes(app)
    monkeypatch.setattr(deps, "_labs", {"konishi-lab": lab})

    class _FakeClient:
        closed = False

        def close(self) -> None:
            type(self).closed = True

    fc = _FakeClient()
    monkeypatch.setattr(deps, "_firestore_db", fc)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        res = client.get("/__test/raise_transient")

    assert res.status_code == 503
    body = res.json()
    assert body["transient"] is True
    assert res.headers.get("retry-after") == "1"
    assert res.headers.get("cache-control") == "no-store"

    # singleton は破棄され、handler の reset_lab / reset_firestore_db が走った
    assert deps._labs == {}
    assert deps._firestore_db is None
    assert _FakeClient.closed is True

    # observability event が emit されている
    fields_list = [
        getattr(r, "_lv_fields", None) for r in caplog.records
    ]
    events = [f["event"] for f in fields_list if isinstance(f, dict)]
    assert "firestore.client_reset" in events


def test_generic_exception_still_returns_500(client: TestClient) -> None:
    """transient でない例外は従来通り 500 を返す (reset は走らない)。"""
    _install_test_routes(app)
    res = client.get("/__test/raise_generic")
    assert res.status_code == 500
    body = res.json()
    assert "transient" not in body
    assert res.headers.get("cache-control") == "no-store"


def test_aborted_returns_503_without_reset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    lab: Lab,
) -> None:
    """N3 (PR #82): Aborted は **reset しない** で 503 を返す。

    cascading reset を防ぐためのキモ。Lab / Firestore singleton が破棄
    されていない (= 次のリクエストが cold start にならない) ことを担保。
    Cloud Logging には `firestore.retriable` event が INFO で出る。
    """
    try:
        import google.api_core.exceptions  # noqa: F401
    except ImportError:
        pytest.skip("google-api-core not installed")

    _install_test_routes(app)
    monkeypatch.setattr(deps, "_labs", {"konishi-lab": lab})

    class _FakeClient:
        closed = False

        def close(self) -> None:
            type(self).closed = True

    fc = _FakeClient()
    monkeypatch.setattr(deps, "_firestore_db", fc)

    with caplog.at_level(logging.INFO, logger="app.main"):
        res = client.get("/__test/raise_aborted")

    assert res.status_code == 503
    body = res.json()
    assert body["transient"] is True
    assert res.headers.get("retry-after") == "1"
    assert res.headers.get("cache-control") == "no-store"

    # *singleton は破棄されていない* のが重要 (cascading reset 防止)
    assert "konishi-lab" in deps._labs
    assert deps._firestore_db is fc
    assert _FakeClient.closed is False

    # observability は client_reset でなく retriable event
    fields_list = [getattr(r, "_lv_fields", None) for r in caplog.records]
    events = [f["event"] for f in fields_list if isinstance(f, dict)]
    assert "firestore.retriable" in events
    assert "firestore.client_reset" not in events
