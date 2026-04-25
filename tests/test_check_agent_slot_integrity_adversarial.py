"""Adversarial tests for scripts/check_agent_slot_integrity.py.

Each scenario targets a specific bypass vector in slot registry validation.
Fixtures are minimal: only the agents needed to exercise the vector.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_agent_slot_integrity import (
    AGENT0,
    check_agent0_exempt,
    check_slot_13_absent,
    check_slot_presence,
    check_slot_uniqueness,
    run_check,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _record(slot=None, **extra) -> dict:
    base: dict = {"balance": 100}
    if slot is not None:
        base["slot"] = slot
    base.update(extra)
    return base


def _record_with_null_slot(**extra) -> dict:
    """Build a record that explicitly sets slot to None (JSON null)."""
    base: dict = {"balance": 100, "slot": None}
    base.update(extra)
    return base


def _make_balances(tmp_path: Path, agents: dict) -> Path:
    (tmp_path / "ledger").mkdir(parents=True, exist_ok=True)
    (tmp_path / "ledger" / "balances.json").write_text(
        json.dumps({"version": 1, "agents": agents}), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Scenario 1 — String-typed slot "7"
#
# Bypass vector: storing slot as string "7" instead of int 7 might bypass
# presence/validity checks if those only accept native ints.  The checker
# explicitly normalizes via _slot_as_int, so "7" must be treated as fully
# valid and must participate in uniqueness normalization as slot 7.
# ---------------------------------------------------------------------------


class TestStringTypedSlot:
    def test_string_slot_passes_presence_check(self):
        # "7" is a valid positive-integer string; must not raise invalid_slot
        agents = {"alice@x": _record(slot="7")}
        viols = check_slot_presence(agents)
        assert viols == [], f"String slot '7' should be valid; got: {viols}"

    def test_string_slot_normalizes_for_uniqueness(self):
        # slot "7" (string) and slot 7 (int) are the same logical slot;
        # they must be detected as a duplicate, not treated as two distinct slots
        agents = {
            "alice@x": _record(slot="7"),
            "bob@x": _record(slot=7),
        }
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 1
        assert viols[0]["slot"] == "7"
        assert set(viols[0]["agents"]) == {"alice@x", "bob@x"}

    def test_string_slot_participates_in_slot13_check(self, tmp_path: Path):
        # String "7" on a clean ledger must produce PASS (not false-flag slot 13)
        agents = {AGENT0: _record(), "alice@x": _record(slot="7")}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "PASS"


# ---------------------------------------------------------------------------
# Scenario 2 — Slot zero
#
# Bypass vector: slot value 0 is falsy in Python.  A naive `if slot:` guard
# would silently skip zero, treating it as "no slot" rather than "invalid slot".
# The checker uses explicit `value > 0`, so zero must be flagged as invalid_slot
# — not silently dropped as missing_slot.
# ---------------------------------------------------------------------------


class TestSlotZero:
    def test_int_zero_reported_as_invalid_not_missing(self):
        # zero must produce invalid_slot, not missing_slot (it is present but illegal)
        agents = {"alice@x": _record(slot=0)}
        viols = check_slot_presence(agents)
        checks = [v["check"] for v in viols]
        assert "invalid_slot" in checks, f"Expected invalid_slot; got: {checks}"
        assert "missing_slot" not in checks

    def test_string_zero_reported_as_invalid(self):
        # "0" must also be caught — not confused with "absent key"
        agents = {"alice@x": _record(slot="0")}
        viols = check_slot_presence(agents)
        checks = [v["check"] for v in viols]
        assert "invalid_slot" in checks

    def test_zero_excluded_from_uniqueness(self):
        # invalid slot 0 must not participate in uniqueness counting;
        # two agents both carrying slot 0 should not generate a uniqueness error
        # (slot_presence will catch them individually instead)
        agents = {
            "alice@x": _record(slot=0),
            "bob@x": _record(slot=0),
        }
        assert check_slot_uniqueness(agents) == []

    def test_run_check_slot_zero_fails(self, tmp_path: Path):
        agents = {AGENT0: _record(), "alice@x": _record(slot=0)}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "invalid_slot" for v in payload["violations"])


# ---------------------------------------------------------------------------
# Scenario 3 — Float slot 7.0
#
# Bypass vector: in Python, `7.0 == 7` is True and `isinstance(7.0, int)` is
# False (float is not a subclass of int).  A checker that uses `== 13` for the
# vacant-slot test or normalizes floats to int might let 7.0 silently pass as
# slot 7, or let 13.0 bypass the slot-13 prohibition.  The checker's
# _slot_as_int explicitly rejects non-int/non-str types, so floats must be
# flagged as invalid_slot.
# ---------------------------------------------------------------------------


class TestFloatSlot:
    def test_float_slot_reported_as_invalid(self):
        agents = {"alice@x": _record(slot=7.0)}
        viols = check_slot_presence(agents)
        checks = [v["check"] for v in viols]
        assert "invalid_slot" in checks, f"Float 7.0 must be invalid; got: {checks}"

    def test_float_13_does_not_bypass_vacant_slot_check(self):
        # 13.0 == VACANT_SLOT is True numerically; confirm it does NOT slip
        # through check_slot_13_absent (because _slot_as_int rejects floats)
        agents = {"alice@x": _record(slot=13.0)}
        viols = check_slot_13_absent(agents)
        # float 13.0 is invalid → _slot_as_int returns None → not == VACANT_SLOT
        # slot_13_absent will NOT catch it; slot_presence catches it instead
        assert viols == [], (
            "float 13.0 bypasses slot_13_absent (caught by slot_presence instead)"
        )
        presence_viols = check_slot_presence(agents)
        assert any(v["check"] == "invalid_slot" for v in presence_viols)

    def test_float_excluded_from_uniqueness(self):
        # float slot must not participate in uniqueness — otherwise 7.0 and 7
        # would generate a spurious duplicate report
        agents = {
            "alice@x": _record(slot=7.0),
            "bob@x": _record(slot=7),
        }
        uniqueness_viols = check_slot_uniqueness(agents)
        # uniqueness ignores invalid float; bob gets valid slot 7
        assert uniqueness_viols == []
        # but presence must flag alice's float slot
        presence_viols = check_slot_presence(agents)
        assert any(
            v["check"] == "invalid_slot" and v["agent"] == "alice@x"
            for v in presence_viols
        )

    def test_run_check_float_slot_fails(self, tmp_path: Path):
        agents = {AGENT0: _record(), "alice@x": _record(slot=7.0)}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "invalid_slot" for v in payload["violations"])

    def test_float_13_caught_as_invalid_slot_in_full_check(self, tmp_path: Path):
        # float 13.0 bypasses check_slot_13_absent (caught as invalid_slot instead);
        # ensure the full run_check still returns FAIL and does NOT produce a
        # slot_13_absent violation (which would change semantics if float handling
        # is ever widened)
        agents = {AGENT0: _record(), "alice@x": _record(slot=13.0)}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        checks = {v["check"] for v in payload["violations"]}
        assert "invalid_slot" in checks
        assert "slot_13_absent" not in checks


# ---------------------------------------------------------------------------
# Scenario 4 — Slot 13 via string "13"
#
# Bypass vector: the vacant-slot prohibition is `_slot_as_int(value) == 13`.
# If _slot_as_int did NOT normalize strings, slot "13" would fail the integer
# comparison and pass silently.  Confirm string "13" is caught.
# ---------------------------------------------------------------------------


class TestSlot13ViaString:
    def test_string_13_caught_by_slot13_check(self):
        # "13" normalizes to int 13 == VACANT_SLOT → violation
        agents = {"cursed@x": _record(slot="13")}
        viols = check_slot_13_absent(agents)
        assert len(viols) == 1
        assert viols[0]["check"] == "slot_13_absent"
        assert "cursed@x" in viols[0]["agents"]

    def test_int_and_string_13_both_caught(self):
        # belt-and-suspenders: both forms must appear in the same violation
        agents = {
            "cursed-a@x": _record(slot="13"),
            "cursed-b@x": _record(slot=13),
        }
        viols = check_slot_13_absent(agents)
        assert len(viols) == 1
        holders = set(viols[0]["agents"])
        assert "cursed-a@x" in holders
        assert "cursed-b@x" in holders

    def test_run_check_string_13_fails(self, tmp_path: Path):
        agents = {AGENT0: _record(), "cursed@x": _record(slot="13")}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "slot_13_absent" for v in payload["violations"])


# ---------------------------------------------------------------------------
# Scenario 5 — agent0 with null slot
#
# Bypass vector: `slot: null` (JSON) becomes `{"slot": None}` in Python.
# A naive `if record.get("slot")` guard treats None as falsy and misses the
# key.  The checker uses `"slot" in record`, which is True even when the value
# is None — so null slot must be flagged as agent0_has_slot.
#
# Contrast: an agent0 record with NO "slot" key at all must NOT be flagged.
# ---------------------------------------------------------------------------


class TestAgent0NullSlot:
    def test_null_slot_triggers_agent0_has_slot_violation(self):
        # key present with None value → "slot" in record is True → violation
        agents = {AGENT0: _record_with_null_slot()}
        viols = check_agent0_exempt(agents)
        assert len(viols) == 1
        assert viols[0]["check"] == "agent0_has_slot"
        assert viols[0]["agent"] == AGENT0
        assert viols[0]["slot"] is None

    def test_absent_slot_key_does_not_trigger_violation(self):
        # key completely absent → "slot" in record is False → no violation
        agents = {AGENT0: {"balance": 100}}
        viols = check_agent0_exempt(agents)
        assert viols == []

    def test_null_slot_not_counted_in_slot_presence_for_agent0(self):
        # agent0 is skipped by check_slot_presence regardless of slot value
        agents = {AGENT0: _record_with_null_slot()}
        viols = check_slot_presence(agents)
        assert viols == []

    def test_run_check_agent0_null_slot_fails(self, tmp_path: Path):
        agents = {AGENT0: _record_with_null_slot(), "alice@x": _record(slot="1")}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "agent0_has_slot" for v in payload["violations"])


# ---------------------------------------------------------------------------
# Scenario 6 — Duplicate slots across types (int 7 vs string "7")
#
# Bypass vector: if uniqueness were checked with raw value equality rather than
# normalized integer keys, `7 != "7"` in Python would hide the collision.
# The checker normalizes both through _slot_as_int → str(int) keying, so the
# collision must be detected regardless of storage type.
# ---------------------------------------------------------------------------


class TestDuplicateSlotsAcrossTypes:
    def test_int_and_string_same_slot_is_duplicate(self):
        # int 7 and string "7" normalize to the same key "7" → uniqueness violation
        agents = {
            "alice@x": _record(slot=7),
            "bob@x": _record(slot="7"),
        }
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 1, f"Expected exactly 1 uniqueness violation; got: {viols}"
        assert viols[0]["check"] == "uniqueness"
        assert viols[0]["slot"] == "7"
        assert set(viols[0]["agents"]) == {"alice@x", "bob@x"}

    def test_cross_type_duplicate_reported_once_not_twice(self):
        # must not generate two separate violations (one for int, one for string)
        agents = {
            "alice@x": _record(slot=7),
            "bob@x": _record(slot="7"),
        }
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 1

    def test_distinct_slots_different_types_no_false_duplicate(self):
        # int 7 vs string "8" must NOT trigger a duplicate — different slots
        agents = {
            "alice@x": _record(slot=7),
            "bob@x": _record(slot="8"),
        }
        assert check_slot_uniqueness(agents) == []

    def test_run_check_cross_type_duplicate_fails(self, tmp_path: Path):
        agents = {
            AGENT0: _record(),
            "alice@x": _record(slot=7),
            "bob@x": _record(slot="7"),
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "uniqueness" for v in payload["violations"])
