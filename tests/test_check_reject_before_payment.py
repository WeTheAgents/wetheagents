#!/usr/bin/env python3
"""Tests for scripts/check_reject_before_payment.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_reject_before_payment import main, run_check

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_reject_before_payment.py"


def _write_history(root: Path, filename: str, events: list[dict[str, object] | str]) -> None:
    lines: list[str] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event)
        else:
            lines.append(json.dumps(event))
    (root / "ledger" / "history" / filename).write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_no_events_pass(temp_repo: Path) -> None:
    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["checks"][0]["violations"] == 0


def test_reject_only_pass(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["checks"][0]["reject_events"] == 1


def test_accept_only_pass(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "accept", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["checks"][0]["accept_events"] == 1


def test_reject_then_accept_same_agent_fails(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    result = _run(temp_repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["violations"] == [
        {
            "issue": 1,
            "agent": "alice@test",
            "event_type": "accept",
            "event_ts": "2026-04-01T10:00:00Z",
            "reject_ts": "2026-04-01T09:00:00Z",
            "reject_file": "2026-04-01.jsonl",
            "reject_line": 1,
            "event_file": "2026-04-01.jsonl",
            "event_line": 2,
        }
    ]


def test_reject_then_accept_different_agent_pass(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 1, "agent": "bob@test", "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_reject_then_payment_same_agent_fails(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "payment", "issue": 1, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["event_type"] == "payment"


def test_accept_then_reject_pass(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "accept", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_multiple_issues_are_independent(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 2, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 1, "agent": "bob@test", "amount": 8, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []


def test_multiple_violations_are_reported(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 1, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert [item["event_type"] for item in report["violations"]] == ["accept", "payment"]


def test_events_are_sorted_across_files_by_timestamp(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-02.jsonl",
        [
            {"type": "accept", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )
    _write_history(
        temp_repo,
        "2026-04-03.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T11:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"


def test_reject_in_later_file_with_earlier_timestamp_still_fails(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-02.jsonl",
        [
            {"type": "payment", "issue": 1, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )
    _write_history(
        temp_repo,
        "2026-04-03.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["event_type"] == "payment"


def test_equal_timestamps_use_line_order(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T10:00:00Z"},
            {"type": "payment", "issue": 1, "agent": "alice@test", "amount": 10, "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["reject_line"] == 1
    assert report["violations"][0]["event_line"] == 2


def test_author_alias_is_accepted_for_relevant_events(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "author": "alice@test", "created_at": "2026-04-01T09:00:00Z"},
            {"type": "payment", "issue": 1, "author": "alice@test", "amount": 10, "started_at": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["agent"] == "alice@test"


def test_ts_alias_is_accepted_for_timestamps(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "ts": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 1, "agent": "alice@test", "ts": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert report["violations"][0]["reject_ts"] == "2026-04-01T09:00:00Z"
    assert report["violations"][0]["event_ts"] == "2026-04-01T10:00:00Z"


def test_invalid_json_returns_fail_report(temp_repo: Path) -> None:
    (temp_repo / "ledger" / "history" / "2026-04-01.jsonl").write_text(
        "{not-json}\n",
        encoding="utf-8",
    )

    result = _run(temp_repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert payload["checks"][0]["status"] == "FAIL"


def test_missing_agent_returns_fail_report(temp_repo: Path) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "timestamp": "2026-04-01T09:00:00Z"},
        ],
    )

    result = _run(temp_repo)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "FAIL"
    assert "missing agent" in payload["checks"][0]["error"]


def test_main_returns_zero_for_clean_repo(temp_repo: Path, capsys) -> None:
    _write_history(
        temp_repo,
        "2026-04-01.jsonl",
        [
            {"type": "reject", "issue": 1, "agent": "alice@test", "timestamp": "2026-04-01T09:00:00Z"},
            {"type": "accept", "issue": 1, "agent": "bob@test", "timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    exit_code = main(["--root", str(temp_repo)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["status"] == "PASS"
