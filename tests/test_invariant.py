#!/usr/bin/env python3
"""Tests for check_invariant.py — non-negative guards and sum equation."""

import json
import os
import subprocess
import tempfile
import shutil

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "check_invariant.py")
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _make_ledger(tmp, balances_agents, escrows_active, hello_count=0):
    """Create a temporary ledger directory with given data."""
    os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
    os.makedirs(os.path.join(tmp, "sandbox"), exist_ok=True)

    with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
        json.dump({"version": 1, "agents": balances_agents}, f)

    with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
        json.dump({"version": 1, "active": escrows_active}, f)

    with open(os.path.join(tmp, "sandbox", "hello_world_registry.jsonl"), "w") as f:
        for i in range(hello_count):
            f.write(json.dumps({"agent": f"agent{i}"}) + "\n")


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
            hello_count=0,
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
            hello_count=0,
        )
        code, out = _run(tmp)
        assert code == 1, f"Expected failure (sum 11000 != 10000), got: {out}"
        assert "FAIL" in out
        assert "Why it matters" in out
        assert "Remediation" in out
    finally:
        shutil.rmtree(tmp)


def test_with_hello_mints():
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={
                "alice@test": {"balance": 5100},
                "bob@test": {"balance": 5100},
            },
            escrows_active={},
            hello_count=2,
        )
        code, out = _run(tmp)
        assert code == 0, f"Expected pass (10200 = 10000 + 2*100), got: {out}"
        assert "PASS" in out
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    tests = [
        test_clean_ledger_passes,
        test_negative_escrow_fails,
        test_negative_balance_fails,
        test_balanced_ledger_passes,
        test_unbalanced_sum_fails,
        test_with_hello_mints,
    ]
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}")
        except Exception as e:
            print(f"ERROR: {t.__name__}: {e}")
