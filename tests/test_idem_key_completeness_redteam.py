import json
import pytest
from pathlib import Path
from typing import Any

from scripts.check_idem_key_completeness import (
    run_completeness_check,
    load_history_events,
)

def test_bypass_escrow_batch_skipped():
    """
    Bypass 1: 'escrow_batch' history events are completely ignored in the 
    VIOLATION check because they are absent from TARGET_HISTORY_TYPES.
    """
    events = [
        {"type": "escrow_batch", "issues": ["101", "102"], "timestamp": "2026-04-15"}
    ]
    all_idem_keys: dict[str, Any] = {}
    aliases: dict[str, str] = {}
    
    violations, warnings = run_completeness_check(all_idem_keys, events, aliases)
    
    # Red-team test: we EXPECT a violation for missing escrow keys, but the script bypasses it.
    # The vulnerability means violations == []
    assert len(violations) == 0, "Vulnerability fixed! escrow_batch is now checked."


def test_bypass_escrow_return_bulk_skipped():
    """
    Bypass 2: 'escrow_return_bulk' events are ignored for the same reason.
    """
    events = [
        {"type": "escrow_return_bulk", "issues": ["201"], "timestamp": "2026-04-15"}
    ]
    all_idem_keys: dict[str, Any] = {}
    aliases: dict[str, str] = {}
    
    violations, warnings = run_completeness_check(all_idem_keys, events, aliases)
    
    # Vulnerability: 0 violations reported despite no idem keys existing.
    assert len(violations) == 0, "Vulnerability fixed! escrow_return_bulk is now checked."


def test_bypass_escrow_actor_mismatch():
    """
    Bypass 3: Escrow check only validates the issue ID, not the actor.
    An attacker can make an escrow event for themselves using another agent's idem key.
    """
    events = [
        {"type": "escrow", "issue": "301", "agent": "Attacker", "timestamp": "2026-04-15"}
    ]
    all_idem_keys: dict[str, Any] = {
        # Valid idem key for Alice, NOT Attacker
        "escrow|301|Alice": "valid"
    }
    aliases: dict[str, str] = {}
    
    violations, warnings = run_completeness_check(all_idem_keys, events, aliases)
    
    # Vulnerability: script considers it completely valid because "301" is in classified["escrow"]
    assert len(violations) == 0, "Vulnerability fixed! escrow actor is now validated."


def test_bypass_payment_falsy_agent_fallback():
    """
    Bypass 4: payment events fallback: event.get("agent") or event.get("author") or ""
    If an attacker sets agent to falsy (like ""), it falls back to author.
    They can steal Alice's idem key by putting her in 'author'.
    """
    events = [
        {
            "type": "payment", 
            "issue": "401", 
            "agent": "",          # Attacker leaves agent empty (falsy)
            "author": "Alice",    # Falls back to Alice
            "timestamp": "2026-04-15"
        }
    ]
    all_idem_keys: dict[str, Any] = {
        "payment|401|Alice": "valid"
    }
    aliases: dict[str, str] = {}
    
    violations, warnings = run_completeness_check(all_idem_keys, events, aliases)
    
    # Vulnerability: script matches the payment to Alice and reports 0 violations
    assert len(violations) == 0, "Vulnerability fixed! agent fallback bypass closed."


def test_bypass_malformed_json_silently_ignored(tmp_path: Path):
    """
    Bypass 5: load_history_events uses try/except json.JSONDecodeError and 'continue's.
    An attacker can hide a malicious event by corrupting the JSON line.
    """
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    
    malicious_log = history_dir / "20260415.jsonl"
    malicious_log.write_text(
        '{"type": "payment", "issue": "501", "agent": "Attacker"}\n'
        '{"type": "payment", "issue": "502", "agent": "Attacker", \n'  # Corrupted line!
    )
    
    events = load_history_events(history_dir)
    
    # Vulnerability: The corrupted line is silently dropped. Only 1 event is loaded.
    assert len(events) == 1, "Vulnerability fixed! JSON errors are no longer silently ignored."
    assert events[0]["issue"] == "501"

def test_bypass_history_type_whitespace():
    """
    Bypass 6: event type whitespace padding.
    If an attacker submits an event with type 'payment ', it is not in TARGET_HISTORY_TYPES.
    It silently skips the violation check despite being a financial event variant.
    """
    events = [
        {"type": "payment ", "issue": "601", "agent": "Attacker", "timestamp": "2026-04-15"}
    ]
    all_idem_keys: dict[str, Any] = {}
    aliases: dict[str, str] = {}
    
    violations, warnings = run_completeness_check(all_idem_keys, events, aliases)
    
    # Vulnerability: No violation because "payment " is ignored.
    assert len(violations) == 0, "Vulnerability fixed! Whitespace variants are now checked."

