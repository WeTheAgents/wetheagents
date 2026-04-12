"""Tests for scripts/check_history_schema.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_history_schema import SCHEMAS, FIELD_ALTERNATIVES, run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp_path: Path) -> Path:
    """Create minimal repo layout with an empty history directory."""
    (tmp_path / "ledger" / "history").mkdir(parents=True)
    return tmp_path


def _write_jsonl(history_dir: Path, filename: str, entries: list[dict]) -> Path:
    """Write entries as JSONL to history_dir/filename."""
    path = history_dir / filename
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n",
        encoding="utf-8",
    )
    return path


def _write_raw(history_dir: Path, filename: str, content: str) -> Path:
    """Write raw string content to history_dir/filename."""
    path = history_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. Valid payment passes
# ---------------------------------------------------------------------------

def test_valid_payment_passes(tmp_path: Path) -> None:
    """A well-formed payment entry produces no FAIL checks."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "payment",
                "agent": "Claude-1@claude",
                "amount": 10,
                "issue": 42,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert fails == []


# ---------------------------------------------------------------------------
# 2. Missing required field fails
# ---------------------------------------------------------------------------

def test_missing_amount_fails(tmp_path: Path) -> None:
    """Payment missing 'amount' triggers a required_fields FAIL."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "payment",
                "agent": "Claude-1@claude",
                # amount omitted
                "issue": 42,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result, passed = run(root)

    assert passed is False
    assert result["status"] == "FAIL"
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert len(fails) == 1
    assert fails[0]["check"] == "required_fields"
    assert "amount" in fails[0]["missing_fields"]


# ---------------------------------------------------------------------------
# 3. Null agent fails
# ---------------------------------------------------------------------------

def test_null_agent_fails(tmp_path: Path) -> None:
    """A payment with agent explicitly null triggers FAIL."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "payment",
                "agent": None,
                "amount": 5,
                "issue": 7,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(
        c["check"] == "required_fields" and "agent" in c.get("missing_fields", [])
        for c in fails
    )


# ---------------------------------------------------------------------------
# 4. Unknown type is warning, not error
# ---------------------------------------------------------------------------

def test_unknown_type_is_warn_not_fail(tmp_path: Path) -> None:
    """An entry with an unrecognised type is WARN, not FAIL, and overall PASS."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"type": "future_event", "data": "something"}],
    )

    result, passed = run(root)

    assert passed is True, "unknown type must not cause FAIL"
    assert result["status"] == "PASS"
    warns = [c for c in result["checks"] if c["status"] == "WARN"]
    assert any(c["check"] == "unknown_type" for c in warns)


# ---------------------------------------------------------------------------
# 5. Empty file passes
# ---------------------------------------------------------------------------

def test_empty_file_passes(tmp_path: Path) -> None:
    """A JSONL file with no entries (blank lines only) is PASS."""
    root = _make_repo(tmp_path)
    _write_raw(root / "ledger" / "history", "2026-01-01.jsonl", "\n\n\n")

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# 6. JSONL parse error is reported (as WARN)
# ---------------------------------------------------------------------------

def test_jsonl_parse_error_reported(tmp_path: Path) -> None:
    """A line that is not valid JSON is reported (as WARN, not FAIL)."""
    root = _make_repo(tmp_path)
    _write_raw(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        '{"type": "payment", "agent": "X@y", "amount": 5, "issue": 1, "ts": "\\!bad"}\n',
    )

    result, _ = run(root)

    all_checks = result["checks"]
    parse_errs = [c for c in all_checks if c["check"] == "parse_error"]
    assert len(parse_errs) == 1, "expected exactly one parse_error check"
    assert parse_errs[0]["status"] == "WARN"


# ---------------------------------------------------------------------------
# 7. Multi-file scan
# ---------------------------------------------------------------------------

def test_multi_file_scan(tmp_path: Path) -> None:
    """Violations in different files are all collected in one result."""
    root = _make_repo(tmp_path)
    hist = root / "ledger" / "history"

    # File 1: clean
    _write_jsonl(hist, "2026-01-01.jsonl", [
        {"type": "payment", "agent": "A@x", "amount": 1, "issue": 1, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    # File 2: missing amount
    _write_jsonl(hist, "2026-01-02.jsonl", [
        {"type": "escrow", "agent": "A@x", "issue": 2, "timestamp": "2026-01-01T00:00:00Z"},
    ])
    # File 3: missing agent
    _write_jsonl(hist, "2026-01-03.jsonl", [
        {"type": "claim", "issue": 3, "timestamp": "2026-01-01T00:00:00Z"},
    ])

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert len(fails) == 2
    files_with_fails = {c["file"] for c in fails}
    assert "2026-01-02.jsonl" in files_with_fails
    assert "2026-01-03.jsonl" in files_with_fails


# ---------------------------------------------------------------------------
# 8. Multiple violations reported together
# ---------------------------------------------------------------------------

def test_multiple_violations_reported_together(tmp_path: Path) -> None:
    """Multiple bad entries in one file produce separate check entries."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {"type": "payment", "agent": "A@x", "amount": 5},          # missing issue + timestamp
            {"type": "escrow", "amount": 3, "issue": 1},                # missing agent + timestamp
            {"type": "verification", "issue": 2, "agent": "A@x",
             "verified_by": "B@y", "evidence": "ok", "timestamp": "2026-01-01T00:00:00Z"},  # valid
        ],
    )

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert len(fails) == 2
    for f in fails:
        assert f["check"] == "required_fields"


# ---------------------------------------------------------------------------
# 9. author alias satisfies agent requirement for escrow
# ---------------------------------------------------------------------------

def test_author_alias_accepted_for_escrow(tmp_path: Path) -> None:
    """Escrow entry with 'author' instead of 'agent' is valid (PASS)."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "escrow",
                "author": "agent0@system",
                "amount": 20,
                "issue": 5,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# 10. created_at alias satisfies timestamp requirement
# ---------------------------------------------------------------------------

def test_created_at_alias_accepted_as_timestamp(tmp_path: Path) -> None:
    """trajectory_mint with 'created_at' instead of 'timestamp' passes."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "trajectory_mint",
                "trajectory": "T3",
                "slot": 1,
                "amount": 20,
                "created_at": "2026-01-01T00:00:00Z",  # alias for timestamp
            }
        ],
    )

    result, passed = run(root)

    assert passed is True
    assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# 11. Fractional amount fails
# ---------------------------------------------------------------------------

def test_fractional_amount_fails(tmp_path: Path) -> None:
    """An entry with a float amount (fractional WEA) triggers FAIL."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "payment",
                "agent": "Claude-1@claude",
                "amount": 1.5,  # fractional — invalid
                "issue": 10,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "amount_type" for c in fails)


# ---------------------------------------------------------------------------
# 12. Output structure always has status, checks, summary
# ---------------------------------------------------------------------------

def test_output_structure(tmp_path: Path) -> None:
    """run() always returns a dict with 'status', 'checks', 'summary'."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [
            {
                "type": "payment",
                "agent": "A@x",
                "amount": 1,
                "issue": 1,
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    )

    result, passed = run(root)

    assert "status" in result
    assert "checks" in result
    assert "summary" in result
    assert isinstance(result["checks"], list)
    assert isinstance(result["summary"], str)
    assert result["status"] in ("PASS", "FAIL")
    assert isinstance(passed, bool)


# ---------------------------------------------------------------------------
# 13. No history directory is FAIL
# ---------------------------------------------------------------------------

def test_no_history_directory_fails(tmp_path: Path) -> None:
    """Missing ledger/history directory returns FAIL."""
    # Do NOT create the history directory
    (tmp_path / "ledger").mkdir()

    result, passed = run(tmp_path)

    assert passed is False
    assert result["status"] == "FAIL"
    assert "history directory not found" in result["summary"]


# ---------------------------------------------------------------------------
# 14. SCHEMAS constant covers all six required types
# ---------------------------------------------------------------------------

def test_schemas_cover_required_types() -> None:
    """SCHEMAS defines all six event types mandated by the spec."""
    required_types = {"payment", "escrow", "escrow_return", "trajectory_mint", "verification", "claim"}
    for t in required_types:
        assert t in SCHEMAS, f"SCHEMAS missing required type '{t}'"


# ---------------------------------------------------------------------------
# 15. missing_type field is FAIL
# ---------------------------------------------------------------------------

def test_entry_without_type_field_fails(tmp_path: Path) -> None:
    """An entry with no 'type' key is a FAIL (missing_type check)."""
    root = _make_repo(tmp_path)
    _write_jsonl(
        root / "ledger" / "history",
        "2026-01-01.jsonl",
        [{"agent": "A@x", "amount": 5, "issue": 1}],  # no type
    )

    result, passed = run(root)

    assert passed is False
    fails = [c for c in result["checks"] if c["status"] == "FAIL"]
    assert any(c["check"] == "missing_type" for c in fails)
