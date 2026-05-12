"""PlatformMetadataBackend (HTTP-based メタデータバックエンド) のユニットテスト。

httpx をモックして、PAT が ADC をスキップすること、各 read メソッドが正しい
URL/header/params で backend を呼ぶこと、404 が None に変換されることを確認する。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from labvault.backends.platform_client import (
    PAT_ENV,
    PlatformClient,
    PlatformNotFound,
)
from labvault.backends.platform_metadata import PlatformMetadataBackend


@pytest.fixture()
def captured_requests() -> list[httpx.Request]:
    return []


def _install_mock(
    monkeypatch: pytest.MonkeyPatch, responses: dict[tuple[str, str], Any]
) -> list[httpx.Request]:
    """httpx.request をモックして、(method, path) → response_data の辞書から返す。

    Returns captured request list (for assertions).
    """
    captured: list[httpx.Request] = []

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        # url から path を抽出
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path
        req = httpx.Request(
            method,
            url,
            **{k: v for k, v in kwargs.items() if k in {"headers", "params", "json"}},
        )
        captured.append(req)
        key = (method, path)
        if key not in responses:
            return httpx.Response(404, request=req, json={"detail": "not found"})
        body = responses[key]
        if isinstance(body, int):
            return httpx.Response(body, request=req)
        return httpx.Response(200, request=req, json=body)

    monkeypatch.setattr(httpx, "request", fake_request)
    return captured


class TestPlatformClientAuth:
    def test_pat_from_argument_skips_adc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """token 引数で PAT を渡せば ADC は呼ばれない。"""
        monkeypatch.delenv(PAT_ENV, raising=False)
        client = PlatformClient("https://example.test", token="lv_testtoken")
        # ADC が呼ばれていたら ImportError or 認証エラーになる。
        # 単に token を取れることだけ確認する。
        assert client._get_access_token() == "lv_testtoken"

    def test_pat_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(PAT_ENV, "lv_envtoken")
        client = PlatformClient("https://example.test")
        assert client._get_access_token() == "lv_envtoken"

    def test_request_sends_bearer_and_team(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _install_mock(monkeypatch, {("GET", "/api/foo"): {"ok": True}})
        client = PlatformClient("https://example.test", token="lv_x")
        result = client.get_dict("/api/foo", team="t1")
        assert result == {"ok": True}
        assert len(captured) == 1
        assert captured[0].headers["Authorization"] == "Bearer lv_x"
        assert captured[0].headers["X-Labvault-Team"] == "t1"

    def test_request_404_raises_PlatformNotFound(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_mock(monkeypatch, {})  # all paths return 404
        client = PlatformClient("https://example.test", token="lv_x")
        with pytest.raises(PlatformNotFound):
            client.get_dict("/api/missing", team="t1")


class TestPlatformMetadataReads:
    def test_get_record_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rec = {"id": "ABC123", "title": "hello", "team": "t1"}
        _install_mock(
            monkeypatch,
            {("GET", "/api/metadata/records/ABC123"): rec},
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        assert backend.get_record("t1", "ABC123") == rec

    def test_get_record_404_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_mock(monkeypatch, {})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        assert backend.get_record("t1", "GONE") is None

    def test_list_records_default_no_parent_filter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _install_mock(
            monkeypatch,
            {("GET", "/api/metadata/records"): [{"id": "A"}, {"id": "B"}]},
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        result = backend.list_records("t1")
        assert [r["id"] for r in result] == ["A", "B"]
        # default の場合は parent_id / parent_unset を送らない
        params = captured[0].url.params
        assert "parent_id" not in params
        assert "parent_unset" not in params

    def test_list_records_root_only_via_parent_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _install_mock(monkeypatch, {("GET", "/api/metadata/records"): []})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.list_records("t1", parent_id=None)
        assert captured[0].url.params.get("parent_unset") == "true"

    def test_list_records_with_specific_parent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _install_mock(monkeypatch, {("GET", "/api/metadata/records"): []})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.list_records("t1", parent_id="PARENT")
        assert captured[0].url.params.get("parent_id") == "PARENT"

    def test_list_records_with_tags_and_filters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _install_mock(monkeypatch, {("GET", "/api/metadata/records"): []})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.list_records(
            "t1",
            tags=["XRD", "Fe-Cr"],
            status="success",
            record_type="experiment",
            limit=50,
        )
        params = captured[0].url.params
        assert params["tags"] == "XRD,Fe-Cr"
        assert params["status"] == "success"
        assert params["type"] == "experiment"
        assert params["limit"] == "50"

    def test_get_cell_logs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rows = [{"cell_id": "c1", "cell_number": 1}]
        captured = _install_mock(
            monkeypatch, {("GET", "/api/metadata/records/R1/cell_logs"): rows}
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        assert backend.get_cell_logs("t1", "R1", limit=50) == rows
        assert captured[0].url.params["limit"] == "50"

    def test_get_template_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        tmpl = {"name": "exp_xrd", "fields": []}
        _install_mock(monkeypatch, {("GET", "/api/metadata/templates/exp_xrd"): tmpl})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        assert backend.get_template("t1", "exp_xrd") == tmpl

    def test_get_template_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_mock(monkeypatch, {})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        assert backend.get_template("t1", "missing") is None

    def test_list_templates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_mock(
            monkeypatch,
            {("GET", "/api/metadata/templates"): [{"name": "a"}, {"name": "b"}]},
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        result = backend.list_templates("t1")
        assert [t["name"] for t in result] == ["a", "b"]


class TestPlatformMetadataWrites:
    """write 系メソッドの HTTP 呼び出し。"""

    def test_create_record_posts_with_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(monkeypatch, {("POST", "/api/metadata/records"): None})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.create_record("t1", {"id": "REC1", "title": "hi"})
        assert captured[0].method == "POST"
        # body を読む
        import json

        body = json.loads(captured[0].read())
        assert body["id"] == "REC1"
        assert body["title"] == "hi"

    def test_create_record_requires_id(self) -> None:
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        with pytest.raises(ValueError, match="id"):
            backend.create_record("t1", {"title": "no id"})

    def test_create_record_serializes_datetime(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import datetime as dt
        import json

        captured = _install_mock(monkeypatch, {("POST", "/api/metadata/records"): None})
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        now = dt.datetime(2026, 5, 12, 12, 0, tzinfo=dt.UTC)
        backend.create_record(
            "t1",
            {"id": "X", "created_at": now, "notes": [{"created_at": now}]},
        )
        body = json.loads(captured[0].read())
        assert body["created_at"] == now.isoformat()
        assert body["notes"][0]["created_at"] == now.isoformat()

    def test_update_record_patches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(
            monkeypatch, {("PATCH", "/api/metadata/records/REC1"): None}
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.update_record("t1", "REC1", {"status": "success"})
        assert captured[0].method == "PATCH"

    def test_delete_record_deletes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(
            monkeypatch, {("DELETE", "/api/metadata/records/R1"): None}
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.delete_record("t1", "R1")
        assert captured[0].method == "DELETE"

    def test_delete_record_404_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_mock(monkeypatch, {})  # all 404
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        # 404 でも例外を出さない (Firestore の delete も冪等)
        backend.delete_record("t1", "GONE")

    def test_save_cell_log_generates_cell_id_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured = _install_mock(
            monkeypatch,
            {("POST", "/api/metadata/records/R1/cell_logs"): {"cell_id": "abc"}},
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        data: dict[str, Any] = {"cell_number": 1}
        backend.save_cell_log("t1", "R1", data)
        # SDK 側で生成した cell_id が dict に入る
        assert "cell_id" in data
        body = json.loads(captured[0].read())
        assert body["cell_id"]  # 何らかの値

    def test_save_cell_log_keeps_existing_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured = _install_mock(
            monkeypatch,
            {("POST", "/api/metadata/records/R1/cell_logs"): {"cell_id": "explicit"}},
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.save_cell_log("t1", "R1", {"cell_id": "explicit", "cell_number": 1})
        body = json.loads(captured[0].read())
        assert body["cell_id"] == "explicit"

    def test_save_template_puts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(
            monkeypatch, {("PUT", "/api/metadata/templates/exp_xrd"): None}
        )
        client = PlatformClient("https://example.test", token="lv_x")
        backend = PlatformMetadataBackend(client)
        backend.save_template("t1", "exp_xrd", {"fields": []})
        assert captured[0].method == "PUT"
