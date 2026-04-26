"""Tests for the pre-commit hook's history date consistency check integration.

Verifies that check_history_file_date_consistency.py behaves correctly when
invoked as a subprocess (as the hook does), and that the hook's trigger
pattern correctly identifies ledger/history/ files.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_history_file_date_consistency.py"
)

_HISTORY_PATTERN = re.compile(r"^ledger/history/")


def _run(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


def _make_history(tmp_path: Path) -> Path:
    h = tmp_path / "ledger" / "history"
    h.mkdir(parents=True, exist_ok=True)
    return h


# ---------------------------------------------------------------------------
# Blocking case: bad date → exit 1
# ---------------------------------------------------------------------------


def test_hook_exits_1_on_event_date_2_days_off(tmp_path: Path) -> None:
    """Hook exits 1 when an event's timestamp is 2 days off from the filename."""
    h = _make_history(tmp_path)
    # File is named 2026-01-01 but event is timestamped 2026-01-03 (2 days off).
    (h / "2026-01-01.jsonl").write_text(
        '{"type": "payment", "amount": 10, "timestamp": "2026-01-03T12:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "date_mismatch" in result.stdout


def test_hook_exits_1_on_out_of_order_events(tmp_path: Path) -> None:
    """Hook exits 1 when events within a file are not in non-decreasing timestamp order."""
    h = _make_history(tmp_path)
    (h / "2026-02-01.jsonl").write_text(
        '{"type": "escrow_create", "amount": 5, "timestamp": "2026-02-01T10:00:00Z"}\n'
        '{"type": "payment", "amount": 5, "timestamp": "2026-02-01T09:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "out_of_order" in result.stdout


def test_hook_exits_1_on_invalid_filename(tmp_path: Path) -> None:
    """Hook exits 1 when a history file has a non-date name."""
    h = _make_history(tmp_path)
    (h / "not-a-date.jsonl").write_text(
        '{"type": "payment", "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "invalid_filename" in result.stdout


# ---------------------------------------------------------------------------
# Passing case: correctly-dated file → exit 0
# ---------------------------------------------------------------------------


def test_hook_exits_0_on_correctly_dated_file(tmp_path: Path) -> None:
    """Hook exits 0 when all events in a file match the filename date."""
    h = _make_history(tmp_path)
    (h / "2026-03-15.jsonl").write_text(
        '{"type": "escrow_create", "amount": 10, "timestamp": "2026-03-15T08:00:00Z"}\n'
        '{"type": "payment", "amount": 10, "timestamp": "2026-03-15T09:30:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_hook_exits_0_on_adjacent_day_timestamp(tmp_path: Path) -> None:
    """Hook exits 0 when event timestamp is exactly 1 day off (within tolerance)."""
    h = _make_history(tmp_path)
    # File is 2026-04-10, event is 2026-04-11 — exactly 1 day off, still OK.
    (h / "2026-04-10.jsonl").write_text(
        '{"type": "payment", "amount": 5, "timestamp": "2026-04-11T01:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_exits_0_on_empty_history_dir(tmp_path: Path) -> None:
    """Hook exits 0 when there are no files in the history directory."""
    _make_history(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_exits_0_on_multiple_valid_files(tmp_path: Path) -> None:
    """Hook exits 0 when multiple files all pass date consistency checks."""
    h = _make_history(tmp_path)
    (h / "2026-05-01.jsonl").write_text(
        '{"type": "escrow_create", "amount": 20, "timestamp": "2026-05-01T10:00:00Z"}\n',
        encoding="utf-8",
    )
    (h / "2026-05-02.jsonl").write_text(
        '{"type": "payment", "amount": 20, "timestamp": "2026-05-02T14:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Hook trigger pattern
# ---------------------------------------------------------------------------


def test_hook_pattern_matches_history_files() -> None:
    """The pre-commit grep pattern matches files under ledger/history/."""
    candidates = [
        "ledger/history/2026-04-01.jsonl",
        "ledger/history/2026-01-15.jsonl",
    ]
    for path in candidates:
        assert _HISTORY_PATTERN.match(path), f"Expected match: {path}"


def test_hook_pattern_does_not_match_other_ledger_files() -> None:
    """The grep pattern does NOT fire for non-history ledger files."""
    non_history = [
        "ledger/balances.json",
        "ledger/escrows.json",
        "ledger/idem_keys.json",
        "ledger/trajectory_mints.json",
    ]
    for path in non_history:
        assert not _HISTORY_PATTERN.match(path), f"Unexpected match: {path}"


def test_hook_pattern_does_not_match_non_ledger_files() -> None:
    """The grep pattern does NOT fire for unrelated files."""
    unrelated = [
        "scripts/check_invariant.py",
        "tests/test_foo.py",
        "domains/circle-1/docs/memo.md",
    ]
    for path in unrelated:
        assert not _HISTORY_PATTERN.match(path), f"Unexpected match: {path}"
