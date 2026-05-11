"""Tests for check_idem_keys_schema — idem_keys.json schema validation.

All tests operate on in-memory data; no real files are read.
"""

from __future__ import annotations

import pytest

from scripts.check_idem_keys_schema import run, _is_valid_created_at


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CREATED_AT = "2026-04-01T12:00:00Z"
VALID_OP = "payment"


def _entry(**kwargs) -> dict:
    """Build a minimal valid new-format entry, overridable via kwargs."""
    base = {"created_at": VALID_CREATED_AT, "op": VALID_OP}
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# Test 1: Valid single key with dict value — PASS
# ---------------------------------------------------------------------------

class TestValidSingleKey:
    def test_pass(self):
        data = {"idem_key_1": _entry()}
        result = run(data)
        assert result["status"] == "PASS"
        assert result["violations"] == []
        assert result["summary"] == "No violations"


# ---------------------------------------------------------------------------
# Test 2: null created_at — FAIL
# ---------------------------------------------------------------------------

class TestNullCreatedAt:
    def test_fail(self):
        data = {"k": _entry(created_at=None)}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(
            v["key"] == "k" and v["field"] == "created_at"
            for v in result["violations"]
        )


# ---------------------------------------------------------------------------
# Test 3: missing created_at — FAIL
# ---------------------------------------------------------------------------

class TestMissingCreatedAt:
    def test_fail(self):
        data = {"k": {"op": VALID_OP}}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(
            v["key"] == "k" and v["field"] == "created_at" and "missing" in v["issue"]
            for v in result["violations"]
        )


# ---------------------------------------------------------------------------
# Test 4: missing op — FAIL
# ---------------------------------------------------------------------------

class TestMissingOp:
    def test_fail(self):
        data = {"k": {"created_at": VALID_CREATED_AT}}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(
            v["key"] == "k" and v["field"] == "op" and "missing" in v["issue"]
            for v in result["violations"]
        )


# ---------------------------------------------------------------------------
# Test 5: op is empty string — FAIL
# ---------------------------------------------------------------------------

class TestOpEmptyString:
    def test_fail(self):
        data = {"k": _entry(op="")}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(v["key"] == "k" and v["field"] == "op" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 6: amount is negative integer — FAIL
# ---------------------------------------------------------------------------

class TestAmountNegative:
    def test_fail(self):
        data = {"k": _entry(amount=-5)}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(v["key"] == "k" and v["field"] == "amount" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 7: amount is a valid positive integer — PASS
# ---------------------------------------------------------------------------

class TestAmountPositive:
    def test_pass(self):
        data = {"k": _entry(amount=10)}
        result = run(data)
        assert result["status"] == "PASS"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 8: amount is 0 — FAIL
# ---------------------------------------------------------------------------

class TestAmountZero:
    def test_fail(self):
        data = {"k": _entry(amount=0)}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(v["key"] == "k" and v["field"] == "amount" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 9: top-level list (not dict) — FAIL
# ---------------------------------------------------------------------------

class TestTopLevelList:
    def test_fail(self):
        result = run([])
        assert result["status"] == "FAIL"
        assert any("top-level" in v["issue"] or "dict" in v["issue"] for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 10: empty dict — PASS (nothing to validate)
# ---------------------------------------------------------------------------

class TestEmptyDict:
    def test_pass(self):
        result = run({})
        assert result["status"] == "PASS"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 11: non-dict, non-string value for a key — FAIL
# ---------------------------------------------------------------------------

class TestNonDictValue:
    def test_fail(self):
        # An integer value is neither a valid dict nor an accepted legacy string.
        data = {"k": 42}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(v["key"] == "k" and v["field"] == "(value)" for v in result["violations"])

    def test_null_value_fails(self):
        data = {"k": None}
        result = run(data)
        assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 12: created_at with valid +05:00 offset — PASS
# ---------------------------------------------------------------------------

class TestCreatedAtPositiveOffset:
    def test_pass(self):
        data = {"k": _entry(created_at="2026-04-01T12:00:00+05:00")}
        result = run(data)
        assert result["status"] == "PASS"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------

class TestCreatedAtNegativeOffset:
    """created_at with -08:00 timezone offset is valid ISO-8601."""
    def test_pass(self):
        data = {"k": _entry(created_at="2026-04-01T12:00:00-08:00")}
        result = run(data)
        assert result["status"] == "PASS"


class TestCreatedAtBadFormat:
    """created_at with bare date string (no time) — FAIL."""
    def test_fail(self):
        data = {"k": _entry(created_at="2026-04-01")}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])


class TestAmountBoolFails:
    """amount=True is a bool, not an int — FAIL."""
    def test_fail(self):
        data = {"k": _entry(amount=True)}
        result = run(data)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "amount" for v in result["violations"])


class TestMultipleKeys:
    """Two valid keys — PASS."""
    def test_pass(self):
        data = {
            "payment|42|alice@test": _entry(op="payment", amount=10),
            "escrow|43|agent0@system": _entry(op="escrow"),
        }
        result = run(data)
        assert result["status"] == "PASS"


class TestLegacyStringValue:
    """Legacy string values (old format) are accepted — PASS."""
    def test_pass(self):
        data = {"escrow|42|agent0@system": "2026-04-01T12:00:00Z"}
        result = run(data)
        assert result["status"] == "PASS"
        assert result["violations"] == []


class TestLegacyEscrowMetadata:
    """Known escrow metadata dicts from older ledger eras are accepted."""

    def test_created_at_amount_without_op_passes_for_gauntlet_escrow_create(self):
        data = {
            "escrow_create_525_t1s16_gauntlet": {
                "amount": 35,
                "created_at": VALID_CREATED_AT,
            }
        }
        result = run(data)
        assert result["status"] == "PASS"
        assert result["violations"] == []

    def test_ts_without_created_at_passes_for_cycle_return(self):
        data = {
            "escrow-return-cycle22-789": {
                "ts": VALID_CREATED_AT,
                "op": "escrow_return",
                "issue": 789,
            }
        }
        result = run(data)
        assert result["status"] == "PASS"
        assert result["violations"] == []

    def test_true_sentinel_passes_for_known_escrow_create_key(self):
        result = run({"escrow_create|812": True})
        assert result["status"] == "PASS"
        assert result["violations"] == []

    def test_unknown_true_sentinel_still_fails(self):
        result = run({"payment|1|alice@test": True})
        assert result["status"] == "FAIL"
        assert any(v["key"] == "payment|1|alice@test" for v in result["violations"])


class TestIsValidCreatedAt:
    """Unit tests for the _is_valid_created_at helper."""

    def test_z_suffix(self):
        assert _is_valid_created_at("2026-04-01T00:00:00Z") is True

    def test_positive_offset(self):
        assert _is_valid_created_at("2026-04-01T00:00:00+05:30") is True

    def test_negative_offset(self):
        assert _is_valid_created_at("2026-04-01T00:00:00-05:00") is True

    def test_fractional_seconds_z(self):
        assert _is_valid_created_at("2026-04-01T00:00:00.123Z") is True

    def test_date_only_rejected(self):
        assert _is_valid_created_at("2026-04-01") is False

    def test_none_rejected(self):
        assert _is_valid_created_at(None) is False

    def test_no_offset_rejected(self):
        assert _is_valid_created_at("2026-04-01T00:00:00") is False
