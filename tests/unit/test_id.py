"""core/id.py のテスト。"""

from __future__ import annotations

from labvault.core.id import generate_id, normalize_id


class TestGenerateId:
    def test_length(self) -> None:
        assert len(generate_id()) == 4

    def test_custom_length(self) -> None:
        assert len(generate_id(8)) == 8

    def test_charset(self) -> None:
        valid = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
        for _ in range(100):
            rid = generate_id()
            assert all(c in valid for c in rid), f"Invalid char in {rid}"

    def test_uppercase(self) -> None:
        for _ in range(100):
            rid = generate_id()
            assert rid == rid.upper()

    def test_no_ambiguous_chars(self) -> None:
        ambiguous = set("ILOU")
        for _ in range(1000):
            rid = generate_id()
            assert not ambiguous.intersection(rid), f"Ambiguous char in {rid}"

    def test_uniqueness(self) -> None:
        ids = {generate_id() for _ in range(200)}
        assert len(ids) >= 199  # 4文字IDで200個なら衝突はほぼ起きない


class TestNormalizeId:
    def test_uppercase(self) -> None:
        assert normalize_id("ab3f") == "AB3F"

    def test_o_to_zero(self) -> None:
        assert normalize_id("AO3F") == "A03F"

    def test_i_to_one(self) -> None:
        assert normalize_id("AI3F") == "A13F"

    def test_l_to_one(self) -> None:
        assert normalize_id("AL3F") == "A13F"

    def test_mixed(self) -> None:
        assert normalize_id("oilO") == "0110"
