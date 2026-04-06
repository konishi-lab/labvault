"""CLI のテスト。"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from labvault.backends.memory import (
    InMemoryMetadataBackend,
    InMemorySearchBackend,
    InMemoryStorageBackend,
)
from labvault.cli.main import cli
from labvault.core.lab import Lab


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def shared_lab():
    """テスト間で共有する Lab インスタンス。"""
    return Lab(
        "test-cli",
        user="tester",
        metadata_backend=InMemoryMetadataBackend(),
        storage_backend=InMemoryStorageBackend(),
        search_backend=InMemorySearchBackend(),
    )


@pytest.fixture()
def _patch_lab(shared_lab):
    """_get_lab を shared_lab に差し替える。"""
    with patch("labvault.cli.main._get_lab", return_value=shared_lab):
        yield


class TestHelp:
    def test_main_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "labvault" in result.output

    def test_new_help(self, runner):
        result = runner.invoke(cli, ["new", "--help"])
        assert result.exit_code == 0


@pytest.mark.usefixtures("_patch_lab")
class TestNew:
    def test_new_creates_record(self, runner):
        result = runner.invoke(cli, ["new", "XRD測定"])
        assert result.exit_code == 0
        assert "XRD測定" in result.output
        parts = result.output.strip().split()
        assert len(parts[0]) == 4

    def test_new_with_tags(self, runner):
        result = runner.invoke(cli, ["new", "test", "-T", "XRD", "-T", "Fe-Cr"])
        assert result.exit_code == 0

    def test_new_with_type(self, runner):
        result = runner.invoke(cli, ["new", "sample", "-t", "sample"])
        assert result.exit_code == 0


@pytest.mark.usefixtures("_patch_lab")
class TestList:
    def test_list_empty(self, runner):
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0

    def test_list_after_new(self, runner):
        runner.invoke(cli, ["new", "list-exp1"])
        runner.invoke(cli, ["new", "list-exp2"])
        result = runner.invoke(cli, ["list"])
        assert result.exit_code == 0
        assert "list-exp1" in result.output
        assert "list-exp2" in result.output


@pytest.mark.usefixtures("_patch_lab")
class TestShow:
    def test_show_record(self, runner):
        new_result = runner.invoke(cli, ["new", "Show Test", "-T", "XRD"])
        record_id = new_result.output.strip().split()[0]

        result = runner.invoke(cli, ["show", record_id])
        assert result.exit_code == 0
        assert "Show Test" in result.output
        assert record_id in result.output
        assert "XRD" in result.output

    def test_show_not_found(self, runner):
        result = runner.invoke(cli, ["show", "ZZZZ"])
        assert result.exit_code != 0


@pytest.mark.usefixtures("_patch_lab")
class TestAdd:
    def test_add_file(self, runner, tmp_path):
        new_result = runner.invoke(cli, ["new", "Add Test"])
        record_id = new_result.output.strip().split()[0]

        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")

        result = runner.invoke(cli, ["add", record_id, str(f)])
        assert result.exit_code == 0
        assert "Added" in result.output

    def test_add_multiple_files(self, runner, tmp_path):
        new_result = runner.invoke(cli, ["new", "Multi Add"])
        record_id = new_result.output.strip().split()[0]

        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("a")
        f2.write_text("b")

        result = runner.invoke(cli, ["add", record_id, str(f1), str(f2)])
        assert result.exit_code == 0
        assert result.output.count("Added") == 2


@pytest.mark.usefixtures("_patch_lab")
class TestSearch:
    def test_search_no_results(self, runner):
        result = runner.invoke(cli, ["search", "nonexistent999"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_finds_record(self, runner):
        runner.invoke(cli, ["new", "XRD Fe-Cr search"])
        result = runner.invoke(cli, ["search", "XRD Fe-Cr search"])
        assert result.exit_code == 0
        assert "XRD" in result.output


class TestDoctor:
    def test_doctor_runs(self, runner):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "Python" in result.output
        assert "doctor" in result.output


class TestInit:
    def test_init_creates_config(self, runner, tmp_path):
        config_dir = tmp_path / ".labvault"

        with patch("labvault.cli.main.Path.home", return_value=tmp_path):
            result = runner.invoke(
                cli,
                ["init", "--team", "my-lab", "--user", "alice"],
            )

        assert result.exit_code == 0
        config_path = config_dir / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert 'team = "my-lab"' in content
        assert 'user = "alice"' in content
