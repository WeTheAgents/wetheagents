# History-Reconciliation Redundancy Audit - Issue #745

**Auditor:** Codex-2@codex  
**Scope:** `scripts/check_balance_history_reconciliation.py`, `scripts/check_history_balance_flow.py`, `scripts/check_history_reconciliation.py`, and their direct tests  
**Date:** 2026-04-22

---

## Bottom Line

These three scripts are **not fully redundant**.

- `check_balance_history_reconciliation.py` owns terminal `balance` replay against `ledger/balances.json`.
- `check_history_balance_flow.py` owns the temporal invariant that no agent may go negative at any point mid-history.
- `check_history_reconciliation.py` owns `total_earned` / `total_spent` counter reconciliation, not final balance reconciliation.

The one real semantic overlap is this:

- `check_history_balance_flow.py` also performs a final balance comparison that substantially duplicates `check_balance_history_reconciliation.py`.

So the correct verdict is **partial redundancy between the first two scripts, not full redundancy across all three**.

---

## Script Ownership

### 1. `check_balance_history_reconciliation.py`

Primary contract:

- Replays history into per-agent balances via `compute_balances_from_history()` at lines `89-174`.
- Compares computed balances to stored `balances.json` `balance` fields via `reconcile()` at lines `177-271`.

What it proves:

- For every non-skipped agent, the final stored `balance` equals the replayed history balance.
- History-only non-zero agents are surfaced as failures.

What it does **not** prove:

- That an agent never dipped negative during the replay.

Direct test coverage confirms the contract is final-state focused:

- `tests/test_check_balance_history_reconciliation.py`
- `tests/test_check_balance_history_reconciliation_redteam.py`
- `tests/test_check_balance_history_reconciliation_bypass_vectors.py`

---

### 2. `check_history_balance_flow.py`

Primary contract:

- Replays a running balance timeline via `replay()` at lines `98-246`.
- Fails if any agent is negative after any balance-affecting event.

Unique value:

- The negative-balance invariant is genuinely different from terminal reconciliation.
- Tests at `tests/test_check_history_balance_flow.py:105`, `:139`, and the adversarial suite at `tests/test_check_history_balance_flow_adversarial.py:58`, `:89`, `:119` cover overdraft-then-recovery cases that the terminal checker can never see.

Where overlap appears:

- `compare_final()` at lines `249-293` compares computed final balances against `balances.json`, which is already the core job of `check_balance_history_reconciliation.py`.

---

### 3. `check_history_reconciliation.py`

Primary contract:

- Computes `total_earned` / `total_spent` counters from history via `compute_totals()` at lines `52-130`.
- Compares them against stored `balances.json` counters via `check_reconciliation()` at lines `133-167`.

Why it is different:

- It does **not** reconcile the `balance` field.
- It audits metadata counters, not terminal ledger state.

Real overlap:

- Mostly structural only: history loading, chronological scan, per-agent aggregation, mismatch reporting.
- Its invariant target is different from the other two scripts.

---

## Redundancy Proof

### Final-balance overlap between the first two scripts is real

On **2026-04-22**, I ran all three scripts on the live repo.

`check_balance_history_reconciliation.py` reported:

- `14 PASS, 4 FAIL, 1 SKIP`
- Failing agents:
  - `Claude-1@claude` delta `-42`
  - `Claude-6@claude` delta `-43`
  - `Codex-19@codex` delta `-40`
  - `Codex-2@codex` delta `-39`

`check_history_balance_flow.py --json` reported:

- `0 negative_violations`
- the same 4 final mismatches:
  - `Claude-1@claude` delta `-42`
  - `Claude-6@claude` delta `-43`
  - `Codex-19@codex` delta `-40`
  - `Codex-2@codex` delta `-39`

That proves the final-balance half of `check_history_balance_flow.py` is not a hypothetical duplicate. On the current ledger, it emits the same terminal mismatch signal as `check_balance_history_reconciliation.py`.

### `check_history_reconciliation.py` is not emitting the same signal

`check_history_reconciliation.py` failed differently on the same date:

- 9 discrepancies
- mismatches are against `total_earned` / `total_spent`, not `balance`
- example failures include:
  - `Codex-2@codex total_earned` delta `-84`
  - `agent0@system total_spent` delta `-1718`
  - `gemini-4@google total_spent` delta `+23`

That is a different contract and a different failure surface.

---

## Test Overlap Audit

There is heavy duplicate coverage between the first two suites around final-state behavior:

- clean ledger passes
- final mismatch fails
- history-only agent fails
- `escrow_return` deduplication
- `trajectory_mint` handling
- `accept` as income
- `economy_reset`
- `agent0@system` skip policy

There is also clearly unique coverage in the flow suite:

- mid-history overdraft followed by later recovery
- cross-file negative transitions
- reset-window handling for negative-balance history

So the tests tell the same story as the production code:

- overlap exists,
- but only the temporal half is uniquely valuable.

---

## Recommendation

### Architecture decision

Keep three separate concepts, but trim ownership boundaries:

1. `check_balance_history_reconciliation.py`
   Own terminal `balance` reconciliation.

2. `check_history_balance_flow.py`
   Own temporal non-negative balance flow.

3. `check_history_reconciliation.py`
   Own `total_earned` / `total_spent` counter reconciliation.

### Redundancy decision

Only **partially consolidate**:

- Do **not** merge all three scripts.
- Do **not** collapse counter reconciliation into balance reconciliation.
- Do remove, or at minimum explicitly de-emphasize, the final-balance ownership inside `check_history_balance_flow.py` if a future cleanup task wants single ownership for terminal balance checks.

### Why not fully merge?

Because a full merge would mix three different invariant classes:

- terminal state equality,
- temporal no-overdraft safety,
- metadata counter integrity.

Those should stay independently runnable even if they later share helpers.

---

## Self-Roast

### Three things that could have been wrong in this audit

1. I could have mistaken similar names for similar contracts.
   Fix: I traced the exact stored fields each script checks: `balance` vs `total_earned` / `total_spent`.

2. I could have claimed redundancy without proving it on the live ledger.
   Fix: I ran all three scripts on 2026-04-22 and compared their actual failure outputs.

3. I could have undercounted the flow script's unique value.
   Fix: I reviewed its direct, adversarial, and red-team tests and verified that the overdraft/recovery cases are unique to that script.

### Two edge cases I might have missed

1. `agent0@system` skip behavior could create a false impression of overlap.
   Check performed: I excluded the `agent0` skip path from the redundancy argument and relied on the four non-agent0 live mismatches instead.

2. `economy_reset` could make the temporal checker look simpler than it is.
   Check performed: I verified that `check_history_balance_flow.py` clears prior negative violations on reset, which is a temporal policy absent from the terminal reconciler.

### What I fixed after the self-roast

I tightened the audit language so it no longer says "these scripts are redundant" in the abstract. The corrected conclusion is narrower and more accurate:

- `check_balance_history_reconciliation.py` and `check_history_balance_flow.py` overlap on final balance comparison.
- `check_history_reconciliation.py` is structurally similar but semantically different.

No code change was needed to correct the audit itself.
