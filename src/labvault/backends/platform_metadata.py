"""HTTP-based metadata backend (PAT-friendly)。

PAT 認証で動く SDK 用の MetadataBackend 実装。直接 Firestore に行かず、
labvault platform backend の ``/api/metadata/*`` 経由でアクセスする。

Phase 2: read 系のみ実装。write 系は Phase 3 で追加予定。
"""

from __future__ import annotations

import logging
from typing import Any

from .platform_client import PlatformClient, PlatformNotFound

logger = logging.getLogger(__name__)


class PlatformMetadataBackend:
    """labvault platform 経由のメタデータバックエンド。

    PlatformClient が Authorization header (PAT or ADC token) を載せて
    backend を呼ぶ。team は X-Labvault-Team header で渡す。

    write 系メソッドは ``NotImplementedError``。Phase 3 で実装する。
    """

    def __init__(self, client: PlatformClient) -> None:
        self._client = client

    # --- Record CRUD ---

    def create_record(self, team: str, data: dict[str, Any]) -> None:
        raise NotImplementedError(
            "PlatformMetadataBackend.create_record is not yet implemented (Phase 3)"
        )

    def get_record(self, team: str, record_id: str) -> dict[str, Any] | None:
        try:
            return self._client.get_dict(
                f"/api/metadata/records/{record_id}", team=team
            )
        except PlatformNotFound:
            return None

    def update_record(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError(
            "PlatformMetadataBackend.update_record is not yet implemented (Phase 3)"
        )

    def delete_record(self, team: str, record_id: str) -> None:
        raise NotImplementedError(
            "PlatformMetadataBackend.delete_record is not yet implemented (Phase 3)"
        )

    def list_records(
        self,
        team: str,
        *,
        tags: list[str] | None = None,
        status: str | None = None,
        record_type: str | None = None,
        created_by: str | None = None,
        parent_id: str | None = "__unset__",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if tags:
            params["tags"] = ",".join(tags)
        if status:
            params["status"] = status
        if record_type:
            params["type"] = record_type
        if created_by:
            params["created_by"] = created_by
        # parent_id semantics:
        #   "__unset__" (default) → omit both → server-side: no filter
        #   None → parent_unset=true (root only)
        #   str → parent_id=<value>
        if parent_id is None:
            params["parent_unset"] = "true"
        elif parent_id != "__unset__":
            params["parent_id"] = parent_id
        return self._client.get_list("/api/metadata/records", team=team, params=params)

    # --- CellLog ---

    def save_cell_log(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        raise NotImplementedError(
            "PlatformMetadataBackend.save_cell_log is not yet implemented (Phase 3)"
        )

    def get_cell_logs(
        self, team: str, record_id: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self._client.get_list(
            f"/api/metadata/records/{record_id}/cell_logs",
            team=team,
            params={"limit": limit},
        )

    # --- Template ---

    def save_template(self, team: str, name: str, data: dict[str, Any]) -> None:
        raise NotImplementedError(
            "PlatformMetadataBackend.save_template is not yet implemented (Phase 3)"
        )

    def get_template(self, team: str, name: str) -> dict[str, Any] | None:
        try:
            return self._client.get_dict(f"/api/metadata/templates/{name}", team=team)
        except PlatformNotFound:
            return None

    def list_templates(self, team: str) -> list[dict[str, Any]]:
        return self._client.get_list("/api/metadata/templates", team=team)
