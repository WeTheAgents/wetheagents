"""Tests for the pre-commit hook's history integrity check integration.

Verifies that check_history_jsonl_integrity.py behaves correctly when invoked
as a subprocess (as the hook does), and that the hook's trigger pattern
correctly identifies ledger/history/ files.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "check_history_jsonl_integrity.py"
)

_HISTORY_PATTERN = re.compile(r"^ledger/history/")


def _run(history_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--history-dir", str(history_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def _make_history(tmp_path: Path) -> Path:
    h = tmp_path / "ledger" / "history"
    h.mkdir(parents=True, exist_ok=True)
    return h


# ---------------------------------------------------------------------------
# Hook subprocess behaviour
# ---------------------------------------------------------------------------


def test_hook_exits_0_on_valid_jsonl(tmp_path: Path) -> None:
    """Hook script exits 0 when history dir contains only valid JSONL lines."""
    h = _make_history(tmp_path)
    (h / "2026-01-01.jsonl").write_text(
        '{"type": "escrow_create", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n'
        '{"type": "payment", "issue": 2, "amount": 5, "ts": "2026-01-01T01:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_exits_1_on_malformed_jsonl(tmp_path: Path) -> None:
    """Hook script exits 1 when a history file contains a malformed JSON line."""
    h = _make_history(tmp_path)
    (h / "2026-01-02.jsonl").write_text(
        '{"type": "payment", "issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n'
        "this is not json\n",
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 1
    assert "invalid JSON" in result.stdout


def test_hook_exits_1_on_missing_event_type(tmp_path: Path) -> None:
    """Hook script exits 1 when a history line has no event type field."""
    h = _make_history(tmp_path)
    (h / "2026-01-03.jsonl").write_text(
        '{"issue": 1, "amount": 10, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 1
    assert "missing event type field" in result.stdout


def test_hook_exits_1_on_missing_timestamp(tmp_path: Path) -> None:
    """Hook script exits 1 when a history line has no timestamp field."""
    h = _make_history(tmp_path)
    (h / "2026-01-04.jsonl").write_text(
        '{"type": "payment", "issue": 1, "amount": 10}\n',
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 1
    assert "missing timestamp field" in result.stdout


def test_hook_exits_0_on_empty_history_dir(tmp_path: Path) -> None:
    """Hook script exits 0 when there are no JSONL files in history dir."""
    h = _make_history(tmp_path)
    result = _run(h)
    assert result.returncode == 0


def test_hook_exits_1_on_non_dict_json(tmp_path: Path) -> None:
    """Hook script exits 1 when a line is valid JSON but not an object."""
    h = _make_history(tmp_path)
    (h / "2026-01-05.jsonl").write_text(
        "[1, 2, 3]\n",
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 1
    assert "expected JSON object" in result.stdout


def test_hook_stdout_contains_pass_on_valid(tmp_path: Path) -> None:
    """Hook script prints 'PASS' to stdout on a clean run."""
    h = _make_history(tmp_path)
    (h / "2026-01-06.jsonl").write_text(
        '{"type": "accept", "issue": 5, "amount": 20, "timestamp": "2026-01-01T00:00:00Z"}\n',
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 0
    assert "PASS" in result.stdout


def test_hook_stdout_contains_fail_on_violation(tmp_path: Path) -> None:
    """Hook script prints 'FAIL' to stdout when violations are detected."""
    h = _make_history(tmp_path)
    (h / "2026-01-07.jsonl").write_text(
        "bad\n",
        encoding="utf-8",
    )
    result = _run(h)
    assert result.returncode == 1
    assert "FAIL" in result.stdout


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
