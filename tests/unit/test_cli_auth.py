"""`labvault auth set-token` / `labvault auth status` の挙動テスト。

backend への verify HTTP は monkeypatch で stub する。実 backend は触らない。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from labvault.cli.main import cli


@pytest.fixture()
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """HOME を tmp_path にすり替えて副作用を閉じ込める。"""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    # Path.home() は HOME を見るので effective
    return tmp_path


@pytest.fixture()
def stub_verify_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "labvault.cli.main._verify_token_against_backend",
        lambda _t, _u: (
            True,
            "verified: alice@example.com (teams: konishi-lab)",
            "alice@example.com",
        ),
    )


@pytest.fixture()
def stub_verify_ok_no_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """検証は通るが email が空 (古い backend / 想定外応答) のシナリオ。"""
    monkeypatch.setattr(
        "labvault.cli.main._verify_token_against_backend",
        lambda _t, _u: (True, "verified: ? (teams: konishi-lab)", ""),
    )


@pytest.fixture()
def stub_verify_ng(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "labvault.cli.main._verify_token_against_backend",
        lambda _t, _u: (False, "HTTP 401: Unauthorized", ""),
    )


def _run(args: list[str], input_: str | None = None) -> tuple[int, str]:
    runner = CliRunner()
    result = runner.invoke(cli, args, input=input_)
    return result.exit_code, result.output


# ----------------------------------------------------------------------
# set-token: 入力経路
# ----------------------------------------------------------------------


def test_set_token_with_flag(home: Path, stub_verify_ok: None) -> None:
    code, out = _run(["auth", "set-token", "--token", "lv_test123", "--no-verify"])
    assert code == 0, out
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_TOKEN=lv_test123" in creds
    assert "LABVAULT_PLATFORM_URL=https://labvault-api-" in creds
    assert "LABVAULT_TEAM=konishi-lab" in creds


def test_set_token_stdin(home: Path) -> None:
    code, out = _run(
        ["auth", "set-token", "--token-stdin", "--no-verify"],
        input_="lv_fromstdin\n",
    )
    assert code == 0, out
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_TOKEN=lv_fromstdin" in creds


def test_set_token_prompt(home: Path) -> None:
    """--token も --token-stdin も無いと getpass プロンプトで受ける。
    CliRunner は input でその stdin を流せる。"""
    code, out = _run(["auth", "set-token", "--no-verify"], input_="lv_prompted\n")
    assert code == 0, out
    assert (
        "LABVAULT_TOKEN=lv_prompted" in (home / ".labvault" / "credentials").read_text()
    )


# ----------------------------------------------------------------------
# 排他 / バリデーション
# ----------------------------------------------------------------------


def test_set_token_and_stdin_exclusive(home: Path) -> None:
    code, out = _run(
        ["auth", "set-token", "--token", "lv_x", "--token-stdin", "--no-verify"],
        input_="lv_y\n",
    )
    assert code != 0
    assert "同時指定不可" in out


def test_set_token_requires_lv_prefix(home: Path) -> None:
    code, out = _run(["auth", "set-token", "--token", "wrongprefix", "--no-verify"])
    assert code != 0
    assert "lv_" in out


def test_set_token_empty_input(home: Path) -> None:
    code, out = _run(["auth", "set-token", "--token-stdin", "--no-verify"], input_="\n")
    assert code != 0
    assert "empty" in out


# ----------------------------------------------------------------------
# 上書き保護
# ----------------------------------------------------------------------


def test_set_token_refuses_overwrite(home: Path, stub_verify_ok: None) -> None:
    creds_path = home / ".labvault" / "credentials"
    creds_path.parent.mkdir()
    creds_path.write_text("LABVAULT_TOKEN=lv_existing\n")
    code, out = _run(["auth", "set-token", "--token", "lv_new", "--no-verify"])
    assert code != 0
    assert "already exists" in out
    # 既存ファイルは触らない
    assert "lv_existing" in creds_path.read_text()


def test_set_token_force_overwrites(home: Path, stub_verify_ok: None) -> None:
    creds_path = home / ".labvault" / "credentials"
    creds_path.parent.mkdir()
    creds_path.write_text("LABVAULT_TOKEN=lv_existing\n")
    code, out = _run(
        ["auth", "set-token", "--token", "lv_new", "--no-verify", "--force"]
    )
    assert code == 0, out
    assert "LABVAULT_TOKEN=lv_new" in creds_path.read_text()


# ----------------------------------------------------------------------
# 検証 (verify)
# ----------------------------------------------------------------------


def test_set_token_verify_blocks_write_on_failure(
    home: Path, stub_verify_ng: None
) -> None:
    code, out = _run(["auth", "set-token", "--token", "lv_bad"])
    assert code != 0
    assert "verification failed" in out
    # 失敗時はファイルが作られない
    assert not (home / ".labvault" / "credentials").exists()


def test_set_token_no_verify_skips_check(home: Path) -> None:
    code, out = _run(["auth", "set-token", "--token", "lv_xx", "--no-verify"])
    assert code == 0, out
    assert (home / ".labvault" / "credentials").exists()


# ----------------------------------------------------------------------
# パーミッション (POSIX のみ)
# ----------------------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission check")
def test_set_token_sets_mode_600_on_posix(home: Path) -> None:
    _run(["auth", "set-token", "--token", "lv_abc", "--no-verify"])
    creds = home / ".labvault" / "credentials"
    assert creds.exists()
    assert oct(creds.stat().st_mode & 0o777) == "0o600"


# ----------------------------------------------------------------------
# user / team / platform_url オプション
# ----------------------------------------------------------------------


def test_set_token_includes_optional_user(home: Path) -> None:
    _run(
        [
            "auth",
            "set-token",
            "--token",
            "lv_xx",
            "--no-verify",
            "--user",
            "instrument-xrd-1",
        ]
    )
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_USER=instrument-xrd-1" in creds


def test_set_token_default_user_from_verified_email(
    home: Path, stub_verify_ok: None
) -> None:
    """`--user` 未指定 + verify 成功 → backend が返した email が default。"""
    code, out = _run(["auth", "set-token", "--token", "lv_xx"])
    assert code == 0, out
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_USER=alice@example.com" in creds
    # 注釈メッセージが出ている
    assert "PAT 発行者を default" in out
    assert "--user instrument-xrd-1" in out


def test_set_token_explicit_user_overrides_email(
    home: Path, stub_verify_ok: None
) -> None:
    """`--user` 明示 → backend の email より優先。装置 PC 用途。"""
    code, out = _run(
        [
            "auth",
            "set-token",
            "--token",
            "lv_xx",
            "--user",
            "instrument-xrd-1",
        ]
    )
    assert code == 0, out
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_USER=instrument-xrd-1" in creds
    assert "alice@example.com" not in creds
    # 明示時は注釈を出さない
    assert "PAT 発行者を default" not in out


def test_set_token_no_user_when_no_verify(home: Path) -> None:
    """`--no-verify` で email が取れないと、--user 未指定なら LABVAULT_USER を書かない。"""
    code, out = _run(["auth", "set-token", "--token", "lv_xx", "--no-verify"])
    assert code == 0, out
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_USER" not in creds


def test_set_token_no_user_when_verify_returns_empty_email(
    home: Path, stub_verify_ok_no_email: None
) -> None:
    """verify 成功でも email が空なら LABVAULT_USER を書かない。"""
    code, out = _run(["auth", "set-token", "--token", "lv_xx"])
    assert code == 0, out
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_USER" not in creds


def test_set_token_custom_team_and_url(home: Path) -> None:
    _run(
        [
            "auth",
            "set-token",
            "--token",
            "lv_xx",
            "--no-verify",
            "--team",
            "other-lab",
            "--platform-url",
            "https://custom.example.com",
        ]
    )
    creds = (home / ".labvault" / "credentials").read_text()
    assert "LABVAULT_TEAM=other-lab" in creds
    assert "LABVAULT_PLATFORM_URL=https://custom.example.com" in creds


# ----------------------------------------------------------------------
# status
# ----------------------------------------------------------------------


def test_auth_status_when_unset(home: Path) -> None:
    code, out = _run(["auth", "status"])
    assert code == 0
    assert "not present" in out


def test_auth_status_masks_token(home: Path) -> None:
    # token をセット → status で末尾は伏字
    _run(["auth", "set-token", "--token", "lv_abcdef1234567890", "--no-verify"])
    code, out = _run(["auth", "status"])
    assert code == 0
    # 末尾の sensitive 部分は出さない (先頭 8 文字 + ...)
    assert "lv_abcde" in out
    assert "1234567890" not in out
