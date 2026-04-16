import pytest
from pathlib import Path
from scripts.check_escrow_task_reward_match import run_check

def test_bypass_float_reward():
    """
    GAP: reward_wea stored as float (e.g. 33.0) vs int (33).
    The checker's _get_task_reward() ignores floats, so the task is skipped
    and no violation is raised even if the escrow amount is completely wrong.
    It should FAIL because the reward type is invalid or mismatched.
    """
    tasks = {"1": {"reward_wea": 33.0}}
    escrows = {"active": {"1": {"amount": 999, "type": "flat"}}} # mismatched
    events = []
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS", "Checker should have failed but exited 0 vacuously"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "task has no valid reward field"

def test_bypass_progressive_underfunded():
    """
    GAP: Progressive PoD where escrow is underfunded.
    The checker allows ANY escrow_amount <= task_reward for progressive tasks.
    If a progressive task has total reward 100 but active escrow is 20
    (without any prior payouts), the checker will PASS instead of FAIL.
    """
    tasks = {"2": {"reward_wea": 100}}
    escrows = {"active": {"2": {"amount": 20, "type": "progressive"}}}
    events = []
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS", "Checker should have failed due to underfunded progressive task"

def test_bypass_missing_task_index():
    """
    GAP: Escrow for issue not in task_index.
    If an active escrow exists but the task is missing from task_index.json,
    the checker skips it and returns PASS, instead of flagging an orphaned escrow.
    """
    tasks = {}
    escrows = {"active": {"3": {"amount": 50, "type": "flat"}}}
    events = []
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "task not in task_index"

def test_bypass_missing_active_block():
    """
    GAP: Empty or malformed escrows.json active block.
    If the 'active' key is missing or empty, the checker vacuously passes
    even if task_index contains tasks that should have escrows.
    """
    tasks = {"4": {"reward_wea": 50}}
    escrows = {} # missing 'active'
    events = []
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS"

def test_bypass_string_escrow_amount():
    """
    GAP: Escrow amount is a string.
    If escrow amount is a string (e.g., "50"), the checker ignores it 
    (skipped) instead of throwing a validation violation, allowing a bypass.
    """
    tasks = {"5": {"reward_wea": 50}}
    escrows = {"active": {"5": {"amount": "999", "type": "flat"}}}
    events = []
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "escrow has no valid integer amount"

def test_bypass_gauntlet_no_formula_check():
    """
    GAP: Gauntlet formula not validated.
    The checker doesn't actually check the gauntlet formula (19 + slot).
    If a task is labeled gauntlet but has reward=999 and escrow=999,
    it completely passes instead of failing the formula requirement.
    """
    tasks = {"6": {"reward_wea": 999, "labels": ["gauntlet"], "slot": 1}}
    escrows = {"active": {"6": {"amount": 999, "type": "flat"}}}
    events = []
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS"

def test_bypass_history_string_amount():
    """
    GAP: History event amount is a string.
    If a history escrow_create event has an amount as a string, it is skipped
    instead of failing, even if the amount is mismatched.
    """
    tasks = {"7": {"reward_wea": 50}}
    escrows = {"active": {}}
    events = [{"type": "escrow_create", "issue": "7", "amount": "999"}]
    
    result = run_check(Path("."), escrows=escrows, tasks=tasks, events=events)
    assert result["status"] == "PASS"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "history event has no valid integer amount"
