"""results の flat 規約 (dict 禁止 / list 上限 / size guard) のテスト。

方針 (前 PR の議論):
- results は scalar / (値, 単位) tuple / 同単位 list (≤ 32) のみ受け付ける
- dict は ValidationError (LLM 解析・検索・散布図の一貫性のため)
- 1 key 100 KB / 合計 500 KB 超で ValidationError (Firestore 1 MB 事故防止)
- 拒否時は __setitem__ の状態が rollback される
- 既存 record の dict は読み込み (_load) では通る (graceful)
"""

from __future__ import annotations

import pytest

from labvault.core.exceptions import ValidationError
from labvault.core.lab import Lab


class TestDictBanned:
    """dict は results に入れられない。"""

    def test_plain_dict_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="dict は入れられません"):
            rec.results["fit"] = {"a": 2.873, "b": 0.001}

    def test_dict_in_tuple_first_raises(self, lab: Lab) -> None:
        """tuple 記法でも (値=dict, 単位) は禁止 (値部分の検証は同じ)。"""
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="dict は入れられません"):
            rec.results["fit"] = ({"a": 2.873}, "Å")

    def test_empty_dict_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="dict は入れられません"):
            rec.results["x"] = {}

    def test_rollback_on_dict_reject(self, lab: Lab) -> None:
        """dict 拒否時、既存 results が破壊されない。"""
        rec = lab.new("test")
        rec.results["peak"] = (0.97, "V")
        with pytest.raises(ValidationError):
            rec.results["fit"] = {"a": 1}
        assert dict(rec.results.items()) == {"peak": 0.97}
        assert "fit" not in rec.results


class TestListLimit:
    """同単位 list は要素数 32 以下。"""

    def test_short_list_ok(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["peaks"] = ([12.5, 25.0, 37.5], "deg")
        assert list(rec.results["peaks"]) == [12.5, 25.0, 37.5]
        assert rec._result_units["peaks"] == "deg"

    def test_list_at_limit_ok(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["xs"] = (list(range(32)), "deg")
        assert len(rec.results["xs"]) == 32

    def test_list_over_limit_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="list 要素数 33"):
            rec.results["xs"] = (list(range(33)), "deg")

    def test_bare_list_over_limit_raises(self, lab: Lab) -> None:
        """tuple 化していない裸の list も同じ制約。"""
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="list 要素数"):
            rec.results["xs"] = list(range(100))

    def test_rollback_on_list_reject(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["peak"] = (0.97, "V")
        with pytest.raises(ValidationError):
            rec.results["xs"] = list(range(100))
        assert "xs" not in rec.results
        assert rec.results["peak"] == 0.97


class TestSizeGuards:
    """1 値 100 KB / 合計 500 KB のサイズ上限。"""

    def test_large_str_value_raises(self, lab: Lab) -> None:
        rec = lab.new("test")
        big = "x" * (110 * 1024)  # 110 KB
        with pytest.raises(ValidationError, match="値サイズ"):
            rec.results["blob"] = big

    def test_total_size_guard(self, lab: Lab) -> None:
        """small key を積み上げて合計上限を超えると拒否。"""
        rec = lab.new("test")
        # 各 90 KB の str を 6 つ → 合計 540 KB > 500 KB
        chunk = "x" * (90 * 1024)
        rec.results["k1"] = chunk
        rec.results["k2"] = chunk
        rec.results["k3"] = chunk
        rec.results["k4"] = chunk
        rec.results["k5"] = chunk
        with pytest.raises(ValidationError, match="合計サイズ"):
            rec.results["k6"] = chunk
        # 拒否したものは入っていない
        assert "k6" not in rec.results
        # 既存は残っている
        assert "k1" in rec.results


class TestStillWorks:
    """規約導入後も既存の正規パターンは全部通ること。"""

    def test_scalar(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["peak"] = 0.97
        assert rec.results["peak"] == 0.97

    def test_scalar_with_unit(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["peak"] = (0.97, "V")
        assert rec.results["peak"] == 0.97
        assert rec._result_units["peak"] == "V"

    def test_scalar_with_unit_and_desc(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["peak"] = (0.97, "V", "出力電圧のピーク")
        assert rec.results["peak"] == 0.97
        assert rec._result_units["peak"] == "V"
        assert rec._result_descriptions["peak"] == "出力電圧のピーク"

    def test_short_list_with_unit(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["peaks_2theta"] = ([12.5, 25.0], "deg")
        assert rec.results["peaks_2theta"] == [12.5, 25.0]
        assert rec._result_units["peaks_2theta"] == "deg"

    def test_str_value(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["phase"] = "BCC"
        assert rec.results["phase"] == "BCC"

    def test_bool_value(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["converged"] = True
        assert rec.results["converged"] is True

    def test_none_value(self, lab: Lab) -> None:
        rec = lab.new("test")
        rec.results["maybe"] = None
        assert rec.results["maybe"] is None


class TestExistingDictRecordsLoadGracefully:
    """既存 Firestore record に dict が入っている場合、load は通る (read 互換)。

    新規書き込みのみ規約に従う。古いデータの読み出しは破壊しない。
    """

    def test_load_existing_dict_via_underscore_load(self, lab: Lab) -> None:
        rec = lab.new("test")
        # _load は永続化からの復元経路 (__setitem__ を経由しない)
        legacy = {
            "fit": {"a": 2.873, "b": 0.001, "chi2": 0.42},
            "peak": 0.97,
        }
        rec.results._load(legacy)
        assert rec.results["fit"] == {"a": 2.873, "b": 0.001, "chi2": 0.42}
        assert rec.results["peak"] == 0.97

    def test_overwrite_existing_dict_with_valid_value_ok(self, lab: Lab) -> None:
        """既存 dict があっても、上書きは正規値ならば成功。"""
        rec = lab.new("test")
        rec.results._load({"fit": {"a": 1.0}, "peak": 0.5})
        # 同じ key に dict 以外を入れるのは OK
        rec.results["fit"] = (2.5, "Å", "lattice constant a")
        assert rec.results["fit"] == 2.5

    def test_overwrite_with_dict_still_raises(self, lab: Lab) -> None:
        """既存 dict があっても、新規 dict 代入は拒否。"""
        rec = lab.new("test")
        rec.results._load({"fit": {"a": 1.0}})
        with pytest.raises(ValidationError):
            rec.results["fit"] = {"a": 2.0}


class TestErrorMessage:
    """エラーメッセージが行動を誘導する内容になっている。"""

    def test_dict_message_mentions_add_object(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="add_object"):
            rec.results["fit"] = {"a": 1}

    def test_dict_message_mentions_flat_expansion(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="flat"):
            rec.results["fit"] = {"a": 1}

    def test_list_message_mentions_add_object(self, lab: Lab) -> None:
        rec = lab.new("test")
        with pytest.raises(ValidationError, match="add_object"):
            rec.results["xs"] = list(range(100))
