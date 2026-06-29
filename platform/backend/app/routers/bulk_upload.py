"""一括アップロードエンドポイント (グリッドマッチング + SSE 進捗)."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError
from labvault.core.record import Record

from ..auth import User, current_user, get_lab_relaxed
from ..observability import log_event
from ..permissions import can_analyze, require_analyze

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/records/{record_id}/bulk-upload", tags=["bulk"])


# --- Models ---


class GridConfig(BaseModel):
    rows: int
    cols: int
    start_position: str = "top-left"
    direction: str = "row-first"


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


# --- Grid Mapping ---


def generate_grid_mapping(
    rows: int,
    cols: int,
    start_position: str,
    direction: str,
) -> list[tuple[int, int]]:
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
    else:
        for col in col_indices:
            for row in row_indices:
                positions.append((row, col))
    return positions


def _get_children_sorted(lab: Lab, record_id: str) -> list[Record]:
    rows = lab._metadata.list_records(lab._team, parent_id=record_id, limit=2000)
    children = [Record._from_dict(r, lab=lab) for r in rows]
    return sorted(children, key=lambda c: _natural_sort_key(c.title))


# --- Endpoints ---


@router.post("/preview", response_model=MatchPreviewResult)
async def preview_matching(
    record_id: str,
    grid: GridConfig,
    filenames: list[str],
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> MatchPreviewResult:
    """子レコードとファイルのマッチング preview を返す (実 upload 前段)。

    S1 Phase 1C: 本 endpoint は後段の upload (POST /api/.../bulk-upload) と
    同じ書き込み権限が前提なので ``require_analyze`` で揃える。
    """
    try:
        parent = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    require_analyze(user, parent)

    children = _get_children_sorted(lab, record_id)
    basenames = [fn.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] for fn in filenames]
    sorted_files = sorted(basenames, key=_natural_sort_key)
    positions = generate_grid_mapping(
        grid.rows, grid.cols, grid.start_position, grid.direction
    )

    items: list[MatchPreviewItem] = []
    matched = 0
    for file_idx, filename in enumerate(sorted_files):
        if file_idx < len(positions):
            row, col = positions[file_idx]
            record_idx = row * grid.cols + col
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


@router.post("")
async def bulk_upload(
    record_id: str,
    files: list[UploadFile],
    rows: int = 0,
    cols: int = 0,
    start_position: str = "top-left",
    direction: str = "row-first",
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> StreamingResponse:
    """SSE で進捗を返しながらアップロードする。

    S1 Phase 1C: 親 record に対する ``require_analyze`` で認可。analyst 共有
    された外部 user も他チームの実験に解析結果ファイルを bulk upload
    できる。viewer / 関係ない user は 403。
    """
    try:
        parent = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_analyze(user, parent)

    if rows == 0 or cols == 0:
        raise HTTPException(status_code=400, detail="rows and cols required")

    children = _get_children_sorted(lab, record_id)
    positions = generate_grid_mapping(rows, cols, start_position, direction)

    def _basename(f: UploadFile) -> str:
        name = f.filename or "untitled"
        return name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]

    sorted_files = sorted(files, key=lambda f: _natural_sort_key(_basename(f)))

    # ファイルデータを先に全部読む (SSE generator 内で await できないため)
    file_data: list[tuple[str, bytes]] = []
    for f in sorted_files:
        data = await f.read()
        file_data.append((_basename(f), data))

    async def event_stream() -> AsyncIterator[str]:
        import time

        total = len(file_data)
        total_bytes = sum(len(d) for _, d in file_data)
        uploaded = 0
        errors: list[str] = []
        # N4 (PR #83): クライアントが SSE を mid-stream で abort すると
        # GeneratorExit が flush され、`bulk_upload.done` event が永久に
        # 出ない問題があった (start のみ累積、observability ダッシュボードが
        # 「成功」と誤判定)。aborted フラグ + try/finally で必ず done event を
        # 出す。GeneratorExit 自身は再 raise (SSE プロトコル遵守)。
        aborted = False
        t0 = time.perf_counter()
        # S1-OBS3 hot-fix (2026-06-29): actor + audit_source を必ず log に
        # 入れる。share-link analyst が他チームの parent に bulk-upload した
        # 時の audit trail が以前は user.email を欠いて断絶していた。
        actor_audit_source = (
            "share-link" if user.share_link_scope is not None else "firebase"
        )
        log_event(
            logger,
            "bulk_upload.start",
            parent_id=record_id,
            total_files=total,
            total_bytes=total_bytes,
            grid=f"{rows}x{cols}",
            children_count=len(children),
            actor=user.email,
            actor_audit_source=actor_audit_source,
        )
        try:
            for file_idx, (filename, data) in enumerate(file_data):
                if len(data) == 0:
                    errors.append(f"{filename}: empty file")
                    yield _sse(
                        "progress",
                        {
                            "current": file_idx + 1,
                            "total": total,
                            "filename": filename,
                            "status": "skipped",
                            "uploaded": uploaded,
                        },
                    )
                    continue

                if file_idx >= len(positions):
                    errors.append(f"{filename}: exceeds grid size")
                    yield _sse(
                        "progress",
                        {
                            "current": file_idx + 1,
                            "total": total,
                            "filename": filename,
                            "status": "skipped",
                            "uploaded": uploaded,
                        },
                    )
                    continue

                row, col = positions[file_idx]
                record_idx = row * cols + col

                if record_idx >= len(children):
                    errors.append(f"{filename}: no sub-record at [{row},{col}]")
                    yield _sse(
                        "progress",
                        {
                            "current": file_idx + 1,
                            "total": total,
                            "filename": filename,
                            "status": "error",
                            "uploaded": uploaded,
                        },
                    )
                    continue

                target = children[record_idx]

                # S1-SEC4 (2026-06-29 hot-fix): 親 require_analyze だけでは
                # share-link analyst (scope=parent record 1 本) が全 child
                # に書き込めてしまう。loop 内で per-child の can_analyze
                # チェックを入れ、scope mismatch は skip する。Firebase
                # team member / super_admin は全 child で通過するので影響
                # なし。Firebase shares 経由の analyst も同様にガード強化
                # (child が parent より厳しい shares を持つ場合の暗黙昇格を
                # 防ぐ)。
                if not can_analyze(user, target):
                    errors.append(
                        f"{filename}: forbidden (no analyze permission on "
                        f"child {target.id})"
                    )
                    yield _sse(
                        "progress",
                        {
                            "current": file_idx + 1,
                            "total": total,
                            "filename": filename,
                            "status": "forbidden",
                            "uploaded": uploaded,
                        },
                    )
                    continue

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
                    target.updated_by = user.email
                    # S1-SEC2: share-link 経路の audit marker
                    target.updated_audit_source = (
                        "share-link"
                        if user.share_link_scope is not None
                        else "firebase"
                    )
                    target._persist()
                    uploaded += 1

                    yield _sse(
                        "progress",
                        {
                            "current": file_idx + 1,
                            "total": total,
                            "filename": filename,
                            "status": "ok",
                            "record_id": target.id,
                            "uploaded": uploaded,
                        },
                    )
                except Exception as e:
                    errors.append(f"{filename}: {e}")
                    yield _sse(
                        "progress",
                        {
                            "current": file_idx + 1,
                            "total": total,
                            "filename": filename,
                            "status": "error",
                            "uploaded": uploaded,
                        },
                    )

            # 正常終了パス: done event を yield してから finally で log
            yield _sse(
                "done",
                {
                    "total": total,
                    "uploaded": uploaded,
                    "errors": errors,
                },
            )
        except GeneratorExit:
            # クライアントが mid-stream で接続切断 (browser タブ閉じ等)
            aborted = True
            raise
        finally:
            # abort / 正常完了 / 例外 のいずれでも必ず done event を log。
            # observability ダッシュボードが「start のみ累積で done 無し」と
            # いう状態にならないようにする (N4)。
            duration_ms = round((time.perf_counter() - t0) * 1000, 1)
            log_event(
                logger,
                "bulk_upload.done",
                level=(
                    logging.WARNING if (errors or aborted) else logging.INFO
                ),
                parent_id=record_id,
                total_files=total,
                uploaded=uploaded,
                error_count=len(errors),
                duration_ms=duration_ms,
                aborted=aborted,
                actor=user.email,
                actor_audit_source=actor_audit_source,
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# --- Helpers ---


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _natural_sort_key(s: str) -> list[int | str]:
    import re

    parts: list[int | str] = []
    for part in re.split(r"(\d+)", s):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())
    return parts


def _build_nc_path(record: Record, filename: str, lab: Lab) -> str:
    conditions = record.get_conditions()
    for ref in record._data_refs:
        if ref.nextcloud_path:
            parent = "/".join(ref.nextcloud_path.split("/")[:-1])
            return f"{parent}/{filename}"
    mdxdb_path = conditions.get("mdxdb_path", "")
    if mdxdb_path:
        return f"{mdxdb_path}/_data/{filename}"
    return f"{lab._storage._base_path}/{record.team}/{record.id}/{filename}"
