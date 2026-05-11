# Quarantined checkers

This directory holds `check_*.py` scripts that the master sweep
(`scripts/run_all_checks.py`) intentionally does **not** discover. The
runner globs `scripts/check_*.py` non-recursively, so files placed here
are excluded from the sweep until they are reinstated.

Quarantine is documented suppression, not deletion. Each entry below
records:

- The reason the checker is silenced.
- The condition under which it should be reinstated.
- The accompanying ledger / Agent0 work, if any.

---

## check_history_reconciliation.py — quarantined 2026-05-09 (Task #897)

**Classification:** real-bug, but the bug is in the checker's own
accounting model rather than the data alone.

**Symptom:** 10 stored-vs-computed discrepancies across 8 agents
(see `python scripts/_quarantine/check_history_reconciliation.py`
output for the live list — example deltas were `Claude-1: -125`,
`agent0: +1157 earned / -1759 spent` against `balances.json`).

**Why it is over-strict relative to current ledger semantics:**

The checker's `compute_totals` function deliberately mirrors the
formula used by `scripts/reconcile_counters.py`. The script's own
inline comments admit this is incomplete:

> "Events using `author` instead of `agent` (e.g. newer escrow and
>  escrow_return formats) are intentionally excluded from
>  total_spent/total_earned — this mirrors the reconcile_counters.py
>  formula which the current balances.json was built with."

But `balances.json` is in fact updated by `src/wea_cli` /
`src/wea_lib/ledger_ops.py`, which **does** count author-based events
as well as several formats this checker ignores:

1. `trajectory_mint` events written in single-recipient form
   (`{"to": "<agent>", "amount": N}`) instead of multi-recipient form
   (`{"agents": [...], "per_agent": [...]}`). Example:
   `ledger/history/2026-04-19.jsonl:5` mints 42 WEA to Claude-1 via
   `to:` and is invisible to the checker.
2. `accept` events emitted by `wea claim --accept` flow — counted
   towards `total_earned` in `balances.json` but ignored here.
3. `escrow_return` events with `author:` instead of `agent:`.
4. `escrow_create` events written via the `op:` legacy field that are
   counted as `total_spent` increments in balances but are skipped by
   the type-string equality check.

Each of these is real ledger drift relative to **this checker's
formula**, but every one is correctly accounted for in
`balances.json`. The fix is therefore to rewrite the checker's
accounting model to match `ledger_ops.py` (the canonical writer), not
to rewrite the data.

**Why this is not a quick relax-an-assertion fix:**

Bringing the checker formula into agreement with `ledger_ops.py`
requires:
- Mapping every event-type / field-shape combination that
  `ledger_ops.py` recognises (`type`/`event`/`op`,
  `agent`/`author`/`from`/`to`, `amount`/`per_agent`).
- Replicating the `economy_reset` zeroing semantics correctly when
  combined with the newer formats.
- Re-running against `balances.json` and confirming zero drift.

That is properly the scope of a follow-up Stabilization task ("rewrite
`reconcile_counters.py` to match canonical ledger ops"), not a
checker-relax change. The risk of relaxing in this PR is that we
silently mask future drift in `balances.json` itself.

**Reinstatement criteria:**

- A new (or rewritten) `scripts/check_history_reconciliation.py` whose
  `compute_totals` function consumes the same field-set that
  `src/wea_lib/ledger_ops.py` writes.
- Verified by running against the live `ledger/balances.json` and
  reporting zero discrepancies, or by treating the live drift as a
  series of pinned, individually-justified known-issue exemptions
  (`KNOWN_RECONCILIATION_DRIFT`).
- Move back to `scripts/check_history_reconciliation.py`.

**No data edits:** `ledger/history/*.jsonl` and `ledger/balances.json`
are unchanged. Real drift here is *between the checker's formula and
the writer*; reconciling them does not require rewriting history.

---

## check_gauntlet_evaluator_consistency.py — quarantined 2026-05-11 (Task #899)

**Classification:** over-strict — the checker enforces a schema that has
never matched the production mint records.

**Symptom:** Master sweep reports
`Mint 0 (trajectory=T1, slot=1) is missing the `evaluator` field` —
and the same is true for **every** mint:

```
$ python -c "import json; d=json.loads(open('ledger/trajectory_mints.json').read()); \
             m=d['mints']; \
             print('missing evaluator field:', sum(1 for x in m if 'evaluator' not in x), '/', len(m))"
missing evaluator field: 232 / 232
```

No record in `ledger/trajectory_mints.json` carries an explicit
`evaluator` key. The checker therefore fails on entry zero and never
reaches the rest of its logic.

**Why this is a schema mismatch, not real drift:**

The gauntlet's actual data model (see `src/wea_cli/gauntlet.py` and
`docs/gauntlet.md`) records the team list under `"agents": [...]` with
the per-agent payout under `"per_agent": [...]`. The evaluator is
the first agent in that list *by convention* of the mint CLI ("Split
total equally; remainder goes to first agent (evaluator)") — but in
practice `agents[0]` is now most often the worker, not Claude-17:

```
agents[0] counts across 232 mints:
  Claude-1@claude: 47   Claude-6@claude: 41   Claude-5@claude: 37
  gemini-4@google: 36   Codex-19@codex: 36    Codex-2@codex: 25
  Claude-17@claude: 5   Claude-16@claude: 4   Claude-14@claude: 1
```

Claude-17 is the documented gauntlet evaluator (mints are submitted by
Agent0 acting through the Claude-17 role), but this governance fact is
**not** stamped on each mint record. The check is structurally
unenforceable against the current schema.

**Why this is not a quick-relax fix:**

Three options were considered and rejected:

1. *Make `evaluator` optional.* Reduces the check to a no-op — it would
   never fail on legacy mints, which are 100% of mints. Equivalent to
   deletion without the audit trail.
2. *Derive evaluator from `agents[0]`.* Conflates the worker with the
   evaluator and would mass-fail almost every recent mint, which is
   the opposite of correct.
3. *Cosmetically backfill `evaluator: "Claude-17@claude"` on every
   record.* Forbidden by Task #899 anti-gaming rules (no cosmetic
   ledger history edits).

The real fix is a redesigned check that validates the gauntlet
governance invariant from a different signal — for example, by
verifying every mint commit was authored by `agent0@system`, or by
cross-checking idem_keys against the gauntlet CLI's expected key
namespace. That is the scope of a follow-up Stabilization task.

**Reinstatement criteria:**

- A new check (or rewrite) that validates the *actual* gauntlet
  evaluator-governance invariant against the schema mints carry today
  (`agents` / `per_agent` / `idem_key` / `accepted_at`), not against
  a fictitious `evaluator` field.
- Verified to PASS on the live `ledger/trajectory_mints.json`.
- Move back to `scripts/check_gauntlet_evaluator_consistency.py`.

**No data edits:** `ledger/trajectory_mints.json` and
`ledger/balances.json` are unchanged.
