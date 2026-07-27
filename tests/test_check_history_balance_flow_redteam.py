import json
from pathlib import Path
import pytest

from scripts.check_history_balance_flow import run

pytestmark = [
    pytest.mark.v1_known_debt,
    pytest.mark.xfail(
        reason="Known v1 history balance gaps tracked by stabilization issue #896",
        strict=True,
    ),
]


def setup_ledger(tmp_path: Path, events: list[dict], final_balances: dict) -> Path:
    ledger_dir = tmp_path / "ledger"
    history_dir = ledger_dir / "history"
    history_dir.mkdir(parents=True)
    
    # Write events to history across two files to simulate boundary crossing if needed
    mid = len(events) // 2
    if mid == 0:
        mid = 1
        
    with open(history_dir / "01.jsonl", "w", encoding="utf-8") as f:
        for e in events[:mid]:
            f.write(json.dumps(e) + "\n")
            
    with open(history_dir / "02.jsonl", "w", encoding="utf-8") as f:
        for e in events[mid:]:
            f.write(json.dumps(e) + "\n")
            
    # Write balances.json
    balances_data = {"agents": {}}
    for agent, balance in final_balances.items():
        balances_data["agents"][agent] = {"balance": balance}
        
    with open(ledger_dir / "balances.json", "w", encoding="utf-8") as f:
        json.dump(balances_data, f)
        
    return tmp_path

def test_negative_balance_cross_file_boundary(tmp_path):
    """
    (a) negative balance crossing history-file midnight boundary.
    The checker processes all files as one stream, but negative violations
    can be wiped by an economy_reset in a subsequent file! This makes the
    intra-cycle negative window invisible to the final pass if not aggregated globally.
    """
    events = [
        {"type": "mint", "agent": "agent-1@platform", "amount": 5, "timestamp": "T1"},
        # Drops below zero in file 1
        {"type": "escrow_create", "agent": "agent-1@platform", "amount": 10, "timestamp": "T2"},
        # File boundary happens here
        # Recovers and reset happens in file 2
        {"type": "mint", "agent": "agent-1@platform", "amount": 10, "timestamp": "T3"},
        {"type": "economy_reset", "agents_zeroed": ["agent-1@platform"], "timestamp": "T4"}
    ]
    final_balances = {"agent-1@platform": 0}
    setup_ledger(tmp_path, events, final_balances)
    
    result, passed = run(tmp_path)
    
    # Expected FAIL detection: there was a negative balance at T2!
    assert not passed, "Checker failed to detect cross-file negative balance"
    assert result["status"] == "FAIL"

def test_economy_reset_manipulated_wea_returned(tmp_path):
    """
    (b) economy_reset with manipulated wea_returned_to_agent0 resetting baseline incorrectly.
    """
    events = [
        {"type": "economy_reset", "wea_returned_to_agent0": 999999, "agents_zeroed": [], "timestamp": "T1"}
    ]
    # Agent0 is not tracked in balances.json
    final_balances = {}
    setup_ledger(tmp_path, events, final_balances)
    
    result, passed = run(tmp_path)
    
    # Expected FAIL detection: manipulated economy reset
    assert not passed, "Checker failed to detect manipulated economy_reset wea_returned_to_agent0"
    assert result["status"] == "FAIL"

def test_escrow_batch_wrong_agent_id_case(tmp_path):
    """
    (c) escrow_batch credits/debits the wrong agent ID variant.
    """
    events = [
        {"type": "mint", "agent": "agent-1@platform", "amount": 10, "timestamp": "T1"},
        {"type": "mint", "agent": "Agent-1@platform", "amount": 10, "timestamp": "T2"}, # Wrong case mint
        {"type": "escrow_batch", "author": "Agent-1@platform", "total": 10, "timestamp": "T3"}, # Wrong case debit
    ]
    # In balances.json, only the correct case is tracked
    final_balances = {
        "agent-1@platform": 10
    }
    setup_ledger(tmp_path, events, final_balances)
    
    result, passed = run(tmp_path)
    
    # Expected FAIL detection: un-tracked agent variant used
    assert not passed, "Checker failed to detect wrong agent ID case in escrow_batch"
    assert result["status"] == "FAIL"

def test_registration_confirmed_nonexistent_previous(tmp_path):
    """
    (d) registration_confirmed with nonexistent previous_id.
    """
    events = [
        {"type": "registration_confirmed", "previous_id": "ghost@platform", "agent": "new@platform", "timestamp": "T1"}
    ]
    final_balances = {
        "new@platform": 0
    }
    setup_ledger(tmp_path, events, final_balances)
    
    result, passed = run(tmp_path)
    
    # Expected FAIL detection: migration from nonexistent id
    assert not passed, "Checker failed to detect registration_confirmed from nonexistent previous_id"
    assert result["status"] == "FAIL"

def test_escrow_return_mismatched_amount(tmp_path):
    """
    (e) escrow_return with amounts that don't match original escrow_create.
    """
    events = [
        {"type": "mint", "agent": "agent-1@platform", "amount": 10, "timestamp": "T1"},
        {"type": "escrow_create", "agent": "agent-1@platform", "amount": 2, "issue": "1", "timestamp": "T2"},
        {"type": "escrow_return", "agent": "agent-1@platform", "amount": 1000, "issue": "1", "timestamp": "T3"}
    ]
    # final computed balance is 10 - 2 + 1000 = 1008
    final_balances = {
        "agent-1@platform": 1008
    }
    setup_ledger(tmp_path, events, final_balances)
    
    result, passed = run(tmp_path)
    
    # Expected FAIL detection: return amount > create amount
    assert not passed, "Checker failed to detect mismatched escrow_return amount"
    assert result["status"] == "FAIL"
