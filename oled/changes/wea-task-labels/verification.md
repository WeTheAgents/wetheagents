# Task labels — Verification

Outcome 1.0 / Spec 1.0 / Design 1.0 / Tasks 1.0.
Decision: Ready for operator review. Installation is pending the explicit manual writer-upgrade decision; this is not an all-green automatic merge.

## Evidence

- Focused label, Tide ledger, and Tide replay checks: 46 passed before the review fix.
- Final label and affected CLI checks: 32 passed after the race and unknown-agent fixes.
- Latest affected label, CLI, and runtime-boundary checks: 44 passed after the remote-listing correction.
- Ruff check for the four new Python files: passed.
- Full vNext suite: first run 717 passed, 18 skipped, one entrypoint registry failure.
  The new read-only CLI module was added to the exact allowlist. Full rerun: 720 passed, 18 pre-existing skips in 252.02 seconds.
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
Surface: 19 product files including MAP.md and the durable runlog, approximately 315 production lines. The extra map entry is required by doc-sync.
BDD alignment: 100% for L-01 through L-06. Financial and historical semantics are unchanged.

## Scenario evidence

- L-01: `test_current_stage_mechanics` covers all six payment labels, equal/variable rewards, and current-stage replacement.
- L-02: `test_open_deadlines_pauses_and_closed_issue`, `test_terminal_task_and_role_escrow`, and `test_main_advance_and_proposals_do_not_open_work`.
- L-03: `test_sync_preserves_topics_audience_and_retries_without_ledger_effects` and exact Issue 958 readback.
- L-04: retry/no-op, partial-removal recovery, pending/no-op writer integration, and both main-advance race tests.
- L-05: CLI unknown/conflict, proposal discovery, canonical balance/genome tests, live CLI reads, and the exact entrypoint allowlist.
- L-06: the proposal form parses, its payment choices equal the catalog, and type/default labels match the published repository metadata.

## Native PR review and installation boundary

- Bundled Codex 0.153.4 reviewed the whole PR and repeated the full vNext suite: 720 passed, 18 skipped.
- P2: `wea tasks` outside a checkout failed before its remote GitHub read. Fixed with the previous remote-listing fallback and a regression test.
- Final native review of `0a77662..2e473a2`: no actionable defects; 20 focused tests and doc-sync passed. No global Codex configuration or installation changed.
- GitHub doc-sync found the new guide absent from MAP.md. The map is corrected; `python scripts/check_doc_sync.py` passes locally.
- The trusted main guard rejects `.github/workflows/tide.yml` as an existing writer-boundary change.
  This is expected for this implementation, which also changes the pinned Tide entrypoint.
  The guard and its allowlist are not relaxed. Earlier installation exceptions are not reused.
  PR #959 needs an explicit operator installation decision bound to its final reviewed head and current main.
  A regular all-green merge is not claimed. The private manual writer-upgrade decision is separate from ledger replay validation.
