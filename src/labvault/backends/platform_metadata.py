"""HTTP-based metadata backend (PAT-friendly)。

PAT 認証で動く SDK 用の MetadataBackend 実装。直接 Firestore に行かず、
labvault platform backend の ``/api/metadata/*`` 経由でアクセスする。

Phase 2 (read) + Phase 3 (write) どちらも実装済み。残りは file storage 系
(Phase 4) と Lab auto-selection (Phase 5)。
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import logging
import uuid
from typing import Any

from .platform_client import PlatformClient, PlatformNotFound

logger = logging.getLogger(__name__)


def _to_jsonable(value: Any) -> Any:
    """SDK 側の dict を JSON-safe な形に変換する (datetime → ISO 文字列)."""
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    return value


class PlatformMetadataBackend:
    """labvault platform 経由のメタデータバックエンド。

    PlatformClient が Authorization header (PAT or ADC token) を載せて
    backend を呼ぶ。team は X-Labvault-Team header で渡す。
    """

    def __init__(self, client: PlatformClient) -> None:
        self._client = client

    # --- Record CRUD ---

    def create_record(self, team: str, data: dict[str, Any]) -> None:
        if not data.get("id"):
            raise ValueError("record data must include 'id'")
        self._client._request(
            "POST",
            "/api/metadata/records",
            team=team,
            json=_to_jsonable(data),
        )

    def get_record(self, team: str, record_id: str) -> dict[str, Any] | None:
        try:
            return self._client.get_dict(
                f"/api/metadata/records/{record_id}", team=team
            )
        except PlatformNotFound:
            return None

    def update_record(self, team: str, record_id: str, data: dict[str, Any]) -> None:
        self._client._request(
            "PATCH",
            f"/api/metadata/records/{record_id}",
            team=team,
            json=_to_jsonable(data),
        )

    def delete_record(self, team: str, record_id: str) -> None:
        # Firestore の delete は冪等 (存在しなくてもエラーにならない) ので
        # 404 もそのまま success として扱う
        with contextlib.suppress(PlatformNotFound):
            self._client._request(
                "DELETE",
                f"/api/metadata/records/{record_id}",
                team=team,
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
        # FirestoreMetadataBackend と同じく、cell_id が無ければ生成して dict に埋める
        if not data.get("cell_id"):
            data["cell_id"] = uuid.uuid4().hex
        resp = self._client._request(
            "POST",
            f"/api/metadata/records/{record_id}/cell_logs",
            team=team,
            json=_to_jsonable(data),
        )
        # backend が生成し直した cell_id を返してきた場合に同期 (こちらが既に
        # 入れているので通常は同じ)
        if isinstance(resp, dict) and resp.get("cell_id"):
            data["cell_id"] = resp["cell_id"]

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
        self._client._request(
            "PUT",
            f"/api/metadata/templates/{name}",
            team=team,
            json=_to_jsonable(data),
        )

    def get_template(self, team: str, name: str) -> dict[str, Any] | None:
        try:
            return self._client.get_dict(f"/api/metadata/templates/{name}", team=team)
        except PlatformNotFound:
            return None

    def list_templates(self, team: str) -> list[dict[str, Any]]:
        return self._client.get_list("/api/metadata/templates", team=team)
