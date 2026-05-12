"""labvault MCP サーバー -- 実験データの検索・閲覧ツール。"""

from __future__ import annotations

import json
import statistics
from typing import Any

from labvault import Lab

_INSTRUCTIONS = """\
labvault MCP サーバー: 実験データの検索・閲覧・比較ツール。

## team の扱い

全ツールに `team: str` (optional) — 複数 team 所属ユーザーが切り替えるための引数。
省略時は LABVAULT_TEAM 環境変数。同一 team の Lab はキャッシュされる。

## ツール連鎖パターン

### 探索型 (「○○の実験を探して」)
1. search(query="○○") → 候補一覧
2. get_detail(record_id=候補ID) → 詳細

### 比較型 (「条件の違いを比べて」)
1. search → 候補取得
2. compare(record_ids=[ID群]) → 横断比較

### 統計型 (「○○の傾向を見せて」)
1. aggregate(key=キー名) → 統計 (conditions/results 両対応)

### 概要型 (「この実験シリーズは何を調べた?」)
1. get_overview(parent_id=ID) → 条件・結果のサマリ

### データ確認型 (「ファイルの中身を見せて」)
1. get_detail(record_id=ID) → ファイル一覧
2. data_preview(record_id=ID, filename=名前) → プレビュー

### 範囲検索 (「power が 50W 以上の実験は?」)
1. search(conditions={"power": {"gte": 50}}) → 該当レコード
"""


def create_server(lab: Lab | None = None) -> Any:
    """MCP サーバーを作成する。

    lab: 事前構築の Lab (主にテスト用)。渡された場合は lab.team の team として
    キャッシュに登録される。本番では None で OK (各ツールの team 引数 or
    LABVAULT_TEAM env から resolve した team で Lab を遅延構築する)。
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("labvault", instructions=_INSTRUCTIONS)

    _labs: dict[str, Lab] = {}
    _default_lab = lab  # team 未指定時のフォールバック (主にテスト用)
    if lab is not None:
        _labs[lab.team] = lab

    def _resolve_team(team: str | None) -> str:
        if team and team.strip():
            return team.strip()
        # 事前構築 lab があればその team を使う (テスト時に env と独立に動作させる)
        if _default_lab is not None:
            return _default_lab.team
        # 本番: settings.team or "default" (Lab.__init__ と同じ規約)
        from labvault.core.config import Settings

        return Settings().team or "default"

    def _get_lab(team: str | None = None) -> Lab:
        team_id = _resolve_team(team)
        if team_id not in _labs:
            _labs[team_id] = Lab(team=team_id)
        return _labs[team_id]

    @mcp.tool(
        description="実験レコードを検索する。自然言語クエリ、タグ、ステータス、"
        "親レコードID、条件でフィルタリング。"
        'conditions は完全一致 ({"power": 20}) または範囲指定 '
        '({"power": {"gte": 10, "lte": 30}}) が可能。'
        "演算子: gt, gte, lt, lte, eq, ne。"
        "include_conditions=True で各レコードの条件も返す。",
    )
    def search(
        query: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        record_type: str | None = None,
        parent_id: str | None = None,
        conditions: dict[str, Any] | None = None,
        include_conditions: bool = False,
        limit: int = 20,
        team: str | None = None,
    ) -> list[dict[str, Any]]:
        from labvault.core.lab import _match_condition

        lab = _get_lab(team)
        if query:
            records = lab.search(
                query,
                tags=tags,
                status=status,
                type=record_type,
                parent_id=parent_id,
                conditions=conditions,
                limit=limit,
            )
        else:
            records = lab.list(
                tags=tags,
                status=status,
                type=record_type,
                limit=limit * 5 if conditions or parent_id else limit,
            )
            if parent_id is not None:
                records = [r for r in records if r.parent_id == parent_id]
            if conditions:
                records = [
                    r
                    for r in records
                    if all(
                        _match_condition(r.get_conditions().get(k), v)
                        for k, v in conditions.items()
                    )
                ]
            records = records[:limit]
        result = []
        for r in records:
            item: dict[str, Any] = {
                "id": r.id,
                "title": r.title,
                "type": r.type,
                "status": str(r.status),
                "tags": r.tags,
                "created_at": r.created_at.isoformat(),
            }
            if include_conditions:
                item["conditions"] = r.get_conditions()
            result.append(item)
        return result

    @mcp.tool(
        description="レコードの詳細を表示する。条件、結果、メモ、ファイル一覧を含む。"
    )
    def get_detail(record_id: str, team: str | None = None) -> dict[str, Any]:
        lab = _get_lab(team)
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
            "condition_units": rec.get_condition_units(),
            "results": rec.results.to_dict(),
            "result_units": rec.get_result_units(),
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
        team: str | None = None,
    ) -> dict[str, Any]:
        lab = _get_lab(team)
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
        team: str | None = None,
    ) -> dict[str, Any]:
        lab = _get_lab(team)
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

    @mcp.tool(
        description="数値キーの統計集計。"
        "results/conditions 両対応。group_by でグループ化。"
        "parent_id で親レコード配下に限定可能。"
        "record_type でレコードタイプを絞り込み "
        "(例: 'measurement' で解析 Record を除外)。",
    )
    def aggregate(
        key: str,
        group_by: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        parent_id: str | None = None,
        record_type: str | None = None,
        team: str | None = None,
    ) -> dict[str, Any]:
        lab = _get_lab(team)
        records = lab.list(
            tags=tags,
            status=status if status else None,
            type=record_type,
            limit=5000,
        )

        if parent_id is not None:
            records = [r for r in records if r.parent_id == parent_id]

        values: list[float] = []
        groups: dict[str, list[float]] = {}

        for rec in records:
            cond = rec.get_conditions()
            res = rec.results.to_dict()
            merged = {**cond, **res}

            if key not in merged:
                continue
            val = merged[key]
            if not isinstance(val, (int, float)):
                continue
            values.append(float(val))

            if group_by:
                group_val = str(merged.get(group_by, "unknown"))
                groups.setdefault(group_val, []).append(float(val))

        result: dict[str, Any] = {
            "key": key,
            "record_count": len(records),
            "overall": _stats(values),
        }
        if group_by and groups:
            result["group_by"] = group_by
            result["groups"] = {k: _stats(v) for k, v in sorted(groups.items())}
        return result

    @mcp.tool(
        description="実験シリーズの概要を1回で取得する。"
        "子レコード数、条件のユニーク値/統計、結果の統計を返す。"
        "「この実験は何を調べたか」をワンショットで把握できる。",
    )
    def get_overview(
        parent_id: str,
        record_type: str | None = None,
        team: str | None = None,
    ) -> dict[str, Any]:
        lab = _get_lab(team)
        all_records = lab.list(type=record_type, limit=5000)
        children = [r for r in all_records if r.parent_id == parent_id]

        condition_keys: dict[str, list[Any]] = {}
        result_keys: dict[str, list[float]] = {}
        status_counts: dict[str, int] = {}

        for rec in children:
            st = str(rec.status)
            status_counts[st] = status_counts.get(st, 0) + 1

            cond = rec.get_conditions()
            for k, v in cond.items():
                condition_keys.setdefault(k, []).append(v)

            res = rec.results.to_dict()
            for k, v in res.items():
                if isinstance(v, (int, float)):
                    result_keys.setdefault(k, []).append(float(v))

        conditions_summary: dict[str, Any] = {}
        for k, vals in condition_keys.items():
            numeric_vals = [v for v in vals if isinstance(v, (int, float))]
            if numeric_vals and len(numeric_vals) == len(vals):
                conditions_summary[k] = {
                    "type": "numeric",
                    "unique_count": len(set(numeric_vals)),
                    "min": min(numeric_vals),
                    "max": max(numeric_vals),
                    "mean": round(statistics.mean(numeric_vals), 4),
                }
            else:
                unique = sorted(set(str(v) for v in vals))
                conditions_summary[k] = {
                    "type": "categorical",
                    "unique_values": unique[:50],
                    "unique_count": len(unique),
                }

        results_summary = {k: _stats(v) for k, v in result_keys.items()}

        return {
            "parent_id": parent_id,
            "child_count": len(children),
            "status_counts": status_counts,
            "conditions": conditions_summary,
            "results": results_summary,
        }

    @mcp.tool(description="レコードの時系列履歴。作成順にイベントを一覧表示。")
    def get_timeline(
        record_id: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        team: str | None = None,
    ) -> list[dict[str, Any]]:
        lab = _get_lab(team)

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
