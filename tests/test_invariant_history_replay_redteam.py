import pytest
from scripts.check_invariant_history_replay import replay, BASE_SUPPLY

def test_economy_reset_clears_violations():
    """
    VULNERABILITY: economy_reset completely clears all past violations.
    An attacker can hide any invariant breaks by appending an economy_reset event.
    """
    events = [
        # Malicious event that breaks invariant: mints 5000 to alice but only records 100 total_minted
        {
            "type": "trajectory_mint",
            "amount": 100,
            "agents": ["alice"],
            "per_agent": [5000],
            "timestamp": "2026-01-01T00:00:00Z"
        },
        # Economy reset clears the violations list
        {
            "type": "economy_reset",
            "new_supply": BASE_SUPPLY,
            "timestamp": "2026-01-02T00:00:00Z"
        }
    ]
    
    result = replay(events, strict_pool=False)
    
    # Script incorrectly reports PASS
    assert result["status"] == "PASS"
    assert len(result["violations"]) == 0

def test_missing_events_still_pass():
    """
    VULNERABILITY: The script only checks if individual events maintain the invariant locally.
    It does not check if the final state matches the actual ledger balances.
    Therefore, completely dropping 'payment' or 'escrow' events still returns PASS.
    """
    events = [
        # Normal escrow
        {
            "type": "escrow",
            "author": "alice",
            "amount": 100,
            "timestamp": "2026-01-01T00:00:00Z"
        },
        # Missing the corresponding payment entirely!
        # The script does not verify the end state against ledger/balances.json
    ]
    
    result = replay(events, strict_pool=False)
    
    assert result["status"] == "PASS"
    # Escrow pool anomaly is recorded but status is PASS
    assert len(result["pool_anomalies"]) > 0

def test_escrow_batch_arbitrary_amounts():
    """
    VULNERABILITY: escrow_batch and other zero-sum events can specify ANY amount
    without breaking the invariant, allowing attackers to arbitrarily shift balances
    into the escrow pool or vice versa (which only causes a pool anomaly, not a FAIL).
    """
    events = [
        {
            "type": "escrow_batch",
            "author": "bob",
            "total": 999999,  # Ridiculous amount
            "timestamp": "2026-01-01T00:00:00Z"
        }
    ]
    
    result = replay(events, strict_pool=False)
    
    assert result["status"] == "PASS"
    assert len(result["violations"]) == 0
    # The anomaly is caught, but status is PASS
    assert len(result["pool_anomalies"]) > 0

def test_unrecognised_event_types_ignored():
    """
    VULNERABILITY: Unrecognised event types are silently ignored without failing.
    If the ledger adds a new event type or an attacker sneaks one in (e.g., 'transfer'),
    the script skips it and still passes.
    """
    events = [
        {
            "type": "malicious_stealth_transfer",
            "from": "agent0@system",
            "to": "hacker",
            "amount": 5000,
            "timestamp": "2026-01-01T00:00:00Z"
        }
    ]
    
    result = replay(events, strict_pool=False)
    
    # Silently ignores the event, status is PASS
    assert result["status"] == "PASS"
    assert len(result["violations"]) == 0

def test_agent_removal_manipulation():
    """
    VULNERABILITY: agent_removal deducts whatever balance the agent CURRENTLY has in the simulation,
    and then adds `balance_returned` and burns `mint_burned`.
    If an attacker crafts an event where `balance_returned - actual_balance == -mint_burned`,
    the invariant holds, even if `balance_returned` and `mint_burned` are completely fake!
    """
    # Start with alice having 100
    events = [
        {
            "type": "hello_world_mint",
            "agent": "alice",
            "amount": 100,
            "timestamp": "1"
        },
        # Now remove alice.
        # actual_balance = 100
        # We want: balance_returned - 100 == -mint_burned
        # Let's say balance_returned = 500. Then 500 - 100 = 400. So mint_burned = -400
        {
            "type": "agent_removal",
            "agent": "alice",
            "balance_returned": 500,
            "mint_burned": -400,
            "timestamp": "2"
        }
    ]
    
    result = replay(events, strict_pool=False)
    
    # The script accepts this absurd state and passes!
    assert result["status"] == "PASS"
    assert len(result["violations"]) == 0
