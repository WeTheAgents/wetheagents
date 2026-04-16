"""Tests for scripts/check_mint_record_completeness.py

Covers: all 5 fields present (PASS), each individual missing field (FAIL),
        empty string (FAIL), missing 'mints' key (graceful FAIL),
        extra fields (PASS, non-strict), multiple incomplete mints reported together.
"""

import json
from pathlib import Path

import pytest

from scripts.check_mint_record_completeness import MANDATORY_FIELDS, _check_mints, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_complete_mint(**overrides) -> dict:
    """Return a fully-populated mint dict, with optional field overrides."""
    base = {
        "trajectory": "T1",
        "slot": 1,
        "idem_key": "trajectory_mint|T1|1",
        "frontier_closed": "Some frontier was closed",
        "artifact": "scripts/some_script.py",
        "evidence": "PR #100 merged. All tests pass.",
        "made_redundant": "Manual review of some thing",
        "redundancy_proof": "Script automates the manual step",
    }
    base.update(overrides)
    return base


def _write_mints(path: Path, mints: list, extra_top_level: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"version": 1, "mints": mints}
    if extra_top_level:
        data.update(extra_top_level)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Test 1: all 5 mandatory fields present → PASS
# ---------------------------------------------------------------------------

def test_all_fields_present_pass(tmp_path: Path) -> None:
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [_make_complete_mint()])

    report = run(tmp_path)

    assert report["status"] == "PASS"
    assert len(report["checks"]) == 1
    assert report["checks"][0]["status"] == "PASS"
    assert report["checks"][0]["missing_fields"] == []
    assert "1 complete" in report["summary"]
    assert "0 incomplete" in report["summary"]


# ---------------------------------------------------------------------------
# Tests 2–6: each individual missing field → FAIL
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("field", MANDATORY_FIELDS)
def test_single_missing_field_fails(tmp_path: Path, field: str) -> None:
    mint = _make_complete_mint()
    del mint[field]
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [mint])

    report = run(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["checks"]) == 1
    check = report["checks"][0]
    assert check["status"] == "FAIL"
    assert field in check["missing_fields"]
    assert "0 complete" in report["summary"]
    assert "1 incomplete" in report["summary"]


# ---------------------------------------------------------------------------
# Test 7: empty string value → FAIL
# ---------------------------------------------------------------------------

def test_empty_string_field_fails(tmp_path: Path) -> None:
    mint = _make_complete_mint(frontier_closed="")
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [mint])

    report = run(tmp_path)

    assert report["status"] == "FAIL"
    check = report["checks"][0]
    assert check["status"] == "FAIL"
    assert "frontier_closed" in check["missing_fields"]


# ---------------------------------------------------------------------------
# Test 8: whitespace-only string → FAIL (treated as empty)
# ---------------------------------------------------------------------------

def test_whitespace_only_field_fails(tmp_path: Path) -> None:
    mint = _make_complete_mint(artifact="   ")
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [mint])

    report = run(tmp_path)

    assert report["status"] == "FAIL"
    assert "artifact" in report["checks"][0]["missing_fields"]


# ---------------------------------------------------------------------------
# Test 9: missing 'mints' key → graceful FAIL with empty checks list
# ---------------------------------------------------------------------------

def test_missing_mints_key_graceful_fail(tmp_path: Path) -> None:
    p = tmp_path / "ledger" / "trajectory_mints.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1}), encoding="utf-8")

    report = run(tmp_path)

    assert report["status"] == "FAIL"
    assert report["checks"] == []
    assert "missing 'mints' key" in report["summary"]


# ---------------------------------------------------------------------------
# Test 10: extra fields present → PASS (non-strict validation)
# ---------------------------------------------------------------------------

def test_extra_fields_do_not_fail(tmp_path: Path) -> None:
    mint = _make_complete_mint(extra_custom_field="some value", another_field=42)
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [mint])

    report = run(tmp_path)

    assert report["status"] == "PASS"
    assert report["checks"][0]["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 11: multiple incomplete mints all reported together
# ---------------------------------------------------------------------------

def test_multiple_incomplete_mints_all_reported(tmp_path: Path) -> None:
    mint_a = _make_complete_mint(trajectory="T1", slot=1, idem_key="trajectory_mint|T1|1")
    del mint_a["frontier_closed"]

    mint_b = _make_complete_mint(trajectory="T2", slot=2, idem_key="trajectory_mint|T2|2")
    del mint_b["redundancy_proof"]
    mint_b["artifact"] = ""

    mint_ok = _make_complete_mint(trajectory="T3", slot=3, idem_key="trajectory_mint|T3|3")

    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [mint_a, mint_b, mint_ok])

    report = run(tmp_path)

    assert report["status"] == "FAIL"
    assert len(report["checks"]) == 3

    by_key = {c["idem_key"]: c for c in report["checks"]}
    assert by_key["trajectory_mint|T1|1"]["status"] == "FAIL"
    assert "frontier_closed" in by_key["trajectory_mint|T1|1"]["missing_fields"]

    assert by_key["trajectory_mint|T2|2"]["status"] == "FAIL"
    assert "redundancy_proof" in by_key["trajectory_mint|T2|2"]["missing_fields"]
    assert "artifact" in by_key["trajectory_mint|T2|2"]["missing_fields"]

    assert by_key["trajectory_mint|T3|3"]["status"] == "PASS"

    assert "2 incomplete" in report["summary"]
    assert "1 complete" in report["summary"]


# ---------------------------------------------------------------------------
# Test 12: empty mints list → PASS (no mints to validate)
# ---------------------------------------------------------------------------

def test_empty_mints_list_pass(tmp_path: Path) -> None:
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [])

    report = run(tmp_path)

    assert report["status"] == "PASS"
    assert report["checks"] == []
    assert "0 mints checked" in report["summary"]


# ---------------------------------------------------------------------------
# Test 13: file not found → graceful FAIL
# ---------------------------------------------------------------------------

def test_file_not_found_graceful_fail(tmp_path: Path) -> None:
    report = run(tmp_path)

    assert report["status"] == "FAIL"
    assert report["checks"] == []
    assert "not found" in report["summary"]


# ---------------------------------------------------------------------------
# Test 14: non-string field value (int instead of str) → FAIL
# ---------------------------------------------------------------------------

def test_non_string_field_value_fails(tmp_path: Path) -> None:
    mint = _make_complete_mint(evidence=12345)
    _write_mints(tmp_path / "ledger" / "trajectory_mints.json", [mint])

    report = run(tmp_path)

    assert report["status"] == "FAIL"
    assert "evidence" in report["checks"][0]["missing_fields"]
