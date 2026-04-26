"""Tests for scripts/check_history_jsonl_integrity.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_history_jsonl_integrity import (  # noqa: E402
    VIOLATIONS,
    WARNINGS,
    check_file,
    main,
)


def _history_dir(temp_repo: Path) -> Path:
    d = temp_repo / "ledger" / "history"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _reset() -> None:
    """Clear module-level state between tests."""
    VIOLATIONS.clear()
    WARNINGS.clear()


# ---------------------------------------------------------------------------
# Acceptance criteria tests
# ---------------------------------------------------------------------------


def test_all_valid_lines_pass(temp_repo: Path) -> None:
    """All valid JSON lines with required fields → exit 0."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-01.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n'
        '{"type": "payment", "issue": 2, "amount": 5, "ts": "2026-01-01T01:00:00Z"}\n'
        '{"type": "escrow_return", "issue": 3, "amount": 10, "timestamp": "2026-01-01T02:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []


def test_malformed_json_line_fails(temp_repo: Path) -> None:
    """A line that is not valid JSON → exit 1."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-02.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n'
        "not valid json at all\n",
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("invalid JSON" in v for v in VIOLATIONS)


def test_missing_required_field_fails(temp_repo: Path) -> None:
    """Event missing timestamp field → exit 1 (required field absent)."""
    _reset()
    h = _history_dir(temp_repo)
    # No timestamp/ts/created_at/event_at/at present
    (h / "2026-01-03.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("missing timestamp field" in v for v in VIOLATIONS)


def test_missing_event_type_field_fails(temp_repo: Path) -> None:
    """Event with no type/event/event_type/op field → exit 1."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-04.jsonl").write_text(
        '{"issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("missing event type field" in v for v in VIOLATIONS)


def test_unknown_event_type_is_warning_not_fail(temp_repo: Path) -> None:
    """Unknown event_type value → WARNING only, exit 0."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-05.jsonl").write_text(
        '{"type": "future_unknown_type", "issue": 1, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []
    assert any("unknown event_type" in w for w in WARNINGS)


def test_empty_history_file_passes(temp_repo: Path) -> None:
    """An empty JSONL file → exit 0 (no lines to validate)."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-06.jsonl").write_text("", encoding="utf-8")
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []


# ---------------------------------------------------------------------------
# Additional robustness tests
# ---------------------------------------------------------------------------


def test_whitespace_only_lines_pass(temp_repo: Path) -> None:
    """Lines with only whitespace are skipped without error."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-07.jsonl").write_text(
        '{"type": "payment", "amount": 5, "timestamp": "2026-01-01T00:00:00Z"}\n'
        "   \n"
        "\n",
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0


def test_no_history_files_passes(temp_repo: Path) -> None:
    """History directory with zero JSONL files → exit 0."""
    _reset()
    h = _history_dir(temp_repo)
    rc = main(str(h))
    assert rc == 0
    assert VIOLATIONS == []


def test_non_numeric_amount_fails(temp_repo: Path) -> None:
    """amount field that is a string → VIOLATION."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-08.jsonl").write_text(
        '{"type": "payment", "amount": "ten", "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("'amount' must be numeric" in v for v in VIOLATIONS)


def test_boolean_amount_fails(temp_repo: Path) -> None:
    """amount: true (bool) must be rejected — bool is subclass of int in Python."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-09.jsonl").write_text(
        '{"type": "payment", "amount": true, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("'amount' must be numeric" in v for v in VIOLATIONS)


def test_non_int_issue_fails(temp_repo: Path) -> None:
    """issue field that is a string → VIOLATION."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-10.jsonl").write_text(
        '{"type": "payment", "issue": "abc", "amount": 5, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("'issue' must be int or null" in v for v in VIOLATIONS)


def test_null_issue_passes(temp_repo: Path) -> None:
    """issue: null is explicitly allowed."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-11.jsonl").write_text(
        '{"type": "payment", "issue": null, "amount": 5, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0


def test_timestamp_alias_ts_passes(temp_repo: Path) -> None:
    """Using 'ts' instead of 'timestamp' satisfies the timestamp requirement."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-12.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10, "ts": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0


def test_event_field_alias_passes(temp_repo: Path) -> None:
    """Using 'event' instead of 'type' satisfies the event type requirement."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-13.jsonl").write_text(
        '{"event": "escrow_return", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0


def test_op_field_alias_passes(temp_repo: Path) -> None:
    """Using 'op' as event type field is valid (triggers warning for unknown type)."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-14.jsonl").write_text(
        '{"op": "escrow_return", "issue": 1, "amount": 10, "ts": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    # op-based records use the op value as event type; escrow_return is known
    # but the field name 'op' causes the value to be checked against known types
    assert rc == 0


def test_non_dict_json_fails(temp_repo: Path) -> None:
    """A line that is valid JSON but not an object → VIOLATION."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-15.jsonl").write_text(
        "[1, 2, 3]\n",
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert any("expected JSON object" in v for v in VIOLATIONS)


def test_multiple_files_violations_accumulate(temp_repo: Path) -> None:
    """Violations in multiple files are all reported before exit 1."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-02-01.jsonl").write_text(
        "bad json\n",
        encoding="utf-8",
    )
    (h / "2026-02-02.jsonl").write_text(
        '{"type": "payment", "amount": "bad", "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 1
    assert len(VIOLATIONS) == 2


def test_created_at_alias_passes(temp_repo: Path) -> None:
    """created_at is accepted as a valid timestamp alias."""
    _reset()
    h = _history_dir(temp_repo)
    (h / "2026-01-16.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10, "created_at": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    rc = main(str(h))
    assert rc == 0


def test_real_ledger_passes() -> None:
    """Live repository history must exit 0."""
    _reset()
    rc = main()
    assert rc == 0, f"Live ledger violations:\n" + "\n".join(VIOLATIONS)
