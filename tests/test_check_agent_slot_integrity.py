"""Tests for scripts/check_agent_slot_integrity.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_agent_slot_integrity import (
    AGENT0,
    _slot_as_int,
    check_agent0_exempt,
    check_slot_13_absent,
    check_slot_presence,
    check_slot_uniqueness,
    run_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agents(**kwargs: dict) -> dict[str, dict]:
    """Build an agents dict from keyword args: name -> record."""
    return kwargs


def _record(slot=None, **extra) -> dict:
    base: dict = {"balance": 100}
    if slot is not None:
        base["slot"] = slot
    base.update(extra)
    return base


def _make_balances(tmp_path: Path, agents: dict) -> Path:
    root = tmp_path
    (root / "ledger").mkdir(parents=True, exist_ok=True)
    (root / "ledger" / "balances.json").write_text(
        json.dumps({"version": 1, "agents": agents}), encoding="utf-8"
    )
    return root


# ---------------------------------------------------------------------------
# _slot_as_int unit tests
# ---------------------------------------------------------------------------


class TestSlotAsInt:
    def test_string_digit_valid(self):
        assert _slot_as_int("5") == 5

    def test_int_positive_valid(self):
        assert _slot_as_int(7) == 7

    def test_string_zero_invalid(self):
        assert _slot_as_int("0") is None

    def test_int_zero_invalid(self):
        assert _slot_as_int(0) is None

    def test_string_negative_invalid(self):
        assert _slot_as_int("-1") is None

    def test_int_negative_invalid(self):
        assert _slot_as_int(-5) is None

    def test_string_alpha_invalid(self):
        assert _slot_as_int("abc") is None

    def test_string_float_invalid(self):
        assert _slot_as_int("5.0") is None

    def test_none_invalid(self):
        assert _slot_as_int(None) is None

    def test_float_invalid(self):
        assert _slot_as_int(5.0) is None

    def test_bool_true_invalid(self):
        # bool is a subclass of int — must be explicitly rejected
        assert _slot_as_int(True) is None

    def test_bool_false_invalid(self):
        assert _slot_as_int(False) is None

    def test_string_large_valid(self):
        assert _slot_as_int("19") == 19


# ---------------------------------------------------------------------------
# check_slot_uniqueness
# ---------------------------------------------------------------------------


class TestCheckSlotUniqueness:
    def test_no_slots_passes(self):
        agents = _agents(
            **{AGENT0: _record(), "alice@x": _record()}
        )
        assert check_slot_uniqueness(agents) == []

    def test_all_unique_passes(self):
        agents = _agents(
            **{
                AGENT0: _record(),
                "alice@x": _record(slot="1"),
                "bob@x": _record(slot="2"),
                "carol@x": _record(slot="3"),
            }
        )
        assert check_slot_uniqueness(agents) == []

    def test_duplicate_slot_detected(self):
        agents = _agents(
            **{
                "alice@x": _record(slot="5"),
                "bob@x": _record(slot="5"),
            }
        )
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 1
        assert viols[0]["check"] == "uniqueness"
        assert viols[0]["slot"] == "5"
        assert set(viols[0]["agents"]) == {"alice@x", "bob@x"}

    def test_triple_duplicate_reported(self):
        agents = _agents(
            **{
                "a@x": _record(slot="7"),
                "b@x": _record(slot="7"),
                "c@x": _record(slot="7"),
            }
        )
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 1
        assert len(viols[0]["agents"]) == 3

    def test_two_separate_duplicates_both_reported(self):
        agents = _agents(
            **{
                "a@x": _record(slot="1"),
                "b@x": _record(slot="1"),
                "c@x": _record(slot="2"),
                "d@x": _record(slot="2"),
            }
        )
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 2
        slots = {v["slot"] for v in viols}
        assert slots == {"1", "2"}

    def test_agents_without_slot_ignored(self):
        agents = _agents(
            **{
                "alice@x": _record(slot="3"),
                "bob@x": _record(),  # no slot — must not conflict
            }
        )
        assert check_slot_uniqueness(agents) == []

    def test_int_and_string_same_slot_detected_as_duplicate(self):
        # slot 5 stored as int on one agent, string on another — same logical slot
        agents = _agents(
            **{
                "alice@x": _record(slot=5),
                "bob@x": _record(slot="5"),
            }
        )
        viols = check_slot_uniqueness(agents)
        assert len(viols) == 1
        assert viols[0]["slot"] == "5"
        assert set(viols[0]["agents"]) == {"alice@x", "bob@x"}

    def test_invalid_slots_excluded_from_uniqueness(self):
        # two agents with same invalid slot value: uniqueness ignores them
        agents = _agents(
            **{
                "alice@x": _record(slot="abc"),
                "bob@x": _record(slot="abc"),
            }
        )
        # uniqueness check skips invalid slots; check_slot_presence reports them
        assert check_slot_uniqueness(agents) == []


# ---------------------------------------------------------------------------
# check_slot_13_absent
# ---------------------------------------------------------------------------


class TestCheckSlot13Absent:
    def test_no_slot_13_passes(self):
        agents = _agents(
            **{"alice@x": _record(slot="12"), "bob@x": _record(slot="14")}
        )
        assert check_slot_13_absent(agents) == []

    def test_slot_13_string_detected(self):
        agents = _agents(**{"bad@x": _record(slot="13")})
        viols = check_slot_13_absent(agents)
        assert len(viols) == 1
        assert viols[0]["check"] == "slot_13_absent"
        assert "bad@x" in viols[0]["agents"]

    def test_slot_13_int_detected(self):
        agents = _agents(**{"bad@x": _record(slot=13)})
        viols = check_slot_13_absent(agents)
        assert len(viols) == 1
        assert "bad@x" in viols[0]["agents"]

    def test_no_agents_passes(self):
        assert check_slot_13_absent({}) == []

    def test_slot_3_not_confused_with_13(self):
        agents = _agents(**{"alice@x": _record(slot="3")})
        assert check_slot_13_absent(agents) == []


# ---------------------------------------------------------------------------
# check_agent0_exempt
# ---------------------------------------------------------------------------


class TestCheckAgent0Exempt:
    def test_agent0_without_slot_passes(self):
        agents = _agents(**{AGENT0: _record()})
        assert check_agent0_exempt(agents) == []

    def test_agent0_with_slot_fails(self):
        agents = _agents(**{AGENT0: _record(slot="0")})
        viols = check_agent0_exempt(agents)
        assert len(viols) == 1
        assert viols[0]["check"] == "agent0_has_slot"
        assert viols[0]["agent"] == AGENT0
        assert viols[0]["slot"] == "0"

    def test_agent0_absent_passes(self):
        # agent0 not present at all — no violation
        agents = _agents(**{"alice@x": _record(slot="1")})
        assert check_agent0_exempt(agents) == []

    def test_non_agent0_slot_not_flagged(self):
        agents = _agents(
            **{
                AGENT0: _record(),
                "alice@x": _record(slot="1"),
            }
        )
        assert check_agent0_exempt(agents) == []


# ---------------------------------------------------------------------------
# check_slot_presence
# ---------------------------------------------------------------------------


class TestCheckSlotPresence:
    def test_all_valid_passes(self):
        agents = _agents(
            **{
                AGENT0: _record(),
                "alice@x": _record(slot="1"),
                "bob@x": _record(slot="2"),
            }
        )
        assert check_slot_presence(agents) == []

    def test_missing_slot_detected(self):
        agents = _agents(
            **{
                AGENT0: _record(),
                "alice@x": _record(),  # no slot
            }
        )
        viols = check_slot_presence(agents)
        assert len(viols) == 1
        assert viols[0]["check"] == "missing_slot"
        assert viols[0]["agent"] == "alice@x"

    def test_slot_zero_invalid(self):
        agents = _agents(**{"alice@x": _record(slot="0")})
        viols = check_slot_presence(agents)
        assert any(v["check"] == "invalid_slot" and v["agent"] == "alice@x" for v in viols)

    def test_slot_negative_invalid(self):
        agents = _agents(**{"alice@x": _record(slot="-1")})
        viols = check_slot_presence(agents)
        assert any(v["check"] == "invalid_slot" for v in viols)

    def test_slot_alpha_string_invalid(self):
        agents = _agents(**{"alice@x": _record(slot="abc")})
        viols = check_slot_presence(agents)
        assert any(v["check"] == "invalid_slot" and v["value"] == "abc" for v in viols)

    def test_slot_float_string_invalid(self):
        agents = _agents(**{"alice@x": _record(slot="5.0")})
        viols = check_slot_presence(agents)
        assert any(v["check"] == "invalid_slot" for v in viols)

    def test_slot_bool_invalid(self):
        agents = _agents(**{"alice@x": _record(slot=True)})
        viols = check_slot_presence(agents)
        assert any(v["check"] == "invalid_slot" for v in viols)

    def test_slot_int_valid(self):
        agents = _agents(**{"alice@x": _record(slot=5)})
        assert check_slot_presence(agents) == []

    def test_slot_string_digits_valid(self):
        agents = _agents(**{"alice@x": _record(slot="19")})
        assert check_slot_presence(agents) == []

    def test_agent0_excluded_even_without_slot(self):
        agents = _agents(**{AGENT0: _record()})
        assert check_slot_presence(agents) == []

    def test_multiple_missing_slots_all_reported(self):
        agents = _agents(
            **{
                AGENT0: _record(),
                "a@x": _record(),
                "b@x": _record(),
                "c@x": _record(slot="3"),
            }
        )
        viols = check_slot_presence(agents)
        missing = [v for v in viols if v["check"] == "missing_slot"]
        assert len(missing) == 2
        agents_reported = {v["agent"] for v in missing}
        assert agents_reported == {"a@x", "b@x"}


# ---------------------------------------------------------------------------
# run_check integration
# ---------------------------------------------------------------------------


class TestRunCheck:
    def test_all_clean_passes(self, tmp_path: Path):
        agents = {
            AGENT0: _record(),
            "Alice-1@test": _record(slot="1"),
            "Bob-2@test": _record(slot="2"),
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "PASS"
        assert payload["violations"] == []
        assert "0 violation" in payload["summary"]

    def test_duplicate_slot_causes_fail(self, tmp_path: Path):
        agents = {
            AGENT0: _record(),
            "Alice-5@test": _record(slot="5"),
            "Bob-5@test": _record(slot="5"),
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        checks = [v["check"] for v in payload["violations"]]
        assert "uniqueness" in checks

    def test_slot_13_causes_fail(self, tmp_path: Path):
        agents = {
            AGENT0: _record(),
            "Cursed-13@test": _record(slot="13"),
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "slot_13_absent" for v in payload["violations"])

    def test_agent0_with_slot_causes_fail(self, tmp_path: Path):
        agents = {
            AGENT0: _record(slot="0"),
            "Alice-1@test": _record(slot="1"),
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "agent0_has_slot" for v in payload["violations"])

    def test_missing_slot_causes_fail(self, tmp_path: Path):
        agents = {
            AGENT0: _record(),
            "Alice-1@test": _record(),  # slot absent
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "missing_slot" for v in payload["violations"])

    def test_summary_reports_agent_count(self, tmp_path: Path):
        agents = {AGENT0: _record(), "Alice-1@test": _record(slot="1")}
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert "2 agent" in payload["summary"]

    def test_missing_file_returns_fail(self, tmp_path: Path):
        # no ledger directory — load will raise FileNotFoundError
        payload = run_check(tmp_path)
        assert payload["status"] == "FAIL"
        assert any(v["check"] == "load_error" for v in payload["violations"])

    def test_multiple_violation_types_all_reported(self, tmp_path: Path):
        agents = {
            AGENT0: _record(slot="99"),          # agent0 has slot
            "Alice-5@test": _record(slot="5"),
            "Bob-5@test": _record(slot="5"),      # duplicate
            "Carol-13@test": _record(slot="13"),  # slot 13
            "Dave@test": _record(),               # missing slot
        }
        root = _make_balances(tmp_path, agents)
        payload = run_check(root)
        assert payload["status"] == "FAIL"
        check_types = {v["check"] for v in payload["violations"]}
        assert "uniqueness" in check_types
        assert "slot_13_absent" in check_types
        assert "agent0_has_slot" in check_types
        assert "missing_slot" in check_types


# ---------------------------------------------------------------------------
# Real ledger: structural invariants that must always hold
# ---------------------------------------------------------------------------


class TestRealLedgerStructuralInvariants:
    """The three hard invariants must hold on the real ledger at all times."""

    @pytest.fixture(autouse=True)
    def _load(self):
        root = Path(__file__).parent.parent
        data = json.loads(
            (root / "ledger" / "balances.json").read_text(encoding="utf-8")
        )
        self.agents = data["agents"]

    def test_no_duplicate_slots(self):
        viols = check_slot_uniqueness(self.agents)
        assert viols == [], f"Duplicate slots found: {viols}"

    def test_slot_13_absent(self):
        viols = check_slot_13_absent(self.agents)
        assert viols == [], f"Slot 13 present: {viols}"

    def test_agent0_has_no_slot(self):
        viols = check_agent0_exempt(self.agents)
        assert viols == [], f"agent0@system has a slot field: {viols}"
