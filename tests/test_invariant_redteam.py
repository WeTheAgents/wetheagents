#!/usr/bin/env python3
"""
Red Team Tests for check_invariant.py — Gauntlet T6 S1
Author: Claude-1@claude
Issue: #301

Findings and severity:
  CRITICAL:
    C1 — Non-dict agent entries (string/list/null) crash with AttributeError
         instead of emitting a clean FAIL message.
    C2 — Non-numeric balance/escrow amount values crash with TypeError
         instead of emitting a clean FAIL message.
  HIGH:
    H1 — agents/active section as list (not dict): .values() raises AttributeError.
    H2 — Float balance/escrow values can silently fail IEEE 754 equality check,
         causing false invariant failures on mathematically-correct ledgers.
    H3 — int() truncation of total_minted happens BEFORE the cross-check:
         total_minted=19.9 truncates to 19, but mints sum stays 19.9,
         producing a false failure; also allows phantom 0.9 WEA with crafted values.
    H4 — Non-dict mint entries in the mints array crash with AttributeError.
    H5 — String amounts in escrow or mint entries crash sum() with TypeError.
  MEDIUM:
    M1 — Version fields are never validated (missing or wrong type silently ignored).
    M2 — total_minted vs sum(mints) cross-check documented (already implemented).
"""
import json
import os
import shutil
import subprocess
import tempfile

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "check_invariant.py")


def _make_ledger(tmp, balances_agents, escrows_active, mints=None):
    """Create a temporary ledger with the given agent/escrow/mint data."""
    os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
    with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
        json.dump({"version": 1, "agents": balances_agents}, f)
    with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
        json.dump({"version": 1, "active": escrows_active}, f)
    if mints is not None:
        with open(os.path.join(tmp, "ledger", "trajectory_mints.json"), "w") as f:
            json.dump(mints, f)


def _run(tmp):
    result = subprocess.run(
        ["python", SCRIPT, "--root", tmp],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ──────────────────────────────────────────────────────────────────────────────
# CRITICAL — C1: Non-dict agent entries
# ──────────────────────────────────────────────────────────────────────────────

def test_c1_string_agent_entry_fails_cleanly():
    """
    CRITICAL C1 — agents dict contains a string value.

    Repro: {"agents": {"evil@test": "owned"}}
    Current behaviour: AttributeError traceback in stderr, exit 1 (no FAIL line).
    Expected behaviour: clean FAIL message in stdout, no Python exception in stderr.
    Impact: Pre-commit hook emits a traceback that looks like a system error,
            not a ledger violation — an operator might skip/bypass the hook.
    Fix: Validate each agent entry is a dict before calling .get().
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": 1, "agents": {"evil@test": "owned"}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": {}}, f)
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_c1_null_agent_entry_fails_cleanly():
    """
    CRITICAL C1 — agents dict contains a null value (JSON null → Python None).

    Repro: {"agents": {"evil@test": null}}
    Current behaviour: AttributeError on None.get('balance', 0).
    Fix: Same as string case — validate entry is a dict.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": 1, "agents": {"evil@test": None}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": {}}, f)
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_c1_list_agent_entry_fails_cleanly():
    """
    CRITICAL C1 — agents dict contains a list value.

    Repro: {"agents": {"evil@test": [1, 2, 3]}}
    Current behaviour: AttributeError on [1,2,3].get('balance', 0).
    Fix: Same as above.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": 1, "agents": {"evil@test": [1, 2, 3]}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": {}}, f)
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# CRITICAL — C2: Non-numeric balance / escrow amounts
# ──────────────────────────────────────────────────────────────────────────────

def test_c2_string_balance_fails_cleanly():
    """
    CRITICAL C2 — balance field is a string instead of int.

    Repro: {"balance": "5000"} — .get returns "5000", sum() raises TypeError.
    Impact: Script crashes without FAIL message; same bypass risk as C1.
    Fix: Validate balance is int or float before summing.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": "5000"}, "b@test": {"balance": 5000}},
            escrows_active={},
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "TypeError" not in err, f"Unhandled TypeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_c2_null_balance_fails_cleanly():
    """
    CRITICAL C2 — balance field is JSON null (Python None).

    Repro: {"balance": null} — .get returns None, sum() raises TypeError.
    Fix: Same as string case.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": None}},
            escrows_active={},
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "TypeError" not in err, f"Unhandled TypeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_c2_string_escrow_amount_fails_cleanly():
    """
    CRITICAL C2 — escrow amount field is a string instead of int.

    Repro: {"amount": "500"} — .get returns "500", sum() raises TypeError.
    Impact: Silently unhandled. Same pre-commit bypass risk.
    Fix: Validate escrow amount is numeric before summing.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": 1, "agents": {"a@test": {"balance": 9500}}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": {
                "1": {"author": "a@test", "amount": "500", "type": "standard",
                      "created_at": "2026-01-01T00:00:00Z"},
            }}, f)
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "TypeError" not in err, f"Unhandled TypeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# HIGH — H1: agents / active section as wrong type
# ──────────────────────────────────────────────────────────────────────────────

def test_h1_agents_section_as_list_fails_cleanly():
    """
    HIGH H1 — agents section is a list, not a dict.

    Repro: {"agents": [{"balance": 10000}]} — .values() on a list raises AttributeError.
    Impact: Same traceback-bypass risk as C1.
    Fix: Assert isinstance(agents, dict) and emit FAIL if not.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": 1, "agents": [{"balance": 10000}]}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": {}}, f)
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_h1_active_section_as_list_fails_cleanly():
    """
    HIGH H1 — active (escrows) section is a list, not a dict.

    Repro: {"active": [{"amount": 0}]} — .values() on a list raises AttributeError.
    Fix: Assert isinstance(active, dict) and emit FAIL if not.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": 1, "agents": {"a@test": {"balance": 10000}}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": 1, "active": [{"amount": 0}]}, f)
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# CRITICAL — Non-dict escrow entries (missed in original C1 fix)
# ──────────────────────────────────────────────────────────────────────────────

def test_non_dict_escrow_entry_fails_cleanly():
    """
    CRITICAL — active dict contains a string value instead of an escrow object.

    Repro: {"active": {"1": "corrupted"}}
    Without fix: AttributeError on 'str'.get('amount', 0) in total_escrowed sum
                 and in the negative-escrow guard — script crashes with traceback.
    Expected: clean FAIL message in stdout, no Python exception in stderr.
    Impact: Pre-commit hook emits a traceback that looks like a system error
            rather than a ledger violation — an operator might skip/bypass the hook.
    Fix: Validate each active entry is a dict before proceeding with amount checks.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10000}},
            escrows_active={"1": "corrupted"},
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# HIGH — H2: Floating-point balance precision
# ──────────────────────────────────────────────────────────────────────────────

def test_h2_float_balances_no_crash():
    """
    HIGH H2 — Float balance values may fail IEEE 754 equality check.

    Repro: 3333.33 * 3 + 0.01 is mathematically 10000.0, but
           float addition can yield 9999.999999999998 or 10000.000000000002.
    Impact: A valid ledger may report FAIL (false positive), or a tampered
            ledger may report PASS (false negative) depending on rounding.
    Current behaviour: No crash, but equality check may be unreliable.
    Fix: Enforce integer-only WEA values (reject floats) or use round().

    Note: This test documents the hazard — it does not assert PASS/FAIL,
    only that no unhandled exception occurs.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={
                "a@test": {"balance": 3333.33},
                "b@test": {"balance": 3333.33},
                "c@test": {"balance": 3333.33},
                "d@test": {"balance": 0.01},
            },
            escrows_active={},
        )
        code, out, err = _run(tmp)
        assert "TypeError" not in err and "AttributeError" not in err, \
            f"Unexpected crash with float balances:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_h2_float_balances_should_be_rejected():
    """
    HIGH H2 — After fix, float balances must be explicitly rejected.

    Fix: Script should emit FAIL with a 'non-integer balance' message
         instead of silently using floats that may fail IEEE 754 equality.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 5000.5}, "b@test": {"balance": 4999.5}},
            escrows_active={},
        )
        code, out, err = _run(tmp)
        # After fix: floats should be rejected
        assert code == 1, f"Expected exit 1 for float balance, got {code}\nout: {out}"
        assert "FAIL" in out, f"Expected FAIL message for float balance:\n{out}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# HIGH — H3: int() truncation of total_minted before cross-check
# ──────────────────────────────────────────────────────────────────────────────

def test_h3_fractional_total_minted_false_failure():
    """
    HIGH H3 — int() truncation causes false cross-check failure.

    Repro: total_minted=19.9, mints=[{"amount": 19.9}].
    After int(19.9) = 19, cross-check: sum(mints)=19.9 != total_minted=19 → FAIL.
    But the data is internally consistent (19.9 == 19.9 before truncation).
    Impact: Valid fractional ledger gets rejected as corrupt.
    Fix: Either reject non-integer total_minted explicitly,
         or perform the cross-check BEFORE the int() conversion.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10020}},
            escrows_active={},
            mints={
                "version": 1,
                "total_minted": 19.9,
                "mints": [{"trajectory": "T1", "slot": 1, "amount": 19.9}],
            },
        )
        code, out, err = _run(tmp)
        assert "TypeError" not in err and "AttributeError" not in err, \
            f"Unhandled exception with fractional total_minted:\n{err}"
        # After fix: non-integer total_minted should produce a clean FAIL
        if code == 1:
            assert "FAIL" in out, f"Exit 1 but no FAIL message:\nstdout: {out}\nstderr: {err}"
    finally:
        shutil.rmtree(tmp)


def test_h3_total_minted_truncation_hides_phantom_supply():
    """
    HIGH H3 — int() truncation allows phantom 0.9 WEA to pass the cross-check.

    Repro: total_minted=19.9 in JSON, individual mints sum to 19.
           int(19.9) = 19. Cross-check: 19 == 19 → PASS.
           But if balances reflect 19.9 extra WEA, invariant LHS differs.
           The cross-check that should catch this is silently bypassed.
    Impact: 0.9 WEA of phantom supply can be injected into the ledger
            while the mints cross-check reports no inconsistency.
    Fix: Reject non-integer total_minted before any conversion.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10019}},
            escrows_active={},
            mints={
                "version": 1,
                "total_minted": 19.9,   # truncates to 19
                "mints": [{"trajectory": "T1", "slot": 1, "amount": 19}],
            },
        )
        code, out, err = _run(tmp)
        assert "TypeError" not in err and "AttributeError" not in err, \
            f"Unhandled exception:\n{err}"
        # After fix: non-integer total_minted must be rejected cleanly
        assert code == 1, f"Expected exit 1 for fractional total_minted, got {code}\nout: {out}"
        assert "FAIL" in out, f"Expected FAIL message:\n{out}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# HIGH — H4: Non-dict mint entries in mints array
# ──────────────────────────────────────────────────────────────────────────────

def test_h4_string_mint_entry_fails_cleanly():
    """
    HIGH H4 — mints array contains a string entry.

    Repro: "mints": ["not_a_dict"]
    Current behaviour: AttributeError on "not_a_dict".get('amount', 0).
    Fix: Validate each mint entry is a dict before calling .get().
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10020}},
            escrows_active={},
            mints={
                "version": 1,
                "total_minted": 20,
                "mints": ["not_a_dict"],
            },
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_h4_null_mint_entry_fails_cleanly():
    """
    HIGH H4 — mints array contains a null entry (Python None).

    Repro: "mints": [null]
    Current behaviour: AttributeError on None.get('amount', 0).
    Fix: Same as string case.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10020}},
            escrows_active={},
            mints={
                "version": 1,
                "total_minted": 20,
                "mints": [None],
            },
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "AttributeError" not in err, f"Unhandled AttributeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# HIGH — H5: String mint amounts
# ──────────────────────────────────────────────────────────────────────────────

def test_h5_string_mint_amount_fails_cleanly():
    """
    HIGH H5 — mint entry has string amount: "20" instead of 20.

    Repro: "mints": [{"amount": "20"}]
    Current behaviour: sum(["20"]) or sum([int, "20"]) raises TypeError.
    Impact: Script crashes without FAIL message.
    Fix: Validate each mint amount is int or float.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10020}},
            escrows_active={},
            mints={
                "version": 1,
                "total_minted": 20,
                "mints": [{"trajectory": "T1", "slot": 1, "amount": "20"}],
            },
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected exit 1, got {code}\nstdout: {out}\nstderr: {err}"
        assert "FAIL" in out, f"Expected FAIL in stdout:\nstdout: {out}\nstderr: {err}"
        assert "TypeError" not in err, f"Unhandled TypeError:\n{err}"
        assert "Traceback" not in err, f"Python traceback in stderr:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# MEDIUM — M1: Version field not validated
# ──────────────────────────────────────────────────────────────────────────────

def test_m1_missing_version_no_crash():
    """
    MEDIUM M1 — Missing version field is silently ignored.

    Current behaviour: script proceeds with PASS/FAIL based on sums alone.
    Risk: A ledger downgraded to an old schema (no version field) passes
          validation even if the format semantics have changed.
    This test documents the gap without asserting desired behavior.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"agents": {"a@test": {"balance": 10000}}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"active": {}}, f)
        code, out, err = _run(tmp)
        assert "TypeError" not in err and "AttributeError" not in err, \
            f"Unexpected crash with missing version field:\n{err}"
    finally:
        shutil.rmtree(tmp)


def test_m1_string_version_no_crash():
    """
    MEDIUM M1 — String version field (e.g. "7") is silently ignored.

    Current behaviour: version is never validated, script proceeds normally.
    Risk: Schema version bumps that change field semantics go undetected.
    """
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "ledger"), exist_ok=True)
        with open(os.path.join(tmp, "ledger", "balances.json"), "w") as f:
            json.dump({"version": "7", "agents": {"a@test": {"balance": 10000}}}, f)
        with open(os.path.join(tmp, "ledger", "escrows.json"), "w") as f:
            json.dump({"version": "5", "active": {}}, f)
        code, out, err = _run(tmp)
        assert "TypeError" not in err and "AttributeError" not in err, \
            f"Unexpected crash with string version:\n{err}"
    finally:
        shutil.rmtree(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# Existing behaviour — verified by red team
# ──────────────────────────────────────────────────────────────────────────────

def test_total_minted_disagrees_with_sum_of_mints():
    """
    Existing check — total_minted disagrees with sum of individual mints.
    The script already handles this; test documents coverage is correct.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10020}},
            escrows_active={},
            mints={
                "version": 1,
                "total_minted": 20,
                "mints": [
                    {"trajectory": "T1", "slot": 1, "amount": 15},
                ],
            },
        )
        code, out, err = _run(tmp)
        assert code == 1, f"Expected failure when sum(mints)=15 != total_minted=20"
        assert "Trajectory mints inconsistency" in out, \
            f"Expected 'Trajectory mints inconsistency' in output:\n{out}"
    finally:
        shutil.rmtree(tmp)


def test_unmatched_escrow_without_balance_deduction_fails():
    """
    Escrow exists but agent balance was never reduced.

    The invariant sum equation correctly catches this:
    sum(balances)=10000, sum(escrows)=500 → LHS=10500 != RHS=10000 → FAIL.
    """
    tmp = tempfile.mkdtemp()
    try:
        _make_ledger(tmp,
            balances_agents={"a@test": {"balance": 10000}},
            escrows_active={"1": {"author": "a@test", "amount": 500, "type": "standard",
                                  "created_at": "2026-01-01T00:00:00Z"}},
        )
        code, out, err = _run(tmp)
        assert code == 1, \
            f"Expected failure: sum=10500 != 10000 but got exit {code}\n{out}"
        assert "FAIL" in out
    finally:
        shutil.rmtree(tmp)
