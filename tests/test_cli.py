from __future__ import annotations

from typer.testing import CliRunner

from manuallabor.cli import app

runner = CliRunner()


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_check_not_implemented_exits_two() -> None:
    result = runner.invoke(app, ["check", "x"])
    assert result.exit_code == 2
