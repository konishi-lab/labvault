"""Firestore 結合テスト (実サーバー接続)。

実行方法:
    LABVAULT_GCP_PROJECT=klab-proto \
    pytest tests/integration/test_firestore_live.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest

from labvault.backends.firestore import FirestoreMetadataBackend
from labvault.core.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture()
def backend():
    settings = Settings()
    if not settings.gcp_project:
        pytest.skip("LABVAULT_GCP_PROJECT not set")
    return FirestoreMetadataBackend(
        project=settings.gcp_project,
        database=settings.firestore_database,
    )


@pytest.fixture()
def team():
    return f"_test_{uuid.uuid4().hex[:8]}"


class TestFirestoreLive:
    def test_create_get_delete(self, backend, team):
        data = {
            "id": "T001",
            "title": "integration test",
            "type": "experiment",
            "status": "running",
            "tags": ["test"],
            "conditions": {},
            "results": {},
            "notes": [],
            "links": [],
            "data_refs": [],
            "external_refs": [],
            "events": [],
            "created_by": "tester",
            "created_at": "2026-04-06T00:00:00+00:00",
            "updated_at": "2026-04-06T00:00:00+00:00",
            "deleted_at": None,
            "parent_id": None,
        }

        # create
        backend.create_record(team, data)

        # get
        result = backend.get_record(team, "T001")
        assert result is not None
        assert result["title"] == "integration test"

        # update
        backend.update_record(team, "T001", {"title": "updated"})
        result = backend.get_record(team, "T001")
        assert result["title"] == "updated"

        # cleanup
        backend.delete_record(team, "T001")
        result = backend.get_record(team, "T001")
        assert result is None

    def test_cell_log(self, backend, team):
        # レコードを先に作成
        data = {
            "id": "T002",
            "title": "cell log test",
            "type": "experiment",
            "status": "running",
            "tags": [],
            "conditions": {},
            "results": {},
            "notes": [],
            "links": [],
            "data_refs": [],
            "external_refs": [],
            "events": [],
            "created_by": "tester",
            "created_at": "2026-04-06T00:00:00+00:00",
            "updated_at": "2026-04-06T00:00:00+00:00",
            "deleted_at": None,
            "parent_id": None,
        }
        backend.create_record(team, data)

        # セルログ保存
        log = {
            "cell_id": "log1",
            "cell_number": 1,
            "execution_count": 1,
            "source": "x = 1",
            "source_hash": "abc",
            "new_vars": {"x": "1"},
            "changed_vars": {},
            "deleted_vars": [],
            "duration_sec": 0.01,
            "executed_at": "2026-04-06T00:00:00+00:00",
            "error": None,
            "session_id": "test:1234",
        }
        backend.save_cell_log(team, "T002", log)

        # 取得
        logs = backend.get_cell_logs(team, "T002")
        assert len(logs) >= 1
        assert logs[0]["source"] == "x = 1"

        # cleanup
        backend.delete_record(team, "T002")
