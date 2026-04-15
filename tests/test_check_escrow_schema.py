"""Tests for check_escrow_schema — escrows.json schema validation."""

import pytest

from scripts.check_escrow_schema import run, _is_iso8601


KNOWN_AGENTS = {"agent0@system", "alice@test", "bob@test"}

BALANCES = {"agents": {a: {} for a in KNOWN_AGENTS}}


def _active(entry: dict, issue: str = "42") -> dict:
    return {"version": 1, "active": {issue: entry}}


# ---------------------------------------------------------------------------
# Test 1: Valid minimal escrow entry (pod type) → PASS
# ---------------------------------------------------------------------------
class TestValidMinimalPod:
    def test_pass(self):
        data = _active({
            "author": "alice@test",
            "amount": 10,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert result["status"] == "PASS"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 2: Missing `author` field → FAIL
# ---------------------------------------------------------------------------
class TestMissingAuthor:
    def test_fail(self):
        data = _active({
            "amount": 10,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "author" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 3: amount = 0 → FAIL
# ---------------------------------------------------------------------------
class TestAmountZero:
    def test_fail(self):
        data = _active({
            "author": "alice@test",
            "amount": 0,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "amount" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 4: amount negative → FAIL
# ---------------------------------------------------------------------------
class TestAmountNegative:
    def test_fail(self):
        data = _active({
            "author": "alice@test",
            "amount": -5,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "amount" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 5: Invalid `type` value → FAIL
# ---------------------------------------------------------------------------
class TestInvalidType:
    def test_fail(self):
        data = _active({
            "author": "alice@test",
            "amount": 10,
            "type": "standard",  # old value, not in new valid set
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "type" for v in result["violations"])

    def test_all_valid_types_pass(self):
        for t in ("pod", "progressive", "winner_take_all", "x_best", "duel", "linear"):
            data = _active({
                "author": "alice@test",
                "amount": 5,
                "type": t,
                "created_at": "2026-04-13T03:49:25Z",
            })
            result = run(data, BALANCES)
            assert result["status"] == "PASS", f"type '{t}' should be valid"


# ---------------------------------------------------------------------------
# Test 6: Malformed `created_at` → FAIL
# ---------------------------------------------------------------------------
class TestMalformedCreatedAt:
    def test_fail(self):
        data = _active({
            "author": "alice@test",
            "amount": 10,
            "type": "pod",
            "created_at": "not-a-date",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])

    def test_date_only_fails(self):
        # date without time is not ISO 8601 datetime
        data = _active({
            "author": "alice@test",
            "amount": 10,
            "type": "pod",
            "created_at": "2026-04-13",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 7: Valid progressive escrow with slots and paid_count → PASS
# ---------------------------------------------------------------------------
class TestValidProgressiveWithSlots:
    def test_pass(self):
        data = _active({
            "author": "alice@test",
            "amount": 8,
            "type": "progressive",
            "created_at": "2026-04-13T03:49:25Z",
            "slots": 3,
            "paid_count": 2,
        })
        result = run(data, BALANCES)
        assert result["status"] == "PASS"
        assert result["violations"] == []


# ---------------------------------------------------------------------------
# Test 8: paid_count > slots → FAIL
# ---------------------------------------------------------------------------
class TestPaidCountExceedsSlots:
    def test_fail(self):
        data = _active({
            "author": "alice@test",
            "amount": 8,
            "type": "progressive",
            "created_at": "2026-04-13T03:49:25Z",
            "slots": 3,
            "paid_count": 5,  # > slots
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "paid_count" for v in result["violations"])


# ---------------------------------------------------------------------------
# Additional: output structure always has required keys
# ---------------------------------------------------------------------------
class TestOutputStructure:
    def test_keys_present_on_pass(self):
        data = _active({
            "author": "alice@test",
            "amount": 10,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert {"status", "checks", "violations", "summary"} <= result.keys()

    def test_keys_present_on_fail(self):
        data = _active({"amount": 10, "type": "pod", "created_at": "2026-04-13T03:49:25Z"})
        result = run(data, BALANCES)
        assert {"status", "checks", "violations", "summary"} <= result.keys()


# ---------------------------------------------------------------------------
# Additional: author not in balances → FAIL
# ---------------------------------------------------------------------------
class TestAuthorNotInBalances:
    def test_unknown_author_fails(self):
        data = _active({
            "author": "ghost@nowhere",
            "amount": 10,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "author" for v in result["violations"])

    def test_no_balances_skips_author_check(self):
        # When balances unavailable, author check is skipped (known_agents empty)
        data = _active({
            "author": "ghost@nowhere",
            "amount": 10,
            "type": "pod",
            "created_at": "2026-04-13T03:49:25Z",
        })
        result = run(data, balances_data=None)
        assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# Additional: missing created_at → FAIL
# ---------------------------------------------------------------------------
class TestMissingCreatedAt:
    def test_fail(self):
        data = _active({
            "author": "alice@test",
            "amount": 10,
            "type": "pod",
        })
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])


# ---------------------------------------------------------------------------
# Additional: multiple entries — one good one bad
# ---------------------------------------------------------------------------
class TestMultipleEntries:
    def test_one_fail_makes_result_fail(self):
        data = {
            "version": 1,
            "active": {
                "10": {
                    "author": "alice@test",
                    "amount": 10,
                    "type": "pod",
                    "created_at": "2026-04-13T03:49:25Z",
                },
                "11": {
                    # missing author
                    "amount": 5,
                    "type": "linear",
                    "created_at": "2026-04-13T03:49:25Z",
                },
            },
        }
        result = run(data, BALANCES)
        assert result["status"] == "FAIL"
        assert len(result["checks"]) == 2
        statuses = {c["issue"]: c["status"] for c in result["checks"]}
        assert statuses["10"] == "PASS"
        assert statuses["11"] == "FAIL"


# ---------------------------------------------------------------------------
# Additional: top-level missing 'active' key
# ---------------------------------------------------------------------------
class TestMissingActiveKey:
    def test_fail(self):
        result = run({"version": 1}, BALANCES)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "active" for v in result["violations"])


# ---------------------------------------------------------------------------
# _is_iso8601 unit tests
# ---------------------------------------------------------------------------
class TestIsIso8601:
    def test_valid_z_suffix(self):
        assert _is_iso8601("2026-04-13T03:49:25Z") is True

    def test_valid_offset(self):
        assert _is_iso8601("2026-04-13T03:49:25+00:00") is True

    def test_invalid_date_string(self):
        assert _is_iso8601("not-a-date") is False

    def test_date_only(self):
        assert _is_iso8601("2026-04-13") is False

    def test_empty_string(self):
        assert _is_iso8601("") is False
