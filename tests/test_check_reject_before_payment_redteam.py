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
    Finding: DEFENDED. The type field is now normalized to lowercase before matching,
    so 'Reject' is treated as 'reject' and the subsequent payment is flagged.
    """
    events = [
        {"type": "Reject", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 42

def test_bypass_agent_id_case_mismatch(tmp_path: Path):
    """
    Investigate: Agent ID case mismatch ('claude-1@claude' vs 'Claude-1@claude')
    Finding: DEFENDED. Agent strings are now normalized to lowercase before use as
    dict keys, so 'Claude-1@claude' matches the stored reject for 'claude-1@claude'.
    """
    events = [
        {"type": "reject", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "Claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["issue"] == 42

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
    Finding: DEFENDED (Malformed). Events with no 'type' key are now counted in
    malformed_lines_skipped rather than silently ignored, making them visible.
    The payment is still allowed (no valid reject registered), but the malformed
    event is tracked and auditable.
    """
    events = [
        {"issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-01T12:00:00Z"},
        {"type": "payment", "issue": 42, "agent": "claude-1@claude", "timestamp": "2026-03-02T12:00:00Z"},
    ]
    create_history_file(tmp_path, "1.jsonl", events)
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert report["stats"]["malformed_lines_skipped"] == 1

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
