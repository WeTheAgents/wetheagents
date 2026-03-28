from __future__ import annotations

from pathlib import Path

from scripts import check_task_format
from wea_cli import cli

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_imports_scripts_from_current_worktree() -> None:
    assert Path(check_task_format.__file__).resolve().is_relative_to(ROOT)


def test_pytest_imports_wea_cli_from_current_worktree() -> None:
    assert Path(cli.__file__).resolve().is_relative_to(ROOT / "src")
