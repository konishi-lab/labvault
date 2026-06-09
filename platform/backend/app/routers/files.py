"""ファイル操作エンドポイント。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError

from ..auth import User, current_user, get_lab
from ..schemas import FileInfo, RecordDetail

router = APIRouter(prefix="/api/records/{record_id}/files", tags=["files"])


@router.get("", response_model=list[FileInfo])
def list_files(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> list[FileInfo]:
    """ファイル一覧を取得する。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    return [
        FileInfo(
            name=ref.name,
            content_type=ref.content_type,
            size_bytes=ref.size_bytes,
        )
        for ref in rec.list_data()
    ]


@router.post("", response_model=RecordDetail, status_code=201)
async def upload_file(
    record_id: str,
    file: UploadFile,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """ファイルをアップロードする。"""
    from ..routers.records import _to_detail

    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None

    rec.updated_by = user.email
    data = await file.read()
    rec.add(data, name=file.filename or "untitled")
    return _to_detail(rec)


@router.get("/{filename:path}")
def download_file(
    record_id: str,
    filename: str,
    download: bool = False,
    lab: Lab = Depends(get_lab),
) -> Response:
    """ファイルをダウンロード/表示する。?download=1 で強制ダウンロード。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    try:
        data = rec.get_data(filename)
    except FileNotFoundError:
        # メタデータに無い (= record.list_data に列挙されていない)。
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as exc:
        # Nextcloud 側で取得に失敗した。最も多いのは下記 2 ケース:
        #   - record メタデータには ref があるが、Nextcloud から実体が
        #     消えている / 別の path に動いた → NextcloudException(404)
        #   - 認証トークンの期限切れや権限不足 → NextcloudException(401/403)
        # nc_py_api 依存を関数内 import (テストで in-memory backend を使う
        # 経路で重たい import を起こさないため)。
        from nc_py_api import NextcloudException

        if isinstance(exc, NextcloudException):
            nc_status = getattr(exc, "status_code", 0) or 502
            # Nextcloud の 404 はクライアント向けには「ファイル本体が
            # ストレージから消えている」状態なので 410 Gone で返す方が
            # 意味が伝わる (record メタデータには残っているが取得不能)。
            http_status = 410 if nc_status == 404 else 502
            raise HTTPException(
                status_code=http_status,
                detail=(
                    f"Nextcloud fetch failed for {filename!r}: {exc}. "
                    "record メタデータには残っているが、Nextcloud 側で"
                    "ファイル本体が見つからない / 取得できない状態です。"
                ),
            ) from exc
        # その他は global handler で 500 (CORS-safe) になる。
        raise

    content_type = "application/octet-stream"
    for ref in rec.list_data():
        if ref.name == filename:
            content_type = ref.content_type or content_type
            break

    if download:
        disposition = "attachment"
    elif content_type.startswith("image/"):
        disposition = "inline"
    else:
        disposition = "attachment"

    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
