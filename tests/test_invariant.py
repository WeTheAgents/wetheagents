#!/usr/bin/env python3
"""Tests for check_invariant.py — non-negative guards and sum equation."""

import json
import os
import shutil
import subprocess
import tempfile

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "check_invariant.py")
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _make_ledger(tmp, balances_agents, escrows_active):
    """Create a temporary ledger directory with given data."""
    os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "sandbox"), exist_ok=True)

    with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
        json.dump({"version": 1, "agents": balances_agents}, f)

    with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
        json.dump({"version": 1, "active": escrows_active}, f)

    with open(os.path.join(tmp, "sandbox", "hello_world_registry.jsonl"), "w") as f:
        f.write("")


def _run(tmp):
    result = subprocess.run(
        ["python", SCRIPT, "--root", tmp],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout


def test_clean_ledger_passes():
    """Current production ledger should pass."""
    result = subprocess.run(
        ["python", SCRIPT, "--root", REPO_ROOT],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Production ledger failed: {result.stdout}"
    assert "PASS" in result.stdout


def test_negative_escrow_fails():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10100}},
            escrows_active={"99": {"author": "a@test", "amount": -100, "type": "standard", "created_at": "2026-01-01T00:00:00Z"}},
        )
        code, out = _run(tmp)
        assert code == 1, f"Expected failure, got: {out}"
        assert "Negative escrows" in out
    finally:
        shutil.rmtree(tmp)


def test_negative_balance_fails():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"evil@test": {"balance": -50}},
            escrows_active={"1": {"author": "x", "amount": 10050, "type": "standard", "created_at": "2026-01-01T00:00:00Z"}},
        )
        code, out = _run(tmp)
        assert code == 1, f"Expected failure, got: {out}"
        assert "Negative balances" in out
    finally:
        shutil.rmtree(tmp)


def test_balanced_ledger_passes():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={
                "alice@test": {"balance": 5000},
                "bob@test": {"balance": 3000},
            },
            escrows_active={"1": {"author": "alice@test", "amount": 2000, "type": "standard", "created_at": "2026-01-01T00:00:00Z"}},
        )
        code, out = _run(tmp)
        assert code == 0, f"Expected pass, got: {out}"
        assert "PASS" in out
    finally:
        shutil.rmtree(tmp)


def test_unbalanced_sum_fails():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"alice@test": {"balance": 9000}},
            escrows_active={"1": {"author": "alice@test", "amount": 2000, "type": "standard", "created_at": "2026-01-01T00:00:00Z"}},
        )
        code, out = _run(tmp)
        assert code == 1, f"Expected failure (sum 11000 != 10000), got: {out}"
        assert "FAIL" in out
        assert "Why it matters" in out
        assert "Remediation" in out
    finally:
        shutil.rmtree(tmp)


def test_registry_does_not_change_fixed_supply():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={
                "alice@test": {"balance": 5000},
                "bob@test": {"balance": 5000},
            },
            escrows_active={},
        )
        with open(os.path.join(tmp, "sandbox", "hello_world_registry.jsonl"), "w") as f:
            f.write(json.dumps({"agent": "legacy-1"}) + "\n")
            f.write(json.dumps({"agent": "legacy-2"}) + "\n")
        code, out = _run(tmp)
        assert code == 0, f"Expected pass (registry no longer changes supply), got: {out}"
        assert "PASS" in out
    finally:
        shutil.rmtree(tmp)


# ---------------------------------------------------------------------------
# Edge cases (#65)
# ---------------------------------------------------------------------------


def test_corrupted_json_fails():
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        os.makedirs(os.path.join(tmp, "sandbox"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            f.write("{invalid json")
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": {}}, f)
        with open(os.path.join(tmp, "sandbox", "hello_world_registry.jsonl"), "w") as f:
            pass
        code, out = _run(tmp)
        assert code != 0, f"Expected failure on corrupted JSON, got: {out}"
    finally:
        shutil.rmtree(tmp)


def test_empty_agents_fails():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={},
            escrows_active={},
        )
        code, out = _run(tmp)
        assert code == 1, f"Expected failure (sum 0 != 10000), got: {out}"
        assert "FAIL" in out
    finally:
        shutil.rmtree(tmp)


def test_missing_balance_key_defaults_zero():
    """Agent entry without 'balance' key — .get defaults to 0, sum wrong."""
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {}},
            escrows_active={},
        )
        code, out = _run(tmp)
        assert code == 1, f"Expected failure (sum 0 != 10000), got: {out}"
    finally:
        shutil.rmtree(tmp)


def test_missing_escrow_amount_defaults_zero():
    """Escrow without 'amount' key — .get defaults to 0."""
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10000}},
            escrows_active={"1": {"author": "a@test", "type": "standard", "created_at": "2026-01-01T00:00:00Z"}},
        )
        code, out = _run(tmp)
        assert code == 0, f"Expected pass (10000 + 0 = 10000), got: {out}"
    finally:
        shutil.rmtree(tmp)
