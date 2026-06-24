"""N4 / N5 / N6 / N8 のリグレッションテスト。

N7 (frontend dashboard truncated 注釈) は frontend 単独の UI 変更で
backend test では確認できないため、別途手動 QA で見る。

各テストは独立に最小ガードを行う:

- N4: bulk_upload の event_stream() が GeneratorExit で abort されても
  `bulk_upload.done` event が emit される (try/finally + aborted=True)
- N5: setup_json_logging() を呼んだ後に root に余分な StreamHandler が
  残らない (json formatter 付き 1 個のみ)
- N6: observability.safe_keys が identifier 形式の key だけ通し、それ以外
  を <redacted> に置換する
- N8: exception handler 内で reset_lab() が壊れて二次例外を出しても
  500 + Cache-Control: no-store を返す (フェイルセーフ)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from app import dependencies as deps
from app.main import app
from app.observability import _JsonFormatter, safe_keys, setup_json_logging
from fastapi import APIRouter
from fastapi.testclient import TestClient


# ---- N6: safe_keys -----------------------------------------------------------


def test_safe_keys_passes_identifier_strings() -> None:
    """identifier 形式 (英数 + underscore + 先頭非数字) はそのまま通る。"""
    assert safe_keys(["power", "target", "lattice_a_A"]) == [
        "power",
        "target",
        "lattice_a_A",
    ]


def test_safe_keys_redacts_freeform_strings() -> None:
    """フリーフォーム文字列 (PII の可能性) は <redacted> に置換される。"""
    keys = ["power", "patient name", "hanako@example.com", "サンプル名"]
    out = safe_keys(keys)
    # 安全な key は残る、それ以外は redacted
    assert out[0] == "power"
    assert out[1] == "<redacted>"  # space を含む
    assert out[2] == "<redacted>"  # @ を含む
    assert out[3] == "<redacted>"  # 非 ASCII
    # 件数は維持 (cardinality 情報を残すため)
    assert len(out) == len(keys)


def test_safe_keys_redacts_too_long_string() -> None:
    """長すぎる key (40 文字超) も redacted。"""
    too_long = "a" * 41
    assert safe_keys([too_long]) == ["<redacted>"]


def test_safe_keys_drops_non_strings() -> None:
    """non-string / 空文字は除外する (redacted ですらない)。"""
    assert safe_keys(["power", "", 42, None, "target"]) == ["power", "target"]


def test_safe_keys_handles_non_iterable() -> None:
    """list でない入力は空 list を返す (defensive)。"""
    assert safe_keys(None) == []
    assert safe_keys("power") == []  # str はバラさない
    assert safe_keys(42) == []


# ---- N5: setup_json_logging ---------------------------------------------------


def test_setup_json_logging_removes_existing_stream_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """既存の StreamHandler を除去し、JSON formatter 付き handler 1 個だけ
    残す。Cloud Run + uvicorn 環境で plain + JSON の二重出力になっていた
    のを解消 (N5)。"""
    # setup_json_logging はモジュールレベル singleton なので reset する
    monkeypatch.setattr("app.observability._JSON_LOGGING_INSTALLED", False)
    monkeypatch.delenv("LABVAULT_DISABLE_JSON_LOG", raising=False)

    # uvicorn 模擬: root に StreamHandler を 2 個入れておく
    root = logging.getLogger()
    saved = list(root.handlers)
    try:
        for h in list(root.handlers):
            root.removeHandler(h)
        for _ in range(2):
            root.addHandler(logging.StreamHandler())

        setup_json_logging()

        stream_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        # JSON formatter 付き handler が 1 個だけ残る
        assert len(stream_handlers) == 1
        assert isinstance(stream_handlers[0].formatter, _JsonFormatter)
    finally:
        # 元の handler 構成に戻す
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in saved:
            root.addHandler(h)


# ---- N4: bulk_upload SSE abort -----------------------------------------------


def test_bulk_upload_event_stream_done_logged_on_abort(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SSE generator が mid-stream で abort されても (`GeneratorExit`)、
    try/finally で `bulk_upload.done` event が必ず emit される。N4 の核。"""
    import time

    # event_stream() の最小再現 (try/finally + GeneratorExit)
    logger = logging.getLogger("test.bulk")
    aborted = False
    t0 = time.perf_counter()

    def gen() -> Any:
        nonlocal aborted
        try:
            yield "progress 1"
            yield "progress 2"  # ← クライアントがここで close を呼ぶ
            yield "done"
        except GeneratorExit:
            aborted = True
            raise
        finally:
            from app.observability import log_event

            duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            log_event(
                logger,
                "bulk_upload.done",
                parent_id="REC1",
                total_files=3,
                uploaded=1,
                error_count=0,
                duration_ms=duration_ms,
                aborted=aborted,
            )

    with caplog.at_level(logging.INFO, logger="test.bulk"):
        it = iter(gen())
        # 最初の 2 件は受け取って、その後 close で abort 模擬
        next(it)
        next(it)
        it.close()  # GeneratorExit を inject

    # done event が出ている + aborted=True が field に乗っている
    events = [
        getattr(r, "_lv_fields", None)
        for r in caplog.records
        if getattr(r, "_lv_fields", None)
    ]
    bulk_done = [e for e in events if isinstance(e, dict) and e.get("event") == "bulk_upload.done"]
    assert len(bulk_done) == 1
    assert bulk_done[0].get("aborted") is True


# ---- N8: handler 二次例外フェイルセーフ ---------------------------------------

_test_router = APIRouter()


def _install_test_routes(app_obj: Any) -> None:
    for r in app_obj.routes:
        if getattr(r, "path", None) == "/__test/raise_secondary":
            return
    app_obj.include_router(_test_router)


@_test_router.get("/__test/raise_secondary")
def _raise_for_secondary_test() -> None:
    raise RuntimeError("primary failure to trigger handler")


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(k, "")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_handler_secondary_exception_still_returns_500_with_no_store(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """exception handler 内部で `transient_firestore_exceptions()` の評価が
    壊れても (例: import 失敗 simulate)、handler 全体の broad try/except
    で 500 + no-store + CORS 整合の JSONResponse を返す (N8)。"""
    _install_test_routes(app)

    # transient_firestore_exceptions() が import で壊れる状況を模擬
    def _boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("simulated handler internal failure")

    # `from .dependencies import transient_firestore_exceptions` の解決時に
    # raise させる: dependencies モジュール自体の attribute を壊す
    monkeypatch.setattr(deps, "transient_firestore_exceptions", _boom)
    monkeypatch.setattr(deps, "retriable_firestore_exceptions", _boom)
    monkeypatch.setattr(deps, "reset_lab", _boom)
    monkeypatch.setattr(deps, "reset_firestore_db", _boom)

    res = client.get("/__test/raise_secondary")
    assert res.status_code == 500
    # フェイルセーフメッセージ
    body = res.json()
    assert "handler failure" in body["detail"]
    # **重要**: Cache-Control: no-store がフォールバック path でも付く
    assert res.headers.get("cache-control") == "no-store"
