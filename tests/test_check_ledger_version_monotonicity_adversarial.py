"""Adversarial tests for scripts/check_ledger_version_monotonicity.py.

Each scenario targets a specific bypass vector in the version monotonicity
validation logic.  Fixtures are minimal: only the state needed to exercise
the vector.  Genuine bypasses are marked with [BYPASS] and include a severity
rating.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_ledger_version_monotonicity as checker  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_ledger_files(
    root: Path,
    *,
    balances_version: Any = 100,
    escrows_version: Any = 100,
    idem_keys_version: Any = 100,
) -> None:
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    for filename, version in (
        ("balances.json", balances_version),
        ("escrows.json", escrows_version),
        ("idem_keys.json", idem_keys_version),
    ):
        (ledger / filename).write_text(
            json.dumps({"agents": {}, "version": version}), encoding="utf-8"
        )


def _write_history_lines(root: Path, lines: list[str | dict], filename: str = "events.jsonl") -> None:
    """Write raw lines or dicts to a history .jsonl file."""
    history = root / "ledger" / "history"
    history.mkdir(parents=True, exist_ok=True)
    parts = []
    for line in lines:
        if isinstance(line, dict):
            parts.append(json.dumps(line))
        else:
            parts.append(line)
    (history / filename).write_text("\n".join(parts) + "\n", encoding="utf-8")


def _payment(n: int = 1) -> list[dict]:
    return [{"type": "payment", "amount": 5, "agent": "agent0@system"} for _ in range(n)]


def _escrow_create(n: int = 1) -> list[dict]:
    return [{"type": "escrow_create", "amount": 10, "issue": 1} for _ in range(n)]


def _escrow_return(n: int = 1) -> list[dict]:
    return [{"type": "escrow_return", "amount": 10, "issue": 1} for _ in range(n)]


def _registration(n: int = 1) -> list[dict]:
    return [{"type": "registration", "agent": f"Claude-{i}@claude"} for i in range(n)]


# ---------------------------------------------------------------------------
# Scenario 1 — Float version
#
# Bypass vector: JSON permits 142.0 as a valid number.  Python's json.loads
# produces float(142.0), not int(142).  A naive `version >= event_count`
# comparison would pass because 142.0 >= 5 is True in Python.  The spec
# requires version to be a positive INTEGER.  _is_positive_int guards this
# with isinstance(value, int), so float values must FAIL.
#
# Verdict: NOT a bypass — checker correctly rejects float versions.
# ---------------------------------------------------------------------------


class TestFloatVersion:
    def test_float_version_fails(self, tmp_path: Path) -> None:
        # version=142.0 satisfies >= event_count numerically but is not an int
        _write_ledger_files(tmp_path, balances_version=142.0, escrows_version=142, idem_keys_version=142)
        _write_history_lines(tmp_path, _payment(5))

        report, passed = checker.check(tmp_path)

        assert not passed, "Float version must FAIL (not a positive integer)"
        violated = [v for v in report["violations"] if "balances" in v["file"]]
        assert violated, "balances.json must appear in violations"
        assert "positive integer" in violated[0]["reason"]

    def test_float_version_large_still_fails(self, tmp_path: Path) -> None:
        # even when float >> event_count, the type check must reject it
        _write_ledger_files(tmp_path, balances_version=9999.0)
        _write_history_lines(tmp_path, _payment(1))

        _, passed = checker.check(tmp_path)

        assert not passed, "9999.0 float must FAIL regardless of magnitude"

    def test_int_version_passes_to_confirm_comparison_is_real(self, tmp_path: Path) -> None:
        # confirms float FAIL is due to type, not magnitude — equivalent int must PASS
        _write_ledger_files(tmp_path, balances_version=142, escrows_version=142, idem_keys_version=142)
        _write_history_lines(tmp_path, _payment(5))

        _, passed = checker.check(tmp_path)

        assert passed, "Equivalent integer version must PASS"

    def test_bool_version_fails(self, tmp_path: Path) -> None:
        # bool is a subclass of int in Python; True == 1, False == 0
        # the checker explicitly excludes bool via `not isinstance(value, bool)`
        _write_ledger_files(tmp_path, balances_version=True)
        _write_history_lines(tmp_path, _payment(1))

        _, passed = checker.check(tmp_path)

        assert not passed, "Boolean True must FAIL (bool is excluded despite being int subclass)"


# ---------------------------------------------------------------------------
# Scenario 2 — Version is a string
#
# Bypass vector: JSON permits "142" as a string.  Python string comparison
# with an integer would raise TypeError or produce an unexpected result.
# A checker that uses `int(version_val) >= count` would silently coerce the
# string, letting it pass even though the spec mandates an integer type.
# The guard `isinstance(value, int)` catches this: str is not int → FAIL.
#
# Verdict: NOT a bypass — checker correctly rejects string versions.
# ---------------------------------------------------------------------------


class TestStringVersion:
    def test_string_version_fails(self, tmp_path: Path) -> None:
        # "142" is a valid integer string but not an integer type
        _write_ledger_files(tmp_path, balances_version="142")
        _write_history_lines(tmp_path, _payment(5))

        report, passed = checker.check(tmp_path)

        assert not passed, "String version must FAIL"
        violated = [v for v in report["violations"] if "balances" in v["file"]]
        assert violated
        assert "positive integer" in violated[0]["reason"]

    def test_string_zero_fails(self, tmp_path: Path) -> None:
        # "0" would pass a coercion check but fail the positive-integer type check
        _write_ledger_files(tmp_path, balances_version="0")
        _write_history_lines(tmp_path, _payment(1))

        _, passed = checker.check(tmp_path)

        assert not passed, '"0" string version must FAIL'

    def test_numeric_string_all_files_fail(self, tmp_path: Path) -> None:
        # all three files with string versions must all fail
        _write_ledger_files(tmp_path, balances_version="50", escrows_version="50", idem_keys_version="50")
        (tmp_path / "ledger" / "history").mkdir(parents=True, exist_ok=True)

        report, passed = checker.check(tmp_path)

        assert not passed
        assert len(report["violations"]) == 3, "All three files must violate"

    def test_integer_version_passes_to_confirm_type_check_is_real(self, tmp_path: Path) -> None:
        # confirms string FAIL is due to type, not value — equivalent int must PASS
        _write_ledger_files(tmp_path, balances_version=142, escrows_version=50, idem_keys_version=50)
        _write_history_lines(tmp_path, _payment(5))

        _, passed = checker.check(tmp_path)

        assert passed, "Integer version 142 with 5 events must PASS"


# ---------------------------------------------------------------------------
# Scenario 3 — Corrupt history line reduces event count
#
# [BYPASS] Severity: MEDIUM
#
# Bypass vector: count_write_events silently skips lines that fail
# json.loads.  If a write-type event is embedded inside a malformed JSON
# line (e.g., the line has extra surrounding garbage), the event is skipped
# and the effective count is lower than the true count.  A version that
# matches the deflated count passes even though the ledger's true history
# implies a higher version is required.
#
# Example: 3 payment events exist logically, but one line is corrupt.
# Checker counts 2.  version=2 passes.  version=2 should arguably require
# at least 3 writes, but the checker cannot infer this.
#
# Mitigation: this bypass requires an attacker to intentionally corrupt
# history lines — not a realistic accident in the git-native ledger.
# ---------------------------------------------------------------------------


class TestCorruptHistoryReducesEventCount:
    def test_corrupt_line_with_embedded_event_passes_with_deflated_version(
        self, tmp_path: Path
    ) -> None:
        # [BYPASS] 2 valid payment events + 1 corrupt line containing "payment" keyword
        # effective count = 2; version=2 passes despite a "missing" write event
        _write_ledger_files(tmp_path, balances_version=2, escrows_version=100, idem_keys_version=100)
        _write_history_lines(
            tmp_path,
            [
                {"type": "payment", "amount": 5},          # valid, counted
                {"type": "payment", "amount": 5},          # valid, counted
                'CORRUPT{"type":"payment","amount":5}END',  # malformed JSON, skipped
            ],
        )

        report, passed = checker.check(tmp_path)

        # [BYPASS] version=2 passes because corrupt line is skipped (count=2, not 3)
        assert passed, (
            "[BYPASS DOCUMENTED] Corrupt line hides a write event; "
            "version=2 passes even though logically 3 writes occurred"
        )

    def test_valid_line_after_corrupt_line_is_still_counted(self, tmp_path: Path) -> None:
        # corrupt lines must not stop processing of subsequent valid lines
        _write_ledger_files(tmp_path, balances_version=1, escrows_version=100, idem_keys_version=100)
        _write_history_lines(
            tmp_path,
            [
                "NOT VALID JSON AT ALL",
                {"type": "payment", "amount": 5},  # valid, must be counted
                "ALSO BAD <<<",
                {"type": "payment", "amount": 5},  # valid, must be counted
            ],
        )

        report, passed = checker.check(tmp_path)

        # version=1 < 2 valid payment events → must FAIL
        assert not passed, "2 valid payment events must be counted despite surrounding corrupt lines"
        violated = [v for v in report["violations"] if "balances" in v["file"]]
        assert violated
        assert violated[0]["write_event_count"] == 2

    def test_all_corrupt_lines_produce_zero_count(self, tmp_path: Path) -> None:
        # entirely corrupt history → count=0 → any positive version passes
        _write_ledger_files(tmp_path, balances_version=1, escrows_version=1, idem_keys_version=1)
        _write_history_lines(
            tmp_path,
            ["{bad", "NOT-JSON", "}{broken}{", "also:bad:yaml"],
        )

        _, passed = checker.check(tmp_path)

        assert passed, "Entirely corrupt history produces count=0; version=1 must PASS"

    def test_single_corrupt_among_valid_does_not_affect_real_count(self, tmp_path: Path) -> None:
        # confirms that only parseable lines are counted — one corrupt does not poison the rest
        _write_ledger_files(tmp_path, balances_version=3, escrows_version=100, idem_keys_version=100)
        _write_history_lines(
            tmp_path,
            [
                {"type": "payment", "amount": 5},
                "{broken json line",
                {"type": "payment", "amount": 5},
                {"type": "payment", "amount": 5},
            ],
        )

        _, passed = checker.check(tmp_path)

        assert passed, "3 valid payment events with version=3 must PASS (corrupt line ignored)"


# ---------------------------------------------------------------------------
# Scenario 4 — Version exactly equals event count (boundary check)
#
# The spec says version >= count.  At the boundary (version == count), the
# check must PASS.  An off-by-one error (using > instead of >=) would
# produce a false FAIL when version exactly matches the event count.
#
# Verdict: NOT a bypass — tests the boundary to confirm no off-by-one error.
# ---------------------------------------------------------------------------


class TestVersionExactlyEqualsCount:
    def test_version_equals_payment_count_passes(self, tmp_path: Path) -> None:
        # 7 payment events, version=7 — boundary must PASS
        _write_ledger_files(tmp_path, balances_version=7, escrows_version=100, idem_keys_version=100)
        _write_history_lines(tmp_path, _payment(7))

        _, passed = checker.check(tmp_path)

        assert passed, "version == event_count must PASS (>= not >)"

    def test_version_equals_escrow_create_count_passes(self, tmp_path: Path) -> None:
        # 4 escrow_create events, version=4 for escrows.json
        _write_ledger_files(tmp_path, balances_version=100, escrows_version=4, idem_keys_version=100)
        _write_history_lines(tmp_path, _escrow_create(4))

        _, passed = checker.check(tmp_path)

        assert passed, "escrows.json: version == escrow_create count must PASS"

    def test_version_equals_mixed_count_for_balances_passes(self, tmp_path: Path) -> None:
        # balances.json counts payment + accept + registration
        # 3 payment + 2 registration = 5; version=5 must PASS
        _write_ledger_files(tmp_path, balances_version=5, escrows_version=100, idem_keys_version=2)
        _write_history_lines(tmp_path, _payment(3) + _registration(2))

        _, passed = checker.check(tmp_path)

        assert passed, "balances: version == (payment + registration) count must PASS"

    def test_version_one_below_count_fails_to_confirm_boundary(self, tmp_path: Path) -> None:
        # belt-and-suspenders: version=6 with 7 events must FAIL
        _write_ledger_files(tmp_path, balances_version=6, escrows_version=100, idem_keys_version=100)
        _write_history_lines(tmp_path, _payment(7))

        _, passed = checker.check(tmp_path)

        assert not passed, "version == count - 1 must FAIL (confirms boundary test is not trivially green)"


# ---------------------------------------------------------------------------
# Scenario 5 — Version = count - 1 (regression detection)
#
# Core regression case: version is exactly one less than the write-event
# count.  This directly tests the primary purpose of the checker — catching
# silent rollbacks or manual version regressions where the version was
# decremented or not bumped after a write.
#
# Verdict: NOT a bypass — confirms correct rejection of a regressed version.
# ---------------------------------------------------------------------------


class TestVersionOneBelowCount:
    def test_balances_version_one_below_fails(self, tmp_path: Path) -> None:
        # 10 payment events, version=9 (one below) → must FAIL
        _write_ledger_files(tmp_path, balances_version=9, escrows_version=100, idem_keys_version=100)
        _write_history_lines(tmp_path, _payment(10))

        report, passed = checker.check(tmp_path)

        assert not passed
        violated = [v for v in report["violations"] if "balances" in v["file"]]
        assert violated
        assert violated[0]["version"] == 9
        assert violated[0]["write_event_count"] == 10
        assert "regression" in violated[0]["reason"]

    def test_escrows_version_one_below_fails(self, tmp_path: Path) -> None:
        # 6 escrow_create events, version=5 → must FAIL
        _write_ledger_files(tmp_path, balances_version=100, escrows_version=5, idem_keys_version=100)
        _write_history_lines(tmp_path, _escrow_create(6))

        report, passed = checker.check(tmp_path)

        assert not passed
        violated = [v for v in report["violations"] if "escrows" in v["file"]]
        assert violated
        assert violated[0]["write_event_count"] == 6

    def test_idem_keys_version_one_below_fails(self, tmp_path: Path) -> None:
        # 3 registration events, version=2 → must FAIL (registration counts for idem_keys)
        _write_ledger_files(tmp_path, balances_version=100, escrows_version=100, idem_keys_version=2)
        _write_history_lines(tmp_path, _registration(3))

        report, passed = checker.check(tmp_path)

        assert not passed
        violated = [v for v in report["violations"] if "idem_keys" in v["file"]]
        assert violated
        assert violated[0]["write_event_count"] == 3

    def test_correct_version_passes_to_confirm_not_trivially_green(self, tmp_path: Path) -> None:
        # version exactly at count must PASS — confirms the FAIL above is real
        _write_ledger_files(tmp_path, balances_version=10, escrows_version=100, idem_keys_version=100)
        _write_history_lines(tmp_path, _payment(10))

        _, passed = checker.check(tmp_path)

        assert passed, "version == count must PASS (confirms regression test is not trivially green)"


# ---------------------------------------------------------------------------
# Scenario 6 — escrow_return excluded from all file counts
#
# The spec explicitly excludes escrow_return from all file event counts.
# This is because escrow_return removes an entry from escrows.json and
# credits balances.json, but there are more return events than version bumps
# per file — including them would cause false-positive failures on healthy
# ledgers.
#
# Bypass vector (false-positive direction): if escrow_return were counted
# for escrows.json or balances.json, a healthy ledger with many returns
# would appear to have more write events than the version, triggering a
# spurious regression failure.
#
# Verdict: NOT a bypass — tests that the exclusion prevents false positives.
# ---------------------------------------------------------------------------


class TestEscrowReturnExcluded:
    def test_escrow_return_not_counted_for_escrows(self, tmp_path: Path) -> None:
        # 5 escrow_create + 10 escrow_return; escrows.version=5
        # if escrow_return were counted: count=15 > 5 → false FAIL
        # correct behavior: count=5 (create only), version=5 → PASS
        _write_ledger_files(tmp_path, balances_version=100, escrows_version=5, idem_keys_version=100)
        _write_history_lines(tmp_path, _escrow_create(5) + _escrow_return(10))

        _, passed = checker.check(tmp_path)

        assert passed, (
            "escrow_return must not be counted for escrows.json; "
            "10 returns + 5 creates with version=5 must PASS"
        )

    def test_escrow_return_not_counted_for_balances(self, tmp_path: Path) -> None:
        # 3 payment events + 10 escrow_return; balances.version=3
        # if escrow_return were counted for balances: count=13 > 3 → false FAIL
        # correct: count=3 (payment only), version=3 → PASS
        _write_ledger_files(tmp_path, balances_version=3, escrows_version=100, idem_keys_version=100)
        _write_history_lines(tmp_path, _payment(3) + _escrow_return(10))

        _, passed = checker.check(tmp_path)

        assert passed, (
            "escrow_return must not be counted for balances.json; "
            "10 returns + 3 payments with version=3 must PASS"
        )

    def test_escrow_create_still_counted_despite_returns(self, tmp_path: Path) -> None:
        # confirms escrow_return exclusion doesn't accidentally drop escrow_create too
        _write_ledger_files(tmp_path, balances_version=100, escrows_version=2, idem_keys_version=100)
        _write_history_lines(tmp_path, _escrow_create(5) + _escrow_return(20))

        report, passed = checker.check(tmp_path)

        # escrow_create count=5, version=2 < 5 → must FAIL
        assert not passed, "escrow_create must still be counted; version=2 with 5 creates must FAIL"
        violated = [v for v in report["violations"] if "escrows" in v["file"]]
        assert violated
        assert violated[0]["write_event_count"] == 5

    def test_report_shows_zero_count_for_return_only_history(self, tmp_path: Path) -> None:
        # history with only escrow_return events → escrows event_count = 0
        _write_ledger_files(tmp_path, balances_version=1, escrows_version=1, idem_keys_version=1)
        _write_history_lines(tmp_path, _escrow_return(50))

        report, _ = checker.check(tmp_path)

        counts = {entry["file"]: entry["write_event_count"] for entry in report["files"]}
        assert counts["ledger/escrows.json"] == 0, (
            "50 escrow_return events must produce count=0 for escrows.json"
        )
        assert counts["ledger/balances.json"] == 0, (
            "50 escrow_return events must produce count=0 for balances.json"
        )
