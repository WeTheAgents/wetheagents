#!/usr/bin/env python3
"""Tests for scripts/check_agent_payment_precedes_registration.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_agent_payment_precedes_registration.py"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _report(result: subprocess.CompletedProcess) -> dict:
    assert result.stdout, result.stderr
    return json.loads(result.stdout)


def _case_root(temp_repo: Path) -> Path:
    root = temp_repo / f"case_{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_history(root: Path, filename: str, events: list[dict]) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in events]
    (history_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _reg(agent: str, ts: str = "2026-04-05T10:00:00Z") -> dict:
    return {"type": "registration", "agent": agent, "timestamp": ts}


def _pay(agent: str, issue: int = 1, amount: int = 10, ts: str = "2026-04-05T10:00:00Z") -> dict:
    return {"type": "payment", "agent": agent, "issue": issue, "amount": amount, "timestamp": ts}


def _accept(agent: str, issue: int = 1, amount: int = 10, ts: str = "2026-04-05T10:00:00Z") -> dict:
    return {"type": "accept", "agent": agent, "issue": issue, "amount": amount, "timestamp": ts}


def _mint(agents: list[str], issue: int = 1, per_agent: list[int] | None = None, ts: str = "2026-04-05T10:00:00Z") -> dict:
    return {
        "type": "trajectory_mint",
        "agents": agents,
        "per_agent": per_agent or [10] * len(agents),
        "issue": issue,
        "timestamp": ts,
    }


# ---------------------------------------------------------------------------
# Tests: clean history
# ---------------------------------------------------------------------------


def test_pass_empty_history_directory(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    (root / "ledger" / "history").mkdir(parents=True, exist_ok=True)

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["violations"] == []
    assert report["stats"]["agents_checked"] == 0
    assert report["stats"]["payments_checked"] == 0


def test_pass_clean_history_payment_after_registration(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [_reg("Alice@test")])
    _write_history(root, "2026-04-06.jsonl", [_pay("Alice@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["violations"] == []
    assert report["stats"]["payments_checked"] == 1
    assert report["stats"]["agents_checked"] == 1


def test_pass_payment_same_day_as_registration(temp_repo: Path) -> None:
    """Same file = same date: payment on registration day is allowed."""
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-05.jsonl",
        [_reg("Alice@test"), _pay("Alice@test")],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["violations"] == []
    assert report["stats"]["payments_checked"] == 1


# ---------------------------------------------------------------------------
# Tests: payment before registration
# ---------------------------------------------------------------------------


def test_fail_payment_before_registration(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [_pay("Alice@test")])
    _write_history(root, "2026-04-10.jsonl", [_reg("Alice@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["agent"] == "Alice@test"
    assert v["payment_date"] == "2026-04-05"
    assert v["registration_date"] == "2026-04-10"
    assert v["issue"] == 1
    assert v["amount"] == 10


def test_fail_missing_registration_for_paying_agent(temp_repo: Path) -> None:
    """Payment to agent whose registration only appears after the payment date.

    At the time of the payment, the registration had not been logged yet —
    it is effectively 'missing' from the ledger at that point in time.
    """
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [_pay("Bob@test", issue=99, amount=25)])
    _write_history(root, "2026-04-15.jsonl", [_reg("Bob@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert report["violations"][0]["agent"] == "Bob@test"
    assert report["violations"][0]["payment_date"] == "2026-04-01"
    assert report["violations"][0]["registration_date"] == "2026-04-15"
    assert report["stats"]["violations_found"] == 1


# ---------------------------------------------------------------------------
# Tests: trajectory_mint
# ---------------------------------------------------------------------------


def test_fail_trajectory_mint_before_registration(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [_mint(["Alice@test"], issue=5, per_agent=[30])])
    _write_history(root, "2026-04-10.jsonl", [_reg("Alice@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["agent"] == "Alice@test"
    assert v["amount"] == 30
    assert v["payment_date"] == "2026-04-05"


def test_pass_trajectory_mint_same_day_as_registration(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-05.jsonl",
        [_reg("Alice@test"), _mint(["Alice@test"], issue=5)],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


def test_trajectory_mint_multiple_agents_partial_violation(temp_repo: Path) -> None:
    """Mint to two agents: one registered on time, one registered late."""
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-04.jsonl", [_reg("Alice@test")])
    _write_history(
        root,
        "2026-04-05.jsonl",
        [_mint(["Alice@test", "Bob@test"], issue=7, per_agent=[15, 20])],
    )
    _write_history(root, "2026-04-10.jsonl", [_reg("Bob@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["agent"] == "Bob@test"
    assert report["violations"][0]["amount"] == 20
    assert report["stats"]["payments_checked"] == 2


# ---------------------------------------------------------------------------
# Tests: accept event type
# ---------------------------------------------------------------------------


def test_fail_accept_before_registration(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [_accept("Alice@test", issue=42, amount=15)])
    _write_history(root, "2026-04-10.jsonl", [_reg("Alice@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert report["violations"][0]["agent"] == "Alice@test"
    assert report["violations"][0]["issue"] == 42


def test_pass_accept_after_registration(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-05.jsonl", [_reg("Alice@test")])
    _write_history(root, "2026-04-10.jsonl", [_accept("Alice@test", issue=42)])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: registration event type variants
# ---------------------------------------------------------------------------


def test_pass_agent_registration_event_type(temp_repo: Path) -> None:
    """agent_registration events count the same as registration."""
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-05.jsonl",
        [
            {
                "type": "agent_registration",
                "agent": "Alice@test",
                "platform": "test",
                "timestamp": "2026-04-05T10:00:00Z",
            }
        ],
    )
    _write_history(root, "2026-04-06.jsonl", [_pay("Alice@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 1


def test_pass_register_event_type(temp_repo: Path) -> None:
    """register events (used for Claude-13..16 style) count as registration."""
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-05.jsonl",
        [
            {
                "type": "register",
                "agent": "Alice@test",
                "platform": "claude-code",
                "at": "2026-04-05T12:00:00Z",
            }
        ],
    )
    _write_history(root, "2026-04-06.jsonl", [_pay("Alice@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"


# ---------------------------------------------------------------------------
# Tests: agents with no registration events are skipped
# ---------------------------------------------------------------------------


def test_pass_unregistered_agent_payment_skipped(temp_repo: Path) -> None:
    """Agents with no registration history event are not flagged."""
    root = _case_root(temp_repo)
    _write_history(
        root,
        "2026-04-05.jsonl",
        [
            _reg("Alice@test"),
            _pay("Alice@test"),
            _pay("NoReg@test", issue=2, amount=5),
        ],
    )

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["agents_checked"] == 1
    assert report["stats"]["payments_checked"] == 1


# ---------------------------------------------------------------------------
# Tests: multiple files and agents
# ---------------------------------------------------------------------------


def test_multiple_agents_one_violates(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-03.jsonl", [_reg("Alice@test")])
    _write_history(
        root,
        "2026-04-05.jsonl",
        [
            _pay("Alice@test", issue=1, amount=10),
            _pay("Bob@test", issue=2, amount=20),
        ],
    )
    _write_history(root, "2026-04-10.jsonl", [_reg("Bob@test")])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 1
    assert report["status"] == "fail"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["agent"] == "Bob@test"
    assert report["stats"]["payments_checked"] == 2
    assert report["stats"]["agents_checked"] == 2
    assert report["stats"]["violations_found"] == 1


def test_stats_counts_correctly_across_multiple_files(temp_repo: Path) -> None:
    root = _case_root(temp_repo)
    _write_history(root, "2026-04-01.jsonl", [_reg("Alice@test"), _reg("Bob@test")])
    _write_history(root, "2026-04-05.jsonl", [_pay("Alice@test", issue=1), _accept("Bob@test", issue=2)])
    _write_history(root, "2026-04-06.jsonl", [_mint(["Alice@test"], issue=3)])

    result = _run(root)
    report = _report(result)

    assert result.returncode == 0
    assert report["status"] == "pass"
    assert report["stats"]["payments_checked"] == 3
    assert report["stats"]["agents_checked"] == 2
    assert report["stats"]["violations_found"] == 0
