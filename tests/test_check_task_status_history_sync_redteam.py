"""
Red Team Tests for check_task_status_history_sync.py

This file codifies bypass vectors found in the synchronization checker.
"""

import json
from pathlib import Path
from scripts.check_task_status_history_sync import run

def setup_repo(tmp_path: Path, task_index: dict, history_events: list[dict]):
    ledger = tmp_path / "ledger"
    history = ledger / "history"
    history.mkdir(parents=True)
    
    (ledger / "task_index.json").write_text(json.dumps(task_index))
    
    lines = [json.dumps(e) for e in history_events]
    (history / "events.jsonl").write_text("\n".join(lines))
    
    return tmp_path

def test_bypass_status_case_mismatch(tmp_path):
    """
    Bypass Vector 1: Status Case Mismatch
    The script explicitly checks for 'paid', 'open', 'claimed', 'rejected'.
    If an attacker manually edits task_index.json to set status to 'PAID',
    the script falls into the 'else' (SKIP) branch and returns a PASS (0),
    completely bypassing the requirement for an 'accept' event in history.
    """
    task_index = {
        "tasks": {
            "100": {
                "status": "PAID",
                "agent": "malicious@agent"
            }
        }
    }
    # No accept event in history!
    history_events = []
    
    root = setup_repo(tmp_path, task_index, history_events)
    result, passed = run(root)
    
    assert passed is True
    assert result["status"] == "PASS"
    assert result["checks"][0]["result"] == "SKIP"
    assert "not covered by consistency rules" in result["checks"][0]["note"]

def test_bypass_agent_id_ignored(tmp_path):
    """
    Bypass Vector 2: Agent ID Validation Missing
    The script checks if *any* 'accept' event exists for the issue number.
    It does not verify that the 'agent' in task_index.json matches the 'agent'
    in the history event. An attacker can edit task_index.json to change the
    agent to themselves, stealing credit for the task, and the checker passes.
    """
    task_index = {
        "tasks": {
            "101": {
                "status": "paid",
                "agent": "attacker@agent"  # Changed from victim
            }
        }
    }
    history_events = [
        {
            "type": "accept",
            "issue": 101,
            "agent": "victim@agent"  # Original correct agent
        }
    ]
    
    root = setup_repo(tmp_path, task_index, history_events)
    result, passed = run(root)
    
    assert passed is True
    assert result["status"] == "PASS"
    assert result["checks"][0]["result"] == "PASS"

def test_bypass_trajectory_mint_list_format(tmp_path):
    """
    Bypass Vector 3: trajectory_mint 'agents' list blindness (False Positive)
    The script expects trajectory_mint events to have a top-level 'issue' field.
    If the event uses the common 'agents' list format for batched payouts,
    the script fails to extract the issue number. This causes a valid 'paid'
    task to trigger a FAIL, allowing a denial-of-service on the CI pipeline.
    """
    task_index = {
        "tasks": {
            "102": {
                "status": "paid",
                "agent": "legit@agent"
            }
        }
    }
    history_events = [
        {
            "type": "trajectory_mint",
            # No top-level 'issue' field
            "agents": [
                {"agent": "legit@agent", "issue": 102}
            ]
        }
    ]
    
    root = setup_repo(tmp_path, task_index, history_events)
    result, passed = run(root)
    
    assert passed is False
    assert result["status"] == "FAIL"
    assert result["checks"][0]["result"] == "FAIL"
    assert "no 'accept' or 'trajectory_mint' event found" in result["checks"][0]["note"]

def test_bypass_issue_type_confusion(tmp_path):
    """
    Bypass Vector 4: Issue Type Confusion (bool to int)
    The script converts the history event 'issue' field using int().
    If an event maliciously or accidentally contains issue: True, int(True) 
    evaluates to 1. This incorrectly satisfies the payment check for issue "1".
    """
    task_index = {
        "tasks": {
            "1": {
                "status": "paid",
                "agent": "attacker@agent"
            }
        }
    }
    history_events = [
        {
            "type": "accept",
            "issue": True,  # Evaluates to 1 in Python
            "agent": "attacker@agent"
        }
    ]
    
    root = setup_repo(tmp_path, task_index, history_events)
    result, passed = run(root)
    
    assert passed is True
    assert result["status"] == "PASS"
    assert result["checks"][0]["result"] == "PASS"
