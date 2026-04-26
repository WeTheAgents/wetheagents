from __future__ import annotations

import json
from pathlib import Path

from scripts.check_history_file_date_consistency import run_check


def _history_dir(root: Path) -> Path:
    path = root / "ledger" / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_jsonl(path: Path, events: list[dict]) -> None:
    lines = [json.dumps(e) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Scenario 1: Leap day — valid date, valid events
# ---------------------------------------------------------------------------


def test_leap_day_valid(temp_repo: Path) -> None:
    """2024-02-29.jsonl with an event on 2024-02-29 passes — 2024 is a leap year."""
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2024-02-29.jsonl",
        [{"timestamp": "2024-02-29T12:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["events_checked"] == 1


# ---------------------------------------------------------------------------
# Scenario 2: Non-leap Feb 29 — invalid calendar date
# ---------------------------------------------------------------------------


def test_non_leap_feb29_is_invalid_date(temp_repo: Path) -> None:
    """2025-02-29.jsonl: filename matches the regex but Feb 29 does not exist in 2025."""
    hd = _history_dir(temp_repo)
    # The filename is syntactically valid (passes the regex) but the date is illegal.
    (hd / "2025-02-29.jsonl").write_text("", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = next(v for v in report["violations"] if v["file"] == "2025-02-29.jsonl")
    assert v["violation_type"] == "invalid_date"


# ---------------------------------------------------------------------------
# Scenario 3: Event at exactly midnight UTC
# ---------------------------------------------------------------------------


def test_event_at_midnight_utc_passes(temp_repo: Path) -> None:
    """An event timestamped 00:00:00Z is still on the same calendar day in UTC."""
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-04-01T00:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["events_checked"] == 1


# ---------------------------------------------------------------------------
# Scenario 4: Event exactly 24 h before file date — within ±1 day tolerance
# ---------------------------------------------------------------------------


def test_event_24h_before_file_date_passes(temp_repo: Path) -> None:
    """Event on 2026-03-31 in 2026-04-01.jsonl: delta == 1 day, within tolerance → PASS."""
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-03-31T01:00:00Z"}],
    )

    report = run_check(temp_repo)

    # delta == 1: the check triggers a VIOLATION only when delta > 1
    assert report["status"] == "PASS"
    assert report["violations"] == []


# ---------------------------------------------------------------------------
# Scenario 5: Event exactly 48 h before file date — outside tolerance
# ---------------------------------------------------------------------------


def test_event_48h_before_file_date_is_violation(temp_repo: Path) -> None:
    """Event on 2026-03-30 in 2026-04-01.jsonl: delta == 2 days → VIOLATION."""
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [{"timestamp": "2026-03-30T01:00:00Z"}],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violations"][0]
    assert v["violation_type"] == "date_mismatch"
    assert v["file"] == "2026-04-01.jsonl"
    assert v["days_off"] == 2


# ---------------------------------------------------------------------------
# Scenario 6: File with only empty lines — no events → pass
# ---------------------------------------------------------------------------


def test_file_with_only_empty_lines_passes(temp_repo: Path) -> None:
    """A file that contains only blank lines has no parseable events — passes silently."""
    hd = _history_dir(temp_repo)
    (hd / "2026-04-01.jsonl").write_text("\n\n\n", encoding="utf-8")

    report = run_check(temp_repo)

    assert report["status"] == "PASS"
    assert report["violations"] == []
    assert report["stats"]["events_checked"] == 0


# ---------------------------------------------------------------------------
# Scenario 7: Two events in reverse chronological order — violation
# ---------------------------------------------------------------------------


def test_two_events_reverse_order_is_violation(temp_repo: Path) -> None:
    """Second event timestamp earlier than first by 1 second triggers out_of_order."""
    hd = _history_dir(temp_repo)
    _write_jsonl(
        hd / "2026-04-01.jsonl",
        [
            {"timestamp": "2026-04-01T10:00:01Z"},
            {"timestamp": "2026-04-01T10:00:00Z"},
        ],
    )

    report = run_check(temp_repo)

    assert report["status"] == "FAIL"
    v = report["violations"][0]
    assert v["violation_type"] == "out_of_order"
    assert v["file"] == "2026-04-01.jsonl"
    assert v["ts_prev"] == "2026-04-01T10:00:01Z"
    assert v["ts_curr"] == "2026-04-01T10:00:00Z"
