"""`labvault doctor` の「次のステップ」表示 + PAT モード注釈テスト。"""

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


def test_doctor_no_env_runs_with_builtin_defaults(clean_env: None) -> None:
    """env も .env も無い状態でも、Settings の default 値で ADC モード相当
    として動く。GCP project / nextcloud / platform URL は default で
    埋まっているので「認証ゼロ」hint は出さない。"""
    out = _run()
    assert "次のステップ:" in out
    # default 値が入っている → 認証セットアップ案内は不要
    assert "推奨は ADC" not in out
    # 代わりに team / user が空なので、その個別 hint は出る
    assert "team が未設定" in out
    assert "user が未設定" in out


def test_doctor_hints_missing_team(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "team が未設定" in out


def test_doctor_hints_missing_user(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "user が未設定" in out


def test_doctor_adc_only_shows_no_auth_hint(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "推奨は ADC" not in out


def test_doctor_pat_mode_normal(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PAT 設定済 + default の platform_url で PAT モードが成立する。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_TOKEN", "lv_test")
    out = _run()
    assert "PAT mode" in out
    # 認証完備なので auth set-token --force 案内は出ない
    assert "labvault auth set-token --force" not in out


def test_doctor_mixed_pat_and_gcp_warns(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_doctor_nextcloud_default_avoids_inmemory_warning(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """default で nextcloud_url が入っているので InMemory 警告は出ない。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    out = _run()
    assert "InMemory フォールバック" not in out


def test_doctor_legend_still_present(clean_env: None) -> None:
    out = _run()
    assert "凡例:" in out
    assert "[OK]" in out and "[--]" in out and "[!!]" in out


# ----------------------------------------------------------------------
# PAT モード注釈
# ----------------------------------------------------------------------


def test_doctor_pat_mode_annotates_unused_fields(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PAT モード時、GCP project 行に `(PAT モードでは未使用)` 注釈が付く。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice@example.com")
    monkeypatch.setenv("LABVAULT_TOKEN", "lv_test")
    out = _run()
    # default で gcp_project は klab-laser-process。PAT モード時は
    # 注釈付きで [OK] 表示される (default 値はそのまま見せる)。
    assert "GCP project: klab-laser-process (PAT モードでは未使用)" in out
    assert "PAT mode" in out


def test_doctor_adc_mode_no_pat_note(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADC モードでは PAT モード注釈は出ない。"""
    monkeypatch.setenv("LABVAULT_TEAM", "konishi-lab")
    monkeypatch.setenv("LABVAULT_USER", "alice")
    monkeypatch.setenv("LABVAULT_GCP_PROJECT", "klab-laser-process")
    out = _run()
    assert "PAT モードでは未使用" not in out
