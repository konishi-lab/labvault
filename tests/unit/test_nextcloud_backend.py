"""NextcloudStorage のユニットテスト (nc-py-api をモック)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from labvault.backends.nextcloud import NextcloudStorage


@pytest.fixture()
def storage():
    """モック済み NextcloudStorage。"""
    with patch(
        "labvault.backends.nextcloud.NextcloudStorage._get_client"
    ) as mock_get:
        mock_nc = MagicMock()
        mock_get.return_value = mock_nc
        s = NextcloudStorage(
            url="https://nc.example.com",
            user="testuser",
            password="testpass",
            group_folder="24UTARIM004",
        )
        # _nc を直接セットして遅延初期化をバイパス
        s._nc = mock_nc
        yield s


class TestPathConversion:
    def test_full_path(self):
        s = NextcloudStorage(
            url="https://nc.example.com",
            user="u",
            password="p",
            group_folder="24UTARIM004",
        )
        assert s._full_path("team/AB3F/data.csv") == (
            "24UTARIM004/labvault/team/AB3F/data.csv"
        )

    def test_base_path(self):
        s = NextcloudStorage(
            url="https://nc.example.com",
            user="u",
            password="p",
            group_folder="mygroup",
        )
        assert s._base_path == "mygroup/labvault"


class TestUpload:
    def test_upload_creates_parent_dirs(self, storage):
        storage.upload("team/AB3F/data.csv", b"hello")

        storage._nc.files.makedirs.assert_called_once_with(
            "24UTARIM004/labvault/team/AB3F", exist_ok=True
        )

    def test_upload_calls_nc_upload(self, storage):
        storage.upload("team/AB3F/data.csv", b"hello")

        storage._nc.files.upload.assert_called_once_with(
            "24UTARIM004/labvault/team/AB3F/data.csv", b"hello"
        )

    def test_upload_returns_sdk_path(self, storage):
        result = storage.upload("team/AB3F/data.csv", b"hello")
        assert result == "team/AB3F/data.csv"


class TestDownload:
    def test_download_returns_bytes(self, storage):
        storage._nc.files.download.return_value = b"file content"

        result = storage.download("team/AB3F/data.csv")

        assert result == b"file content"
        storage._nc.files.download.assert_called_once_with(
            "24UTARIM004/labvault/team/AB3F/data.csv"
        )

    def test_download_raises_on_bad_type(self, storage):
        storage._nc.files.download.return_value = "not bytes"

        with pytest.raises(TypeError, match="Unexpected"):
            storage.download("team/AB3F/data.csv")


class TestDelete:
    def test_delete_calls_nc(self, storage):
        storage.delete("team/AB3F/data.csv")

        storage._nc.files.delete.assert_called_once_with(
            "24UTARIM004/labvault/team/AB3F/data.csv",
            not_fail=True,
        )


class TestExists:
    def test_exists_true(self, storage):
        storage._nc.files.by_path.return_value = SimpleNamespace(
            name="data.csv"
        )
        assert storage.exists("team/AB3F/data.csv") is True

    def test_exists_false(self, storage):
        storage._nc.files.by_path.return_value = None
        assert storage.exists("team/AB3F/data.csv") is False


class TestListFiles:
    def test_list_files(self, storage):
        storage._nc.files.listdir.return_value = [
            SimpleNamespace(
                is_dir=False,
                user_path="/24UTARIM004/labvault/team/AB3F/a.csv",
            ),
            SimpleNamespace(
                is_dir=False,
                user_path="/24UTARIM004/labvault/team/AB3F/b.csv",
            ),
            SimpleNamespace(
                is_dir=True,
                user_path="/24UTARIM004/labvault/team/AB3F/subdir",
            ),
        ]

        result = storage.list_files("team/AB3F")
        assert result == ["team/AB3F/a.csv", "team/AB3F/b.csv"]

    def test_list_files_empty(self, storage):
        storage._nc.files.listdir.side_effect = Exception("not found")
        assert storage.list_files("team/XXXX") == []
