#!/usr/bin/env python3
"""Adversarial tests for scripts/check_escrow_idem_coverage.py.

Bypass vectors discovered:
  GAP-1: Partial return masking — one escrow_return for issue N exempts ALL
         escrow_create events for issue N, including unregistered ones whose
         escrows may still be active.
  GAP-2: Non-regex key format escapes Direction 2 — orphaned idem_keys whose
         issue portion doesn't match r'^escrow_create_(\\d+)_' (e.g. no
         trailing underscore after digits) are silently skipped.
  GAP-3: Phantom history coverage — any escrow_create event for issue N
         (even a legacy event with no idem_key field) suppresses Direction 2
         orphaned-key detection for ALL escrow_create_N_* keys in
         idem_keys.json.
  GAP-4: Integer idem_key bypasses Direction 1 — if event["idem_key"] is an
         integer (not a string), isinstance check silently skips it; the
         active escrow is invisible.
  GAP-5: load_idem_keys silently drops keys when "keys" field is a list —
         non-dict "keys" is swallowed; Direction 2 sees an empty dict.

Non-bypass adversarial cases (correctly detected or edge-bounded):
  ADV-6:  escrow_return with blank issue "" does NOT populate returned_issues
          (correct — but means a blank-issue escrow_create is never exempted).
  ADV-7:  escrow_return_bulk with integer issues still populates returned_issues
          correctly (no bypass here).
  ADV-8:  idem_key starts with escrow_create_ but has double underscore
          (empty issue digits) — Direction 2 skips due to regex miss.
  ADV-9:  issue field None in escrow_create converts to "None" string — does
          NOT collide with numeric issue strings (correct boundary).
  ADV-10: escrow_return for a different issue does NOT exempt the active one
          (verified: Direction 1 correctly fires).
  ADV-11: Multiple events same issue all unregistered — all flagged (no
          partial-return present).
  ADV-12: Top-level key named "version" is excluded from the idem scan —
          correctly skipped (won't generate false orphan).
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_escrow_idem_coverage import (  # noqa: E402
    load_idem_keys,
    run_coverage_check,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _create(issue, idem_key=None) -> dict:
    e: dict = {"type": "escrow_create", "issue": issue, "amount": 30}
    if idem_key is not None:
        e["idem_key"] = idem_key
    return e


def _return(issue) -> dict:
    return {"type": "escrow_return", "issue": issue, "amount": 30}


def _return_bulk(issues: list) -> dict:
    return {"type": "escrow_return_bulk", "issues": issues}


def _write_idem_file(data: dict) -> Path:
    """Write a temporary idem_keys.json and return its Path."""
    tmp = tempfile.NamedTemporaryFile(
        suffix=".json", delete=False, mode="w", encoding="utf-8"
    )
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


# ===========================================================================
# GAP TESTS — confirmed bypass vectors where checker returns PASS despite a
# real coverage violation.
# ===========================================================================


def test_gap1_partial_return_masks_unregistered_sibling_idem_key():
    """GAP-1: Partial return masking.

    Mechanism:
        `returned_issues` is keyed on issue NUMBER, not on a specific
        escrow_create event or its idem_key.  When two separate escrow_create
        events exist for the same issue (e.g. re-escrow after a failed
        delivery), a single escrow_return for that issue marks the entire
        issue as "returned."  Direction 1 then silently skips ALL events for
        that issue, including a second event whose idem_key is absent from
        idem_keys.json and whose escrow was never actually returned.

    Exploit path:
        issue 200:
          event A — idem_key "escrow_create_200_v1", registered ✓
          event B — idem_key "escrow_create_200_v2", NOT registered (gap!)
          escrow_return for issue 200 (covers only event A)

        Direction 1 sees issue "200" in returned_issues → skips event B.
        Result: PASS, but escrow_create_200_v2 is an active unguarded escrow.
    """
    # GAP: Direction 1 skips event B because issue 200 is in returned_issues,
    # even though event B's idem_key is unregistered and its escrow is active.
    idem = {"escrow_create_200_v1": "2026-01-01T00:00:00Z"}
    events = [
        _create(200, "escrow_create_200_v1"),   # registered — clean
        _create(200, "escrow_create_200_v2"),   # NOT registered — real gap
        _return(200),                           # only one escrow was returned
    ]
    missing, orphaned = run_coverage_check(idem, events)
    # Bypass confirmed: script returns PASS (missing == [], orphaned == [])
    assert missing == [], f"Expected bypass (no missing reported), got {missing}"
    assert orphaned == [], f"Expected bypass (no orphaned reported), got {orphaned}"


def test_gap2_orphaned_key_with_no_trailing_underscore_escapes_direction2():
    """GAP-2: Non-regex key format escapes Direction 2.

    Mechanism:
        _issue_from_key() uses r'^escrow_create_(\\d+)_' — requires a
        trailing underscore after the issue digits.  Keys that start with
        "escrow_create_" but lack the trailing underscore (e.g.
        "escrow_create_42abc" or "escrow_create_42") cause
        _issue_from_key() to return None, triggering `continue` in Direction
        2.  The orphaned key is never reported.

    Exploit path:
        idem_keys.json has "escrow_create_42abc" (no trailing underscore).
        No matching escrow_create history event exists.
        Direction 2 skips this key → orphaned key is invisible → PASS.
    """
    # GAP: "escrow_create_42abc" starts with the escrow_create_ prefix but
    # _issue_from_key returns None (regex requires digits then underscore),
    # so Direction 2 silently skips it.
    idem = {"escrow_create_42abc": "2026-01-01T00:00:00Z"}
    events = []  # no history events at all — this is a true orphan
    missing, orphaned = run_coverage_check(idem, events)
    # Bypass confirmed: orphaned key is not reported
    assert missing == [], f"Expected bypass (no missing reported), got {missing}"
    assert orphaned == [], f"Expected bypass (no orphaned reported), got {orphaned}"


def test_gap2b_key_ending_without_underscore_after_digits_escapes_direction2():
    """GAP-2b: Key with no separator between digits and suffix also escapes.

    Same root cause as GAP-2 but with a digit-only suffix (no alpha chars).
    "escrow_create_42" has no trailing underscore → regex miss → SKIP.
    """
    # GAP: "escrow_create_42" has no trailing underscore → _issue_from_key
    # returns None → Direction 2 skips it.
    idem = {"escrow_create_42": "2026-01-01T00:00:00Z"}
    events = []
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == [], f"Expected bypass, got {missing}"
    assert orphaned == [], f"Expected bypass, got {orphaned}"


def test_gap3_phantom_history_coverage_via_legacy_event():
    """GAP-3: Phantom history coverage — legacy event suppresses Direction 2.

    Mechanism:
        Direction 2 checks `issue not in history_escrow_issues`.
        `history_escrow_issues` is populated from ALL escrow_create events
        regardless of whether they carry an idem_key field.  A legacy
        escrow_create event (no idem_key) for issue 99 adds "99" to
        history_escrow_issues, which prevents any idem_keys.json entry keyed
        on issue 99 from being flagged as orphaned — even one that was
        registered for a completely different, now-deleted event.

    Exploit path:
        idem_keys.json has "escrow_create_99_stale" (orphaned — its original
        event is gone or was never associated with the current history).
        A legacy escrow_create event for issue 99 (no idem_key) exists.
        Direction 2: "99" is in history_escrow_issues → NOT orphaned → PASS.
    """
    # GAP: The legacy event for issue 99 provides phantom coverage.
    # "escrow_create_99_stale" is truly orphaned (no event registered it) but
    # Direction 2 sees issue "99" in history_escrow_issues and passes.
    idem = {"escrow_create_99_stale": "2026-01-01T00:00:00Z"}
    events = [
        _create(99),  # legacy event — NO idem_key field at all
    ]
    missing, orphaned = run_coverage_check(idem, events)
    # Bypass confirmed: orphaned key is not flagged because "99" is in
    # history_escrow_issues from the legacy event
    assert missing == [], f"Expected bypass, got {missing}"
    assert orphaned == [], f"Expected bypass, got {orphaned}"


def test_gap4_integer_idem_key_in_event_bypasses_direction1():
    """GAP-4: Integer idem_key bypasses Direction 1.

    Mechanism:
        Direction 1 guards with:
            if not isinstance(idem, str) or not idem.startswith(...):
                continue
        If event["idem_key"] is an integer (42) rather than a string, the
        isinstance check fails and the event is silently skipped.  The active
        escrow has no idem_key registered and is never flagged.

    Exploit path:
        escrow_create event with idem_key=42 (integer), no escrow_return.
        idem_keys.json is empty.
        Direction 1: isinstance(42, str) → False → SKIP → PASS.
    """
    # GAP: Integer idem_key is silently ignored; the active escrow coverage
    # gap is invisible to Direction 1.
    idem: dict = {}
    events = [
        {"type": "escrow_create", "issue": 300, "idem_key": 300, "amount": 30},
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == [], f"Expected bypass, got {missing}"
    assert orphaned == [], f"Expected bypass, got {orphaned}"


def test_gap5_load_idem_keys_silently_drops_list_format_keys():
    """GAP-5: load_idem_keys silently drops keys when 'keys' field is a list.

    Mechanism:
        load_idem_keys checks `if isinstance(nested, dict)` before calling
        merged.update(nested).  If "keys" is a list (e.g. a malformed or
        legacy format), it is silently ignored.  The top-level scan then
        skips "keys" by name.  The result is an empty merged dict; Direction
        2 sees no registered escrow_create_ keys and returns PASS.

    Exploit path:
        idem_keys.json = {"keys": ["escrow_create_400_orphaned"]}
        No history events.
        load_idem_keys returns {} → Direction 2 finds no keys → PASS.
        But "escrow_create_400_orphaned" should have been checked.
    """
    # GAP: The list-format "keys" is silently dropped; the orphaned entry
    # is invisible to both directions.
    idem_data = {"keys": ["escrow_create_400_orphaned"]}
    idem_path = _write_idem_file(idem_data)
    try:
        merged = load_idem_keys(idem_path)
    finally:
        idem_path.unlink(missing_ok=True)

    # merged should be empty — the list was silently dropped
    assert "escrow_create_400_orphaned" not in merged, (
        "Expected bypass: list-format key should be absent from merged dict"
    )
    # Confirm: running the coverage check with this empty merged dict returns PASS
    missing, orphaned = run_coverage_check(merged, [])
    assert missing == [] and orphaned == [], (
        "Expected PASS (both empty) due to empty merged idem dict"
    )


# ===========================================================================
# NON-BYPASS ADVERSARIAL TESTS — edge cases that are correctly detected or
# correctly bounded.
# ===========================================================================


def test_adv6_blank_issue_escrow_return_does_not_propagate():
    """ADV-6: escrow_return with blank issue "" does NOT exempt anything.

    An escrow_return event where issue="" produces str("") = "" which fails
    `if issue:` check → NOT added to returned_issues.  A subsequent
    escrow_create for the same blank issue is therefore NOT exempted and will
    be flagged if its idem_key is absent.  The blank-issue escrow_create is
    also not exempted via escrow_return_bulk (since "" is not in any bulk list).
    """
    idem: dict = {}
    events = [
        _create("", "escrow_create__fuzz_key"),  # blank issue, active
        {"type": "escrow_return", "issue": "", "amount": 30},  # blank return
    ]
    missing, orphaned = run_coverage_check(idem, events)
    # "escrow_create__fuzz_key" starts with the prefix but has no digits →
    # Direction 1 sees it is missing from idem_keys, issue="" is NOT in
    # returned_issues (because blank-issue return is skipped), → FLAGGED
    assert len(missing) == 1, f"Expected 1 missing, got {missing}"
    assert missing[0]["idem_key"] == "escrow_create__fuzz_key"


def test_adv7_return_bulk_with_integer_issues_normalizes_correctly():
    """ADV-7: escrow_return_bulk with integer issues converts to strings correctly.

    No bypass here: str(42) == "42", so integer issues in bulk events
    correctly match string issues from escrow_create events.
    """
    idem: dict = {}
    events = [
        _create(42, "escrow_create_42_bulk_test"),
        _return_bulk([42]),  # integer in list, same as string "42"
    ]
    missing, orphaned = run_coverage_check(idem, events)
    # Escrow returned → exempt from Direction 1
    assert missing == []
    assert orphaned == []


def test_adv8_double_underscore_key_escapes_direction2():
    """ADV-8: Key with empty issue digits (double underscore) escapes Direction 2.

    "escrow_create__suffix" starts with the prefix but has no digits between
    the underscores — regex r'^escrow_create_(\\d+)_' requires at least one
    digit.  _issue_from_key returns None → Direction 2 skips.

    This is the same class of bug as GAP-2 but at the boundary of zero digits.
    """
    idem = {"escrow_create__suffix": "2026-01-01T00:00:00Z"}
    events = []
    missing, orphaned = run_coverage_check(idem, events)
    # Regex miss on empty digits → key silently skipped by Direction 2
    assert orphaned == [], f"Expected Direction 2 skip (regex miss), got {orphaned}"


def test_adv9_none_issue_in_event_does_not_collide_with_numeric_issues():
    """ADV-9: issue=None in event becomes str "None" — no collision with integers.

    If an escrow_create event has issue=None and idem_key="escrow_create_None_abc",
    the issue becomes "None" (not "42"). A separate escrow_return for issue=42
    does NOT exempt the "None" event — they don't collide.
    This is correct behavior (no bypass), but verifies the boundary.
    """
    idem: dict = {}
    events = [
        # None issue — idem_key references literal "None"
        {"type": "escrow_create", "issue": None, "idem_key": "escrow_create_None_abc"},
        _return(42),  # returning issue 42 — must NOT pardon None issue
    ]
    missing, orphaned = run_coverage_check(idem, events)
    # "escrow_create_None_abc" starts with prefix, NOT in idem_keys,
    # "None" NOT in returned_issues (only "42" is there) → FLAGGED
    assert len(missing) == 1
    assert missing[0]["idem_key"] == "escrow_create_None_abc"


def test_adv10_escrow_return_for_different_issue_does_not_exempt_active():
    """ADV-10: escrow_return for issue 55 does NOT exempt issue 56.

    Confirms that the returned_issues check is per-issue and does not
    cross-contaminate: FAIL is correctly reported for issue 56.
    """
    idem: dict = {}
    events = [
        _create(56, "escrow_create_56_active"),
        _return(55),  # different issue — must not exempt 56
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert len(missing) == 1
    assert missing[0]["idem_key"] == "escrow_create_56_active"
    assert missing[0]["issue"] == "56"


def test_adv11_multiple_unregistered_events_same_issue_all_flagged():
    """ADV-11: Multiple unregistered events for same issue are all flagged.

    Partial-return masking (GAP-1) requires an escrow_return to be present.
    Without it, all unregistered idem_keys are correctly reported.
    """
    idem: dict = {}
    events = [
        _create(77, "escrow_create_77_first"),
        _create(77, "escrow_create_77_second"),
        # no escrow_return for 77
    ]
    missing, orphaned = run_coverage_check(idem, events)
    assert len(missing) == 2
    keys_reported = {m["idem_key"] for m in missing}
    assert "escrow_create_77_first" in keys_reported
    assert "escrow_create_77_second" in keys_reported


def test_adv12_version_key_excluded_from_idem_scan():
    """ADV-12: Top-level "version" key is excluded — no false orphan.

    load_idem_keys skips top-level keys named "version" and "keys" to avoid
    treating metadata as idem_keys.  This is correct behavior: a "version"
    key in the JSON file should not trigger Direction 2.
    """
    # Simulate load_idem_keys output: "version" was stripped, only real keys remain
    idem = {"escrow_create_500_real": "2026-01-01T00:00:00Z"}
    events = [_create(500, "escrow_create_500_real")]
    missing, orphaned = run_coverage_check(idem, events)
    assert missing == []
    assert orphaned == []


def test_adv13_load_idem_keys_version_key_not_treated_as_idem():
    """ADV-13: load_idem_keys correctly excludes top-level 'version' key.

    Even though the JSON has a top-level "version" field that doesn't start
    with "escrow_create_", load_idem_keys excludes it from the merged dict
    via the explicit exclusion in the secondary scan.  Direction 2 would not
    generate a false orphan for "version".
    """
    idem_data = {
        "version": "2026-01-01",
        "keys": {"escrow_create_600_t1s1": "2026-01-01T00:00:00Z"},
    }
    idem_path = _write_idem_file(idem_data)
    try:
        merged = load_idem_keys(idem_path)
    finally:
        idem_path.unlink(missing_ok=True)

    assert "version" not in merged, "version metadata must be excluded"
    assert "escrow_create_600_t1s1" in merged, "real idem_key must be present"
