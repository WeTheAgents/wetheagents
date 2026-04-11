"""Adversarial test suite for check_task_index_consistency.py.

Each test probes a crafted edge case designed to fool the consistency checker.
Attack vectors are documented in comments. GAP tests expose false negatives —
places where a malformed ledger passes all checks without triggering a failure.

Test categories:
  FAIL  — checker must detect the inconsistency (exit 1 / non-empty failures)
  PASS  — checker must not raise spurious errors on these valid states
  GAP   — checker silently passes a real inconsistency (documented false negatives)
"""
from __future__ import annotations

import json
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
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_history(root: Path, *records: dict) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(r) for r in records)
    (history_dir / "2026-04-11.jsonl").write_text(payload + "\n", encoding="utf-8")


def _setup(
    tmp_path: Path,
    task_index: dict,
    escrows: dict,
    history: list[dict],
) -> Path:
    """Write all ledger fixtures into tmp_path and return it as repo root."""
    _write(tmp_path / "ledger" / "task_index.json", task_index)
    _write(tmp_path / "ledger" / "escrows.json", escrows)
    if history:
        _write_history(tmp_path, *history)
    else:
        (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)
    return tmp_path


# ---------------------------------------------------------------------------
# FAIL cases — checker must detect the inconsistency
# ---------------------------------------------------------------------------


def test_adv01_paid_wrong_agent_fails() -> None:
    # Attack vector: Agent B submits work and a payment event is created for B.
    # But task_index records Agent A as the sole accepted agent.
    # A never received payment. Checker must flag A as unpaid.
    # Spec case 1: payment exists but for wrong agent → FAIL
    failures = check_accepted_agents_have_payments(
        {"tasks": {"55": {"status": "paid", "accepted_agents": ["A@test"]}}},
        {55: {"B@test"}},  # payment exists for B, not A
    )
    assert any("A@test" in f for f in failures), (
        "Expected failure: A@test is accepted but only B@test has a payment event"
    )


def test_adv02_accepted_agents_partial_coverage_fails() -> None:
    # Attack vector: Two agents accepted for the same task, but only one payment
    # was processed. B's payment was silently dropped or never recorded.
    # Checker must report B as unpaid while leaving A's entry clean.
    # Spec case 2: accepted_agents=[A,B] but payment only for A → FAIL
    failures = check_accepted_agents_have_payments(
        {"tasks": {"77": {"status": "paid", "accepted_agents": ["A@test", "B@test"]}}},
        {77: {"A@test"}},  # B missing
    )
    assert any("B@test" in f for f in failures), "B@test has no payment event — must be flagged"
    assert not any("A@test" in f for f in failures), "A@test is correctly paid — must not appear"


def test_adv03_payment_wrong_issue_number_fails(tmp_path: Path) -> None:
    # Attack vector: Adversary crafts a payment event with issue=99 to satisfy
    # task #55. The checker indexes payments by the issue field in the event.
    # The agent ends up in payments_by_issue[99], not payments_by_issue[55].
    # Task #55 therefore has no payment event on record → checker must fail.
    # Spec case 5: payment event has correct agent but wrong issue number → FAIL
    root = _setup(
        tmp_path,
        task_index={"tasks": {"55": {"status": "paid", "accepted_agents": ["A@test"], "reward": 10}}},
        escrows={"active": {}},
        history=[{"type": "payment", "issue": 99, "agent": "A@test", "amount": 10}],
    )
    results = run_checks(root)
    all_failures = [f for _, fs in results for f in fs]
    assert any("55" in f for f in all_failures), (
        "Task #55 should fail — payment event filed under issue 99, not 55"
    )


def test_adv04_open_zero_reward_nonzero_escrow_fails() -> None:
    # Attack vector: Task reward is 0 in task_index (could indicate a free task
    # or a zeroed-out entry), but escrows.json has 50 WEA locked for this issue.
    # The escrow amount doesn't match the stated reward → checker must flag it.
    # Spec case 6: escrow_amount=0 but non-zero active escrow → FAIL
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"20": {"status": "open", "reward": 0}}},
        {"active": {"20": {"amount": 50, "type": "standard"}}},
    )
    assert any("20" in f for f in failures), (
        "Expected failure: escrow amount=50 does not match task reward=0"
    )


def test_adv05_case_sensitive_agent_mismatch_fails() -> None:
    # Attack vector: Checker uses exact string comparison for agent names.
    # An adversary submits as "claude-1@claude" (lowercase), but task_index
    # records "Claude-1@claude" (title-case). The two strings are unequal →
    # the accepted agent appears unpaid despite a payment event existing.
    # Spec case 10: case-sensitivity behavior → documents exact-match behavior
    failures = check_accepted_agents_have_payments(
        {"tasks": {"88": {"status": "paid", "accepted_agents": ["Claude-1@claude"]}}},
        {88: {"claude-1@claude"}},  # lowercase variant — different string
    )
    assert any("Claude-1@claude" in f for f in failures), (
        "Case mismatch: 'Claude-1@claude' != 'claude-1@claude' — "
        "checker performs exact string match, no case normalization"
    )


# ---------------------------------------------------------------------------
# PASS cases — checker must NOT raise spurious errors
# ---------------------------------------------------------------------------


def test_adv06_empty_task_index_with_payment_history_passes(tmp_path: Path) -> None:
    # No tasks in task_index → no inconsistencies possible, even if history
    # contains orphan payment events for issue numbers that don't exist.
    # Confirms: checker does not raise spurious errors on orphan history.
    # Spec case 7: 0 tasks + payment history → PASS
    root = _setup(
        tmp_path,
        task_index={"tasks": {}},
        escrows={"active": {}},
        history=[{"type": "payment", "issue": 55, "agent": "ghost@test", "amount": 10}],
    )
    results = run_checks(root)
    assert all(not fs for _, fs in results), (
        f"No tasks in index — all checks should pass; got failures: {results}"
    )


def test_adv07_intermediate_accepted_status_passes() -> None:
    # status=accepted is an intermediate state between claimed and paid.
    # No payment event is expected at this stage.
    # check_paid_tasks_have_payment_events only fires on status=paid.
    # check_no_stale_escrows only fires on paid/cancelled.
    # Confirms: checker does not treat 'accepted' as equivalent to 'paid'.
    # Spec case 8: status=accepted with no payment → PASS
    failures_paid = check_paid_tasks_have_payment_events(
        {"tasks": {"60": {"status": "accepted", "accepted_agents": None}}},
        {},  # no payment events
    )
    failures_stale = check_no_stale_escrows(
        {"tasks": {"60": {"status": "accepted"}}},
        {"active": {}},  # no active escrow
    )
    assert failures_paid == [], "status=accepted should not trigger paid-payment check"
    assert failures_stale == [], "status=accepted must not trigger stale-escrow check"


def test_adv08_trajectory_mint_not_confused_with_payment_passes(tmp_path: Path) -> None:
    # A trajectory mint event appears in the same history file as the task's
    # payment event. The mint event must not interfere with payment detection
    # or cause spurious failures.
    # Confirms: checker filters on type="payment" — mint events are invisible to it.
    # Spec case 9: trajectory mint not confused with task payment → PASS
    root = _setup(
        tmp_path,
        task_index={"tasks": {"55": {"status": "paid", "accepted_agents": ["A@test"], "reward": 10}}},
        escrows={"active": {}},
        history=[
            {"type": "payment", "issue": 55, "agent": "A@test", "amount": 10},
            {
                "type": "mint",
                "issue": 55,
                "agent": "evaluator@claude",
                "amount": 20,
                "trajectory": "T1",
            },
        ],
    )
    results = run_checks(root)
    assert all(not fs for _, fs in results), (
        f"Mint event must not interfere with task payment check; got: {results}"
    )


# ---------------------------------------------------------------------------
# GAP tests — document false negatives in the current checker
# ---------------------------------------------------------------------------


def test_adv09_claimed_escrow_wrong_internal_issue_gap(tmp_path: Path) -> None:
    # Attack vector (GAP): Escrow entry is keyed as "55" in active{} but carries
    # an internal 'issue' field pointing to issue 99. The checker satisfies the
    # claimed-task check by looking up `issue_str in active` (key lookup only).
    # It never verifies that the escrow's internal issue field matches the key.
    # A recycled escrow from a different task could pass undetected.
    # Expected: checker PASSES (false negative — the gap is documented, not fixed).
    # Spec case 3: claimed escrow exists but for different issue → documents gap
    root = _setup(
        tmp_path,
        task_index={"tasks": {"55": {"status": "claimed", "reward": 10}}},
        escrows={
            "active": {
                "55": {"amount": 10, "issue": 99, "author": "agent0@system"},
            }
        },  # keyed "55" but internal issue=99
        history=[],
    )
    results = run_checks(root)
    all_failures = [f for _, fs in results for f in fs]
    # GAP: checker sees key "55" in active → claimed check passes.
    # The internal issue=99 mismatch is undetected.
    assert not any("55" in f for f in all_failures), (
        "GAP CONFIRMED: checker does not validate escrow's internal issue field vs key — "
        "escrow keyed '55' with internal issue=99 passes the claimed-task check undetected"
    )


def test_adv10_open_task_no_escrow_reward_present_gap(tmp_path: Path) -> None:
    # Attack vector (GAP): Task is open with reward=15 WEA in task_index, but no
    # corresponding entry exists in escrows.json. Funds may never have been locked.
    # check_open_tasks_escrow_amount does `if escrow is None: continue` — it skips
    # the check entirely when no escrow entry exists, even if reward is non-zero.
    # An agent could start work believing funds are secured when they aren't.
    # Expected: checker PASSES (false negative — gap documented).
    # Spec case 4: open task with escrow_amount but no active escrow → documents gap
    root = _setup(
        tmp_path,
        task_index={"tasks": {"33": {"status": "open", "reward": 15}}},
        escrows={"active": {}},  # no escrow entry for task 33
        history=[],
    )
    results = run_checks(root)
    all_failures = [f for _, fs in results for f in fs]
    # GAP: open task with reward=15 and no escrow → passes unchecked.
    assert not any("33" in f for f in all_failures), (
        "GAP CONFIRMED: open task with reward=15 but no active escrow entry passes unchecked — "
        "check_open_tasks_escrow_amount skips when no escrow entry exists"
    )


def test_adv11_open_null_reward_active_escrow_bypass_gap() -> None:
    # Attack vector (GAP): Task has reward=None (field absent or explicitly null)
    # in task_index, but an active escrow entry exists with amount=999 WEA.
    # check_open_tasks_escrow_amount short-circuits with `if reward is None: continue`
    # before comparing amount vs reward. An escrow of arbitrary size passes.
    # Expected: checker PASSES (false negative — gap documented).
    failures = check_open_tasks_escrow_amount(
        {"tasks": {"44": {"status": "open", "reward": None}}},
        {"active": {"44": {"amount": 999, "type": "standard"}}},
    )
    # GAP: reward=None causes checker to skip the amount comparison entirely.
    assert not any("44" in f for f in failures), (
        "GAP CONFIRMED: reward=None bypasses the amount!=reward comparison — "
        "escrow of 999 WEA passes unchecked when task reward is null"
    )


def test_adv12_paid_no_accepted_agents_wrong_agent_gap(tmp_path: Path) -> None:
    # Attack vector (GAP): Task is status=paid with accepted_agents=None.
    # A payment event exists in history — but for "hacker@evil", not the real worker.
    # check_paid_tasks_have_payment_events only verifies that *some* payment event
    # exists for the issue; it does not cross-reference which agent was paid.
    # check_accepted_agents_have_payments skips when accepted_agents is empty/None.
    # The original worker is never paid; the check passes anyway.
    # Expected: checker PASSES (false negative — gap documented).
    root = _setup(
        tmp_path,
        task_index={
            "tasks": {"66": {"status": "paid", "accepted_agents": None, "reward": 10}}
        },
        escrows={"active": {}},
        history=[{"type": "payment", "issue": 66, "agent": "hacker@evil", "amount": 10}],
    )
    results = run_checks(root)
    all_failures = [f for _, fs in results for f in fs]
    # GAP: "hacker@evil" payment satisfies the paid-task check for task #66.
    assert not any("66" in f for f in all_failures), (
        "GAP CONFIRMED: when accepted_agents=None, any payment for the issue satisfies "
        "the paid-task check — 'hacker@evil' payment passes undetected for task #66"
    )
