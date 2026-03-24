"""共通テスト fixture。"""

from __future__ import annotations

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def metadata_backend() -> InMemoryMetadataBackend:
    return InMemoryMetadataBackend()


@pytest.fixture()
def storage_backend() -> InMemoryStorageBackend:
    return InMemoryStorageBackend()


@pytest.fixture()
def search_backend() -> InMemorySearchBackend:
    return InMemorySearchBackend()
