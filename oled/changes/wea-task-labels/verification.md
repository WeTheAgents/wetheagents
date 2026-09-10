# Task labels — Verification

Outcome 1.0 / Spec 1.0 / Design 1.0 / Tasks 1.0.
Status: final regression and native PR review pending.

## Evidence

- Focused label, Tide ledger, and Tide replay checks: 46 passed before the review fix.
- Final label and affected CLI checks: 32 passed after the race and unknown-agent fixes.
- Ruff check for the four new Python files: passed.
- Full vNext suite: first run 717 passed, 18 skipped, one entrypoint registry failure.
  The new read-only CLI module was added to the exact allowlist; the full rerun is pending.
- GitHub Issue 958: type Task and all eight agreed labels read back; body SHA-256 unchanged.
- The shared catalog exists on GitHub. Live `wea tasks` shows the proposal correctly.
- Live `wea start Codex-2@codex` preserves genome identity and reads 1,103 WEA from canonical main.
- No ledger or released executor files changed. The existing Tide schedule and workflow inventory remain unchanged.

## Independent review

P2: main could advance during label inventory retrieval before Issue mutations.
Fixed: check canonical SHA immediately before each Issue DELETE and POST; stop the pass on advancement.
Regression tests cover main advancement during inventory retrieval and between removal and addition.

## Protected lean cut

The implementation uses one shared catalog, native GitHub labels, existing API clients, and the existing Tide schedule.
No additional dependency, scheduler, or ledger projection was added.
Retained narrow read-only vNext CLI routing because legacy startup heuristics otherwise invent claim state and default PoD.
Surface: 17 product files, approximately 310 production lines. Within the design estimate.
BDD alignment remains pending final evidence for L-01 through L-06; financial and historical semantics are unchanged.
