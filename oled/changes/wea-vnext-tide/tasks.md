# Tasks: automatic Tide

Bound to Outcome 1.0 / Spec 1.0 / Design 1.1.
Status: implementation in progress; no live activation.

- [x] Fetch current main and create a dedicated worktree from bfb8a6d.
- [x] Retain accepted writer, batching, and human-decision boundaries.
- [x] Complete raw intake/lifecycle and batch replay design against existing executor rules.
- [x] Implement a new immutable source boundary and source-to-settlement replay.
- [x] Implement authenticated collection, cutoff, unresolved-case reporting, and durable batch evidence.
- [x] Replace the single-command Action with scheduled/manual Tide and one pending PR.
- [x] Rebuild the trusted guard and writer-universe checks; retire competing Actions.
- [ ] Prove two-task batches, author/control authority, funding-before-work, retry, restart, stale candidates, and collection races.
- [ ] Reconcile current BDD evidence, guides, activation procedure, and pilot checkpoints.
- [ ] Complete independent review and codex exec review before publication.
- [ ] Record the operator decision on first-stage funding publication time.
- [ ] Resolve organization Actions PR-creation policy with operator authorization.
- [ ] Prepare exact activation only after merged code and all required checks.

Previous metadata correction and newcomer cleanup are merged in PR 949.
Existing task-lifecycle source/payment requirements remain binding; its single-transaction writer direction is superseded here.
