# Design: WEA vNext S13C Financial Correction

**Revision:** 1.1
**Date:** 2026-08-15
**Status:** Accepted
**Outcome:** `outcome.md` version 1.0
**Specification:** `spec.md` version 1.1

## Revision history

| Revision | Date | Implements | Material decision |
| --- | --- | --- | --- |
| 1.0 | 2026-08-15 | Spec 1.0 | Pure immutable correction state, canonical hashes, dual confirmation, atomic application, and reconstruction. |
| 1.1 | 2026-08-15 | Spec 1.1 | Signed supply, pinned opening/group chain, strict separate rebuild, versioned bindings, and bounded inactive snapshots. |

The 2026-08-16 evidence reconciliation does not change Design 1.1. It adds
version provenance and a plain-language operator review only.

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
identities, proves the opening invariant, and derives an ordered opening
snapshot hash before returning state. A recovery caller must retain that hash
as an external trust anchor; changing row order or authority membership while
retaining the pinned hash fails reconstruction.

The factory bounds each public iterable before sorting or rebuilding it. The
accepted snapshot ceilings are 10,000 positions, 100,000 published rows, 64
MiB of aggregate published-row content, and 128 authority bindings. Authority
bindings use canonical order, and uniqueness is enforced on
`(binding_id, binding_version)` so a stable binding identity can retain its
version history.

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
  the financial state before and after the group. It also commits to its
  zero-based sequence number and predecessor hash; the first predecessor is the
  opening snapshot hash.
- `CorrectionIdempotencyRecord` maps one idempotency key and proposal hash to
  one correction group.
- `FinancialCorrectionState` stores immutable opening evidence, configured
  authority bindings, accepted groups, and exact idempotency records.

Current positions, total minted, correction rows, and the complete ledger-row
sequence are derived by replay. They are not independent mutable fields. Each
validated immutable state retains one non-comparable derived replay cache so
properties do not reconstruct the same history repeatedly.

The cache is never a trust anchor. Every public operation reconstructs a
separate state value from exact fields and refreshes the cache through full
historical replay. This rejects nested type/value tampering, repairs a modified
derived cache without mutating the caller, and keeps failed operations atomic.

## Application algorithm

`apply_financial_correction(state, proposal, approvals, effective_at)` returns
`(state, group)` and performs these steps:

1. Rebuild and replay the exact caller-owned state into a separate validated
   value, then rebuild the proposal, bounded approval tuple, and timestamp.
   Reject subclasses, booleans as integers, malformed values, incomplete
   objects, and over-limit iterables without mutating caller-owned state.
2. Check the idempotency key and correction ID. An exact replay returns the
   equal freshly validated state and existing group. Conflicting reuse rejects.
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

The public limits are 256 affected IDs, 128 postings, two approvals, and 64
accepted groups per snapshot. Idempotent replay is checked before the group
ceiling so retry remains stable. A 65th distinct group is rejected and requires
a new externally pinned opening checkpoint. The ceiling bounds the deliberate
full-reconstruction cost at this inactive trust boundary.

No partially constructed state is exposed. Every failure raises
`FinancialCorrectionError` before a new state is returned.

## Reconstruction and tamper detection

`FinancialCorrectionState.__post_init__` treats all supplied values as
untrusted. It rebuilds exact dataclass values, checks uniqueness and canonical
identity rules, validates the published-row content hashes, and replays groups
in tuple order from the opening positions.

For each group it revalidates:

- proposal and approval hashes and authority snapshots;
- the pinned opening snapshot and sequence/predecessor hash chain;
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

`confirm_correction(...)` is a snapshot operation inside that trusted boundary,
not a caller-authentication mechanism. Its configured authority inputs must have
already been verified by the operator-controlled source that establishes the
opening snapshot.

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
- Scenario-registry tests prove S13C remains one of 70 current scenarios. Nine
  accepted-future Block 9 scenarios remain unimplemented; the proposed-future
  set is empty.
- Runtime-boundary tests prove `financial_correction.py` stays outside executor
  and pre-activation entrypoint closures.
- Existing invariant and repository-wide quality gates remain mandatory.
