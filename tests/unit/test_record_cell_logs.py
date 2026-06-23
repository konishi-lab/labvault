"""`Record.cell_logs()` accessor の検証。

backend (memory / firestore / platform) すべてに `get_cell_logs` が
あるが、SDK 利用者からは Record メソッド経由が clean。MCP
`get_notebook_log` ツールもこの accessor 経由で書かれているので、
1 段ラップが正しく動くことを担保する。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


def _cell(cell_id: str, n: int, source: str) -> dict:
    return {
        "cell_id": cell_id,
        "record_id": "",
        "cell_number": n,
        "execution_count": n,
        "source": source,
        "source_hash": "abc",
        "new_vars": {},
        "changed_vars": {},
        "deleted_vars": [],
        "duration_sec": 0.0,
        "executed_at": datetime.now(UTC).isoformat(),
        "error": None,
        "session_id": "s",
    }


@pytest.fixture()
def lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
    ):
        monkeypatch.setenv(k, "")
    return Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


def test_record_cell_logs_returns_sorted_list(lab: Lab) -> None:
    rec = lab.new("nb", auto_log=False)
    lab._metadata.save_cell_log(lab._team, rec.id, _cell("b", 2, "y = 1"))
    lab._metadata.save_cell_log(lab._team, rec.id, _cell("a", 1, "x = 1"))

    logs = rec.cell_logs()
    assert [c["cell_number"] for c in logs] == [1, 2]
    assert logs[0]["source"] == "x = 1"


def test_record_cell_logs_empty(lab: Lab) -> None:
    rec = lab.new("bare", auto_log=False)
    assert rec.cell_logs() == []


def test_record_cell_logs_respects_limit(lab: Lab) -> None:
    rec = lab.new("nb", auto_log=False)
    for i in range(1, 6):
        lab._metadata.save_cell_log(lab._team, rec.id, _cell(f"c{i}", i, f"# {i}"))
    assert len(rec.cell_logs(limit=3)) == 3
    assert len(rec.cell_logs(limit=100)) == 5
