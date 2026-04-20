import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_single_escrow_per_issue import run_check

def _make_repo(tmp_path: Path, events: list[dict], filename: str = "events.jsonl") -> Path:
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(e) for e in events)
    (history_dir / filename).write_text(content, encoding="utf-8")
    return tmp_path

def test_bypass_op_capitalization(tmp_path):
    """
    Bypass Vector: Op name capitalization.
    The checker matches strictly on lower-case strings ("escrow_create").
    By capitalizing the op ("Escrow_create"), the event type is ignored, 
    allowing a second escrow for the same issue to bypass detection.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_create", "issue": 42},
        # Capitalized type -> ignored by _OPEN_EVENT_TYPES -> bypass!
        {"type": "Escrow_create", "issue": 42},
    ])
    result = run_check(repo)
    # The second create is skipped, so peak_open_escrows remains 1 -> PASS (false negative).
    assert result["status"] == "PASS"
    assert result["stats"]["issues_with_multiple_active_escrows"] == 0

def test_investigate_issue_number_type(tmp_path):
    """
    Investigation: Issue number type mismatch.
    Does the checker treat `issue: 42` and `issue: "42"` as the same?
    Yes. `_normalize_issue` handles both `int` and `str` types, stripping and parsing strings.
    Thus, this is NOT a bypass vector. The checker correctly flags this.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_create", "issue": 42},
        {"type": "escrow_create", "issue": "42"},
    ])
    result = run_check(repo)
    # Checker correctly normalizes both to "42" and flags the double escrow.
    assert result["status"] == "FAIL"
    assert result["stats"]["issues_with_multiple_active_escrows"] == 1
    assert result["violations"][0]["open_escrows"] == 2

def test_investigate_mismatched_agent_id(tmp_path):
    """
    Investigation: Close event with mismatched agent ID.
    If agent A creates, and agent B closes, does it close?
    Yes. The checker completely ignores the agent ID.
    This means if a history has mismatched agents, the checker still successfully closes the escrow.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_create", "issue": 42, "agent": "A"},
        {"type": "accept", "issue": 42, "agent": "B"}, # Agent B closes
        {"type": "escrow_create", "issue": 42, "agent": "C"},
    ])
    result = run_check(repo)
    # The accept by agent B successfully closes the first escrow.
    # The second escrow is then valid -> PASS.
    assert result["status"] == "PASS"

def test_bypass_empty_op_field(tmp_path):
    """
    Bypass Vector: Empty op field.
    If an event lacks 'type', 'event', or 'op', _event_type returns None.
    The checker completely ignores the event, bypassing detection of double escrow.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_create", "issue": 42},
        # No op/type/event field
        {"issue": 42, "data": "hidden_escrow_create"},
    ])
    result = run_check(repo)
    # Second create is ignored -> PASS (false negative)
    assert result["status"] == "PASS"

def test_bypass_unsupported_issue_type(tmp_path):
    """
    Bypass Vector: Unsupported issue type (e.g., float).
    The `_normalize_issue` function only explicitly handles `int` and `str`.
    If `issue` is a float (e.g., 42.0), it returns None, and the event is ignored.
    This allows a second escrow to bypass detection.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_create", "issue": 42},
        # float issue -> _normalize_issue returns None -> event skipped -> bypass!
        {"type": "escrow_create", "issue": 42.0},
    ])
    result = run_check(repo)
    # The float-issue create is skipped -> PASS (false negative)
    assert result["status"] == "PASS"
    assert result["stats"]["issues_with_multiple_active_escrows"] == 0

def test_investigate_double_escrow_return(tmp_path):
    """
    Investigation: Two escrow_return events for the same issue.
    Does the counter go negative, hiding a subsequent double create?
    No. `current_count <= 1` calls `.pop()`. The counter never goes negative.
    Thus, a subsequent double escrow_create WILL be correctly flagged.
    """
    repo = _make_repo(tmp_path, [
        {"type": "escrow_create", "issue": 42},
        {"type": "escrow_return", "issue": 42},
        {"type": "escrow_return", "issue": 42}, # Counter drops to 0 (popped), not -1
        {"type": "escrow_create", "issue": 42},
        {"type": "escrow_create", "issue": 42}, # This will be detected as double escrow
    ])
    result = run_check(repo)
    # Correctly flags the last double create.
    assert result["status"] == "FAIL"
    assert result["stats"]["issues_with_multiple_active_escrows"] == 1
