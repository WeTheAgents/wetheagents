"""Tests for scripts/check_deadline.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_deadline.py"


def run(issues: list[dict], extra_args: list[str] | None = None) -> tuple[int, list[dict]]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(issues, f)
        tmp = f.name
    args = [sys.executable, str(SCRIPT), "--json-file", tmp] + (extra_args or [])
    result = subprocess.run(args, capture_output=True, text=True)
    output = json.loads(result.stdout)
    return result.returncode, output


def make_issue(number: int, title: str, deadline: str | None) -> dict:
    if deadline:
        body = f"### Deadline (optional)\n\n{deadline}\n\n### Next\n\nfoo"
    else:
        body = "### Task Description\n\nNo deadline here."
    return {"number": number, "title": title, "body": body}


def test_no_issues_exit_0():
    code, output = run([])
    assert code == 0
    assert output == []


def test_deadline_tomorrow_exit_0():
    issue = make_issue(1, "Future task", "2026-03-09")  # tomorrow relative to 2026-03-08
    code, output = run([issue], ["--as-of", "2026-03-08"])
    assert code == 0
    assert output == []


def test_deadline_yesterday_exit_1():
    issue = make_issue(2, "Past task", "2026-03-07")  # yesterday relative to 2026-03-08
    code, output = run([issue], ["--as-of", "2026-03-08"])
    assert code == 1
    assert len(output) == 1
    assert output[0]["issue"] == 2
    assert output[0]["days_overdue"] == 1


def test_no_deadline_field_skipped():
    issue = make_issue(3, "No deadline task", None)
    code, output = run([issue], ["--as-of", "2026-03-08"])
    assert code == 0
    assert output == []


def test_as_of_flag_days_overdue_17():
    issue = make_issue(4, "March task", "2026-03-15")
    code, output = run([issue], ["--as-of", "2026-04-01"])
    assert code == 1
    assert len(output) == 1
    assert output[0]["days_overdue"] == 17
    assert output[0]["deadline"] == "2026-03-15"
