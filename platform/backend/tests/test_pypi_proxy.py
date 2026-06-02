"""PyPI proxy (`/api/pypi/*`) のテスト。

カバー範囲:
- Basic Auth が無いと 401 + WWW-Authenticate
- username が `__token__` でないと 401
- password が空 / 形式不正 → 401
- `_verify_pat` が None を返す PAT → 401
- 有効な PAT で `/simple/` → 200 + 配信パッケージ一覧
- `/simple/labvault/` → 200 + AR から取った HTML が proxy URL に rewrite される
- `/simple/<unknown>/` → 404 (ALLOWED_PACKAGES 外)
- `/files/<不正な filename>` → 400
- `/files/<unknown-package>-1.0.0.whl` → 404
- AR から 200 + bytes 返るときに stream が完走する

AR への httpx 呼び出しは `monkeypatch` で stub する (実 AR には触らない)。
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import FakeDB


def _basic(user: str, password: str) -> str:
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()


@pytest.fixture()
def client(fake_db: FakeDB) -> Iterator[TestClient]:
    """auth dependency_overrides は **無し** で生の TestClient を返す。
    pypi proxy は Basic Auth を独自で検証するため、dev_skip も干渉させない。"""
    from app.main import app

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def stub_pat(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """`_verify_pat` を辞書 lookup で差し替える。

    返り値の dict に `{"lv_good": "email"}` のように key=PAT, value=email を
    入れることでテストごとに valid PAT を増減できる。
    """
    valid: dict[str, str] = {}

    def fake(token: str) -> Any:
        email = valid.get(token)
        if email is None:
            return None

        class _PatUser:
            uid = email
            email_attr = email
            display_name = email

        return _PatUser()

    monkeypatch.setattr("app.routers.pypi_proxy._verify_pat", fake)
    return valid


@pytest.fixture()
def stub_ar(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """`_ar_access_token` / `httpx.get` / `httpx.Client` を差し替える。

    呼出し履歴と返却内容は dict に保存。テストごとに `ar["responses"]` で
    URL ごとのレスポンスを設定。
    """
    state: dict[str, Any] = {"calls": [], "responses": {}}

    monkeypatch.setattr(
        "app.routers.pypi_proxy._ar_access_token", lambda: "fake-ar-token"
    )

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        state["calls"].append(("GET-simple", url, kwargs.get("headers")))
        resp = state["responses"].get(url)
        if resp is None:
            return httpx.Response(404, text="not found")
        return resp

    monkeypatch.setattr("app.routers.pypi_proxy.httpx.get", fake_get)

    # /files/ では httpx.Client + .send(stream=True) を使う。簡略のため
    # Client クラスごと置換し、send で StreamingResponse の元になるダミー
    # を返す。
    class _FakeStreamedResponse:
        def __init__(self, status_code: int, content: bytes = b"") -> None:
            self.status_code = status_code
            self._content = content
            self.headers: dict[str, str] = {"Content-Length": str(len(content))}

        def iter_bytes(self, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
            yield self._content

        def close(self) -> None:
            pass

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def build_request(
            self, method: str, url: str, **_kwargs: Any
        ) -> tuple[str, str]:
            return (method, url)

        def send(
            self, req: tuple[str, str], stream: bool = False
        ) -> _FakeStreamedResponse:
            _ = stream  # not used in fake
            _, url = req
            state["calls"].append(("GET-file", url))
            resp = state["responses"].get(url)
            if resp is None:
                return _FakeStreamedResponse(404)
            assert isinstance(resp, _FakeStreamedResponse)
            return resp

        def close(self) -> None:
            pass

    monkeypatch.setattr("app.routers.pypi_proxy.httpx.Client", _FakeClient)
    state["_FakeStreamedResponse"] = _FakeStreamedResponse
    return state


# ----------------------------------------------------------------------
# 認証境界
# ----------------------------------------------------------------------


def test_pypi_index_requires_basic(client: TestClient) -> None:
    res = client.get("/api/pypi/simple/")
    assert res.status_code == 401
    assert "Basic" in res.headers.get("WWW-Authenticate", "")


def test_pypi_index_rejects_wrong_username(
    client: TestClient, stub_pat: dict[str, str]
) -> None:
    stub_pat["lv_good"] = "alice@example.com"
    res = client.get(
        "/api/pypi/simple/", headers={"Authorization": _basic("alice", "lv_good")}
    )
    assert res.status_code == 401
    assert "__token__" in res.json()["detail"]


def test_pypi_index_rejects_empty_password(client: TestClient) -> None:
    res = client.get(
        "/api/pypi/simple/", headers={"Authorization": _basic("__token__", "")}
    )
    assert res.status_code == 401


def test_pypi_index_rejects_invalid_pat(
    client: TestClient, stub_pat: dict[str, str]
) -> None:
    # stub_pat に登録していない token → _verify_pat が None
    res = client.get(
        "/api/pypi/simple/",
        headers={"Authorization": _basic("__token__", "lv_unknown")},
    )
    assert res.status_code == 401


def test_pypi_index_accepts_valid_pat(
    client: TestClient, stub_pat: dict[str, str]
) -> None:
    stub_pat["lv_good"] = "alice@example.com"
    res = client.get(
        "/api/pypi/simple/",
        headers={"Authorization": _basic("__token__", "lv_good")},
    )
    assert res.status_code == 200
    assert "labvault" in res.text


# ----------------------------------------------------------------------
# /simple/{package}/
# ----------------------------------------------------------------------


def test_pypi_package_unknown_404(client: TestClient, stub_pat: dict[str, str]) -> None:
    stub_pat["lv_good"] = "alice@example.com"
    res = client.get(
        "/api/pypi/simple/numpy/",
        headers={"Authorization": _basic("__token__", "lv_good")},
    )
    assert res.status_code == 404


def test_pypi_package_rewrites_hrefs(
    client: TestClient,
    stub_pat: dict[str, str],
    stub_ar: dict[str, Any],
) -> None:
    stub_pat["lv_good"] = "alice@example.com"
    # AR の simple ページを stub
    ar_html = """<!DOCTYPE html><html><body>
<a href="https://asia-northeast1-python.pkg.dev/p/r/labvault/labvault-0.1.2-py3-none-any.whl#sha256=abc">labvault-0.1.2-py3-none-any.whl</a>
</body></html>"""
    from app.routers.pypi_proxy import _ar_base

    stub_ar["responses"][f"{_ar_base()}/simple/labvault/"] = httpx.Response(
        200, text=ar_html
    )

    res = client.get(
        "/api/pypi/simple/labvault/",
        headers={"Authorization": _basic("__token__", "lv_good")},
    )
    assert res.status_code == 200
    # href が proxy URL に書き換えられている (オリジン抜き)
    assert (
        'href="/api/pypi/files/labvault-0.1.2-py3-none-any.whl#sha256=abc"' in res.text
    )
    # オリジナルの AR URL は残っていない
    assert "asia-northeast1-python.pkg.dev" not in res.text


# ----------------------------------------------------------------------
# /files/{filename}
# ----------------------------------------------------------------------


def test_pypi_file_invalid_filename_400(
    client: TestClient, stub_pat: dict[str, str]
) -> None:
    """filename に空白や許可外文字 (例: スペース) → 400。

    (path traversal `../` は FastAPI のルーターが path normalize するため
    そもそも `/api/pypi/files/...` にマッチしない別経路で 404 になる。
    ここでは validator 側で弾く例として「許可文字以外」を使う。)
    """
    stub_pat["lv_good"] = "alice@example.com"
    res = client.get(
        "/api/pypi/files/labvault%20bad.whl",
        headers={"Authorization": _basic("__token__", "lv_good")},
    )
    assert res.status_code == 400


def test_pypi_file_unknown_package_404(
    client: TestClient, stub_pat: dict[str, str]
) -> None:
    stub_pat["lv_good"] = "alice@example.com"
    res = client.get(
        "/api/pypi/files/numpy-1.0.0-py3-none-any.whl",
        headers={"Authorization": _basic("__token__", "lv_good")},
    )
    assert res.status_code == 404


def test_pypi_file_streams_content(
    client: TestClient,
    stub_pat: dict[str, str],
    stub_ar: dict[str, Any],
) -> None:
    stub_pat["lv_good"] = "alice@example.com"
    fake_wheel = b"PK\x03\x04fake-zip-content"
    from app.routers.pypi_proxy import _ar_base

    stub_ar["responses"][f"{_ar_base()}/labvault/labvault-0.1.2-py3-none-any.whl"] = (
        stub_ar["_FakeStreamedResponse"](200, fake_wheel)
    )

    res = client.get(
        "/api/pypi/files/labvault-0.1.2-py3-none-any.whl",
        headers={"Authorization": _basic("__token__", "lv_good")},
    )
    assert res.status_code == 200
    assert res.content == fake_wheel
    # AR access に backend SA token が乗っているかは AR fixture 側の責務
