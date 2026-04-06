"""labvault MCP サーバー -- 実験データの検索・閲覧ツール。"""

from __future__ import annotations

import json
import statistics
from typing import Any

from mcp.server.fastmcp import FastMCP

from labvault import Lab

_INSTRUCTIONS = """\
labvault MCP サーバー: 実験データの検索・閲覧・比較ツール。

## ツール連鎖パターン

### 探索型 (「○○の実験を探して」)
1. search(query="○○") → 候補一覧
2. get_detail(record_id=候補ID) → 詳細

### 比較型 (「条件の違いを比べて」)
1. search → 候補取得
2. compare(record_ids=[ID群]) → 横断比較

### 統計型 (「○○の傾向を見せて」)
1. aggregate(result_key=キー名) → 統計

### データ確認型 (「ファイルの中身を見せて」)
1. get_detail(record_id=ID) → ファイル一覧
2. data_preview(record_id=ID, filename=名前) → プレビュー
"""


def create_server(lab: Lab | None = None) -> FastMCP:
    """MCP サーバーを作成する。"""
    mcp = FastMCP("labvault", instructions=_INSTRUCTIONS)
    _lab = lab

    def _get_lab() -> Lab:
        nonlocal _lab
        if _lab is None:
            _lab = Lab()
        return _lab

    @mcp.tool(
        description="実験レコードを検索する。自然言語クエリまたはタグ・ステータスでフィルタリング。"
    )
    def search(
        query: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        record_type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        lab = _get_lab()
        if query:
            records = lab.search(
                query,
                tags=tags,
                status=status,
                type=record_type,
                limit=limit,
            )
        else:
            records = lab.list(
                tags=tags,
                status=status,
                type=record_type,
                limit=limit,
            )
        return [
            {
                "id": r.id,
                "title": r.title,
                "type": r.type,
                "status": str(r.status),
                "tags": r.tags,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]

    @mcp.tool(
        description="レコードの詳細を表示する。条件、結果、メモ、ファイル一覧を含む。"
    )
    def get_detail(record_id: str) -> dict[str, Any]:
        lab = _get_lab()
        rec = lab.get(record_id)
        return {
            "id": rec.id,
            "title": rec.title,
            "type": rec.type,
            "status": str(rec.status),
            "created_by": rec.created_by,
            "created_at": rec.created_at.isoformat(),
            "updated_at": rec.updated_at.isoformat(),
            "tags": rec.tags,
            "conditions": rec.get_conditions(),
            "results": rec.results.to_dict(),
            "notes": [
                {"text": n.text, "created_at": n.created_at.isoformat()}
                for n in rec.notes
            ],
            "files": [
                {
                    "name": ref.name,
                    "content_type": ref.content_type,
                    "size_bytes": ref.size_bytes,
                }
                for ref in rec.list_data()
            ],
            "links": [
                {
                    "target_id": lk.target_id,
                    "relation": lk.relation,
                    "description": lk.description,
                }
                for lk in rec.links
            ],
            "parent_id": rec.parent_id,
        }

    @mcp.tool(description="複数レコードを横断比較する。条件・結果の差異を検出。")
    def compare(
        record_ids: list[str],
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        lab = _get_lab()
        records_data: list[dict[str, Any]] = []
        all_fields: set[str] = set()

        for rid in record_ids[:10]:
            rec = lab.get(rid)
            cond = rec.get_conditions()
            res = rec.results.to_dict()
            merged = {**cond, **res}
            all_fields.update(merged.keys())
            records_data.append(
                {"record_id": rid, "title": rec.title, "values": merged}
            )

        target_fields = fields or sorted(all_fields)

        differences = []
        common: dict[str, Any] = {}
        for f in target_fields:
            vals = [r["values"].get(f) for r in records_data]
            unique = set(json.dumps(v, default=str) for v in vals)
            if len(unique) == 1:
                common[f] = vals[0]
            else:
                differences.append(f)

        return {
            "fields": target_fields,
            "records": [
                {
                    "record_id": r["record_id"],
                    "title": r["title"],
                    "values": {f: r["values"].get(f) for f in target_fields},
                }
                for r in records_data
            ],
            "differences": differences,
            "common": common,
        }

    @mcp.tool(
        description="レコードに添付されたファイルのプレビュー。"
        "CSV は先頭行、テキストは先頭文字を返す。",
    )
    def data_preview(
        record_id: str,
        filename: str,
    ) -> dict[str, Any]:
        lab = _get_lab()
        rec = lab.get(record_id)
        data = rec.get_data(filename)

        ref = next((r for r in rec.list_data() if r.name == filename), None)
        result: dict[str, Any] = {
            "name": filename,
            "content_type": ref.content_type if ref else "",
            "size_bytes": len(data),
        }

        ct = (ref.content_type if ref else "").lower()
        if "csv" in ct or filename.endswith((".csv", ".tsv")):
            text = data.decode("utf-8", errors="replace")
            lines = text.strip().split("\n")
            result["preview_type"] = "csv"
            result["header"] = lines[0] if lines else ""
            result["rows"] = lines[1:11]  # 先頭10行
            result["total_lines"] = len(lines)
        elif "json" in ct or filename.endswith(".json"):
            result["preview_type"] = "json"
            result["content"] = json.loads(data)
        elif "text" in ct or filename.endswith((".txt", ".log")):
            text = data.decode("utf-8", errors="replace")
            result["preview_type"] = "text"
            result["content"] = text[:2000]
            result["total_chars"] = len(text)
        else:
            result["preview_type"] = "binary"
            result["hex_preview"] = data[:64].hex()

        return result

    @mcp.tool(
        description="数値結果の統計集計。"
        "平均、標準偏差、最小、最大を計算。group_by で条件別集計。",
    )
    def aggregate(
        result_key: str,
        group_by: str | None = None,
        tags: list[str] | None = None,
        status: str = "success",
    ) -> dict[str, Any]:
        lab = _get_lab()
        records = lab.list(tags=tags, status=status, limit=1000)

        values: list[float] = []
        groups: dict[str, list[float]] = {}

        for rec in records:
            res = rec.results.to_dict()
            if result_key not in res:
                continue
            val = res[result_key]
            if not isinstance(val, (int, float)):
                continue
            values.append(float(val))

            if group_by:
                cond = rec.get_conditions()
                group_val = str(cond.get(group_by, "unknown"))
                groups.setdefault(group_val, []).append(float(val))

        def _stats(vals: list[float]) -> dict[str, Any]:
            if not vals:
                return {}
            return {
                "count": len(vals),
                "mean": round(statistics.mean(vals), 4),
                "std": (round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0),
                "min": min(vals),
                "max": max(vals),
                "median": round(statistics.median(vals), 4),
            }

        result: dict[str, Any] = {
            "result_key": result_key,
            "overall": _stats(values),
        }
        if group_by and groups:
            result["group_by"] = group_by
            result["groups"] = {k: _stats(v) for k, v in sorted(groups.items())}
        return result

    @mcp.tool(description="レコードの時系列履歴。作成順にイベントを一覧表示。")
    def get_timeline(
        record_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        lab = _get_lab()

        if record_id:
            rec = lab.get(record_id)
            children = rec.children()
            records = [rec, *children]
        elif tags:
            records = lab.list(tags=tags, limit=limit)
        else:
            records = lab.list(limit=limit)

        timeline = sorted(records, key=lambda r: r.created_at)
        return [
            {
                "id": r.id,
                "title": r.title,
                "type": r.type,
                "status": str(r.status),
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat(),
            }
            for r in timeline[:limit]
        ]

    return mcp
