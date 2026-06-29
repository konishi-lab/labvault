"""S1 Phase 2B: share-link 共通 endpoint (/api/share-links/...)。

record-スコープな ``POST/GET/DELETE /api/records/{id}/share-links`` は
records.py 側に置く。本ルータは「token 自身に紐付く操作」だけを担当する。
現状は ``/me`` (自己紹介) のみ。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..auth import User, current_user
from ..schemas import ShareLinkScopeMe

router = APIRouter(prefix="/api/share-links", tags=["share-links"])


@router.get("/me", response_model=ShareLinkScopeMe)
def my_share_link_scope(
    user: User = Depends(current_user),
) -> ShareLinkScopeMe:
    """share-link token 経由で認証された user の自身のスコープを返す。

    ``/share/{token}`` 公開ページが「最初の 1 fetch」でこれを呼び、得た
    ``record_id`` で続いて ``/api/records/{id}`` を叩く流れ。Firebase user
    (``share_link_scope is None``) が叩いた場合は 403 — share-link 専用
    endpoint であることを明示する。
    """
    scope = user.share_link_scope
    if scope is None:
        raise HTTPException(
            status_code=403,
            detail="this endpoint is only available for share-link tokens",
        )
    # 期限 / 失効情報は scope オブジェクトには無いので、ストアから引き直す。
    # active な token だけが ``current_user`` を通るので、ここまで来た時点で
    # is_active は実質 True。ただし表示用に expires_at / revoked_at を返す
    # ため、store からメタデータを補完する。

    # share-link 認証経由なら uid は ``share-link:<hash_prefix>`` 形式
    # (auth.py の _verify_share_link)。先頭 16 char の hash prefix を抽出。
    if not user.uid.startswith("share-link:"):
        # 想定外: share_link_scope はあるのに uid 形式が違う → 500 で気付く
        raise HTTPException(
            status_code=500,
            detail="internal: share-link user has unexpected uid format",
        )
    hash_prefix = user.uid.removeprefix("share-link:")

    from ..dependencies import get_share_link_store

    store = get_share_link_store()
    # hash_prefix からは厳密 lookup できないので、list_for_record + prefix match
    links = store.list_for_record(scope.record_id, scope.team)
    target = next(
        (link_ for link_ in links if link_.token_hash.startswith(hash_prefix)),
        None,
    )

    return ShareLinkScopeMe(
        record_id=scope.record_id,
        team=scope.team,
        role=scope.role,
        pseudo_email=user.email,
        pseudo_display_name=user.display_name,
        expires_at=target.expires_at if target else None,
        revoked_at=target.revoked_at if target else None,
    )
