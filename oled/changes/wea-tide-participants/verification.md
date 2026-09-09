# Verification

Status: in progress. Live admission requires manual implementation merge and then manual Tide merge.

## Current scenario registry

All locators below are in `tests/vnext/test_tide_participants.py`.

| Scenario | Executable evidence |
| --- | --- |
| P-01 | `test_new_account_requires_owner_and_approval_and_starts_at_zero`; `test_invalid_consent_or_approval_has_no_effect` |
| P-02 | `test_invalid_consent_or_approval_has_no_effect`; `test_thirteen_canonical_claude_balances_survive_bulk_registration` |
| P-03 | `test_thirteen_canonical_claude_balances_survive_bulk_registration`; `test_new_account_requires_owner_and_approval_and_starts_at_zero` |
| P-04 | `test_atomic_rejection_for_invalid_or_reserved_identity`; `test_duplicate_conflicting_and_additional_requests`; `test_competing_requests_in_one_batch_reserve_atomically` |
| P-05 | `test_merge_time_limits_authority_and_no_activation_only_pr`; existing immutable Work authority tests in the vNext suite |
| P-06 | `test_superseded_consent_cannot_gain_approval_or_rewrite_admission`; `test_old_batches_keep_semantics_and_runtime_is_pinned`; `test_duplicate_conflicting_and_additional_requests`; `test_competing_requests_in_one_batch_reserve_atomically` |
| P-07 | `test_guard_rejects_forged_participant_projection`; trusted source and canonical merge validation in `test_tide_ledger.py` |
| P-08 | `test_new_account_requires_owner_and_approval_and_starts_at_zero`; `test_duplicate_conflicting_and_additional_requests`; canonical thirteen-Claude replay |

## Independent Review

Fresh-context reviewer `participant_review` inspected the whole change against the accepted contract.

- P1: unresolved schema 1 participant commands were retried as admission under schema 2. Fixed: retain revision introduction eligibility during replay; require fresh schema 2 consent and approval. The exact schema transition is covered by `test_old_batches_keep_semantics_and_runtime_is_pinned`.

## Checks

- First focused Tide run: 51 passed, one new fixture failed because its draft declared a zero maximum bank. The fixture now uses a positive bank; no production task rule changed.
- Admission-only run before the historical-boundary regression: 20 passed.
- Full vNext suite: 698 passed, 18 skipped, one packaging-fixture failure. Its imaginary future version 0.10.0 collided with the newly implemented version. The fixture now uses 999.0.0.
- Final targeted run: `python -m pytest tests/vnext/test_packaging.py tests/vnext/test_tide_participants.py tests/vnext/test_runtime_boundary.py -q --disable-warnings` — 34 passed. This includes all 22 admission cases and the corrected wheel/isolation test.
- Ruff on changed Python files, doc-sync, canonical invariant, and `git diff --check`: passed.
- Independent follow-up: no remaining actionable authority/history findings; all 22 participant cases passed.
- Canonical Claude replay: thirteen identities; balances unchanged; opening supply 19,025 WEA. This is local evidence, not a live registration.
- GitHub source publication, trusted Tide run, candidate merge: pending implementation merge.

## Self-review before publication

The change addresses admission through the existing Tide path. No new workflow, task runtime change, payment rule, mint, automatic merge, or unrelated genome edit is included. Normative BDD and source evidence are versioned together. The canonical thirteen-Claude replay preserves every balance. A separate code merge is necessary before live consent is posted, because schema 1 sources must not later gain new authority.
