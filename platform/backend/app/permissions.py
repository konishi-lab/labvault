"""record レベルの認可ロジックを 1 ファイルに集約。

S1 (PR #84): record 共有機能の認可は **team membership だけ** だった既存の
判定を、**team membership OR `shares` 経由** に拡張する。複数の handler で
個別に同じ判定を書くと「 share を考慮し忘れる」事故が起きやすいので、
helper を 1 つ持って全 handler でそれを使う形にする。

呼び出し側 (records.py) は:

    rec = lab.get(record_id)
    require_read(user, rec)            # 読めない → 403

    require_analyze(user, rec)         # 子 record 作成 / file upload
    require_team_membership(user, rec) # record 自体の編集 (タイトル/タグ等)

の 3 段階で使い分ける。share は **編集権限を渡さない** ことが重要 (PR
時点でのスコープ決定): share された側は record 自体を変更できず、子
record を作るか viewer として読むだけ。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .auth import User, is_super_admin

# 共有 role の定義。SDK 側 (`Record.SHARE_ROLES`) と一致させる。
ROLE_VIEWER = "viewer"
ROLE_ANALYST = "analyst"
VALID_SHARE_ROLES = (ROLE_VIEWER, ROLE_ANALYST)


def _get_share_role(record: Any, user_email: str) -> str | None:
    """user_email がこの record に share されているか調べ、role を返す。

    `record` は SDK の `Record` でも、`_from_dict` 前の生 dict でも OK
    (duck-type)。share されていなければ None。`record.shares` または
    `record["shares"]` のどちらでも引ける。
    """
    if not user_email:
        return None
    shares: Any = None
    if hasattr(record, "shares"):
        shares = record.shares
        if callable(shares):
            shares = shares()
    elif isinstance(record, dict):
        shares = record.get("shares")
    if not isinstance(shares, dict):
        return None
    role = shares.get(user_email.strip().lower())
    if isinstance(role, str) and role in VALID_SHARE_ROLES:
        return role
    return None


def can_read(user: User, record: Any) -> bool:
    """user がこの record の **詳細 / ファイル DL** を見られるか。

    判定順:
    1. super_admin → 常に True
    2. team membership (record.team が user.teams に居る) → True
    3. shares に user.email がある (role を問わず) → True
    """
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    if record_team and user.has_team(record_team):
        return True
    return _get_share_role(record, user.email) is not None


def can_analyze(user: User, record: Any) -> bool:
    """user がこの record に対し **解析 (子 record 作成 + file/results 投稿)**
    できるか。

    判定順:
    1. team membership → True (team 内ユーザーは元々何でもできる)
    2. shares で role == "analyst" → True
    3. それ以外 (super_admin だけ / viewer share / 関係なし) → False
    """
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    if record_team and user.has_team(record_team):
        return True
    return _get_share_role(record, user.email) == ROLE_ANALYST


def can_grant(user: User, record: Any) -> bool:
    """user がこの record の **共有を変更 (grant / revoke)** できるか。

    判定順:
    1. super_admin → True
    2. user.email == record.created_by → True (本人による grant)
    3. record.team の team admin → True

    **「他人が grant した share を引き継いだ別チームメンバー」は grant
    できない** (= shares 経由でアクセスしている人は再共有不可)。意図的な
    制限で、share が再帰的に拡散するのを防ぐ。
    """
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    if not record_team:
        return False
    # team admin
    if user.role_in(record_team) == "admin":
        return True
    # record creator 本人
    created_by = _record_field(record, "created_by")
    return bool(
        isinstance(created_by, str)
        and created_by
        and user.email == created_by.strip().lower()
    )


def can_edit(user: User, record: Any) -> bool:
    """user がこの record 自体 (タイトル / タグ / status / 条件 / 結果) を
    編集できるか。

    share された側は **edit 不可** (= team membership だけが edit 権限)。
    解析結果の追加は子 record の作成として `can_analyze` 経由で許可。
    """
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    return bool(record_team and user.has_team(record_team))


# --- HTTPException を投げる require_* ヘルパ ---


def require_read(user: User, record: Any) -> None:
    if not can_read(user, record):
        raise HTTPException(status_code=403, detail="forbidden")


def require_analyze(user: User, record: Any) -> None:
    if not can_analyze(user, record):
        raise HTTPException(status_code=403, detail="analyst access required")


def require_grant(user: User, record: Any) -> None:
    if not can_grant(user, record):
        raise HTTPException(
            status_code=403,
            detail="only record creator or team admin can grant shares",
        )


def require_edit(user: User, record: Any) -> None:
    if not can_edit(user, record):
        raise HTTPException(status_code=403, detail="team membership required")


# --- 内部ヘルパ ---


def _record_team(record: Any) -> str | None:
    """`record.team` (Record) または `record["team"]` (dict) を返す。"""
    if hasattr(record, "team"):
        team = record.team
        if isinstance(team, str):
            return team
    if isinstance(record, dict):
        v = record.get("team")
        if isinstance(v, str):
            return v
    return None


def _record_field(record: Any, name: str) -> Any:
    """Record / dict の汎用 field accessor。"""
    if hasattr(record, name):
        return getattr(record, name)
    if isinstance(record, dict):
        return record.get(name)
    return None
