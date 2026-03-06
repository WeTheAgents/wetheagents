"""Tests for check_ledger_schema — ledger JSON structure validation."""

import pytest

from scripts.check_ledger_schema import (
    ERRORS,
    validate_balances,
    validate_escrows,
    validate_idem_keys,
    validate_pending,
    validate_task_index,
)


@pytest.fixture(autouse=True)
def clear_errors():
    ERRORS.clear()
    yield
    ERRORS.clear()


# -- balances.json --

class TestValidateBalances:
    def test_valid_no_errors(self):
        data = {
            "version": 1,
            "agents": {
                "alice@test": {
                    "balance": 100,
                    "registered_at": "2026-03-01T00:00:00Z",
                    "platform": "Cursor",
                    "github_username": "alice",
                },
            },
        }
        validate_balances(data)
        assert ERRORS == []

    def test_missing_version(self):
        validate_balances({"agents": {}})
        assert any("version" in e for e in ERRORS)

    def test_missing_agents(self):
        validate_balances({"version": 1})
        assert any("agents" in e for e in ERRORS)

    def test_agent_id_no_at(self):
        data = {
            "version": 1,
            "agents": {
                "alice": {
                    "balance": 100,
                    "registered_at": "2026-03-01T00:00:00Z",
                    "platform": "Cursor",
                    "github_username": "alice",
                },
            },
        }
        validate_balances(data)
        assert any("@" in e for e in ERRORS)

    def test_string_balance(self):
        data = {
            "version": 1,
            "agents": {
                "alice@test": {
                    "balance": "100",
                    "registered_at": "2026-03-01T00:00:00Z",
                    "platform": "Cursor",
                    "github_username": "alice",
                },
            },
        }
        validate_balances(data)
        assert any("not int" in e for e in ERRORS)

    def test_negative_balance(self):
        data = {
            "version": 1,
            "agents": {
                "alice@test": {
                    "balance": -5,
                    "registered_at": "2026-03-01T00:00:00Z",
                    "platform": "Cursor",
                    "github_username": "alice",
                },
            },
        }
        validate_balances(data)
        assert any("negative" in e.lower() for e in ERRORS)

    def test_missing_required_fields(self):
        data = {"version": 1, "agents": {"alice@test": {"balance": 100}}}
        validate_balances(data)
        assert any("registered_at" in e for e in ERRORS)
        assert any("platform" in e for e in ERRORS)
        assert any("github_username" in e for e in ERRORS)


# -- escrows.json --

class TestValidateEscrows:
    def test_valid_no_errors(self):
        data = {
            "version": 1,
            "active": {
                "42": {"author": "alice@test", "amount": 30, "type": "standard"},
            },
        }
        validate_escrows(data)
        assert ERRORS == []

    def test_invalid_type(self):
        data = {
            "version": 1,
            "active": {
                "42": {"author": "alice@test", "amount": 30, "type": "unknown"},
            },
        }
        validate_escrows(data)
        assert any("unknown" in e for e in ERRORS)

    def test_negative_amount(self):
        data = {
            "version": 1,
            "active": {
                "42": {"author": "alice@test", "amount": -10, "type": "standard"},
            },
        }
        validate_escrows(data)
        assert any("negative" in e.lower() for e in ERRORS)

    def test_missing_author(self):
        data = {
            "version": 1,
            "active": {
                "42": {"amount": 30, "type": "standard"},
            },
        }
        validate_escrows(data)
        assert any("author" in e for e in ERRORS)

    def test_missing_amount(self):
        data = {
            "version": 1,
            "active": {
                "42": {"author": "alice@test", "type": "standard"},
            },
        }
        validate_escrows(data)
        assert any("amount" in e for e in ERRORS)


# -- idem_keys.json --

def test_idem_keys_missing_keys():
    validate_idem_keys({})
    assert any("keys" in e for e in ERRORS)


def test_idem_keys_valid():
    validate_idem_keys({"keys": {"foo": "bar"}})
    assert ERRORS == []


# -- pending.json --

def test_pending_queue_not_list():
    validate_pending({"queue": {}})
    assert any("not a list" in e for e in ERRORS)


def test_pending_valid():
    validate_pending({"queue": []})
    assert ERRORS == []


# -- task_index.json --

def test_task_index_missing_tasks():
    validate_task_index({})
    assert any("tasks" in e for e in ERRORS)


def test_task_index_valid():
    validate_task_index({"tasks": {}})
    assert ERRORS == []
