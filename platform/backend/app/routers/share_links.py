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

    # S1-CQ8 hot-fix (2026-06-29): ``ShareLinkScope`` に ``token_hash`` を
    # 保持するようになったので、``get_by_hash`` で 1 read 直叩きできる。
    # 旧実装は uid prefix から list_for_record + prefix 一致検索で、record
    # あたり N read かかっていた (発行数が増えるほど比例で読み込み増)。
    #
    # 期限 / 失効情報は scope object には無いので、ストアから引き直す。
    # active token だけが ``current_user`` を通るので、ここまで来た時点で
    # is_active=True (表示用に expires_at / revoked_at を返すため fetch)。

    from ..dependencies import get_share_link_store

    target = get_share_link_store().get_by_hash(scope.token_hash)

    return ShareLinkScopeMe(
        record_id=scope.record_id,
        team=scope.team,
        role=scope.role,
        pseudo_email=user.email,
        pseudo_display_name=user.display_name,
        expires_at=target.expires_at if target else None,
        revoked_at=target.revoked_at if target else None,
    )
