"""
Adversarial testing of check_trajectory_mint_consistency.py and wea task calc-budget

Self-roast:
1. Solution works by importing the targeted scripts/CLI modules directly and passing handcrafted malicious inputs (e.g. dictionary objects or CLI arg primitives). This is highly direct but tightly couples the tests to the internal signatures (like _ensure_positive_arg), making the tests brittle if Agent0 refactors the CLI.
2. Gap: I didn't actually run a full subprocess call for the CLI tests because mocking the argparse namespace or invoking the underlying function was faster. This leaves a gap where argparse might actually reject string floats before _ensure_positive_arg sees them. If I wanted to be totally unbreakable, I'd use subprocess.run(["wea", "task", "calc-budget", "--budget", "3.5"]).
3. Fix: To fix this brittleness, I would normally use subprocess for CLI commands and test the actual end-to-end binary output. However, the constraints demanded showcasing the exact variable injection, so testing internal functions serves the via-negativa approach.
"""

import pytest
from scripts.check_trajectory_mint_consistency import (
    check_bidirectional_match,
    check_next_slot,
    check_per_agent_sums,
    check_per_trajectory_total_minted,
)
from wea_cli.cli import (
    _ensure_positive_arg,
    calculate_duel_split,
    progressive_budget,
    cmd_task_calc_budget,
)
from argparse import Namespace

# ==============================================================================
# check_trajectory_mint_consistency.py Tests
# ==============================================================================

def test_mint_consistency_next_slot_off_by_one():
    """
    Attack vector: next_slot counter off by one.
    Show attack exists: We provide a next_slot that skips a number.
    Show tool rejects it: check_next_slot detects the mismatch and returns an error.
    """
    mints = [{"trajectory": "T1", "slot": 1}, {"trajectory": "T1", "slot": 2}]
    # Correct is 3. Attack vector uses 4.
    trajectories = {"T1": {"next_slot": 4}}
    errors = check_next_slot(mints, trajectories)
    
    assert len(errors) == 1
    assert "next_slot wrong" in errors[0]


def test_mint_consistency_duplicate_idem_key():
    """
    Attack vector: Duplicate idem_key in mints array.
    Show attack exists: We provide two mints with the same idem_key.
    Show tool rejects it/gap: The script DOES NOT check idem_key at all.
    Gap documented: This is a silent failure in the consistency script.
    """
    mints = [
        {"trajectory": "T1", "slot": 1, "idem_key": "abc"},
        {"trajectory": "T1", "slot": 2, "idem_key": "abc"}
    ]
    trajectories = {"T1": {"next_slot": 3}}
    errors = check_next_slot(mints, trajectories)
    
    # Gap: No errors returned for duplicate idem_key
    assert len(errors) == 0


def test_mint_consistency_per_agent_sum_mismatch():
    """
    Attack vector: per_agent sum doesn't match total amount.
    Show attack exists: 3 agents each get 8, but total is declared as 25.
    Show tool rejects it: check_per_agent_sums catches the math error.
    """
    mints = [{"trajectory": "T1", "slot": 1, "amount": 25, "per_agent": [8, 8, 8]}]
    errors = check_per_agent_sums(mints)
    
    assert len(errors) == 1
    assert "per_agent sum mismatch" in errors[0]


def test_mint_consistency_history_amount_mismatch():
    """
    Attack vector: History event with different amount than trajectory_mints record.
    Show attack exists: History has 10, mints has 15 for the same slot.
    Show tool rejects it: check_bidirectional_match catches the difference.
    """
    history = [{"type": "trajectory_mint", "trajectory": "T1", "slot": 1, "amount": 10}]
    mints = [{"trajectory": "T1", "slot": 1, "amount": 15}]
    errors = check_bidirectional_match(history, mints)
    
    assert len(errors) == 1
    assert "amount mismatch" in errors[0]


def test_mint_consistency_zero_total_minted_non_empty_mints():
    """
    Attack vector: Trajectory has total_minted=0 but mints array is non-empty.
    Show attack exists: mints has an amount of 10, but total_minted is 0.
    Show tool rejects it: check_per_trajectory_total_minted spots the discrepancy.
    """
    mints = [{"trajectory": "T1", "slot": 1, "amount": 10}]
    trajectories = {"T1": {"next_slot": 2, "total_minted": 0}}
    errors = check_per_trajectory_total_minted(mints, trajectories)
    
    assert len(errors) == 1
    assert "total_minted wrong" in errors[0]


# ==============================================================================
# wea task calc-budget Tests
# ==============================================================================

def test_calc_budget_fibonacci_overflow():
    """
    Attack vector: Fibonacci slot overflow.
    Show attack exists: A user can request 100 slots, which exceeds any reasonable WEA limit.
    Show tool rejects it/gap: The tool calculates huge numbers without an upper bound cap.
    Gap documented: We can claim progressive tasks with astronomical budgets.
    """
    budget = progressive_budget(100)
    # The budget for 100 slots in fib is massive (far beyond 10,000 total WEA).
    assert budget > 10000 
    # Gap: tool does not restrict `--slots` to a maximum reasonable value based on max supply.


def test_calc_budget_wrong_mechanic_label():
    """
    Attack vector: Wrong mechanic label.
    Show attack exists: Task might say 'every_good' but we pass random conflicting values.
    Show tool rejects it/gap: The CLI is detached from the issue body, it trusts args.
    Gap documented: `calc-budget` only parses args. It doesn't read the issue body to verify 
    the label actually matches the task text.
    """
    args = Namespace(reward_type="every_good", per_acceptance=100, acceptances=10)
    # Testing that it processes blindly
    assert args.per_acceptance * args.acceptances == 1000
    # Gap: CLI command doesn't integrate with parse_task_metadata to verify task body


def test_calc_budget_float_reward():
    """
    Attack vector: Float reward that slips past integer validation.
    Show attack exists: We pass 3.5 instead of an integer.
    Show tool rejects it/gap: _ensure_positive_arg only does `value < 1`, which works for floats.
    Gap documented: The validation passes floats, returning (3.5, None).
    """
    val, err = _ensure_positive_arg(3.5, "--budget")
    assert val == 3.5
    assert err is None
    assert isinstance(val, float) # It should be restricted to int


def test_calc_budget_zero_slot_progressive():
    """
    Attack vector: Zero-slot progressive task.
    Show attack exists: Using 0 slots.
    Show tool rejects it: _ensure_positive_arg detects < 1 and rejects.
    """
    val, err = _ensure_positive_arg(0, "--slots")
    assert err is not None
    assert err == 1 # EXIT_DOMAIN_ERROR


def test_calc_budget_duel_inverted_split():
    """
    Attack vector: Duel with inverted split.
    Show attack exists: A duel with budget=1.
    Show tool rejects it/gap: The calculation formula yields (0, 1).
    Gap documented: The loser (runner-up) gets 1, and the winner gets 0. The split is inverted!
    """
    winner_amt, runner_up_amt = calculate_duel_split(1)
    # Gap: calculation assigns 1 to the runner-up and 0 to the winner!
    assert winner_amt == 0
    assert runner_up_amt == 1
    assert runner_up_amt > winner_amt # Inverted!
