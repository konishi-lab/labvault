"""共通テスト fixture。"""

from __future__ import annotations

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab


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
