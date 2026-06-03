"""共通テスト fixture。"""

from __future__ import annotations

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab


@pytest.fixture(autouse=True)
def _blank_builtin_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """0.2.2 で `Settings` に埋め込まれた konishi-lab 本番運用 default を
    全テストで空に上書きする。

    背景: `gcp_project` が常に default で埋まっていると、auto-selection
    が optional な `google.cloud.firestore` を import しに行く。CI の
    `[dev]` だけインストール環境では `ModuleNotFoundError` で落ちる。

    本番運用 default を直接テストしたい場合は、各テスト側で
    `monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")`
    のように再設定すれば後勝ちで上書きできる。
    """
    for key in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_PLATFORM_URL",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
    ):
        monkeypatch.setenv(key, "")


@pytest.fixture()
def metadata_backend() -> InMemoryMetadataBackend:
    return InMemoryMetadataBackend()


@pytest.fixture()
def storage_backend() -> InMemoryStorageBackend:
    return InMemoryStorageBackend()


@pytest.fixture()
def search_backend() -> InMemorySearchBackend:
    return InMemorySearchBackend()


@pytest.fixture()
def lab() -> Lab:
    return Lab(
        "test-team",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )
