"""scripts/idx_backfill.py のユニットテスト。

InMemory backend で record を作り、`idx_*` を意図的にクリアした上で
backfill を走らせて挙動を検証する。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.core.lab import Lab

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "idx_backfill.py"


@pytest.fixture()
def backfill_mod():
    """scripts/idx_backfill.py を import する (sys.path に scripts/ は無いので)。"""
    spec = importlib.util.spec_from_file_location("idx_backfill_mod", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["idx_backfill_mod"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def lab() -> Lab:
    return Lab(
        "test-team",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


def _strip_idx(lab: Lab) -> None:
    """全 record の idx_* を消して「過去 record」状態をシミュレート。"""
    for raw in lab._metadata._records[lab._team].values():
        for key in list(raw.keys()):
            if key.startswith("idx_"):
                del raw[key]


def test_backfill_apply_writes_idx_fields(lab: Lab, backfill_mod) -> None:
    lab.new("a", template="XRD", target="Cu", method="thin_film")
    lab.new("b", template="XRD", target="Mo")
    _strip_idx(lab)
    # 事前確認: idx_* が消えている
    for raw in lab._metadata._records[lab._team].values():
        assert not any(k.startswith("idx_") for k in raw)

    stats = backfill_mod.backfill(lab, apply=True, limit=100)
    assert stats["updated"] == 2
    assert stats["no_template"] == 0
    assert stats["no_change"] == 0

    # 反映されている
    rows = list(lab._metadata._records[lab._team].values())
    targets = {r.get("idx_target") for r in rows}
    assert targets == {"Cu", "Mo"}


def test_backfill_dry_run_does_not_write(lab: Lab, backfill_mod) -> None:
    lab.new("a", template="XRD", target="Cu")
    _strip_idx(lab)

    stats = backfill_mod.backfill(lab, apply=False, limit=100)
    assert stats["updated"] == 1

    # 書き込まれていない
    raw = next(iter(lab._metadata._records[lab._team].values()))
    assert "idx_target" not in raw


def test_backfill_is_idempotent(lab: Lab, backfill_mod) -> None:
    lab.new("a", template="XRD", target="Cu")
    # idx_target は既に正しい状態 → 2 回目以降は no_change
    stats = backfill_mod.backfill(lab, apply=True, limit=100)
    assert stats["updated"] == 0
    assert stats["no_change"] == 1


def test_backfill_skips_no_template_records(lab: Lab, backfill_mod) -> None:
    lab.new("no-tpl")  # template 無し
    lab.new("with-tpl", template="XRD", target="Cu")
    _strip_idx(lab)

    stats = backfill_mod.backfill(lab, apply=True, limit=100)
    assert stats["no_template"] == 1
    assert stats["updated"] == 1


def test_backfill_skips_unset_indexed_keys(lab: Lab, backfill_mod) -> None:
    # XRD の indexed_fields = ["target", "method", "sample_name"] のうち
    # target だけ入力 → idx_target だけ書かれる (idx_method / idx_sample_name
    # は書かない)
    lab.new("partial", template="XRD", target="Mo")
    _strip_idx(lab)

    backfill_mod.backfill(lab, apply=True, limit=100)
    raw = next(iter(lab._metadata._records[lab._team].values()))
    assert raw.get("idx_target") == "Mo"
    assert "idx_method" not in raw
    assert "idx_sample_name" not in raw


def test_backfill_writes_only_diff(lab: Lab, backfill_mod) -> None:
    """既存の idx_* と一致する key は再書き込みしない (write 量最小化)。"""
    lab.new("multi", template="XRD", target="Cu", method="thin_film")
    # idx_method だけ消す (idx_target は正しいまま残す)
    raw = next(iter(lab._metadata._records[lab._team].values()))
    del raw["idx_method"]

    stats = backfill_mod.backfill(lab, apply=True, limit=100)
    assert stats["updated"] == 1
    # 補完されて idx_method=thin_film が入っている
    raw = next(iter(lab._metadata._records[lab._team].values()))
    assert raw["idx_method"] == "thin_film"
    assert raw["idx_target"] == "Cu"
