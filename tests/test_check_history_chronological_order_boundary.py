"""Boundary spec tests for scripts/check_history_chronological_order.py — Gauntlet T4S28.

Encodes the full behavioural contract for edge/boundary inputs:

  (1)  single-event file: always passes, events_checked == 1
  (2)  millisecond reversal: 09:00:00.001Z → 09:00:00.000Z detected as violation
  (3)  millisecond equal: identical sub-second timestamps are non-decreasing → PASS
  (4)  null timestamp value: {"ts": null} — not a str, skipped gracefully
  (5)  empty-string timestamp: {"ts": ""} — empty after strip, skipped gracefully
  (6)  cross-file ordering: last event of day N > first event of day N+1 — NOT detected
       (each _scan_file resets previous_timestamp; per-file isolation is by design)
  (7)  filename gap: missing day between two files does not trigger any violation
  (8)  single-file history: no cross-day cases, ordered events pass cleanly
  (9)  empty history directory: files_scanned=0, events_checked=0, PASS
  (10) blank-only JSONL: file with only blank/whitespace lines → events_checked=0, PASS
  (11) one valid + one irreparably corrupt line: corrupt line skipped, valid events checked
  (12) non-date filename (genesis.jsonl): glob("*.jsonl") includes it — IS scanned
  (13) 1000+ ordered events: PASS in under 5 seconds (performance contract)
  (14) out-of-order at end of large file: violation at last pair is reported
  (15) exit code 0 on PASS via subprocess (exact code contract)
  (16) exit code 1 on FAIL via subprocess (not 2 or other)
  (17) output JSON contains required keys: "status" and "violations"

Gaps found (documented, not fixed — script unchanged):
  GAP-1: Cross-file ordering is not enforced. _scan_file resets previous_timestamp to None
          at the start of every file, so a timestamp that jumps backward between consecutive
          date-named files is silently ignored. This can mask real violations when events
          from different source clocks end up in the wrong daily file.
  GAP-2: Non-date-formatted filenames (e.g. genesis.jsonl) are included by glob("*.jsonl")
          with no filtering or warning. They participate in the sorted scan order based on
          alphabetical filename ordering, which may not match chronological intent.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.check_history_chronological_order import main, run_check

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_history_chronological_order.py"


# ── helpers ───────────────────────────────────────────────────────────────────


def _history_dir(root: Path) -> Path:
    path = root / "ledger" / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_jsonl(path: Path, events: list[dict | str]) -> None:
    lines: list[str] = []
    for event in events:
        lines.append(event if isinstance(event, str) else json.dumps(event))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── (1) single event always passes ───────────────────────────────────────────


def test_spec_1_single_event_always_passes(temp_repo: Path) -> None:
    """A file with exactly one timestamped event can never have an ordering violation."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [{"ts": "2026-04-01T12:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["events_checked"] == 1


# ── (2) millisecond reversal detected ────────────────────────────────────────


def test_spec_2_millisecond_reversed_fails(temp_repo: Path) -> None:
    """A 1-millisecond backward step is a genuine ordering violation."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [
            {"ts": "2026-04-01T09:00:00.001Z"},
            {"ts": "2026-04-01T09:00:00.000Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    assert report["violations"][0]["file"] == "2026-04-01.jsonl"
    assert report["violations"][0]["index"] == 2


# ── (3) millisecond equal timestamps allowed ──────────────────────────────────


def test_spec_3_millisecond_equal_timestamps_pass(temp_repo: Path) -> None:
    """Two events with identical sub-second timestamps satisfy non-decreasing order."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [
            {"ts": "2026-04-01T09:00:00.500Z"},
            {"ts": "2026-04-01T09:00:00.500Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["events_checked"] == 2


# ── (4) null timestamp skipped ───────────────────────────────────────────────


def test_spec_4_null_timestamp_skipped_gracefully(temp_repo: Path) -> None:
    """{"ts": null} is not a str value; _extract_timestamp returns None and the event is skipped."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [{"ts": None}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 0


# ── (5) empty-string timestamp skipped ───────────────────────────────────────


def test_spec_5_empty_string_timestamp_skipped_gracefully(temp_repo: Path) -> None:
    """{"ts": ""} strips to an empty string; _extract_timestamp skips it without error."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [{"ts": ""}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 0


# ── (6) cross-file ordering not enforced ──────────────────────────────────────


def test_spec_6_cross_day_violation_not_detected_between_files(temp_repo: Path) -> None:
    """Last event of day N later than first event of day N+1 produces no violation.

    _scan_file resets previous_timestamp = None at the start of each file, so
    cross-file ordering is never compared.  This is by design but is a documented gap.
    """
    hdir = _history_dir(temp_repo)
    _write_jsonl(
        hdir / "2026-04-01.jsonl",
        [{"ts": "2026-04-01T23:59:00Z"}],
    )
    _write_jsonl(
        hdir / "2026-04-02.jsonl",
        [{"ts": "2026-04-01T12:00:00Z"}],  # earlier than last event of day 1 — not detected
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["files_scanned"] == 2


# ── (7) filename gap passes ───────────────────────────────────────────────────


def test_spec_7_filename_gap_between_days_passes(temp_repo: Path) -> None:
    """Missing a day's file (e.g. 2026-03-02.jsonl absent) does not trigger a violation."""
    hdir = _history_dir(temp_repo)
    _write_jsonl(
        hdir / "2026-03-01.jsonl",
        [{"ts": "2026-03-01T10:00:00Z"}, {"ts": "2026-03-01T11:00:00Z"}],
    )
    _write_jsonl(
        hdir / "2026-03-03.jsonl",  # 2026-03-02 intentionally absent
        [{"ts": "2026-03-03T09:00:00Z"}, {"ts": "2026-03-03T10:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["files_scanned"] == 2
    assert report["stats"]["events_checked"] == 4


# ── (8) single-file history passes ────────────────────────────────────────────


def test_spec_8_single_file_history_passes(temp_repo: Path) -> None:
    """A history with exactly one correctly-ordered file produces PASS with no cross-day risk."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-15.jsonl",
        [
            {"ts": "2026-04-15T08:00:00Z"},
            {"ts": "2026-04-15T09:30:00Z"},
            {"ts": "2026-04-15T11:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["files_scanned"] == 1
    assert report["stats"]["events_checked"] == 3


# ── (9) empty history directory ───────────────────────────────────────────────


def test_spec_9_empty_history_directory_passes(temp_repo: Path) -> None:
    """An existing but empty history directory produces PASS with zero files scanned."""
    # temp_repo fixture creates history dir with no .jsonl files
    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["files_scanned"] == 0
    assert report["stats"]["events_checked"] == 0


# ── (10) blank-only file ──────────────────────────────────────────────────────


def test_spec_10_blank_only_file_passes_with_zero_events(temp_repo: Path) -> None:
    """A JSONL file containing only blank lines contributes zero events and no violations."""
    hdir = _history_dir(temp_repo)
    (hdir / "2026-04-01.jsonl").write_text("\n\n   \n\t\n\n", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["files_scanned"] == 1
    assert report["stats"]["events_checked"] == 0


# ── (11) corrupt line in otherwise ordered file ───────────────────────────────


def test_spec_11_corrupt_line_skipped_valid_events_still_checked(temp_repo: Path) -> None:
    """An irreparably corrupt JSON line is skipped; valid lines before and after are still compared."""
    hdir = _history_dir(temp_repo)
    (hdir / "2026-04-01.jsonl").write_text(
        '{"ts": "2026-04-01T09:00:00Z"}\n'
        '{"ts": "broken"\n'  # irreparable corrupt line
        '{"ts": "2026-04-01T10:00:00Z"}\n',
        encoding="utf-8",
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 2
    assert report["violations"] == []


# ── (12) non-date filename scanned ────────────────────────────────────────────


def test_spec_12_non_date_filename_included_in_scan(temp_repo: Path) -> None:
    """glob('*.jsonl') matches all .jsonl files — 'genesis.jsonl' is scanned, not silently skipped."""
    hdir = _history_dir(temp_repo)
    _write_jsonl(
        hdir / "genesis.jsonl",
        [
            {"ts": "2026-01-01T00:00:00Z"},
            {"ts": "2026-01-01T01:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["stats"]["files_scanned"] == 1
    assert report["stats"]["events_checked"] == 2


# ── (13) large ordered file passes quickly ────────────────────────────────────


def test_spec_13_large_ordered_file_completes_under_5_seconds(temp_repo: Path) -> None:
    """1000+ correctly-ordered events must pass within the 5-second performance budget."""
    base = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
    events = [{"ts": _iso(base + timedelta(seconds=i))} for i in range(1001)]

    _write_jsonl(_history_dir(temp_repo) / "2026-04-01.jsonl", events)

    start = time.monotonic()
    report = run_check(temp_repo)
    elapsed = time.monotonic() - start

    assert report["status"] == "PASS"
    assert report["stats"]["events_checked"] == 1001
    assert elapsed < 5.0, f"check took {elapsed:.2f}s — exceeded 5s budget"


# ── (14) out-of-order at end of large file ────────────────────────────────────


def test_spec_14_out_of_order_at_end_of_large_file_detected(temp_repo: Path) -> None:
    """A single reversed pair at the very end of a 1000+ event file is found and reported."""
    base = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
    events: list[dict] = [{"ts": _iso(base + timedelta(seconds=i))} for i in range(1000)]
    # Append reversed pair: t+1001 then t+1000
    events.append({"ts": _iso(base + timedelta(seconds=1001))})
    events.append({"ts": _iso(base + timedelta(seconds=1000))})

    _write_jsonl(_history_dir(temp_repo) / "2026-04-01.jsonl", events)

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    assert len(report["violations"]) == 1
    violation = report["violations"][0]
    assert violation["file"] == "2026-04-01.jsonl"
    assert violation["index"] == 1002  # event #1002 (1-based) is the offender
    assert violation["ts_curr"] < violation["ts_prev"]


# ── (15) exit code exactly 0 on pass ─────────────────────────────────────────


def test_spec_15_exit_code_exactly_zero_on_pass(temp_repo: Path) -> None:
    """Script exits with code 0 (not 2 or any other value) when history is clean."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [{"ts": "2026-04-01T09:00:00Z"}, {"ts": "2026-04-01T10:00:00Z"}],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


# ── (16) exit code exactly 1 on fail ─────────────────────────────────────────


def test_spec_16_exit_code_exactly_one_on_fail(temp_repo: Path) -> None:
    """Script exits with code 1 (not 2 or any other non-zero value) when violations exist."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [{"ts": "2026-04-01T10:00:00Z"}, {"ts": "2026-04-01T09:00:00Z"}],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1


# ── (17) output JSON has required keys ───────────────────────────────────────


def test_spec_17_output_json_has_status_and_violations_keys(temp_repo: Path) -> None:
    """Script stdout is parseable JSON containing at least 'status' and 'violations' keys."""
    _write_jsonl(
        _history_dir(temp_repo) / "2026-04-01.jsonl",
        [{"ts": "2026-04-01T09:00:00Z"}, {"ts": "2026-04-01T10:00:00Z"}],
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(temp_repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert "status" in payload, "output JSON must contain 'status' key"
    assert "violations" in payload, "output JSON must contain 'violations' key"
    assert isinstance(payload["status"], str)
    assert isinstance(payload["violations"], list)
