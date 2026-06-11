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
wea circle1 sweep --fail
```

If you want a JSON snapshot written to disk (recommended on Windows), use `--out`:

```bash
wea circle1 sweep --out .wea_runs/circle1_sweep.json
```

This also updates `.wea_runs/circle1_sweep_latest.json` for quick access.

### Prepare an online reconciliation queue (offline-only)

When GitHub is blocked, generate a deterministic queue file for the next
GitHub-connected reconciliation session:

```bash
python scripts/build_task_index_reconciliation_queue.py --out .wea_runs/task_index_reconciliation_queue.json
```

Or via the repo-local CLI:

```bash
wea circle1 queue --out .wea_runs/task_index_reconciliation_queue.json
```

This file includes suggested actions per issue, but **must** be reconciled
against GitHub issue truth before any changes are made.

### If `wea circle1` is missing in your shell

Some environments may have an older `wea` installed on `PATH` (or importing
`wea_cli` from a different worktree). In that case, run the repo-local CLI
explicitly:

```powershell
.\scripts\wea_local.ps1 circle1 sweep --out .wea_runs/circle1_sweep.json
```

Queue generation is also available via the wrapper:

```powershell
.\scripts\wea_local.ps1 circle1 queue --out .wea_runs/task_index_reconciliation_queue.json
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
