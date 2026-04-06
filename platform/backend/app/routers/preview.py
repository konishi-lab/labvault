"""ファイルプレビューエンドポイント。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError

from ..dependencies import get_lab

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/records/{record_id}/preview", tags=["preview"]
)


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

    # VK4 ファイルのみ対応
    if not filename.lower().endswith(".vk4"):
        raise HTTPException(
            status_code=400, detail="Preview not supported for this file type"
        )

    # キャッシュ確認: 同フォルダに {name}_preview.png があるか
    preview_name = filename.rsplit(".", 1)[0] + "_preview.png"

    # Nextcloud 上のキャッシュを探す
    ref = next((r for r in rec.list_data() if r.name == filename), None)
    if ref is None:
        raise HTTPException(status_code=404, detail="File not found")

    # キャッシュの Nextcloud パスを組み立て
    preview_nc_path = ref.nextcloud_path.rsplit("/", 1)[0] + "/" + preview_name

    # キャッシュがあるか確認
    if lab._storage and lab._storage.exists(preview_nc_path):
        logger.info("Preview cache hit: %s", preview_nc_path)
        png_data = lab._storage.download(preview_nc_path)
        return Response(content=png_data, media_type="image/png")

    # キャッシュなし: VK4 をデコードして PNG 生成
    logger.info("Preview cache miss, decoding: %s", filename)
    try:
        vk4_data = rec.get_data(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    try:
        from labvault.parsers.vk4 import to_preview_png

        png_data = to_preview_png(vk4_data, max_size=512)
    except Exception as e:
        logger.exception("Failed to decode VK4: %s", e)
        raise HTTPException(
            status_code=500, detail=f"Failed to decode VK4: {e}"
        )

    # キャッシュとして Nextcloud に保存
    if lab._storage:
        try:
            lab._storage.upload(preview_nc_path, png_data, "image/png")
            logger.info("Preview cached: %s", preview_nc_path)
        except Exception:
            logger.warning("Failed to cache preview", exc_info=True)

    return Response(content=png_data, media_type="image/png")
