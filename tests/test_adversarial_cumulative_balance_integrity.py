"""Adversarial tests for scripts/check_history_cumulative_balance_integrity.py (T1S41).

Seven attack scenarios that attempt to bypass or silently pass the cumulative
balance integrity checker:

1. Timestamp-reordering bypass — credit placed first in file (large amount),
   debit placed second but with an EARLIER `ts`; a file-order checker never
   sees the negative; the correct ts-sorted checker does.

2. Intermediate negative masked by correct final sum — multiple debits create
   a mid-replay negative balance that is later recovered; a final-sum-only
   checker silently passes; the correct checker fails on the step violation.

3. Zero-balance-then-debit edge — agent reaches exactly 0 (valid) then
   receives a further debit (-1); must FAIL, not silently pass.

4. Missing history file for active agent — balances.json shows agent earned
   WEA but history dir contains no events for that agent; final mismatch
   detected → FAIL.

5. Phantom agent in history — event credits an agent absent from
   balances.json; checker must not silently skip; must FAIL or report.

6. Escrow as separate pool bypass — a broken checker that never deducts
   escrow_create from the running balance would miss the negative and even
   match the final balance if escrow_return is also ignored; the correct
   checker sees the debit and fails.

7. Idempotent replay — calling run() twice on the same data returns the same
   exit code and violations; no state mutation between calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Conditional import — skip entire module if T1S41 is not yet merged.
# This allows `pytest tests/ -q` to exit 0 before the implementation lands.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from scripts.check_history_cumulative_balance_integrity import run as _run  # type: ignore[import]
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False
    _run = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason="check_history_cumulative_balance_integrity (T1S41) not yet merged",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run(root: Path):  # type: ignore[return]
    """Thin wrapper so tests call run() uniformly."""
    assert _run is not None
    return _run(root)


def _write_ledger(root: Path, balances: dict, events: list[dict], filename: str = "2026-01-01.jsonl") -> None:
    ledger = root / "ledger"
    ledger.mkdir(parents=True, exist_ok=True)
    (ledger / "balances.json").write_text(
        json.dumps({"version": 1, "agents": balances}), encoding="utf-8"
    )
    history = ledger / "history"
    history.mkdir(parents=True, exist_ok=True)
    (history / filename).write_text(
        "\n".join(json.dumps(e) for e in events), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Scenario 1: Timestamp-reordering bypass
# ---------------------------------------------------------------------------


def test_ts_reorder_bypass_file_order_hides_negative(tmp_path: Path) -> None:
    """File order: large credit first (ts=T2), debit second (ts=T1, EARLIER).

    A file-order checker sees credit before debit — balance never goes negative.
    The correct ts-sorted checker processes the debit first (ts=T1) and detects
    balance = -80 before the credit arrives at ts=T2.

    Attack intent: attacker places a large credit first in the history file to
    fool a checker that trusts file order over recorded timestamps.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 120}},
        events=[
            # Credit placed FIRST in file, but has a LATER ts
            {
                "type": "payment",
                "agent": "alice@claude",
                "amount": 200,
                "ts": "2026-01-01T02:00:00Z",
            },
            # Debit placed SECOND in file, but has an EARLIER ts — exposes the bypass
            {
                "type": "escrow_create",
                "agent": "alice@claude",
                "amount": 80,
                "issue": 1,
                "ts": "2026-01-01T01:00:00Z",
            },
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, (
        "checker must sort by ts and detect the -80 balance at T1 "
        "before the +200 credit arrives at T2"
    )
    assert result["status"] == "FAIL"
    violations = result["negative_violations"]
    assert len(violations) >= 1, "at least one negative violation expected"
    agents = {v["agent"] for v in violations}
    assert "alice@claude" in agents


# ---------------------------------------------------------------------------
# Scenario 2: Intermediate negative masked by correct final sum
# ---------------------------------------------------------------------------


def test_intermediate_negative_hidden_by_recovery(tmp_path: Path) -> None:
    """Multiple debits create mid-replay negative; correct final sum masks it.

    Sequence: earn 30, debit 40 (→ -10, VIOLATION), earn 20 (→ 10), debit 5
    (→ 5). Final = 5, matches balances.json.

    A final-sum-only checker silently passes because the terminal balance is
    correct. The correct checker must catch the -10 intermediate violation.
    """
    _write_ledger(
        tmp_path,
        balances={"bob@codex": {"balance": 5}},
        events=[
            {"type": "payment",      "agent": "bob@codex", "amount": 30,  "ts": "2026-01-01T01:00:00Z"},
            {"type": "escrow_create","agent": "bob@codex", "amount": 40, "issue": 2, "ts": "2026-01-01T02:00:00Z"},
            # balance is -10 here — VIOLATION even though it recovers
            {"type": "payment",      "agent": "bob@codex", "amount": 20,  "ts": "2026-01-01T03:00:00Z"},
            {"type": "escrow_create","agent": "bob@codex", "amount": 5,  "issue": 3, "ts": "2026-01-01T04:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "checker must FAIL on intermediate negative, not just final sum"
    assert result["status"] == "FAIL"
    violations = result["negative_violations"]
    assert any(v["agent"] == "bob@codex" for v in violations)
    # The violation balance must be at most -10
    min_bal = min(v["balance"] for v in violations if v["agent"] == "bob@codex")
    assert min_bal <= -10


# ---------------------------------------------------------------------------
# Scenario 3: Zero-balance edge — debit after exactly-zero balance
# ---------------------------------------------------------------------------


def test_zero_balance_then_debit_fails(tmp_path: Path) -> None:
    """Agent reaches exactly 0 (valid), then receives a further debit (-1).

    Reaching zero must not be flagged as a violation. But the subsequent
    debit pushes the balance to -1, which must cause FAIL.
    """
    _write_ledger(
        tmp_path,
        balances={"carol@gemini": {"balance": 9}},
        events=[
            {"type": "payment",       "agent": "carol@gemini", "amount": 10, "ts": "2026-01-01T01:00:00Z"},
            # Debit to exactly 0 — legal
            {"type": "escrow_create", "agent": "carol@gemini", "amount": 10, "issue": 4, "ts": "2026-01-01T02:00:00Z"},
            # One more debit — pushes to -1, must FAIL
            {"type": "escrow_create", "agent": "carol@gemini", "amount": 1,  "issue": 5, "ts": "2026-01-01T03:00:00Z"},
            # Recovery payment so final = 9 matches stored
            {"type": "escrow_return", "agent": "carol@gemini", "amount": 10, "issue": 4, "ts": "2026-01-01T04:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "balance of -1 after zero must trigger FAIL, not silent pass"
    assert result["status"] == "FAIL"
    violations = result["negative_violations"]
    assert any(v["agent"] == "carol@gemini" for v in violations)
    # Confirm the exact violation is -1 (not a false alarm at zero)
    negative_bals = [v["balance"] for v in violations if v["agent"] == "carol@gemini"]
    assert any(b == -1 for b in negative_bals), f"expected -1 violation, got: {negative_bals}"


def test_exactly_zero_balance_passes(tmp_path: Path) -> None:
    """Agent reaches exactly 0 — must PASS (zero is valid, spec says < 0 triggers fail)."""
    _write_ledger(
        tmp_path,
        balances={"dave@cursor": {"balance": 0}},
        events=[
            {"type": "payment",       "agent": "dave@cursor", "amount": 50, "ts": "2026-01-01T01:00:00Z"},
            {"type": "escrow_create", "agent": "dave@cursor", "amount": 50, "issue": 6, "ts": "2026-01-01T02:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is True, "exactly-zero balance must PASS — only < 0 is a violation"
    assert result["status"] == "PASS"
    assert result["negative_violations"] == []


# ---------------------------------------------------------------------------
# Scenario 4: Missing history file for active agent
# ---------------------------------------------------------------------------


def test_missing_history_for_active_agent_fails(tmp_path: Path) -> None:
    """balances.json shows agent earned 100 WEA; history has zero events for it.

    The history directory exists (and has events for another agent), but the
    active agent is entirely absent from history. Replay computes 0 for the
    agent, but stored = 100 — final mismatch detected → FAIL.

    Attack intent: history file for the relevant date was deleted or never
    written; a lazy checker would skip missing files without detecting drift.
    """
    ledger = tmp_path / "ledger"
    ledger.mkdir(parents=True)
    # balances.json claims active_agent has 100 WEA
    (ledger / "balances.json").write_text(
        json.dumps({
            "version": 1,
            "agents": {
                "known@claude": {"balance": 50},
                "active_agent@codex": {"balance": 100},  # claims 100 WEA
            },
        }),
        encoding="utf-8",
    )
    history = ledger / "history"
    history.mkdir()
    # History file only contains events for known@claude — active_agent absent
    (history / "2026-01-01.jsonl").write_text(
        json.dumps({"type": "payment", "agent": "known@claude", "amount": 50, "ts": "2026-01-01T01:00:00Z"}),
        encoding="utf-8",
    )

    result, passed = run(tmp_path)

    assert passed is False, "missing history for active agent must cause final-balance FAIL"
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "active_agent@codex" in mismatches, (
        f"active_agent@codex must appear in mismatches; got: {list(mismatches)}"
    )
    m = mismatches["active_agent@codex"]
    assert m["stored"] == 100
    assert m["computed"] == 0


# ---------------------------------------------------------------------------
# Scenario 5: Phantom agent in history
# ---------------------------------------------------------------------------


def test_phantom_agent_in_history_fails(tmp_path: Path) -> None:
    """History credits 'phantom@codex' which is absent from balances.json.

    Checker must not silently skip phantom agents. A phantom with non-zero
    computed balance must produce a final-balance mismatch → FAIL.

    Attack intent: attacker injects events crediting an unregistered agent to
    siphon WEA off-ledger; a naive checker that only validates known agents
    would silently accept these credits.
    """
    _write_ledger(
        tmp_path,
        balances={"alice@claude": {"balance": 50}},
        events=[
            {"type": "payment", "agent": "alice@claude",  "amount": 50,  "ts": "2026-01-01T01:00:00Z"},
            # phantom@codex not in balances.json — must not be silently skipped
            {"type": "payment", "agent": "phantom@codex", "amount": 99,  "ts": "2026-01-01T02:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, "phantom agent with non-zero balance must trigger FAIL"
    assert result["status"] == "FAIL"
    mismatches = {m["agent"]: m for m in result["final_mismatches"]}
    assert "phantom@codex" in mismatches, (
        "phantom agent must appear in mismatches — not silently ignored"
    )
    m = mismatches["phantom@codex"]
    assert m["computed"] == 99
    # stored is None or 0 (agent absent from balances.json)
    assert m["stored"] in (None, 0)


# ---------------------------------------------------------------------------
# Scenario 6: Escrow treated as separate pool (bypass attempt)
# ---------------------------------------------------------------------------


def test_escrow_as_separate_pool_bypass_detected(tmp_path: Path) -> None:
    """Escrow-pool bypass: a broken checker that ignores escrow debit/credit
    would see running balance = 100 throughout and match the stored value.
    The correct checker deducts the escrow_create (-150) and detects a
    negative balance of -50 before the escrow_return recovers it.

    Attack design (for broken checker):
      - payment +100 → balance 100
      - escrow_create 150: BROKEN checker keeps balance at 100 (no deduct)
      - escrow_return 150: BROKEN checker ignores return (no credit)
      - final computed = 100 = stored → PASS (silent failure)

    Correct checker:
      - payment +100 → 100
      - escrow_create 150 → -50 (VIOLATION!)
      - escrow_return 150 → 100
      - FAIL ✓
    """
    _write_ledger(
        tmp_path,
        balances={"eve@claude": {"balance": 100}},
        events=[
            {"type": "payment",       "agent": "eve@claude", "amount": 100, "ts": "2026-01-01T01:00:00Z"},
            # Escrow exceeds balance — correct checker detects -50
            {"type": "escrow_create", "agent": "eve@claude", "amount": 150, "issue": 7, "ts": "2026-01-01T02:00:00Z"},
            # Return restores balance — broken checker's final sum coincidentally matches
            {"type": "escrow_return", "agent": "eve@claude", "amount": 150, "issue": 7, "ts": "2026-01-01T03:00:00Z"},
        ],
    )

    result, passed = run(tmp_path)

    assert passed is False, (
        "escrow_create must deduct from running balance; "
        "a -50 intermediate violation must be caught even though final balance matches"
    )
    assert result["status"] == "FAIL"
    violations = result["negative_violations"]
    assert any(v["agent"] == "eve@claude" for v in violations), (
        "eve@claude must appear in negative_violations"
    )
    # Confirm the violation balance is at most -50
    eve_bals = [v["balance"] for v in violations if v["agent"] == "eve@claude"]
    assert any(b <= -50 for b in eve_bals), f"expected ≤ -50 violation, got: {eve_bals}"


# ---------------------------------------------------------------------------
# Scenario 7: Idempotent replay
# ---------------------------------------------------------------------------


def test_idempotent_replay_same_result_twice(tmp_path: Path) -> None:
    """Calling run() twice on the same data returns identical results.

    Verifies no global state, file mutation, or side-effect accumulation
    between invocations. Determinism is required for CI reliability.
    """
    _write_ledger(
        tmp_path,
        balances={
            "alpha@claude": {"balance": 70},
            "beta@codex":   {"balance": 30},
        },
        events=[
            {"type": "payment",       "agent": "alpha@claude", "amount": 100, "ts": "2026-01-01T01:00:00Z"},
            {"type": "escrow_create", "agent": "alpha@claude", "amount": 30,  "issue": 8, "ts": "2026-01-01T02:00:00Z"},
            {"type": "payment",       "agent": "beta@codex",   "amount": 30,  "ts": "2026-01-01T03:00:00Z"},
        ],
    )

    result1, passed1 = run(tmp_path)
    result2, passed2 = run(tmp_path)

    assert passed1 == passed2, "idempotency: exit code must be the same on both runs"
    assert result1["status"] == result2["status"], "idempotency: status must be stable"
    assert len(result1["negative_violations"]) == len(result2["negative_violations"]), (
        "idempotency: violation count must not change between runs"
    )
    assert len(result1["final_mismatches"]) == len(result2["final_mismatches"]), (
        "idempotency: mismatch count must not change between runs"
    )
    assert result1["events_replayed"] == result2["events_replayed"], (
        "idempotency: events_replayed must be stable"
    )


def test_idempotent_replay_failing_case_also_stable(tmp_path: Path) -> None:
    """run() on a FAILING case also returns the same result twice.

    Ensures idempotency holds for both PASS and FAIL outcomes.
    """
    _write_ledger(
        tmp_path,
        balances={"frank@claude": {"balance": 0}},
        events=[
            {"type": "payment",       "agent": "frank@claude", "amount": 10, "ts": "2026-01-01T01:00:00Z"},
            {"type": "escrow_create", "agent": "frank@claude", "amount": 20, "issue": 9, "ts": "2026-01-01T02:00:00Z"},
            {"type": "payment",       "agent": "frank@claude", "amount": 10, "ts": "2026-01-01T03:00:00Z"},
        ],
    )

    result1, passed1 = run(tmp_path)
    result2, passed2 = run(tmp_path)

    assert passed1 is False, "this case must FAIL (negative balance mid-history)"
    assert passed1 == passed2, "FAIL result must be stable across runs"
    assert result1["status"] == result2["status"] == "FAIL"
    assert len(result1["negative_violations"]) == len(result2["negative_violations"])
