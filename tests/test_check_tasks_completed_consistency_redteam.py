import sys
from pathlib import Path
import pytest
import json
import tempfile

# Add scripts to sys.path so we can import the module
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import check_tasks_completed_consistency as checker

def test_event_type_filtering():
    """Test that non-task events do not increment tasks_completed."""
    events = [
        {"type": "trajectory_mint", "agent": "alice", "amount": 100, "issue": 1},
        {"type": "escrow_create", "agent": "alice", "amount": 100, "issue": 2},
        {"type": "escrow_return", "agent": "alice", "amount": 100, "issue": 3},
        {"type": "verification", "agent": "alice", "amount": 100, "issue": 4},
        {"type": "payment", "agent": "alice", "amount": 100, "issue": 5},
    ]
    computed = checker.compute_tasks_completed(events)
    assert computed.get("alice") == 1


def test_issue_field_parsing():
    """Test issue field parsing for various valid and invalid formats."""
    events = [
        {"type": "payment", "agent": "bob", "amount": 10, "issue": None},  # skipped
        {"type": "payment", "agent": "bob", "amount": 10},  # missing, skipped
        {"type": "payment", "agent": "bob", "amount": 10, "issue": 10.5},  # float, parsed as 10
        {"type": "payment", "agent": "bob", "amount": 10, "issue": "20"},  # string, parsed as 20
        {"type": "payment", "agent": "bob", "amount": 10, "issue": "20 "},  # string with space, parsed as 20
    ]
    computed = checker.compute_tasks_completed(events)
    # 10.5 -> 10, "20" -> 20, "20 " -> 20. Distinct issues: 10, 20
    assert computed.get("bob") == 2


def test_agent_attribution():
    """Test agent field absence or mismatch."""
    events = [
        {"type": "payment", "amount": 10, "issue": 1},  # absent agent
        {"type": "payment", "agent": "", "amount": 10, "issue": 2},  # empty string
        {"type": "payment", "agent": None, "amount": 10, "issue": 3},  # None
        {"type": "payment", "agent": "charlie", "amount": 10, "issue": 4},
    ]
    computed = checker.compute_tasks_completed(events)
    assert computed.get("charlie") == 1
    assert "" not in computed
    assert None not in computed


def test_multi_event_deduplication():
    """Test that multiple events for the same issue only count once."""
    events = [
        {"type": "accept", "agent": "dave", "amount": 5, "issue": 42},
        {"type": "payment", "agent": "dave", "amount": 10, "issue": 42},
        {"type": "payment", "agent": "dave", "amount": 20, "issue": 42},
        {"type": "payment", "agent": "dave", "amount": 10, "issue": 43},
    ]
    computed = checker.compute_tasks_completed(events)
    assert computed.get("dave") == 2


def test_empty_history():
    """Test agent with tasks_completed=0 and no history."""
    stored_agents = {"eve": {"tasks_completed": 0}}
    computed = {}
    status, div, warn, summ = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(div) == 0


def test_bypass_non_dict_agent_info():
    """
    # BYPASS: If an agent's info in balances.json is not a dict (e.g., a list or string),
    # check_consistency skips the divergence check via `if not isinstance(info, dict): continue`.
    # Furthermore, because the agent ID is still `in stored_agents`, it is skipped in the second
    # loop (which checks for history-only agents). This completely hides any divergence and returns PASS.
    """
    stored_agents = {
        "hacker_agent": []  # Not a dict
    }
    computed = {
        "hacker_agent": 500  # Agent actually has 500 completed tasks in history
    }
    
    status, div, warn, summ = checker.check_consistency(stored_agents, computed)
    
    assert status == "PASS"
    assert len(div) == 0
    assert len(warn) == 0


def test_bypass_unparseable_issue_id():
    """
    # BYPASS: compute_tasks_completed silently catches ValueError/TypeError for issue types
    # that int() cannot parse (e.g., "123a" or [123]) and ignores the event.
    # An attacker can have tasks_completed=0 in balances.json while having
    # actual payments with unparseable string issue IDs, and the checker will PASS.
    """
    events = [
        {"type": "payment", "agent": "sneaky", "amount": 100, "issue": "404a"},
        {"type": "payment", "agent": "sneaky", "amount": 100, "issue": "invalid"},
        {"type": "accept", "agent": "sneaky", "amount": 50, "issue": [1]},
    ]
    
    computed = checker.compute_tasks_completed(events)
    
    # The checker computes 0 tasks completed due to silently continuing on ValueError/TypeError
    assert computed.get("sneaky", 0) == 0
    
    # When matched against a balances.json that also claims 0, it passes
    stored_agents = {"sneaky": {"tasks_completed": 0}}
    status, div, warn, summ = checker.check_consistency(stored_agents, computed)
    
    assert status == "PASS"
    assert len(div) == 0


def test_bypass_missing_agent_passes():
    """
    # BYPASS: If an agent is completely missing from balances.json but has
    # tasks completed in history, the checker adds a warning but does NOT
    # add a divergence. The script sets status to "PASS" if divergences is empty,
    # completely ignoring warnings. This means deleting an agent from balances.json
    # bypasses the failure state.
    """
    stored_agents = {}
    computed = {
        "deleted_agent": 5
    }
    status, div, warn, summ = checker.check_consistency(stored_agents, computed)
    
    assert status == "PASS"
    assert len(div) == 0
    assert len(warn) == 1


def test_bypass_event_type_case_sensitivity():
    """
    # BYPASS: The event type check is strictly lowercase `if t not in ("payment", "accept"):`.
    # If an attacker manages to write an event with type "Payment" or "PAYMENT" into history,
    # compute_tasks_completed ignores it. Then a balances.json with tasks_completed=0 will PASS.
    """
    events = [
        {"type": "Payment", "agent": "mallory", "amount": 10, "issue": 1},
        {"type": "ACCEPT", "agent": "mallory", "amount": 10, "issue": 2},
    ]
    computed = checker.compute_tasks_completed(events)
    
    assert computed.get("mallory", 0) == 0
    
    stored_agents = {"mallory": {"tasks_completed": 0}}
    status, div, warn, summ = checker.check_consistency(stored_agents, computed)
    
    assert status == "PASS"
    assert len(div) == 0


def test_bypass_invalid_json_line():
    """
    # BYPASS: _iter_events silently catches json.JSONDecodeError and continues.
    # If a history file line is maliciously corrupted or truncated, the event is
    # ignored, computing a lower tasks_completed. If balances.json reflects this
    # artificially lowered count, the checker returns PASS.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        history_file = tmp_path / "1.jsonl"
        
        # Write one valid event and one corrupted event
        history_file.write_text(
            '{"type": "payment", "agent": "eve", "amount": 10, "issue": 1}\n'
            '{"type": "payment", "agent": "eve", "amount": 10, "issue": 2, \n' # Invalid JSON
        )
        
        events = checker._iter_events(tmp_path)
        assert len(events) == 1
        
        computed = checker.compute_tasks_completed(events)
        assert computed.get("eve") == 1
        
        stored_agents = {"eve": {"tasks_completed": 1}}
        status, div, warn, summ = checker.check_consistency(stored_agents, computed)
        
        assert status == "PASS"
        assert len(div) == 0
