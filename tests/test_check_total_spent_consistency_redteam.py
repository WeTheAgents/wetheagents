import json
import sys
from pathlib import Path
import pytest

# Add scripts directory to path so we can import the module without modifying it
sys.path.insert(0, str(Path("scripts").resolve()))
import check_total_spent_consistency as checker

def run_checker(ledger_dir: Path) -> dict:
    balances_path = ledger_dir / "balances.json"
    history_dir = ledger_dir / "history"
    
    with balances_path.open(encoding="utf-8") as fh:
        balances = json.load(fh)
        
    events = checker._iter_events(history_dir)
    computed = checker.compute_total_spent(events)
    stored_agents = balances.get("agents", {})
    
    status, divergences, summary = checker.check_consistency(stored_agents, computed)
    return {
        "status": status,
        "divergences": divergences,
        "summary": summary
    }

def test_gap_agent_not_in_balances(tmp_path):
    """
    # GAP: Agent missing from balances.json is silently ignored
    # Exploit mechanism: The script iterates `for agent_id in sorted(stored_agents):`. 
    # If an agent has `escrow_create` events in history but is completely missing 
    # from balances.json, the script never checks them and returns PASS.
    """
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()
    
    (ledger_dir / "balances.json").write_text(json.dumps({
        "agents": {}
    }))
    
    (history_dir / "01.jsonl").write_text(json.dumps({
        "type": "escrow_create", 
        "author": "phantom@test", 
        "amount": 100,
        "idem_key": "tx1"
    }) + "\n")
    
    out = run_checker(ledger_dir)
    assert out["status"] == "PASS"

def test_gap_case_sensitivity(tmp_path):
    """
    # GAP: Author field case sensitivity mismatch
    # Exploit mechanism: The script adds to `spent[author]` using the exact casing 
    # from the history event. If the event uses "AGENT1@TEST" but balances.json 
    # uses "agent1@test", `computed.get("agent1@test", 0)` returns 0. 
    # If balances.json has total_spent=0, it incorrectly returns PASS.
    """
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()
    
    (ledger_dir / "balances.json").write_text(json.dumps({
        "agents": {
            "agent1@test": {
                "total_spent": 0
            }
        }
    }))
    
    (history_dir / "01.jsonl").write_text(json.dumps({
        "type": "escrow_create", 
        "author": "AGENT1@TEST", 
        "amount": 100,
        "idem_key": "tx2"
    }) + "\n")
    
    out = run_checker(ledger_dir)
    assert out["status"] == "PASS"

def test_gap_json_decode_break(tmp_path):
    """
    # GAP: JSON Decode Error breaks the entire line
    # Exploit mechanism: `_extract_objects` catches json.JSONDecodeError and `break`s, 
    # discarding the rest of the line. If a line starts with invalid JSON but contains 
    # valid JSON events later, the valid events are ignored, allowing a bypass.
    """
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()
    
    (ledger_dir / "balances.json").write_text(json.dumps({
        "agents": {
            "agent1@test": {
                "total_spent": 0
            }
        }
    }))
    
    valid_event = json.dumps({
        "type": "escrow_create", 
        "author": "agent1@test", 
        "amount": 100,
        "idem_key": "tx3"
    })
    (history_dir / "01.jsonl").write_text(f'garbagedata{valid_event}\n')
    
    out = run_checker(ledger_dir)
    assert out["status"] == "PASS"

def test_gap_duplicate_idem_keys(tmp_path):
    """
    # GAP: Duplicate idem_keys are double-counted
    # Exploit mechanism: The script does not track `idem_key`. If an event is duplicated 
    # in the history, its amount is added twice. If balances.json also incorrectly 
    # double-counted the amount, the script returns PASS, masking the idempotency failure.
    """
    ledger_dir = tmp_path / "ledger"
    ledger_dir.mkdir()
    history_dir = ledger_dir / "history"
    history_dir.mkdir()
    
    (ledger_dir / "balances.json").write_text(json.dumps({
        "agents": {
            "agent1@test": {
                "total_spent": 200
            }
        }
    }))
    
    event = json.dumps({
        "type": "escrow_create", 
        "author": "agent1@test", 
        "amount": 100,
        "idem_key": "tx4"
    })
    (history_dir / "01.jsonl").write_text(f'{event}\n{event}\n')
    
    out = run_checker(ledger_dir)
    assert out["status"] == "PASS"
