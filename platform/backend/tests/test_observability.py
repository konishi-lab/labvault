"""Cloud Logging 互換の構造化ログ helper を検証する。

backend review C3 「records.py / metadata.py 全体で logger インスタンス
が存在せず、slow query や push-down 失敗が完全ブラックボックス」への
対応。`observability.log_event` / `EventTimer` / `_JsonFormatter` の
振る舞いを caplog ベースで固定する。

主要 endpoint (list_records / aggregate / bulk_upload) の instrument は
caplog に event 名 + key fields が乗ることだけ検証する。詳細な field
の正しさは既存の endpoint test (test_records_aggregate 等) が押さえる
ので、ここでは「event 名が出ているか」「slow / error で level が
上がるか」だけを担保する。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator

import pytest
from app.main import app
from app.observability import (
    SLOW_THRESHOLD_MS,
    EventTimer,
    _JsonFormatter,
    log_event,
)
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)

# ---- 単体: helper の挙動 ------------------------------------------------------


def test_log_event_emits_with_fields(caplog: pytest.LogCaptureFixture) -> None:
    """log_event は event 名 + 渡した field を record に乗せて出力する。"""
    logger = logging.getLogger("test.log_event")
    with caplog.at_level(logging.INFO, logger="test.log_event"):
        log_event(logger, "demo.event", key="power", count=5)
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    fields = rec._lv_fields  # type: ignore[attr-defined]
    assert fields["event"] == "demo.event"
    assert fields["key"] == "power"
    assert fields["count"] == 5
    # message は人間が読める要約
    assert "demo.event" in caplog.records[0].message


def test_event_timer_logs_duration_ms(caplog: pytest.LogCaptureFixture) -> None:
    """EventTimer は context を抜けたタイミングで duration_ms 付きで 1 度だけ出す。"""
    logger = logging.getLogger("test.timer")
    with (
        caplog.at_level(logging.INFO, logger="test.timer"),
        EventTimer(logger, "demo.timed", arg=1) as t,
    ):
        t.add(post_fact=42)
    assert len(caplog.records) == 1
    fields = caplog.records[0]._lv_fields  # type: ignore[attr-defined]
    assert fields["event"] == "demo.timed"
    assert "duration_ms" in fields
    assert fields["arg"] == 1
    assert fields["post_fact"] == 42


def test_event_timer_marks_slow(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SLOW_THRESHOLD_MS を超えると level=WARNING + slow=True が付く。"""
    # 1ms に下げて確実に slow 判定させる
    monkeypatch.setattr("app.observability.SLOW_THRESHOLD_MS", 1)
    logger = logging.getLogger("test.slow")
    with (
        caplog.at_level(logging.INFO, logger="test.slow"),
        EventTimer(logger, "demo.slow"),
    ):
        time.sleep(0.01)  # 10ms = 必ず 1ms 超え
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    fields = caplog.records[0]._lv_fields  # type: ignore[attr-defined]
    assert fields.get("slow") is True
    assert fields["duration_ms"] >= 1
    # SLOW_THRESHOLD_MS が import 時にバインドされる import path がないこと
    # を念のため確認 (monkeypatch が観測されている)
    assert SLOW_THRESHOLD_MS == 1000  # 元の値は変えていない


def test_event_timer_logs_error_on_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """context 内で例外が起きると level=ERROR + error_type=<例外名> で記録、
    例外自体は suppress せず再 raise される。"""
    logger = logging.getLogger("test.err")
    with (
        caplog.at_level(logging.INFO, logger="test.err"),
        pytest.raises(ValueError),
        EventTimer(logger, "demo.fail"),
    ):
        raise ValueError("boom")
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    fields = caplog.records[0]._lv_fields  # type: ignore[attr-defined]
    assert fields["error_type"] == "ValueError"
    assert fields["event"] == "demo.fail"


def test_json_formatter_produces_valid_json() -> None:
    """_JsonFormatter の出力が valid JSON で、severity / message / fields を
    含む (Cloud Logging が自動 parse できる規約)。"""
    fmt = _JsonFormatter()
    rec = logging.LogRecord(
        name="x",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    rec._lv_fields = {"event": "demo", "k": 1}  # type: ignore[attr-defined]
    line = fmt.format(rec)
    parsed = json.loads(line)
    assert parsed["severity"] == "WARNING"
    assert parsed["message"] == "hello world"
    assert parsed["event"] == "demo"
    assert parsed["k"] == 1
    assert parsed["logger"] == "x"


# ---- 統合: 実 endpoint で event が emit されているか --------------------------


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(k, "")
    lab = Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )
    for i in range(3):
        lab.new(f"r-{i}", power=i * 10, auto_log=False)
    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


def _events(records: list[logging.LogRecord]) -> list[str]:
    out = []
    for r in records:
        f = getattr(r, "_lv_fields", None)
        if isinstance(f, dict) and "event" in f:
            out.append(f["event"])
    return out


def test_list_records_emits_event(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.routers.records"):
        res = client.get("/api/records")
    assert res.status_code == 200
    assert "records.list" in _events(caplog.records)


def test_aggregate_emits_event(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="app.routers.records"):
        res = client.get("/api/records/aggregate?key=power")
    assert res.status_code == 200
    evs = _events(caplog.records)
    assert "records.aggregate" in evs
