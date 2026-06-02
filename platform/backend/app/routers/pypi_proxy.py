"""PEP 503 compatible PyPI proxy authenticated by labvault PAT.

装置 PC / CI などで gcloud (Artifact Registry reader) を持たずに
labvault SDK を pip install できるようにする。

pip からの使い方:

    pip install \\
      --index-url https://pypi.org/simple/ \\
      --extra-index-url https://__token__:lv_xxx@labvault-api-.../api/pypi/simple/ \\
      "labvault[gcp,nextcloud]"

- 認証は HTTP Basic Auth: username 固定 `__token__`、password が labvault PAT
- backend SA が Artifact Registry に access して wheel を取得 → client に
  stream で返す (redirect は backend 側で吸収)
- 配信パッケージは `ALLOWED_PACKAGES` に絞り、典型的なタイポや探索を遮断
"""

from __future__ import annotations

import base64
import logging
import os
import re
from collections.abc import Iterator
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx
from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import HTMLResponse, StreamingResponse

from ..artifact_registry import AR_SCOPE
from ..auth import _verify_pat

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pypi", tags=["pypi"])

# 配信を許可するパッケージ。タイポや探索を遮断する。
ALLOWED_PACKAGES: frozenset[str] = frozenset({"labvault"})

# AR Python repo の base URL。env で上書き可。
AR_PYPI_BASE_ENV = "LABVAULT_AR_PYPI_BASE"
_DEFAULT_AR_PYPI_BASE = (
    "https://asia-northeast1-python.pkg.dev/klab-laser-process/labvault-pypi"
)


def _ar_base() -> str:
    return (os.environ.get(AR_PYPI_BASE_ENV) or _DEFAULT_AR_PYPI_BASE).rstrip("/")


def _ar_access_token() -> str:
    """backend SA で AR にアクセスするための access token。"""
    creds, _ = google.auth.default(scopes=[AR_SCOPE])
    creds.refresh(google.auth.transport.requests.Request())
    token: str | None = getattr(creds, "token", None)
    if not token:
        raise HTTPException(status_code=502, detail="failed to obtain AR token")
    return token


def _require_pat(authorization: str | None) -> None:
    """HTTP Basic Auth (`__token__:<lv_pat>`) を検証する。

    失敗時は 401 + WWW-Authenticate ヘッダで pip に再送を促す。
    """
    if not authorization or not authorization.lower().startswith("basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Basic auth required. Use username '__token__' and your "
                "labvault PAT (lv_*) as password."
            ),
            headers={"WWW-Authenticate": 'Basic realm="labvault-pypi"'},
        )
    try:
        decoded = base64.b64decode(authorization.split(" ", 1)[1]).decode(
            "utf-8", errors="replace"
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Basic auth") from e

    user, sep, password = decoded.partition(":")
    if not sep:
        raise HTTPException(status_code=401, detail="Invalid Basic auth (missing ':')")
    if user != "__token__":
        raise HTTPException(status_code=401, detail="Username must be '__token__'")
    password = password.strip()
    if not password:
        raise HTTPException(status_code=401, detail="Empty password")

    # 既存の PAT 検証ロジックを再利用する (auth.py)。失敗時 None。
    pat_user = _verify_pat(password)
    if pat_user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or revoked PAT",
            headers={"WWW-Authenticate": 'Basic realm="labvault-pypi"'},
        )


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------


@router.get("/simple/", response_class=HTMLResponse)
def pypi_index(authorization: str | None = Header(default=None)) -> HTMLResponse:
    """PEP 503 root index. 配信パッケージへのリンクを返す。"""
    _require_pat(authorization)
    body = "".join(f'<a href="{p}/">{p}</a><br/>\n' for p in sorted(ALLOWED_PACKAGES))
    html = (
        "<!DOCTYPE html><html><head><title>labvault-pypi</title></head>"
        f"<body>{body}</body></html>"
    )
    return HTMLResponse(html)


@router.get("/simple/{package}/", response_class=HTMLResponse)
def pypi_package(
    package: str, authorization: str | None = Header(default=None)
) -> HTMLResponse:
    """指定パッケージの simple ページ。AR から取って href を proxy URL に rewrite。"""
    _require_pat(authorization)
    if package not in ALLOWED_PACKAGES:
        raise HTTPException(
            status_code=404, detail=f"package not available: {package!r}"
        )

    url = f"{_ar_base()}/simple/{package}/"
    token = _ar_access_token()
    try:
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
    except httpx.HTTPError as e:
        logger.exception("AR simple page fetch failed")
        raise HTTPException(status_code=502, detail=f"AR proxy error: {e}") from e
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"package not in AR: {package!r}")
    if resp.status_code != 200:
        logger.warning(
            "AR simple page returned %s: %s", resp.status_code, resp.text[:200]
        )
        raise HTTPException(status_code=502, detail=f"AR returned {resp.status_code}")

    # AR の href は wheel への完全 URL なので、`/api/pypi/files/{filename}` に
    # 書き換える。fragment (#sha256=...) は保持。
    pattern = re.compile(r'href="([^"]+)"')

    def rewrite(match: re.Match[str]) -> str:
        full = match.group(1)
        path, sep, fragment = full.partition("#")
        filename = path.rsplit("/", 1)[-1]
        new = f"/api/pypi/files/{filename}"
        if sep:
            new += "#" + fragment
        return f'href="{new}"'

    rewritten = pattern.sub(rewrite, resp.text)
    return HTMLResponse(rewritten)


# 安全なファイル名形式: 英数 + . _ - + のみ。長さ制限。
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._+\-]+$")


@router.get("/files/{filename}")
def pypi_file(
    filename: str, authorization: str | None = Header(default=None)
) -> StreamingResponse:
    """wheel / sdist を AR から取得して stream で返す。"""
    _require_pat(authorization)
    if not filename or len(filename) > 200 or not _FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    # filename の先頭から package 名を抽出 (labvault-0.1.2-... → labvault)。
    package = filename.split("-", 1)[0].lower()
    if package not in ALLOWED_PACKAGES:
        raise HTTPException(
            status_code=404, detail=f"package not available: {package!r}"
        )

    url = f"{_ar_base()}/{package}/{filename}"
    token = _ar_access_token()

    # status pre-check + stream で返す。stream の中で例外を上げると FastAPI 側で
    # 既にヘッダが送られているので 200 のまま中断する。先に GET で status を
    # 確認し、200 ならそのまま body を stream する。
    client = httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        req = client.build_request(
            "GET", url, headers={"Authorization": f"Bearer {token}"}
        )
        response = client.send(req, stream=True)
    except httpx.HTTPError as e:
        client.close()
        logger.exception("AR file fetch failed")
        raise HTTPException(status_code=502, detail=f"AR proxy error: {e}") from e

    if response.status_code == 404:
        response.close()
        client.close()
        raise HTTPException(status_code=404, detail=f"file not found: {filename}")
    if response.status_code != 200:
        response.close()
        client.close()
        raise HTTPException(
            status_code=502, detail=f"AR returned {response.status_code}"
        )

    def iter_chunks() -> Iterator[bytes]:
        try:
            yield from response.iter_bytes(chunk_size=64 * 1024)
        finally:
            response.close()
            client.close()

    headers: dict[str, Any] = {
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    content_length = response.headers.get("Content-Length")
    if content_length:
        headers["Content-Length"] = content_length
    return StreamingResponse(
        iter_chunks(),
        media_type="application/octet-stream",
        headers=headers,
    )
