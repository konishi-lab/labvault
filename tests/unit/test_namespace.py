"""namespace キャプチャと差分検出のテスト。"""

from __future__ import annotations

from labvault.tracking.namespace import (
    REDACTED,
    capture_namespace,
    diff_namespaces,
)


class TestCapture:
    def test_basic_variables(self):
        ns = {"x": 1, "y": "hello", "z": [1, 2, 3]}
        result = capture_namespace(ns)
        assert "x" in result
        assert "y" in result
        assert "z" in result
        # 各エントリは (id, digest) のタプル
        for _, (obj_id, digest) in result.items():
            assert isinstance(obj_id, int)
            assert isinstance(digest, str)

    def test_underscore_excluded(self):
        ns = {"x": 1, "_private": 2, "__dunder": 3}
        result = capture_namespace(ns)
        assert "x" in result
        assert "_private" not in result
        assert "__dunder" not in result

    def test_module_excluded(self):
        import os

        ns = {"x": 1, "os": os}
        result = capture_namespace(ns)
        assert "x" in result
        assert "os" not in result

    def test_function_excluded(self):
        def my_func():
            pass

        ns = {"x": 1, "my_func": my_func}
        result = capture_namespace(ns)
        assert "x" in result
        assert "my_func" not in result

    def test_class_excluded(self):
        ns = {"x": 1, "MyClass": type("MyClass", (), {})}
        result = capture_namespace(ns)
        assert "x" in result
        assert "MyClass" not in result

    def test_ipython_vars_excluded(self):
        ns = {"x": 1, "In": [], "Out": {}, "get_ipython": lambda: None}
        result = capture_namespace(ns)
        assert "x" in result
        assert "In" not in result
        assert "Out" not in result
        assert "get_ipython" not in result

    def test_sensitive_masked(self):
        ns = {"api_key": "sk-1234", "password": "secret123", "x": 1}
        result = capture_namespace(ns)
        assert result["api_key"][1] == REDACTED
        assert result["password"][1] == REDACTED
        assert result["x"][1] != REDACTED

    def test_sensitive_case_insensitive(self):
        ns = {"API_KEY": "val", "My_Secret": "val"}
        result = capture_namespace(ns)
        assert result["API_KEY"][1] == REDACTED
        assert result["My_Secret"][1] == REDACTED

    def test_method_excluded(self):
        class Obj:
            def method(self):
                pass

        ns = {"x": 1, "m": Obj().method}
        result = capture_namespace(ns)
        assert "x" in result
        assert "m" not in result


class TestDiff:
    def test_new_variable(self):
        before: dict[str, tuple[int, str]] = {}
        after = {"x": (100, "abc123")}
        new, changed, deleted = diff_namespaces(before, after)
        assert "x" in new
        assert changed == {}
        assert deleted == []

    def test_deleted_variable(self):
        before = {"x": (100, "abc123")}
        after: dict[str, tuple[int, str]] = {}
        new, changed, deleted = diff_namespaces(before, after)
        assert new == {}
        assert changed == {}
        assert "x" in deleted

    def test_changed_by_reassignment(self):
        """id() が変わった場合 (再代入)."""
        before = {"x": (100, "abc123")}
        after = {"x": (200, "def456")}
        new, changed, deleted = diff_namespaces(before, after)
        assert new == {}
        assert "x" in changed
        assert changed["x"]["before"] == "abc123"
        assert changed["x"]["after"] == "def456"
        assert deleted == []

    def test_changed_in_place(self):
        """id() が同じで digest が変わった場合 (in-place mutation)."""
        before = {"x": (100, "abc123")}
        after = {"x": (100, "xyz789")}
        _new, changed, _deleted = diff_namespaces(before, after)
        assert "x" in changed

    def test_no_change(self):
        before = {"x": (100, "abc123")}
        after = {"x": (100, "abc123")}
        new, changed, deleted = diff_namespaces(before, after)
        assert new == {}
        assert changed == {}
        assert deleted == []

    def test_redacted_skipped(self):
        """REDACTED 変数は差分に含めない。"""
        before = {"api_key": (100, REDACTED)}
        after = {"api_key": (200, REDACTED)}
        new, changed, deleted = diff_namespaces(before, after)
        assert new == {}
        assert changed == {}
        assert deleted == []

    def test_mixed(self):
        before = {"a": (1, "d1"), "b": (2, "d2"), "c": (3, "d3")}
        after = {"a": (1, "d1"), "b": (20, "d20"), "d": (4, "d4")}
        new, changed, deleted = diff_namespaces(before, after)
        assert "d" in new
        assert "b" in changed
        assert "c" in deleted
        assert "a" not in changed
