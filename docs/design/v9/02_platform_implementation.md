# v9 プラットフォーム実装仕様書

> v8設計 + REQUIREMENTSに基づく、プラットフォーム側（MCPサーバー、Cloud Functions、WebApp、GCPインフラ）の実装レベル仕様。
> 対象リポジトリ: `labvault-platform/`（モノレポ）

---

## 目次

1. [MCPサーバー実装仕様（14ツール）](#1-mcpサーバー実装仕様14ツール)
2. [Cloud Functions実装仕様](#2-cloud-functions実装仕様)
3. [Firestoreスキーマ（最終版）](#3-firestoreスキーマ最終版)
4. [Nextcloudディレクトリ構造（最終版）](#4-nextcloudディレクトリ構造最終版)
5. [WebApp（Streamlit）実装仕様](#5-webappstreamlit実装仕様)
6. [GCPインフラ設定](#6-gcpインフラ設定)
7. [モノレポのディレクトリ構成と各ファイル](#7-モノレポのディレクトリ構成と各ファイル)
8. [実装ロードマップ（Issue粒度）](#8-実装ロードマップissue粒度)
9. [認証フローの詳細](#9-認証フローの詳細)
10. [デプロイ手順](#10-デプロイ手順)

---

## 1. MCPサーバー実装仕様（14ツール）

### 1.1 サーバー基盤

```python
# mcp-server/src/server.py
from fastmcp import FastMCP
from google.cloud import firestore
from shared.nextcloud import NextcloudClient

mcp = FastMCP(
    name="labvault",
    version="0.1.0",
    description="実験データ管理プラットフォーム MCP Server",
)

# 共有リソース（起動時に1回初期化）
db = firestore.AsyncClient(project="labvault-project", database="labvault")
nc = NextcloudClient()  # Nextcloud WebDAV クライアント
```

**デプロイ先**: Cloud Run（asia-northeast1）
**トランスポート**: Streamable HTTP（`/mcp` エンドポイント）
**認証**: Cloud Run IAM invoker + APIキー認証（詳細は[セクション9](#9-認証フローの詳細)）

### 1.2 全14ツール一覧と分類

| # | ツール名 | 分類 | Firestore | Nextcloud | Vertex AI |
|---|---------|------|-----------|-----------|-----------|
| 1 | `search` | 検索 | R | - | Embedding |
| 2 | `get_detail` | 取得 | R | - | - |
| 3 | `compare` | 分析 | R | - | - |
| 4 | `data_preview` | 取得 | R | R | - |
| 5 | `get_results` | 検索 | R | - | - |
| 6 | `aggregate` | 分析 | R | - | - |
| 7 | `get_timeline` | 取得 | R | - | - |
| 8 | `get_trace` | 取得 | R | - | - |
| 9 | `explain_result` | 分析 | R | - | - |
| 10 | `compare_runs` | 分析 | R | - | - |
| 11 | `get_notebook_log` | 取得 | R | - | - |
| 12 | `execute_code` | 実行 | R/W | R/W | - |
| 13 | `batch_execute` | 実行 | R/W | R/W | - |
| 14 | `get_image` | 取得 | R | R | - |

R=読み取り, W=書き込み

---

### 1.3 各ツール完全実装

#### Tool 1: `search`

**目的**: ハイブリッド検索（構造化フィルタ + ベクトル類似度）

```python
# mcp-server/src/tools/search.py
from typing import Any
from google.cloud.firestore_v1.vector import Vector
from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from vertexai.language_models import TextEmbeddingModel
from dataclasses import dataclass

embedding_model = TextEmbeddingModel.from_pretrained("text-embedding-004")


@dataclass
class SearchResult:
    id: str
    title: str
    type: str
    status: str
    tags: list[str]
    created_by: str
    created_at: str
    conditions_summary: dict
    results_summary: dict
    notebook_summary: str | None
    relevance_score: float | None


def _apply_conditions_filter(doc_conditions: dict, conditions_filter: dict) -> bool:
    """Python側で conditions_filter を適用する。
    例: {"temperature_C": {">": 300}} -> doc_conditions["temperature_C"] > 300
    """
    for key, constraint in conditions_filter.items():
        value = doc_conditions.get(key)
        if value is None:
            return False
        if isinstance(constraint, dict):
            for op, threshold in constraint.items():
                if op == ">" and not (value > threshold):
                    return False
                elif op == ">=" and not (value >= threshold):
                    return False
                elif op == "<" and not (value < threshold):
                    return False
                elif op == "<=" and not (value <= threshold):
                    return False
                elif op == "==" and not (value == threshold):
                    return False
                elif op == "!=" and not (value != threshold):
                    return False
        else:
            if value != constraint:
                return False
    return True


def _doc_to_search_result(doc, score: float | None = None) -> SearchResult:
    """Firestoreドキュメントを SearchResult に変換する。"""
    d = doc.to_dict()
    conditions = d.get("conditions", {})
    results = d.get("results", {})
    # サマリー: 上位5フィールドのみ
    conditions_summary = dict(list(conditions.items())[:5])
    results_summary = dict(list(results.items())[:5])
    return SearchResult(
        id=doc.id,
        title=d.get("title", ""),
        type=d.get("type", ""),
        status=d.get("status", ""),
        tags=d.get("tags", []),
        created_by=d.get("created_by", ""),
        created_at=d.get("created_at", "").isoformat() if hasattr(d.get("created_at", ""), "isoformat") else str(d.get("created_at", "")),
        conditions_summary=conditions_summary,
        results_summary=results_summary,
        notebook_summary=d.get("notebook_summary"),
        relevance_score=score,
    )


@mcp.tool()
async def search(
    team_id: str,
    query: str | None = None,
    tags: list[str] | None = None,
    status: str | None = None,
    record_type: str | None = None,
    created_by: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    conditions_filter: dict | None = None,
    limit: int = 20,
) -> list[dict]:
    """レコードをハイブリッド検索する。"""
    records_ref = db.collection("teams").document(team_id).collection("records")

    if query:
        # --- ベクトル検索パス ---
        embeddings = embedding_model.get_embeddings(
            [query], output_dimensionality=768
        )
        query_vector = embeddings[0].values

        vector_query = records_ref.where("deleted_at", "==", None).find_nearest(
            vector_field="embedding",
            query_vector=Vector(query_vector),
            distance_measure=DistanceMeasure.COSINE,
            limit=limit * 3,
        )
        docs_with_scores = []
        async for doc in vector_query.stream():
            d = doc.to_dict()
            # 構造化フィルタをPython側で適用
            if tags and not any(t in d.get("tags", []) for t in tags):
                continue
            if status and d.get("status") != status:
                continue
            if record_type and d.get("type") != record_type:
                continue
            if created_by and d.get("created_by") != created_by:
                continue
            if created_after:
                from datetime import datetime, timezone
                after_dt = datetime.fromisoformat(created_after)
                if d.get("created_at") and d["created_at"] < after_dt:
                    continue
            if created_before:
                from datetime import datetime, timezone
                before_dt = datetime.fromisoformat(created_before)
                if d.get("created_at") and d["created_at"] > before_dt:
                    continue
            if conditions_filter and not _apply_conditions_filter(
                d.get("conditions", {}), conditions_filter
            ):
                continue
            # Cosine距離からスコアへ変換 (1 - distance)
            score = 1.0 - (doc.distance if hasattr(doc, "distance") else 0.0)
            docs_with_scores.append((doc, score))

        # limit件に絞る
        docs_with_scores = docs_with_scores[:limit]
        return [
            _doc_to_search_result(doc, score).__dict__
            for doc, score in docs_with_scores
        ]

    else:
        # --- 構造化フィルタのみ ---
        q = records_ref.where("deleted_at", "==", None)
        if tags:
            q = q.where("tags", "array_contains_any", tags)
        if status:
            q = q.where("status", "==", status)
        if record_type:
            q = q.where("type", "==", record_type)
        if created_by:
            q = q.where("created_by", "==", created_by)
        if created_after:
            from datetime import datetime
            q = q.where("created_at", ">=", datetime.fromisoformat(created_after))
        if created_before:
            from datetime import datetime
            q = q.where("created_at", "<=", datetime.fromisoformat(created_before))

        q = q.order_by("created_at", direction="DESCENDING").limit(limit)

        results = []
        async for doc in q.stream():
            d = doc.to_dict()
            if conditions_filter and not _apply_conditions_filter(
                d.get("conditions", {}), conditions_filter
            ):
                continue
            results.append(_doc_to_search_result(doc).__dict__)
        return results


# -------------------------------------------------------------------
# Tool 2: get_detail
# -------------------------------------------------------------------

@mcp.tool()
async def get_detail(
    team_id: str,
    record_id: str,
    include_sub_records: bool = False,
    include_notebook_log: bool = False,
    include_analyses: bool = False,
    include_traces: bool = False,
) -> dict:
    """レコードの詳細情報を取得する。"""
    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    doc = await record_ref.get()
    if not doc.exists:
        raise ValueError(f"Record {record_id} not found")
    d = doc.to_dict()
    if d.get("deleted_at") is not None:
        raise ValueError(f"Record {record_id} has been deleted")

    result = {
        "id": doc.id,
        "title": d.get("title", ""),
        "type": d.get("type", ""),
        "status": d.get("status", ""),
        "tags": d.get("tags", []),
        "conditions": d.get("conditions", {}),
        "results": d.get("results", {}),
        "notes": d.get("notes", []),
        "created_by": d.get("created_by", ""),
        "created_at": str(d.get("created_at", "")),
        "updated_at": str(d.get("updated_at", "")),
        "parent_id": d.get("parent_id"),
        "file_refs": d.get("file_refs", []),
        "notebook_summary": d.get("notebook_summary"),
        "trace_summary": d.get("trace_summary"),
        "sub_records": None,
        "notebook_log": None,
        "analyses": None,
        "traces": None,
    }

    import asyncio
    tasks = []

    # サブレコード取得
    if include_sub_records:
        async def _get_sub_records():
            q = (
                db.collection("teams").document(team_id)
                .collection("records")
                .where("parent_id", "==", record_id)
                .where("deleted_at", "==", None)
                .order_by("created_at")
            )
            subs = []
            async for sub_doc in q.stream():
                sd = sub_doc.to_dict()
                subs.append({
                    "id": sub_doc.id,
                    "title": sd.get("title", ""),
                    "type": sd.get("type", ""),
                    "status": sd.get("status", ""),
                    "created_at": str(sd.get("created_at", "")),
                })
            return subs
        tasks.append(("sub_records", _get_sub_records()))

    # Notebookログ取得
    if include_notebook_log:
        async def _get_notebook_log():
            logs_ref = record_ref.collection("cell_logs").order_by("cell_number")
            cells = []
            total_duration = 0.0
            async for log_doc in logs_ref.stream():
                ld = log_doc.to_dict()
                cells.append(ld)
                total_duration += ld.get("duration_sec", 0.0)

            key_cells = [
                c for c in cells
                if len(c.get("new_vars", {})) >= 2
                or c.get("changed_vars")
                or c.get("error")
            ]
            # 最終名前空間を構築
            final_ns = {}
            for c in cells:
                for var, val in c.get("new_vars", {}).items():
                    final_ns[var] = val
                for var, info in c.get("changed_vars", {}).items():
                    final_ns[var] = info.get("after", info) if isinstance(info, dict) else info

            return {
                "summary": d.get("notebook_summary"),
                "cell_count": len(cells),
                "total_duration_sec": total_duration,
                "key_cells": key_cells[:20],
                "final_namespace": final_ns,
            }
        tasks.append(("notebook_log", _get_notebook_log()))

    # 解析履歴取得
    if include_analyses:
        async def _get_analyses():
            q = record_ref.collection("analyses").order_by("executed_at", direction="DESCENDING")
            analyses = []
            async for a_doc in q.stream():
                analyses.append(a_doc.to_dict())
            return analyses
        tasks.append(("analyses", _get_analyses()))

    # トレース取得
    if include_traces:
        async def _get_traces():
            q = record_ref.collection("traces").order_by("timestamp")
            traces = []
            async for t_doc in q.stream():
                traces.append(t_doc.to_dict())
            return traces
        tasks.append(("traces", _get_traces()))

    if tasks:
        gathered = await asyncio.gather(*[t[1] for t in tasks])
        for (key, _), value in zip(tasks, gathered):
            result[key] = value

    return result


# -------------------------------------------------------------------
# Tool 3: compare
# -------------------------------------------------------------------

@mcp.tool()
async def compare(
    team_id: str,
    record_ids: list[str],
    fields: list[str] | None = None,
) -> dict:
    """複数レコードの条件・結果を比較表で返す。"""
    import asyncio

    if len(record_ids) < 2 or len(record_ids) > 10:
        raise ValueError("record_ids must contain 2 to 10 entries")

    async def _get_record(rid):
        ref = (
            db.collection("teams").document(team_id)
            .collection("records").document(rid)
        )
        doc = await ref.get()
        if not doc.exists:
            raise ValueError(f"Record {rid} not found")
        return doc

    docs = await asyncio.gather(*[_get_record(rid) for rid in record_ids])

    # フィールド自動検出
    if fields is None:
        field_set = set()
        for doc in docs:
            d = doc.to_dict()
            field_set.update(d.get("conditions", {}).keys())
            field_set.update(d.get("results", {}).keys())
        fields = sorted(field_set)

    records_data = []
    for doc in docs:
        d = doc.to_dict()
        merged = {**d.get("conditions", {}), **d.get("results", {})}
        entry = {"id": doc.id, "title": d.get("title", "")}
        for f in fields:
            entry[f] = merged.get(f)
        records_data.append(entry)

    # 共通/差分の検出
    common = {}
    differences = []
    for f in fields:
        values = [r.get(f) for r in records_data]
        if all(v == values[0] for v in values):
            common[f] = values[0]
        else:
            differences.append(f)

    return {
        "fields": fields,
        "records": records_data,
        "differences": differences,
        "common": common,
    }


# -------------------------------------------------------------------
# Tool 4: data_preview
# -------------------------------------------------------------------

@mcp.tool()
async def data_preview(
    team_id: str,
    record_id: str,
    filename: str,
) -> dict:
    """レコードに紐づくファイルのプレビュー/統計サマリーを取得する。"""
    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    doc = await record_ref.get()
    if not doc.exists:
        raise ValueError(f"Record {record_id} not found")
    d = doc.to_dict()

    # file_refs からファイルを探す
    file_ref = None
    for fr in d.get("file_refs", []):
        if fr.get("name") == filename:
            file_ref = fr
            break
    if file_ref is None:
        raise ValueError(f"File {filename} not found in record {record_id}")

    # preview_refs に既存プレビューがあるか確認
    preview_refs = d.get("preview_refs", {})
    preview_key = filename.replace(".", "_")
    if preview_key in preview_refs:
        return {
            "filename": filename,
            "file_type": preview_refs[preview_key].get("type", "unknown"),
            "size_bytes": preview_refs[preview_key].get("size_bytes", 0),
            "preview": preview_refs[preview_key],
        }

    # Nextcloudから取得してオンデマンドプレビュー生成
    nextcloud_path = d.get("nextcloud_path", "")
    src_path = f"{nextcloud_path}/_data/{filename}"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    import tempfile
    import numpy as np
    import pandas as pd
    from pathlib import Path

    size_bytes = file_ref.get("size", 0)

    if size_bytes > 100 * 1024 * 1024:
        return {
            "filename": filename,
            "file_type": ext,
            "size_bytes": size_bytes,
            "preview": {"note": "ファイルが100MBを超えるためプレビュー生成をスキップ"},
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / filename
        await nc.download_file(src_path, str(local_path))

        if ext == "npy":
            arr = np.load(str(local_path), allow_pickle=False)
            preview = {
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "stats": {},
            }
            if np.issubdtype(arr.dtype, np.number):
                preview["stats"] = {
                    "min": float(np.nanmin(arr)),
                    "max": float(np.nanmax(arr)),
                    "mean": float(np.nanmean(arr)),
                    "std": float(np.nanstd(arr)),
                }
            return {
                "filename": filename,
                "file_type": "npy",
                "size_bytes": size_bytes,
                "preview": preview,
            }

        elif ext in ("csv", "tsv"):
            delimiter = "," if ext == "csv" else "\t"
            df = pd.read_csv(str(local_path), delimiter=delimiter, nrows=1000)
            preview = {
                "columns": list(df.columns),
                "shape": [len(df), len(df.columns)],
                "head": df.head(10).to_dict(orient="records"),
                "stats": df.describe(include="all").to_dict(),
            }
            return {
                "filename": filename,
                "file_type": "csv",
                "size_bytes": size_bytes,
                "preview": preview,
            }

        elif ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp"):
            from PIL import Image
            img = Image.open(str(local_path))
            preview = {
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "format": img.format,
            }
            # サムネイルパスがあれば含める
            thumb_key = filename.rsplit(".", 1)[0]
            thumb_path = f"{nextcloud_path}/_preview/{thumb_key}_thumb.jpg"
            preview["thumbnail_path"] = thumb_path
            return {
                "filename": filename,
                "file_type": "image",
                "size_bytes": size_bytes,
                "preview": preview,
            }

        else:
            # テキストとして読み込み
            try:
                text = local_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = local_path.read_text(encoding="shift_jis", errors="replace")
            return {
                "filename": filename,
                "file_type": "text",
                "size_bytes": size_bytes,
                "preview": {"text": text[:2000], "line_count": text.count("\n") + 1},
            }


# -------------------------------------------------------------------
# Tool 5: get_results
# -------------------------------------------------------------------

@mcp.tool()
async def get_results(
    team_id: str,
    result_key: str,
    tags: list[str] | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """特定の結果キーを持つレコードを横断的に取得する。"""
    q = (
        db.collection("teams").document(team_id)
        .collection("records")
        .where("deleted_at", "==", None)
        .where("result_keys", "array_contains", result_key)
    )
    if status:
        q = q.where("status", "==", status)
    if tags:
        q = q.where("tags", "array_contains_any", tags)

    q = q.order_by("created_at", direction="DESCENDING").limit(limit)

    results = []
    async for doc in q.stream():
        d = doc.to_dict()
        results.append({
            "record_id": doc.id,
            "title": d.get("title", ""),
            "value": d.get("results", {}).get(result_key),
            "conditions": dict(list(d.get("conditions", {}).items())[:5]),
            "created_at": str(d.get("created_at", "")),
        })
    return results


# -------------------------------------------------------------------
# Tool 6: aggregate
# -------------------------------------------------------------------

@mcp.tool()
async def aggregate(
    team_id: str,
    result_key: str,
    group_by: str | None = None,
    tags: list[str] | None = None,
    status: str = "success",
) -> dict:
    """結果の数値を集約して統計量を返す。"""
    import numpy as np

    entries = await get_results(
        team_id=team_id,
        result_key=result_key,
        tags=tags,
        status=status,
        limit=500,
    )

    values = [
        e["value"] for e in entries
        if isinstance(e["value"], (int, float))
    ]

    if not values:
        return {
            "result_key": result_key,
            "total_count": 0,
            "overall": {},
            "groups": None,
        }

    arr = np.array(values, dtype=float)
    overall = {
        "mean": float(np.mean(arr)),
        "std": float(np.std(arr)),
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "median": float(np.median(arr)),
    }

    groups = None
    if group_by:
        import pandas as pd
        rows = [
            {
                "value": e["value"],
                "group": e["conditions"].get(group_by),
            }
            for e in entries
            if isinstance(e["value"], (int, float)) and e["conditions"].get(group_by) is not None
        ]
        if rows:
            df = pd.DataFrame(rows)
            grouped = df.groupby("group")["value"].agg(["count", "mean", "std", "min", "max", "median"])
            groups = [
                {"group_value": idx, **row.to_dict()}
                for idx, row in grouped.iterrows()
            ]

    return {
        "result_key": result_key,
        "total_count": len(values),
        "overall": overall,
        "groups": groups,
    }


# -------------------------------------------------------------------
# Tool 7: get_timeline
# -------------------------------------------------------------------

@mcp.tool()
async def get_timeline(
    team_id: str,
    sample: str | None = None,
    record_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """実験の時系列履歴を取得する。"""
    records_ref = db.collection("teams").document(team_id).collection("records")

    if sample:
        q = (
            records_ref
            .where("deleted_at", "==", None)
            .where("conditions.sample", "==", sample)
            .order_by("created_at")
            .limit(limit)
        )
    elif record_id:
        q = (
            records_ref
            .where("deleted_at", "==", None)
            .where("parent_id", "==", record_id)
            .order_by("created_at")
            .limit(limit)
        )
    else:
        q = (
            records_ref
            .where("deleted_at", "==", None)
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
        )

    results = []
    async for doc in q.stream():
        d = doc.to_dict()
        results.append({
            "record_id": doc.id,
            "title": d.get("title", ""),
            "type": d.get("type", ""),
            "status": d.get("status", ""),
            "created_at": str(d.get("created_at", "")),
            "created_by": d.get("created_by", ""),
            "conditions_summary": dict(list(d.get("conditions", {}).items())[:5]),
            "results_summary": dict(list(d.get("results", {}).items())[:5]),
        })
    return results


# -------------------------------------------------------------------
# Tool 8: get_trace
# -------------------------------------------------------------------

@mcp.tool()
async def get_trace(
    team_id: str,
    record_id: str,
    trace_id: str | None = None,
    function_name: str | None = None,
) -> list[dict]:
    """@exp.track で記録された関数トレースを取得する。"""
    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    traces_ref = record_ref.collection("traces")

    if trace_id:
        doc = await traces_ref.document(trace_id).get()
        if not doc.exists:
            raise ValueError(f"Trace {trace_id} not found")
        return [doc.to_dict()]

    q = traces_ref.order_by("timestamp")
    if function_name:
        q = traces_ref.where("function", "==", function_name).order_by("timestamp")

    results = []
    async for doc in q.stream():
        td = doc.to_dict()
        results.append({
            "trace_id": doc.id,
            "type": td.get("type", ""),
            "timestamp": str(td.get("timestamp", "")),
            "function": td.get("function"),
            "file": td.get("file", ""),
            "line": td.get("line", 0),
            "args": td.get("args"),
            "return_value": td.get("return_value"),
            "call_tree": td.get("call_tree"),
            "duration_sec": td.get("duration_sec", 0.0),
            "summary": td.get("summary", ""),
        })
    return results


# -------------------------------------------------------------------
# Tool 9: explain_result
# -------------------------------------------------------------------

@mcp.tool()
async def explain_result(
    team_id: str,
    record_id: str,
    result_key: str,
) -> dict:
    """結果の値がどのように算出されたか、セルログ・トレース・解析履歴から説明する。"""
    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    doc = await record_ref.get()
    if not doc.exists:
        raise ValueError(f"Record {record_id} not found")
    d = doc.to_dict()
    value = d.get("results", {}).get(result_key)
    if value is None:
        raise ValueError(f"Result key '{result_key}' not found in record {record_id}")

    sources = []

    # セルログから探索
    cell_logs_ref = record_ref.collection("cell_logs").order_by("cell_number")
    async for log_doc in cell_logs_ref.stream():
        ld = log_doc.to_dict()
        new_vars = ld.get("new_vars", {})
        changed_vars = ld.get("changed_vars", {})
        source_code = ld.get("source", "")
        if (
            result_key in new_vars
            or result_key in changed_vars
            or result_key in source_code
        ):
            sources.append({
                "type": "cell_log",
                "cell_number": ld.get("cell_number"),
                "source_excerpt": source_code[:500],
                "new_vars": {k: v for k, v in new_vars.items() if k == result_key},
                "changed_vars": {k: v for k, v in changed_vars.items() if k == result_key},
                "timestamp": str(ld.get("timestamp", "")),
            })

    # トレースから探索
    traces_ref = record_ref.collection("traces").order_by("timestamp")
    async for t_doc in traces_ref.stream():
        td = t_doc.to_dict()
        ret = td.get("return_value", {})
        if isinstance(ret, dict) and result_key in ret:
            sources.append({
                "type": "trace",
                "trace_id": t_doc.id,
                "function": td.get("function"),
                "return_value": {result_key: ret[result_key]},
                "timestamp": str(td.get("timestamp", "")),
            })

    # 解析履歴から探索
    analyses_ref = record_ref.collection("analyses").order_by("executed_at")
    async for a_doc in analyses_ref.stream():
        ad = a_doc.to_dict()
        if result_key in ad.get("results", {}):
            sources.append({
                "type": "analysis",
                "analysis_id": a_doc.id,
                "name": ad.get("name"),
                "result_value": ad["results"][result_key],
                "code_excerpt": ad.get("code", "")[:500],
                "timestamp": str(ad.get("executed_at", "")),
            })

    # 説明テキストを生成
    if sources:
        first = sources[-1]  # 最新のソース
        if first["type"] == "cell_log":
            explanation = (
                f"{result_key} = {value} は、セル{first['cell_number']}で算出されました。"
                f" コード: {first['source_excerpt'][:100]}..."
            )
        elif first["type"] == "trace":
            explanation = (
                f"{result_key} = {value} は、関数 {first['function']} の"
                f" 戻り値として記録されました。"
            )
        elif first["type"] == "analysis":
            explanation = (
                f"{result_key} = {value} は、解析 '{first['name']}'"
                f" (ID: {first['analysis_id']}) で算出されました。"
            )
        else:
            explanation = f"{result_key} = {value} （算出元の詳細は不明）"
    else:
        explanation = f"{result_key} = {value} （算出過程のログが見つかりませんでした）"

    return {
        "record_id": record_id,
        "result_key": result_key,
        "value": value,
        "sources": sources,
        "explanation": explanation,
    }


# -------------------------------------------------------------------
# Tool 10: compare_runs
# -------------------------------------------------------------------

@mcp.tool()
async def compare_runs(
    team_id: str,
    record_ids: list[str],
    function_name: str | None = None,
) -> dict:
    """同一関数/処理の異なるパラメータ実行を比較する。"""
    import asyncio

    if len(record_ids) < 2 or len(record_ids) > 10:
        raise ValueError("record_ids must contain 2 to 10 entries")

    async def _get_record_data(rid):
        ref = (
            db.collection("teams").document(team_id)
            .collection("records").document(rid)
        )
        doc = await ref.get()
        if not doc.exists:
            raise ValueError(f"Record {rid} not found")
        d = doc.to_dict()

        params = {}
        if function_name:
            # トレースからargsを取得
            traces_ref = ref.collection("traces").where("function", "==", function_name)
            async for t_doc in traces_ref.stream():
                td = t_doc.to_dict()
                if td.get("args"):
                    params = td["args"]
                    break
        else:
            params = d.get("conditions", {})

        return {
            "record_id": rid,
            "params": params,
            "results": d.get("results", {}),
        }

    records_data = await asyncio.gather(*[_get_record_data(rid) for rid in record_ids])

    # パラメータ差分
    all_param_keys = set()
    for rd in records_data:
        all_param_keys.update(rd["params"].keys())

    parameter_diffs = []
    common_params = {}
    for key in sorted(all_param_keys):
        values = {rd["record_id"]: rd["params"].get(key) for rd in records_data}
        unique_values = set(str(v) for v in values.values())
        if len(unique_values) == 1:
            common_params[key] = records_data[0]["params"].get(key)
        else:
            parameter_diffs.append({"param": key, "values": values})

    # 結果差分
    all_result_keys = set()
    for rd in records_data:
        all_result_keys.update(rd["results"].keys())

    result_diffs = []
    for key in sorted(all_result_keys):
        values = {rd["record_id"]: rd["results"].get(key) for rd in records_data}
        unique_values = set(str(v) for v in values.values())
        if len(unique_values) > 1:
            result_diffs.append({"result_key": key, "values": values})

    return {
        "function_name": function_name,
        "parameter_diffs": parameter_diffs,
        "result_diffs": result_diffs,
        "common_params": common_params,
    }


# -------------------------------------------------------------------
# Tool 11: get_notebook_log
# -------------------------------------------------------------------

@mcp.tool()
async def get_notebook_log(
    team_id: str,
    record_id: str,
    level: str = "L2",
    cell_range: list[int] | None = None,
    filter_imports: list[str] | None = None,
) -> dict:
    """Notebookのセル実行履歴を取得する。"""
    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    doc = await record_ref.get()
    if not doc.exists:
        raise ValueError(f"Record {record_id} not found")
    d = doc.to_dict()

    # セルログを全件取得
    logs_ref = record_ref.collection("cell_logs").order_by("cell_number")
    all_cells = []
    async for log_doc in logs_ref.stream():
        all_cells.append(log_doc.to_dict())

    # cell_range フィルタ
    if cell_range and len(cell_range) == 2:
        start, end = cell_range
        all_cells = [c for c in all_cells if start <= c.get("cell_number", 0) <= end]

    # filter_imports フィルタ
    if filter_imports:
        all_cells = [
            c for c in all_cells
            if any(lib in c.get("imports", []) for lib in filter_imports)
        ]

    total_duration = sum(c.get("duration_sec", 0.0) for c in all_cells)
    all_imports = set()
    for c in all_cells:
        all_imports.update(c.get("imports", []))

    result = {
        "record_id": record_id,
        "notebook_summary": d.get("notebook_summary"),
        "cell_count": len(all_cells),
        "execution_time_total_sec": total_duration,
        "libraries_used": sorted(all_imports),
        "key_cells": None,
        "final_namespace": None,
        "cells": None,
    }

    if level in ("L2", "L3"):
        key_cells = [
            {
                "cell_number": c.get("cell_number"),
                "source": c.get("source", "")[:500],
                "new_vars": list(c.get("new_vars", {}).keys()),
                "changed_vars": list(c.get("changed_vars", {}).keys()),
                "duration_sec": c.get("duration_sec", 0.0),
                "error": c.get("error"),
            }
            for c in all_cells
            if len(c.get("new_vars", {})) >= 2
            or c.get("changed_vars")
            or c.get("error")
        ]
        result["key_cells"] = key_cells

        # final_namespace
        final_ns = {}
        for c in all_cells:
            for var, val in c.get("new_vars", {}).items():
                final_ns[var] = val
            for var, info in c.get("changed_vars", {}).items():
                final_ns[var] = info.get("after", info) if isinstance(info, dict) else info
        result["final_namespace"] = final_ns

    if level == "L3":
        result["cells"] = [
            {
                "cell_number": c.get("cell_number"),
                "source": c.get("source", ""),
                "new_vars": c.get("new_vars", {}),
                "changed_vars": c.get("changed_vars", {}),
                "duration_sec": c.get("duration_sec", 0.0),
                "imports": c.get("imports", []),
                "error": c.get("error"),
                "output_summary": c.get("output_summary"),
            }
            for c in all_cells
        ]

    return result


# -------------------------------------------------------------------
# Tool 12: execute_code
# -------------------------------------------------------------------

import random
import re
import hashlib
import ast
import asyncio
import shutil
import subprocess
import sys
import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

# Crockford's Base32 文字セット
CROCKFORD_CHARS = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

BANNED_IMPORTS = {
    "os", "subprocess", "socket", "http", "urllib",
    "requests", "shutil", "pathlib",
    "ctypes", "multiprocessing", "threading",
    "signal", "resource", "gc",
}


def generate_analysis_id(length: int = 4) -> str:
    """Crockford's Base32 のランダムID（4文字 = 約100万通り）"""
    return "".join(random.choices(CROCKFORD_CHARS, k=length))


async def generate_unique_analysis_id(
    db, team_id: str, record_id: str
) -> str:
    """レコード内で重複しないIDを生成する。"""
    analyses_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
        .collection("analyses")
    )
    for _ in range(10):
        aid = generate_analysis_id()
        doc = await analyses_ref.document(aid).get()
        if not doc.exists:
            return aid
    raise RuntimeError("解析IDの生成に失敗しました（重複回避リトライ上限）")


def auto_generate_name(code: str, prompt: str | None) -> str:
    """コードとプロンプトから人間可読な名前を自動生成する。"""
    if "curve_fit" in code or "fitting" in code.lower():
        return "curve_fit"
    elif "peak" in code.lower():
        return "peak_analysis"
    elif "plot" in code.lower() or "plt." in code:
        return "visualization"
    elif prompt:
        return re.sub(r'[^\w]', '_', prompt[:20]).strip('_').lower()
    return "analysis"


async def ensure_unique_name(
    db, team_id: str, record_id: str, base_name: str
) -> str:
    """レコード内で重複しない名前を返す。"""
    analyses_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
        .collection("analyses")
    )
    query = analyses_ref.where("name", ">=", base_name).where("name", "<=", base_name + "\uf8ff")
    existing = [doc.to_dict()["name"] async for doc in query.stream()]

    if base_name not in existing:
        return base_name
    for i in range(1, 1000):
        candidate = f"{base_name}_{i:03d}"
        if candidate not in existing:
            return candidate
    return f"{base_name}_{generate_analysis_id()}"


def validate_code(code: str) -> list[str]:
    """コードの安全性を検査する。"""
    violations = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"構文エラー: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name.split(".")[0]
                if module in BANNED_IMPORTS:
                    violations.append(f"禁止されたモジュール: {module}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module = node.module.split(".")[0]
                if module in BANNED_IMPORTS:
                    violations.append(f"禁止されたモジュール: {module}")
    return violations


def _detect_packages(code: str) -> dict:
    """コードで使用されているパッケージを検出する。"""
    packages = {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return packages
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                packages[alias.name.split(".")[0]] = "unknown"
        elif isinstance(node, ast.ImportFrom) and node.module:
            packages[node.module.split(".")[0]] = "unknown"
    return packages


async def _execute_in_subprocess(
    code: str, file_paths: dict[str, str], timeout: int
) -> dict:
    """subprocess でコードを実行する簡易サンドボックス。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 1. データファイルを tmpdir にコピー
        for name, local_path in file_paths.items():
            shutil.copy(local_path, Path(tmpdir) / name)

        # 2. ラッパースクリプトを生成
        file_var_lines = "\n".join(
            f'{name.replace(".", "_")}_path = "{Path(tmpdir) / name}"'
            for name in file_paths
        )
        first_file = next(iter(file_paths.values()), "")
        wrapper = f"""
import sys, json, os
os.chdir("{tmpdir}")
_result = {{}}
_images = []

# ファイルパス変数を注入
{file_var_lines}
file_path = "{first_file}"

# ユーザーコード実行
exec(open("{tmpdir}/_code.py").read())

# matplotlib の Figure を自動保存
try:
    import matplotlib
    import matplotlib.pyplot as plt
    for i, fig_num in enumerate(plt.get_fignums()):
        fig = plt.figure(fig_num)
        img_path = f"{tmpdir}/_img_{{i}}.png"
        fig.savefig(img_path, dpi=150, bbox_inches='tight')
        _images.append(img_path)
except ImportError:
    pass

# result 変数を収集
if 'result' in dir():
    _result = result

print(json.dumps({{"results": _result, "images": _images}}, default=str))
"""
        (Path(tmpdir) / "_code.py").write_text(code)
        (Path(tmpdir) / "_wrapper.py").write_text(wrapper)

        # 3. subprocess で実行
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(tmpdir) / "_wrapper.py"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir,
            env={
                "PATH": os.environ.get("PATH", ""),
                "HOME": tmpdir,
            },
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": f"実行タイムアウト ({timeout}秒)", "results": {}, "images": []}

        if proc.returncode != 0:
            return {"error": stderr.decode(), "results": {}, "images": []}

        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            return {
                "error": f"出力のパースに失敗: {stdout.decode()[:500]}",
                "results": {},
                "images": [],
                "stdout": stdout.decode(),
            }


@mcp.tool()
async def execute_code(
    team_id: str,
    record_id: str,
    code: str,
    files: list[str] | None = None,
    input_analyses: list[str] | None = None,
    name: str | None = None,
    prompt: str | None = None,
    timeout_sec: int = 60,
) -> dict:
    """Pythonコードをサンドボックスで実行し、結果を自動保存する。"""
    import time
    start_time = time.monotonic()

    # 0. コード検査
    violations = validate_code(code)
    if violations:
        return {
            "analysis_id": "",
            "name": "",
            "results": {},
            "stdout": "",
            "images": [],
            "duration_sec": 0.0,
            "error": "コード検査エラー: " + "; ".join(violations),
        }

    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    doc = await record_ref.get()
    if not doc.exists:
        raise ValueError(f"Record {record_id} not found")
    d = doc.to_dict()
    nextcloud_path = d.get("nextcloud_path", "")

    # 1. 解析IDと名前の生成
    analysis_id = await generate_unique_analysis_id(db, team_id, record_id)
    base_name = name or auto_generate_name(code, prompt)
    final_name = await ensure_unique_name(db, team_id, record_id, base_name)

    # 2. 入力ファイルの取得
    file_paths = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        if files:
            for fname in files:
                src = f"{nextcloud_path}/_data/{fname}"
                local = str(Path(tmpdir) / fname)
                await nc.download_file(src, local)
                file_paths[fname] = local

        if input_analyses:
            for aid in input_analyses:
                a_doc = await (
                    record_ref.collection("analyses").document(aid).get()
                )
                if a_doc.exists:
                    a_data = a_doc.to_dict()
                    result_path = str(Path(tmpdir) / f"analysis_{aid}.json")
                    Path(result_path).write_text(
                        json.dumps(a_data.get("results", {}), default=str, ensure_ascii=False)
                    )
                    file_paths[f"analysis_{aid}.json"] = result_path

        # 3. コード実行
        exec_result = await _execute_in_subprocess(code, file_paths, timeout_sec)

    duration = time.monotonic() - start_time

    # 4. 画像の保存
    saved_images = []
    for img_path_str in exec_result.get("images", []):
        img_path = Path(img_path_str)
        if img_path.exists():
            img_name = f"{analysis_id}_{img_path.name}"
            dest = f"{nextcloud_path}/_analyses/{img_name}"
            await nc.upload_file(dest, img_path.read_bytes())
            saved_images.append(img_name)

    # 5. 解析履歴をFirestoreに保存
    analysis_doc = {
        "id": analysis_id,
        "name": final_name,
        "code": code,
        "input_files": files or [],
        "input_analyses": input_analyses or [],
        "results": exec_result.get("results", {}),
        "images": saved_images,
        "stdout": exec_result.get("stdout", ""),
        "executed_at": datetime.now(timezone.utc),
        "executed_by": "claude",
        "prompt": prompt,
        "duration_sec": duration,
        "packages": _detect_packages(code),
        "error": exec_result.get("error"),
    }
    await (
        record_ref.collection("analyses").document(analysis_id)
        .set(analysis_doc)
    )

    return {
        "analysis_id": analysis_id,
        "name": final_name,
        "results": exec_result.get("results", {}),
        "stdout": exec_result.get("stdout", ""),
        "images": saved_images,
        "duration_sec": duration,
        "error": exec_result.get("error"),
    }


# -------------------------------------------------------------------
# Tool 13: batch_execute
# -------------------------------------------------------------------

BATCH_CONCURRENCY = 5

@mcp.tool()
async def batch_execute(
    team_id: str,
    record_ids: list[str],
    code: str,
    file: str,
    name: str | None = None,
    prompt: str | None = None,
    timeout_sec: int = 60,
) -> dict:
    """同一Pythonコードを複数レコードのデータに一括適用する。"""
    import time
    start_time = time.monotonic()

    if len(record_ids) < 2 or len(record_ids) > 20:
        raise ValueError("record_ids must contain 2 to 20 entries")

    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def execute_one(rid: str) -> dict:
        async with semaphore:
            try:
                result = await execute_code(
                    team_id=team_id,
                    record_id=rid,
                    code=code,
                    files=[file],
                    name=name,
                    prompt=prompt,
                    timeout_sec=timeout_sec,
                )
                return {"record_id": rid, **result}
            except Exception as e:
                return {
                    "record_id": rid,
                    "analysis_id": "",
                    "name": "",
                    "results": {},
                    "stdout": "",
                    "images": [],
                    "duration_sec": 0.0,
                    "error": str(e),
                }

    results = await asyncio.gather(*[execute_one(rid) for rid in record_ids])

    succeeded = sum(1 for r in results if not r.get("error"))
    failed = sum(1 for r in results if r.get("error"))

    # 横断比較表: 成功した結果のresultsを集約
    results_table = []
    for r in results:
        if not r.get("error") and r.get("results"):
            row = {"record_id": r["record_id"]}
            row.update(r["results"])
            results_table.append(row)

    return {
        "results": list(results),
        "summary": {
            "succeeded": succeeded,
            "failed": failed,
            "results_table": results_table,
        },
        "total_duration_sec": time.monotonic() - start_time,
    }


# -------------------------------------------------------------------
# Tool 14: get_image
# -------------------------------------------------------------------

import base64
import mimetypes

@mcp.tool()
async def get_image(
    team_id: str,
    record_id: str,
    image_name: str | None = None,
    analysis_id: str | None = None,
    as_base64: bool = True,
) -> dict:
    """レコードに保存された画像を取得する。"""
    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    doc = await record_ref.get()
    if not doc.exists:
        raise ValueError(f"Record {record_id} not found")
    d = doc.to_dict()
    nextcloud_path = d.get("nextcloud_path", "")

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".tif", ".tiff", ".bmp", ".gif"}

    if image_name is None:
        # 画像一覧を返す
        images = []
        # file_refs から画像を収集
        for fr in d.get("file_refs", []):
            fname = fr.get("name", "")
            ext = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if ext in IMAGE_EXTENSIONS:
                images.append({
                    "name": fname,
                    "analysis_id": None,
                    "content_base64": "",
                    "mime_type": mimetypes.guess_type(fname)[0] or "application/octet-stream",
                    "size": fr.get("size", 0),
                })
        # analyses から画像を収集
        analyses_ref = record_ref.collection("analyses").order_by("executed_at", direction="DESCENDING")
        async for a_doc in analyses_ref.stream():
            ad = a_doc.to_dict()
            for img in ad.get("images", []):
                images.append({
                    "name": img,
                    "analysis_id": a_doc.id,
                    "content_base64": "",
                    "mime_type": mimetypes.guess_type(img)[0] or "image/png",
                    "size": 0,
                })
        return {"images": images}

    # 特定画像の取得
    if analysis_id:
        src_path = f"{nextcloud_path}/_analyses/{analysis_id}_{image_name}"
    else:
        # まず _analyses 下を試す、なければ _data 下
        src_path = f"{nextcloud_path}/_data/{image_name}"

    # サムネイルがあればそちらを優先（元画像が大きい場合）
    preview_refs = d.get("preview_refs", {})
    preview_key = image_name.replace(".", "_") if image_name else ""
    if preview_key in preview_refs:
        thumb_path = preview_refs[preview_key].get("thumbnail_path")
        if thumb_path and not as_base64:
            src_path = thumb_path

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / (image_name or "image")
        try:
            await nc.download_file(src_path, str(local_path))
        except Exception:
            # analysis_id付きパスで再試行
            if analysis_id:
                alt_path = f"{nextcloud_path}/_analyses/{image_name}"
                await nc.download_file(alt_path, str(local_path))
            else:
                raise

        content = local_path.read_bytes()
        mime = mimetypes.guess_type(image_name or "")[0] or "image/png"

        image_data = {
            "name": image_name,
            "analysis_id": analysis_id,
            "mime_type": mime,
            "size": len(content),
        }
        if as_base64:
            image_data["content_base64"] = base64.b64encode(content).decode("ascii")
        else:
            image_data["content_base64"] = ""

    return {"images": [image_data]}


# ===================================================================
# サーバー起動
# ===================================================================

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8080, path="/mcp")
```

---

## 2. Cloud Functions実装仕様

### 2.1 embedding_generator

**トリガー**: Firestore `teams/{team_id}/records/{record_id}` の `onCreate` および `onUpdate`（embedding_text フィールド変更時）

**ランタイム**: Python 3.12, 256MB メモリ, 60秒タイムアウト

```python
# functions/embedding_generator/main.py
import hashlib
import functions_framework
from google.cloud import firestore
from vertexai.language_models import TextEmbeddingModel

model = TextEmbeddingModel.from_pretrained("text-embedding-004")
db = firestore.Client(project="labvault-project", database="labvault")


def _extract_string(field_value) -> str | None:
    """Firestoreイベントのフィールド値から文字列を抽出する。"""
    if field_value is None:
        return None
    if isinstance(field_value, dict):
        return field_value.get("stringValue")
    return str(field_value)


@functions_framework.cloud_event
def on_record_change(cloud_event):
    """レコード作成/更新時にembeddingを生成してFirestoreに書き戻す。"""
    # 1. イベントからドキュメントパスとデータを取得
    resource = cloud_event.data["value"]
    doc_path = cloud_event["subject"]  # teams/{team_id}/records/{record_id}
    fields = resource.get("fields", {})

    # 2. embedding_text を取得
    embedding_text = _extract_string(fields.get("embedding_text"))
    if not embedding_text:
        return

    # 3. 既存のembeddingと同じテキストなら再生成しない（無限ループ防止）
    existing_hash = _extract_string(fields.get("embedding_text_hash"))
    new_hash = hashlib.sha256(embedding_text.encode()).hexdigest()[:16]
    if existing_hash == new_hash:
        return

    # 4. Vertex AI でembedding生成
    embeddings = model.get_embeddings(
        [embedding_text],
        output_dimensionality=768,
    )
    vector = embeddings[0].values

    # 5. Firestore に書き戻し
    doc_ref = db.document(doc_path)
    doc_ref.update({
        "embedding": vector,
        "embedding_text_hash": new_hash,
        "embedding_updated_at": firestore.SERVER_TIMESTAMP,
    })
```

**requirements.txt**:
```
functions-framework==3.*
google-cloud-firestore==2.*
google-cloud-aiplatform==1.*
```

**デプロイコマンド**:
```bash
gcloud functions deploy embedding-generator \
  --gen2 \
  --region=asia-northeast1 \
  --runtime=python312 \
  --source=functions/embedding_generator/ \
  --entry-point=on_record_change \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.written" \
  --trigger-event-filters="database=labvault" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}" \
  --memory=256Mi \
  --timeout=60s \
  --service-account=functions-sa@labvault-project.iam.gserviceaccount.com
```

---

### 2.2 nextcloud_poller

**トリガー**: Cloud Scheduler（5分間隔）→ HTTP

**ランタイム**: Python 3.12, 512MB メモリ, 120秒タイムアウト

```python
# functions/nextcloud_poller/main.py
import functions_framework
from google.cloud import firestore, secretmanager
from nc_py_api import Nextcloud
from datetime import datetime, timezone

db = firestore.Client(project="labvault-project", database="labvault")


def _get_nextcloud_client() -> Nextcloud:
    """Secret Managerから認証情報を取得してNextcloudクライアントを返す。"""
    client = secretmanager.SecretManagerServiceClient()
    project_id = "labvault-project"

    url = client.access_secret_version(
        name=f"projects/{project_id}/secrets/nextcloud-url/versions/latest"
    ).payload.data.decode("utf-8")
    user = client.access_secret_version(
        name=f"projects/{project_id}/secrets/nextcloud-user/versions/latest"
    ).payload.data.decode("utf-8")
    password = client.access_secret_version(
        name=f"projects/{project_id}/secrets/nextcloud-password/versions/latest"
    ).payload.data.decode("utf-8")

    return Nextcloud(nextcloud_url=url, nc_auth_user=user, nc_auth_pass=password)


def _guess_file_type(filename: str) -> str:
    """ファイル名から種別を推定する。"""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    type_map = {
        "csv": "csv", "tsv": "tsv", "npy": "npy",
        "png": "image", "jpg": "image", "jpeg": "image",
        "tif": "image", "tiff": "image", "bmp": "image",
        "txt": "text", "log": "text", "dat": "text",
        "ras": "ras", "json": "json",
    }
    return type_map.get(ext, "binary")


def _find_modified_files(nc: Nextcloud, base_path: str, since: datetime) -> list:
    """Nextcloud WebDAV PROPFIND で変更ファイルを検出する。"""
    all_files = []

    def walk(path):
        try:
            items = nc.files.listdir(path)
        except Exception:
            return
        for item in items:
            if item.is_dir:
                if item.name == "_data" or not item.name.startswith("_"):
                    walk(item.user_path)
            else:
                if item.last_modified and item.last_modified > since:
                    all_files.append(item)

    walk(base_path)
    return all_files


def _extract_record_id(file_path: str, base_path: str) -> str | None:
    """ファイルパスからレコードIDを抽出する。
    パス例: large/group/labvault/v1/db_name/AB3F/_data/xrd.csv -> "AB3F"
    """
    relative = file_path.replace(base_path, "")
    parts = relative.split("/")
    # v{major}/{db_name}/{record_id}/...
    if len(parts) >= 3:
        return parts[2]
    return None


@functions_framework.http
def poll_nextcloud(request):
    """Nextcloudの変更を検出してFirestoreを更新する。"""
    # 1. Nextcloud認証情報をSecret Managerから取得
    nc = _get_nextcloud_client()

    # 2. 前回チェック時刻を取得
    state_ref = db.collection("_system").document("poller_state")
    state = state_ref.get().to_dict() or {}
    last_check = state.get("last_check", datetime(2020, 1, 1, tzinfo=timezone.utc))

    # 3. チーム一覧を取得
    teams = db.collection("teams").stream()

    for team_doc in teams:
        team = team_doc.to_dict()
        group_folder = team.get("nextcloud_group_folder")
        if not group_folder:
            continue

        # 4. Nextcloud WebDAV で変更ファイルを検出
        base_path = f"large/{group_folder}/labvault/"
        try:
            changed = _find_modified_files(nc, base_path, last_check)
        except Exception as e:
            print(f"Nextcloud polling error for {group_folder}: {e}")
            continue

        # 5. 各ファイルについてFirestoreに登録
        for file_info in changed:
            record_id = _extract_record_id(file_info.path, base_path)
            if not record_id:
                continue

            record_ref = (
                db.collection("teams").document(team_doc.id)
                .collection("records").document(record_id)
            )
            record = record_ref.get()

            if not record.exists:
                record_ref.set({
                    "title": f"Nextcloud投入: {record_id}",
                    "type": "experiment",
                    "status": "in_progress",
                    "tags": [],
                    "conditions": {},
                    "results": {},
                    "result_keys": [],
                    "notes": [],
                    "created_by": "nextcloud_browser",
                    "created_at": firestore.SERVER_TIMESTAMP,
                    "updated_at": firestore.SERVER_TIMESTAMP,
                    "parent_id": None,
                    "visibility": "team",
                    "deleted_at": None,
                    "file_refs": [],
                })

            record_ref.update({
                "file_refs": firestore.ArrayUnion([{
                    "name": file_info.name,
                    "path": file_info.path,
                    "size": file_info.size,
                    "type": _guess_file_type(file_info.name),
                    "uploaded_at": file_info.last_modified.isoformat(),
                    "source": "nextcloud_browser",
                }]),
                "updated_at": firestore.SERVER_TIMESTAMP,
            })

    # 6. チェック時刻を更新
    state_ref.set({"last_check": datetime.now(timezone.utc)})
    return "OK", 200
```

**requirements.txt**:
```
functions-framework==3.*
google-cloud-firestore==2.*
google-cloud-secret-manager==2.*
nc-py-api==0.17.*
```

**Cloud Scheduler 設定**:
```bash
gcloud scheduler jobs create http nextcloud-poller \
  --location=asia-northeast1 \
  --schedule="*/5 * * * *" \
  --uri="https://nextcloud-poller-XXXXX.asia-northeast1.run.app" \
  --http-method=POST \
  --oidc-service-account-email=scheduler-sa@labvault-project.iam.gserviceaccount.com
```

---

### 2.3 preview_generator

**トリガー**: Firestore `teams/{team_id}/records/{record_id}` の `onUpdate`（`file_refs` フィールド変更時）

**ランタイム**: Python 3.12, 1024MB メモリ, 300秒タイムアウト

```python
# functions/preview_generator/main.py
import json
import io
import tempfile
import functions_framework
from google.cloud import firestore
from PIL import Image
import numpy as np
import pandas as pd

db = firestore.Client(project="labvault-project", database="labvault")


def _get_nextcloud_client():
    """Secret Managerから認証情報を取得してNextcloudクライアントを返す。"""
    from google.cloud import secretmanager
    from nc_py_api import Nextcloud

    client = secretmanager.SecretManagerServiceClient()
    project_id = "labvault-project"
    url = client.access_secret_version(
        name=f"projects/{project_id}/secrets/nextcloud-url/versions/latest"
    ).payload.data.decode("utf-8")
    user = client.access_secret_version(
        name=f"projects/{project_id}/secrets/nextcloud-user/versions/latest"
    ).payload.data.decode("utf-8")
    password = client.access_secret_version(
        name=f"projects/{project_id}/secrets/nextcloud-password/versions/latest"
    ).payload.data.decode("utf-8")
    return Nextcloud(nextcloud_url=url, nc_auth_user=user, nc_auth_pass=password)


def _extract_file_refs(fields: dict) -> list[dict]:
    """Firestoreイベントのfields構造からfile_refsを抽出する。"""
    file_refs_field = fields.get("file_refs", {})
    if isinstance(file_refs_field, dict) and "arrayValue" in file_refs_field:
        values = file_refs_field["arrayValue"].get("values", [])
        refs = []
        for v in values:
            if "mapValue" in v:
                m = v["mapValue"].get("fields", {})
                refs.append({
                    k: list(fv.values())[0] if isinstance(fv, dict) else fv
                    for k, fv in m.items()
                })
        return refs
    if isinstance(file_refs_field, list):
        return file_refs_field
    return []


def _parse_doc_path(doc_path: str) -> tuple[str, str]:
    """ドキュメントパスからteam_idとrecord_idを抽出する。"""
    parts = doc_path.split("/")
    # teams/{team_id}/records/{record_id}
    team_idx = parts.index("teams") + 1 if "teams" in parts else -1
    record_idx = parts.index("records") + 1 if "records" in parts else -1
    return parts[team_idx], parts[record_idx]


def _get_nextcloud_base_path(record_ref) -> str:
    """レコードのNextcloudベースパスを取得する。"""
    doc = record_ref.get()
    return doc.to_dict().get("nextcloud_path", "")


def _guess_type(ext: str) -> str:
    type_map = {
        "png": "image", "jpg": "image", "jpeg": "image",
        "tif": "image", "tiff": "image", "bmp": "image",
        "npy": "npy", "csv": "csv", "tsv": "csv",
        "txt": "text", "log": "text", "dat": "text",
    }
    return type_map.get(ext, "binary")


def _save_preview_meta(nc, nextcloud_base: str, original_name: str, meta: dict):
    """プレビューメタデータJSONをNextcloudに保存する。"""
    stem = original_name.rsplit(".", 1)[0]
    meta_path = f"{nextcloud_base}/_preview/{stem}_meta.json"
    nc.files.upload(meta_path, json.dumps(meta, ensure_ascii=False, default=str).encode())


def _update_preview_refs(record_ref, original_name: str, meta: dict):
    """Firestoreのレコードに preview_refs を追加する。"""
    record_ref.update({
        f"preview_refs.{original_name.replace('.', '_')}": meta,
        "updated_at": firestore.SERVER_TIMESTAMP,
    })


def _preview_image(nc, ref: dict, nextcloud_base: str, record_ref):
    """画像ファイルのプレビュー生成。サムネイルとメタデータ。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    with tempfile.NamedTemporaryFile(suffix=f".{name.rsplit('.', 1)[-1]}") as tmp:
        nc.files.download(src_path, tmp.name)
        img = Image.open(tmp.name)

        meta = {
            "filename": name,
            "type": "image",
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "format": img.format,
            "size_bytes": ref.get("size", 0),
        }

        # サムネイル生成（256x256）
        thumb = img.copy()
        thumb.thumbnail((256, 256), Image.Resampling.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="JPEG", quality=85)
        thumb_bytes = thumb_buf.getvalue()

        stem = name.rsplit(".", 1)[0]
        thumb_name = f"{stem}_thumb.jpg"
        thumb_path = f"{nextcloud_base}/_preview/{thumb_name}"
        nc.files.upload(thumb_path, thumb_bytes)

        # プレビュー画像（1024x1024）
        preview = img.copy()
        preview.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        preview_buf = io.BytesIO()
        preview.save(preview_buf, format="JPEG", quality=90)
        preview_bytes = preview_buf.getvalue()

        preview_name = f"{stem}_preview.jpg"
        preview_path = f"{nextcloud_base}/_preview/{preview_name}"
        nc.files.upload(preview_path, preview_bytes)

        meta["thumbnail_path"] = thumb_path
        meta["preview_path"] = preview_path

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


def _preview_npy(nc, ref: dict, nextcloud_base: str, record_ref):
    """NumPy配列のプレビュー生成。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    with tempfile.NamedTemporaryFile(suffix=".npy") as tmp:
        nc.files.download(src_path, tmp.name)
        arr = np.load(tmp.name, allow_pickle=False)

        meta = {
            "filename": name,
            "type": "npy",
            "shape": list(arr.shape),
            "dtype": str(arr.dtype),
            "size_bytes": ref.get("size", 0),
            "nbytes": int(arr.nbytes),
            "stats": {},
        }
        if np.issubdtype(arr.dtype, np.number):
            meta["stats"] = {
                "min": float(np.nanmin(arr)),
                "max": float(np.nanmax(arr)),
                "mean": float(np.nanmean(arr)),
                "std": float(np.nanstd(arr)),
                "nan_count": int(np.count_nonzero(np.isnan(arr))) if np.issubdtype(arr.dtype, np.floating) else 0,
            }
        if arr.ndim > 1:
            meta["stats"]["shape_description"] = f"{arr.ndim}次元配列: " + " x ".join(map(str, arr.shape))

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


def _preview_csv(nc, ref: dict, nextcloud_base: str, record_ref, delimiter=","):
    """CSV/TSVファイルのプレビュー生成。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    with tempfile.NamedTemporaryFile(suffix=f".{name.rsplit('.', 1)[-1]}", mode="wb") as tmp:
        nc.files.download(src_path, tmp.name)

        try:
            df_head = pd.read_csv(tmp.name, delimiter=delimiter, nrows=1000)
        except Exception:
            _preview_text(nc, ref, nextcloud_base, record_ref)
            return

        total_rows = 0
        for chunk in pd.read_csv(tmp.name, delimiter=delimiter, chunksize=10000):
            total_rows += len(chunk)

        meta = {
            "filename": name,
            "type": "csv",
            "size_bytes": ref.get("size", 0),
            "columns": list(df_head.columns),
            "total_rows": total_rows,
            "total_columns": len(df_head.columns),
            "head_10": df_head.head(10).to_dict(orient="records"),
            "describe": df_head.describe(include="all").to_dict(),
            "dtypes": {col: str(dtype) for col, dtype in df_head.dtypes.items()},
        }

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


def _preview_text(nc, ref: dict, nextcloud_base: str, record_ref):
    """テキストファイルのプレビュー。"""
    name = ref["name"]
    src_path = f"{nextcloud_base}/_data/{name}"

    content = nc.files.download(src_path)
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("shift_jis", errors="replace")
    else:
        text = str(content)

    meta = {
        "filename": name,
        "type": "text",
        "size_bytes": ref.get("size", 0),
        "line_count": text.count("\n") + 1,
        "preview_text": text[:2000],
        "encoding_detected": "utf-8",
    }

    _save_preview_meta(nc, nextcloud_base, name, meta)
    _update_preview_refs(record_ref, name, meta)


@functions_framework.cloud_event
def on_file_refs_update(cloud_event):
    """file_refs 更新時にプレビューを自動生成する。"""
    doc_path = cloud_event["subject"]
    old_value = cloud_event.data.get("oldValue", {}).get("fields", {})
    new_value = cloud_event.data["value"]["fields"]

    old_refs = _extract_file_refs(old_value)
    new_refs = _extract_file_refs(new_value)
    added_refs = [r for r in new_refs if r["name"] not in {o["name"] for o in old_refs}]

    if not added_refs:
        return

    nc = _get_nextcloud_client()
    team_id, record_id = _parse_doc_path(doc_path)
    record_ref = db.document(doc_path)
    nextcloud_base = _get_nextcloud_base_path(record_ref)

    for ref in added_refs:
        try:
            name = ref["name"]
            size = ref.get("size", 0)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

            if size > 100 * 1024 * 1024:
                meta = {
                    "filename": name,
                    "size_bytes": size,
                    "type": _guess_type(ext),
                    "note": "ファイルが100MBを超えるためプレビュー生成をスキップ",
                }
                _save_preview_meta(nc, nextcloud_base, name, meta)
                _update_preview_refs(record_ref, name, meta)
                continue

            if ext in ("png", "jpg", "jpeg", "tif", "tiff", "bmp"):
                _preview_image(nc, ref, nextcloud_base, record_ref)
            elif ext == "npy":
                _preview_npy(nc, ref, nextcloud_base, record_ref)
            elif ext in ("csv", "tsv"):
                _preview_csv(nc, ref, nextcloud_base, record_ref, delimiter="," if ext == "csv" else "\t")
            elif ext in ("txt", "log", "dat", "ras"):
                _preview_text(nc, ref, nextcloud_base, record_ref)

        except Exception as e:
            print(f"Preview generation failed for {ref.get('name', '?')}: {e}")
```

**requirements.txt**:
```
functions-framework==3.*
google-cloud-firestore==2.*
google-cloud-secret-manager==2.*
nc-py-api==0.17.*
Pillow==11.*
numpy>=2.0.0
pandas==2.*
```

**デプロイコマンド**:
```bash
gcloud functions deploy preview-generator \
  --gen2 \
  --region=asia-northeast1 \
  --runtime=python312 \
  --source=functions/preview_generator/ \
  --entry-point=on_file_refs_update \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.updated" \
  --trigger-event-filters="database=labvault" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}" \
  --memory=1024Mi \
  --timeout=300s \
  --service-account=functions-sa@labvault-project.iam.gserviceaccount.com
```

---

### 2.4 notebook_summarizer

**トリガー**: Firestore `teams/{team_id}/records/{record_id}/cell_logs/{cell_log_id}` の `onCreate`（バッチ処理）

```python
# functions/notebook_summarizer/main.py
from datetime import datetime, timezone
import functions_framework
from google.cloud import firestore
import vertexai
from vertexai.generative_models import GenerativeModel

db = firestore.Client(project="labvault-project", database="labvault")
vertexai.init(project="labvault-project", location="asia-northeast1")
gemini = GenerativeModel("gemini-2.0-flash-001")


@functions_framework.cloud_event
def on_cell_log_create(cloud_event):
    """セルログ追加時にNotebookサマリーの再生成をスケジュールする。"""
    doc_path = cloud_event["subject"]
    parts = doc_path.split("/")
    team_id, record_id = parts[1], parts[3]

    record_ref = (
        db.collection("teams").document(team_id)
        .collection("records").document(record_id)
    )
    record_ref.update({
        "_summary_pending": True,
        "_summary_pending_at": firestore.SERVER_TIMESTAMP,
    })


@functions_framework.http
def generate_summaries(request):
    """_summary_pending=True のレコードのNotebookサマリーを生成する。
    Cloud Scheduler から1分間隔で呼び出される。
    """
    teams = db.collection("teams").stream()
    for team_doc in teams:
        records = (
            db.collection("teams").document(team_doc.id)
            .collection("records")
            .where("_summary_pending", "==", True)
            .stream()
        )
        for record_doc in records:
            record = record_doc.to_dict()
            pending_at = record.get("_summary_pending_at")
            if pending_at and (datetime.now(timezone.utc) - pending_at).total_seconds() > 30:
                _generate_summary_for_record(
                    team_doc.id, record_doc.id, record_doc.reference
                )
    return "OK", 200


def _generate_summary_for_record(team_id: str, record_id: str, record_ref):
    """特定レコードのNotebookサマリーを生成する。"""
    cell_logs = list(
        record_ref.collection("cell_logs")
        .order_by("cell_number")
        .stream()
    )
    if not cell_logs:
        return

    cells_text = "\n---\n".join([
        f"Cell {c.to_dict()['cell_number']}: "
        f"{c.to_dict().get('source', '')[:500]}\n"
        f"新規変数: {list(c.to_dict().get('new_vars', {}).keys())}\n"
        f"変更変数: {list(c.to_dict().get('changed_vars', {}).keys())}"
        for c in cell_logs
    ])

    prompt = f"""以下のJupyter Notebookのセル実行履歴から、
このNotebookで行われた処理を100文字以内で要約してください。
使用した手法名、主要パラメータ、最終結果を含めてください。
日本語で回答してください。

{cells_text}"""

    response = gemini.generate_content(prompt)
    summary = response.text.strip()

    record = record_ref.get().to_dict()
    embedding_text = _build_embedding_text(record, summary)

    record_ref.update({
        "notebook_summary": summary,
        "embedding_text": embedding_text,
        "_summary_pending": firestore.DELETE_FIELD,
        "_summary_pending_at": firestore.DELETE_FIELD,
    })


def _build_embedding_text(record: dict, notebook_summary: str | None) -> str:
    """embedding対象テキストを構築する。"""
    parts = []
    parts.append(record.get("title", ""))
    parts.append(record.get("title", ""))  # 2回繰り返し（重み付け）
    parts.append(" ".join(record.get("tags", [])))
    for k, v in record.get("results", {}).items():
        parts.append(f"{k}: {v}")
    for k, v in record.get("conditions", {}).items():
        parts.append(f"{k}={v}")
    for note in record.get("notes", [])[-3:]:
        parts.append(note.get("text", ""))
    if notebook_summary:
        parts.append(notebook_summary)
    return " ".join(filter(None, parts))
```

---

## 3. Firestoreスキーマ（最終版）

### 3.1 完全な構造

```
firestore/ (database: "labvault")
|
+-- _system/                               # システム管理用
|   +-- poller_state/
|       +-- last_check: timestamp          # Nextcloudポーラーの最終チェック時刻
|       +-- version: string                # スキーマバージョン
|
+-- teams/
    +-- {team_id}/                         # 例: "konishi-lab"
        +-- team_name: string              # "小西研究室"
        +-- members: map<uid, role>        # {"tanaka": "admin", "suzuki": "member"}
        +-- nextcloud_group_folder: string # "konishi-lab"
        +-- db_name: string                # "experiments"
        +-- db_version: number             # 1 (メジャーバージョン)
        +-- created_at: timestamp
        |
        +-- templates/ (サブコレクション)
        |   +-- {template_name}/           # "xrd", "sem", "thermal_treatment"
        |       +-- display_name: string   # "XRD測定"
        |       +-- type: string           # "experiment"
        |       +-- default_tags: array<string>   # ["XRD"]
        |       +-- condition_fields: array<map>  # [{name, type, unit, default}]
        |       +-- result_fields: array<map>     # [{name, type, unit}]
        |       +-- description: string
        |
        +-- records/ (サブコレクション)
            +-- {record_id}/               # "AB3F" (Crockford's Base32, 4文字)
                |
                | === 基本メタデータ ===
                +-- title: string
                +-- type: string           # "experiment" | "sample" | "process" | "computation"
                +-- status: string         # "success" | "failed" | "partial" | "in_progress"
                +-- tags: array<string>
                +-- conditions: map
                +-- results: map
                +-- result_keys: array<string>     # 検索用
                +-- notes: array<map>              # [{text, by, at}]
                +-- created_by: string
                +-- created_at: timestamp
                +-- updated_at: timestamp
                +-- parent_id: string | null
                +-- visibility: string             # "team" | "private"
                +-- template_used: string | null
                +-- deleted_at: timestamp | null
                |
                | === ファイル参照 ===
                +-- file_refs: array<map>
                +-- nextcloud_path: string         # "large/konishi-lab/labvault/v1/experiments/AB3F"
                |
                | === 外部参照 ===
                +-- external_refs: array<map>
                |
                | === プレビュー ===
                +-- preview_refs: map
                |
                | === Embedding ===
                +-- embedding: vector(768)
                +-- embedding_text: string
                +-- embedding_text_hash: string
                +-- embedding_updated_at: timestamp
                |
                | === 自動ログサマリー ===
                +-- notebook_summary: string | null
                +-- trace_summary: string | null
                |
                | === サブコレクション ===
                +-- cell_logs/
                +-- traces/
                +-- analyses/
```

### 3.2 インデックス定義

```bash
# 1. レコード検索（タグ + ステータス + 日時）
gcloud firestore indexes composite create \
  --database=labvault \
  --collection-group=records \
  --field-config field-path=tags,array-config=CONTAINS \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=DESCENDING

# 2. ベクトルインデックス
gcloud firestore indexes composite create \
  --database=labvault \
  --collection-group=records \
  --field-config=vector-config='{"dimension":"768","flat": {}}',field-path=embedding

# 3. 結果キー検索
gcloud firestore indexes composite create \
  --database=labvault \
  --collection-group=records \
  --field-config field-path=result_keys,array-config=CONTAINS \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=created_at,order=DESCENDING
```

### 3.3 セキュリティルール

```javascript
// infra/firestore.rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /_system/{document=**} {
      allow read, write: if false;
    }
    match /teams/{teamId} {
      allow read: if isTeamMember(teamId);
      allow write: if isTeamAdmin(teamId);

      match /records/{recordId} {
        allow read: if isTeamMember(teamId);
        allow create: if isTeamMember(teamId);
        allow update: if isTeamMember(teamId);
        allow delete: if isRecordOwner(teamId, recordId) || isTeamAdmin(teamId);
        match /cell_logs/{logId} {
          allow read: if isTeamMember(teamId);
          allow write: if isTeamMember(teamId);
        }
        match /traces/{traceId} {
          allow read: if isTeamMember(teamId);
          allow write: if isTeamMember(teamId);
        }
        match /analyses/{analysisId} {
          allow read: if isTeamMember(teamId);
          allow write: if isTeamMember(teamId);
        }
      }
      match /templates/{templateId} {
        allow read: if isTeamMember(teamId);
        allow write: if isTeamAdmin(teamId);
      }
    }

    function isTeamMember(teamId) {
      return request.auth != null &&
             request.auth.uid in get(/databases/$(database)/documents/teams/$(teamId)).data.members;
    }
    function isTeamAdmin(teamId) {
      return request.auth != null &&
             get(/databases/$(database)/documents/teams/$(teamId)).data.members[request.auth.uid] == "admin";
    }
    function isRecordOwner(teamId, recordId) {
      return request.auth != null &&
             get(/databases/$(database)/documents/teams/$(teamId)/records/$(recordId)).data.created_by == request.auth.uid;
    }
  }
}
```

---

## 4. Nextcloudディレクトリ構造（最終版）

```
large/{group_folder}/labvault/
+-- v{major}/
    +-- {db_name}/
        +-- _db_meta.json
        +-- schemas/
        |   +-- {schema_name}.json
        +-- {record_id}/
            +-- _record_meta.json
            +-- _data/
            |   +-- xrd_raw.ras
            |   +-- xrd_raw.csv
            |   +-- SEM_50000x.tif
            +-- _preview/
            |   +-- xrd_raw_meta.json
            |   +-- SEM_50000x_thumb.jpg
            |   +-- SEM_50000x_preview.jpg
            |   +-- SEM_50000x_meta.json
            +-- _analyses/
            |   +-- AN7K_fit_plot.png
            |   +-- BM2P_comparison.png
            +-- {sub_record_id}/     # 再帰的階層
                +-- _record_meta.json
                +-- _data/
                +-- ...
```

---

## 5. WebApp（Streamlit）実装仕様

WebAppの実装はv8と同一方針。Streamlit + Cloud Run で構成し、MCPサーバーへHTTP経由でリクエストを送信する。

---

## 6. GCPインフラ設定

### 6.1 プロジェクト構成

```
プロジェクト: labvault-project
リージョン: asia-northeast1 (東京)
```

### 6.2 サービスアカウント

| SA名 | 用途 | 権限 |
|-------|------|------|
| `mcp-server@labvault-project.iam` | MCPサーバー | Firestore User, Secret Manager Accessor |
| `functions-sa@labvault-project.iam` | Cloud Functions | Firestore User, Secret Manager Accessor, Vertex AI User |
| `code-executor@labvault-project.iam` | コード実行 | Firestore User, Secret Manager Accessor |
| `scheduler-sa@labvault-project.iam` | Cloud Scheduler | Cloud Run Invoker |

### 6.3 Secret Manager

```bash
gcloud secrets create nextcloud-url --replication-policy=automatic
gcloud secrets create nextcloud-user --replication-policy=automatic
gcloud secrets create nextcloud-password --replication-policy=automatic
gcloud secrets create api-key-hash --replication-policy=automatic
```

---

## 7. モノレポのディレクトリ構成と各ファイル

```
labvault-platform/
+-- mcp-server/
|   +-- Dockerfile
|   +-- pyproject.toml
|   +-- src/
|       +-- server.py
|       +-- tools/
|       |   +-- search.py
|       |   +-- get_detail.py
|       |   +-- compare.py
|       |   +-- data_preview.py
|       |   +-- get_results.py
|       |   +-- aggregate.py
|       |   +-- get_timeline.py
|       |   +-- get_trace.py
|       |   +-- explain_result.py
|       |   +-- compare_runs.py
|       |   +-- get_notebook_log.py
|       |   +-- execute_code.py
|       |   +-- batch_execute.py
|       |   +-- get_image.py
|       +-- auth/
|           +-- middleware.py
+-- functions/
|   +-- embedding_generator/
|   |   +-- main.py
|   |   +-- requirements.txt
|   +-- nextcloud_poller/
|   |   +-- main.py
|   |   +-- requirements.txt
|   +-- preview_generator/
|   |   +-- main.py
|   |   +-- requirements.txt
|   +-- notebook_summarizer/
|       +-- main.py
|       +-- requirements.txt
+-- shared/
|   +-- nextcloud.py
|   +-- models.py
|   +-- config.py
+-- code-executor/
|   +-- Dockerfile
|   +-- requirements.txt
+-- webapp/
|   +-- Dockerfile
|   +-- app.py
+-- infra/
|   +-- firestore.rules
|   +-- firestore.indexes.json
|   +-- cloudbuild.yaml
+-- tests/
+-- pyproject.toml
```

---

## 8. 実装ロードマップ（Issue粒度）

| Phase | Issue | 内容 |
|-------|-------|------|
| 1a | モノレポ初期化 | labvault-platform リポジトリ作成、CI/CD |
| 1b | MCPサーバー基盤 | FastMCP + Cloud Run デプロイ |
| 1c | Firestore設定 | スキーマ、インデックス、セキュリティルール |
| 2a | 検索ツール群 | search, get_detail, get_results, get_timeline |
| 2b | 分析ツール群 | compare, aggregate, compare_runs, explain_result |
| 2c | データ取得ツール群 | data_preview, get_trace, get_notebook_log, get_image |
| 2d | 実行ツール群 | execute_code, batch_execute |
| 3a | Cloud Functions | embedding_generator, nextcloud_poller, preview_generator |
| 3b | notebook_summarizer | Gemini連携サマリー生成 |
| 4 | WebApp | Streamlit ダッシュボード |
| 5 | 認証強化 | APIキー管理、チーム権限 |

---

## 9. 認証フローの詳細

### 9.1 アーキテクチャ概要

```
Claude Desktop / SDK
    |
    | (1) HTTPリクエスト + Authorization: Bearer <API_KEY>
    v
Cloud Run (MCPサーバー)
    |
    +-- (2) 認証ミドルウェア: APIキー検証
    |       +-- Secret Manager から api-key-hash を取得
    |       +-- SHA-256ハッシュ比較
    |       +-- team_id をリクエストコンテキストに注入
    |
    +-- (3) ツール実行
    |
    +-- (4) Firestoreアクセス (サービスアカウント認証)
    +-- (5) Nextcloudアクセス (Secret Manager経由)
```

### 9.2 APIキー認証ミドルウェア

```python
# mcp-server/src/auth/middleware.py
import hashlib
import hmac
from functools import lru_cache
from google.cloud import secretmanager, firestore

secret_client = secretmanager.SecretManagerServiceClient()
db = firestore.AsyncClient(project="labvault-project", database="labvault")

PROJECT_ID = "labvault-project"


@lru_cache(maxsize=1)
def _get_valid_api_keys() -> dict[str, dict]:
    """Secret Manager + Firestore からAPIキー情報を取得する。
    返り値: {key_hash: {team_id, user_id, scopes}}
    """
    # Firestoreの _system/api_keys から取得
    # 各ドキュメント: {key_hash, team_id, user_id, scopes, created_at, expires_at}
    keys = {}
    for doc in db.collection("_system").document("api_keys").collection("keys").stream():
        d = doc.to_dict()
        keys[d["key_hash"]] = {
            "team_id": d["team_id"],
            "user_id": d["user_id"],
            "scopes": d.get("scopes", ["*"]),
        }
    return keys


def verify_api_key(api_key: str) -> dict | None:
    """APIキーを検証し、メタデータを返す。無効な場合はNone。"""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    valid_keys = _get_valid_api_keys()
    return valid_keys.get(key_hash)


async def auth_middleware(request):
    """FastMCPリクエストの認証を行うミドルウェア。"""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"error": "Missing or invalid Authorization header"}, 401

    api_key = auth_header[7:]  # "Bearer " を除去
    key_info = verify_api_key(api_key)
    if key_info is None:
        return {"error": "Invalid API key"}, 403

    # リクエストコンテキストに認証情報を注入
    request.state.auth = key_info
    return None  # 認証成功
```

### 9.3 APIキーの発行フロー

```python
# 管理者用スクリプト: scripts/generate_api_key.py
import hashlib
import secrets
from google.cloud import firestore
from datetime import datetime, timezone, timedelta

db = firestore.Client(project="labvault-project", database="labvault")


def generate_api_key(team_id: str, user_id: str, expires_days: int = 365) -> str:
    """APIキーを生成してFirestoreに登録する。"""
    # 1. ランダムAPIキー生成（32バイト = 64文字hex）
    raw_key = secrets.token_hex(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    # 2. Firestoreに保存（ハッシュのみ保存、平文は保存しない）
    db.collection("_system").document("api_keys").collection("keys").document(key_hash[:12]).set({
        "key_hash": key_hash,
        "team_id": team_id,
        "user_id": user_id,
        "scopes": ["*"],
        "created_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=expires_days),
    })

    # 3. 平文キーを返す（この時のみ表示、以後復元不可）
    print(f"API Key (save this, it won't be shown again):")
    print(f"  {raw_key}")
    print(f"Team: {team_id}, User: {user_id}")
    return raw_key
```

### 9.4 Cloud Run IAM設定

```bash
# MCPサーバーは認証不要（APIキーで自前認証するため）
gcloud run services add-iam-policy-binding labvault-mcp-server \
  --region=asia-northeast1 \
  --member="allUsers" \
  --role="roles/run.invoker"

# ただし本番環境ではCloud ArmorやLoad Balancerで制限をかける
```

---

## 10. デプロイ手順

### 10.1 MCPサーバー（Cloud Run）

**Dockerfile**:
```dockerfile
# mcp-server/Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY mcp-server/pyproject.toml mcp-server/
COPY shared/ shared/
COPY mcp-server/src/ mcp-server/src/

RUN pip install --no-cache-dir -e ./mcp-server

EXPOSE 8080
CMD ["python", "-m", "mcp-server.src.server"]
```

**デプロイ**:
```bash
# コンテナイメージのビルドとプッシュ
gcloud builds submit \
  --tag gcr.io/labvault-project/mcp-server:latest \
  --project=labvault-project

# Cloud Run へデプロイ
gcloud run deploy labvault-mcp-server \
  --image=gcr.io/labvault-project/mcp-server:latest \
  --region=asia-northeast1 \
  --platform=managed \
  --memory=1Gi \
  --cpu=2 \
  --min-instances=0 \
  --max-instances=5 \
  --timeout=300 \
  --service-account=mcp-server@labvault-project.iam.gserviceaccount.com \
  --set-env-vars="GCP_PROJECT=labvault-project,FIRESTORE_DATABASE=labvault"
```

### 10.2 Cloud Functions 一括デプロイ

```bash
#!/bin/bash
# scripts/deploy_functions.sh

set -e
PROJECT="labvault-project"
REGION="asia-northeast1"
SA="functions-sa@${PROJECT}.iam.gserviceaccount.com"

echo "=== Deploying embedding-generator ==="
gcloud functions deploy embedding-generator \
  --gen2 --region=$REGION --runtime=python312 \
  --source=functions/embedding_generator/ \
  --entry-point=on_record_change \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.written" \
  --trigger-event-filters="database=labvault" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}" \
  --memory=256Mi --timeout=60s \
  --service-account=$SA

echo "=== Deploying preview-generator ==="
gcloud functions deploy preview-generator \
  --gen2 --region=$REGION --runtime=python312 \
  --source=functions/preview_generator/ \
  --entry-point=on_file_refs_update \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.updated" \
  --trigger-event-filters="database=labvault" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}" \
  --memory=1024Mi --timeout=300s \
  --service-account=$SA

echo "=== Deploying nextcloud-poller ==="
gcloud functions deploy nextcloud-poller \
  --gen2 --region=$REGION --runtime=python312 \
  --source=functions/nextcloud_poller/ \
  --entry-point=poll_nextcloud \
  --trigger-http \
  --memory=512Mi --timeout=120s \
  --service-account=$SA

echo "=== Deploying notebook-summarizer (trigger) ==="
gcloud functions deploy notebook-summarizer-trigger \
  --gen2 --region=$REGION --runtime=python312 \
  --source=functions/notebook_summarizer/ \
  --entry-point=on_cell_log_create \
  --trigger-event-filters="type=google.cloud.firestore.document.v1.created" \
  --trigger-event-filters="database=labvault" \
  --trigger-event-filters-path-pattern="document=teams/{team_id}/records/{record_id}/cell_logs/{cell_log_id}" \
  --memory=256Mi --timeout=30s \
  --service-account=$SA

echo "=== Deploying notebook-summarizer (scheduler) ==="
gcloud functions deploy notebook-summarizer-scheduler \
  --gen2 --region=$REGION --runtime=python312 \
  --source=functions/notebook_summarizer/ \
  --entry-point=generate_summaries \
  --trigger-http \
  --memory=512Mi --timeout=120s \
  --service-account=$SA

echo "=== Done ==="
```

### 10.3 コード実行環境（Cloud Run Jobs）

```bash
# コンテナイメージのビルド
gcloud builds submit \
  --tag gcr.io/labvault-project/code-executor:latest \
  code-executor/

# Cloud Run Job の作成
gcloud run jobs create code-executor \
  --image=gcr.io/labvault-project/code-executor:latest \
  --region=asia-northeast1 \
  --cpu=2 \
  --memory=2Gi \
  --task-timeout=120s \
  --max-retries=0 \
  --service-account=code-executor@labvault-project.iam.gserviceaccount.com \
  --vpc-connector=labvault-vpc-connector \
  --vpc-egress=all-traffic
```
