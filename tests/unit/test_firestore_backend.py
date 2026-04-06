"""FirestoreMetadataBackend のユニットテスト (Firestore をモック)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from labvault.backends.firestore import FirestoreMetadataBackend


@pytest.fixture()
def backend():
    """モック済み FirestoreMetadataBackend。"""
    with patch(
        "labvault.backends.firestore.FirestoreMetadataBackend._get_db"
    ) as mock_get:
        mock_db = MagicMock()
        mock_get.return_value = mock_db
        b = FirestoreMetadataBackend(project="test", database="(default)")
        b._db = mock_db
        yield b


def _mock_doc(data, exists=True):
    doc = MagicMock()
    doc.exists = exists
    doc.to_dict.return_value = data
    return doc


class TestRecordCRUD:
    def test_create_record(self, backend):
        data = {"id": "AB3F", "title": "test", "deleted_at": None}
        backend.create_record("team-a", data)

        backend._db.collection.assert_called_with("teams")

    def test_get_record(self, backend):
        data = {"id": "AB3F", "title": "test", "deleted_at": None}
        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = _mock_doc(data)

        result = backend.get_record("team-a", "AB3F")
        assert result == data

    def test_get_record_not_found(self, backend):
        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = _mock_doc(None, exists=False)

        result = backend.get_record("team-a", "XXXX")
        assert result is None

    def test_get_record_deleted(self, backend):
        """deleted_at が設定されている場合は None を返す。"""
        data = {"id": "AB3F", "deleted_at": "2026-01-01T00:00:00Z"}
        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = _mock_doc(data)

        result = backend.get_record("team-a", "AB3F")
        assert result is None

    def test_update_record(self, backend):
        data = {"id": "AB3F", "title": "updated"}
        backend.update_record("team-a", "AB3F", data)

        # set with merge=True
        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.set
        ).assert_called_once_with(data, merge=True)

    def test_delete_record(self, backend):
        backend.delete_record("team-a", "AB3F")

        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.delete
        ).assert_called_once()


class TestCellLog:
    def test_save_cell_log(self, backend):
        data = {"cell_id": "c1", "cell_number": 1, "source": "x = 1"}
        backend.save_cell_log("team-a", "AB3F", data)

        # cell_logs サブコレクションに保存される
        backend._db.collection.assert_called()

    def test_save_cell_log_generates_id(self, backend):
        """cell_id がない場合は自動生成される。"""
        data = {"cell_number": 1, "source": "x = 1"}
        backend.save_cell_log("team-a", "AB3F", data)
        assert "cell_id" in data


class TestTemplate:
    def test_save_template(self, backend):
        data = {"display_name": "XRD", "type": "experiment"}
        backend.save_template("team-a", "XRD", data)

        backend._db.collection.assert_called()

    def test_get_template(self, backend):
        data = {"display_name": "XRD", "type": "experiment"}
        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = _mock_doc(data)

        result = backend.get_template("team-a", "XRD")
        assert result == data

    def test_get_template_not_found(self, backend):
        (
            backend._db.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = _mock_doc(None, exists=False)

        result = backend.get_template("team-a", "XXXX")
        assert result is None
