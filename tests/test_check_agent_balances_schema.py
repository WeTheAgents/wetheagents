"""Tests for check_agent_balances_schema — agent record validation."""

import pytest

from scripts.check_agent_balances_schema import is_iso8601, run_validation, validate_agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _agent(**overrides):
    """Build a valid agent record, applying overrides or deletions.

    Pass a field name with value DELETE_KEY sentinel to remove it.
    """
    base = {
        "balance": 100,
        "registered_at": "2026-03-01T00:00:00Z",
        "platform": "claude-code",
        "operator": "peach",
        "github_username": "peachuser",
        "total_earned": 100,
        "total_spent": 0,
        "tasks_completed": 3,
        "tasks_created": 1,
    }
    for k, v in overrides.items():
        if v is _DELETE:
            base.pop(k, None)
        else:
            base[k] = v
    return base


_DELETE = object()


def _data(*agents_pairs, version=1):
    """Build a full balances.json-shaped dict from (agent_id, agent) pairs."""
    return {"version": version, "agents": dict(agents_pairs)}


# ---------------------------------------------------------------------------
# is_iso8601 unit tests
# ---------------------------------------------------------------------------

class TestIsIso8601:
    def test_valid_utc(self):
        assert is_iso8601("2026-03-01T00:00:00Z")

    def test_valid_offset(self):
        assert is_iso8601("2026-03-01T12:30:00+05:30")

    def test_valid_fractional_seconds(self):
        assert is_iso8601("2026-03-01T00:00:00.123Z")

    def test_invalid_date_only(self):
        assert not is_iso8601("2026-03-01")

    def test_invalid_space_separator(self):
        assert not is_iso8601("2026-03-01 00:00:00Z")

    def test_empty_string(self):
        assert not is_iso8601("")


# ---------------------------------------------------------------------------
# validate_agent unit tests
# ---------------------------------------------------------------------------

class TestValidateAgent:
    def test_valid_agent_no_violations(self):
        viols = validate_agent("alice@test", _agent())
        assert viols == []

    def test_valid_agent_float_balance_allowed(self):
        viols = validate_agent("alice@test", _agent(balance=99.5))
        assert viols == []

    def test_valid_agent_float_total_earned_allowed(self):
        viols = validate_agent("alice@test", _agent(total_earned=10.0))
        assert viols == []

    def test_valid_agent_extra_optional_field_ignored(self):
        rec = _agent()
        rec["runtime"] = ["cloud"]
        rec["slot"] = "5"
        viols = validate_agent("alice@test", rec)
        assert viols == []

    def test_missing_balance(self):
        viols = validate_agent("alice@test", _agent(**{"balance": _DELETE}))
        fields = [v["field"] for v in viols]
        assert "balance" in fields

    def test_missing_registered_at(self):
        viols = validate_agent("alice@test", _agent(**{"registered_at": _DELETE}))
        fields = [v["field"] for v in viols]
        assert "registered_at" in fields

    def test_missing_platform(self):
        viols = validate_agent("alice@test", _agent(**{"platform": _DELETE}))
        assert any(v["field"] == "platform" for v in viols)

    def test_missing_operator(self):
        viols = validate_agent("alice@test", _agent(**{"operator": _DELETE}))
        assert any(v["field"] == "operator" for v in viols)

    def test_missing_github_username(self):
        viols = validate_agent("alice@test", _agent(**{"github_username": _DELETE}))
        assert any(v["field"] == "github_username" for v in viols)

    def test_missing_total_earned(self):
        viols = validate_agent("alice@test", _agent(**{"total_earned": _DELETE}))
        assert any(v["field"] == "total_earned" for v in viols)

    def test_missing_total_spent(self):
        viols = validate_agent("alice@test", _agent(**{"total_spent": _DELETE}))
        assert any(v["field"] == "total_spent" for v in viols)

    def test_missing_tasks_completed(self):
        viols = validate_agent("alice@test", _agent(**{"tasks_completed": _DELETE}))
        assert any(v["field"] == "tasks_completed" for v in viols)

    def test_missing_tasks_created(self):
        viols = validate_agent("alice@test", _agent(**{"tasks_created": _DELETE}))
        assert any(v["field"] == "tasks_created" for v in viols)

    def test_negative_balance_rejected(self):
        viols = validate_agent("alice@test", _agent(balance=-1))
        assert any(v["field"] == "balance" for v in viols)

    def test_string_balance_rejected(self):
        viols = validate_agent("alice@test", _agent(balance="100"))
        assert any(v["field"] == "balance" for v in viols)

    def test_bool_balance_rejected(self):
        # bool is subclass of int — must be explicitly rejected
        viols = validate_agent("alice@test", _agent(balance=True))
        assert any(v["field"] == "balance" for v in viols)

    def test_negative_total_earned_rejected(self):
        viols = validate_agent("alice@test", _agent(total_earned=-5))
        assert any(v["field"] == "total_earned" for v in viols)

    def test_negative_total_spent_rejected(self):
        viols = validate_agent("alice@test", _agent(total_spent=-1))
        assert any(v["field"] == "total_spent" for v in viols)

    def test_float_tasks_completed_rejected(self):
        viols = validate_agent("alice@test", _agent(tasks_completed=3.0))
        assert any(v["field"] == "tasks_completed" for v in viols)

    def test_float_tasks_created_rejected(self):
        viols = validate_agent("alice@test", _agent(tasks_created=1.0))
        assert any(v["field"] == "tasks_created" for v in viols)

    def test_negative_tasks_completed_rejected(self):
        viols = validate_agent("alice@test", _agent(tasks_completed=-1))
        assert any(v["field"] == "tasks_completed" for v in viols)

    def test_negative_tasks_created_rejected(self):
        viols = validate_agent("alice@test", _agent(tasks_created=-2))
        assert any(v["field"] == "tasks_created" for v in viols)

    def test_invalid_registered_at_format(self):
        viols = validate_agent("alice@test", _agent(registered_at="2026-03-01"))
        assert any(v["field"] == "registered_at" for v in viols)

    def test_non_string_registered_at_rejected(self):
        viols = validate_agent("alice@test", _agent(registered_at=20260301))
        assert any(v["field"] == "registered_at" for v in viols)

    def test_empty_platform_rejected(self):
        viols = validate_agent("alice@test", _agent(platform=""))
        assert any(v["field"] == "platform" for v in viols)

    def test_whitespace_only_platform_rejected(self):
        viols = validate_agent("alice@test", _agent(platform="   "))
        assert any(v["field"] == "platform" for v in viols)

    def test_empty_operator_rejected(self):
        viols = validate_agent("alice@test", _agent(operator=""))
        assert any(v["field"] == "operator" for v in viols)

    def test_empty_github_username_rejected(self):
        viols = validate_agent("alice@test", _agent(github_username=""))
        assert any(v["field"] == "github_username" for v in viols)

    def test_violation_carries_agent_id(self):
        viols = validate_agent("bob@claude", _agent(balance=-5))
        assert all(v["agent_id"] == "bob@claude" for v in viols)


# ---------------------------------------------------------------------------
# run_validation integration tests
# ---------------------------------------------------------------------------

class TestRunValidation:
    def test_valid_data_passes(self):
        data = _data(("alice@test", _agent()))
        checks, viols = run_validation(data)
        assert viols == []
        assert any(c["status"] == "PASS" for c in checks)

    def test_missing_version_flagged(self):
        data = {"agents": {"alice@test": _agent()}}
        checks, viols = run_validation(data)
        assert any(v["field"] == "version" for v in viols)

    def test_missing_agents_key_stops_early(self):
        _, viols = run_validation({"version": 1})
        assert any(v["field"] == "agents" for v in viols)

    def test_agents_not_dict_stops_early(self):
        _, viols = run_validation({"version": 1, "agents": ["alice@test"]})
        assert any(v["field"] == "agents" for v in viols)

    def test_agent_record_not_dict(self):
        data = {"version": 1, "agents": {"alice@test": "not-a-dict"}}
        _, viols = run_validation(data)
        assert any(v["agent_id"] == "alice@test" for v in viols)

    def test_multiple_agents_all_validated(self):
        data = _data(
            ("alice@test", _agent()),
            ("bob@test", _agent(balance=-1)),
        )
        _, viols = run_validation(data)
        # only bob should have violations
        assert all(v["agent_id"] == "bob@test" for v in viols)

    def test_status_fail_on_violation(self):
        data = _data(("alice@test", _agent(balance=-1)))
        checks, viols = run_validation(data)
        assert viols  # non-empty means FAIL

    def test_checks_list_populated(self):
        data = _data(("alice@test", _agent()))
        checks, _ = run_validation(data)
        assert len(checks) >= 1

    def test_zero_balance_passes(self):
        _, viols = run_validation(_data(("alice@test", _agent(balance=0))))
        assert viols == []

    def test_zero_tasks_passes(self):
        _, viols = run_validation(
            _data(("alice@test", _agent(tasks_completed=0, tasks_created=0)))
        )
        assert viols == []

    def test_bool_tasks_completed_rejected(self):
        data = _data(("alice@test", _agent(tasks_completed=True)))
        _, viols = run_validation(data)
        assert any(v["field"] == "tasks_completed" for v in viols)
