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

## share の子孫継承 (2026-07-01)

親 record に付いた ``shares`` は、子 / 孫 / ... にも継承される (実験
シリーズを丸ごと共有するユースケースが主。root を共有すれば下の解析
record 全部が付いてくる)。

- 継承するのは ``can_read`` / ``can_analyze`` のみ。``can_grant`` /
  ``can_edit`` は継承しない (共有された人が再共有・編集できるように
  なると事故が起きやすいため意図的に据え置き)
- 子に直接 ``shares[email]`` エントリがある場合はそれが優先。継承は
  「エントリが無い」ときのみ。これにより特定の子だけ role を下げる
  操作 (parent=analyst, child=viewer 明示) が可能
- 継承経路の追跡には lab (parent を fetch する) が必要。lab を渡さない
  ``can_read(user, rec)`` は継承しない (後方互換)。fetch_readable_or_404
  / fetch_analyzable_or_403 経由なら自動で lab が渡される
- share-link scope (token 公開リンク) は依然として **record 1 本固定**。
  scope check が先に走り、子孫には決して降りない (Phase 2 契約)
- ループ / 深すぎる chain は ``_MAX_PARENT_DEPTH`` (=32) で切る
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi import HTTPException

# S1-CQ4 (2026-06-29): 共有 role の定義は SDK 側 (``Record.SHARE_ROLES``)
# を single source of truth として import する。旧実装では backend に
# `VALID_SHARE_ROLES` を別途定義していて、SDK と手動同期になっていた。
from labvault.core.record import Record as _SDKRecord

from .auth import User, is_super_admin

ROLE_VIEWER = "viewer"
ROLE_ANALYST = "analyst"
# 後方互換のため定数も export 維持 (handler が import している)
VALID_SHARE_ROLES = _SDKRecord.SHARE_ROLES

# 親を辿る最大段数。実測 chain は 1-3 段が普通だが、循環 / 悪意ある深い
# chain (実装ミスで parent_id が壊れているケース) の暴走を防ぐガード。
_MAX_PARENT_DEPTH = 32


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


def can_read(user: User, record: Any, *, lab: Any = None) -> bool:
    """user がこの record の **詳細 / ファイル DL** を見られるか。

    判定順:
    1. share-link scope (S1 Phase 2): scope.record_id == rec.id なら
       role 問わず True (viewer/analyst 両方が read 可)。scope mismatch
       なら他の path は試さず False (share-link user の境界を厳格に保つ)
    2. super_admin → 常に True
    3. team membership (record.team が user.teams に居る) → True
    4. shares に user.email がある (role を問わず) → True
    5. (2026-07-01) lab が渡されていれば、親 record の shares を辿って
       いずれかに user.email があれば True (子孫継承)。直接 4 で match
       した場合は 4 が優先されるため、ここには到達しない
    """
    if user.share_link_scope is not None:
        return _matches_share_link_scope(user.share_link_scope, record)
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    if record_team and user.has_team(record_team):
        return True
    if _get_share_role(record, user.email) is not None:
        return True
    return _inherits_share_role(lab, record, user.email) is not None


def can_analyze(user: User, record: Any, *, lab: Any = None) -> bool:
    """user がこの record に対し **解析 (子 record 作成 + file/results 投稿)**
    できるか。

    判定順:
    1. share-link scope (S1 Phase 2): scope.record_id == rec.id かつ
       scope.role == "analyst" のみ True。viewer scope はここで False。
       scope mismatch も False (他の path に fall through しない)
    2. team membership → True (team 内ユーザーは元々何でもできる)
    3. shares に user.email エントリがあればそれを見る:
       - role == "analyst" → True
       - role == "viewer"  → False (**明示的に downgrade された child**
         なら継承しない。「parent=analyst でも child=viewer 指定」ができる)
    4. (2026-07-01) shares に直接エントリが無ければ、lab 経由で親を
       辿って **最も近い祖先** の role を継承 (analyst のみ True)
    """
    if user.share_link_scope is not None:
        return (
            _matches_share_link_scope(user.share_link_scope, record)
            and user.share_link_scope.role == ROLE_ANALYST
        )
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    if record_team and user.has_team(record_team):
        return True
    direct = _get_share_role(record, user.email)
    if direct is not None:
        return direct == ROLE_ANALYST
    return _inherits_share_role(lab, record, user.email) == ROLE_ANALYST


def can_grant(user: User, record: Any) -> bool:
    """user がこの record の **共有を変更 (grant / revoke)** できるか。

    判定順:
    1. share-link user (S1 Phase 2) → 常に False (再共有 / token 再発行
       を禁止。token は record owner / team admin から明示発行されたもの
       だけが有効)
    2. super_admin → True
    3. user.email == record.created_by → True (本人による grant)
    4. record.team の team admin → True

    **「他人が grant した share を引き継いだ別チームメンバー」は grant
    できない** (= shares 経由でアクセスしている人は再共有不可)。意図的な
    制限で、share が再帰的に拡散するのを防ぐ。
    """
    if user.share_link_scope is not None:
        return False
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
    S1 Phase 2 share-link user も同様に edit 不可 (analyst でも子 record
    作成と upload だけが許される)。
    """
    if user.share_link_scope is not None:
        return False
    if is_super_admin(user):
        return True
    record_team = _record_team(record)
    return bool(record_team and user.has_team(record_team))


# --- HTTPException を投げる require_* ヘルパ ---


def require_read(user: User, record: Any, *, lab: Any = None) -> None:
    if not can_read(user, record, lab=lab):
        raise HTTPException(status_code=403, detail="forbidden")


def require_analyze(user: User, record: Any, *, lab: Any = None) -> None:
    if not can_analyze(user, record, lab=lab):
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


def fetch_readable_or_404(lab: Any, record_id: str, user: User) -> Any:
    """S1-SEC6 hot-fix (2026-06-29): record fetch + read 認可を uniform 404 で扱う。

    旧 ``require_read`` は **record 存在 (lab.get で 404) と 認可失敗 (403)**
    を分けて返していたため、攻撃者が任意の 6 桁 Base32 ID と任意の
    X-Labvault-Team header の組合せで「ID が存在するか」を確認できる
    存在オラクル (404 vs 403) になっていた。

    本 helper は **どちらの失敗も 404 で返す** ことで存在オラクルを構造
    的に消す。GitHub の private repo と同じ defense-in-depth pattern。

    Read endpoint (``get_record`` / ``get_children`` / ``files`` /
    ``preview`` / ``cell_logs`` 等) で使う。Write endpoint は
    ``fetch_analyzable_or_403`` 経由で「read までは通る user は 403、
    read も通らない user は 404」と分岐させる (既知 record への write 拒否は
    存在を漏らさないので 403 で OK)。
    """
    from labvault.core.exceptions import RecordNotFoundError

    try:
        rec = lab.get(record_id)
    except RecordNotFoundError:
        raise HTTPException(status_code=404, detail="Record not found") from None
    if not can_read(user, rec, lab=lab):
        # 404 で uniform。403 にすると存在を漏らす。
        raise HTTPException(status_code=404, detail="Record not found")
    return rec


def fetch_analyzable_or_403(lab: Any, record_id: str, user: User) -> Any:
    """S1-SEC6: write endpoint 用。read は通るが analyze 不可なら 403。

    - record 不在 / read 不可 → 404 (uniform、存在オラクル無し)
    - read 通るが analyze 不可 (viewer 共有等) → 403 (存在は既知なので
      隠す意味なし、書込権限不足を明示)
    """
    rec = fetch_readable_or_404(lab, record_id, user)
    if not can_analyze(user, rec, lab=lab):
        raise HTTPException(
            status_code=403, detail="analyst access required"
        )
    return rec


def fetch_grantable_or_403(lab: Any, record_id: str, user: User) -> Any:
    """S1-SEC6: share grant/revoke / share-link issue 用。read 通るが
    grant 不可 → 403。

    pattern は analyzable と同じ (read 通った user に対する write 拒否)。
    """
    rec = fetch_readable_or_404(lab, record_id, user)
    if not can_grant(user, rec):
        raise HTTPException(
            status_code=403,
            detail="only record creator or team admin can grant shares",
        )
    return rec


def require_team_member(user: User, team: str) -> None:
    """指定 team の membership を強制する (record を介さない write 用)。

    主に **root record の作成** で使う。share 経由のユーザーが root
    record を自由に作れると team の空間を勝手に汚せてしまうので、root
    record は team member だけが作る。子 record (parent_id 指定) は親に
    対する ``require_analyze`` で判定する別経路。super_admin はバイパス。
    S1 Phase 2 share-link user も root 作成は不可 (scope は record 1 本に
    固定で、新規 root を作れる権限を持たない設計)。
    """
    if user.share_link_scope is not None:
        raise HTTPException(
            status_code=403,
            detail="share-link token では root record を作成できません",
        )
    if is_super_admin(user):
        return
    if not user.has_team(team):
        raise HTTPException(
            status_code=403,
            detail=f"team {team!r} の member ではありません",
        )


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


def _matches_share_link_scope(scope: Any, record: Any) -> bool:
    """share-link scope と record の対応関係を検証する。

    record_id だけでなく **team も一致** することを要求する (Crockford
    Base32 6 桁 ID が別 team で衝突する確率はゼロに近いが、ID 衝突を
    悪用するシナリオを構造的に排除するためのガード)。
    """
    rid = _record_id(record)
    rteam = _record_team(record)
    return bool(
        rid is not None
        and rid == scope.record_id
        and rteam is not None
        and rteam == scope.team
    )


def _record_id(record: Any) -> str | None:
    """`record.id` (Record) または `record["id"]` (dict) を返す。"""
    if hasattr(record, "id"):
        rid = record.id
        if isinstance(rid, str):
            return rid
    if isinstance(record, dict):
        v = record.get("id")
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


def _walk_parents(lab: Any, record: Any) -> Iterator[Any]:
    """親から祖父母、曾祖父母…と順に yield する。

    - ``parent_id`` が None / 空 / str 以外なら停止
    - ``lab.get`` が RecordNotFoundError なら停止 (壊れた chain の途中で
      切れているケース。継承を諦める方が安全)
    - 循環参照 (A→B→A) や過剰に深い chain は ``_MAX_PARENT_DEPTH`` で切る
    - lab が None なら継承なし (後方互換フォールバック)
    """
    if lab is None:
        return
    from labvault.core.exceptions import RecordNotFoundError

    seen: set[str] = set()
    start_id = _record_id(record)
    if isinstance(start_id, str):
        seen.add(start_id)

    current = record
    for _ in range(_MAX_PARENT_DEPTH):
        pid = _record_field(current, "parent_id")
        if not isinstance(pid, str) or not pid or pid in seen:
            return
        seen.add(pid)
        try:
            parent = lab.get(pid)
        except RecordNotFoundError:
            return
        yield parent
        current = parent


def _inherits_share_role(lab: Any, record: Any, user_email: str) -> str | None:
    """親を辿って最初に見つかった (= 最も近い祖先の) share role を返す。

    見つからなければ None。lab=None なら常に None (継承しない)。
    """
    for ancestor in _walk_parents(lab, record):
        role = _get_share_role(ancestor, user_email)
        if role is not None:
            return role
    return None
