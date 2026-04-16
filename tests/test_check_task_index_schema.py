"""Tests for check_task_index_schema — task_index.json schema validation.

All tests operate on in-memory data; no real files are read.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from scripts.check_task_index_schema import run, _is_iso8601_datetime, _is_iso8601_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CREATED_AT = "2026-04-01T12:00:00Z"


def _entry(**kwargs) -> dict:
    """Build a minimal valid new-format task entry, overridable via kwargs."""
    base = {
        "reward_wea": 30,
        "reward_type": "pod",
        "status": "open",
        "created_at": VALID_CREATED_AT,
        "accepted_agents": [],
        "min_agents": 1,
    }
    base.update(kwargs)
    return base


def _tasks(**kwargs) -> dict:
    """Wrap entries into a tasks dict keyed by issue number strings."""
    return kwargs


# ---------------------------------------------------------------------------
# Test 1: Fully valid new-format entry — PASS
# ---------------------------------------------------------------------------

class TestFullyValidEntry:
    def test_pass(self):
        tasks = _tasks(**{"42": _entry()})
        result = run(tasks)
        assert result["status"] == "PASS"
        assert result["violations"] == []
        assert result["summary"] == "No violations"


# ---------------------------------------------------------------------------
# Test 2: Missing required field — FAIL
# ---------------------------------------------------------------------------

class TestMissingRequiredField:
    def test_missing_status_fails(self):
        # Remove status from a new-format entry (reward_wea present → strict mode)
        entry = _entry()
        del entry["status"]
        tasks = _tasks(**{"10": entry})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "status" for v in result["violations"])

    def test_missing_created_at_fails(self):
        entry = _entry()
        del entry["created_at"]
        tasks = _tasks(**{"11": entry})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(
            v["issue"] == "11" and v["field"] == "created_at" and "missing" in v["issue_detail"]
            for v in result["violations"]
        )


# ---------------------------------------------------------------------------
# Test 3: Wrong type for reward_wea — FAIL
# ---------------------------------------------------------------------------

class TestRewardWeaWrongType:
    def test_string_fails(self):
        tasks = _tasks(**{"20": _entry(reward_wea="30")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "reward_wea" for v in result["violations"])

    def test_float_fails(self):
        tasks = _tasks(**{"21": _entry(reward_wea=30.5)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "reward_wea" for v in result["violations"])

    def test_bool_fails(self):
        # bool is a subclass of int in Python; must be explicitly rejected
        tasks = _tasks(**{"22": _entry(reward_wea=True)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "reward_wea" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 4: Invalid reward_type enum — FAIL
# ---------------------------------------------------------------------------

class TestInvalidRewardTypeEnum:
    def test_unknown_type_fails(self):
        tasks = _tasks(**{"30": _entry(reward_type="bounty")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(
            v["issue"] == "30" and v["field"] == "reward_type"
            for v in result["violations"]
        )

    def test_valid_types_pass(self):
        for rt in ("pod", "progressive", "wta", "best", "duel", "linear"):
            tasks = _tasks(**{"31": _entry(reward_type=rt)})
            result = run(tasks)
            assert result["status"] == "PASS", f"Expected PASS for reward_type={rt}"


# ---------------------------------------------------------------------------
# Test 5: Invalid status enum — FAIL
# ---------------------------------------------------------------------------

class TestInvalidStatusEnum:
    def test_cancelled_fails(self):
        tasks = _tasks(**{"40": _entry(status="cancelled")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(
            v["issue"] == "40" and v["field"] == "status"
            for v in result["violations"]
        )

    def test_deleted_fails(self):
        tasks = _tasks(**{"41": _entry(status="deleted")})
        result = run(tasks)
        assert result["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Test 6: Malformed created_at — FAIL
# ---------------------------------------------------------------------------

class TestMalformedCreatedAt:
    def test_date_only_fails(self):
        tasks = _tasks(**{"50": _entry(created_at="2026-04-01")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])

    def test_no_timezone_fails(self):
        tasks = _tasks(**{"51": _entry(created_at="2026-04-01T12:00:00")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 7: Negative reward_wea — FAIL
# ---------------------------------------------------------------------------

class TestNegativeRewardWea:
    def test_negative_fails(self):
        tasks = _tasks(**{"60": _entry(reward_wea=-5)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(
            v["issue"] == "60" and v["field"] == "reward_wea"
            for v in result["violations"]
        )

    def test_zero_fails(self):
        tasks = _tasks(**{"61": _entry(reward_wea=0)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "reward_wea" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 8: Empty accepted_agents list — PASS
# ---------------------------------------------------------------------------

class TestEmptyAcceptedAgents:
    def test_empty_list_passes(self):
        tasks = _tasks(**{"70": _entry(accepted_agents=[])})
        result = run(tasks)
        assert result["status"] == "PASS"
        assert result["violations"] == []

    def test_non_empty_list_passes(self):
        tasks = _tasks(**{"71": _entry(accepted_agents=["Claude-5@claude"])})
        result = run(tasks)
        assert result["status"] == "PASS"

    def test_dict_accepted_agents_fails(self):
        # A dict is not a list — must fail
        tasks = _tasks(**{"72": _entry(accepted_agents={})})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "accepted_agents" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 9: Invalid optional field type — FAIL
# ---------------------------------------------------------------------------

class TestInvalidOptionalFieldType:
    def test_claimed_by_int_fails(self):
        tasks = _tasks(**{"80": _entry(claimed_by=123)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "claimed_by" for v in result["violations"])

    def test_claimed_at_bad_format_fails(self):
        tasks = _tasks(**{"81": _entry(claimed_at="not-a-date")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "claimed_at" for v in result["violations"])

    def test_deadline_bad_format_fails(self):
        tasks = _tasks(**{"82": _entry(deadline="April 1st")})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "deadline" for v in result["violations"])

    def test_claimed_by_null_passes(self):
        tasks = _tasks(**{"83": _entry(claimed_by=None)})
        result = run(tasks)
        assert result["status"] == "PASS"

    def test_deadline_valid_date_passes(self):
        tasks = _tasks(**{"84": _entry(deadline="2026-05-01")})
        result = run(tasks)
        assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 10: Null required field — FAIL
# ---------------------------------------------------------------------------

class TestNullRequiredField:
    def test_null_reward_wea_fails(self):
        tasks = _tasks(**{"90": _entry(reward_wea=None)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(
            v["issue"] == "90" and v["field"] == "reward_wea"
            for v in result["violations"]
        )

    def test_null_created_at_fails(self):
        tasks = _tasks(**{"91": _entry(created_at=None)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "created_at" for v in result["violations"])

    def test_null_status_fails(self):
        tasks = _tasks(**{"92": _entry(status=None)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "status" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 11: Multi-entry mix (one valid, one invalid) — FAIL
# ---------------------------------------------------------------------------

class TestMultiEntryMix:
    def test_one_good_one_bad_fails(self):
        tasks = {
            "100": _entry(),
            "101": _entry(reward_type="unknown_type"),
        }
        result = run(tasks)
        assert result["status"] == "FAIL"
        # The valid entry produces no violations
        violations_for_100 = [v for v in result["violations"] if v["issue"] == "100"]
        assert violations_for_100 == []
        # The invalid entry produces at least one violation
        violations_for_101 = [v for v in result["violations"] if v["issue"] == "101"]
        assert len(violations_for_101) >= 1

    def test_multiple_valid_entries_pass(self):
        tasks = {
            "200": _entry(reward_type="pod"),
            "201": _entry(reward_type="duel", min_agents=2),
            "202": _entry(reward_type="wta", status="paid"),
        }
        result = run(tasks)
        assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 12: Empty task_index — PASS
# ---------------------------------------------------------------------------

class TestEmptyTaskIndex:
    def test_empty_tasks_pass(self):
        result = run({})
        assert result["status"] == "PASS"
        assert result["violations"] == []
        assert result["summary"] == "No violations"

    def test_non_dict_tasks_fail(self):
        result = run([])
        assert result["status"] == "FAIL"
        assert any("dict" in v["issue_detail"] for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 13: Legacy entries (no reward_wea) are grandfathered — PASS
# ---------------------------------------------------------------------------

class TestLegacyEntriesGrandfathered:
    def test_legacy_entry_passes(self):
        # Old-format entry: uses 'reward' and 'mechanic', no 'reward_wea'
        tasks = {
            "70": {
                "title": "Old task",
                "author": "agent0@system",
                "reward": 10,
                "mechanic": "best_x",
                "status": "cancelled",
                "created_at": "2026-03-05T10:35:07Z",
            }
        }
        result = run(tasks)
        assert result["status"] == "PASS"

    def test_legacy_status_cancelled_passes(self):
        # 'cancelled' is not in the new-format enum but grandfathered for legacy.
        tasks = {
            "72": {
                "reward": 10,
                "mechanic": "best_x",
                "status": "cancelled",
                "created_at": "2026-03-05T10:36:18Z",
            }
        }
        result = run(tasks)
        assert result["status"] == "PASS"


# ---------------------------------------------------------------------------
# Test 14: main() produces valid JSON output
# ---------------------------------------------------------------------------

class TestMainJsonOutput:
    def test_main_outputs_valid_json(self):
        result = subprocess.run(
            [sys.executable, "scripts/check_task_index_schema.py"],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent),
        )
        output = result.stdout.strip()
        assert output, "main() produced no stdout"
        parsed = json.loads(output)
        assert "status" in parsed
        assert "violations" in parsed
        assert "summary" in parsed
        assert isinstance(parsed["violations"], list)

    def test_main_exits_0_on_current_ledger(self):
        result = subprocess.run(
            [sys.executable, "scripts/check_task_index_schema.py"],
            capture_output=True,
            text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent),
        )
        assert result.returncode == 0, (
            f"Script failed on current ledger:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Test 15: Key validation — non-integer keys fail
# ---------------------------------------------------------------------------

class TestKeyValidation:
    def test_non_integer_key_fails(self):
        # A legacy entry with a non-integer key still fails key validation.
        tasks = {"abc": {"reward": 10, "status": "open"}}
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "issue_number" for v in result["violations"])

    def test_zero_key_fails(self):
        tasks = {"0": {"reward": 10, "status": "open"}}
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "issue_number" for v in result["violations"])

    def test_negative_key_fails(self):
        tasks = {"-1": {"reward": 10, "status": "open"}}
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "issue_number" for v in result["violations"])


# ---------------------------------------------------------------------------
# Test 16: min_agents edge cases
# ---------------------------------------------------------------------------

class TestMinAgentsValidation:
    def test_zero_min_agents_fails(self):
        tasks = _tasks(**{"110": _entry(min_agents=0)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "min_agents" for v in result["violations"])

    def test_negative_min_agents_fails(self):
        tasks = _tasks(**{"111": _entry(min_agents=-1)})
        result = run(tasks)
        assert result["status"] == "FAIL"

    def test_bool_min_agents_fails(self):
        # bool is a subclass of int in Python — must be explicitly rejected
        tasks = _tasks(**{"112": _entry(min_agents=True)})
        result = run(tasks)
        assert result["status"] == "FAIL"
        assert any(v["field"] == "min_agents" for v in result["violations"])


# ---------------------------------------------------------------------------
# Tests for helpers
# ---------------------------------------------------------------------------

class TestIsIso8601Datetime:
    def test_z_suffix(self):
        assert _is_iso8601_datetime("2026-04-01T00:00:00Z") is True

    def test_positive_offset(self):
        assert _is_iso8601_datetime("2026-04-01T00:00:00+05:30") is True

    def test_negative_offset(self):
        assert _is_iso8601_datetime("2026-04-01T00:00:00-08:00") is True

    def test_fractional_seconds(self):
        assert _is_iso8601_datetime("2026-04-01T12:00:00.123Z") is True

    def test_date_only_rejected(self):
        assert _is_iso8601_datetime("2026-04-01") is False

    def test_no_offset_rejected(self):
        assert _is_iso8601_datetime("2026-04-01T12:00:00") is False

    def test_none_rejected(self):
        assert _is_iso8601_datetime(None) is False


class TestIsIso8601Date:
    def test_valid_date(self):
        assert _is_iso8601_date("2026-04-01") is True

    def test_datetime_rejected(self):
        assert _is_iso8601_date("2026-04-01T12:00:00Z") is False

    def test_none_rejected(self):
        assert _is_iso8601_date(None) is False
