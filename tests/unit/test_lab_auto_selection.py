"""Lab auto-selection (Phase 5) のユニットテスト。

settings.token + settings.platform_url の組み合わせで Lab() がどの backend を
選ぶかを確認する。Settings は env で操作。
"""

from __future__ import annotations

import pytest

from labvault.backends.firestore import FirestoreMetadataBackend
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.backends.platform_metadata import PlatformMetadataBackend
from labvault.backends.platform_search import PlatformEmbedding, PlatformSearch
from labvault.backends.platform_storage import PlatformStorage
from labvault.core.config import Settings
from labvault.core.lab import Lab, _build_platform_client


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in [
        "LABVAULT_TOKEN",
        "LABVAULT_PLATFORM_URL",
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_TEAM",
        "LABVAULT_USER",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_USER",
        "LABVAULT_NEXTCLOUD_PASSWORD",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_AUTO_SYNC",
    ]:
        monkeypatch.delenv(key, raising=False)


def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """env / .env / ~/.labvault/credentials のすべてを無効化して、テストが他の
    環境の値を拾わないようにする。"""
    _clear_env(monkeypatch)
    # cwd を tmp に切替えて .env 干渉を排除
    monkeypatch.chdir(tmp_path)
    # ~/.labvault/credentials も拾わないように HOME を tmp に
    monkeypatch.setenv("HOME", str(tmp_path))
    # auto_sync を切る (テストでバッファ書き込みを起動させない)
    monkeypatch.setenv("LABVAULT_AUTO_SYNC", "false")


class TestBuildPlatformClient:
    def test_returns_none_when_no_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _isolate_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LABVAULT_PLATFORM_URL", "https://x.test")
        # token 不在
        assert _build_platform_client(Settings()) is None

    def test_returns_none_when_no_url(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _isolate_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LABVAULT_TOKEN", "lv_x")
        # url 不在
        assert _build_platform_client(Settings()) is None

    def test_returns_client_when_both_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _isolate_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LABVAULT_TOKEN", "lv_x")
        monkeypatch.setenv("LABVAULT_PLATFORM_URL", "https://x.test")
        client = _build_platform_client(Settings())
        assert client is not None
        # token を直接埋め込む path
        assert client._get_access_token() == "lv_x"


class TestLabAutoSelection:
    def test_pat_mode_uses_platform_backends(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _isolate_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LABVAULT_TOKEN", "lv_pat_test")
        monkeypatch.setenv("LABVAULT_PLATFORM_URL", "https://x.test")
        monkeypatch.setenv("LABVAULT_TEAM", "test-team")

        lab = Lab()
        assert isinstance(lab._metadata, PlatformMetadataBackend)
        assert isinstance(lab._storage, PlatformStorage)
        assert isinstance(lab._search, PlatformSearch)
        assert isinstance(lab._embedding, PlatformEmbedding)
        # team が PlatformStorage / PlatformEmbedding に伝わる
        assert lab._storage._team == "test-team"
        assert lab._embedding._team == "test-team"

    def test_no_token_no_gcp_uses_memory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        _isolate_env(monkeypatch, tmp_path)
        # token なし、gcp_project もなし → InMemory にフォールバック
        lab = Lab()
        assert isinstance(lab._metadata, InMemoryMetadataBackend)
        assert isinstance(lab._storage, InMemoryStorageBackend)
        assert isinstance(lab._search, InMemorySearchBackend)
        assert lab._embedding is None

    def test_token_without_url_falls_back_to_direct(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """token だけ設定されていても URL が無ければ Platform mode に入らない。

        gcp_project が設定されていれば Firestore 直結。
        """
        _isolate_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LABVAULT_TOKEN", "lv_x")
        monkeypatch.setenv("LABVAULT_GCP_PROJECT", "test-project")

        lab = Lab()
        assert isinstance(lab._metadata, FirestoreMetadataBackend)
        assert not isinstance(lab._metadata, PlatformMetadataBackend)

    def test_explicit_backend_overrides_pat_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """metadata_backend を明示指定した場合、PAT mode でもそれが優先される。"""
        _isolate_env(monkeypatch, tmp_path)
        monkeypatch.setenv("LABVAULT_TOKEN", "lv_x")
        monkeypatch.setenv("LABVAULT_PLATFORM_URL", "https://x.test")

        explicit_meta = InMemoryMetadataBackend()
        lab = Lab(metadata_backend=explicit_meta)
        assert lab._metadata is explicit_meta
        # 他の backend は PAT mode のものが入る (mix も OK)
        assert isinstance(lab._storage, PlatformStorage)
