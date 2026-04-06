"""Nextcloud 結合テスト (実サーバー接続)。

実行方法:
    LABVAULT_NEXTCLOUD_URL=https://... \
    LABVAULT_NEXTCLOUD_USER=... \
    LABVAULT_NEXTCLOUD_PASSWORD=... \
    LABVAULT_NEXTCLOUD_GROUP_FOLDER=... \
    pytest tests/integration/test_nextcloud_live.py -v -m integration
"""

from __future__ import annotations

import uuid

import pytest

from labvault.backends.nextcloud import NextcloudStorage
from labvault.core.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture()
def storage():
    """実 Nextcloud に接続する NextcloudStorage。"""
    settings = Settings()
    if not settings.nextcloud_url:
        pytest.skip("LABVAULT_NEXTCLOUD_URL not set")
    return NextcloudStorage(
        url=settings.nextcloud_url,
        user=settings.nextcloud_user,
        password=settings.nextcloud_password,
        group_folder=settings.nextcloud_group_folder,
    )


@pytest.fixture()
def test_path():
    """テスト用のユニークなパス。"""
    uid = uuid.uuid4().hex[:8]
    return f"_test/{uid}/test_file.txt"


class TestNextcloudLive:
    def test_upload_download_delete(self, storage, test_path):
        data = b"hello from labvault integration test"

        # upload
        result = storage.upload(test_path, data)
        assert result == test_path

        # exists
        assert storage.exists(test_path) is True

        # download
        downloaded = storage.download(test_path)
        assert downloaded == data

        # delete
        storage.delete(test_path)
        assert storage.exists(test_path) is False

    def test_list_files(self, storage, test_path):
        storage.upload(test_path, b"test")

        prefix = "/".join(test_path.split("/")[:-1])
        files = storage.list_files(prefix)
        assert test_path in files

        # cleanup
        storage.delete(test_path)
