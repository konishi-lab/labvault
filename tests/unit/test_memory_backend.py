"""backends/memory.py のテスト。"""

from __future__ import annotations

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)

T = "team1"


class TestInMemoryMetadataBackend:
    def test_create_and_get(self, metadata_backend: InMemoryMetadataBackend) -> None:
        data = {
            "id": "AB3F",
            "title": "XRD",
            "status": "running",
            "tags": ["XRD"],
        }
        metadata_backend.create_record(T, data)
        got = metadata_backend.get_record(T, "AB3F")
        assert got is not None
        assert got["title"] == "XRD"

    def test_get_nonexistent(self, metadata_backend: InMemoryMetadataBackend) -> None:
        assert metadata_backend.get_record(T, "ZZZZ") is None

    def test_update(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.create_record(T, {"id": "A", "title": "old"})
        metadata_backend.update_record(T, "A", {"title": "new"})
        got = metadata_backend.get_record(T, "A")
        assert got is not None
        assert got["title"] == "new"

    def test_delete(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.create_record(T, {"id": "A", "title": "x"})
        metadata_backend.delete_record(T, "A")
        assert metadata_backend.get_record(T, "A") is None

    def test_list_all(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.create_record(T, {"id": "A", "title": "a", "updated_at": "2"})
        metadata_backend.create_record(T, {"id": "B", "title": "b", "updated_at": "1"})
        records = metadata_backend.list_records(T)
        assert len(records) == 2

    def test_list_filter_tags(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.create_record(T, {"id": "A", "tags": ["XRD"]})
        metadata_backend.create_record(T, {"id": "B", "tags": ["SEM"]})
        records = metadata_backend.list_records(T, tags=["XRD"])
        assert len(records) == 1
        assert records[0]["id"] == "A"

    def test_list_filter_status(
        self, metadata_backend: InMemoryMetadataBackend
    ) -> None:
        metadata_backend.create_record(T, {"id": "A", "status": "success"})
        metadata_backend.create_record(T, {"id": "B", "status": "failed"})
        records = metadata_backend.list_records(T, status="success")
        assert len(records) == 1
        assert records[0]["id"] == "A"

    def test_list_filter_type(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.create_record(T, {"id": "A", "type": "experiment"})
        metadata_backend.create_record(T, {"id": "B", "type": "sample"})
        records = metadata_backend.list_records(T, record_type="experiment")
        assert len(records) == 1

    def test_list_excludes_deleted(
        self, metadata_backend: InMemoryMetadataBackend
    ) -> None:
        metadata_backend.create_record(T, {"id": "A", "deleted_at": None})
        metadata_backend.create_record(T, {"id": "B", "deleted_at": "2026-01-01"})
        records = metadata_backend.list_records(T)
        assert len(records) == 1
        assert records[0]["id"] == "A"

    def test_list_limit_offset(self, metadata_backend: InMemoryMetadataBackend) -> None:
        for i in range(10):
            metadata_backend.create_record(T, {"id": str(i), "updated_at": str(i)})
        records = metadata_backend.list_records(T, limit=3, offset=2)
        assert len(records) == 3

    def test_deep_copy_isolation(
        self, metadata_backend: InMemoryMetadataBackend
    ) -> None:
        data = {"id": "A", "tags": ["XRD"]}
        metadata_backend.create_record(T, data)
        data["tags"].append("SEM")
        got = metadata_backend.get_record(T, "A")
        assert got is not None
        assert got["tags"] == ["XRD"]

    def test_cell_log(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.save_cell_log(T, "AB3F", {"cell_number": 1, "source": "x=1"})
        metadata_backend.save_cell_log(T, "AB3F", {"cell_number": 2, "source": "y=2"})
        logs = metadata_backend.get_cell_logs(T, "AB3F")
        assert len(logs) == 2

    def test_template(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.save_template(
            T, "XRD", {"name": "XRD", "default_tags": ["XRD"]}
        )
        tmpl = metadata_backend.get_template(T, "XRD")
        assert tmpl is not None
        assert tmpl["name"] == "XRD"
        assert metadata_backend.get_template(T, "NONE") is None
        assert len(metadata_backend.list_templates(T)) == 1

    def test_team_isolation(self, metadata_backend: InMemoryMetadataBackend) -> None:
        metadata_backend.create_record("team1", {"id": "A", "title": "t1"})
        metadata_backend.create_record("team2", {"id": "A", "title": "t2"})
        r1 = metadata_backend.get_record("team1", "A")
        r2 = metadata_backend.get_record("team2", "A")
        assert r1 is not None and r1["title"] == "t1"
        assert r2 is not None and r2["title"] == "t2"


class TestInMemoryStorageBackend:
    def test_upload_download(self, storage_backend: InMemoryStorageBackend) -> None:
        storage_backend.upload("/data/file.csv", b"a,b\n1,2")
        assert storage_backend.download("/data/file.csv") == b"a,b\n1,2"

    def test_download_not_found(self, storage_backend: InMemoryStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            storage_backend.download("/nonexistent")

    def test_exists(self, storage_backend: InMemoryStorageBackend) -> None:
        assert not storage_backend.exists("/file")
        storage_backend.upload("/file", b"data")
        assert storage_backend.exists("/file")

    def test_delete(self, storage_backend: InMemoryStorageBackend) -> None:
        storage_backend.upload("/file", b"data")
        storage_backend.delete("/file")
        assert not storage_backend.exists("/file")

    def test_list_files(self, storage_backend: InMemoryStorageBackend) -> None:
        storage_backend.upload("/data/a.csv", b"")
        storage_backend.upload("/data/b.csv", b"")
        storage_backend.upload("/other/c.csv", b"")
        files = storage_backend.list_files("/data/")
        assert files == ["/data/a.csv", "/data/b.csv"]


class TestInMemorySearchBackend:
    def test_index_and_search(self, search_backend: InMemorySearchBackend) -> None:
        search_backend.index(T, "AB3F", "Fe-Cr XRD")
        results = search_backend.search(T, "Fe-Cr")
        assert len(results) == 1
        assert results[0]["record_id"] == "AB3F"

    def test_search_case_insensitive(
        self, search_backend: InMemorySearchBackend
    ) -> None:
        search_backend.index(T, "AB3F", "XRD measurement")
        results = search_backend.search(T, "xrd")
        assert len(results) == 1

    def test_search_no_match(self, search_backend: InMemorySearchBackend) -> None:
        search_backend.index(T, "AB3F", "XRD")
        results = search_backend.search(T, "SEM")
        assert len(results) == 0

    def test_delete_index(self, search_backend: InMemorySearchBackend) -> None:
        search_backend.index(T, "AB3F", "XRD")
        search_backend.delete_index(T, "AB3F")
        results = search_backend.search(T, "XRD")
        assert len(results) == 0

    def test_search_limit(self, search_backend: InMemorySearchBackend) -> None:
        for i in range(10):
            search_backend.index(T, str(i), "keyword")
        results = search_backend.search(T, "keyword", limit=3)
        assert len(results) == 3
