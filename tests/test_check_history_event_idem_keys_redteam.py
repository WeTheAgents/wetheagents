"""
Self-Roast / Findings Analysis:

Finding 1: Integer idem_key bypass (Real Vulnerability)
- Why it is real: `isinstance(idem_key, str)` skips any `idem_key` that is not a string (e.g., int, list, dict). If the actual ledger consumer allows integer idempotency keys, an attacker could use them to bypass the checker completely while still getting the ledger to process the event.
- Fixed by: converting `idem_key` to string with `str(idem_key)` instead of filtering by `isinstance`.

Finding 2: Empty string idem_key bypass (Edge Case / Minor Vulnerability)
- Why it is real: `if ... and idem_key:` treats empty strings as falsy and skips them. If `""` is parsed by the ledger as a valid key, the attacker bypasses the check.
- Fixed by: changing the condition to `if idem_key is not None:` so empty strings are evaluated and reported.

Finding 3: List payload in idem_keys.json (False Positive)
- Why it isn't a bypass, but a bug: If `idem_keys.json` is a top-level list `["key1"]`, `load_idem_keys` returns an empty set. This would cause all events with `idem_key` to fail (false positive), blocking valid operations.
- Fixed by: explicitly checking `if isinstance(payload, list)` and adding its items.

Finding 4: List inside "keys" block (False Positive)
- Why it isn't a bypass, but a bug: `load_idem_keys` assumed `payload["keys"]` must be a dictionary. If it was a list `{"keys": ["key1"]}`, it was ignored, causing false positives.
- Fixed by: adding `elif isinstance(nested, list):` to extract the keys.

Finding 5: Reserved words as valid keys (False Positive / Python Trap)
- Why it isn't a bypass, but a bug: `load_idem_keys` ignored "version" indiscriminately due to a Python trap (`isinstance(True, int)` is True!). So `{"version": True}` skipped "version" as a key, causing a false positive.
- Fixed by: changing the check to `type(v) is int` to safely ignore the integer schema version but include a boolean valid key.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_event_idem_keys import run_check

def _write_history(root: Path, filename: str, *events: object) -> None:
    history_dir = root / "ledger" / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) if isinstance(e, (dict, list)) else str(e) for e in events]
    text = "\n".join(lines) + "\n"
    (history_dir / filename).write_text(text, encoding="utf-8")

def _write_idem_keys(root: Path, payload: object) -> None:
    path = root / "ledger" / "idem_keys.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

def test_finding_1_integer_idem_key_bypass(temp_repo: Path) -> None:
    """
    Vulnerability: `scan_history` skips events where `idem_key` is not a string (e.g., an integer).
    This allows an attacker to bypass the check by using integer keys if the system accepts them.
    """
    _write_idem_keys(temp_repo, {})
    _write_history(temp_repo, "events.jsonl", {"idem_key": 12345, "type": "payment"})
    report, exit_code = run_check(temp_repo)
    # RED TEAM EXPECTATION: The check should catch this violation.
    assert exit_code == 1
    assert len(report["violations"]) == 1
    assert report["violations"][0]["idem_key"] == "12345"

def test_finding_2_empty_string_idem_key_bypass(temp_repo: Path) -> None:
    """
    Vulnerability: `scan_history` skips empty string `idem_key`s due to `and idem_key`.
    """
    _write_idem_keys(temp_repo, {})
    _write_history(temp_repo, "events.jsonl", {"idem_key": "", "type": "payment"})
    report, exit_code = run_check(temp_repo)
    # RED TEAM EXPECTATION: Empty string is a violation if not in idem_keys.json.
    assert exit_code == 1
    assert len(report["violations"]) == 1
    assert report["violations"][0]["idem_key"] == ""

def test_finding_3_list_payload_idem_keys_false_positive(temp_repo: Path) -> None:
    """
    Vulnerability: If `idem_keys.json` is a top-level list, `load_idem_keys` returns an empty set.
    """
    _write_idem_keys(temp_repo, ["key1", "key2"])
    _write_history(temp_repo, "events.jsonl", {"idem_key": "key1", "type": "payment"})
    report, exit_code = run_check(temp_repo)
    # RED TEAM EXPECTATION: This should PASS.
    assert exit_code == 0
    assert report["status"] == "PASS"

def test_finding_4_keys_as_list_false_positive(temp_repo: Path) -> None:
    """
    Vulnerability: `load_idem_keys` expects `payload["keys"]` to be a dict. If it's a list, it's skipped.
    """
    _write_idem_keys(temp_repo, {"keys": ["key1", "key2"]})
    _write_history(temp_repo, "events.jsonl", {"idem_key": "key1", "type": "payment"})
    report, exit_code = run_check(temp_repo)
    # RED TEAM EXPECTATION: This should PASS since "key1" is in the list.
    assert exit_code == 0
    assert report["status"] == "PASS"

def test_finding_5_reserved_word_false_positive(temp_repo: Path) -> None:
    """
    Vulnerability: `load_idem_keys` ignores "version" and "keys" at the top level indiscriminately.
    If an event legitimately uses "version" as a key, it causes a false positive.
    """
    _write_idem_keys(temp_repo, {"version": True})
    _write_history(temp_repo, "events.jsonl", {"idem_key": "version", "type": "payment"})
    report, exit_code = run_check(temp_repo)
    # RED TEAM EXPECTATION: This should PASS since "version" is an actual key here.
    assert exit_code == 0
    assert report["status"] == "PASS"
