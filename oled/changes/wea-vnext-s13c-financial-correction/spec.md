# Specification: WEA vNext S13C Financial Correction

**Version:** 1.1
**Date:** 2026-08-15
**Status:** Accepted
**Outcome:** `outcome.md` version 1.0

## Version history

| Version | Date | Authority | Material behavior |
| --- | --- | --- | --- |
| 1.0 | 2026-08-15 | WEA operator | Atomic append-only correction, dual confirmation, invariant preservation, and replay. |
| 1.1 | 2026-08-15 | WEA operator | Signed supply adjustment, prior correction-row references, versioned bindings, opening/group commitments, and bounded inactive snapshots. |

The 2026-08-16 scenario and evidence-map edit is non-behavioral. It makes the
accepted 1.1 clauses directly verifiable without changing them.

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

- **GIVEN:** A valid opening state, two known published rows, and a complete
  canonical transfer proposal.
- **WHEN:** Independent effective operator and Agent0 authorities confirm the
  same exact proposal hash and the correction is applied.
- **THEN:** One complete correction group is appended in posting order. The
  published-row prefix stays byte-identical and total minted does not change.
- **EVIDENCE:** `test_s_13c_1_atomic_redistribution_preserves_published_row_bytes`,
  `test_s_13c_1_rejects_incomplete_or_duplicate_proposal_inputs`, and
  `test_s_13c_1_proposal_hash_binds_the_exact_payload`.

### S-13C.2: Explicit supply correction

- **GIVEN:** A valid opening state and complete mint or burn proposals for
  known positions.
- **WHEN:** Both required authorities approve each exact proposal and it is
  applied.
- **THEN:** The position amount and total minted change by the same signed
  value. The resulting supply remains non-negative and the invariant holds.
- **EVIDENCE:** `test_s_13c_2_mint_and_burn_adjust_supply_with_position_amounts`,
  `test_s_13c_2_burn_can_create_a_signed_negative_supply_adjustment`, and
  `test_signed_opening_supply_adjustment_reconstructs_when_supply_is_valid`.

### S-13C.3: Invalid approval evidence changes nothing

- **GIVEN:** A valid proposal and an unchanged valid state.
- **WHEN:** An approval is missing, duplicated by role, bound to another hash,
  bound to a wrong authority snapshot, unknown, inactive, not independent, or
  later than the proposed effective time.
- **THEN:** The whole proposal is rejected and no row or group is appended.
- **EVIDENCE:** `test_s_13c_3_missing_or_mismatched_approval_changes_nothing`,
  `test_s_13c_3_approval_sources_must_be_independent_and_effective`,
  `test_s_13c_3_unknown_or_inactive_authority_cannot_confirm`, and
  `test_s_13c_3_requires_exact_binding_snapshot_and_one_approval_per_role`.

### S-13C.4: Invalid financial effect changes nothing

- **GIVEN:** A state and a proposed financial correction.
- **WHEN:** A reference or position is unknown, a debit becomes negative, a
  transfer does not net to zero, a posting kind/sign/value is invalid, a row
  identity collides, or an invariant fails.
- **THEN:** The whole correction is rejected and the caller state remains
  unchanged.
- **EVIDENCE:** `test_s_13c_4_invalid_effect_rejects_the_whole_group`,
  `test_s_13c_4_rejects_invalid_opening_invariant_and_boolean_money`,
  `test_s_13c_4_rejects_zero_delta_posting`, and
  `test_s_13c_4_rejects_a_deterministic_row_identity_collision`.

### S-13C.5: Replay is stable and conflicts fail closed

- **GIVEN:** A valid accepted correction history and its pinned opening
  snapshot.
- **WHEN:** The exact request is replayed, a conflicting identity is reused,
  history is reconstructed, or an input reaches a published limit.
- **THEN:** Exact replay returns the existing group. Conflicts, tampering,
  reordering, subclasses, and over-limit distinct history reject without
  changing the caller state. Public iterables stop at the limit plus one.
- **EVIDENCE:** `test_s_13c_5_exact_replay_returns_existing_group_without_append`,
  `test_s_13c_5_conflicting_idempotency_or_correction_id_fails_closed`,
  `test_s_13c_5_reconstruction_rejects_tampered_group`,
  `test_s_13c_5_group_chain_rejects_coordinated_noop_reordering`,
  `test_full_reconstruction_rejects_nested_row_tampering_on_exact_replay`,
  `test_full_reconstruction_repairs_a_tampered_derived_replay_cache`,
  `test_rejected_apply_does_not_mutate_the_caller_state`,
  `test_validated_state_rejects_identical_value_nested_subclasses`,
  `test_correction_history_and_proposal_cardinalities_are_bounded`,
  `test_64_group_ceiling_allows_exact_replay_and_rejects_new_group`, and
  `test_public_iterables_stop_after_limit_plus_one_items`.

## Verification contract

All test names below are in `tests/vnext/test_correction.py` unless another
file is named.

| Requirement clause | Scenario | Exact evidence |
| --- | --- | --- |
| R-FC-01 complete canonical IDs, non-empty collections, no duplicate affected IDs | S-13C.1 | `test_s_13c_1_rejects_incomplete_or_duplicate_proposal_inputs` |
| R-FC-01 exact payload hash and posting order | S-13C.1 | `test_s_13c_1_proposal_hash_binds_the_exact_payload`; `test_s_13c_1_atomic_redistribution_preserves_published_row_bytes` |
| R-FC-01 transfer/mint/burn sign, type, and transfer-net rules | S-13C.2, S-13C.4 | `test_s_13c_2_mint_and_burn_adjust_supply_with_position_amounts`; `test_s_13c_4_rejects_invalid_opening_invariant_and_boolean_money`; `test_s_13c_4_rejects_zero_delta_posting`; `test_s_13c_4_invalid_effect_rejects_the_whole_group` |
| R-FC-02 exact operator and Agent0 roles, hash, binding snapshot, interval, and source independence | S-13C.3 | `test_s_13c_3_missing_or_mismatched_approval_changes_nothing`; `test_s_13c_3_approval_sources_must_be_independent_and_effective`; `test_s_13c_3_unknown_or_inactive_authority_cannot_confirm`; `test_s_13c_3_requires_exact_binding_snapshot_and_one_approval_per_role` |
| R-FC-02 stable binding ID with unique versions | S-13C.3 | `test_stable_authority_binding_id_allows_non_overlapping_versions`; `test_authority_binding_set_has_one_canonical_opening_commitment` |
| R-FC-03 pre/post invariant, known references/positions, atomic append, immutable ordered prefix, collision rejection | S-13C.1, S-13C.4 | `test_s_13c_1_atomic_redistribution_preserves_published_row_bytes`; `test_s_13c_4_invalid_effect_rejects_the_whole_group`; `test_s_13c_4_rejects_invalid_opening_invariant_and_boolean_money`; `test_s_13c_4_rejects_a_deterministic_row_identity_collision` |
| R-FC-04 exact replay and conflicting correction/idempotency identities | S-13C.5 | `test_s_13c_5_exact_replay_returns_existing_group_without_append`; `test_s_13c_5_conflicting_idempotency_or_correction_id_fails_closed` |
| R-FC-04 opening commitment, group chain, full reconstruction, hashes, order, exact types, and caller immutability | S-13C.5 | `test_s_13c_5_reconstruction_rejects_tampered_group`; `test_opening_snapshot_commitment_rejects_reordered_rows`; `test_opening_snapshot_commitment_rejects_added_authority`; `test_s_13c_5_group_chain_rejects_coordinated_noop_reordering`; `test_full_reconstruction_rejects_nested_row_tampering_on_exact_replay`; `test_full_reconstruction_repairs_a_tampered_derived_replay_cache`; `test_rejected_apply_does_not_mutate_the_caller_state`; `test_validated_state_rejects_identical_value_nested_subclasses` |
| R-FC-05 all cardinality/byte/iterable limits and the 64/65 replay boundary | S-13C.5 | `test_correction_history_and_proposal_cardinalities_are_bounded`; `test_64_group_ceiling_allows_exact_replay_and_rejects_new_group`; `test_public_iterables_stop_after_limit_plus_one_items` |
| S13C remains current in a registry of 70 current / 9 accepted-future / 0 proposed-future Block 9 scenarios | Registry | `tests/vnext/test_scenario_registry.py` |
| Inactive module stays outside current executor closures | Runtime isolation | `tests/vnext/test_runtime_boundary.py` |

Existing invariant, schema, task-index, documentation, lint, type, focused,
vNext, and full-suite checks must remain green.

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
