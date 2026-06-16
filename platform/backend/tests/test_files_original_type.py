"""``/api/records/{id}`` と ``/api/records/{id}/files`` で
``DataRef.original_type`` がレスポンスに含まれていることを確認する。

LLM 解析 / Web UI が「これは Figure 由来か装置 raw か」を拡張子推測でなく
metadata から判別する基盤になる。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from app.main import app
from fastapi.testclient import TestClient

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def seeded_lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    """``konishi-lab`` 用の InMemory Lab。複数の add_* 経路で record にファイルを
    積む。"""
    for key in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
    ):
        monkeypatch.setenv(key, "")
    lab = Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )
    rec = lab.new("file-type-test", auto_log=False)
    # add_object 経由 (semantic タグが付くケース)
    rec.add_object("config.json", {"detector": "HyPix"})
    rec.add_object("memo.txt", "first peak found")
    # add_bytes 経由 (raw、original_type=None)
    rec.add_bytes("photo.png", b"\x89PNG\r\n...", content_type="image/png")
    return lab


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, seeded_lab: Lab) -> Iterator[TestClient]:
    monkeypatch.setattr(
        "app.dependencies.get_lab_for_team",
        lambda team_id: seeded_lab,
    )
    with TestClient(app) as c:
        yield c


def _record_id(lab: Lab) -> str:
    """seeded_lab で作った唯一の record の ID を返す。"""
    items = lab.list(limit=10)
    assert items, "seeded_lab に record が無い"
    return items[0].id


def test_record_detail_includes_original_type(
    client: TestClient, seeded_lab: Lab
) -> None:
    rid = _record_id(seeded_lab)
    res = client.get(f"/api/records/{rid}")
    assert res.status_code == 200
    body = res.json()
    files = {f["name"]: f for f in body["files"]}
    assert files["config.json"]["original_type"] == "dict"
    assert files["memo.txt"]["original_type"] == "str"
    # add_bytes 経路は raw 取り込み扱い → None
    assert files["photo.png"]["original_type"] is None


def test_files_list_endpoint_includes_original_type(
    client: TestClient, seeded_lab: Lab
) -> None:
    rid = _record_id(seeded_lab)
    res = client.get(f"/api/records/{rid}/files")
    assert res.status_code == 200
    files = {f["name"]: f for f in res.json()}
    assert files["config.json"]["original_type"] == "dict"
    assert files["memo.txt"]["original_type"] == "str"
    assert files["photo.png"]["original_type"] is None


def test_original_type_field_present_even_when_null(
    client: TestClient, seeded_lab: Lab
) -> None:
    """API レスポンスに必ず original_type キーが含まれることを確認 (frontend が
    optional として扱えるよう、欠落でなく明示的に null/string が返る)。"""
    rid = _record_id(seeded_lab)
    res = client.get(f"/api/records/{rid}/files")
    for f in res.json():
        assert "original_type" in f
