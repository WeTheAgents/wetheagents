import json
import pytest
import sys
from pathlib import Path
from unittest.mock import patch
import io
import contextlib

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))

from scripts import check_balances_earned_consistency

@pytest.fixture
def temp_ledger(tmp_path):
    ledger_dir = tmp_path / "ledger"
    history_dir = ledger_dir / "history"
    history_dir.mkdir(parents=True)
    
    def write_ledger(balances, history_events):
        with open(ledger_dir / "balances.json", "w") as f:
            json.dump(balances, f)
        
        with open(history_dir / "0001.jsonl", "w") as f:
            for event in history_events:
                f.write(json.dumps(event) + "\n")
                
    return tmp_path, write_ledger

def run_checker(tmp_path):
    with patch("scripts.check_balances_earned_consistency._repo_root", return_value=tmp_path):
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            exit_code = check_balances_earned_consistency.main()
        output = json.loads(f.getvalue())
        return exit_code, output

def test_bypass_1_negative_accept_ignored(temp_ledger):
    # Spec: accept uses amount (no positive-only restriction). Code: requires amount > 0.
    # Attacker posts an accept with negative amount, true earned should be -100.
    # Checker computes 0. Attacker puts 0 in balances.json and bypasses.
    tmp_path, write_ledger = temp_ledger
    events = [
        {"type": "accept", "agent": "attacker@system", "amount": -100}
    ]
    balances = {
        "agents": {
            "attacker@system": {
                "total_earned": 0,  # Checker will erroneously match this
                "total_spent": 0
            }
        }
    }
    write_ledger(balances, events)
    exit_code, out = run_checker(tmp_path)
    assert exit_code == 0
    assert out["status"] == "PASS"

def test_bypass_2_escrow_return_recipient_fallback(temp_ledger):
    # Spec: escrow_return -> amount when agent is the recipient.
    # Code: recip = e.get("recipient") or e.get("author") or e.get("agent", "")
    # Attacker creates escrow_return with recipient="" and author="attacker@system".
    tmp_path, write_ledger = temp_ledger
    events = [
        {"type": "escrow_create", "issue": 1, "author": "victim@system", "amount": 100},
        {"type": "escrow_return", "issue": 1, "recipient": "", "author": "attacker@system", "amount": 100}
    ]
    balances = {
        "agents": {
            "victim@system": {
                "total_earned": 0,
                "total_spent": 100
            },
            "attacker@system": {
                "total_earned": 100,  # Checker erroneously gives 100 to attacker
                "total_spent": 0
            }
        }
    }
    write_ledger(balances, events)
    exit_code, out = run_checker(tmp_path)
    assert exit_code == 0
    assert out["status"] == "PASS"

def test_bypass_3_issue_type_mismatch(temp_ledger):
    # Spec: match escrow_create and escrow_return on issue.
    # Code uses set which distinguishes int 1 and str "1".
    tmp_path, write_ledger = temp_ledger
    events = [
        {"type": "escrow_create", "issue": 1, "author": "victim@system", "amount": 100},
        {"type": "escrow_return", "issue": "1", "recipient": "victim@system", "amount": 100}
    ]
    balances = {
        "agents": {
            "victim@system": {
                "total_earned": 0, # Should be 100, but checker skips it as old-format
                "total_spent": 100
            }
        }
    }
    write_ledger(balances, events)
    exit_code, out = run_checker(tmp_path)
    assert exit_code == 0
    assert out["status"] == "PASS"

def test_bypass_4_empty_agents_list(temp_ledger):
    # Spec: amount for single-agent format (no agents[] list).
    # Code checks `if agents_list:` which is falsy for [].
    tmp_path, write_ledger = temp_ledger
    events = [
        {"type": "trajectory_mint", "agents": [], "agent": "attacker@system", "amount": 100}
    ]
    balances = {
        "agents": {
            "attacker@system": {
                "total_earned": 100, # Checker erroneously credits 100
                "total_spent": 0
            }
        }
    }
    write_ledger(balances, events)
    exit_code, out = run_checker(tmp_path)
    assert exit_code == 0
    assert out["status"] == "PASS"

def test_bypass_5_missing_issue_cross_pollution(temp_ledger):
    # Spec: old-format escrow_return (pre-dating escrow_create) are excluded.
    # Code: if issue not in escrow_create_issues. If both miss 'issue', it's None in set.
    tmp_path, write_ledger = temp_ledger
    events = [
        {"type": "escrow_create", "author": "victim@system", "amount": 10},
        {"type": "escrow_return", "recipient": "attacker@system", "amount": 100}
    ]
    balances = {
        "agents": {
            "victim@system": {
                "total_earned": 0,
                "total_spent": 10
            },
            "attacker@system": {
                "total_earned": 100, # Checker erroneously credits 100
                "total_spent": 0
            }
        }
    }
    write_ledger(balances, events)
    exit_code, out = run_checker(tmp_path)
    assert exit_code == 0
    assert out["status"] == "PASS"

def test_bypass_6_negative_escrow_create(temp_ledger):
    # Code just adds amount to spent without checking > 0.
    tmp_path, write_ledger = temp_ledger
    events = [
        {"type": "escrow_create", "issue": 1, "author": "attacker@system", "amount": -500}
    ]
    balances = {
        "agents": {
            "attacker@system": {
                "total_earned": 0,
                "total_spent": -500 # Checker erroneously allows negative spent
            }
        }
    }
    write_ledger(balances, events)
    exit_code, out = run_checker(tmp_path)
    assert exit_code == 0
    assert out["status"] == "PASS"
