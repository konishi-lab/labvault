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
    can_grant,
    can_read,
    require_analyze,
    require_grant,
    require_read,
    require_team_member,
)
from ..schemas import (
    AggregateResponse,
    CellLogEntry,
    CellLogListResponse,
    ConditionsUpdate,
    ConditionUnitsUpdate,
    CreatedShareLink,
    NoteCreate,
    RecordCreate,
    RecordDetail,
    RecordListResponse,
    RecordSummary,
    ResultUnitsUpdate,
    ResultUpdate,
    RevokeShareLinkResponse,
    ShareEntry,
    ShareGrantRequest,
    ShareLinkCreate,
    ShareLinkInfo,
    ShareLinkListResponse,
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
        created_audit_source=getattr(rec, "created_audit_source", None),
        updated_audit_source=getattr(rec, "updated_audit_source", None),
    )


def _to_detail(rec: Any, viewer: User | None = None) -> RecordDetail:
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

    # S1-CQ1 (2026-06-29 hot-fix): `shares` (email → role) は **grant 主体**
    # にだけ全件返す。viewer/analyst として共有された Firebase user / 外部
    # share-link user は他の共有相手の email を見られない (情報漏洩防止)。
    # backward-compat の `viewer=None` 経路は内部 helper (sub() の親 stamp
    # 等) 用で、外部 API では必ず viewer を渡すこと。
    all_shares = getattr(rec, "shares", None) or {}
    if viewer is None or can_grant(viewer, rec):
        # grant 主体は全件見える
        visible_shares = dict(all_shares)
    elif viewer.email and viewer.email.strip().lower() in all_shares:
        # 共有された側 (Firebase user): 自分の role 1 件だけ返す
        # (UI が「あなたは viewer/analyst として共有されています」表示用)
        my_email = viewer.email.strip().lower()
        visible_shares = {my_email: all_shares[my_email]}
    else:
        visible_shares = {}

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
        created_audit_source=getattr(rec, "created_audit_source", None),
        updated_audit_source=getattr(rec, "updated_audit_source", None),
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
        shares=visible_shares,
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


def _audit_source_for(user: User) -> str:
    """S1-SEC2 hot-fix (2026-06-29): user の認証経路を audit field 用文字列で返す。

    share-link token 経由なら ``"share-link"``、それ以外 (Firebase / PAT /
    super_admin) は ``"firebase"``。SDK 直接呼び出し (Notebook 経由) は
    backend handler を通らないので、本関数は呼ばれない (Record の
    `_created_audit_source` は None のまま = legacy 経路として扱われる)。
    """
    return "share-link" if user.share_link_scope is not None else "firebase"


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
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RecordDetail:
    """レコードを作成する。created_by は認証済 email を刻印。

    S1 Phase 1C: ``parent_id`` 指定で子 record を作る場合は親 record に
    対する ``require_analyze`` で認可判定 — 他チームから analyst 共有
    された user も解析結果 record を作れる。``parent_id`` 未指定 (root
    record 作成) は team membership を要求 (``require_team_member``) —
    share 経由 user が team 空間に勝手に root を作るのを防ぐ。
    """
    source = _audit_source_for(user)
    if body.parent_id:
        # 子 record 作成 — 親への analyst 権限が要る
        try:
            parent = lab.get(body.parent_id)
        except RecordNotFoundError:
            raise HTTPException(
                status_code=404, detail="parent record not found"
            ) from None
        require_analyze(user, parent)
        # `Record.sub()` は親 Lab の default user を created_by に使う
        # ため、ここでは lab.new() + parent_id 直結 + bidirectional link
        # を inline で書いて created_by に呼び出し user の email を刻む。
        rec = lab.new(
            body.title,
            type=body.type,
            tags=body.tags if body.tags else None,
            auto_log=False,
            created_by=user.email,
            **body.conditions,
        )
        rec._parent_id = parent.id
        # S1-SEC2: audit source は作成時に決定 (created/updated 両方)
        rec._created_audit_source = source
        rec._updated_audit_source = source
        rec.updated_by = user.email
        rec._persist()
        # `Record.sub()` と揃える: 親⇄子の双方向 link を張る
        parent.link(rec.id, "has_child")
        rec.link(parent.id, "child_of")
    else:
        # root record 作成 — team membership を要求
        require_team_member(user, lab._team)
        rec = lab.new(
            body.title,
            type=body.type,
            tags=body.tags if body.tags else None,
            auto_log=False,
            created_by=user.email,
            **body.conditions,
        )
        # S1-SEC2: lab.new 後に audit source を刻んで再 persist (1 round-trip)
        rec._created_audit_source = source
        rec._updated_audit_source = source
        rec._persist()
    return _to_detail(rec, user)


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

    S1-SEC1 (2026-06-29 hot-fix): share-link token (`ls_*`) で叩くと、
    token の ``pseudo_email`` が偶然他 record の ``shared_with_emails``
    に含まれた場合 (例: 内部関係者が ``ceo@company.com`` のような被害者
    email を指定して token 発行 → /shared-with-me で全 team 横断 enumerate)
    cross-tenant disclosure が起きる。share-link は「record 1 本 + role」
    が scope 契約 (Phase 2 設計) なので、この endpoint は **Firebase 認証
    の user 限定** とする。
    """
    if user.share_link_scope is not None:
        # share-link token は 1 record scope。複数 record にまたがる
        # /shared-with-me は scope 外。
        raise HTTPException(
            status_code=403,
            detail="share-link tokens cannot list shared records (1-record scope)",
        )
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
                    created_audit_source=d.get("created_audit_source"),
                    updated_audit_source=d.get("updated_audit_source"),
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
    return _to_detail(rec, user)


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
    user: User = Depends(current_user),
) -> RecordDetail:
    """削除を取り消す。"""
    try:
        rec = lab.restore(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    # S1-SEC2: restore も mutation の一種
    rec.updated_by = user.email
    rec.updated_audit_source = _audit_source_for(user)
    rec._persist()
    return _to_detail(rec, user)


@router.get("/{record_id}/children", response_model=RecordListResponse)
def get_children(
    record_id: str,
    limit: int = 100,
    offset: int = 0,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RecordListResponse:
    """子レコード一覧を取得する（ページネーション対応）。

    認可 (S1-SEC3 hot-fix 2026-06-29): 親 ``require_read`` に加え、
    **per-child の ``can_read`` で filter する**。share-link user は
    scope = record 1 本に固定 (Phase 2 設計) なので、parent 経由で他
    子の summary が漏れないようにする。Firebase の team member /
    super_admin は can_read が全 child で True になるので影響なし。
    """
    from labvault.core.record import Record

    try:
        parent = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    require_read(user, parent)

    if hasattr(lab._metadata, "list_records"):
        all_rows = lab._metadata.list_records(
            lab._team,
            parent_id=record_id,
            limit=10000,
        )
        all_children_raw = [Record._from_dict(r, lab=lab) for r in all_rows]
    else:
        all_records = lab.list(limit=10000)
        all_children_raw = [r for r in all_records if r.parent_id == record_id]

    # S1-SEC3: 子ごとの認可。share-link scope user は scope record のみ
    # 通過 (parent 自身は children に出ない構造なので、share-link で
    # parent を持つ user は children を 0 件として見ることになる)。
    visible_children = [c for c in all_children_raw if can_read(user, c)]
    total = len(visible_children)
    children = visible_children[offset : offset + limit]

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
    """子レコードの ID + conditions + results を一括取得する。

    S1-SEC3 hot-fix (2026-06-29): get_children と同様に **per-child の
    ``can_read`` で filter** する。share-link viewer/analyst は scope
    record の child は本来読めない契約なので、conditions / results 全件
    が parent 経由で漏れないようにする。
    """
    from labvault.core.record import Record

    try:
        parent = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found")
    require_read(user, parent)

    if hasattr(lab._metadata, "list_records"):
        rows = lab._metadata.list_records(lab._team, parent_id=record_id, limit=limit)
        all_children = [Record._from_dict(r, lab=lab) for r in rows]
    else:
        all_records = lab.list(limit=10000)
        all_children = [r for r in all_records if r.parent_id == record_id]

    # S1-SEC3: per-child 認可
    children = [c for c in all_children if can_read(user, c)]

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

    閲覧条件 (S1-CQ1 hot-fix 2026-06-29): ``require_grant`` で gating する。
    旧仕様では ``require_read`` で通していたため、share された外部 user /
    share-link user が他の共有相手の email を全件 enumerate できる情報
    漏洩があった。share された側が「自分の role」を確認するには
    ``GET /api/records/{id}`` レスポンスの ``shares`` field (こちらも
    S1-CQ1 で自分のエントリ 1 件だけ返るように制限) を使うこと。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_grant(user, rec)
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
    rec.updated_audit_source = _audit_source_for(user)
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
    return _to_detail(rec, user)


# --- 外部 token sharing (S1 Phase 2) ---


def _link_to_info(link: Any) -> ShareLinkInfo:
    """``ShareLink`` (dataclass) → ``ShareLinkInfo`` (Pydantic) のアダプタ。"""
    return ShareLinkInfo(
        token_hash_prefix=link.token_hash[:16],
        record_id=link.record_id,
        team=link.team,
        role=link.role,
        pseudo_email=link.pseudo_email,
        pseudo_display_name=link.pseudo_display_name,
        created_by=link.created_by,
        created_at=link.created_at,
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        last_used_at=getattr(link, "last_used_at", None),
        label=link.label,
        is_active=link.is_active(),
    )


@router.get("/{record_id}/share-links", response_model=ShareLinkListResponse)
def list_record_share_links(
    record_id: str,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> ShareLinkListResponse:
    """この record の発行済 share-link 一覧。

    閲覧可能なのは grant 主体 (``can_grant``)。raw token は含まれない
    ので、漏洩リスクは無いが「誰宛てに何個 link 出ているか」は機微情報
    なので閲覧主体を絞っている。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_grant(user, rec)

    from ..dependencies import get_share_link_store

    store = get_share_link_store()
    links = store.list_for_record(record_id, lab._team)
    links.sort(key=lambda link_: link_.created_at, reverse=True)
    return ShareLinkListResponse(items=[_link_to_info(link_) for link_ in links])


@router.post(
    "/{record_id}/share-links",
    response_model=CreatedShareLink,
    status_code=201,
)
def issue_record_share_link(
    record_id: str,
    body: ShareLinkCreate,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> CreatedShareLink:
    """record 1 本に対する外部 token を発行する。

    発行主体: ``can_grant`` (record creator / team admin / super-admin)。
    raw token は **本レスポンスにのみ** 含まれ、Firestore には SHA-256
    hash しか残らない (PAT 方式)。発行者は受け取った raw token を即
    クライアントへ伝える運用 (再表示不可)。

    audit 用に pseudo email + pseudo display name を required にしてある。
    token で書き込まれた record の ``created_by`` / ``updated_by`` には
    この pseudo identity が刻まれる。
    """
    import datetime as _dt

    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_grant(user, rec)

    if body.role not in VALID_SHARE_ROLES:
        raise HTTPException(
            status_code=400,
            detail=f"role must be one of {list(VALID_SHARE_ROLES)}",
        )
    pseudo_email = (body.pseudo_email or "").strip().lower()
    if not pseudo_email or "@" not in pseudo_email:
        raise HTTPException(
            status_code=400,
            detail="valid pseudo_email is required (audit 用 identity)",
        )
    # S1-SEC2 B1 (2026-06-29 hot-fix): 既存の Firebase user (allowed_users
    # doc が存在) と同じ email を pseudo_email に指定するのは impersonation
    # の温床なので reject する。`created_audit_source` field でも別経路で
    # 検出可能だが、ここでの reject は最初の防御線 (defense-in-depth)。
    # Firestore 1 read で 1 doc を見るだけなので cost も極小。
    from ..auth import allowed_users_ref

    try:
        if allowed_users_ref().document(pseudo_email).get().exists:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"pseudo_email {pseudo_email!r} は既存の Firebase user の "
                    "email と一致します。share-link は外部協力者向け identity "
                    "なので、実在 user とは衝突しない値を指定してください "
                    "(例: ext+<name>@klab.share など)"
                ),
            )
    except HTTPException:
        raise
    except Exception:
        # Firestore 障害時は best-effort で通す (chain of trust より availability)。
        # 後段の audit_source field で十分検出可能。
        logger.warning(
            "allowed_users lookup failed during share-link issue, "
            "skipping pseudo_email collision check",
            exc_info=True,
        )

    display = (body.pseudo_display_name or pseudo_email).strip()

    from ..share_links import MAX_EXPIRES_DAYS, ShareLink, generate_token

    days = body.expires_days if body.expires_days is not None else 30
    if days < 0 or days > MAX_EXPIRES_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"expires_days must be between 0 and {MAX_EXPIRES_DAYS}",
        )
    now = _dt.datetime.now(_dt.UTC)
    expires_at = (now + _dt.timedelta(days=days)) if days > 0 else None

    raw_token, token_hash = generate_token()
    link = ShareLink(
        token_hash=token_hash,
        record_id=record_id,
        team=lab._team,
        role=body.role,
        pseudo_email=pseudo_email,
        pseudo_display_name=display,
        created_by=user.email,
        created_at=now,
        expires_at=expires_at,
        revoked_at=None,
        label=(body.label or "").strip(),
    )

    from ..dependencies import get_share_link_store

    store = get_share_link_store()
    store.create(link)

    log_event(
        logger,
        "record.share_link_issued",
        record_id=record_id,
        team=lab._team,
        token_hash_prefix=token_hash[:16],
        role=body.role,
        pseudo_email=pseudo_email,
        expires_at=expires_at.isoformat() if expires_at else None,
        issued_by=user.email,
    )

    info = _link_to_info(link)
    return CreatedShareLink(
        token=raw_token,
        token_hash_prefix=info.token_hash_prefix,
        record_id=info.record_id,
        team=info.team,
        role=info.role,
        pseudo_email=info.pseudo_email,
        pseudo_display_name=info.pseudo_display_name,
        created_by=info.created_by,
        created_at=info.created_at,
        expires_at=info.expires_at,
        revoked_at=info.revoked_at,
        last_used_at=info.last_used_at,
        label=info.label,
        is_active=info.is_active,
    )


@router.delete(
    "/{record_id}/share-links/{token_hash_prefix}",
    response_model=RevokeShareLinkResponse,
)
def revoke_record_share_link(
    record_id: str,
    token_hash_prefix: str,
    lab: Lab = Depends(get_lab_relaxed),
    user: User = Depends(current_user),
) -> RevokeShareLinkResponse:
    """指定 token の link を revoke する (revoked_at を立てる)。

    revoke 主体: ``can_grant``。prefix は list 表示用の先頭 16 文字。
    完全 hash でなく prefix 経由なのは URL の取り回しの都合 (raw token
    自体は二度と表示されないため)。collision (2^64) は実用上ゼロ。
    """
    import datetime as _dt

    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    require_grant(user, rec)

    prefix = (token_hash_prefix or "").strip().lower()
    if not prefix or len(prefix) < 8:
        raise HTTPException(
            status_code=400, detail="token_hash_prefix must be at least 8 chars"
        )

    from ..dependencies import get_share_link_store

    store = get_share_link_store()
    target = next(
        (
            link_
            for link_ in store.list_for_record(record_id, lab._team)
            if link_.token_hash.startswith(prefix)
        ),
        None,
    )
    if target is None:
        raise HTTPException(status_code=404, detail="share-link not found")

    now = _dt.datetime.now(_dt.UTC)
    store.revoke(target.token_hash, at=now)
    log_event(
        logger,
        "record.share_link_revoked",
        record_id=record_id,
        team=lab._team,
        token_hash_prefix=target.token_hash[:16],
        revoked_by=user.email,
    )
    return RevokeShareLinkResponse(
        status="ok", token_hash_prefix=target.token_hash[:16]
    )


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
    rec.updated_audit_source = _audit_source_for(user)
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
    return _to_detail(rec, user)


# --- Record Operations ---


def _get_and_stamp(lab: Lab, record_id: str, user: User) -> Any:
    """レコード取得 + 更新者刻印。mutator 呼び出し前に使う。

    S1-SEC2 hot-fix (2026-06-29): ``updated_audit_source`` も合わせて刻む。
    続く mutator が ``_persist()`` を呼ぶ前にこの 2 つを set しておく
    (Record.updated_by setter / updated_audit_source setter は _persist
    を呼ばない設計なので、同じパターン)。
    """
    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    rec.updated_by = user.email
    rec.updated_audit_source = _audit_source_for(user)
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
    return _to_detail(rec, user)


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
    return _to_detail(rec, user)


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
    return _to_detail(rec, user)


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
    return _to_detail(rec, user)


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
    return _to_detail(rec, user)


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
    return _to_detail(rec, user)


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
    return _to_detail(rec, user)
