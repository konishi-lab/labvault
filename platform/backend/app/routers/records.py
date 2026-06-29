"""レコード CRUD + 操作エンドポイント。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from labvault import Lab
from labvault.core.exceptions import RecordNotFoundError

from ..auth import User, current_user, get_lab, get_lab_relaxed
from ..observability import EventTimer, log_event, safe_keys
from ..permissions import (
    VALID_SHARE_ROLES,
    require_analyze,
    require_grant,
    require_read,
)
from ..schemas import (
    AggregateResponse,
    CellLogEntry,
    CellLogListResponse,
    ConditionsUpdate,
    ConditionUnitsUpdate,
    NoteCreate,
    RecordCreate,
    RecordDetail,
    RecordListResponse,
    RecordSummary,
    ResultUnitsUpdate,
    ResultUpdate,
    ShareEntry,
    ShareGrantRequest,
    ShareListResponse,
    SharedRecordListResponse,
    SharedRecordSummary,
    StatsBlock,
    StatusUpdate,
    TagsUpdate,
)

router = APIRouter(prefix="/api/records", tags=["records"])
logger = logging.getLogger(__name__)


def _to_summary(rec: Any) -> RecordSummary:
    return RecordSummary(
        id=rec.id,
        title=rec.title,
        type=rec.type,
        status=str(rec.status),
        tags=rec.tags,
        created_by=rec.created_by,
        created_at=rec.created_at,
        updated_by=rec.updated_by,
        updated_at=rec.updated_at,
        parent_id=rec.parent_id,
        template_name=getattr(rec, "template_name", None),
    )


def _to_detail(rec: Any) -> RecordDetail:
    # template の result_fields から unit / description の auto-fill 元を抽出。
    # Web UI が「これは template 由来」「これは手動入力」を視覚的に区別するのに使う。
    template_result_units: dict[str, str] = {}
    template_result_descriptions: dict[str, str] = {}
    template_required_conditions: list[str] = []
    template_required_results: list[str] = []
    tpl = rec._resolve_template() if hasattr(rec, "_resolve_template") else None
    if tpl is not None:
        for rf in getattr(tpl, "result_fields", []) or []:
            if rf.unit:
                template_result_units[rf.name] = rf.unit
            if rf.description:
                template_result_descriptions[rf.name] = rf.description
            if rf.required:
                template_required_results.append(rf.name)
        # required_conditions は TemplateV10 直下の list[str] (v10 で確立済)
        template_required_conditions = list(
            getattr(tpl, "required_conditions", []) or []
        )

    return RecordDetail(
        id=rec.id,
        title=rec.title,
        type=rec.type,
        status=str(rec.status),
        tags=rec.tags,
        created_by=rec.created_by,
        created_at=rec.created_at,
        updated_by=rec.updated_by,
        updated_at=rec.updated_at,
        parent_id=rec.parent_id,
        template_name=getattr(rec, "template_name", None),
        conditions=rec.get_conditions(),
        condition_units=rec.get_condition_units(),
        condition_descriptions=rec.get_condition_descriptions(),
        results=rec.results.to_dict(),
        result_units=rec.get_result_units(),
        result_descriptions=rec.get_result_descriptions(),
        template_result_units=template_result_units,
        template_result_descriptions=template_result_descriptions,
        template_required_conditions=template_required_conditions,
        template_required_results=template_required_results,
        # S1: 共有設定 (email → role)。Web UI の record 詳細「共有」モーダル
        # が現状を表示するのに使う。閲覧者が grant 主体でない場合でも、
        # 自分が share されている事実を確認するため返す (UI 側でフィルタ)。
        shares=getattr(rec, "shares", None) or {},
        notes=[
            {"text": n.text, "created_at": n.created_at, "author": n.author}
            for n in rec.notes
        ],
        files=[
            {
                "name": ref.name,
                "content_type": ref.content_type,
                "size_bytes": ref.size_bytes,
                "original_type": ref.original_type,
            }
            for ref in rec.list_data()
        ],
        links=[
            {
                "target_id": lk.target_id,
                "relation": lk.relation,
                "description": lk.description,
            }
            for lk in rec.links
        ],
        events=rec.events,
    )


@router.get("", response_model=RecordListResponse)
def list_records(
    tags: str | None = None,
    status: str | None = None,
    type: str | None = None,
    conditions: str | None = None,
    created_by: str | None = None,
    template: str | None = None,
    limit: int = 20,
    offset: int = 0,
    lab: Lab = Depends(get_lab),
) -> RecordListResponse:
    """レコード一覧を取得する。

    conditions は JSON 文字列で渡す (例: `{"target": "Cu"}` を URL encode)。
    template の indexed_fields に挙がっている key は `idx_<key>` として
    Firestore に push down され、それ以外は post-filter される (PR #14)。

    created_by は record の created_by フィールドと完全一致でフィルタする
    (典型的には自分が作った record だけ見たい時に email を渡す)。
    """
    import json

    tag_list = tags.split(",") if tags else None

    parsed_conditions: dict[str, Any] = {}
    if conditions:
        try:
            loaded = json.loads(conditions)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"conditions must be valid JSON: {e}",
            ) from e
        if not isinstance(loaded, dict):
            raise HTTPException(
                status_code=400, detail="conditions must be a JSON object"
            )
        parsed_conditions = loaded

    # push down 対象 (idx_<key>) の振り分け。Lab._get_indexed_keys() は
    # template cache + backend templates の union。scalar 等値だけが対象。
    push_down: dict[str, Any] = {}
    if parsed_conditions:
        indexed_keys = lab._get_indexed_keys()
        for key, value in parsed_conditions.items():
            if (
                key in indexed_keys
                and not isinstance(value, dict)
                and isinstance(value, (str, int, float, bool))
            ):
                push_down[f"idx_{key}"] = value

    fetch_limit = limit * 5 if parsed_conditions else limit
    # 走査全体を計測 + 構造化ログ。push-down に乗らなかった条件
    # (= post-filter で潰す条件) が多いほど遅くなるので可視化が要。
    with EventTimer(
        logger,
        "records.list",
        limit=limit,
        offset=offset,
        # N6 (PR #83): ユーザー入力由来の condition key を生で log に乗せると
        # フリーフォーム key (`patient_name` 等) が漏洩する。`safe_keys` で
        # identifier 形式 + 短い key のみ pass、他は `<redacted>` に置換。
        condition_keys=safe_keys(sorted(parsed_conditions.keys())),
        push_down_keys=safe_keys(sorted(push_down.keys())),
        post_filter_keys=safe_keys(
            sorted(k for k in parsed_conditions if f"idx_{k}" not in push_down)
        ),
        template=template,
        mine_only=bool(created_by),
    ) as timer:
        # Firestore に parent_id==None フィルタを直接渡す
        if hasattr(lab._metadata, "list_records"):
            records = lab._metadata.list_records(
                lab._team,
                tags=tag_list,
                status=status,
                record_type=type,
                created_by=created_by,
                parent_id=None,  # ルートレコードのみ
                conditions=push_down or None,
                limit=fetch_limit,
                offset=offset,
            )
            from labvault.core.record import Record as _Record

            items = [_Record._from_dict(r, lab=lab) for r in records]
        else:
            items = lab.list(
                tags=tag_list,
                status=status,
                type=type,
                created_by=created_by,
                limit=fetch_limit,
                offset=offset,
            )
            items = [r for r in items if r.parent_id is None]

        fetched_count = len(items)

        # post-filter: push down に乗らない条件 + Platform backend がサーバー未
        # 対応の場合の正確性保証。Lab.search と同じ _match_condition を使う。
        if parsed_conditions:
            from labvault.core.lab import _match_condition

            filtered: list[Any] = []
            for rec in items:
                cond = rec.get_conditions()
                if all(
                    _match_condition(cond.get(k), v)
                    for k, v in parsed_conditions.items()
                ):
                    filtered.append(rec)
                    if len(filtered) >= limit:
                        break
            items = filtered
        elif len(items) > limit:
            items = items[:limit]

        # template フィルタ (post-filter)。indexed_fields にしないので
        # 数の多い team では遅くなる可能性があるが、template 名でのドリル
        # ダウンは UI のショートカット用途で、頻度は低い前提。
        if template:
            items = [
                r for r in items if getattr(r, "template_name", None) == template
            ]

        # 内部 fetch_limit に達した = サーバー側で more がある可能性
        has_more = len(items) >= limit and len(items) > 0
        timer.add(
            fetched=fetched_count,
            returned=len(items),
            post_filter_dropped=fetched_count - len(items),
            has_more=has_more,
        )

    return RecordListResponse(
        items=[_to_summary(r) for r in items],
        total=len(items),
        has_more=has_more,
    )


@router.post("", response_model=RecordDetail, status_code=201)
def create_record(
    body: RecordCreate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """レコードを作成する。created_by は認証済 email を刻印。"""
    rec = lab.new(
        body.title,
        type=body.type,
        tags=body.tags if body.tags else None,
        auto_log=False,
        created_by=user.email,
        **body.conditions,
    )
    return _to_detail(rec)


def _compute_stats(vals: list[float]) -> StatsBlock:
    """数値リスト → StatsBlock。空集合は count=0 で返す (他フィールドは 0.0)。

    `labvault.core.aggregate.compute_stats` を Pydantic schema に詰め
    替える薄いアダプタ。3 経路 (backend / MCP / CLI) で同じ計算式を使う
    ようにするための delegate (PR #78 で core 抽出)。
    """
    from labvault.core.aggregate import compute_stats

    s = compute_stats(vals)
    return StatsBlock(
        count=s.count, mean=s.mean, std=s.std, min=s.min, max=s.max, median=s.median
    )


# `/{record_id}` より前に declare すること (FastAPI ルーティング順)。
@router.get("/aggregate", response_model=AggregateResponse)
def aggregate_records(
    key: str,
    tags: str | None = None,
    status: str | None = None,
    type: str | None = None,
    conditions: str | None = None,
    created_by: str | None = None,
    template: str | None = None,
    parent_id: str | None = None,
    group_by: str | None = None,
    limit: int = 500,
    lab: Lab = Depends(get_lab),
) -> AggregateResponse:
    """現フィルタ集合に対する数値キーの統計集計。

    `/api/records` と同じフィルタ ( tags / status / type / conditions /
    created_by / template / parent_id) を受け、`key` (conditions または
    results のどちらに入っていても可) を numeric として取り出して n /
    min / max / mean / median / std を返す。

    Web UI の `/records` StatsPanel から呼ばれて「現在表示中の N 件で
    なく、フィルタにマッチする全集合の統計」を出すのに使う。limit を
    超えた場合 truncated=True (default 500 = scatter 用の安全上限)。

    aggregate は post-filter で必ず numeric チェックする (`isinstance`)
    ので、 conditions に「power に "20W" を文字列で入れた record」が
    混ざっていても value_count から除外される。
    """
    import json

    tag_list = tags.split(",") if tags else None

    parsed_conditions: dict[str, Any] = {}
    if conditions:
        try:
            loaded = json.loads(conditions)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"conditions must be valid JSON: {e}",
            ) from e
        if not isinstance(loaded, dict):
            raise HTTPException(
                status_code=400, detail="conditions must be a JSON object"
            )
        parsed_conditions = loaded

    if limit < 1 or limit > 5000:
        raise HTTPException(
            status_code=400, detail="limit must be between 1 and 5000"
        )

    # push-down 対象 (idx_<key>) の振り分け。list_records と同じ流儀。
    push_down: dict[str, Any] = {}
    if parsed_conditions:
        indexed_keys = lab._get_indexed_keys()
        for k, value in parsed_conditions.items():
            if (
                k in indexed_keys
                and not isinstance(value, dict)
                and isinstance(value, (str, int, float, bool))
            ):
                push_down[f"idx_{k}"] = value

    # parent_id が指定された場合はそれを使う。さもなくば parent_id=None
    # (ルートレコード集合) を default — `/records` の挙動と揃える。
    effective_parent = parent_id if parent_id is not None else None
    fetch_limit = min(limit + 1, 5001)  # +1 で truncated 判定

    with EventTimer(
        logger,
        "records.aggregate",
        # `key` / `group_by` はユーザー入力なので同様に safe_keys でガード。
        # 単一値だが list 化して通す ([0] で 1 要素を取り出す)。
        key=safe_keys([key])[0] if key else key,
        group_by=safe_keys([group_by])[0] if group_by else None,
        limit=limit,
        parent_id=parent_id,
        push_down_keys=safe_keys(sorted(push_down.keys())),
        post_filter_keys=safe_keys(
            sorted(k for k in parsed_conditions if f"idx_{k}" not in push_down)
        ),
    ) as timer:
        if hasattr(lab._metadata, "list_records"):
            records = lab._metadata.list_records(
                lab._team,
                tags=tag_list,
                status=status,
                record_type=type,
                created_by=created_by,
                parent_id=effective_parent,
                conditions=push_down or None,
                limit=fetch_limit,
            )
            from labvault.core.record import Record as _Record

            items = [_Record._from_dict(r, lab=lab) for r in records]
        else:
            items = lab.list(
                tags=tag_list,
                status=status,
                type=type,
                created_by=created_by,
                limit=fetch_limit,
            )
            if parent_id is None:
                items = [r for r in items if r.parent_id is None]
            else:
                items = [r for r in items if r.parent_id == parent_id]

        # post-filter で push-down に乗らない条件 + template フィルタを適用。
        if parsed_conditions:
            from labvault.core.lab import _match_condition

            items = [
                r
                for r in items
                if all(
                    _match_condition(r.get_conditions().get(k), v)
                    for k, v in parsed_conditions.items()
                )
            ]
        if template:
            items = [
                r for r in items if getattr(r, "template_name", None) == template
            ]

        truncated = len(items) > limit
        if truncated:
            items = items[:limit]

        from labvault.core.aggregate import compute_aggregate

        result = compute_aggregate(items, key, group_by=group_by)
        timer.add(
            record_count=result.record_count,
            value_count=result.value_count,
            truncated=truncated,
            groups=len(result.groups),
        )

    def _to_block(s: Any) -> StatsBlock:
        return StatsBlock(
            count=s.count, mean=s.mean, std=s.std, min=s.min, max=s.max, median=s.median
        )

    return AggregateResponse(
        key=result.key,
        record_count=result.record_count,
        value_count=result.value_count,
        stats=_to_block(result.overall),
        group_by=group_by,
        groups={k: _to_block(v) for k, v in result.groups.items()},
        truncated=truncated,
    )


# `/{record_id}` より前に declare する (FastAPI ルーティング順)。
@router.get("/shared-with-me", response_model=SharedRecordListResponse)
def list_shared_with_me(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(current_user),
) -> SharedRecordListResponse:
    """自分宛てに `shares` 経由で共有された record を **全 team 横断** で返す。

    S1 Phase 1B (PR for 2026-06-29): cross-team query。`X-Labvault-Team`
    header は受けず (自分が属さない team の record も返るため)、
    Firestore 側で `collection_group('records')` を `shared_with_emails
    array_contains user.email` で絞り込んで `updated_at` 降順に返す。

    Frontend は items 各要素の `team` を使って `X-Labvault-Team` を組み
    立て、record 詳細 endpoint を叩く流れ。`role` は viewer / analyst の
    どちらが付与されているか (UI が「解析」アクションを出すか判定)。
    """
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    from ..dependencies import get_shared_metadata_backend

    backend = get_shared_metadata_backend()
    email = (user.email or "").strip().lower()

    with EventTimer(
        logger,
        "records.shared_with_me",
        limit=limit,
        offset=offset,
    ) as timer:
        # +1 件取って has_more を判定する。
        raw = backend.list_records_shared_with(email, limit=limit + 1, offset=offset)
        truncated = len(raw) > limit
        if truncated:
            raw = raw[:limit]

        items: list[SharedRecordSummary] = []
        for d in raw:
            shares = d.get("shares") or {}
            role = shares.get(email, "viewer") if isinstance(shares, dict) else "viewer"
            if role not in VALID_SHARE_ROLES:
                # 旧 / 想定外の role が保存されていても無視せず viewer 扱いで
                # 表示する (UI 側で「未知の role」を出すより安全側)。
                role = "viewer"
            items.append(
                SharedRecordSummary(
                    id=d.get("id", ""),
                    title=d.get("title", ""),
                    type=d.get("type", "experiment"),
                    status=str(d.get("status", "")),
                    tags=list(d.get("tags") or []),
                    created_by=d.get("created_by", "") or "",
                    created_at=d["created_at"],
                    updated_by=d.get("updated_by", "") or "",
                    updated_at=d["updated_at"],
                    parent_id=d.get("parent_id"),
                    template_name=d.get("template"),
                    team=d.get("team", "") or "",
                    role=role,
                )
            )
        timer.add(returned=len(items), has_more=truncated)

    return SharedRecordListResponse(
        items=items,
        total=len(items),
        has_more=truncated,
    )


@router.get("/{record_id}", response_model=RecordDetail)
def get_record(
    record_id: str,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RecordDetail:
    """レコード詳細を取得する。

    S1 (PR #84): team membership だけでなく `shares` で share された
    ユーザーも閲覧できるよう、`require_read` で認可判定する。team
    membership が無い user は X-Labvault-Team header を record owner team
    に向けて投げる必要がある (Frontend が「他チームから共有」表示の際に
    付与する)。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    require_read(user, rec)
    return _to_detail(rec)


@router.delete("/{record_id}", status_code=204)
def delete_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> None:
    """レコードを削除する (ソフトデリート)."""
    try:
        lab.delete(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")


@router.post("/{record_id}/restore", response_model=RecordDetail)
def restore_record(
    record_id: str,
    lab: Lab = Depends(get_lab),
) -> RecordDetail:
    """削除を取り消す。"""
    try:
        rec = lab.restore(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    return _to_detail(rec)


@router.get("/{record_id}/children", response_model=RecordListResponse)
def get_children(
    record_id: str,
    limit: int = 100,
    offset: int = 0,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RecordListResponse:
    """子レコード一覧を取得する（ページネーション対応）。"""
    from labvault.core.record import Record

    try:
        parent = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    # S1: 親 record の認可を子の閲覧にも適用する (親が見える人は子も見える)。
    require_read(user, parent)

    if hasattr(lab._metadata, "list_records"):
        # total カウント用に大きめに取得
        all_rows = lab._metadata.list_records(
            lab._team,
            parent_id=record_id,
            limit=10000,
        )
        total = len(all_rows)
        rows = all_rows[offset : offset + limit]
        children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        all_children = [r for r in all_records if r.parent_id == record_id]
        total = len(all_children)
        children = all_children[offset : offset + limit]

    return RecordListResponse(
        items=[_to_summary(c) for c in children],
        total=total,
    )


@router.get("/{record_id}/children/conditions")
def get_children_conditions(
    record_id: str,
    limit: int = 5000,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> list[dict[str, Any]]:
    """子レコードの ID + conditions + results を一括取得する。"""
    from labvault.core.record import Record

    try:
        parent = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    # S1: 親 record の認可を子の閲覧にも適用する。
    require_read(user, parent)

    if hasattr(lab._metadata, "list_records"):
        rows = lab._metadata.list_records(lab._team, parent_id=record_id, limit=limit)
        children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        children = [r for r in all_records if r.parent_id == record_id]

    items = []
    for c in children:
        results_raw = c.results.to_dict()
        # __analysis_id を除外
        results = {
            k: v for k, v in results_raw.items() if not k.endswith("__analysis_id")
        }
        items.append(
            {
                "id": c.id,
                "title": c.title,
                "conditions": c.get_conditions(),
                "results": results,
                # scatter 軸ラベルで `[unit]` を出すために units を同梱。
                # 子はだいたい同じ template で揃うので、frontend で集約して
                # 1 つの unitsMap として scatter に渡す。
                "condition_units": c.get_condition_units(),
                "result_units": c.get_result_units(),
            }
        )
    return items


@router.get("/{record_id}/cell_logs", response_model=CellLogListResponse)
def get_cell_logs(
    record_id: str,
    limit: int = 100,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> CellLogListResponse:
    """この record に紐付いた Notebook セル実行ログ (cell_number 昇順)。

    `IPython hooks` で自動収集された CellLog (要件 R13) を Web UI / MCP
    から読めるようにする公開 endpoint。SDK 同梱の ``CellLog`` dataclass
    と同じスキーマ + Pydantic validation。

    R13 は labvault の最大の差別化資産だが、これまで Web / MCP に
    露出経路が無く実質「死蔵」状態だった (Roadmap レビューより)。
    本 endpoint と frontend の CellLog セクション + MCP
    `get_notebook_log` ツールを一式で出すことで「LLM が Notebook 履歴を
    辿って解析を続ける」シナリオが初めて成立する。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_read(user, rec)

    if limit < 1 or limit > 1000:
        raise HTTPException(
            status_code=400, detail="limit must be between 1 and 1000"
        )

    # backend は cell_number 昇順 + limit 件まで返す。`+1` 取って has_more
    # を見るパターン。internal の `_metadata.get_cell_logs` を使う。
    raw = lab._metadata.get_cell_logs(lab._team, record_id, limit=limit + 1)
    truncated = len(raw) > limit
    if truncated:
        raw = raw[:limit]
    items = [CellLogEntry.model_validate(r) for r in raw]
    return CellLogListResponse(items=items, total=len(items), has_more=truncated)


# --- 共有 (S1 / PR #84) ---


@router.get("/{record_id}/shares", response_model=ShareListResponse)
def list_record_shares(
    record_id: str,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> ShareListResponse:
    """この record の共有設定一覧。

    閲覧条件: `can_read` (team membership OR share)。share された側も自分の
    role を確認するため共有設定を見られる。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_read(user, rec)
    shares = getattr(rec, "shares", None) or {}
    return ShareListResponse(
        items=[ShareEntry(email=e, role=r) for e, r in sorted(shares.items())]
    )


@router.post(
    "/{record_id}/shares",
    response_model=RecordDetail,
    status_code=201,
)
def grant_record_share(
    record_id: str,
    body: ShareGrantRequest,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RecordDetail:
    """指定 email にこの record を共有する。

    grant 主体: record の `created_by` 本人 + record team の admin
    (`permissions.can_grant` 参照)。同じ email を再 grant すると role が
    上書きされる (role 変更にも使える)。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_grant(user, rec)

    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="valid email is required")
    if body.role not in VALID_SHARE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {list(VALID_SHARE_ROLES)}",
        )
    # 自分自身に share しない (no-op だが UX 上は警告する)
    if email == (user.email or "").strip().lower():
        raise HTTPException(
            status_code=400,
            detail="cannot share a record with yourself",
        )

    rec.updated_by = user.email
    rec.grant_share(email, body.role)
    log_event(
        logger,
        "record.share_granted",
        record_id=record_id,
        team=lab._team,
        granted_to=email,
        role=body.role,
        granted_by=user.email,
    )
    return _to_detail(rec)


@router.delete("/{record_id}/shares/{email}", response_model=RecordDetail)
def revoke_record_share(
    record_id: str,
    email: str,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RecordDetail:
    """指定 email の share を取り消す。

    revoke 主体: grant と同じ (`can_grant`)。存在しない email を渡しても
    エラーにせず 200 を返す (idempotent revoke、UI 上の race 対策)。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_grant(user, rec)

    target = (email or "").strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail="email is required")
    existed = target in (getattr(rec, "shares", None) or {})
    rec.updated_by = user.email
    rec.revoke_share(target)
    if existed:
        log_event(
            logger,
            "record.share_revoked",
            record_id=record_id,
            team=lab._team,
            revoked_from=target,
            revoked_by=user.email,
        )
    return _to_detail(rec)


# --- Record Operations ---


def _get_and_stamp(lab: Lab, record_id: str, user: User) -> Any:
    """レコード取得 + 更新者刻印。mutator 呼び出し前に使う。"""
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    rec.updated_by = user.email
    return rec


@router.patch("/{record_id}/conditions", response_model=RecordDetail)
def update_conditions(
    record_id: str,
    body: ConditionsUpdate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """実験条件を更新する。"""
    rec = _get_and_stamp(lab, record_id, user)
    rec.conditions(**body.conditions)
    return _to_detail(rec)


@router.post("/{record_id}/tags", response_model=RecordDetail)
def add_tags(
    record_id: str,
    body: TagsUpdate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """タグを追加する。"""
    rec = _get_and_stamp(lab, record_id, user)
    rec.tag(*body.tags)
    return _to_detail(rec)


@router.post("/{record_id}/notes", response_model=RecordDetail)
def add_note(
    record_id: str,
    body: NoteCreate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """メモを追加する。author も認証済 email を刻印。"""
    rec = _get_and_stamp(lab, record_id, user)
    rec.note(body.text, author=user.email)
    return _to_detail(rec)


@router.patch("/{record_id}/status", response_model=RecordDetail)
def update_status(
    record_id: str,
    body: StatusUpdate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """ステータスを更新する。"""
    rec = _get_and_stamp(lab, record_id, user)
    rec.status = body.status
    return _to_detail(rec)


@router.patch("/{record_id}/units", response_model=RecordDetail)
def update_units(
    record_id: str,
    body: ConditionUnitsUpdate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """条件の単位と説明を更新する。"""
    rec = _get_and_stamp(lab, record_id, user)
    rec._condition_units.update(body.units)
    if body.descriptions:
        rec._condition_descriptions.update(body.descriptions)
    rec._persist()
    return _to_detail(rec)


@router.patch("/{record_id}/result_units", response_model=RecordDetail)
def update_result_units(
    record_id: str,
    body: ResultUnitsUpdate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """結果の単位と説明を更新する (conditions 側と対称)."""
    rec = _get_and_stamp(lab, record_id, user)
    rec._result_units.update(body.units)
    if body.descriptions:
        rec._result_descriptions.update(body.descriptions)
    rec._persist()
    return _to_detail(rec)


@router.post("/{record_id}/results", response_model=RecordDetail)
def add_result(
    record_id: str,
    body: ResultUpdate,
    lab: Lab = Depends(get_lab),
    user: User = Depends(current_user),
) -> RecordDetail:
    """結果を追加する。"""
    rec = _get_and_stamp(lab, record_id, user)
    rec.results[body.key] = body.value
    return _to_detail(rec)
