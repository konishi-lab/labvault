"""_shallow_digest のテスト。"""

from __future__ import annotations

import pytest

from labvault.tracking.digest import _shallow_digest


class TestPrimitives:
    def test_int(self):
        d = _shallow_digest(42)
        assert isinstance(d, str)
        assert len(d) == 16

    def test_float(self):
        assert _shallow_digest(3.14) == _shallow_digest(3.14)
        assert _shallow_digest(3.14) != _shallow_digest(2.71)

    def test_str(self):
        assert _shallow_digest("hello") == _shallow_digest("hello")
        assert _shallow_digest("hello") != _shallow_digest("world")

    def test_none(self):
        d = _shallow_digest(None)
        assert isinstance(d, str)

    def test_bool(self):
        assert _shallow_digest(True) != _shallow_digest(False)


class TestContainers:
    def test_dict(self):
        d1 = _shallow_digest({"a": 1, "b": 2})
        d2 = _shallow_digest({"a": 1, "b": 2})
        assert d1 == d2

    def test_dict_different(self):
        d1 = _shallow_digest({"a": 1})
        d2 = _shallow_digest({"a": 1, "b": 2})
        assert d1 != d2

    def test_list(self):
        d1 = _shallow_digest([1, 2, 3])
        d2 = _shallow_digest([1, 2, 3])
        assert d1 == d2

    def test_list_different(self):
        assert _shallow_digest([1, 2]) != _shallow_digest([1, 2, 3])

    def test_set(self):
        d = _shallow_digest({1, 2, 3})
        assert isinstance(d, str)
        assert len(d) == 16

    def test_empty_containers(self):
        assert isinstance(_shallow_digest({}), str)
        assert isinstance(_shallow_digest([]), str)
        assert isinstance(_shallow_digest(set()), str)


class TestFallback:
    def test_unknown_object(self):
        class Foo:
            pass

        d = _shallow_digest(Foo())
        assert isinstance(d, str)
        assert len(d) == 16


class TestNumpy:
    @pytest.fixture(autouse=True)
    def _skip_no_numpy(self):
        pytest.importorskip("numpy")

    def test_ndarray(self):
        import numpy as np

        arr = np.array([1.0, 2.0, 3.0])
        d = _shallow_digest(arr)
        assert isinstance(d, str)
        assert len(d) == 16

    def test_ndarray_same(self):
        import numpy as np

        a = np.zeros((10, 10))
        b = np.zeros((10, 10))
        assert _shallow_digest(a) == _shallow_digest(b)

    def test_ndarray_different_shape(self):
        import numpy as np

        a = np.zeros((10, 10))
        b = np.zeros((5, 20))
        assert _shallow_digest(a) != _shallow_digest(b)


class TestPandas:
    @pytest.fixture(autouse=True)
    def _skip_no_pandas(self):
        pytest.importorskip("pandas")

    def test_dataframe(self):
        import pandas as pd

        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        d = _shallow_digest(df)
        assert isinstance(d, str)
        assert len(d) == 16

    def test_series(self):
        import pandas as pd

        s = pd.Series([1, 2, 3], name="x")
        d = _shallow_digest(s)
        assert isinstance(d, str)
        assert len(d) == 16
