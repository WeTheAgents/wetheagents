from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.check_issue_ledger_sync import (
    load_ledger_events,
    main,
    parse_github_issues,
    run_checks,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_history(root: Path, *records: dict) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(r) for r in records)
    (history_dir / "events.jsonl").write_text(lines + "\n", encoding="utf-8")


def _gh_json(*issues: dict) -> str:
    """Serialize a list of GitHub issue dicts to JSON string."""
    return json.dumps(list(issues))


def _gh_issue(number: int, *label_names: str) -> dict:
    return {
        "number": number,
        "state": "closed",
        "labels": [{"name": n} for n in label_names],
    }


# ---------------------------------------------------------------------------
# run_checks unit tests (pure logic, no I/O)
# ---------------------------------------------------------------------------

def test_run_checks_all_consistent() -> None:
    """Fully consistent data → no failures and no warnings."""
    checks = run_checks(
        accept_issues={42},
        escrow_issues={42, 99},
        paid_issues={42},
        claimed_not_paid={99},
    )
    for _name, _severity, bad in checks:
        assert bad == [], f"unexpected failures: {bad}"


def test_run_checks_orphan_paid_label() -> None:
    """Issue has 'paid' label but no accept event → ERROR."""
    checks = dict(
        (name, bad)
        for name, _sev, bad in run_checks(
            accept_issues=set(),
            escrow_issues=set(),
            paid_issues={42},
            claimed_not_paid=set(),
        )
    )
    assert 42 in checks["paid label with no accept event"]
    assert checks["accept event with no paid label"] == []


def test_run_checks_orphan_accept_event() -> None:
    """Accept event exists but issue not labeled 'paid' → ERROR."""
    checks = dict(
        (name, bad)
        for name, _sev, bad in run_checks(
            accept_issues={42},
            escrow_issues=set(),
            paid_issues=set(),
            claimed_not_paid=set(),
        )
    )
    assert 42 in checks["accept event with no paid label"]
    assert checks["paid label with no accept event"] == []


def test_run_checks_claimed_no_escrow() -> None:
    """Claimed issue (not paid) with no escrow event → WARN."""
    checks = dict(
        (name, bad)
        for name, _sev, bad in run_checks(
            accept_issues=set(),
            escrow_issues=set(),
            paid_issues=set(),
            claimed_not_paid={77},
        )
    )
    assert 77 in checks["claimed issue with no escrow event"]


def test_run_checks_claimed_with_escrow_passes() -> None:
    """Claimed issue (not paid) with escrow event present → no WARN."""
    checks = dict(
        (name, bad)
        for name, _sev, bad in run_checks(
            accept_issues=set(),
            escrow_issues={77},
            paid_issues=set(),
            claimed_not_paid={77},
        )
    )
    assert checks["claimed issue with no escrow event"] == []


# ---------------------------------------------------------------------------
# load_ledger_events tests (file I/O via tmp_path)
# ---------------------------------------------------------------------------

def test_load_ledger_accept_events(tmp_path: Path) -> None:
    """accept events are collected by issue number."""
    _write_history(
        tmp_path,
        {"type": "accept", "issue": 42, "agent": "agent@x", "amount": 10},
        {"type": "accept", "issue": 99, "agent": "agent@x", "amount": 5},
    )
    accept, escrow = load_ledger_events(tmp_path)
    assert accept == {42, 99}
    assert escrow == set()


def test_load_ledger_escrow_batch_issues_array(tmp_path: Path) -> None:
    """escrow_batch with 'issues' list populates escrow_issues correctly."""
    _write_history(
        tmp_path,
        {"type": "escrow_batch", "author": "agent0@system", "issues": [10, 20, 30], "total": 60},
    )
    accept, escrow = load_ledger_events(tmp_path)
    assert accept == set()
    assert escrow == {10, 20, 30}


def test_load_ledger_missing_history_dir(tmp_path: Path) -> None:
    """Missing ledger/history dir returns empty sets without error."""
    accept, escrow = load_ledger_events(tmp_path)
    assert accept == set()
    assert escrow == set()


# ---------------------------------------------------------------------------
# parse_github_issues unit tests
# ---------------------------------------------------------------------------

def test_parse_github_issues_paid_and_claimed() -> None:
    """Paid and claimed-not-paid issues are separated correctly."""
    data = [
        _gh_issue(1, "task", "paid"),
        _gh_issue(2, "task", "claimed"),
        _gh_issue(3, "task", "open"),
    ]
    paid, claimed = parse_github_issues(data)
    assert paid == {1}
    assert claimed == {2}


# ---------------------------------------------------------------------------
# main() integration tests
# ---------------------------------------------------------------------------

def test_main_exits_0_on_clean(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """All consistent → exit 0 and all checks PASS."""
    _write_history(
        tmp_path,
        {"type": "accept", "issue": 42, "agent": "a@x", "amount": 10},
        {"type": "escrow", "issue": 77, "author": "agent0@system", "amount": 5},
    )
    gh = _gh_json(
        _gh_issue(42, "task", "paid"),
        _gh_issue(77, "task", "claimed"),
    )
    rc = main(["--root", str(tmp_path)], gh_issues_json=gh)
    out = capsys.readouterr().out
    assert rc == 0
    assert "PASS: paid label with no accept event" in out
    assert "PASS: accept event with no paid label" in out
    assert "PASS: claimed issue with no escrow event" in out


def test_main_exits_1_on_discrepancy(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Orphan paid label → exit 1 and FAIL line in output."""
    _write_history(tmp_path)  # no accept events
    gh = _gh_json(_gh_issue(42, "task", "paid"))
    rc = main(["--root", str(tmp_path)], gh_issues_json=gh)
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL: paid label with no accept event" in out
    assert "42" in out
