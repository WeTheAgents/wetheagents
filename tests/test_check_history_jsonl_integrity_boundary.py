"""Boundary / edge-case tests for scripts/check_history_jsonl_integrity.py.

Covers all 7 boundary scenarios from issue #855:
  1. Trailing whitespace line at end of file
  2. Partial write / truncated JSON
  3. Nested JSON with required field absent at top level
  4. amount as numeric-looking string
  5. issue: null
  6. Multiple violations in one file (all reported before exit)
  7. Unknown event_type value — WARNING only, exit 0
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_history_jsonl_integrity import (  # noqa: E402
    VIOLATIONS,
    WARNINGS,
    main,
)


def _history_dir(temp_repo: Path) -> Path:
    d = temp_repo / "ledger" / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reset() -> None:
    VIOLATIONS.clear()
    WARNINGS.clear()


# ---------------------------------------------------------------------------
# Scenario 1: Trailing whitespace / blank line at end of file
# ---------------------------------------------------------------------------


def test_trailing_blank_line_passes(temp_repo: Path) -> None:
    """File ending with blank and whitespace-only lines — must pass (lines skipped)."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_01.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n'
        '{"type": "payment", "issue": 2, "amount": 5, "timestamp": "2026-01-01T01:00:00Z"}\n'
        "\n"
        "   \n",
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []


# ---------------------------------------------------------------------------
# Scenario 2: Partial write / truncated JSON (no closing brace)
# ---------------------------------------------------------------------------


def test_truncated_json_is_violation(temp_repo: Path) -> None:
    """Line cut off before closing brace — JSONDecodeError → VIOLATION."""
    _reset()
    h = _history_dir(temp_repo)
    # Matches the exact truncation pattern described in the issue
    (h / "boundary_02.jsonl").write_text(
        '{"event_type": "accept", "idem_key": "accept|123"\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("invalid JSON" in v for v in VIOLATIONS)


# ---------------------------------------------------------------------------
# Scenario 3: Required field nested inside a sub-object (absent at top level)
# ---------------------------------------------------------------------------


def test_event_type_nested_not_top_level_is_violation(temp_repo: Path) -> None:
    """event_type buried inside data{}, absent at top level — VIOLATION.

    _event_type() checks only top-level keys (type, event, event_type, op).
    Nesting hides the field, so the missing-event-type check fires.
    """
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_03a.jsonl").write_text(
        '{"data": {"event_type": "accept"}, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("missing event type field" in v for v in VIOLATIONS)


def test_amount_nested_not_top_level_not_flagged(temp_repo: Path) -> None:
    """amount nested inside sub-object, absent at top level — NOT a violation.

    The implementation only type-checks amount when present at top level
    (treated as optional). A record without top-level amount is valid per
    current implementation, even if amount exists deeper in the structure.
    """
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_03b.jsonl").write_text(
        '{"type": "payment", "data": {"amount": 10}, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []


# ---------------------------------------------------------------------------
# Scenario 4: amount as numeric-looking string ("100")
# ---------------------------------------------------------------------------


def test_amount_as_numeric_string_is_violation(temp_repo: Path) -> None:
    """'amount': '100' — string, not numeric → VIOLATION.

    The type check is strict: only int or float pass. Even a string that looks
    like a number (e.g. '100') is rejected.
    """
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_04.jsonl").write_text(
        '{"type": "payment", "amount": "100", "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("'amount' must be numeric" in v for v in VIOLATIONS)
    assert any("str" in v for v in VIOLATIONS)


# ---------------------------------------------------------------------------
# Scenario 5: issue: null
# ---------------------------------------------------------------------------


def test_null_issue_passes(temp_repo: Path) -> None:
    """issue: null is valid per spec — must pass with no violations."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_05.jsonl").write_text(
        '{"type": "trajectory_mint", "issue": null, "amount": 55, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []


# ---------------------------------------------------------------------------
# Scenario 6: Multiple violations in one file — all reported before exit
# ---------------------------------------------------------------------------


def test_multiple_violations_in_one_file_all_reported(temp_repo: Path) -> None:
    """3 malformed lines in a single JSONL file — all 3 violations reported, exit 1."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_06.jsonl").write_text(
        # line 1: valid — no violation
        '{"type": "payment", "amount": 5, "timestamp": "2026-01-01T00:00:00Z"}\n'
        # line 2: truncated JSON — JSONDecodeError violation
        '{"type": "payment", "amount": 5\n'
        # line 3: amount is a string — type violation
        '{"type": "escrow_create", "amount": "bad", "timestamp": "2026-01-01T00:00:00Z"}\n'
        # line 4: missing event type field — required field violation
        '{"amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert len(VIOLATIONS) == 3


# ---------------------------------------------------------------------------
# Scenario 7: Unknown event_type — WARNING only, exit 0
# ---------------------------------------------------------------------------


def test_unknown_event_type_field_is_warning_not_violation(temp_repo: Path) -> None:
    """event_type='future_type' (using 'event_type' key) — WARNING only, exit 0.

    Forward compatibility: unknown values in a known event-type field produce
    a WARNING so new event types don't break old checkers. Exit code stays 0.
    """
    _reset()
    h = _history_dir(temp_repo)
    (h / "boundary_07.jsonl").write_text(
        '{"event_type": "future_type", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []
    assert len(WARNINGS) >= 1
    assert any("unknown event_type" in w for w in WARNINGS)
    assert any("future_type" in w for w in WARNINGS)
