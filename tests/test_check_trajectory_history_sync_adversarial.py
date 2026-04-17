"""Adversarial tests for scripts/check_trajectory_history_sync.py

Each test targets a specific bypass vector — inputs that cause the checker to
return PASS (status == "PASS") when there is a real synchronization violation,
or expose silent failure modes where violations are swallowed without warning.

All tests are self-contained: in-memory string/list fixtures and pytest
tmp_path temporary directories only.  No real ledger files are read.

Bypass vectors covered:
  1.  [GAP] String-typed slot in history event → event silently dropped → PASS
  2.  [GAP] Float-typed slot in JSON entry → entry silently dropped → PASS
  3.  [GAP] Amount/agents field mismatch ignored — only (trajectory, slot) matched
  4.  [GAP] Non-.jsonl history file silently ignored → event never seen → PASS
  5.  [GAP] Leading garbage in history line breaks parser → event dropped → PASS
  6.  [GAP] Numeric trajectory in history event → event dropped → PASS
  7.  _iter_json_objects: leading garbage causes immediate break (unit)
  8.  _iter_json_objects: concatenated JSON objects both parsed (baseline unit)
  9.  _iter_json_objects: trailing garbage — first object captured, rest dropped
 10.  extract_json_keys silently drops entries with string-typed slot
 11.  extract_json_keys silently drops entries with float-typed slot
 12.  extract_json_keys silently drops entries with missing trajectory field
 13.  Duplicate (trajectory, slot) in JSON collapses via set — structural error invisible
 14.  Type-case sensitivity: "Trajectory_Mint" ≠ "trajectory_mint" → event missed → FAIL
 15.  load_history_mints skips trajectory_mint with None trajectory field
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_trajectory_history_sync import (
    _iter_json_objects,
    extract_json_keys,
    load_history_mints,
    run_check,
)


# ---------------------------------------------------------------------------
# Test 1 — [GAP] String-typed slot in history event → event dropped → PASS
# ---------------------------------------------------------------------------


def test_string_slot_in_history_hides_event(tmp_path: Path) -> None:
    """[CONFIRMED GAP] load_history_mints checks isinstance(slot, int) before
    adding a key.  A history trajectory_mint event where slot is a JSON string
    ("5" instead of 5) is silently discarded.  history_keys is empty for that
    entry even though the event physically exists in the file.

    Real violation: history has a trajectory_mint for (T1, slot=5) written with
    a string-typed slot.  trajectory_mints.json has no corresponding entry.
    The checker should report missing_from_json = [(T1, 5)], but because the
    history event is dropped by the isinstance guard, history_keys is empty →
    json_keys is also empty → PASS.

    Bypass mechanism: isinstance(slot, int) guard in load_history_mints silently
    discards any event where slot is not a bare Python int.  A string-typed slot
    (which is valid JSON and non-null) is rejected without warning.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: no entry for (T1, 5)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": []}),
        encoding="utf-8",
    )

    # History: trajectory_mint with string-typed slot — not a valid int
    (history / "cycle.jsonl").write_text(
        json.dumps({"type": "trajectory_mint", "trajectory": "T1", "slot": "5", "amount": 37}),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    # GAP: string slot causes isinstance(slot, int) to return False → event dropped
    assert result["status"] == "PASS", (
        "History has a trajectory_mint for (T1, '5') but the string slot fails "
        "isinstance(slot, int).  The event is silently dropped; history_keys is "
        "empty; missing_from_json is never raised.  PASS despite a real violation."
    )
    assert result["missing_from_json"] == [], (
        "missing_from_json should have contained (T1, 5) but the event was "
        "dropped before it could be added to history_keys."
    )


# ---------------------------------------------------------------------------
# Test 2 — [GAP] Float-typed slot in JSON entry → entry dropped → PASS
# ---------------------------------------------------------------------------


def test_float_slot_in_json_hides_entry(tmp_path: Path) -> None:
    """[CONFIRMED GAP] extract_json_keys checks isinstance(slot, int) before
    adding a key.  In Python 3, isinstance(7.0, int) is False — float-typed
    slots are silently discarded.  json_keys is empty for that entry.

    Real violation: trajectory_mints.json has an entry for (T2, slot=7) written
    with a float-typed slot (7.0).  There is no matching history event.  The
    checker should report missing_from_history = [(T2, 7)], but because the
    JSON entry is dropped by the isinstance guard, json_keys is empty → PASS.

    This can occur when the mint ledger is written by a system that serializes
    all numbers as floats (JavaScript JSON.stringify, certain Python serializers).

    Bypass mechanism: isinstance(slot, int) in extract_json_keys rejects float
    slots without warning.  Note: bool is a subclass of int so True/False (1/0)
    would pass — only bare floats are silently dropped.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: entry with float-typed slot (7.0)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": [{"trajectory": "T2", "slot": 7.0, "amount": 20}]}),
        encoding="utf-8",
    )

    # History: no entry for (T2, 7) — no .jsonl files
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": [{"trajectory": "T2", "slot": 7.0, "amount": 20}]}),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    # GAP: float slot 7.0 fails isinstance(slot, int) → json entry dropped
    assert result["status"] == "PASS", (
        "JSON has a mint for (T2, 7.0) but float slot fails isinstance(slot, int). "
        "The entry is silently dropped; json_keys is empty; missing_from_history "
        "is never raised.  PASS despite a real violation."
    )
    assert result["missing_from_history"] == []


# ---------------------------------------------------------------------------
# Test 3 — [GAP] Amount field mismatch not detected — only (trajectory, slot) matched
# ---------------------------------------------------------------------------


def test_amount_mismatch_not_detected(tmp_path: Path) -> None:
    """[CONFIRMED GAP] The checker only validates that (trajectory, slot) keys
    match between JSON and history.  It does not compare amount, agents,
    per_agent, or any other payload field.

    Real violation: trajectory_mints.json records 37 WEA for (T3, 10) but the
    history event shows 9999 WEA for the same slot.  The data disagreement is
    a real synchronization error — one source was written incorrectly.  But
    because both sides have the same (trajectory, slot) key, run_check sees no
    difference and returns PASS.

    Bypass mechanism: run_check computes set differences of (trajectory, slot)
    tuples only.  Payload fields (amount, agents, per_agent, idem_key) are
    never read or compared during the cross-validation.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: correct key, amount = 37
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": [{"trajectory": "T3", "slot": 10, "amount": 37}]}),
        encoding="utf-8",
    )

    # History: same key, amount = 9999 (major discrepancy)
    (history / "cycle.jsonl").write_text(
        json.dumps(
            {"type": "trajectory_mint", "trajectory": "T3", "slot": 10, "amount": 9999}
        ),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    # GAP: only key presence is checked; 9999 vs 37 amount mismatch is invisible
    assert result["status"] == "PASS", (
        "Amount mismatch (JSON=37, history=9999) is not detected.  The checker "
        "only validates (trajectory, slot) key presence, not data correctness."
    )
    assert result["missing_from_history"] == []
    assert result["missing_from_json"] == []


# ---------------------------------------------------------------------------
# Test 4 — [GAP] Non-.jsonl history file silently ignored
# ---------------------------------------------------------------------------


def test_non_jsonl_history_file_silently_ignored(tmp_path: Path) -> None:
    """[CONFIRMED GAP] load_history_mints uses glob("*.jsonl") to discover
    history files.  Any file with a different extension (.json, .log, .txt)
    is silently ignored even if it contains valid trajectory_mint events.

    Real violation: a history file was written as 'mints.json' rather than
    'mints.jsonl'.  It contains a valid trajectory_mint for (T4, 8).
    trajectory_mints.json has no corresponding entry.  The checker should
    report missing_from_json = [(T4, 8)], but the .json file is never read
    by glob("*.jsonl") → history_keys is empty → PASS.

    Bypass mechanism: history_dir.glob("*.jsonl") only matches files with the
    exact .jsonl extension.  All other extensions are invisible to the scanner
    regardless of file content.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: no entry for (T4, 8)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": []}),
        encoding="utf-8",
    )

    # History event in a .json file — will not be discovered by glob("*.jsonl")
    (history / "mints.json").write_text(
        json.dumps(
            {"type": "trajectory_mint", "trajectory": "T4", "slot": 8, "amount": 29}
        ),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    # GAP: .json file ignored; history_keys empty; missing_from_json never raised
    assert result["status"] == "PASS", (
        "A trajectory_mint event in mints.json is silently ignored because "
        "glob('*.jsonl') only matches .jsonl files.  The history→JSON check "
        "never sees the event."
    )
    assert result["missing_from_json"] == []


# ---------------------------------------------------------------------------
# Test 5 — [GAP] Leading garbage in history line breaks parser → event dropped
# ---------------------------------------------------------------------------


def test_leading_garbage_in_history_line_hides_event(tmp_path: Path) -> None:
    """[CONFIRMED GAP] _iter_json_objects processes each line with raw_decode
    starting at position 0.  On JSONDecodeError it immediately breaks out of
    the parsing loop — it does NOT skip the offending character and retry.

    A line beginning with a non-JSON byte causes an immediate break.  All JSON
    objects on that line — including ones that follow the garbage prefix — are
    silently dropped with no warning.

    Real violation: a trajectory_mint for (T5, 12) is in a history file but on
    a line beginning with a stray byte.  trajectory_mints.json has no entry for
    (T5, 12).  The checker should report missing_from_json = [(T5, 12)], but
    the event is dropped by the parser → history_keys is empty → PASS.

    Bypass mechanism: `except json.JSONDecodeError: break` in _iter_json_objects
    terminates parsing on the first error rather than advancing past the bad
    character to recover subsequent valid objects.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: no entry for (T5, 12)
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": []}),
        encoding="utf-8",
    )

    # History line: starts with garbage byte — valid JSON object follows but is unreachable
    corrupted_line = 'X{"type":"trajectory_mint","trajectory":"T5","slot":12,"amount":41}'
    (history / "cycle.jsonl").write_text(corrupted_line, encoding="utf-8")

    result = run_check(tmp_path)

    # GAP: 'X' at pos=0 triggers JSONDecodeError + break; event at pos=1 is never reached
    assert result["status"] == "PASS", (
        "Leading 'X' byte causes _iter_json_objects to break immediately.  The "
        "trajectory_mint for (T5, 12) is never read; both sets empty → PASS "
        "despite a real history event lacking a JSON entry."
    )
    assert result["missing_from_json"] == []


# ---------------------------------------------------------------------------
# Test 6 — [GAP] Numeric trajectory in history event → event dropped → PASS
# ---------------------------------------------------------------------------


def test_numeric_trajectory_in_history_hides_event(tmp_path: Path) -> None:
    """[CONFIRMED GAP] load_history_mints checks isinstance(traj, str) before
    adding a key.  A trajectory_mint event where trajectory is an integer (e.g.
    1 instead of "T1") fails the isinstance check and is silently dropped.

    Real violation: history has a trajectory_mint for (trajectory=1, slot=5).
    trajectory_mints.json has no corresponding entry.  The checker should report
    missing_from_json = [(1, 5)] (or the canonical string form), but the event
    is skipped → history_keys is empty → PASS.

    This can occur when trajectory IDs are stored as integers in the source
    system and not converted to the canonical "T<N>" string form.

    Bypass mechanism: isinstance(traj, str) guard in load_history_mints rejects
    numeric trajectory values silently; no warning or error is emitted.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: no entry for trajectory=1
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": []}),
        encoding="utf-8",
    )

    # History: trajectory_mint with integer trajectory (not string)
    (history / "cycle.jsonl").write_text(
        json.dumps({"type": "trajectory_mint", "trajectory": 1, "slot": 5, "amount": 37}),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    # GAP: isinstance(1, str) = False → event dropped; history_keys empty → PASS
    assert result["status"] == "PASS", (
        "Numeric trajectory (1 instead of 'T1') causes load_history_mints to "
        "drop the event.  history_keys empty → PASS despite history having a "
        "trajectory_mint not reflected in JSON."
    )
    assert result["missing_from_json"] == []


# ---------------------------------------------------------------------------
# Test 7 — _iter_json_objects: leading garbage → immediate break (unit)
# ---------------------------------------------------------------------------


def test_iter_json_objects_leading_garbage_drops_all() -> None:
    """_iter_json_objects breaks on the first JSONDecodeError at position 0.
    A line beginning with an invalid JSON byte causes an immediate break;
    valid JSON objects that follow the garbage prefix are never reached.

    This is the low-level parser behaviour underlying the GAP in test 5.
    The break-on-error design was intended to handle concatenated objects
    but unintentionally makes recovery from garbage prefixes impossible.
    """
    line = 'CORRUPT{"type":"trajectory_mint","trajectory":"T1","slot":5}'
    result = _iter_json_objects(line)
    assert result == [], (
        "_iter_json_objects breaks at pos=0 because 'C' is not valid JSON. "
        "The valid object after the prefix is never attempted."
    )


# ---------------------------------------------------------------------------
# Test 8 — _iter_json_objects: concatenated objects both parsed (baseline)
# ---------------------------------------------------------------------------


def test_iter_json_objects_concatenated_objects_both_parsed() -> None:
    """Baseline: _iter_json_objects correctly parses two concatenated JSON
    objects with no separator on a single line.

    This documents the intended use-case that the raw_decode loop was designed
    for.  Contrast with test 7: the same mechanism that handles concatenation
    fails to recover from a garbage prefix — valid objects after garbage are
    lost, but valid objects after another valid object are captured.
    """
    line = (
        '{"type":"trajectory_mint","trajectory":"T1","slot":5}'
        '{"type":"trajectory_mint","trajectory":"T2","slot":6}'
    )
    result = _iter_json_objects(line)
    assert len(result) == 2
    assert result[0] == {"type": "trajectory_mint", "trajectory": "T1", "slot": 5}
    assert result[1] == {"type": "trajectory_mint", "trajectory": "T2", "slot": 6}


# ---------------------------------------------------------------------------
# Test 9 — _iter_json_objects: trailing garbage after valid object
# ---------------------------------------------------------------------------


def test_iter_json_objects_trailing_garbage_partial_parse() -> None:
    """_iter_json_objects captures the valid first object then breaks on
    trailing garbage.  The valid object IS included in the result.

    Asymmetry with the leading-garbage case (test 7): trailing garbage is
    benign (first object captured before the break), but leading garbage is
    catastrophic (nothing captured because the break occurs before any object).
    """
    line = '{"type":"trajectory_mint","trajectory":"T3","slot":9}TRAILING_GARBAGE'
    result = _iter_json_objects(line)
    assert len(result) == 1
    assert result[0]["trajectory"] == "T3"
    assert result[0]["slot"] == 9


# ---------------------------------------------------------------------------
# Test 10 — extract_json_keys silently drops entries with string-typed slot
# ---------------------------------------------------------------------------


def test_extract_json_keys_drops_string_slot() -> None:
    """extract_json_keys requires slot to be an int (isinstance(slot, int)).
    A mint entry with slot encoded as a string is silently discarded; no
    warning or error is emitted.

    This is the low-level key-extraction function underlying the GAP in test 1.
    The string slot "5" is not coerced to int 5 — it is simply omitted.
    """
    mints = [
        {"trajectory": "T1", "slot": "5", "amount": 37},  # string slot — dropped
        {"trajectory": "T2", "slot": 6, "amount": 20},    # int slot — kept
    ]
    keys = extract_json_keys(mints)
    assert ("T1", "5") not in keys, "String '5' is not accepted as a valid slot"
    assert ("T1", 5) not in keys, "String '5' is not coerced to int 5"
    assert ("T2", 6) in keys, "Int-typed slot is correctly included"
    assert len(keys) == 1


# ---------------------------------------------------------------------------
# Test 11 — extract_json_keys silently drops entries with float-typed slot
# ---------------------------------------------------------------------------


def test_extract_json_keys_drops_float_slot() -> None:
    """extract_json_keys rejects float-typed slots because isinstance(5.0, int)
    is False in Python 3.  A mint entry serialized with a float slot is silently
    dropped with no warning.

    This is the low-level function underlying the GAP in test 2.  Note:
    booleans would pass (bool is a subclass of int in Python), but plain
    floats like 7.0 are rejected.
    """
    mints = [
        {"trajectory": "T2", "slot": 7.0, "amount": 20},  # float slot — dropped
        {"trajectory": "T3", "slot": 8, "amount": 25},    # int slot — kept
    ]
    keys = extract_json_keys(mints)
    assert ("T2", 7) not in keys, "Float 7.0 is not coerced to int 7"
    assert ("T3", 8) in keys
    assert len(keys) == 1


# ---------------------------------------------------------------------------
# Test 12 — extract_json_keys silently drops entries with missing trajectory
# ---------------------------------------------------------------------------


def test_extract_json_keys_drops_missing_trajectory() -> None:
    """extract_json_keys requires both trajectory (str) and slot (int).
    An entry missing the trajectory field is silently dropped; no error raised.

    If JSON contains a partially-written mint entry (trajectory omitted during
    a write failure), that entry is invisible to both the JSON→history and
    history→JSON checks.  The omission is never flagged.
    """
    mints = [
        {"slot": 5, "amount": 37},          # no trajectory field — dropped
        {"trajectory": "T1", "slot": 6},    # valid — kept
    ]
    keys = extract_json_keys(mints)
    assert len(keys) == 1
    assert ("T1", 6) in keys


# ---------------------------------------------------------------------------
# Test 13 — Duplicate (trajectory, slot) in JSON collapses via set
# ---------------------------------------------------------------------------


def test_duplicate_json_mint_collapses_to_single_key(tmp_path: Path) -> None:
    """extract_json_keys uses a Python set to accumulate (trajectory, slot) keys.
    If trajectory_mints.json has two entries with the same (trajectory, slot)
    but different amounts, the duplicate collapses silently.

    The checker sees one key on the JSON side matching one key on the history
    side → PASS.  The structural error in JSON (a duplicate mint entry, which
    could indicate a double-minting bug) is never flagged.

    Bypass mechanism: set deduplication in extract_json_keys discards the second
    entry with the same key; no duplicate detection or warning is provided.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON: two entries with same (T1, 5) key but different amounts
    (ledger / "trajectory_mints.json").write_text(
        json.dumps(
            {
                "mints": [
                    {"trajectory": "T1", "slot": 5, "amount": 37},
                    {"trajectory": "T1", "slot": 5, "amount": 99},  # duplicate key
                ]
            }
        ),
        encoding="utf-8",
    )

    # History: one entry for (T1, 5)
    (history / "cycle.jsonl").write_text(
        json.dumps(
            {"type": "trajectory_mint", "trajectory": "T1", "slot": 5, "amount": 37}
        ),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    assert result["status"] == "PASS", (
        "Duplicate mint entry in JSON collapses via set deduplication.  The "
        "double-minting at (T1, 5) is invisible — checker sees 1 key per side "
        "and returns PASS."
    )


# ---------------------------------------------------------------------------
# Test 14 — Type-case sensitivity: "Trajectory_Mint" not recognised → FAIL
# ---------------------------------------------------------------------------


def test_history_event_wrong_type_case_causes_fail(tmp_path: Path) -> None:
    """load_history_mints uses exact string equality: event.get("type") ==
    "trajectory_mint".  An event written with wrong capitalisation
    ("Trajectory_Mint", "TRAJECTORY_MINT") is NOT matched and is silently
    skipped — the type string is never normalised.

    When JSON has an entry for (T6, 15) but the history event uses the wrong
    case, history_keys is empty for that key → FAIL (missing_from_history).

    This is not a false-PASS GAP — the checker correctly reports FAIL.  It
    documents that type matching is case-sensitive and that no normalisation
    is applied to the event type field.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    history = ledger / "history"
    history.mkdir()

    # JSON has the entry
    (ledger / "trajectory_mints.json").write_text(
        json.dumps({"mints": [{"trajectory": "T6", "slot": 15, "amount": 38}]}),
        encoding="utf-8",
    )

    # History event uses capitalised type — will not match "trajectory_mint"
    (history / "cycle.jsonl").write_text(
        json.dumps(
            {"type": "Trajectory_Mint", "trajectory": "T6", "slot": 15, "amount": 38}
        ),
        encoding="utf-8",
    )

    result = run_check(tmp_path)

    # Expected FAIL: type mismatch causes history event to be dropped
    assert result["status"] == "FAIL"
    assert result["missing_from_history"] == [{"trajectory": "T6", "slot": 15}]
    assert result["missing_from_json"] == []


# ---------------------------------------------------------------------------
# Test 15 — load_history_mints skips events with None trajectory
# ---------------------------------------------------------------------------


def test_load_history_mints_skips_none_trajectory(tmp_path: Path) -> None:
    """load_history_mints checks isinstance(traj, str) before adding a key.
    An event where trajectory is null (JSON null → Python None) fails the
    isinstance check and is silently skipped.

    If a history file contains a trajectory_mint with trajectory=null (e.g.
    due to a serialization error) and JSON has no corresponding entry, both
    sets are empty → PASS.  The null-trajectory event is invisible to both
    directions of the check and generates no warning.
    """
    history = tmp_path / "ledger" / "history"
    history.mkdir(parents=True)

    # trajectory = null / None — fails isinstance(traj, str)
    (history / "cycle.jsonl").write_text(
        json.dumps(
            {"type": "trajectory_mint", "trajectory": None, "slot": 5, "amount": 20}
        ),
        encoding="utf-8",
    )

    keys = load_history_mints(history)

    assert len(keys) == 0, (
        "Event with trajectory=null is dropped by isinstance(traj, str); "
        "the None value is rejected without warning."
    )
