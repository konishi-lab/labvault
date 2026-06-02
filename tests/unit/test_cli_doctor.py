"""`labvault doctor` の「次のステップ」表示テスト。

Settings は env から読むので、各テストで `monkeypatch.delenv` / `setenv` で
状態をシミュレートする。HOME も tmp_path にすり替えて、ローカル
`~/.labvault/credentials` の影響を遮断する。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from labvault.cli.main import cli


@pytest.fixture()
def clean_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """全 LABVAULT_* env と HOME を初期化する。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for key in [
        "LABVAULT_TEAM",
        "LABVAULT_USER",
        "LABVAULT_GCP_PROJECT",
        "LABVAULT_FIRESTORE_DATABASE",
        "LABVAULT_NEXTCLOUD_URL",
        "LABVAULT_NEXTCLOUD_USER",
        "LABVAULT_NEXTCLOUD_PASSWORD",
        "LABVAULT_NEXTCLOUD_GROUP_FOLDER",
        "LABVAULT_PLATFORM_URL",
        "LABVAULT_TOKEN",
    ]:
        monkeypatch.delenv(key, raising=False)


def _run() -> str:
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    return result.output


def test_doctor_hints_no_auth_recommends_adc(clean_env: None) -> None:
    """team / user / gcp / pat すべて未設定 → ADC 推奨と PAT の両案内が出る。"""
    out = _run()
    assert "次のステップ:" in out
    assert "推奨は ADC" in out
    assert "gcloud auth application-default login" in out
    assert "LABVAULT_GCP_PROJECT" in out
    assert "labvault auth set-token" in out


def test_doctor_hints_missing_team(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """team だけ無い → team の hint が出る。"""
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "team が未設定" in out
    assert "LABVAULT_TEAM=" in out


def test_doctor_hints_missing_user(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "user が未設定" in out
    assert "LABVAULT_USER" in out


def test_doctor_adc_only_shows_no_auth_hint(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADC モード (gcp あり、PAT なし) は推奨パスなので auth 関連の hint なし。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    # 認証関連の hint は出ない
    assert "推奨は ADC" not in out
    assert "labvault auth set-token --token-stdin" not in out


def test_doctor_pat_without_platform_url_hints(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_TOKEN", "lv_test")
    out = _run()
    assert "LABVAULT_PLATFORM_URL" in out
    assert "labvault auth set-token --force" in out


def test_doctor_mixed_pat_and_gcp_warns(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PAT と GCP 両方ある場合は「PAT を外して ADC に寄せる」案内が出る。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    monkeypatch.setenv("LABVAULT_TOKEN", "lv_test")
    monkeypatch.setenv(
        "LABVAULT_PLATFORM_URL",
        "https://labvault-api-355809880738.asia-northeast1.run.app",
    )
    out = _run()
    assert "両方が設定されている" in out
    assert "ADC のみに寄せる" in out


def test_doctor_nextcloud_missing_warns_inmemory(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADC モードで Nextcloud も platform URL も無い → ファイル消失警告。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "InMemory フォールバック" in out


def test_doctor_legend_still_present(clean_env: None) -> None:
    """凡例が末尾に残っている (PR #26 で導入したもの)。"""
    out = _run()
    assert "凡例:" in out
    assert "[OK]" in out and "[--]" in out and "[!!]" in out
