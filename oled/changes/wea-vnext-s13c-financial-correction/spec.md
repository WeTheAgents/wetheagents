# Specification: WEA vNext S13C Financial Correction

**Version:** 1.1
**Date:** 2026-08-15
**Status:** Accepted
**Outcome:** `outcome.md` version 1.0

## Delta authority

This specification promotes S-13C from accepted-future behavior in the WEA
vNext recreation specification to current inactive control-plane behavior. It
does not change the other current scenarios or make WEA vNext live.

This delta has priority over conflicting S-13C status, scenario-count, and
accepted-future text in `oled/changes/wea-vnext-recreation/`.

## Terms

- **Published ledger row:** an immutable, identified historical row known to
  the correction state.
- **Financial position:** a known balance or escrow position with a
  non-negative integer amount.
- **Compensating posting:** one signed change to a known financial position.
- **Correction group:** the proposal, approval evidence, and all rows appended
  for one accepted correction.
- **Opening supply:** the fixed supply represented by the opening positions
  before later mint or burn effects.
- **Opening snapshot hash:** the externally pinnable SHA-256 commitment to the
  ordered opening positions, exact published-row digests, supply values, and
  complete authority-binding set.
- **Total minted:** the cumulative signed supply adjustment. Mint increases it;
  burn decreases it.

## Financial invariant

At every accepted state boundary:

```text
sum(all balance and escrow positions) = opening supply + total minted
```

All position amounts and the right-hand side must be non-negative integers.
Boolean values are not monetary integers.

## Requirements

### R-FC-01: Exact canonical proposal

A proposal MUST contain:

- one canonical correction ID;
- one non-empty, duplicate-free set of affected known ledger IDs, where each ID
  identifies an opening published row or a previously accepted correction row;
- one non-empty ordered list of exact compensating postings;
- one canonical idempotency key; and
- one SHA-256 proposal hash computed from the exact canonical proposal payload.

Each posting MUST name an existing financial position, contain a non-zero
integer delta, and declare exactly one kind:

- `transfer`: contributes zero to total minted;
- `mint`: has a positive delta and increases total minted by the same amount;
- `burn`: has a negative delta and decreases total minted by the same amount.

The aggregate of all `transfer` deltas in a correction MUST equal zero.
A proposal MUST contain at most 256 affected ledger IDs and at most 128
postings.

### R-FC-02: Independent verified confirmation

One operator approval and one Agent0 approval MUST confirm the same proposal
hash. Each approval MUST resolve to the exact configured authority identity,
authority revision, binding identity, binding version, and effective interval
for its role.

The two approvals MUST come from distinct source identities and revisions.
Both bindings MUST be effective when the approval is made, and the correction
effective time MUST be no earlier than either confirmation time. Missing,
duplicated, mismatched, expired, premature, or unverifiable approval evidence
MUST reject the proposal without changing state.

A binding ID is stable across revisions. The pair of binding ID and positive
binding version MUST be unique in opening evidence; distinct versions of the
same binding ID are valid and each approval resolves its exact version and
effective interval.

This inactive module treats `VerifiedCorrectionAuthority` values as trusted
opening evidence and snapshots their configured identity and revision. Caller
authentication and production authority-source loading remain outside this
control-plane boundary; this delivery makes no claim that an untrusted Python
caller is authenticated.

### R-FC-03: Atomic append and invariant preservation

The state MUST validate the pre-correction invariant before evaluating a
proposal. Every affected ledger ID and financial position MUST already be
known. The complete ordered posting list MUST be evaluated as one group.

The group MUST append all deterministic correction rows or append none. It
MUST reject if any resulting position, total minted value, row identity, or
post-correction invariant is invalid. A rejection MUST return the original
state unchanged.

All previously published ledger rows MUST remain byte-identical and retain
their order. New correction rows MUST follow that prefix in proposal posting
order.

### R-FC-04: Idempotency and reconstruction

An identical replay of an accepted proposal, approvals, and effective time
MUST return the existing group without appending rows or changing state.

Reuse of an idempotency key or correction ID for different content MUST be
rejected. A reconstructed state MUST validate the opening snapshot and replay
every correction group, including proposal hashes, approval snapshots, row
identities, row hashes, references, ordering, and financial invariants. Any
tampering or inconsistent replay MUST reject reconstruction.

The opening snapshot hash MUST match the exact ordered opening evidence. Each
correction group MUST commit to its zero-based sequence number and the previous
group hash, with the first group anchored to the opening snapshot hash.

### R-FC-05: Bounded inactive snapshots

One opening snapshot MUST contain at most 10,000 positions, 100,000 published
rows, 64 MiB of aggregate published-row content, and 128 authority bindings.
One application call MUST consume at most two approvals. One state MUST contain
at most 64 correction groups and 64 matching idempotency records.

Public iterable inputs MUST be collected only through the applicable limit
plus one item, then reject when over limit. Aggregate row bytes MUST reject as
soon as the byte ceiling is crossed. At the 64-group ceiling, an exact replay
remains valid, while a new correction MUST reject unchanged. Continued history
requires a separately retained and externally pinned opening checkpoint; this
inactive module does not define checkpoint persistence.

## Acceptance scenarios

### S-13C.1: Atomic redistribution preserves history

Given a valid opening state and two known published ledger rows, a proposal
debits one known balance and credits another by the same amount. Independent,
effective operator and Agent0 approvals confirm its hash. Applying the proposal
appends one correction group, preserves the published-row prefix exactly, and
leaves total minted unchanged.

### S-13C.2: Explicit supply correction

Given a valid opening state, independently approved mint and burn proposals
apply their signed supply changes to known positions and total minted by the
same amount. The invariant holds after each complete group.

### S-13C.3: Invalid approval evidence changes nothing

Missing approval, a proposal-hash mismatch, an unknown or inactive authority,
the same approval source for both roles, or an effective time before a
confirmation rejects the whole proposal and appends no row.

### S-13C.4: Invalid financial effect changes nothing

An unknown ledger reference, unknown position, insufficient debit, invalid
posting kind, malformed integer, row collision, failed pre-invariant, or
failed post-invariant rejects the whole proposal and appends no row.

### S-13C.5: Replay is stable and conflicts fail closed

Replaying an identical accepted correction returns its existing group and row
identities with an equal freshly validated state. Reusing its idempotency key
or correction ID for different content is rejected without changing state.
Reconstruction rejects modified rows, approval evidence, or group metadata.
Over-limit state or public iterable input rejects without unbounded
materialization.

## Verification contract

- `tests/vnext/test_correction.py` covers S-13C.1 through S-13C.5.
- `tests/vnext/test_scenario_registry.py` proves that S-13C is current and the
  current-scenario count is updated without losing another scenario.
- `tests/vnext/test_runtime_boundary.py` proves that the inactive module does
  not enter a current executor closure.
- Existing invariant, schema, task-index, documentation, lint, type, focused,
  vNext, and full-suite checks remain green.

## Non-goals and compatibility ceiling

- No file-backed transaction, locking, compare-and-swap, fsync, or recovery
  journal.
- No current ledger or v1 ledger mutation.
- No runtime, worker, executor, scheduler, CLI command, or GitHub integration.
- No creation of positions, identities, authority bindings, or published rows.
- No authentication of an untrusted in-process caller. Authority bindings are
  pre-verified trusted inputs.
- No non-financial correction path.
- A future live cutover requires a separate accepted design for durable atomic
  writes and authenticated authority-source loading.
