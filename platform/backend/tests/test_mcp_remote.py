"""``/mcp`` Streamable HTTP エンドポイントの統合テスト。

PAT 認証 middleware + lab_provider 経由のツール呼び出しが round-trip するかを
確認する (MCP プロトコルの正しさそのものは ``mcp`` パッケージに任せる)。

Lab は InMemory 系で組み立てて ``get_lab_for_team`` を差し替える。"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from app.main import app
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    """``konishi-lab`` 用の InMemory Lab を 1 件レコード入りで返す。

    Lab 構築で env 由来の Firestore / Vertex AI バックエンドを掴まないよう、
    関連 env を空に倒してから組み立てる。"""
    for key in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(key, "")
    lab = Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )
    rec = lab.new("xrd-test", auto_log=False)
    rec.tag("xrd")
    rec.conditions(power=50)
    return lab


@pytest.fixture()
def mcp_client(
    monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab
) -> Iterator[TestClient]:
    """``get_lab_for_team`` を seeded_lab で差し替えた TestClient。

    ``LABVAULT_DEV_SKIP_AUTH=1`` (conftest が立てる) により認証 middleware は
    dev ユーザ (``konishi-lab``) で短絡する。
    """
    monkeypatch.setattr(
        "app.routers.mcp.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


def _post_mcp(
    client: TestClient, payload: dict, headers: dict | None = None
) -> tuple[int, dict | None]:
    """``POST /mcp`` で JSON-RPC を送り、SSE レスポンスから JSON を 1 件取り出す。

    Streamable HTTP は ``text/event-stream`` で返してくるため、最初の ``data:``
    行を JSON として decode する (stateless モード)。
    """
    h = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if headers:
        h.update(headers)
    resp = client.post("/mcp", content=json.dumps(payload), headers=h)
    if resp.status_code >= 400:
        return resp.status_code, None
    body = resp.text
    for line in body.splitlines():
        if line.startswith("data:"):
            return resp.status_code, json.loads(line[len("data:") :].strip())
    # 純 JSON 応答の場合
    return resp.status_code, resp.json() if body else None


def _initialize(client: TestClient) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    status, data = _post_mcp(client, payload)
    assert status == 200, f"initialize failed: {status}"
    assert data is not None and "result" in data, data
    return data["result"]


def test_initialize_smoke(mcp_client: TestClient) -> None:
    """initialize で serverInfo が返ること。"""
    result = _initialize(mcp_client)
    assert result["serverInfo"]["name"] == "labvault"


def test_tools_list_includes_search(mcp_client: TestClient) -> None:
    """tools/list で 7 ツールが揃っていること。"""
    _initialize(mcp_client)
    status, data = _post_mcp(
        mcp_client,
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert status == 200
    assert data is not None
    names = {t["name"] for t in data["result"]["tools"]}
    assert {
        "search",
        "get_detail",
        "compare",
        "data_preview",
        "aggregate",
        "get_overview",
        "get_timeline",
    } <= names


def test_search_returns_seeded_record(mcp_client: TestClient) -> None:
    """tools/call search が seeded_lab のレコードを返すこと。lab_provider が
    middleware で bind された context から正しく ``konishi-lab`` の Lab を引けて
    いる証拠になる。"""
    _initialize(mcp_client)
    status, data = _post_mcp(
        mcp_client,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "search", "arguments": {"tags": ["xrd"]}},
        },
    )
    assert status == 200
    assert data is not None, data
    payload = data["result"]
    # FastMCP は list 戻り値を 1 要素ごとに content[i] (text=JSON) に展開する。
    items = [json.loads(c["text"]) for c in payload["content"]]
    assert len(items) == 1, items
    assert items[0]["title"] == "xrd-test"
    assert items[0]["tags"] == ["xrd"]


def test_missing_authorization_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """LABVAULT_DEV_SKIP_AUTH を外すと Authorization 無しは 401。"""
    monkeypatch.delenv("LABVAULT_DEV_SKIP_AUTH", raising=False)
    with TestClient(app) as c:
        resp = c.post(
            "/mcp",
            content="{}",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 401
    assert "Authorization" in resp.json()["error"]


def test_non_pat_bearer_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """``lv_`` で始まらない Bearer (Firebase / Google ADC) は 401。

    PAT 専用路線。Web UI 認証は ``/api/*`` 側のみ。"""
    monkeypatch.delenv("LABVAULT_DEV_SKIP_AUTH", raising=False)
    with TestClient(app) as c:
        resp = c.post(
            "/mcp",
            content="{}",
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Authorization": "Bearer ya29.fakegoogle",
            },
        )
    assert resp.status_code == 401
    assert "lv_" in resp.json()["error"]
