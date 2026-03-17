"""Tests for the process_pending.py circuit breaker — T3 Slot 2.

The circuit breaker checks the invariant after all in-memory modifications
but before writing files to disk. If the invariant is broken, it halts
and writes nothing.

Tests:
1. _invariant_failure detects negative balances.
2. _invariant_failure detects negative escrows.
3. _invariant_failure detects conservation drift.
4. _invariant_failure passes clean state.
5. _sum_balances_and_escrows computes correctly.
6. process() halts when circuit breaker fires (monkeypatched).
7. process() does not modify files when circuit breaker fires.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.process_pending import (
    _invariant_failure,
    _sum_balances_and_escrows,
    process,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _make_balances(*agent_bals: tuple[str, int]) -> dict:
    return {
        "agents": {
            name: {"balance": bal} for name, bal in agent_bals
        }
    }


def _make_escrows(*escrow_amounts: tuple[str, int]) -> dict:
    return {
        "active": {
            issue: {"amount": amt} for issue, amt in escrow_amounts
        }
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


# ── Test 1: Detects negative balance ──────────────────────────────────


def test_invariant_failure_detects_negative_balance() -> None:
    bal = _make_balances(("good@test", 100), ("bad@test", -5))
    esc = _make_escrows()
    result = _invariant_failure(bal, esc, expected_total=95)
    assert result is not None
    assert "negative balance" in result
    assert "bad@test" in result


# ── Test 2: Detects negative escrow ───────────────────────────────────


def test_invariant_failure_detects_negative_escrow() -> None:
    bal = _make_balances(("a@test", 100))
    esc = _make_escrows(("42", -3))
    result = _invariant_failure(bal, esc, expected_total=97)
    assert result is not None
    assert "negative escrow" in result
    assert "#42" in result


# ── Test 3: Detects conservation drift ────────────────────────────────


def test_invariant_failure_detects_drift() -> None:
    bal = _make_balances(("a@test", 100))
    esc = _make_escrows(("1", 50))
    # Actual total is 150, but we claim 200
    result = _invariant_failure(bal, esc, expected_total=200)
    assert result is not None
    assert "drift" in result
    assert "200" in result
    assert "150" in result


# ── Test 4: Passes clean state ────────────────────────────────────────


def test_invariant_failure_passes_clean_state() -> None:
    bal = _make_balances(("a@test", 100), ("b@test", 50))
    esc = _make_escrows(("1", 30), ("2", 20))
    result = _invariant_failure(bal, esc, expected_total=200)
    assert result is None


# ── Test 5: Sum computation ───────────────────────────────────────────


def test_sum_balances_and_escrows() -> None:
    bal = _make_balances(("a@test", 100), ("b@test", 250))
    esc = _make_escrows(("1", 30), ("2", 20))
    assert _sum_balances_and_escrows(bal, esc) == 400


def test_sum_empty() -> None:
    assert _sum_balances_and_escrows({"agents": {}}, {"active": {}}) == 0


# ── Test 6: process() halts when circuit breaker fires ────────────────


def test_process_halts_on_circuit_breaker(temp_repo: Path, monkeypatch) -> None:
    """Monkeypatch _invariant_failure to always fire, verify process returns 1."""
    import scripts.process_pending as mod

    escrows_path = temp_repo / "ledger" / "escrows.json"
    pending_path = temp_repo / "ledger" / "pending.json"

    escrows = _read_json(escrows_path)
    escrows["active"]["301"] = {
        "author": "author@local",
        "amount": 10,
        "type": "standard",
        "created_at": "2026-03-04T10:00:00Z",
    }
    _write_json(escrows_path, escrows)

    _write_json(pending_path, {
        "version": 1,
        "queue": [{
            "type": "payment",
            "mechanic": "standard",
            "issue": 301,
            "agent": "alice@test",
            "amount": 10,
            "proposed_by": "author@local",
            "proposed_at": "2026-03-04T10:01:00Z",
            "event_at": "2026-03-04T10:01:00Z",
        }],
    })

    # Inject a circuit breaker trigger
    monkeypatch.setattr(mod, "_invariant_failure", lambda *a, **kw: "INJECTED: test failure")

    rc = process(temp_repo, dry_run=False)
    assert rc == 1


# ── Test 7: Files untouched when circuit breaker fires ────────────────


def test_files_untouched_on_circuit_breaker(temp_repo: Path, monkeypatch) -> None:
    """When circuit breaker fires, no ledger files should be modified."""
    import scripts.process_pending as mod

    balances_path = temp_repo / "ledger" / "balances.json"
    escrows_path = temp_repo / "ledger" / "escrows.json"
    idem_path = temp_repo / "ledger" / "idem_keys.json"
    pending_path = temp_repo / "ledger" / "pending.json"

    # Snapshot file contents before
    bal_before = balances_path.read_text(encoding="utf-8")
    esc_before_data = _read_json(escrows_path)
    idem_before = idem_path.read_text(encoding="utf-8")

    # Set up a valid payment
    esc_before_data["active"]["302"] = {
        "author": "author@local",
        "amount": 15,
        "type": "standard",
        "created_at": "2026-03-04T10:00:00Z",
    }
    _write_json(escrows_path, esc_before_data)
    esc_before = escrows_path.read_text(encoding="utf-8")

    _write_json(pending_path, {
        "version": 1,
        "queue": [{
            "type": "payment",
            "mechanic": "standard",
            "issue": 302,
            "agent": "bob@test",
            "amount": 15,
            "proposed_by": "author@local",
            "proposed_at": "2026-03-04T10:02:00Z",
            "event_at": "2026-03-04T10:02:00Z",
        }],
    })
    pending_before = pending_path.read_text(encoding="utf-8")

    # Inject circuit breaker failure
    monkeypatch.setattr(mod, "_invariant_failure", lambda *a, **kw: "INJECTED: conservation drift")

    rc = process(temp_repo, dry_run=False)
    assert rc == 1

    # Verify NO files were changed
    assert balances_path.read_text(encoding="utf-8") == bal_before
    assert escrows_path.read_text(encoding="utf-8") == esc_before
    assert idem_path.read_text(encoding="utf-8") == idem_before
    # Pending queue should NOT have been cleared
    assert pending_path.read_text(encoding="utf-8") == pending_before
