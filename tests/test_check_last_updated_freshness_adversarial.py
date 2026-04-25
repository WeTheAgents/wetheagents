"""Adversarial tests for scripts/check_last_updated_freshness.py.

Each scenario targets a specific bypass vector in the freshness validation.
Fixtures are minimal: only the state needed to exercise the vector.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_last_updated_freshness import (
    check_freshness,
    collect_history_max_ts,
    _parse_utc_timestamp,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_root(tmp_path: Path, last_updated: str | None = "ABSENT") -> Path:
    """Write a minimal repo structure under tmp_path.

    last_updated="ABSENT" omits the key; None writes JSON null; any string
    writes the literal string value.
    """
    root = tmp_path / "repo"
    (root / "ledger" / "history").mkdir(parents=True)
    balances: dict = {"version": 1, "agents": {}}
    if last_updated != "ABSENT":
        balances["last_updated"] = last_updated
    (root / "ledger" / "balances.json").write_text(
        json.dumps(balances), encoding="utf-8"
    )
    return root


def _write_history(root: Path, filename: str, events: list[dict | str]) -> None:
    """Write history events as JSONL. Pass a str element for a corrupt line."""
    lines = []
    for ev in events:
        if isinstance(ev, str):
            lines.append(ev)
        else:
            lines.append(json.dumps(ev))
    (root / "ledger" / "history" / filename).write_text(
        "\n".join(lines), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Scenario 1 — Equal timestamps in different ISO representations (Z vs +00:00)
#
# Bypass vector: a naive string comparison treats "...Z" and "...+00:00" as
# unequal even though they denote the same instant.  If the checker compared
# raw strings, an equal-timestamp state would report as stale (delta<0) when
# last_updated uses Z and history uses +00:00, or vice versa.  The checker
# normalises both through _parse_utc_timestamp → UTC datetime, so the
# comparison is always on identical-timezone-aware objects.
# ---------------------------------------------------------------------------


class TestEqualTimestampsIsoVariants:
    def test_last_updated_z_history_offset_equal(self, tmp_path: Path):
        # last_updated uses Z suffix; history event uses +00:00 offset — same instant
        root = _make_root(tmp_path, "2024-06-01T10:00:00Z")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T10:00:00+00:00"}])
        result = check_freshness(root)
        assert result["pass"], f"Equal instant (Z vs +00:00) must PASS; got: {result['reason']}"

    def test_last_updated_offset_history_z_equal(self, tmp_path: Path):
        # last_updated uses +00:00; history event uses Z — same instant
        root = _make_root(tmp_path, "2024-06-01T10:00:00+00:00")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T10:00:00Z"}])
        result = check_freshness(root)
        assert result["pass"], f"Equal instant (+00:00 vs Z) must PASS; got: {result['reason']}"

    def test_stale_by_one_second_still_fails(self, tmp_path: Path):
        # belt-and-suspenders: one second behind must FAIL to confirm the above
        # assertions are not trivially green (checker must actually compare timestamps)
        root = _make_root(tmp_path, "2024-06-01T09:59:59Z")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T10:00:00+00:00"}])
        result = check_freshness(root)
        assert not result["pass"], "last_updated 1s behind history must FAIL"

    def test_parse_utc_timestamp_z_equals_offset(self):
        # unit-level: the normalisation function itself must produce equal datetimes
        ts_z = _parse_utc_timestamp("2024-06-01T10:00:00Z")
        ts_off = _parse_utc_timestamp("2024-06-01T10:00:00+00:00")
        assert ts_z == ts_off, "Z and +00:00 representations must parse to identical datetimes"


# ---------------------------------------------------------------------------
# Scenario 2 — Corrupt history line reduces effective max
#
# Bypass vector: inserting a corrupt (non-parseable) line as the newest event
# would hide that event from the checker, since unparseable lines are silently
# skipped.  A stale last_updated (behind only the corrupt line) would appear
# fresh because the effective max drops to the last valid event.  The checker
# should still detect staleness against any parseable event — it must not
# silently promote a corrupt-only history to "no constraint".
# ---------------------------------------------------------------------------


class TestCorruptHistoryLine:
    def test_stale_caught_despite_corrupt_newest_line(self, tmp_path: Path):
        # corrupt line is appended AFTER a valid newer event — staleness must be caught
        # against the valid newer event regardless of the corrupt line
        root = _make_root(tmp_path, "2024-06-01T00:00:00Z")
        _write_history(
            root,
            "h.jsonl",
            [
                {"ts": "2024-06-01T00:00:00Z"},   # last_updated matches this
                {"ts": "2024-06-02T00:00:00Z"},   # newer valid — last_updated is stale
                "NOT VALID JSON <<<",              # corrupt line after the valid newer one
            ],
        )
        result = check_freshness(root)
        assert not result["pass"], (
            "Stale last_updated must be caught even when a corrupt line follows the newest valid event"
        )

    def test_corrupt_line_between_valid_events_uses_real_max(self, tmp_path: Path):
        # corrupt line is sandwiched between two valid events; effective max = T2
        root = _make_root(tmp_path, "2024-06-01T00:00:00Z")
        _write_history(
            root,
            "h.jsonl",
            [
                {"ts": "2024-05-01T00:00:00Z"},   # older valid
                "{bad json",                       # corrupt line in the middle
                {"ts": "2024-06-02T00:00:00Z"},   # newer valid
            ],
        )
        result = check_freshness(root)
        assert not result["pass"], "Corrupt middle line must not hide the newer valid event"

    def test_corrupt_only_history_acts_as_no_events(self, tmp_path: Path):
        # if every line in history is corrupt, effective max is None → PASS
        # (this is the expected behavior — can't be stale if there's no parseable baseline)
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        _write_history(root, "h.jsonl", ["{bad", "also bad <<<", "}broken{"])
        result = check_freshness(root)
        assert result["pass"], "Entirely corrupt history must produce PASS (no parseable events)"

    def test_valid_events_still_caught_with_mixed_corrupt(self, tmp_path: Path):
        # confirms the corrupt_only PASS above is not trivially green
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        _write_history(
            root,
            "h.jsonl",
            ["{bad", {"ts": "2024-06-01T00:00:00Z"}, "also bad"],
        )
        result = check_freshness(root)
        assert not result["pass"], "Stale last_updated must be caught when at least one valid event exists"


# ---------------------------------------------------------------------------
# Scenario 3 — Null last_updated field vs absent key
#
# Bypass vector: `{"last_updated": null}` in JSON → Python None.  A guard
# like `if "last_updated" not in balances` misses the null case because the
# key IS present; only its value is None.  The checker uses
# `not isinstance(raw_last_updated, str)` which catches both None and absent.
# Both cases must produce FAIL, and their error messages should reflect the
# same validation path.
# ---------------------------------------------------------------------------


class TestNullLastUpdated:
    def test_null_last_updated_fails(self, tmp_path: Path):
        # key present with JSON null value → must FAIL
        root = _make_root(tmp_path, None)  # writes "last_updated": null
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert not result["pass"], "null last_updated must FAIL"
        assert result["last_updated"] is None

    def test_absent_last_updated_fails(self, tmp_path: Path):
        # key completely absent → must also FAIL
        root = _make_root(tmp_path, "ABSENT")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert not result["pass"], "Absent last_updated key must FAIL"
        assert result["last_updated"] is None

    def test_null_fails_same_as_absent(self, tmp_path: Path):
        # both should fail for the same reason category
        root_null = _make_root(tmp_path / "null_case", None)
        root_absent = _make_root(tmp_path / "absent_case", "ABSENT")
        for root in (root_null, root_absent):
            _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result_null = check_freshness(root_null)
        result_absent = check_freshness(root_absent)
        assert not result_null["pass"]
        assert not result_absent["pass"]
        assert "missing or empty" in result_null["reason"]
        assert "missing or empty" in result_absent["reason"]

    def test_valid_last_updated_passes_with_history(self, tmp_path: Path):
        # confirms the null/absent FAIL tests are not trivially green
        root = _make_root(tmp_path, "2024-06-01T00:00:00Z")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert result["pass"], "Valid equal last_updated with history must PASS"


# ---------------------------------------------------------------------------
# Scenario 4 — Future-dated last_updated
#
# Bypass vector: concern that the checker might incorrectly reject a future
# timestamp as "invalid" or treat it as suspicious.  A future last_updated is
# semantically fine — it merely means the ledger was pre-stamped or the clock
# drifted forward.  The check is `last_updated >= max_history_ts`; a future
# value satisfies this trivially and must PASS.  If the checker added any
# upper-bound validation, it would incorrectly reject future-dated ledgers.
# ---------------------------------------------------------------------------


class TestFutureLastUpdated:
    def test_future_last_updated_with_history_passes(self, tmp_path: Path):
        # last_updated is far in the future — must PASS (fresh relative to any history)
        root = _make_root(tmp_path, "2099-01-01T00:00:00Z")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert result["pass"], f"Future last_updated must PASS; got: {result['reason']}"

    def test_future_last_updated_no_history_passes(self, tmp_path: Path):
        # future last_updated with no history — must PASS (no constraint)
        root = _make_root(tmp_path, "2099-01-01T00:00:00Z")
        result = check_freshness(root)
        assert result["pass"], "Future last_updated with no history must PASS"

    def test_past_last_updated_fails_to_confirm_comparison_is_real(self, tmp_path: Path):
        # confirms the future PASS tests are not trivially green — past must FAIL
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert not result["pass"], "Past last_updated behind history must FAIL"

    def test_future_last_updated_delta_is_positive(self, tmp_path: Path):
        # delta_seconds = last_updated - max_history_ts must be positive for future last_updated
        root = _make_root(tmp_path, "2099-01-01T00:00:00Z")
        _write_history(root, "h.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert result["delta_seconds"] is not None
        assert result["delta_seconds"] > 0, "delta_seconds must be positive when last_updated > max_history_ts"


# ---------------------------------------------------------------------------
# Scenario 5 — Empty file in history directory (zero-byte .jsonl)
#
# Bypass vector: an empty .jsonl file contributes zero events; if it were the
# only file in history/, collect_history_max_ts returns None, and the checker
# returns PASS.  An attacker who truncates history files or creates empty
# placeholder files could hide all events from freshness validation.  This
# scenario verifies the expected behavior (empty file = no events = no
# constraint) and confirms that a non-empty sibling file still provides
# the effective max.
# ---------------------------------------------------------------------------


class TestEmptyHistoryFile:
    def test_empty_only_file_gives_no_constraint(self, tmp_path: Path):
        # zero-byte .jsonl → no events → PASS even with old last_updated
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        (root / "ledger" / "history" / "empty.jsonl").write_bytes(b"")
        result = check_freshness(root)
        assert result["pass"], "Zero-byte history file must produce PASS (no events to compare)"

    def test_empty_file_does_not_suppress_valid_sibling(self, tmp_path: Path):
        # empty file alongside a valid .jsonl — valid events must still enforce staleness
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        (root / "ledger" / "history" / "empty.jsonl").write_bytes(b"")
        _write_history(root, "events.jsonl", [{"ts": "2024-06-01T00:00:00Z"}])
        result = check_freshness(root)
        assert not result["pass"], (
            "Stale last_updated must be caught when a non-empty sibling exists alongside the empty file"
        )

    def test_collect_history_max_ts_returns_none_for_empty_dir(self, tmp_path: Path):
        # unit-level: empty history dir → None (used by PASS path)
        root = tmp_path / "repo"
        (root / "ledger" / "history").mkdir(parents=True)
        max_ts = collect_history_max_ts(root)
        assert max_ts is None, "Empty history dir must return None from collect_history_max_ts"

    def test_collect_history_max_ts_ignores_empty_file(self, tmp_path: Path):
        # zero-byte file must not cause an error or return a spurious timestamp
        root = tmp_path / "repo"
        (root / "ledger" / "history").mkdir(parents=True)
        (root / "ledger" / "history" / "empty.jsonl").write_bytes(b"")
        max_ts = collect_history_max_ts(root)
        assert max_ts is None, "Empty .jsonl file must produce None from collect_history_max_ts"


# ---------------------------------------------------------------------------
# Scenario 6 — All history lines missing ts/timestamp/event_at fields
#
# Bypass vector: history events are valid JSON but use a different field name
# for their timestamp (e.g., "created_at", "time", "date").  The checker only
# reads ts, timestamp, and event_at.  If all events use an unknown field,
# collect_history_max_ts returns None and the check passes regardless of how
# stale last_updated is.  This is a genuine bypass vector: stripping standard
# timestamp fields from history events would defeat freshness validation.
# ---------------------------------------------------------------------------


class TestAllHistoryLinesLackTimestampFields:
    def test_no_ts_fields_gives_no_constraint(self, tmp_path: Path):
        # events exist but none carry ts/timestamp/event_at → PASS
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        _write_history(
            root,
            "h.jsonl",
            [
                {"created_at": "2024-06-01T00:00:00Z", "op": "transfer"},
                {"date": "2024-06-02T00:00:00Z", "op": "escrow"},
                {"time": "2024-06-03T00:00:00Z", "op": "release"},
            ],
        )
        result = check_freshness(root)
        assert result["pass"], (
            "Events with only unknown timestamp fields must produce PASS (effective max absent)"
        )

    def test_mixing_known_and_unknown_fields_detects_staleness(self, tmp_path: Path):
        # one event has ts — that event IS checked, so stale last_updated fails
        root = _make_root(tmp_path, "2020-01-01T00:00:00Z")
        _write_history(
            root,
            "h.jsonl",
            [
                {"created_at": "2099-01-01T00:00:00Z", "op": "big event"},  # unknown field
                {"ts": "2024-06-01T00:00:00Z", "op": "transfer"},           # known field
            ],
        )
        result = check_freshness(root)
        assert not result["pass"], (
            "Stale last_updated must be caught when at least one event has a known timestamp field"
        )

    def test_collect_max_ts_returns_none_for_fieldless_events(self, tmp_path: Path):
        # unit-level: no recognizable field → None
        root = tmp_path / "repo"
        (root / "ledger" / "history").mkdir(parents=True)
        _write_history(
            root,
            "h.jsonl",
            [{"created_at": "2024-06-01T00:00:00Z"}, {"date": "2024-06-02T00:00:00Z"}],
        )
        max_ts = collect_history_max_ts(root)
        assert max_ts is None, (
            "Events with only unrecognized timestamp fields must produce None"
        )

    def test_each_known_field_name_is_detected(self, tmp_path: Path):
        # ts, timestamp, and event_at are all independently recognized
        for field in ("ts", "timestamp", "event_at"):
            root = _make_root(tmp_path / field, "2020-01-01T00:00:00Z")
            _write_history(root, "h.jsonl", [{field: "2024-06-01T00:00:00Z"}])
            result = check_freshness(root)
            assert not result["pass"], f"Field '{field}' must be recognised; stale should FAIL"
