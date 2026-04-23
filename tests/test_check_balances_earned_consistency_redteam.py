import json
from pathlib import Path
from unittest import mock
import pytest

from scripts.check_balances_earned_consistency import main

"""
Red Team Bypass Vectors for check_balances_earned_consistency.py
"""

def test_bypass_type_spoofing(tmp_path: Path):
    """
    Severity: Critical
    Bypass Vector 1: Type Spoofing in Agent Dictionary
    
    Description:
    In `check_consistency`, the script iterates over `stored_agents` and skips checking
    any agent whose value is not a dictionary (`if not isinstance(info, dict): continue`).
    If an attacker changes an agent's entry in `balances.json` to a string (e.g. 
    `"agent-1@platform": "deleted"`), the script silently skips calculating divergences
    for this agent. Because the agent ID is still present as a key in `stored_agents`,
    it also bypasses the "history-only agent" warning loop. The script returns PASS
    (exit code 0) even though the agent's ledger data is completely missing/corrupted.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()
    
    # 1. Valid history for agent
    history_file = history / "0001.jsonl"
    history_file.write_text(json.dumps({"type": "payment", "agent": "Alice", "amount": 100}) + "\n")
    
    # 2. Spoofed balances.json (string instead of dict)
    balances_file = ledger / "balances.json"
    balances_file.write_text(json.dumps({
        "agents": {
            "Alice": "corrupted_or_deleted"
        }
    }))
    
    # 3. Check passes (returns 0) despite inconsistency
    with mock.patch("scripts.check_balances_earned_consistency._repo_root", return_value=tmp_path):
        assert main() == 0


def test_bypass_missing_agent_warning_only(tmp_path: Path):
    """
    Severity: High
    Bypass Vector 2: Missing Agent Deletion Warning Only
    
    Description:
    If an agent is entirely removed from `balances.json`, the script correctly computes
    their earned and spent totals from history, and notices they are absent from
    `stored_agents`. However, it only appends a warning to the `warnings` list and
    does not emit a divergence. The script evaluates `divergences == 0` and returns
    `PASS` (exit code 0). This allows a malicious actor to completely delete an agent
    with non-zero balances from the ledger, and the consistency checker will still pass.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()
    
    # 1. Valid history for agent
    history_file = history / "0001.jsonl"
    history_file.write_text(json.dumps({"type": "payment", "agent": "Bob", "amount": 200}) + "\n")
    
    # 2. Agent missing from balances.json completely
    balances_file = ledger / "balances.json"
    balances_file.write_text(json.dumps({
        "agents": {}
    }))
    
    # 3. Check passes (returns 0) despite inconsistency
    with mock.patch("scripts.check_balances_earned_consistency._repo_root", return_value=tmp_path):
        assert main() == 0


def test_bypass_invalid_json_silent_skip(tmp_path: Path):
    """
    Severity: High
    Bypass Vector 3: Invalid JSON Silent Skip
    
    Description:
    The event parsing loop catches `json.JSONDecodeError` and silently continues.
    If an attacker manually corrupts a line in `history/*.jsonl` (e.g., making it
    invalid JSON) and simultaneously reduces the corresponding agent's `total_earned`
    in `balances.json` by the exact amount of that event, the script will silently
    ignore the corrupted event, compute the reduced total, match `balances.json`,
    and return PASS. An inconsistency (corrupted history) exists, but the check passes.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()
    
    # 1. Corrupted history file (invalid JSON) + valid event
    history_file = history / "0001.jsonl"
    history_file.write_text(
        '{"type": "payment", "agent": "Charlie", "amount": 500\n' + # Missing closing brace
        json.dumps({"type": "payment", "agent": "Charlie", "amount": 100}) + "\n"
    )
    
    # 2. Balances only reflect the valid event, ignoring the 500
    balances_file = ledger / "balances.json"
    balances_file.write_text(json.dumps({
        "agents": {
            "Charlie": {"total_earned": 100, "total_spent": 0}
        }
    }))
    
    # 3. Check passes (returns 0) despite corrupted history file
    with mock.patch("scripts.check_balances_earned_consistency._repo_root", return_value=tmp_path):
        assert main() == 0


def test_bypass_negative_accept_amount(tmp_path: Path):
    """
    Severity: Medium
    Bypass Vector 4: Negative Accept Events Ignored
    
    Description:
    The spec states `accept` should be the amount when the agent matches. However,
    the implementation groups `payment` and `accept` together and enforces
    `if a and amount > 0:`. This incorrectly applies the 'positive only' rule
    of `payment` to `accept`. An attacker can inject an `accept` event with a
    negative amount, and the script will add 0. If `balances.json` is modified
    to match this skipped amount, the script returns PASS, hiding the negative
    accept anomaly.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()
    
    # 1. History contains a negative accept event and a normal payment
    history_file = history / "0001.jsonl"
    history_file.write_text(
        json.dumps({"type": "accept", "agent": "Dave", "amount": -50}) + "\n" +
        json.dumps({"type": "payment", "agent": "Dave", "amount": 100}) + "\n"
    )
    
    # 2. Balances reflect only the positive 100
    balances_file = ledger / "balances.json"
    balances_file.write_text(json.dumps({
        "agents": {
            "Dave": {"total_earned": 100, "total_spent": 0}
        }
    }))
    
    # 3. Check passes (returns 0) despite ignoring the negative accept
    with mock.patch("scripts.check_balances_earned_consistency._repo_root", return_value=tmp_path):
        assert main() == 0
