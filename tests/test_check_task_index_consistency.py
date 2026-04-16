from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.check_task_index_consistency import (
    check_accepted_agents_have_payments,
    check_claimed_tasks_have_evidence,
    check_no_stale_escrows,
    check_open_tasks_escrow_amount,
    check_paid_tasks_have_payment_events,
    run_checks,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, *records: dict) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(r) for r in records)
    (history_dir / "2026-03-06.jsonl").write_text(lines + "\n", encoding="utf-8")


def _base_repo(tmp_path: Path) -> Path:
    """Clean repo: one paid task with a payment event, one open task with escrow."""
    root = tmp_path

    _write(
        root / "ledger" / "task_index.json",
        {
            "version": 1,
            "tasks": {
                "10": {
                    "title": "paid task",
                    "status": "paid",
                    "reward": 20,
                    "mechanic": "best_x",
                    "accepted_agents": None,
                },
                "20": {
                    "title": "open task with escrow",
                    "status": "open",
                    "reward": 15,
                    "mechanic": "standard",
                    "accepted_agents": None,
                },
                "30": {
                    "title": "open task without escrow",
                    "status": "open",
                    "reward": 10,
                    "mechanic": "every_good",
                    "accepted_agents": None,
                },
            },
        },
    )
    _write(
        root / "ledger" / "escrows.json",
        {
            "version": 1,
            "active": {
                "20": {"author": "agent0@system", "amount": 15, "type": "standard"},
            },
        },
    )
    _write_history(
        root,
        {"type": "payment", "issue": 10, "agent": "worker@test", "amount": 20},
    )
    return root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_checks_pass_on_clean_repo(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    results = run_checks(root)
    assert all(not failures for _, failures in results), results


def test_paid_task_no_payment_history_fails(tmp_path: Path) -> None:
    root = _base_repo(tmp_path)
    _write_history(root)  # wipe history
    task_index = json.loads(
        (root / "ledger" / "task_index.json").read_text(encoding="utf-8")
    )
    failures = check_paid_tasks_have_payment_events(task_index, {})
    assert any("10" in f for f in failures)


def test_paid_task_with_payment_passes() -> None:
    failures = check_paid_tasks_have_payment_events(
        {"tasks": {"99": {"status": "paid", "reward": 5}}},
        {99: {"worker@test"}},
    )
    assert failures == []


def test_open_escrow_matching_amount_passes() -> None:
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"20": {"status": "open", "reward": 15}}},
        {"active": {"20": {"amount": 15, "type": "standard"}}},
    )
    assert failures == []


def test_open_escrow_amount_mismatch_fails() -> None:
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"20": {"status": "open", "reward": 15}}},
        {"active": {"20": {"amount": 10, "type": "standard"}}},
    )
    assert any("20" in f and "amount=10" in f for f in failures)


def test_open_escrow_zero_amount_fails() -> None:
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"20": {"status": "open", "reward": 15}}},
        {"active": {"20": {"amount": 0, "type": "standard"}}},
    )
    assert any("20" in f for f in failures)


def test_open_no_escrow_passes() -> None:
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"30": {"status": "open", "reward": 10}}},
        {"active": {}},
    )
    assert failures == []


def test_open_every_good_per_acceptance_mismatch_fails() -> None:
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"40": {"status": "open", "reward": 25}}},
        {"active": {"40": {"amount": 50, "type": "every_good", "per_acceptance": 10}}},
    )
    assert any("per_acceptance=10" in f for f in failures)


def test_open_every_good_matching_per_acceptance_passes() -> None:
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"40": {"status": "open", "reward": 25}}},
        {"active": {"40": {"amount": 50, "type": "every_good", "per_acceptance": 25}}},
    )
    assert failures == []


def test_claimed_with_claim_event_passes() -> None:
    events = {55: [{"type": "claim", "issue": 55, "agent": "worker@test"}]}
    failures = check_claimed_tasks_have_evidence(
        {"tasks": {"55": {"status": "claimed"}}},
        {"active": {}},
        events,
    )
    assert failures == []


def test_claimed_with_escrow_passes() -> None:
    failures = check_claimed_tasks_have_evidence(
        {"tasks": {"55": {"status": "claimed"}}},
        {"active": {"55": {"amount": 10}}},
        {},
    )
    assert failures == []


def test_claimed_no_evidence_fails() -> None:
    failures = check_claimed_tasks_have_evidence(
        {"tasks": {"55": {"status": "claimed"}}},
        {"active": {}},
        {},
    )
    assert any("55" in f for f in failures)


def test_accepted_agents_all_paid_passes() -> None:
    failures = check_accepted_agents_have_payments(
        {"tasks": {"77": {"status": "paid", "accepted_agents": ["a@test", "b@test"]}}},
        {77: {"a@test", "b@test"}},
    )
    assert failures == []


def test_accepted_agents_missing_payment_fails() -> None:
    failures = check_accepted_agents_have_payments(
        {"tasks": {"77": {"status": "paid", "accepted_agents": ["a@test", "b@test"]}}},
        {77: {"a@test"}},  # b@test missing
    )
    assert any("b@test" in f for f in failures)
    assert not any("a@test" in f for f in failures)


def test_accepted_agents_none_skips() -> None:
    failures = check_accepted_agents_have_payments(
        {"tasks": {"77": {"status": "paid", "accepted_agents": None}}},
        {},
    )
    assert failures == []


def test_stale_escrow_for_paid_task_fails() -> None:
    failures = check_no_stale_escrows(
        {"tasks": {"10": {"status": "paid"}}},
        {"active": {"10": {"amount": 20}}},
    )
    assert any("10" in f and "paid" in f for f in failures)


def test_stale_escrow_for_cancelled_task_fails() -> None:
    failures = check_no_stale_escrows(
        {"tasks": {"10": {"status": "cancelled"}}},
        {"active": {"10": {"amount": 20}}},
    )
    assert any("10" in f and "cancelled" in f for f in failures)


def test_stale_escrow_open_task_passes() -> None:
    failures = check_no_stale_escrows(
        {"tasks": {"10": {"status": "open"}}},
        {"active": {"10": {"amount": 20}}},
    )
    assert failures == []


# ---------------------------------------------------------------------------
# Integration test — real repo must be clean
# ---------------------------------------------------------------------------


def test_integration_real_repo_is_clean() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "check_task_index_consistency.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(repo_root)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"check_task_index_consistency.py reported failures:\n{result.stdout}{result.stderr}"
    )
