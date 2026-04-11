import json
import pytest
from pathlib import Path

from scripts.check_payment_completeness import check_payment_completeness
from scripts.check_task_index_consistency import run_checks

def setup_ledger(tmp_path: Path, task_index=None, escrows=None, history_events=None):
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()
    
    if task_index is not None:
        (ledger / "task_index.json").write_text(json.dumps(task_index))
    else:
        (ledger / "task_index.json").write_text('{"tasks": {}}')
        
    if escrows is not None:
        (ledger / "escrows.json").write_text(json.dumps(escrows))
    else:
        (ledger / "escrows.json").write_text('{"active": {}}')
        
    if history_events is not None:
        with open(history / "events.jsonl", "w") as f:
            for ev in history_events:
                f.write(json.dumps(ev) + "\n")

# ==========================================
# Targets for check_payment_completeness.py
# ==========================================

def test_verification_without_payment(tmp_path):
    """
    Attack Vector: A verification is recorded for an escrowed issue, but payment is never made.
    Expected Behavior: The script detects exactly 1 gap.
    """
    events = [
        {"type": "escrow", "issue": 1, "amount": 10},
        {"type": "verification", "issue": 1, "agent": "A"}
    ]
    setup_ledger(tmp_path, history_events=events)
    gaps = check_payment_completeness(tmp_path)
    assert len(gaps) == 1
    assert gaps[0]["agent"] == "A"

def test_duplicate_verifications_one_payment(tmp_path):
    """
    Attack Vector: An agent verifies multiple times (e.g. spamming) but gets paid only once.
    Expected Behavior: The script considers it complete (no gaps).
    """
    events = [
        {"type": "escrow", "issue": 2, "amount": 10},
        {"type": "verification", "issue": 2, "agent": "B"},
        {"type": "verification", "issue": 2, "agent": "B"},
        {"type": "payment", "issue": 2, "agent": "B"}
    ]
    setup_ledger(tmp_path, history_events=events)
    gaps = check_payment_completeness(tmp_path)
    assert len(gaps) == 0

def test_trajectory_mint_confusion(tmp_path):
    """
    Attack Vector: Non-task events (e.g., trajectory_mint) without issue/agent fields are present.
    Expected Behavior: The script ignores irrelevant events and correctly finds real payment gaps.
    """
    events = [
        {"type": "trajectory_mint", "amount": 500},
        {"type": "escrow", "issue": 3, "amount": 10},
        {"type": "verification", "issue": 3, "agent": "C"}
    ]
    setup_ledger(tmp_path, history_events=events)
    gaps = check_payment_completeness(tmp_path)
    assert len(gaps) == 1
    assert gaps[0]["issue"] == 3

def test_mechanic_variations_every_good(tmp_path):
    """
    Attack Vector: 'every_good' mechanic where multiple agents verify. One is paid, the other is not.
    Expected Behavior: The script correctly identifies the unpaid agent.
    """
    events = [
        {"type": "escrow", "issue": 4, "mechanic": "every_good", "per_acceptance": 5},
        {"type": "verification", "issue": 4, "agent": "D"},
        {"type": "verification", "issue": 4, "agent": "E"},
        {"type": "payment", "issue": 4, "agent": "D"}
    ]
    setup_ledger(tmp_path, history_events=events)
    gaps = check_payment_completeness(tmp_path)
    assert len(gaps) == 1
    assert gaps[0]["agent"] == "E"

def test_verification_rejected_work(tmp_path):
    """
    Attack Vector: A verification event exists but the issue was never escrowed (e.g., rejected invalid task).
    Expected Behavior: The script skips unescrowed issues and reports no gaps.
    """
    events = [
        {"type": "verification", "issue": 5, "agent": "F"}
    ]
    setup_ledger(tmp_path, history_events=events)
    gaps = check_payment_completeness(tmp_path)
    assert len(gaps) == 0

def test_escrow_batch(tmp_path):
    """
    Attack Vector: An escrow_batch event lists multiple issues, only some get paid after verification.
    Expected Behavior: The script identifies the specific issue in the batch that is missing payment.
    """
    events = [
        {"type": "escrow_batch", "issues": [10, 11]},
        {"type": "verification", "issue": 10, "agent": "A"},
        {"type": "verification", "issue": 11, "agent": "A"},
        {"type": "payment", "issue": 10, "agent": "A"}
    ]
    setup_ledger(tmp_path, history_events=events)
    gaps = check_payment_completeness(tmp_path)
    assert len(gaps) == 1
    assert gaps[0]["issue"] == 11

# ==========================================
# Targets for check_task_index_consistency.py
# ==========================================

def test_paid_task_wrong_agent_payment(tmp_path):
    """
    Attack Vector: Task is marked 'paid' to Agent X in task_index, but payment history shows Agent Y.
    Expected Behavior: Fails the accepted agents payment check.
    """
    task_index = {"tasks": {"6": {"status": "paid", "accepted_agents": ["X"]}}}
    events = [{"type": "payment", "issue": 6, "agent": "Y"}]
    setup_ledger(tmp_path, task_index=task_index, history_events=events)
    results = run_checks(tmp_path)
    accepted_failures = [r[1] for r in results if r[0] == "Accepted agents all have payment events in history"][0]
    assert len(accepted_failures) == 1
    assert "accepted_agent='X' has no payment event" in accepted_failures[0]

def test_partial_multi_agent_payment(tmp_path):
    """
    Attack Vector: task_index has multiple accepted agents, but only one received a payment event.
    Expected Behavior: Fails the accepted agents payment check for the unpaid agent.
    """
    task_index = {"tasks": {"7": {"status": "paid", "accepted_agents": ["A", "B"]}}}
    events = [{"type": "payment", "issue": 7, "agent": "A"}]
    setup_ledger(tmp_path, task_index=task_index, history_events=events)
    results = run_checks(tmp_path)
    accepted_failures = [r[1] for r in results if r[0] == "Accepted agents all have payment events in history"][0]
    assert len(accepted_failures) == 1
    assert "accepted_agent='B'" in accepted_failures[0]

def test_escrow_number_mismatch(tmp_path):
    """
    Attack Vector: An open task has an active escrow amount that does not match the task reward.
    Expected Behavior: Fails the escrow amount consistency check.
    """
    task_index = {"tasks": {"8": {"status": "open", "reward": 100}}}
    escrows = {"active": {"8": {"amount": 50}}}
    setup_ledger(tmp_path, task_index=task_index, escrows=escrows)
    results = run_checks(tmp_path)
    escrow_failures = [r[1] for r in results if r[0] == "Open tasks with active escrow have consistent amount"][0]
    assert len(escrow_failures) == 1
    assert "amount=50 != task reward=100" in escrow_failures[0]

def test_case_sensitivity_edge_cases(tmp_path):
    """
    Attack Vector: Agent names are case-insensitive in intent but strictly checked (e.g. 'Agent1' vs 'agent1').
    Expected Behavior: Script strictly fails the case-mismatched agent payment check.
    """
    task_index = {"tasks": {"9": {"status": "paid", "accepted_agents": ["Agent1"]}}}
    events = [{"type": "payment", "issue": 9, "agent": "agent1"}]
    setup_ledger(tmp_path, task_index=task_index, history_events=events)
    results = run_checks(tmp_path)
    accepted_failures = [r[1] for r in results if r[0] == "Accepted agents all have payment events in history"][0]
    assert len(accepted_failures) == 1
    assert "accepted_agent='Agent1'" in accepted_failures[0]

def test_stale_escrow_cancelled_task(tmp_path):
    """
    Attack Vector: Task is marked 'cancelled' but still has an active escrow entry.
    Expected Behavior: Fails the stale escrows check.
    """
    task_index = {"tasks": {"12": {"status": "cancelled"}}}
    escrows = {"active": {"12": {"amount": 100}}}
    setup_ledger(tmp_path, task_index=task_index, escrows=escrows)
    results = run_checks(tmp_path)
    stale_failures = [r[1] for r in results if r[0] == "No stale escrows for paid or cancelled tasks"][0]
    assert len(stale_failures) == 1
    assert "status=cancelled but still has an active escrow" in stale_failures[0]

def test_claimed_task_without_evidence(tmp_path):
    """
    Attack Vector: A task is marked as 'claimed' in task_index but there is no active escrow and no claim event.
    Expected Behavior: Fails the claimed tasks evidence check.
    """
    task_index = {"tasks": {"13": {"status": "claimed"}}}
    setup_ledger(tmp_path, task_index=task_index)
    results = run_checks(tmp_path)
    claimed_failures = [r[1] for r in results if r[0] == "Claimed tasks have a claim event or escrow entry"][0]
    assert len(claimed_failures) == 1
    assert "status=claimed but no claim event in history and no active escrow" in claimed_failures[0]

def test_stale_escrow_paid_task(tmp_path):
    """
    Attack Vector: Task is marked 'paid' but still has an active escrow entry.
    Expected Behavior: Fails the stale escrows check.
    """
    task_index = {"tasks": {"14": {"status": "paid"}}}
    escrows = {"active": {"14": {"amount": 50}}}
    setup_ledger(tmp_path, task_index=task_index, escrows=escrows)
    results = run_checks(tmp_path)
    stale_failures = [r[1] for r in results if r[0] == "No stale escrows for paid or cancelled tasks"][0]
    assert len(stale_failures) == 1
    assert "status=paid but still has an active escrow entry" in stale_failures[0]
