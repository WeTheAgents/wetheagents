#!/usr/bin/env python3
"""Tests for scripts/check_escrow_idem_coverage.py.

Covers:
  1.  Happy path — all events covered, all keys matched → PASS
  2.  Direction 1 FAIL — active escrow with idem_key field but key absent
  3.  Direction 2 FAIL — orphaned idem key with no history event
  4.  Both directions FAIL simultaneously
  5.  Event without idem_key field is skipped (legacy event)
  6.  Returned escrow with missing key is exempt (not a violation)
  7.  Escrow_return_bulk exempts covered issues
  8.  Idem key present only in nested 'keys' object → still found
  9.  Idem key present only at top level → still found
 10.  Key with non-numeric suffix still parsed correctly
 11.  Empty inputs — no events, no idem keys → PASS
 12.  Malformed idem_key field (wrong prefix) is ignored
 13.  Multiple missing active escrows reported individually
 14.  Multiple orphaned idem keys reported individually
 15.  Event with idem_key but issue already returned by escrow_return_bulk

--since flag tests:
 16.  --since filters out pre-date events (direction 1); no false positives
 17.  --since after all events gives PASS even if history has coverage gaps
 18.  No --since flag still checks all events (unchanged behavior)
 19.  --since boundary: event exactly on since date is included
 20.  --since with future date gives PASS (no events in scope)
 21.  --since filters direction 2 idem keys by timestamp value
 22.  --since: event before since exempts that issue; post-since event still checked
 23.  --since: idem key with no parseable timestamp is always checked (not filtered)
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_escrow_idem_coverage import run_coverage_check  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _idem(keys_nested: dict | None = None, keys_toplevel: dict | None = None) -> dict:
    """Build a merged idem_keys dict as returned by load_idem_keys()."""
    merged: dict = {}
    if keys_nested:
        merged.update(keys_nested)
    if keys_toplevel:
        merged.update(keys_toplevel)
    return merged


def _create(issue: int, idem_key: str | None = None) -> dict:
    e: dict = {"type": "escrow_create", "issue": issue, "amount": 30}
    if idem_key is not None:
        e["idem_key"] = idem_key
    return e


def _return(issue: int) -> dict:
    return {"type": "escrow_return", "issue": issue, "amount": 30}


def _return_bulk(issues: list[int]) -> dict:
    return {"type": "escrow_return_bulk", "issues": issues}


# ---------------------------------------------------------------------------
# Test 1: happy path — all events covered, all keys matched → PASS
# ---------------------------------------------------------------------------


def test_happy_path_pass():
    idem = _idem({"escrow_create_10_t1s1_gauntlet": "2026-01-01T00:00:00Z"})
    events = [_create(10, "escrow_create_10_t1s1_gauntlet")]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 2: direction 1 FAIL — active escrow, key absent from idem_keys
# ---------------------------------------------------------------------------


def test_direction1_active_escrow_missing_key_fail():
    idem = _idem()  # empty — no keys registered
    events = [_create(20, "escrow_create_20_t2s1_gauntlet")]
    missing, orphaned = run_coverage_check(idem, events)
    assert len(missing) == 1
    assert missing[0]["idem_key"] == "escrow_create_20_t2s1_gauntlet"
    assert missing[0]["issue"] == "20"
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 3: direction 2 FAIL — orphaned idem key, no matching history event
# ---------------------------------------------------------------------------


def test_direction2_orphaned_idem_key_fail():
    idem = _idem({"escrow_create_30_t3s1_gauntlet": "2026-01-01T00:00:00Z"})
    events = []  # no escrow_create events at all
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert len(orphaned) == 1
    assert orphaned[0]["idem_key"] == "escrow_create_30_t3s1_gauntlet"
    assert orphaned[0]["issue"] == "30"


# ---------------------------------------------------------------------------
# Test 4: both directions fail simultaneously
# ---------------------------------------------------------------------------


def test_both_directions_fail():
    # issue 40: event with idem_key field, key absent from idem_keys (dir 1)
    # issue 50: key in idem_keys, no history event (dir 2)
    idem = _idem({"escrow_create_50_t5s1_gauntlet": "2026-01-01T00:00:00Z"})
    events = [_create(40, "escrow_create_40_t4s1_gauntlet")]
    missing, orphaned = run_coverage_check(idem, events)
    assert len(missing) == 1
    assert missing[0]["issue"] == "40"
    assert len(orphaned) == 1
    assert orphaned[0]["issue"] == "50"


# ---------------------------------------------------------------------------
# Test 5: event without idem_key field is skipped (legacy event)
# ---------------------------------------------------------------------------


def test_event_without_idem_key_skipped():
    idem = _idem()
    events = [_create(60)]  # no idem_key field → legacy, skip
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 6: returned escrow with missing key is exempt
# ---------------------------------------------------------------------------


def test_returned_escrow_missing_key_exempt():
    idem = _idem()  # key not registered
    events = [
        _create(70, "escrow_create_70_t7s1_gauntlet"),
        _return(70),  # escrow was returned → exempt from direction 1
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 7: escrow_return_bulk exempts covered issues
# ---------------------------------------------------------------------------


def test_return_bulk_exempts_issues():
    idem = _idem()  # no keys registered
    events = [
        _create(80, "escrow_create_80_t8s1_gauntlet"),
        _create(81, "escrow_create_81_t8s2_gauntlet"),
        _return_bulk([80, 81]),
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 8: idem key in nested 'keys' object is found
# ---------------------------------------------------------------------------


def test_nested_keys_object_found():
    # load_idem_keys merges nested keys — simulate that merge here
    idem = _idem(keys_nested={"escrow_create_90_t9s1_gauntlet": "2026-01-01T00:00:00Z"})
    events = [_create(90, "escrow_create_90_t9s1_gauntlet")]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 9: idem key at top level is found
# ---------------------------------------------------------------------------


def test_toplevel_key_found():
    idem = _idem(keys_toplevel={"escrow_create_100_t10s1_gauntlet": "2026-01-01T00:00:00Z"})
    events = [_create(100, "escrow_create_100_t10s1_gauntlet")]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 10: key with long/unusual suffix is parsed correctly
# ---------------------------------------------------------------------------


def test_unusual_suffix_parsed():
    idem = _idem({"escrow_create_110_manual_override_extra": "2026-01-01T00:00:00Z"})
    events = [_create(110, "escrow_create_110_manual_override_extra")]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 11: empty inputs — no events, no idem keys → PASS
# ---------------------------------------------------------------------------


def test_empty_inputs_pass():
    missing, orphaned = run_coverage_check({}, [])
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 12: malformed idem_key field (wrong prefix) is ignored
# ---------------------------------------------------------------------------


def test_wrong_prefix_idem_key_ignored():
    idem = _idem()
    events = [
        {"type": "escrow_create", "issue": 120, "idem_key": "escrow|120|agent0"},
        {"type": "escrow_create", "issue": 121, "idem_key": "payment|121|agent0"},
        {"type": "escrow_create", "issue": 122},  # no field at all
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 13: multiple missing active escrows reported individually
# ---------------------------------------------------------------------------


def test_multiple_missing_active_escrows():
    idem = _idem()
    events = [
        _create(130, "escrow_create_130_t13s1_gauntlet"),
        _create(131, "escrow_create_131_t13s2_gauntlet"),
        _create(132, "escrow_create_132_t13s3_gauntlet"),
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert len(missing) == 3
    issues = {m["issue"] for m in missing}
    assert issues == {"130", "131", "132"}
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 14: multiple orphaned idem keys reported individually
# ---------------------------------------------------------------------------


def test_multiple_orphaned_idem_keys():
    idem = _idem({
        "escrow_create_140_t14s1_gauntlet": "2026-01-01T00:00:00Z",
        "escrow_create_141_t14s2_gauntlet": "2026-01-01T00:00:00Z",
    })
    events = []  # no history events
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert len(orphaned) == 2
    issues = {o["issue"] for o in orphaned}
    assert issues == {"140", "141"}


# ---------------------------------------------------------------------------
# Test 15: return_bulk covers events even when key also missing
# ---------------------------------------------------------------------------


def test_return_bulk_covers_missing_key():
    idem = _idem()  # no key registered for issue 150
    events = [
        _create(150, "escrow_create_150_t15s1_gauntlet"),
        _return_bulk([150, 151, 152]),  # 150 is in the bulk return
    ]
    missing, orphaned = run_coverage_check(idem, events)
    # Issue 150 was returned via bulk → exempt
    assert missing == []
    assert orphaned == []


# ===========================================================================
# --since flag tests (Tests 16–23)
# ===========================================================================

# Helper: create an escrow_create event with an explicit timestamp field.

def _create_ts(issue: int, idem_key: str, created_at: str) -> dict:
    """Like _create() but with a created_at timestamp field."""
    return {
        "type": "escrow_create",
        "issue": issue,
        "amount": 30,
        "idem_key": idem_key,
        "created_at": created_at,
    }


# ---------------------------------------------------------------------------
# Test 16: --since filters pre-date events in direction 1; no false positives
# ---------------------------------------------------------------------------


def test_since_filters_pre_date_events_direction1():
    # Issue 160: event dated 2026-03-01 (before since=2026-04-01)
    # No key registered — would be direction-1 FAIL without --since
    idem = _idem()
    events = [_create_ts(160, "escrow_create_160_t16s1_gauntlet", "2026-03-01T12:00:00Z")]
    since = date(2026, 4, 1)
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # Event is before since → skipped → no violation
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 17: --since after all events gives PASS even if gaps would exist
# ---------------------------------------------------------------------------


def test_since_after_all_events_gives_pass():
    # Issue 170: key in idem_keys but NO history event → direction-2 gap
    # Key's value is dated 2026-03-15, well before since=2026-05-01
    idem = _idem({"escrow_create_170_t17s1_gauntlet": "2026-03-15T00:00:00Z"})
    events = []  # no history events at all
    since = date(2026, 5, 1)
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # Key's value predate since → key skipped in direction 2 → PASS
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 18: no --since flag still checks all events (unchanged behavior)
# ---------------------------------------------------------------------------


def test_no_since_checks_all_events():
    # Issue 180: old event (2026-01-01) with key absent — would be violation
    idem = _idem()  # no key registered
    events = [_create_ts(180, "escrow_create_180_t18s1_gauntlet", "2026-01-01T00:00:00Z")]
    # No since → must detect the missing key
    missing, orphaned = run_coverage_check(idem, events)
    assert len(missing) == 1
    assert missing[0]["issue"] == "180"
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 19: --since boundary — event exactly on since date is included
# ---------------------------------------------------------------------------


def test_since_boundary_event_on_date_included():
    # Issue 190: event exactly on 2026-04-01 — should be CHECKED (>= since)
    # No key registered → direction-1 violation expected
    idem = _idem()
    events = [_create_ts(190, "escrow_create_190_t19s1_gauntlet", "2026-04-01T00:00:00Z")]
    since = date(2026, 4, 1)
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # Event is exactly on since date → included → missing key detected
    assert len(missing) == 1
    assert missing[0]["issue"] == "190"
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 20: --since with future date gives PASS (no events in scope)
# ---------------------------------------------------------------------------


def test_since_future_date_gives_pass():
    # Issue 200: recent event with missing key
    idem = _idem()
    events = [_create_ts(200, "escrow_create_200_t20s1_gauntlet", "2026-04-17T00:00:00Z")]
    since = date(2099, 1, 1)  # far future
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # All events are before since → nothing checked → PASS
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 21: --since filters direction 2 idem keys by timestamp value
# ---------------------------------------------------------------------------


def test_since_filters_direction2_by_key_timestamp():
    # Key for issue 210 registered on 2026-03-01 (before since=2026-04-01)
    # No history event for issue 210 → would be direction-2 FAIL without since
    idem = _idem({"escrow_create_210_t21s1_gauntlet": "2026-03-01T00:00:00Z"})
    events = []  # no history
    since = date(2026, 4, 1)
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # Key predate since → skipped in direction 2 → PASS
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 22: returned escrow before since still exempts direction-1 post-since
# ---------------------------------------------------------------------------


def test_since_returned_before_since_exempts_post_since_event():
    # Issue 220: return event (no timestamp on return) happened in history.
    # A new escrow_create on 2026-04-05 with missing key should be exempt
    # because the issue was already returned.
    idem = _idem()  # no key registered
    events = [
        _create_ts(220, "escrow_create_220_t22s1_gauntlet", "2026-04-05T00:00:00Z"),
        _return(220),  # returned — no date needed for lookup structures
    ]
    since = date(2026, 4, 1)
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # Event is on/after since → checked; but issue was returned → exempt
    assert missing == []
    assert orphaned == []


# ---------------------------------------------------------------------------
# Test 23: idem key with no parseable timestamp value is always checked
# ---------------------------------------------------------------------------


def test_since_key_without_timestamp_always_checked():
    # Key for issue 230 has a non-timestamp value (e.g. boolean True)
    # No history event → would be orphaned → must still be reported even with --since
    idem = _idem({"escrow_create_230_t23s1_gauntlet": True})  # type: ignore[arg-type]
    events = []  # no history event
    since = date(2026, 4, 1)
    missing, orphaned = run_coverage_check(idem, events, since=since)
    # Key value is not a string → cannot filter by date → check unconditionally
    assert len(orphaned) == 1
    assert orphaned[0]["issue"] == "230"
    assert missing == []
