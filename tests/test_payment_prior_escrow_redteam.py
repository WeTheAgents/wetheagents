import json
import pytest
from pathlib import Path
from scripts.check_payment_has_prior_escrow import run_check

def write_history(tmp_path: Path, filename: str, events: list[dict]):
    history_dir = tmp_path / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    with open(history_dir / filename, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

def test_timestamp_collision_bypass(tmp_path):
    """
    Demonstrate that payments can bypass the prior-escrow check if they share
    the exact same timestamp as the escrow but are placed in a file that sorts
    alphabetically before the payment's file.
    """
    # Escrow in a.jsonl, Payment in z.jsonl. Both have same timestamp.
    # a.jsonl sorts before z.jsonl, so escrow is processed first.
    write_history(tmp_path, "a.jsonl", [
        {"type": "escrow", "issue": 1, "timestamp": "2026-01-01T12:00:00Z"}
    ])
    write_history(tmp_path, "z.jsonl", [
        {"type": "payment", "issue": 1, "idem_key": "x", "timestamp": "2026-01-01T12:00:00Z"}
    ])
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert report["checked"] == 1
    assert not report["violations"]

def test_case_format_variation_bypass(tmp_path):
    """
    Demonstrate that type and format variations allow bypasses.
    Escrow created for integer 123, but payment is for string "123".
    Because the script stringifies issue numbers, the payment passes.
    """
    write_history(tmp_path, "history.jsonl", [
        {"type": "escrow", "issue": 123, "timestamp": "2026-01-01T12:00:00Z"},
        {"type": "payment", "issue": "123", "idem_key": "x", "timestamp": "2026-01-02T12:00:00Z"}
    ])
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert report["checked"] == 1

def test_multi_escrow_disambiguation_bypass(tmp_path):
    """
    Demonstrate that if an escrow is returned/refunded, the script still
    considers the issue to have a valid prior escrow forever.
    """
    write_history(tmp_path, "history.jsonl", [
        {"type": "escrow", "issue": 5, "timestamp": "2026-01-01T12:00:00Z"},
        {"type": "escrow_refund", "issue": 5, "timestamp": "2026-01-02T12:00:00Z"},
        {"type": "payment", "issue": 5, "idem_key": "x", "timestamp": "2026-01-03T12:00:00Z"}
    ])
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert report["checked"] == 1

def test_partial_issue_match_vulnerability(tmp_path):
    """
    Demonstrate bypass for mismatched issue numbers (issue 99 vs 999).
    Even if only escrow for 999 exists, a payment for 99 can completely
    bypass validation by omitting the idem_key (legacy exception exploit).
    """
    write_history(tmp_path, "history.jsonl", [
        {"type": "escrow", "issue": "999", "timestamp": "2026-01-01T12:00:00Z"},
        # Payment for 99 has no idem_key -> throws warning, but PASSES check
        {"type": "payment", "issue": "99", "timestamp": "2026-01-02T12:00:00Z"} 
    ])
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert any(w["reason"] == "keyless_payment_without_prior_escrow" for w in report["warnings"])

def test_missing_timestamp_bypass(tmp_path):
    """
    Demonstrate that omitting the timestamp field from a payment completely
    bypasses the prior escrow validation check.
    """
    write_history(tmp_path, "history.jsonl", [
        {"type": "escrow", "issue": 1, "timestamp": "2026-01-01T12:00:00Z"},
        {"type": "payment", "issue": 2, "idem_key": "x"} # Missing timestamp
    ])
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert any(w["reason"] == "payment_missing_timestamp_no_prior_escrow" for w in report["warnings"])

def test_predates_first_escrow_bypass(tmp_path):
    """
    Demonstrate that placing a payment before the very first escrow in the system
    bypasses validation.
    """
    write_history(tmp_path, "history.jsonl", [
        {"type": "escrow", "issue": 100, "timestamp": "2026-01-02T12:00:00Z"},
        {"type": "payment", "issue": 200, "idem_key": "x", "timestamp": "2026-01-01T12:00:00Z"}
    ])
    report = run_check(tmp_path)
    assert report["status"] == "PASS"
    assert any(w["reason"] == "payment_predates_first_escrow_event" for w in report["warnings"])
