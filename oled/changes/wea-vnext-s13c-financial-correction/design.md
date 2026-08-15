# Design: WEA vNext S13C Financial Correction

**Revision:** 1.0
**Date:** 2026-08-15
**Status:** Accepted
**Outcome:** `outcome.md` version 1.0
**Specification:** `spec.md` version 1.0

## Decision summary

Implement S-13C as a pure, immutable, standard-library control-plane module at
`src/wea_vnext/financial_correction.py`. The module owns no file, network,
GitHub, executor, CLI, or current-ledger integration. It validates and replays
complete correction state in memory. This is the protected boundary for this
inactive delivery; a live writer remains a separate future design.

## Public model

### Opening evidence

- `MoneyPosition(position_id, kind, amount)` records one known `balance` or
  `escrow` position. Amounts are exact non-negative integers.
- `PublishedLedgerRow(ledger_id, content, content_hash)` retains the exact bytes
  and SHA-256 of one immutable prior row.
- `VerifiedCorrectionAuthority` binds `operator` or `agent0` to one authority
  identity and revision, binding identity and version, and half-open effective
  interval.

`initial_financial_correction_state(...)` accepts these explicit values plus
`opening_supply` and `opening_total_minted`. It requires canonical, unique
identities and proves the opening invariant before returning state.

### Proposal and approval

- `CompensatingPosting(position_id, delta, kind)` represents a `transfer`,
  `mint`, or `burn` change.
- `make_correction_proposal(...)` validates canonical correction and
  idempotency identities, sorts the affected ledger IDs, retains posting order,
  and computes the SHA-256 of canonical JSON containing every proposal field.
- `confirm_correction(...)` resolves an exact configured authority binding at
  `confirmed_at` and returns an immutable approval snapshot bound to the
  proposal hash and full authority interval.

Only canonical JSON primitives enter a hash. JSON encoding uses UTF-8,
`allow_nan=False`, sorted keys, compact separators, and no trailing newline.
Datetime values are normalized to UTC and encoded with a `Z` suffix.

### Accepted group

- `CorrectionLedgerRow` contains a deterministic row ID, correction ID,
  proposal hash, posting index, exact posting, effective time, and row hash.
- `CorrectionGroup` contains the proposal, the operator and Agent0 approval
  snapshots in fixed role order, all row objects, effective time, and hashes of
  the financial state before and after the group.
- `CorrectionIdempotencyRecord` maps one idempotency key and proposal hash to
  one correction group.
- `FinancialCorrectionState` stores immutable opening evidence, configured
  authority bindings, accepted groups, and exact idempotency records.

Current positions, total minted, correction rows, and the complete ledger-row
sequence are derived by replay. They are not independent mutable fields.

## Application algorithm

`apply_financial_correction(state, proposal, approvals, effective_at)` returns
`(state, group)` and performs these steps:

1. Rebuild and replay the exact caller-owned state, proposal, approval tuple,
   and timestamp. Reject subclasses, booleans as integers, malformed values,
   and incomplete objects.
2. Check the idempotency key and correction ID. An exact replay returns the
   original state and existing group. Conflicting reuse rejects.
3. Require every affected ledger ID to exist in the published-row prefix or a
   previously accepted correction row.
4. Resolve exactly one operator and one Agent0 approval. Each snapshot must
   match the proposal hash and one configured binding active at confirmation.
   Their authority identity and revision must be independent. The application
   time cannot precede either confirmation.
5. Aggregate every posting against a temporary copy of current positions.
   Transfers must net to zero. Mint and burn deltas update total minted by the
   same signed amount. Unknown positions, non-positive mint, non-negative burn,
   insufficient funds, or an invalid resulting supply reject.
6. Prove the financial invariant against the complete temporary result.
7. Derive deterministic row and group identities and hashes. Reject any
   collision.
8. Construct a new immutable state containing the complete group and
   idempotency record. The state constructor replays all history again before
   the result is returned.

No partially constructed state is exposed. Every failure raises
`FinancialCorrectionError` before a new state is returned.

## Reconstruction and tamper detection

`FinancialCorrectionState.__post_init__` treats all supplied values as
untrusted. It rebuilds exact dataclass values, checks uniqueness and canonical
identity rules, validates the published-row content hashes, and replays groups
in tuple order from the opening positions.

For each group it revalidates:

- proposal and approval hashes and authority snapshots;
- affected-row availability at that historical point;
- posting order, deterministic row IDs, and row hashes;
- pre-state and post-state hashes;
- correction ID and idempotency uniqueness; and
- pre- and post-group financial invariants.

This makes accepted in-memory state self-validating and lets tests demonstrate
recovery from an immutable snapshot without trusting constructor history.

## Failure and recovery model

Validation failure leaves the caller's immutable state unchanged. An inactive
consumer recovers by loading explicit opening evidence and replaying complete
accepted groups. There is no partial-write recovery because this delivery does
not write files or external systems.

A future live integration must separately choose authenticated source loading,
durable serialization, locking or compare-and-swap, atomic file replacement or
transaction semantics, fsync, crash recovery, and single-writer enforcement.
This module is not evidence that those concerns are solved.

## Compatibility and dependency boundaries

- Do not import `wea_vnext.engine`, executor packages, `src/wea_cli`, or current
  ledger operations.
- Do not export the module through a current runtime facade.
- Do not modify executor manifests, rulesets, current ledger files, or v1
  behavior.
- Add S-13C only to the control-plane scenario scope; leave the 67 runtime
  scenarios and S-11A/S-11B behavior unchanged.
- Keep the implementation on the Python 3.10 standard library.

## Verification hooks

- Direct S-13C tests cover success, failure atomicity, idempotency, supply
  changes, reconstruction, and tamper rejection.
- Scenario-registry tests prove 70 current scenarios and no accepted-future
  scenario after this delta.
- Runtime-boundary tests prove `financial_correction.py` stays outside executor
  and pre-activation entrypoint closures.
- Existing invariant and repository-wide quality gates remain mandatory.
