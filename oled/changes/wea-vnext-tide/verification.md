# Verification: automatic Tide

Decision: NOT READY for live activation. Local implementation is in final review.
Contract: Outcome 1.0 / Spec 1.0 / Design 1.1.
Base: bfb8a6d91d4e3da6dc9c2935814e6b5fdc5c843d.

## Scope and executable evidence

The new source boundary is executor `0.9.0` / ruleset `0.9`.
Historical facade pins and released executor bytes are unchanged.
The existing 70-scenario registry remains scoped to its stored references;
it does not silently become evidence for the new raw-source adapter.
The accepted Tide delta has the following direct tests in `tests/vnext/`:

| Contract | Exact proving surface |
| --- | --- |
| T-01 | `test_tide_collection.py`: complete reads, fixed cutoff, immutable edit IDs, deleted history, metadata changes, substituted content, required artifact API failure |
| T-01 / T-06 | `test_tide_ledger.py::test_candidate_cannot_drop_previously_tracked_issues` |
| T-02 | `test_tide_replay.py::test_one_batch_funds_two_tasks_and_rejects_a_third_overspend` |
| T-02 | `test_tide_replay.py::test_work_acceptance_derives_payment_and_retains_raw_comment` |
| T-02 / T-05 | `test_tide_replay.py::test_raw_intake_funds_once_and_replays_from_json`, `test_exact_work_event_retry_is_idempotent_inside_the_executor` |
| T-03 | `test_tide_replay.py`: unauthorized Triage copies, cross-Issue Work, pre-funding predecessors, exact edit reconciliation, missing intermediate Issue edits |
| T-03 | `test_tide_replay.py::test_common_control_is_confirmed_from_a_real_authorized_source` |
| T-04 | `test_tide_replay.py::test_pre_funding_work_cannot_be_laundered_by_a_later_tide` |
| T-05 | `test_tide_ledger.py`: no-op, canonical retry, push-before-PR recovery, paginated PR discovery, stale-status invalidation |
| T-06 | `test_tide_ledger.py`: Git candidate replay, unearned balanced transfer, mixed code and ledger paths, wrong Actions provenance |
| T-06 | `test_block9_github_native.py`: trusted workflow and writer-boundary inventory; historical Block 9 cases retain their original provenance |
| T-07 | `test_tide_activation.py`: exact imported balances, no reallocation, stale predecessor, source identity, Issue, edit, and hash rejection |
| Readback | `test_tide_ledger.py::test_read_only_cli_reports_canonical_balance` |

New Tide tests are explicit `0.9.0` evidence. Old closure tests alone do not prove this integration.
Synthetic GitHub tests do not prove live token permissions or required branch enforcement.

## Checks and review

- Targeted Tide, runtime-boundary, and packaging suite: 55 passed before the final review regressions.
- Full vNext suite: **667 passed, 18 skipped** after correcting the canonical CLI fixture and packaging/boundary tests.
- Trusted GitHub boundary suite after final guard hardening: **44 passed**.
- Documentation and retired-claim tests: **22 passed**.
- Direct CLI template invocation without PYTHONPATH and claim tests: **4 passed**.
- Codex review ran the broader suite: 4950 passed, 18 skipped, 11 xfailed, three failures. All three failure paths were then corrected and passed targeted checks; a fresh full-repository result is not claimed.
- Ruff passes on new Tide code, new closure, CLI readback, and Tide/packaging tests.
- Whole modified-file Ruff includes pre-existing debt in legacy CLI and audit scripts; it is not claimed passing.
- Documentation sync, legacy invariant (19025 WEA, zero active escrow), and ledger schema passed.
- Read-only CLI reports canonical origin/main inactive at the exact base above.
- Independent review findings about source scope, mutable metadata, raw authority, ordering, and recovery have been addressed with regressions.
- `codex exec review --base origin/main` is running; publication review is not complete.
- Every new executor manifest entry was checked against staged Git blob bytes; all matched. New closure files use LF for consistent Linux verification.

## Live probes and unresolved prerequisites

Authenticated read-only collection against canonical Issue 946 previously captured
four real sources with no unknown revision. This was a read probe, not a paid pilot.
Canonical main remains the base SHA above. No ledger/vnext namespace exists.

The GitHub repository setting prevents Actions-created PRs. Enabling it at repository
scope failed because of organization policy. The token lacks `admin:org`, so the
organization-level change is awaiting the operator. No remote setting changed.
The exact UI procedure is in `docs/TIDE.md`.

The S-02H / T-04 first-stage publication-time question remains unanswered.
The proposed shift for manual funding-merge wait has NOT been implemented.
Current clocks retain the original activation-time anchor. No live-readiness claim
is permitted before the operator decision and its exact evidence are recorded.

Private ruleset enforcement remains DEFERRED. Manual review must verify current
main and the exact candidate status. The initial code-only writer upgrade still
needs the existing manual maintenance process; PR 949's exception is not reusable.

No activation, paid transaction, worker launch, visibility change, or workflow dispatch
has occurred in this implementation worktree. The parent activation and S-80/S-81
live checks remain unfulfilled until actual canonical runs and pilot evidence exist.
