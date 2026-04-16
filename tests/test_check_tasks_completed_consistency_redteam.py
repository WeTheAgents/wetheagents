import sys
from pathlib import Path

# Add scripts dir to path to import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import check_tasks_completed_consistency as checker

def test_normal_pass():
    stored_agents = {"agent1": {"tasks_completed": 1}}
    computed = {"agent1": 1}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(divergences) == 0

def test_normal_fail():
    stored_agents = {"agent1": {"tasks_completed": 1}}
    computed = {"agent1": 2}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "FAIL"
    assert len(divergences) == 1

def test_bypass_info_not_a_dict():
    # BYPASS: When an agent's value in balances.json is not a dict (e.g., None or a list),
    # the script skips it during the divergence check. Furthermore, because the agent ID
    # is present in stored_agents, it also skips it during the warning check!
    # This results in zero divergences and zero warnings, returning PASS.
    stored_agents = {"hacker": None}
    computed = {"hacker": 5}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(divergences) == 0
    assert len(warnings) == 0

def test_bypass_agent_type_mismatch():
    # BYPASS: If the history event parsed the agent as an integer (e.g., 123), 
    # it is stored in `computed` with an int key. But `stored_agents` from JSON
    # will always have string keys (e.g., "123"). `computed.get("123")` will miss the int key,
    # defaulting to 0, which matches stored_count=0. A warning is emitted but status is PASS.
    stored_agents = {"123": {"tasks_completed": 0}}
    computed = {123: 5}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(divergences) == 0
    assert len(warnings) == 1

def test_bypass_falsy_agent():
    # BYPASS: If an agent ID is falsy (e.g. empty string ""), the event is completely skipped
    # in compute_tasks_completed. This means history is ignored and it matches a stored count of 0.
    events = [{"type": "payment", "agent": "", "amount": 10, "issue": 1}]
    computed = checker.compute_tasks_completed(events)
    stored_agents = {"": {"tasks_completed": 0}}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(divergences) == 0

def test_bypass_missing_agent_warning_only():
    # BYPASS: An agent present in history with completed tasks but completely missing
    # from balances.json only generates a warning. The status remains PASS despite
    # the invariant strictly failing.
    stored_agents = {}
    computed = {"hacker": 5}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(divergences) == 0
    assert len(warnings) == 1

def test_issue_field_parsing_float_string():
    # BYPASS: If the issue field is a string representation of a float (e.g. "123.4"),
    # int("123.4") raises ValueError, and the event is silently ignored.
    events = [{"type": "payment", "agent": "a", "amount": 10, "issue": "123.4"}]
    computed = checker.compute_tasks_completed(events)
    assert "a" not in computed or computed["a"] == 0

def test_deduplication_of_same_issue():
    events = [
        {"type": "payment", "agent": "a", "amount": 10, "issue": 1},
        {"type": "accept", "agent": "a", "amount": 5, "issue": "1"},
        {"type": "payment", "agent": "a", "amount": 20, "issue": 1.0}
    ]
    computed = checker.compute_tasks_completed(events)
    assert computed.get("a") == 1

def test_empty_history_with_tasks_completed_0():
    stored_agents = {"a": {"tasks_completed": 0}}
    computed = {}
    status, divergences, warnings, summary = checker.check_consistency(stored_agents, computed)
    assert status == "PASS"
    assert len(divergences) == 0
