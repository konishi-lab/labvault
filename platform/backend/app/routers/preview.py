"""ファイルプレビューエンドポイント。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError

from ..dependencies import get_lab

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/records/{record_id}/preview", tags=["preview"]
)


def _nc_download(lab: Lab, nc_path: str) -> bytes | None:
    """Nextcloud からパスを直接指定してダウンロードする。"""
    import io

    try:
        nc = lab._storage._get_client()
        buf = io.BytesIO()
        nc.files.download2stream(nc_path, buf)
        return buf.getvalue()
    except Exception:
        return None


def _nc_upload(lab: Lab, nc_path: str, data: bytes) -> None:
    """Nextcloud にパスを直接指定してアップロードする。"""
    try:
        nc = lab._storage._get_client()
        parent = "/".join(nc_path.split("/")[:-1])
        if parent:
            nc.files.makedirs(parent, exist_ok=True)
        nc.files.upload(nc_path, data)
    except Exception:
        logger.warning("Failed to upload preview cache", exc_info=True)


def _nc_exists(lab: Lab, nc_path: str) -> bool:
    """Nextcloud 上にファイルが存在するか確認する。"""
    try:
        nc = lab._storage._get_client()
        return nc.files.by_path(nc_path) is not None
    except Exception:
        return False


@router.get("/{filename:path}")
def preview_file(
    record_id: str,
    filename: str,
    lab: Lab = Depends(get_lab),
) -> Response:
    """ファイルのプレビュー画像を返す。

    VK4: 光学画像をPNGに変換。キャッシュとして同フォルダに保存。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    if not filename.lower().endswith(".vk4"):
        raise HTTPException(
            status_code=400,
            detail="Preview not supported for this file type",
        )

    # DataRef からファイルの Nextcloud パスを取得
    ref = next((r for r in rec.list_data() if r.name == filename), None)
    if ref is None:
        raise HTTPException(status_code=404, detail="File not found")

    nc_path = ref.nextcloud_path
    preview_nc_path = nc_path.rsplit(".", 1)[0] + "_preview.png"

    # キャッシュ確認
    if _nc_exists(lab, preview_nc_path):
        logger.info("Preview cache hit: %s", preview_nc_path)
        png_data = _nc_download(lab, preview_nc_path)
        if png_data:
            return Response(content=png_data, media_type="image/png")

    # VK4 をダウンロード (raw パスで直接アクセス)
    logger.info("Preview cache miss, decoding: %s", nc_path)
    vk4_data = _nc_download(lab, nc_path)
    if vk4_data is None:
        raise HTTPException(status_code=404, detail="VK4 file not found")

    # デコード
    try:
        from labvault.parsers.vk4 import to_preview_png

        png_data = to_preview_png(vk4_data, max_size=512)
    except Exception as e:
        logger.exception("Failed to decode VK4: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Failed to decode VK4: {e}"
        )

    # キャッシュ保存
    _nc_upload(lab, preview_nc_path, png_data)
    logger.info("Preview cached: %s", preview_nc_path)

    return Response(content=png_data, media_type="image/png")
