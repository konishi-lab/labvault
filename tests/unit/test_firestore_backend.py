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

    def _record_ref(self, backend):
        """mock の collection→document→collection→document chain を辿った doc ref。"""
        teams_coll = backend._db.collection.return_value
        team_doc = teams_coll.document.return_value
        records_coll = team_doc.collection.return_value
        return records_coll.document.return_value

    def test_update_record_uses_update_not_set_merge(self, backend):
        """S1-DATA1 regression: ``update()`` を使う (top-level 全置換)。

        旧実装 ``set(data, merge=True)`` は nested map (``shares`` 等) を
        deep-merge するため revoke した email subfield が残留し
        authorization leak になる。``update()`` は top-level field 単位の
        置換でこれを防ぐ。
        """
        data = {"id": "AB3F", "title": "updated"}
        backend.update_record("team-a", "AB3F", data)

        ref = self._record_ref(backend)
        ref.update.assert_called_once_with(data)
        # 旧実装 (set merge=True) は呼ばれない
        ref.set.assert_not_called()

    def test_update_record_falls_back_to_set_on_not_found(self, backend):
        """``update()`` は doc 不在で NotFound を投げる → ``set()`` で
        fallback (buffer 復元 / legacy 経路保護)。

        google.api_core が未インストール (``[gcp]`` extra 無し) の環境
        では fallback path を試せないので skip。
        """
        NotFound = pytest.importorskip("google.api_core.exceptions").NotFound

        ref = self._record_ref(backend)
        ref.update.side_effect = NotFound("missing")

        data = {"id": "AB3F", "title": "fresh"}
        backend.update_record("team-a", "AB3F", data)

        ref.update.assert_called_once_with(data)
        ref.set.assert_called_once_with(data)

    def test_update_record_replaces_shares_map_fully(self, backend):
        """S1-DATA1: revoke で消えた email が Firestore 側にも残らないこと。

        ``_to_dict()`` の結果として ``shares`` field を含む dict を渡せば、
        ``update()`` は top-level shares を完全に置換する (deep-merge せず)。
        本テストは「呼び出された引数に消えたはずの email が含まれていな
        いこと」を、Firestore mock 経由で確認する (再現テストの SDK 部分)。
        """
        # 初期 grant: 2 件
        initial = {
            "id": "AB3F",
            "shares": {"alice@x.com": "viewer", "bob@y.com": "viewer"},
        }
        backend.update_record("team-a", "AB3F", initial)

        # bob を revoke 後 (SDK が _to_dict で送る形)
        after_revoke = {"id": "AB3F", "shares": {"alice@x.com": "viewer"}}
        backend.update_record("team-a", "AB3F", after_revoke)

        ref = self._record_ref(backend)
        # 2 回 update() が呼ばれ、2 回目の引数は alice だけ含む shares
        assert ref.update.call_count == 2
        second_call_args = ref.update.call_args_list[1][0][0]
        assert second_call_args["shares"] == {"alice@x.com": "viewer"}
        assert "bob@y.com" not in second_call_args["shares"]

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
