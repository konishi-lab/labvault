"""一括アップロードエンドポイント。"""

from __future__ import annotations

import io
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError
from labvault.core.record import Record

from ..dependencies import get_lab

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records/{record_id}/bulk-upload", tags=["bulk"])


class MatchPreviewItem(BaseModel):
    filename: str
    record_id: str | None
    record_title: str | None
    status: str  # "matched" | "unmatched"


class MatchPreviewResult(BaseModel):
    total: int
    matched: int
    unmatched: int
    items: list[MatchPreviewItem]


class BulkUploadResult(BaseModel):
    total: int
    matched: int
    uploaded: int
    errors: list[str]


@router.post("/preview", response_model=MatchPreviewResult)
async def preview_matching(
    record_id: str,
    filenames: list[str],
    lab: Lab = Depends(get_lab),
) -> MatchPreviewResult:
    """ファイル名とサブレコードのマッチングをプレビューする。"""
    try:
        lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    rows = lab._metadata.list_records(
        lab._team, parent_id=record_id, limit=2000
    )
    children = [Record._from_dict(r, lab=lab) for r in rows]
    children_by_title: dict[str, Record] = {c.title: c for c in children}
    children_sorted = sorted(children, key=lambda c: c.title)

    items: list[MatchPreviewItem] = []
    matched = 0
    for fn in filenames:
        target = _find_matching_child(fn, children_by_title, children_sorted)
        if target:
            items.append(
                MatchPreviewItem(
                    filename=fn,
                    record_id=target.id,
                    record_title=target.title,
                    status="matched",
                )
            )
            matched += 1
        else:
            items.append(
                MatchPreviewItem(
                    filename=fn,
                    record_id=None,
                    record_title=None,
                    status="unmatched",
                )
            )

    return MatchPreviewResult(
        total=len(filenames),
        matched=matched,
        unmatched=len(filenames) - matched,
        items=items,
    )


@router.post("", response_model=BulkUploadResult)
async def bulk_upload(
    record_id: str,
    files: list[UploadFile],
    lab: Lab = Depends(get_lab),
) -> BulkUploadResult:
    """子レコードにファイルを一括アップロードする。

    ファイル名からサブレコードを自動マッチングする。
    例: "Fused Silica_1.vk4" → title に "5W_0_0001" を含むサブレコード

    マッチング戦略:
    1. ファイル名と同じ名前のサブレコードがあればそこに追加
    2. ファイル名の番号部分 (例: _1, _38) でサブレコードを順番にマッチ
    """
    try:
        lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    # 子レコード一覧を取得
    rows = lab._metadata.list_records(
        lab._team, parent_id=record_id, limit=2000
    )
    children = [Record._from_dict(r, lab=lab) for r in rows]

    # タイトルで辞書を作成
    children_by_title: dict[str, Record] = {c.title: c for c in children}

    # タイトルをソートして番号順マッチング用リストも作る
    children_sorted = sorted(children, key=lambda c: c.title)

    result = BulkUploadResult(
        total=len(files), matched=0, uploaded=0, errors=[]
    )

    for file in files:
        filename = file.filename or "untitled"
        data = await file.read()

        if len(data) == 0:
            result.errors.append(f"{filename}: empty file")
            continue

        # マッチング: ファイル名の番号を抽出して対応するサブレコードを探す
        target = _find_matching_child(
            filename, children_by_title, children_sorted
        )

        if target is None:
            result.errors.append(f"{filename}: no matching sub-record")
            continue

        result.matched += 1

        try:
            # Nextcloud に直接アップロード (raw パス)
            nc_path = _build_nc_path(target, filename, lab)
            nc = lab._storage._get_client()
            parent_dir = "/".join(nc_path.split("/")[:-1])
            nc.files.makedirs(parent_dir, exist_ok=True)

            buf = io.BytesIO(data)
            nc.files.upload(nc_path, data)

            # DataRef を追加
            from labvault.core.types import DataRef

            # 同名ファイルがあれば上書き
            target._data_refs = [
                r for r in target._data_refs if r.name != filename
            ]
            target._data_refs.append(
                DataRef(
                    name=filename,
                    nextcloud_path=nc_path,
                    size_bytes=len(data),
                )
            )
            target._persist()
            result.uploaded += 1
            logger.info("Uploaded %s -> %s (%s)", filename, target.id, nc_path)
        except Exception as e:
            result.errors.append(f"{filename}: {e}")
            logger.exception("Failed to upload %s", filename)

    return result


def _find_matching_child(
    filename: str,
    by_title: dict[str, Record],
    sorted_children: list[Record],
) -> Record | None:
    """ファイル名からサブレコードをマッチングする。

    戦略:
    1. ファイル名 (拡張子なし) がタイトルと完全一致
    2. ファイル名から番号を抽出し、順番でマッチ
    """
    import re

    stem = filename.rsplit(".", 1)[0] if "." in filename else filename

    # 完全一致
    if stem in by_title:
        return by_title[stem]

    # 番号抽出: "Fused Silica_1" → 1, "Fused Silica_38" → 38
    m = re.search(r"_(\d+)$", stem)
    if m:
        idx = int(m.group(1)) - 1  # 1-based → 0-based
        if 0 <= idx < len(sorted_children):
            return sorted_children[idx]

    return None


def _build_nc_path(record: Record, filename: str, lab: Lab) -> str:
    """サブレコードのファイル用 Nextcloud パスを構築する。"""
    # マイグレーション済みレコードは conditions に mdxdb_id がある
    conditions = record.get_conditions()
    mdxdb_id = conditions.get("mdxdb_id")

    if mdxdb_id:
        # 既存の _data/ パスから親パスを推定
        for ref in record._data_refs:
            if ref.nextcloud_path:
                parent = "/".join(ref.nextcloud_path.split("/")[:-1])
                return f"{parent}/{filename}"

        # conditions の mdxdb_path から推定
        mdxdb_path = conditions.get("mdxdb_path", "")
        if mdxdb_path:
            return f"{mdxdb_path}/_data/{filename}"

    # labvault ネイティブレコード
    return f"{lab._storage._base_path}/{record.team}/{record.id}/{filename}"
