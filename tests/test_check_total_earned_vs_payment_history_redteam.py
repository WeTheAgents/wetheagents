import pytest
from scripts.check_total_earned_vs_payment_history import compute_total_earned, check_consistency

def test_format_ambiguity_agents_without_per_agent_bypass():
    """
    Finding: Format ambiguity (mint parsed two ways) - empty per_agent
    Classification: BYPASS
    Severity: HIGH

    If a mint entry has both 'agents' and 'agent', the script strictly assumes
    multi-agent format. However, if 'per_agent' is missing or shorter than
    'agents', the script skips adding the amount. If the entry was actually
    a valid single-agent format that happened to include an 'agents' field,
    the script will compute 0 instead of the correct amount, leading to a false FAIL.
    """
    events = [{
        "type": "trajectory_mint",
        "agents": ["alice"],
        "agent": "alice",
        "amount": 100
    }]
    earned = compute_total_earned(events)
    assert earned.get("alice", 0) == 0

def test_agent_string_normalization_bypass():
    """
    Finding: Agent string normalization missing (case, whitespace)
    Classification: BYPASS
    Severity: MEDIUM

    The compute_total_earned function fails to strip whitespace or normalize case
    for the agent field. This means "alice", "Alice", and "alice " are treated
    as different agents, causing both false PASS and false FAIL scenarios depending
    on balances.json.
    """
    events = [
        {"type": "payment", "agent": "alice ", "amount": 50},
        {"type": "payment", "agent": "Alice", "amount": 50}
    ]
    earned = compute_total_earned(events)
    assert "alice" not in earned
    assert earned.get("alice ", 0) == 50
    assert earned.get("Alice", 0) == 50

def test_history_event_type_matching_bypass():
    """
    Finding: History event type matching ignores case/whitespace
    Classification: BYPASS
    Severity: MEDIUM

    Event type matching strictly checks for exact string matches "payment" or "accept".
    If the event type is "Payment" or "payment ", it is ignored, leading to
    uncounted earnings and a false FAIL.
    """
    events = [{"type": "Payment", "agent": "alice", "amount": 100}]
    earned = compute_total_earned(events)
    assert earned.get("alice", 0) == 0

def test_zero_amount_mints_bypass():
    """
    Finding: Zero-amount mints bypass warning logic
    Classification: BYPASS
    Severity: LOW

    The script explicitly filters out zero-amount mints by checking `amount > 0`.
    While a zero amount doesn't change `total_earned`, agents who only have
    zero-amount mints will be completely ignored when checking for warnings
    (agents present in history but missing from balances.json). This allows
    ghost agents to hide in the history without warning.
    """
    events = [{"type": "payment", "agent": "ghost", "amount": 0}]
    earned = compute_total_earned(events)
    assert "ghost" not in earned

def test_concurrent_format_fields_bypass():
    """
    Finding: Concurrent format fields cause amount shadowing
    Classification: BYPASS
    Severity: HIGH

    If a mint entry contains both multi-agent ('agents', 'per_agent') and
    single-agent ('agent', 'amount') fields, the script prioritizes the
    multi-agent fields and ignores the single-agent fields. If the ledger
    actually credits both, or prefers the single-agent format, the script
    will under-calculate, causing a false FAIL or missing a real mismatch.
    """
    events = [{
        "type": "trajectory_mint",
        "agents": ["alice"],
        "per_agent": [20],
        "agent": "alice",
        "amount": 80
    }]
    earned = compute_total_earned(events)
    assert earned.get("alice", 0) == 20

def test_missing_amount_field_type_error_bypass():
    """
    Finding: Null amount field causes TypeError crash
    Classification: BYPASS
    Severity: HIGH

    If the amount field is explicitly null, `e.get("amount", 0)` returns None,
    and `int(None)` raises a TypeError, crashing the entire check script.
    This effectively denies the ability to audit the ledger.
    """
    events = [{"type": "payment", "agent": "alice", "amount": None}]
    with pytest.raises(TypeError):
        compute_total_earned(events)
