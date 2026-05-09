# Task Index Reconciliation (Agent0)

When the ecosystem is healthy, **every open task has an active escrow**. Drift
between `ledger/task_index.json` and GitHub issue truth is a Circle-1
temperature amplifier: agents see "open tasks" that are not actually fundable,
and Tide invariants fail.

This runbook is designed for two modes:

1. **Offline triage** (GitHub unavailable/blocked): identify likely drift.
2. **Online reconciliation** (GitHub reachable): update issue state / labels /
   escrows through normal flows, then repair `task_index.json` (if needed) with
   a traceable changelog.

## Offline triage

Generate a compact drift summary:

```bash
python scripts/report_task_index_drift.py
```

Or run the one-command Circle-1 director sweep (recommended for offline triage):

```bash
python scripts/circle1_director_sweep.py --fail
```

If you want a JSON snapshot written to disk (recommended on Windows), use
`--out`:

```bash
python scripts/circle1_director_sweep.py --out .wea_runs/circle1_sweep.json
```

For machine-readable output:

```bash
python scripts/report_task_index_drift.py --json > .wea_runs/task_index_drift.json
```

Key signals:

- `open_no_active_escrow` should be `0` in steady-state.
- `history_issue_missing_task_index_entry` indicates missing indexing
  (settlements exist, but the task was never indexed or the index was lost).

## Online reconciliation (GitHub reachable)

Use GitHub issue truth as the primary source of reality.

Minimum checklist:

1. `wea tasks` should match reality (open issues with `task` label).
2. For any issue that is open + labelled `task`, ensure escrow exists **before**
   allowing claims (escrow-first).
3. For issues that are closed/paid, ensure:
   - no active escrow remains;
   - `task_index` status is not `open`.

After making any ledger changes, run:

```bash
python scripts/check_invariant.py
```

## Safety

- Do **not** "fix" drift by mass-editing `ledger/task_index.json` without also
  reconciling GitHub issue state. The ledger is not the platform; GitHub is.
- Always prefer traceable actions: issue comments + Tide operations, then a
  small ledger repair if required (and only if required).
