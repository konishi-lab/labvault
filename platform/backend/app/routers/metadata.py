"""SDK 用 raw metadata API。

PlatformMetadataBackend (PAT 認証で動く SDK) からの呼び出しを受ける。
レスポンスは Firestore の生 dict (FirestoreMetadataBackend.get_record と同型)
をそのまま JSON 化する。Web UI 向けの整形済 ``/api/records/...`` とは別系統。

team は ``X-Labvault-Team`` header から取る (current_team が解決)。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)

from labvault import Lab

from ..auth import current_team, get_lab

router = APIRouter(prefix="/api/metadata")

# JSON 経由で来た文字列を Firestore Timestamp に戻すための既知 key 集合。
# 深いネスト (notes[].created_at, events[].timestamp 等) も同名なら一律変換する。
DATETIME_KEYS = {
    "created_at",
    "updated_at",
    "deleted_at",
    "started_at",
    "ended_at",
    "last_used_at",
    "last_login_at",
    "timestamp",
}


def _jsonable(value: Any) -> Any:
    """Firestore 固有型 (Vector 等) を JSON-safe な形に再帰変換する。

    - Vector → list[float]
    - dict → 値を再帰変換
    - list/tuple → 要素を再帰変換
    - その他 (datetime / プリミティブ) はそのまま返す (FastAPI が処理)
    """
    # google.cloud.firestore Vector を遅延 import (依存を main 経路から外す)
    try:
        from google.cloud.firestore_v1.vector import Vector
    except ImportError:  # pragma: no cover
        Vector = None  # type: ignore[assignment]

    if Vector is not None and isinstance(value, Vector):
        return list(value.to_map_value().get("value", []))
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _restore_datetimes(value: Any) -> Any:
    """SDK から JSON で送られてきた dict 内の ISO 文字列を datetime に戻す。

    DATETIME_KEYS に含まれる名前の値が文字列なら ``datetime.fromisoformat`` で
    パースして Firestore に Timestamp として書けるようにする (一貫性維持)。
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in DATETIME_KEYS and isinstance(v, str):
                try:
                    parsed = dt.datetime.fromisoformat(v)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=dt.UTC)
                    out[k] = parsed
                except ValueError:
                    out[k] = v
            else:
                out[k] = _restore_datetimes(v)
        return out
    if isinstance(value, list):
        return [_restore_datetimes(v) for v in value]
    return value


@router.get("/records/{record_id}")
def get_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, Any]:
    """単一レコードの生 dict を返す。soft delete 済は 404。"""
    data = lab._metadata.get_record(team, record_id)
    if data is None:
        raise HTTPException(status_code=404, detail="record not found")
    return _jsonable(data)


@router.get("/records")
def list_records(
    tags: str | None = None,
    status: str | None = None,
    record_type: str | None = Query(None, alias="type"),
    created_by: str | None = None,
    parent_id: str | None = None,
    parent_unset: bool = False,
    limit: int = 100,
    offset: int = 0,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """レコード一覧の生 dict 配列を返す。

    parent_id semantics:
      - parent_unset=true: parent_id が None (ルートレコード) のみ
      - parent_id="abc": parent_id == "abc"
      - 両方未指定: parent_id フィルタなし (全レコード)
    """
    tag_list = tags.split(",") if tags else None
    if parent_unset:
        pid: str | None = None
    elif parent_id is not None:
        pid = parent_id
    else:
        pid = "__unset__"  # MetadataBackend の sentinel: フィルタなし
    rows = lab._metadata.list_records(
        team,
        tags=tag_list,
        status=status,
        record_type=record_type,
        created_by=created_by,
        parent_id=pid,
        limit=limit,
        offset=offset,
    )
    return [_jsonable(r) for r in rows]


@router.get("/records/{record_id}/cell_logs")
def get_cell_logs(
    record_id: str,
    limit: int = 100,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """セルログ一覧の生 dict 配列。cell_number 昇順。"""
    return [
        _jsonable(r) for r in lab._metadata.get_cell_logs(team, record_id, limit=limit)
    ]


@router.get("/templates/{name}")
def get_template(
    name: str,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, Any]:
    """テンプレートの生 dict。未存在は 404。"""
    data = lab._metadata.get_template(team, name)
    if data is None:
        raise HTTPException(status_code=404, detail="template not found")
    return _jsonable(data)


@router.get("/templates")
def list_templates(
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """テンプレート一覧の生 dict 配列。"""
    return [_jsonable(t) for t in lab._metadata.list_templates(team)]


# --- Write endpoints (Phase 3) ---


@router.post("/records", status_code=201)
def create_record(
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """生 dict のレコードを作成する (set 上書き、merge しない)。

    body には ``id`` フィールドが必須 (Firestore の document id に使う)。
    """
    if not body.get("id"):
        raise HTTPException(status_code=400, detail="body.id required")
    data = _restore_datetimes(body)
    lab._metadata.create_record(team, data)
    return Response(status_code=201)


@router.patch("/records/{record_id}", status_code=204)
def update_record(
    record_id: str,
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """レコードを部分更新する (set with merge)。"""
    data = _restore_datetimes(body)
    lab._metadata.update_record(team, record_id, data)
    return Response(status_code=204)


@router.delete("/records/{record_id}", status_code=204)
def delete_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """レコードを物理削除する (soft delete は update_record で deleted_at を設定する別経路)."""
    lab._metadata.delete_record(team, record_id)
    return Response(status_code=204)


@router.post("/records/{record_id}/cell_logs", status_code=201)
def save_cell_log(
    record_id: str,
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, str]:
    """セルログを保存する。

    ``body.cell_id`` が無ければ backend 側で uuid4 を生成し、レスポンスで返す。
    既にあれば上書き (set)。
    """
    data = _restore_datetimes(body)
    lab._metadata.save_cell_log(team, record_id, data)
    # save_cell_log は data を mutate して cell_id を埋めるので、それを返す
    return {"cell_id": data.get("cell_id", "")}


@router.put("/templates/{name}", status_code=204)
def save_template(
    name: str,
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """テンプレートを upsert する。"""
    data = _restore_datetimes(body)
    lab._metadata.save_template(team, name, data)
    return Response(status_code=204)


# --- Storage proxy (Phase 4) ---


@router.post("/storage", status_code=201)
async def storage_upload(
    file: UploadFile,
    path: str = Form(...),
    content_type: str = Form(""),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, str]:
    """ファイルアップロード。

    ``path`` は SDK が組み立てた相対パス (例 ``{team}/{record_id}/{filename}``)。
    backend は無加工で ``lab._storage.upload()`` に渡す。
    """
    data = await file.read()
    ct = content_type or file.content_type or ""
    stored_path = lab._storage.upload(path, data, ct)
    return {"path": stored_path}


@router.get("/storage")
def storage_download(
    path: str = Query(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """ファイルダウンロード。content は application/octet-stream で返す。"""
    try:
        data = lab._storage.download(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"file not found: {path}") from e
    return Response(content=data, media_type="application/octet-stream")


@router.delete("/storage", status_code=204)
def storage_delete(
    path: str = Query(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """ファイル削除 (冪等)。"""
    try:
        lab._storage.delete(path)
    except FileNotFoundError:
        pass  # idempotent
    return Response(status_code=204)


@router.get("/storage/exists")
def storage_exists(
    path: str = Query(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, bool]:
    return {"exists": lab._storage.exists(path)}


@router.get("/storage/list")
def storage_list(
    prefix: str = Query(""),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, list[str]]:
    return {"paths": lab._storage.list_files(prefix)}


# --- Search proxy (Phase 4) ---


@router.post("/search/index", status_code=204)
def search_index(
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    """ベクトル検索のインデックスを更新する。

    body: {record_id: str, text: str, embedding?: list[float]}
    embedding 未指定なら backend の Embedding client で text から生成して保存する。
    """
    rid = body.get("record_id")
    if not rid:
        raise HTTPException(status_code=400, detail="record_id required")
    text = body.get("text", "")
    embedding = body.get("embedding")
    if embedding is None and text and getattr(lab, "_embedding", None) is not None:
        try:
            embedding = lab._embedding.embed(text)
        except Exception:
            embedding = None
    lab._search.index(team, rid, text, embedding=embedding)
    return Response(status_code=204)


@router.post("/search")
def search_query(
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> list[dict[str, Any]]:
    """ベクトル検索。

    body: {query: str, embedding?: list[float], filters?: dict, limit?: int}
    embedding 未指定なら query を backend で embed する。
    """
    query = body.get("query", "")
    embedding = body.get("embedding")
    filters = body.get("filters")
    limit = int(body.get("limit", 20))
    if embedding is None and query and getattr(lab, "_embedding", None) is not None:
        try:
            embedding = lab._embedding.embed(query)
        except Exception:
            embedding = None
    rows = lab._search.search(
        team, query, embedding=embedding, filters=filters, limit=limit
    )
    return [_jsonable(r) for r in rows]


@router.delete("/search/index/{record_id}", status_code=204)
def search_delete_index(
    record_id: str,
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> Response:
    lab._search.delete_index(team, record_id)
    return Response(status_code=204)


# --- Embedding proxy (Phase 4) ---


@router.post("/embedding")
def embedding_embed(
    body: dict[str, Any] = Body(...),
    lab: Lab = Depends(get_lab),
    team: str = Depends(current_team),
) -> dict[str, Any]:
    """text または texts (batch) を embedding に変換して返す。

    body: {text?: str, texts?: list[str]}
    Returns: {embedding: [...]} or {embeddings: [[...], ...]}
    """
    if getattr(lab, "_embedding", None) is None:
        raise HTTPException(status_code=503, detail="embedding client not configured")
    text = body.get("text")
    texts = body.get("texts")
    if text is not None:
        return {"embedding": lab._embedding.embed(text)}
    if texts is not None:
        return {"embeddings": lab._embedding.embed_batch(texts)}
    raise HTTPException(status_code=400, detail="text or texts required")
