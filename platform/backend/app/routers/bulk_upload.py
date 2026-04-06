"""一括アップロードエンドポイント (グリッドマッチング)."""

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


# --- Models ---


class GridConfig(BaseModel):
    rows: int
    cols: int
    start_position: str = "top-left"  # top-left, top-right, bottom-left, bottom-right
    direction: str = "row-first"  # row-first, column-first


class MatchPreviewItem(BaseModel):
    filename: str
    grid_row: int
    grid_col: int
    record_id: str | None
    record_title: str | None
    record_created_at: str | None
    status: str


class MatchPreviewResult(BaseModel):
    total_files: int
    total_records: int
    matched: int
    unmatched: int
    items: list[MatchPreviewItem]


class BulkUploadResult(BaseModel):
    total: int
    matched: int
    uploaded: int
    errors: list[str]


# --- Grid Mapping ---


def generate_grid_mapping(
    rows: int,
    cols: int,
    start_position: str,
    direction: str,
) -> list[tuple[int, int]]:
    """グリッド位置の走査順序を生成する。

    Returns:
        [(row, col), ...] の順序リスト
    """
    row_indices = list(range(rows))
    col_indices = list(range(cols))

    if start_position in ("top-right", "bottom-right"):
        col_indices.reverse()
    if start_position in ("bottom-left", "bottom-right"):
        row_indices.reverse()

    positions: list[tuple[int, int]] = []
    if direction == "row-first":
        for row in row_indices:
            for col in col_indices:
                positions.append((row, col))
    else:  # column-first
        for col in col_indices:
            for row in row_indices:
                positions.append((row, col))

    return positions


def _get_children_sorted(lab: Lab, record_id: str) -> list[Record]:
    """子レコードを自然順ソートで取得する。"""
    rows = lab._metadata.list_records(
        lab._team, parent_id=record_id, limit=2000
    )
    children = [Record._from_dict(r, lab=lab) for r in rows]
    return sorted(children, key=lambda c: _natural_sort_key(c.title))


# --- Endpoints ---


@router.post("/preview", response_model=MatchPreviewResult)
async def preview_matching(
    record_id: str,
    grid: GridConfig,
    filenames: list[str],
    lab: Lab = Depends(get_lab),
) -> MatchPreviewResult:
    """グリッドベースのマッチングをプレビューする。"""
    try:
        lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    children = _get_children_sorted(lab, record_id)

    # ファイルを自然順ソート
    sorted_files = sorted(filenames, key=_natural_sort_key)

    # グリッド走査順序を生成
    positions = generate_grid_mapping(
        grid.rows, grid.cols, grid.start_position, grid.direction
    )

    items: list[MatchPreviewItem] = []
    matched = 0

    for file_idx, filename in enumerate(sorted_files):
        if file_idx < len(positions):
            row, col = positions[file_idx]
            record_idx = row * grid.cols + col  # row-major index
            if record_idx < len(children):
                child = children[record_idx]
                items.append(
                    MatchPreviewItem(
                        filename=filename,
                        grid_row=row,
                        grid_col=col,
                        record_id=child.id,
                        record_title=child.title,
                        record_created_at=child.created_at.isoformat(),
                        status="matched",
                    )
                )
                matched += 1
                continue

        items.append(
            MatchPreviewItem(
                filename=filename,
                grid_row=-1,
                grid_col=-1,
                record_id=None,
                record_title=None,
                record_created_at=None,
                status="unmatched",
            )
        )

    return MatchPreviewResult(
        total_files=len(sorted_files),
        total_records=len(children),
        matched=matched,
        unmatched=len(sorted_files) - matched,
        items=items,
    )


@router.post("", response_model=BulkUploadResult)
async def bulk_upload(
    record_id: str,
    files: list[UploadFile],
    rows: int = 0,
    cols: int = 0,
    start_position: str = "top-left",
    direction: str = "row-first",
    lab: Lab = Depends(get_lab),
) -> BulkUploadResult:
    """グリッドマッチングで子レコードにファイルを一括アップロードする。"""
    try:
        lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")

    children = _get_children_sorted(lab, record_id)

    if rows == 0 or cols == 0:
        raise HTTPException(
            status_code=400, detail="rows and cols are required"
        )

    positions = generate_grid_mapping(rows, cols, start_position, direction)

    # ファイルを自然順ソート
    sorted_files = sorted(files, key=lambda f: _natural_sort_key(f.filename or ""))

    result = BulkUploadResult(
        total=len(sorted_files), matched=0, uploaded=0, errors=[]
    )

    for file_idx, file in enumerate(sorted_files):
        filename = file.filename or "untitled"
        data = await file.read()

        if len(data) == 0:
            result.errors.append(f"{filename}: empty file")
            continue

        if file_idx >= len(positions):
            result.errors.append(f"{filename}: exceeds grid size")
            continue

        row, col = positions[file_idx]
        record_idx = row * cols + col

        if record_idx >= len(children):
            result.errors.append(f"{filename}: no sub-record at [{row},{col}]")
            continue

        target = children[record_idx]
        result.matched += 1

        try:
            nc_path = _build_nc_path(target, filename, lab)
            nc = lab._storage._get_client()
            parent_dir = "/".join(nc_path.split("/")[:-1])
            nc.files.makedirs(parent_dir, exist_ok=True)
            nc.files.upload(nc_path, data)

            from labvault.core.types import DataRef

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
            logger.info("Uploaded %s -> %s [%d,%d]", filename, target.id, row, col)
        except Exception as e:
            result.errors.append(f"{filename}: {e}")
            logger.exception("Failed to upload %s", filename)

    return result


# --- Helpers ---


def _natural_sort_key(s: str) -> list[int | str]:
    """自然順ソート用キー。'file_2' < 'file_10'。"""
    import re

    parts: list[int | str] = []
    for part in re.split(r"(\d+)", s):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())
    return parts


def _build_nc_path(record: Record, filename: str, lab: Lab) -> str:
    """サブレコードのファイル用 Nextcloud パスを構築する。"""
    conditions = record.get_conditions()

    for ref in record._data_refs:
        if ref.nextcloud_path:
            parent = "/".join(ref.nextcloud_path.split("/")[:-1])
            return f"{parent}/{filename}"

    mdxdb_path = conditions.get("mdxdb_path", "")
    if mdxdb_path:
        return f"{mdxdb_path}/_data/{filename}"

    return f"{lab._storage._base_path}/{record.team}/{record.id}/{filename}"
