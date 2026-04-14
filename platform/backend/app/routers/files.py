"""ファイル操作エンドポイント。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError

from ..dependencies import get_lab
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
) -> RecordDetail:
    """ファイルをアップロードする。"""
    from ..routers.records import _to_detail

    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

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
        raise HTTPException(status_code=404, detail="File not found")

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
