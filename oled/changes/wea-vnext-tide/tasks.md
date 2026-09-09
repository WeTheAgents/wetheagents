# Tasks: automatic Tide

Bound to Outcome 1.0 / Spec 1.0 / Design 1.1.
Status: implementation reviewed and published as draft PR 950; operator decisions are recorded; browser policy setup, manual code merge, and live activation remain pending.

- [x] Fetch current main and create a dedicated worktree from bfb8a6d.
- [x] Retain accepted writer, batching, and human-decision boundaries.
- [x] Complete raw intake/lifecycle and batch replay design against existing executor rules.
- [x] Implement a new immutable source boundary and source-to-settlement replay.
- [x] Implement authenticated collection, cutoff, unresolved-case reporting, and durable batch evidence.
- [x] Replace the single-command Action with scheduled/manual Tide and one pending PR.
- [x] Rebuild the trusted guard and writer-universe checks; retire competing Actions.
- [x] Prove two-task batches, author/control authority, funding-before-work, retry, restart, stale candidates, and collection races in local tests.
- [x] Reconcile current BDD evidence, guides, activation procedure, and pilot checkpoints; retain explicit live-evidence gaps.
- [x] Complete independent review and post-publication codex exec review; fix until clean before requesting merge.
- [x] Record the operator decision on first-stage funding publication time: retain the current clock for now (2026-09-09).
- [x] Obtain organization Actions PR-creation authorization (2026-09-09).
- [ ] Apply the authorized policy through Chrome and verify the repository setting.
- [x] Obtain the one-time operator decision to replace the old writer with PR 950.
- [ ] Present the final reviewed head and current base for manual code merge.
- [ ] Prepare exact activation only after merged code and all required checks.

Previous metadata correction and newcomer cleanup are merged in PR 949.
Existing task-lifecycle source/payment requirements remain binding; its single-transaction writer direction is superseded here.
