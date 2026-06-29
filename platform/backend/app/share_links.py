"""S1 Phase 2 — 外部 token sharing 用の ``shared_links`` ストア。

PAT (Personal Access Token) と似た形だが record 単位スコープで、record
所有チームに属さない外部協力者にも token を発行できるようにする。
受け取った側は ``Authorization: Bearer ls_<hex>`` で record 1 本に対する
viewer / analyst 権限を得る。

設計:

- token 文字列は ``ls_`` (link-share) + 32 hex char (= 128 bit)。raw token
  はクライアントに 1 回だけ返し、Firestore には **SHA-256 hash のみ** を
  保存する (PAT と同じ)
- スコープは **record 1 本** に固定。複数 record を 1 token で扱いたい
  場合は別 token を発行する設計 (failure blast radius を最小化)
- pseudo email + pseudo display name は token 発行時に明示指定。
  audit trail (``created_by`` / ``updated_by``) にそのまま記録される
- 有効期限 (optional)、revoke (manual)、label (free-form) を持つ
- record と同じ team に紐付ける (team が削除された場合の cascade で
  share-link も消える想定)

ストアは抽象化して Firestore / InMemory の差し替えができる構造にする
(tests は InMemory 経路で監査可能)。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Any, Protocol

SHARE_LINK_PREFIX = "ls_"
TOKEN_HEX_LENGTH = 32  # 128 bit
MAX_EXPIRES_DAYS = 365  # 1 year — それより長い token は発行できない


@dataclass(frozen=True)
class ShareLink:
    """1 件の share-link Firestore document。"""

    token_hash: str  # SHA-256 hex (64 chars)
    record_id: str
    team: str
    role: str  # "viewer" | "analyst"
    pseudo_email: str
    pseudo_display_name: str
    created_by: str  # 発行した user の email
    created_at: dt.datetime
    expires_at: dt.datetime | None
    revoked_at: dt.datetime | None
    label: str

    def is_active(self, *, now: dt.datetime | None = None) -> bool:
        """有効期限 + revoke の両方を見て、現在使えるか判定する。"""
        if self.revoked_at is not None:
            return False
        if self.expires_at is None:
            return True
        ref = now or dt.datetime.now(dt.UTC)
        return self.expires_at > ref

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_hash": self.token_hash,
            "record_id": self.record_id,
            "team": self.team,
            "role": self.role,
            "pseudo_email": self.pseudo_email,
            "pseudo_display_name": self.pseudo_display_name,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ShareLink:
        # Firestore は datetime をそのまま読み書きできる。InMemory でも同様。
        return cls(
            token_hash=d["token_hash"],
            record_id=d["record_id"],
            team=d.get("team", ""),
            role=d.get("role", "viewer"),
            pseudo_email=d.get("pseudo_email", ""),
            pseudo_display_name=d.get("pseudo_display_name", ""),
            created_by=d.get("created_by", ""),
            created_at=d.get("created_at", dt.datetime.now(dt.UTC)),
            expires_at=d.get("expires_at"),
            revoked_at=d.get("revoked_at"),
            label=d.get("label", ""),
        )


# --- ストア抽象 ----------------------------------------------------------


class ShareLinkStore(Protocol):
    """share-link の永続化抽象。Firestore / InMemory の両方が実装する。"""

    def create(self, link: ShareLink) -> None: ...

    def get_by_hash(self, token_hash: str) -> ShareLink | None: ...

    def list_for_record(self, record_id: str, team: str) -> list[ShareLink]: ...

    def revoke(self, token_hash: str, *, at: dt.datetime) -> bool:
        """revoked_at を立てる。存在しなければ False。"""
        ...


@dataclass
class InMemoryShareLinkStore:
    """テスト用のインメモリ実装。"""

    _docs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def create(self, link: ShareLink) -> None:
        self._docs[link.token_hash] = link.to_dict()

    def get_by_hash(self, token_hash: str) -> ShareLink | None:
        d = self._docs.get(token_hash)
        return ShareLink.from_dict(d) if d else None

    def list_for_record(self, record_id: str, team: str) -> list[ShareLink]:
        return [
            ShareLink.from_dict(d)
            for d in self._docs.values()
            if d.get("record_id") == record_id and d.get("team") == team
        ]

    def revoke(self, token_hash: str, *, at: dt.datetime) -> bool:
        d = self._docs.get(token_hash)
        if d is None:
            return False
        d["revoked_at"] = at
        return True


class FirestoreShareLinkStore:
    """``shared_links`` collection を Firestore 上に持つ実装。"""

    COLLECTION = "shared_links"

    def __init__(self, db: Any) -> None:
        self._db = db

    def _ref(self) -> Any:
        return self._db.collection(self.COLLECTION)

    def create(self, link: ShareLink) -> None:
        # doc ID は token_hash 先頭 16 文字。collision は 2^64 程度なので
        # 実用上ぶつからない。リスト表示時のキーにも便利。
        doc_id = link.token_hash[:16]
        self._ref().document(doc_id).set(link.to_dict())

    def get_by_hash(self, token_hash: str) -> ShareLink | None:
        from google.cloud.firestore_v1.base_query import FieldFilter

        snaps = list(
            self._ref()
            .where(filter=FieldFilter("token_hash", "==", token_hash))
            .limit(1)
            .stream()
        )
        if not snaps:
            return None
        return ShareLink.from_dict(snaps[0].to_dict() or {})

    def list_for_record(self, record_id: str, team: str) -> list[ShareLink]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        snaps = (
            self._ref()
            .where(filter=FieldFilter("record_id", "==", record_id))
            .where(filter=FieldFilter("team", "==", team))
            .stream()
        )
        return [ShareLink.from_dict(s.to_dict() or {}) for s in snaps]

    def revoke(self, token_hash: str, *, at: dt.datetime) -> bool:
        # doc ID lookup の方が高速だが、token_hash が doc_id と一致する
        # 保証は無い (collision 回避で衝突したら別 ID を振る将来拡張)。
        # 安全側に query → update で一発処理する。
        from google.cloud.firestore_v1.base_query import FieldFilter

        snaps = list(
            self._ref()
            .where(filter=FieldFilter("token_hash", "==", token_hash))
            .limit(1)
            .stream()
        )
        if not snaps:
            return False
        snaps[0].reference.update({"revoked_at": at})
        return True


# --- token 発行ヘルパ ---------------------------------------------------


def generate_token() -> tuple[str, str]:
    """新規 share-link token を生成する。

    戻り値: (raw_token, token_hash)。raw_token は呼び出し側から
    クライアントへ 1 回だけ返し、token_hash のみを永続化する (再表示不可)。
    """
    raw_hex = secrets.token_hex(TOKEN_HEX_LENGTH // 2)
    raw_token = f"{SHARE_LINK_PREFIX}{raw_hex}"
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token, token_hash


def hash_token(raw_token: str) -> str:
    """検証用: クライアントから来た raw token を hash に変換する。"""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
