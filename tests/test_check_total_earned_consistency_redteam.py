import json
from pathlib import Path
from scripts.check_balances_earned_consistency import check_consistency, compute_earned_spent

def test_bypass_non_dict_agent():
    # BYPASS: An agent with a non-dict value in stored_agents completely bypasses both the divergence check and the warning check.
    # The script uses `if not isinstance(info, dict): continue`, ignoring the agent.
    # Then in the warning loop, `if agent_id in stored_agents: continue` skips the warning.
    # So the script exits 0, even though hacker has 1000 computed_earned and no valid stored_earned.
    events = [
        {"type": "payment", "agent": "hacker@platform", "amount": 1000}
    ]
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents = {
        "hacker@platform": 1000  # Not a dict!
    }
    status, divergences, warnings, _ = check_consistency(stored_agents, computed_earned, computed_spent)
    assert status == "PASS"
    assert len(divergences) == 0
    assert len(warnings) == 0

def test_bypass_type_mismatch_escrow_issue():
    # BYPASS: escrow_create uses an integer issue ID, but escrow_return uses a string issue ID.
    # The script uses `issue not in escrow_create_issues`, comparing `"123" not in {123}`, which is True.
    # The escrow_return is skipped, computed_earned remains 0. If stored_earned is 0, it passes.
    # We successfully hide income!
    events = [
        {"type": "escrow_create", "author": "client@platform", "amount": 500, "issue": 123},
        {"type": "escrow_return", "recipient": "hacker@platform", "amount": 500, "issue": "123"}
    ]
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents = {
        "client@platform": {"total_spent": 500, "total_earned": 0},
        "hacker@platform": {"total_spent": 0, "total_earned": 0}
    }
    status, divergences, warnings, _ = check_consistency(stored_agents, computed_earned, computed_spent)
    assert status == "PASS"
    assert len(divergences) == 0

def test_bypass_trajectory_mint_string_agents():
    # BYPASS: trajectory_mint with `agents` as a string instead of a list.
    # The script does `for i, a in enumerate("hacker@platform"):`, assigning amounts to agents "h", "a", "c", etc.
    # The actual agent "hacker@platform" gets 0 computed_earned.
    # If stored_earned is 0, it passes (divergences = 0).
    events = [
        {"type": "trajectory_mint", "agents": "hacker@platform", "per_agent": [1000]}
    ]
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents = {
        "hacker@platform": {"total_earned": 0, "total_spent": 0}
    }
    status, divergences, warnings, _ = check_consistency(stored_agents, computed_earned, computed_spent)
    assert status == "PASS"
    assert len(divergences) == 0

def test_bypass_event_type_whitespace():
    # BYPASS: Event type has trailing whitespace, e.g., "payment ".
    # The script matches exactly `t in ("payment", "accept")`, so it skips the event.
    # Income is hidden, computed_earned is 0, matching stored_earned = 0.
    events = [
        {"type": "payment ", "agent": "hacker@platform", "amount": 1000}
    ]
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents = {
        "hacker@platform": {"total_earned": 0, "total_spent": 0}
    }
    status, divergences, warnings, _ = check_consistency(stored_agents, computed_earned, computed_spent)
    assert status == "PASS"
    assert len(divergences) == 0

def test_bypass_duplicate_events():
    # BYPASS: The script does not deduplicate events.
    # An attacker duplicates an event to inflate both computed_earned and stored_earned.
    # The script exits 0, confirming the "consistency" of an invalid duplicated ledger.
    events = [
        {"type": "payment", "agent": "hacker@platform", "amount": 1000, "id": "tx1"},
        {"type": "payment", "agent": "hacker@platform", "amount": 1000, "id": "tx1"} # Exact duplicate
    ]
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents = {
        "hacker@platform": {"total_earned": 2000, "total_spent": 0}
    }
    status, divergences, warnings, _ = check_consistency(stored_agents, computed_earned, computed_spent)
    assert status == "PASS"
    assert len(divergences) == 0

def test_bypass_escrow_return_missing_issue():
    # BYPASS: escrow_return without an issue field.
    # `issue = e.get("issue")` returns None.
    # If there is ANY escrow_create without an issue field, `None` is in `escrow_create_issues`.
    # Then `None not in escrow_create_issues` is False, so it counts the return!
    # This allows old/invalid escrow returns to be counted if a single invalid escrow_create exists.
    events = [
        {"type": "escrow_create", "author": "client@platform", "amount": 500}, # issue is None
        {"type": "escrow_return", "recipient": "hacker@platform", "amount": 1000} # issue is None
    ]
    computed_earned, computed_spent = compute_earned_spent(events)
    stored_agents = {
        "client@platform": {"total_spent": 500, "total_earned": 0},
        "hacker@platform": {"total_spent": 0, "total_earned": 1000}
    }
    status, divergences, warnings, _ = check_consistency(stored_agents, computed_earned, computed_spent)
    assert status == "PASS"
    assert len(divergences) == 0
