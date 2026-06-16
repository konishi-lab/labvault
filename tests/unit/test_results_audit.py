"""results_audit.scan_record の各違反パターンの検証。

CLI 用 (`labvault check-results`) のロジックを純粋関数として切り出してある。
ここではその関数だけテストし、CLI 統合は別途 smoke test。
"""

from __future__ import annotations

from labvault.core.results_audit import (
    MAX_LIST_LEN,
    MAX_TOTAL_BYTES,
    MAX_VALUE_BYTES,
    scan_record,
    summarize,
)


def _record(results: dict, rid: str = "TEST01") -> dict:
    """results 部分だけを渡して Firestore 風 raw doc を作る。"""
    return {
        "id": rid,
        "team": "test-team",
        "title": "test",
        "results": results,
    }


class TestDictDetection:
    def test_dict_value_detected(self) -> None:
        v = scan_record(_record({"fit": {"a": 1, "b": 2}}))
        assert len(v) == 1
        assert v[0].kind == "dict"
        assert v[0].key == "fit"
        assert v[0].record_id == "TEST01"
        assert "flat 展開" in v[0].detail or "add_object" in v[0].detail

    def test_nested_dict_value_detected(self) -> None:
        v = scan_record(_record({"x": {"nested": {"deep": 1}}}))
        assert len(v) == 1
        assert v[0].kind == "dict"

    def test_scalar_value_not_flagged(self) -> None:
        v = scan_record(_record({"peak": 0.97, "phase": "BCC"}))
        assert v == []

    def test_preview_truncates(self) -> None:
        long = {"a" * 50: 1, "b" * 50: 2}
        v = scan_record(_record({"big": long}))
        assert v[0].value_preview.endswith("...")
        assert len(v[0].value_preview) <= 84


class TestLongList:
    def test_list_at_limit_not_flagged(self) -> None:
        v = scan_record(_record({"xs": list(range(MAX_LIST_LEN))}))
        # `value_too_large` トリガーも無いはず
        assert v == []

    def test_list_over_limit_flagged(self) -> None:
        v = scan_record(_record({"xs": list(range(MAX_LIST_LEN + 1))}))
        kinds = {x.kind for x in v}
        assert "long_list" in kinds

    def test_short_list_passes(self) -> None:
        v = scan_record(_record({"peaks": [12.5, 25.0]}))
        assert v == []


class TestValueTooLarge:
    def test_large_string_value_flagged(self) -> None:
        big = "x" * (MAX_VALUE_BYTES + 100)
        v = scan_record(_record({"blob": big}))
        assert any(x.kind == "value_too_large" for x in v)

    def test_normal_string_passes(self) -> None:
        v = scan_record(_record({"phase": "BCC"}))
        assert v == []


class TestTotalTooLarge:
    def test_total_exceeded(self) -> None:
        # 1 key 90 KB を 6 つ → 540 KB > 500 KB
        chunk = "x" * (90 * 1024)
        results = {f"k{i}": chunk for i in range(6)}
        v = scan_record(_record(results))
        assert any(x.kind == "total_too_large" for x in v)

    def test_under_total_passes(self) -> None:
        # 80 KB を 3 つ → 240 KB
        chunk = "x" * (80 * 1024)
        results = {f"k{i}": chunk for i in range(3)}
        v = scan_record(_record(results))
        # value_too_large も total_too_large も発火しない
        assert v == []


class TestMixedViolations:
    def test_multiple_violations_listed_separately(self) -> None:
        v = scan_record(
            _record(
                {
                    "fit": {"a": 1},  # dict
                    "xs": list(range(100)),  # long_list
                    "phase": "BCC",  # OK
                }
            )
        )
        kinds = {x.kind for x in v}
        assert "dict" in kinds
        assert "long_list" in kinds
        # 違反 2 件、OK 1 件 → 2
        assert len(v) == 2


class TestEdgeCases:
    def test_no_results_field(self) -> None:
        v = scan_record({"id": "X"})
        assert v == []

    def test_empty_results(self) -> None:
        v = scan_record(_record({}))
        assert v == []

    def test_record_id_falls_back_to_empty(self) -> None:
        v = scan_record({"results": {"fit": {"a": 1}}})
        assert v[0].record_id == ""

    def test_non_dict_results_ignored(self) -> None:
        """results field 自体が壊れている (list 等) ケースは破壊せず empty を返す。"""
        v = scan_record({"id": "X", "results": [1, 2, 3]})
        assert v == []


class TestSummarize:
    def test_summarize_counts_by_kind(self) -> None:
        v = scan_record(
            _record(
                {
                    "a": {"x": 1},
                    "b": {"x": 1},
                    "c": list(range(100)),
                }
            )
        )
        counts = summarize(v)
        assert counts["dict"] == 2
        assert counts["long_list"] == 1

    def test_summarize_empty(self) -> None:
        assert summarize([]) == {}


def test_constants_in_sync_with_results_proxy() -> None:
    """audit の上限値が _ResultsProxy と同期していることを保証。"""
    from labvault.core.record import _ResultsProxy

    assert MAX_LIST_LEN == _ResultsProxy._MAX_LIST_LEN
    assert MAX_VALUE_BYTES == _ResultsProxy._MAX_VALUE_BYTES
    assert MAX_TOTAL_BYTES == _ResultsProxy._MAX_TOTAL_BYTES
