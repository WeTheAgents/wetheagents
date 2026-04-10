from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_task_format import TASK_BODY_TEMPLATE, validate_detailed
from wea_cli import cli

ROOT = Path(__file__).resolve().parents[1]


def test_parser_supports_task_lint_and_template_subcommands() -> None:
    parser = cli.build_parser()

    lint_args = parser.parse_args(["task", "lint", "draft.md", "--json"])
    template_args = parser.parse_args(["task", "template"])

    assert lint_args.command == "task"
    assert lint_args.task_command == "lint"
    assert lint_args.file == "draft.md"
    assert lint_args.json is True
    assert lint_args._handler is cli.cmd_task_lint

    assert template_args.command == "task"
    assert template_args.task_command == "template"
    assert template_args._handler is cli.cmd_task_template


def test_task_template_is_valid(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.cmd_task_template(argparse.Namespace())

    assert rc == cli.EXIT_OK
    body = capsys.readouterr().out
    assert validate_detailed(body) == []


def test_cmd_task_lint_reports_human_errors_with_line_numbers(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = temp_repo / "draft.md"
    draft.write_text(
        """### Your Agent ID

agent0@system

### Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

abc
""",
        encoding="utf-8",
    )

    rc = cli.cmd_task_lint(argparse.Namespace(file=str(draft), json=False))

    assert rc == cli.EXIT_DOMAIN_ERROR
    out = capsys.readouterr().out
    assert "Task body format: FAIL (1 issue(s))" in out
    assert f"{draft}:11: Reward must be an integer, got `abc`." in out


def test_cmd_task_lint_json_output_reports_machine_readable_errors(
    temp_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = temp_repo / "draft.md"
    draft.write_text(
        """### Your Agent ID

agent0@system

## Reward Type

Winner Take All (single winner, full budget)

### Reward (WEA)

5
""",
        encoding="utf-8",
    )

    rc = cli.cmd_task_lint(argparse.Namespace(file=str(draft), json=True))

    assert rc == cli.EXIT_DOMAIN_ERROR
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["path"] == str(draft)
    assert payload["errors"] == [
        {
            "line": 5,
            "message": (
                "Field **Reward Type** uses `##` header — must be `###` "
                "(GitHub Forms template format). Also ensure a blank line between header and value."
            ),
        }
    ]


def test_cmd_task_lint_reads_dev_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(TASK_BODY_TEMPLATE))

    rc = cli.cmd_task_lint(argparse.Namespace(file="/dev/stdin", json=False))

    assert rc == cli.EXIT_OK
    assert "/dev/stdin: OK" in capsys.readouterr().out


def test_cmd_task_lint_missing_file_returns_runtime_error(
    capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cli.cmd_task_lint(argparse.Namespace(file="missing-task.md", json=False))

    assert rc == cli.EXIT_RUNTIME_ERROR
    assert "Task body file not found" in capsys.readouterr().out


def test_cli_task_template_round_trips_into_task_lint() -> None:
    template = subprocess.run(
        [sys.executable, "src/wea_cli/cli.py", "--root", ".", "task", "template"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert template.returncode == 0

    lint = subprocess.run(
        [sys.executable, "src/wea_cli/cli.py", "--root", ".", "task", "lint", "/dev/stdin"],
        cwd=ROOT,
        input=template.stdout,
        capture_output=True,
        text=True,
        check=False,
    )

    assert lint.returncode == 0
    assert "/dev/stdin: OK" in lint.stdout
