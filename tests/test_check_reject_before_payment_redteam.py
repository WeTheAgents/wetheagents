import json
import pytest
from pathlib import Path
from typing import Any

from scripts.check_reject_before_payment import run_check

def create_history_file(tmp_path: Path, filename: str, events: list[dict[str, Any]]):
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    file_path = history_dir / filename
    with file_path.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")

def test_bypass_op_name_capitalization(tmp_path: Path):
    """
    Investigate: Op name capitalization ('Reject' vs 'reject')
    Finding: BYPASS. The checker does not normalize op names, so 'Reject' is ignored.
    A subsequent 'payment' is not flagged as a violation.
    """
    events = [
        {"type": "Reject", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "PASS"

def test_bypass_agent_id_case_mismatch(tmp_path: Path):
    """
    Investigate: Agent ID case mismatch ('claude-1@claude' vs 'Claude-1@claude')
    Finding: BYPASS. The checker groups by agent ID string without case normalization.
    """
    events = [
        {"type": "reject", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "Claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "PASS"

def test_defended_issue_number_type_mismatch(tmp_path: Path):
    """
    Investigate: Issue number type mismatch (int vs string)
    Finding: DEFENDED. The checker parses the issue field into an integer.
    A string issue ID will be matched with the int issue ID.
    """
    events = [
        {"type": "reject", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": "42", "agent": "claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "FAIL"
    assert report["violations"][0]["issue"] == 42

def test_bypass_missing_op_field(tmp_path: Path):
    """
    Investigate: Missing op field (no 'type' key)
    Finding: BYPASS. The checker skips events without a 'type' key.
    A reject without a type is not registered, allowing a payment.
    """
    events = [
        {"issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "PASS"

def test_defended_empty_agent_field(tmp_path: Path):
    """
    Investigate: Empty agent field
    Finding: DEFENDED (Skip). Events with an empty agent field are silently skipped;
    they cannot form a valid (issue, agent) pair. The payment is also skipped, so
    no violation is recorded and the check returns PASS — both sides invisible.
    Note: original behavior was ValueError (crash → FAIL); changed to skip by T4S26 spec closure.
    """
    events = [
        {"type": "reject", "issue": 42, "agent": "", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert report["violations"] == []
