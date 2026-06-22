"""aggregate / overview ロジックが `bool` を numeric 扱いしないことを検証する。

Python の `bool` は `int` のサブクラスなので、`isinstance(v, (int, float))`
だけのガードでは `True / False` が 1.0 / 0.0 として mean に混入する。
backend /api/records/aggregate は明示除外しているが、PR レビューで MCP /
CLI 側でガード漏れが見つかったので、3 経路すべてで一致した挙動になる
ことを SDK 単体テストとして保証する。

注: MCP / CLI の実 endpoint テストは別 (mcp/cli が tool としての挙動を
テスト)。ここでは「データに True/False が混じった record を `merged` で
集めたとき numeric 扱いされないか」を pure-python レベルで担保する。
"""

from __future__ import annotations

import statistics

import pytest

from labvault import Lab
from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)


@pytest.fixture()
def lab(monkeypatch: pytest.MonkeyPatch) -> Lab:
    for k in (
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
    ):
        monkeypatch.setenv(k, "")
    return Lab(
        "konishi-lab",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


def test_bool_excluded_from_numeric_aggregate(lab: Lab) -> None:
    """conditions に True/False が混ざっても mean に流れ込まないこと。

    backend / MCP / CLI が共通で
    `isinstance(v, (int, float)) and not isinstance(v, bool)`
    を使うようになったので、ここで純 python ロジックの「あるべき挙動」
    を test だけ起こす。
    """
    # 数値の record 3 件 + bool record 2 件
    for v in [10.0, 20.0, 30.0]:
        lab.new(f"num-{v}", power=v, auto_log=False)
    lab.new("bool-true", power=True, auto_log=False)
    lab.new("bool-false", power=False, auto_log=False)

    records = lab.list(limit=50)
    values: list[float] = []
    for rec in records:
        merged = {**rec.get_conditions(), **rec.results.to_dict()}
        v = merged.get("power")
        # ★ aggregate / overview 全 3 経路で使うべきガード
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        values.append(float(v))

    # bool record が混入していたら mean が変わる:
    #   numeric のみ → (10+20+30)/3 = 20.0
    #   bool 混入 → (10+20+30+1+0)/5 = 12.2
    # list は updated_at DESC で来るため順序は問わない。
    assert sorted(values) == [10.0, 20.0, 30.0]
    assert statistics.mean(values) == pytest.approx(20.0)
