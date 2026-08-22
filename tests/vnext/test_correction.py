"""S-13C financial-correction control-plane contract tests."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from wea_vnext.financial_correction import (
    CompensatingPosting,
    CorrectionApproval,
    CorrectionGroup,
    CorrectionIdempotencyRecord,
    CorrectionLedgerRow,
    FinancialCorrectionError,
    FinancialCorrectionState,
    MoneyPosition,
    PublishedLedgerRow,
    VerifiedCorrectionAuthority,
    apply_financial_correction,
    confirm_correction,
    initial_financial_correction_state,
    make_correction_proposal,
    make_published_ledger_row,
)

UTC = timezone.utc
START = datetime(2026, 8, 15, 8, tzinfo=UTC)


def _authority(
    kind: str,
    *,
    authority_id: str | None = None,
    revision: str | None = None,
) -> VerifiedCorrectionAuthority:
    return VerifiedCorrectionAuthority(
        authority_kind=kind,
        authority_id=authority_id or f"{kind}:primary",
        authority_revision_id=revision or f"{kind}:revision:7",
        binding_id=f"binding:{kind}:financial-correction",
        binding_version=3,
        effective_from=START - timedelta(days=1),
        effective_until=START + timedelta(days=30),
    )


def _state(
    *,
    authority_bindings: tuple[VerifiedCorrectionAuthority, ...] | None = None,
) -> FinancialCorrectionState:
    return initial_financial_correction_state(
        opening_supply=175,
        opening_total_minted=0,
        opening_positions=(
            MoneyPosition("balance:alice", "balance", 100),
            MoneyPosition("balance:bob", "balance", 50),
            MoneyPosition("escrow:task-42", "escrow", 25),
        ),
        published_rows=(
            make_published_ledger_row(
                "ledger:history:2026-08-14:1",
                b'{"amount":25,"type":"escrow"}',
            ),
            make_published_ledger_row(
                "ledger:history:2026-08-14:2",
                b'{"amount":10,"type":"payment"}',
            ),
        ),
        authority_bindings=authority_bindings
        or (_authority("operator"), _authority("agent0")),
    )


def _proposal(
    *,
    correction_id: str = "correction:2026-08-15:redistribute",
    idempotency_key: str = "financial-correction:2026-08-15:redistribute",
    affected_ledger_ids: tuple[str, ...] = (
        "ledger:history:2026-08-14:2",
        "ledger:history:2026-08-14:1",
    ),
    postings: tuple[CompensatingPosting, ...] = (
        CompensatingPosting("balance:alice", -20, "transfer"),
        CompensatingPosting("balance:bob", 20, "transfer"),
    ),
):
    return make_correction_proposal(
        correction_id=correction_id,
        affected_ledger_ids=affected_ledger_ids,
        postings=postings,
        idempotency_key=idempotency_key,
    )


def _approvals(
    state: FinancialCorrectionState,
    proposal: Any,
    *,
    confirmed_at: datetime = START,
) -> tuple[CorrectionApproval, CorrectionApproval]:
    return (
        confirm_correction(
            state,
            proposal=proposal,
            authority_kind="operator",
            authority_id="operator:primary",
            authority_revision_id="operator:revision:7",
            confirmed_at=confirmed_at,
        ),
        confirm_correction(
            state,
            proposal=proposal,
            authority_kind="agent0",
            authority_id="agent0:primary",
            authority_revision_id="agent0:revision:7",
            confirmed_at=confirmed_at + timedelta(minutes=1),
        ),
    )


def _amounts(state: FinancialCorrectionState) -> dict[str, int]:
    return {position.position_id: position.amount for position in state.positions}


def _forged(value: Any, **changes: object) -> Any:
    forged = object.__new__(type(value))
    for field in fields(value):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(value, field.name)),
        )
    return forged


def _reconstruct(
    state: FinancialCorrectionState,
    *,
    groups: tuple[CorrectionGroup, ...] | None = None,
    idempotency_records: tuple[CorrectionIdempotencyRecord, ...] | None = None,
) -> FinancialCorrectionState:
    return FinancialCorrectionState(
        opening_supply=state.opening_supply,
        opening_total_minted=state.opening_total_minted,
        opening_snapshot_hash=state.opening_snapshot_hash,
        opening_positions=state.opening_positions,
        published_rows=state.published_rows,
        authority_bindings=state.authority_bindings,
        groups=state.groups if groups is None else groups,
        idempotency_records=(
            state.idempotency_records
            if idempotency_records is None
            else idempotency_records
        ),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"correction_id": ""}, "correction_id must be a canonical identifier"),
        (
            {"idempotency_key": ""},
            "idempotency_key must be a canonical identifier",
        ),
        ({"affected_ledger_ids": ()}, "affected_ledger_ids must be non-empty"),
        (
            {
                "affected_ledger_ids": (
                    "ledger:history:2026-08-14:1",
                    "ledger:history:2026-08-14:1",
                )
            },
            "affected_ledger_ids must be non-empty and duplicate-free",
        ),
        ({"postings": ()}, "postings must be non-empty"),
    ],
)
def test_s_13c_1_rejects_incomplete_or_duplicate_proposal_inputs(
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "correction_id": "correction:complete",
        "affected_ledger_ids": ("ledger:history:2026-08-14:1",),
        "postings": (CompensatingPosting("balance:alice", 1, "mint"),),
        "idempotency_key": "financial-correction:complete",
    }
    values.update(changes)

    with pytest.raises(FinancialCorrectionError, match=message):
        make_correction_proposal(**values)  # type: ignore[arg-type]


def test_s_13c_1_proposal_hash_binds_the_exact_payload() -> None:
    state = _state()
    proposal = _proposal()
    forged = _forged(proposal, proposal_hash="0" * 64)

    with pytest.raises(FinancialCorrectionError, match="proposal hash"):
        apply_financial_correction(
            state,
            proposal=forged,
            approvals=_approvals(state, proposal),
            effective_at=START + timedelta(minutes=2),
        )


def test_s_13c_1_atomic_redistribution_preserves_published_row_bytes() -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    original_rows = tuple((row.ledger_id, row.content) for row in state.published_rows)

    updated, group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=approvals,
        effective_at=START + timedelta(minutes=2),
    )

    assert _amounts(updated) == {
        "balance:alice": 80,
        "balance:bob": 70,
        "escrow:task-42": 25,
    }
    assert updated.total_minted == 0
    assert tuple((row.ledger_id, row.content) for row in updated.published_rows) == (
        original_rows
    )
    assert updated.ledger_rows[:2] == updated.published_rows
    assert updated.ledger_rows[2:] == group.rows
    assert tuple(row.posting_index for row in group.rows) == (0, 1)
    assert group.proposal.affected_ledger_ids == (
        "ledger:history:2026-08-14:1",
        "ledger:history:2026-08-14:2",
    )


def test_s_13c_2_mint_and_burn_adjust_supply_with_position_amounts() -> None:
    state = _state()
    mint = _proposal(
        correction_id="correction:2026-08-15:mint",
        idempotency_key="financial-correction:2026-08-15:mint",
        affected_ledger_ids=("ledger:history:2026-08-14:1",),
        postings=(CompensatingPosting("balance:alice", 10, "mint"),),
    )
    minted, mint_group = apply_financial_correction(
        state,
        proposal=mint,
        approvals=_approvals(state, mint),
        effective_at=START + timedelta(minutes=2),
    )

    burn = _proposal(
        correction_id="correction:2026-08-15:burn",
        idempotency_key="financial-correction:2026-08-15:burn",
        affected_ledger_ids=(mint_group.rows[0].row_id,),
        postings=(CompensatingPosting("balance:bob", -5, "burn"),),
    )
    burned, _ = apply_financial_correction(
        minted,
        proposal=burn,
        approvals=_approvals(minted, burn, confirmed_at=START + timedelta(minutes=3)),
        effective_at=START + timedelta(minutes=5),
    )

    assert _amounts(minted)["balance:alice"] == 110
    assert minted.total_minted == 10
    assert sum(_amounts(minted).values()) == minted.opening_supply + 10
    assert _amounts(burned)["balance:bob"] == 45
    assert burned.total_minted == 5
    assert sum(_amounts(burned).values()) == burned.opening_supply + 5


def test_s_13c_2_burn_can_create_a_signed_negative_supply_adjustment() -> None:
    state = _state()
    burn = _proposal(
        correction_id="correction:2026-08-15:opening-burn",
        idempotency_key="financial-correction:2026-08-15:opening-burn",
        affected_ledger_ids=("ledger:history:2026-08-14:1",),
        postings=(CompensatingPosting("balance:alice", -10, "burn"),),
    )

    burned, _ = apply_financial_correction(
        state,
        proposal=burn,
        approvals=_approvals(state, burn),
        effective_at=START + timedelta(minutes=2),
    )

    assert burned.total_minted == -10
    assert sum(_amounts(burned).values()) == burned.opening_supply - 10


def test_signed_opening_supply_adjustment_reconstructs_when_supply_is_valid() -> None:
    state = initial_financial_correction_state(
        opening_supply=185,
        opening_total_minted=-10,
        opening_positions=(
            MoneyPosition("balance:alice", "balance", 100),
            MoneyPosition("balance:bob", "balance", 50),
            MoneyPosition("escrow:task-42", "escrow", 25),
        ),
        published_rows=(
            make_published_ledger_row("ledger:history:1", b"{}"),
        ),
        authority_bindings=(_authority("operator"), _authority("agent0")),
    )

    assert state.total_minted == -10
    assert sum(_amounts(state).values()) == 175

    with pytest.raises(FinancialCorrectionError, match="resulting supply"):
        initial_financial_correction_state(
            opening_supply=5,
            opening_total_minted=-10,
            opening_positions=(MoneyPosition("balance:alice", "balance", 0),),
            published_rows=(
                make_published_ledger_row("ledger:history:1", b"{}"),
            ),
            authority_bindings=(_authority("operator"), _authority("agent0")),
        )


def test_s_13c_3_missing_or_mismatched_approval_changes_nothing() -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)

    with pytest.raises(FinancialCorrectionError, match="operator and one Agent0"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=approvals[:1],
            effective_at=START + timedelta(minutes=2),
        )

    other = _proposal(
        correction_id="correction:2026-08-15:other",
        idempotency_key="financial-correction:2026-08-15:other",
    )
    mismatched = (approvals[0], _approvals(state, other)[1])
    with pytest.raises(FinancialCorrectionError, match="proposal hash"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=mismatched,
            effective_at=START + timedelta(minutes=2),
        )

    assert state.groups == ()
    assert state.correction_rows == ()


def test_s_13c_3_approval_sources_must_be_independent_and_effective() -> None:
    shared_id = "authority:shared"
    shared_revision = "authority:shared:revision:1"
    state = _state(
        authority_bindings=(
            _authority(
                "operator",
                authority_id=shared_id,
                revision=shared_revision,
            ),
            _authority(
                "agent0",
                authority_id=shared_id,
                revision=shared_revision,
            ),
        )
    )
    proposal = _proposal()
    approvals = (
        confirm_correction(
            state,
            proposal=proposal,
            authority_kind="operator",
            authority_id=shared_id,
            authority_revision_id=shared_revision,
            confirmed_at=START,
        ),
        confirm_correction(
            state,
            proposal=proposal,
            authority_kind="agent0",
            authority_id=shared_id,
            authority_revision_id=shared_revision,
            confirmed_at=START,
        ),
    )
    with pytest.raises(FinancialCorrectionError, match="independent"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=approvals,
            effective_at=START + timedelta(minutes=1),
        )

    regular_state = _state()
    regular_proposal = _proposal()
    regular_approvals = _approvals(regular_state, regular_proposal)
    with pytest.raises(FinancialCorrectionError, match="precede confirmation"):
        apply_financial_correction(
            regular_state,
            proposal=regular_proposal,
            approvals=regular_approvals,
            effective_at=START,
        )


def test_s_13c_3_unknown_or_inactive_authority_cannot_confirm() -> None:
    state = _state()
    proposal = _proposal()
    with pytest.raises(FinancialCorrectionError, match="configured active binding"):
        confirm_correction(
            state,
            proposal=proposal,
            authority_kind="operator",
            authority_id="operator:unknown",
            authority_revision_id="operator:revision:7",
            confirmed_at=START,
        )

    inactive_operator = VerifiedCorrectionAuthority(
        authority_kind="operator",
        authority_id="operator:primary",
        authority_revision_id="operator:revision:7",
        binding_id="binding:operator:financial-correction",
        binding_version=3,
        effective_from=START - timedelta(days=2),
        effective_until=START,
    )
    inactive_state = _state(
        authority_bindings=(inactive_operator, _authority("agent0"))
    )
    with pytest.raises(FinancialCorrectionError, match="configured active binding"):
        confirm_correction(
            inactive_state,
            proposal=proposal,
            authority_kind="operator",
            authority_id="operator:primary",
            authority_revision_id="operator:revision:7",
            confirmed_at=START,
        )


def test_s_13c_3_requires_exact_binding_snapshot_and_one_approval_per_role() -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)

    with pytest.raises(FinancialCorrectionError, match="one operator and one Agent0"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=(approvals[0], approvals[0]),
            effective_at=START + timedelta(minutes=2),
        )

    operator_binding = next(
        binding
        for binding in state.authority_bindings
        if binding.authority_kind == "operator"
    )
    alternate_state = _state(
        authority_bindings=(
            _forged(
                operator_binding,
                binding_version=operator_binding.binding_version + 1,
            ),
            _authority("agent0"),
        )
    )
    wrong_version = confirm_correction(
        alternate_state,
        proposal=proposal,
        authority_kind="operator",
        authority_id="operator:primary",
        authority_revision_id="operator:revision:7",
        confirmed_at=START,
    )
    with pytest.raises(FinancialCorrectionError, match="configured active authority"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=(wrong_version, approvals[1]),
            effective_at=START + timedelta(minutes=2),
        )

    assert state.groups == ()
    assert state.correction_rows == ()


def test_s_13c_4_rejects_zero_delta_posting() -> None:
    with pytest.raises(FinancialCorrectionError, match="non-zero integer"):
        CompensatingPosting("balance:alice", 0, "transfer")


@pytest.mark.parametrize(
    ("affected", "postings", "message"),
    [
        (
            ("ledger:history:unknown",),
            (
                CompensatingPosting("balance:alice", -20, "transfer"),
                CompensatingPosting("balance:bob", 20, "transfer"),
            ),
            "unknown affected ledger",
        ),
        (
            ("ledger:history:2026-08-14:1",),
            (CompensatingPosting("balance:unknown", 5, "mint"),),
            "unknown financial position",
        ),
        (
            ("ledger:history:2026-08-14:1",),
            (CompensatingPosting("balance:bob", -51, "burn"),),
            "negative position",
        ),
        (
            ("ledger:history:2026-08-14:1",),
            (CompensatingPosting("balance:alice", -1, "transfer"),),
            "transfer postings must net to zero",
        ),
    ],
)
def test_s_13c_4_invalid_effect_rejects_the_whole_group(
    affected: tuple[str, ...],
    postings: tuple[CompensatingPosting, ...],
    message: str,
) -> None:
    state = _state()
    proposal = _proposal(affected_ledger_ids=affected, postings=postings)

    with pytest.raises(FinancialCorrectionError, match=message):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=_approvals(state, proposal),
            effective_at=START + timedelta(minutes=2),
        )

    assert _amounts(state)["balance:alice"] == 100
    assert state.groups == ()


def test_s_13c_4_rejects_invalid_opening_invariant_and_boolean_money() -> None:
    with pytest.raises(FinancialCorrectionError, match="opening financial invariant"):
        initial_financial_correction_state(
            opening_supply=10,
            opening_positions=(MoneyPosition("balance:alice", "balance", 9),),
            published_rows=(
                make_published_ledger_row("ledger:history:1", b"{}"),
            ),
            authority_bindings=(_authority("operator"), _authority("agent0")),
        )

    with pytest.raises(
        FinancialCorrectionError,
        match="delta must be a non-zero integer",
    ):
        CompensatingPosting("balance:alice", True, "mint")

    with pytest.raises(FinancialCorrectionError, match="posting kind"):
        CompensatingPosting("balance:alice", 1, "adjust")
    with pytest.raises(FinancialCorrectionError, match="mint posting"):
        CompensatingPosting("balance:alice", -1, "mint")
    with pytest.raises(FinancialCorrectionError, match="burn posting"):
        CompensatingPosting("balance:alice", 1, "burn")


def test_s_13c_4_rejects_a_deterministic_row_identity_collision() -> None:
    state = _state()
    proposal = _proposal()
    effective_at = START + timedelta(minutes=2)
    _, candidate_group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=_approvals(state, proposal),
        effective_at=effective_at,
    )
    collision_state = initial_financial_correction_state(
        opening_supply=state.opening_supply,
        opening_total_minted=state.opening_total_minted,
        opening_positions=state.opening_positions,
        published_rows=(
            *state.published_rows,
            make_published_ledger_row(candidate_group.rows[0].row_id, b"{}"),
        ),
        authority_bindings=state.authority_bindings,
    )

    with pytest.raises(FinancialCorrectionError, match="row identity collides"):
        apply_financial_correction(
            collision_state,
            proposal=proposal,
            approvals=_approvals(collision_state, proposal),
            effective_at=effective_at,
        )

    assert collision_state.groups == ()


def test_s_13c_5_exact_replay_returns_existing_group_without_append() -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    effective_at = START + timedelta(minutes=2)
    updated, group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )

    replayed, existing = apply_financial_correction(
        updated,
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )

    assert replayed == updated
    assert replayed is not updated
    assert existing == group
    assert len(replayed.groups) == 1
    assert len(replayed.correction_rows) == 2


def test_s_13c_5_conflicting_idempotency_or_correction_id_fails_closed() -> None:
    state = _state()
    proposal = _proposal()
    updated, _ = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=_approvals(state, proposal),
        effective_at=START + timedelta(minutes=2),
    )
    conflict_by_key = _proposal(
        correction_id="correction:2026-08-15:different",
        postings=(
            CompensatingPosting("balance:alice", -10, "transfer"),
            CompensatingPosting("balance:bob", 10, "transfer"),
        ),
    )
    with pytest.raises(FinancialCorrectionError, match="idempotency key"):
        apply_financial_correction(
            updated,
            proposal=conflict_by_key,
            approvals=_approvals(updated, conflict_by_key),
            effective_at=START + timedelta(minutes=4),
        )

    conflict_by_id = _proposal(
        idempotency_key="financial-correction:2026-08-15:different",
        postings=(
            CompensatingPosting("balance:alice", -10, "transfer"),
            CompensatingPosting("balance:bob", 10, "transfer"),
        ),
    )
    with pytest.raises(FinancialCorrectionError, match="correction ID"):
        apply_financial_correction(
            updated,
            proposal=conflict_by_id,
            approvals=_approvals(updated, conflict_by_id),
            effective_at=START + timedelta(minutes=4),
        )

    assert len(updated.groups) == 1


@pytest.mark.parametrize("target", ["row", "approval", "group"])
def test_s_13c_5_reconstruction_rejects_tampered_group(target: str) -> None:
    state = _state()
    proposal = _proposal()
    updated, group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=_approvals(state, proposal),
        effective_at=START + timedelta(minutes=2),
    )

    if target == "row":
        tampered_row: CorrectionLedgerRow = _forged(
            group.rows[0], row_hash="0" * 64
        )
        tampered = _forged(group, rows=(tampered_row, *group.rows[1:]))
    elif target == "approval":
        tampered_approval: CorrectionApproval = _forged(
            group.operator_approval,
            proposal_hash="0" * 64,
        )
        tampered = _forged(group, operator_approval=tampered_approval)
    else:
        tampered = _forged(group, post_state_hash="0" * 64)

    with pytest.raises(FinancialCorrectionError):
        _reconstruct(updated, groups=(tampered,))


def test_s_13c_5_clean_state_reconstructs_to_the_same_value() -> None:
    state = _state()
    proposal = _proposal()
    updated, _ = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=_approvals(state, proposal),
        effective_at=START + timedelta(minutes=2),
    )

    assert _reconstruct(updated) == updated


def test_opening_snapshot_commitment_rejects_reordered_rows() -> None:
    state = _state()

    with pytest.raises(FinancialCorrectionError, match="opening snapshot hash"):
        FinancialCorrectionState(
            opening_supply=state.opening_supply,
            opening_total_minted=state.opening_total_minted,
            opening_snapshot_hash=state.opening_snapshot_hash,
            opening_positions=state.opening_positions,
            published_rows=tuple(reversed(state.published_rows)),
            authority_bindings=state.authority_bindings,
        )


def test_opening_snapshot_commitment_rejects_added_authority() -> None:
    state = _state()
    added = VerifiedCorrectionAuthority(
        authority_kind="operator",
        authority_id="operator:alternate",
        authority_revision_id="operator:alternate:revision:1",
        binding_id="binding:operator:alternate:financial-correction",
        binding_version=1,
        effective_from=START - timedelta(days=1),
        effective_until=START + timedelta(days=30),
    )

    with pytest.raises(FinancialCorrectionError, match="opening snapshot hash"):
        FinancialCorrectionState(
            opening_supply=state.opening_supply,
            opening_total_minted=state.opening_total_minted,
            opening_snapshot_hash=state.opening_snapshot_hash,
            opening_positions=state.opening_positions,
            published_rows=state.published_rows,
            authority_bindings=(
                state.authority_bindings[0],
                added,
                state.authority_bindings[1],
            ),
        )


def test_authority_binding_set_has_one_canonical_opening_commitment() -> None:
    bindings = (_authority("operator"), _authority("agent0"))
    forward = _state(authority_bindings=bindings)
    reversed_input = _state(authority_bindings=tuple(reversed(bindings)))

    assert forward.authority_bindings == reversed_input.authority_bindings
    assert forward.opening_snapshot_hash == reversed_input.opening_snapshot_hash


def test_stable_authority_binding_id_allows_non_overlapping_versions() -> None:
    operator_v1 = VerifiedCorrectionAuthority(
        authority_kind="operator",
        authority_id="operator:primary",
        authority_revision_id="operator:revision:6",
        binding_id="binding:operator:financial-correction",
        binding_version=1,
        effective_from=START - timedelta(days=30),
        effective_until=START - timedelta(days=1),
    )
    operator_v2 = VerifiedCorrectionAuthority(
        authority_kind="operator",
        authority_id="operator:primary",
        authority_revision_id="operator:revision:7",
        binding_id="binding:operator:financial-correction",
        binding_version=2,
        effective_from=START - timedelta(days=1),
        effective_until=START + timedelta(days=30),
    )

    state = _state(
        authority_bindings=(operator_v2, _authority("agent0"), operator_v1)
    )

    assert tuple(
        (binding.binding_id, binding.binding_version)
        for binding in state.authority_bindings
        if binding.authority_kind == "operator"
    ) == (
        ("binding:operator:financial-correction", 1),
        ("binding:operator:financial-correction", 2),
    )


def test_s_13c_5_group_chain_rejects_coordinated_noop_reordering() -> None:
    state = _state()
    first = _proposal(
        correction_id="correction:2026-08-15:noop-first",
        idempotency_key="financial-correction:2026-08-15:noop-first",
        postings=(
            CompensatingPosting("balance:alice", -1, "transfer"),
            CompensatingPosting("balance:alice", 1, "transfer"),
        ),
    )
    after_first, first_group = apply_financial_correction(
        state,
        proposal=first,
        approvals=_approvals(state, first),
        effective_at=START + timedelta(minutes=2),
    )
    second = _proposal(
        correction_id="correction:2026-08-15:noop-second",
        idempotency_key="financial-correction:2026-08-15:noop-second",
        postings=(
            CompensatingPosting("balance:bob", -1, "transfer"),
            CompensatingPosting("balance:bob", 1, "transfer"),
        ),
    )
    after_second, second_group = apply_financial_correction(
        after_first,
        proposal=second,
        approvals=_approvals(
            after_first,
            second,
            confirmed_at=START + timedelta(minutes=3),
        ),
        effective_at=START + timedelta(minutes=5),
    )

    assert first_group.sequence_number == 0
    assert first_group.previous_group_hash == state.opening_snapshot_hash
    assert second_group.sequence_number == 1
    assert second_group.previous_group_hash == first_group.group_hash
    with pytest.raises(FinancialCorrectionError, match="deterministic replay"):
        _reconstruct(
            after_second,
            groups=(second_group, first_group),
            idempotency_records=tuple(reversed(after_second.idempotency_records)),
        )


def test_validated_state_reuses_replay_and_rejects_top_level_history_tampering() -> (
    None
):
    state = _state()
    proposal = _proposal()
    updated, _ = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=_approvals(state, proposal),
        effective_at=START + timedelta(minutes=2),
    )

    assert updated.positions is updated.positions
    assert updated.correction_rows is updated.correction_rows
    forged: FinancialCorrectionState = _forged(updated, groups=())
    with pytest.raises(FinancialCorrectionError, match="idempotency records"):
        confirm_correction(
            forged,
            proposal=_proposal(
                correction_id="correction:2026-08-15:after-tamper",
                idempotency_key="financial-correction:2026-08-15:after-tamper",
            ),
            authority_kind="operator",
            authority_id="operator:primary",
            authority_revision_id="operator:revision:7",
            confirmed_at=START + timedelta(minutes=3),
        )


def test_full_reconstruction_rejects_nested_row_tampering_on_exact_replay() -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    effective_at = START + timedelta(minutes=2)
    updated, group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )
    tampered_posting: CompensatingPosting = _forged(
        group.rows[0].posting,
        delta=-19,
    )
    tampered_row: CorrectionLedgerRow = _forged(
        group.rows[0],
        posting=tampered_posting,
    )
    tampered_group: CorrectionGroup = _forged(
        group,
        rows=(tampered_row, *group.rows[1:]),
    )
    tampered_state: FinancialCorrectionState = _forged(
        updated,
        groups=(tampered_group,),
    )

    with pytest.raises(FinancialCorrectionError, match="correction row"):
        apply_financial_correction(
            tampered_state,
            proposal=proposal,
            approvals=approvals,
            effective_at=effective_at,
        )


def test_full_reconstruction_repairs_a_tampered_derived_replay_cache() -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    effective_at = START + timedelta(minutes=2)
    updated, _ = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )
    object.__setattr__(updated._replay_result.positions[0], "amount", 999)

    replayed, existing = apply_financial_correction(
        updated,
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )

    assert replayed == updated
    assert replayed is not updated
    assert existing.proposal == proposal
    assert _amounts(replayed)["balance:alice"] == 80
    assert type(replayed.positions[0].amount) is int


def test_rejected_apply_does_not_mutate_the_caller_state() -> None:
    state = _state()
    proposal = _proposal()
    opening_positions = state.opening_positions
    published_rows = state.published_rows
    authority_bindings = state.authority_bindings
    replay_result = state._replay_result

    with pytest.raises(FinancialCorrectionError, match="exactly one operator"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=(),
            effective_at=START + timedelta(minutes=2),
        )

    assert state.opening_positions is opening_positions
    assert state.published_rows is published_rows
    assert state.authority_bindings is authority_bindings
    assert state._replay_result is replay_result


def test_validated_state_rejects_identical_value_nested_subclasses() -> None:
    class ForgedRow(CorrectionLedgerRow):
        pass

    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    effective_at = START + timedelta(minutes=2)
    updated, group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )
    forged_row = object.__new__(ForgedRow)
    for field in fields(group.rows[0]):
        object.__setattr__(
            forged_row,
            field.name,
            getattr(group.rows[0], field.name),
        )
    forged_group: CorrectionGroup = _forged(
        group,
        rows=(forged_row, *group.rows[1:]),
    )
    forged_state: FinancialCorrectionState = _forged(
        updated,
        groups=(forged_group,),
    )

    with pytest.raises(FinancialCorrectionError, match="exact CorrectionLedgerRow"):
        apply_financial_correction(
            forged_state,
            proposal=proposal,
            approvals=approvals,
            effective_at=effective_at,
        )


def test_correction_history_and_proposal_cardinalities_are_bounded() -> None:
    state = _state()
    proposal = _proposal()
    updated, group = apply_financial_correction(
        state,
        proposal=proposal,
        approvals=_approvals(state, proposal),
        effective_at=START + timedelta(minutes=2),
    )

    with pytest.raises(FinancialCorrectionError, match="history limit"):
        FinancialCorrectionState(
            opening_supply=updated.opening_supply,
            opening_total_minted=updated.opening_total_minted,
            opening_snapshot_hash=updated.opening_snapshot_hash,
            opening_positions=updated.opening_positions,
            published_rows=updated.published_rows,
            authority_bindings=updated.authority_bindings,
            groups=(group,) * 65,
        )
    with pytest.raises(FinancialCorrectionError, match="affected_ledger_ids"):
        make_correction_proposal(
            correction_id="correction:too-many-references",
            affected_ledger_ids=tuple(
                f"ledger:reference:{index}" for index in range(257)
            ),
            postings=(CompensatingPosting("balance:alice", 1, "mint"),),
            idempotency_key="financial-correction:too-many-references",
        )

    large_row = make_published_ledger_row(
        "ledger:large",
        b"x" * (1024 * 1024),
    )
    with pytest.raises(FinancialCorrectionError, match="aggregate byte limit"):
        initial_financial_correction_state(
            opening_supply=175,
            opening_positions=state.opening_positions,
            published_rows=(large_row,) * 65,
            authority_bindings=state.authority_bindings,
        )


def test_64_group_ceiling_allows_exact_replay_and_rejects_new_group() -> None:
    state = _state()
    last_proposal = None
    last_approvals = None
    last_effective_at = None
    last_group = None
    for index in range(64):
        proposal = _proposal(
            correction_id=f"correction:ceiling:{index}",
            idempotency_key=f"financial-correction:ceiling:{index}",
            postings=(
                CompensatingPosting("balance:alice", -1, "transfer"),
                CompensatingPosting("balance:alice", 1, "transfer"),
            ),
        )
        approvals = _approvals(state, proposal)
        effective_at = START + timedelta(minutes=2 + index)
        state, group = apply_financial_correction(
            state,
            proposal=proposal,
            approvals=approvals,
            effective_at=effective_at,
        )
        last_proposal = proposal
        last_approvals = approvals
        last_effective_at = effective_at
        last_group = group

    assert last_proposal is not None
    assert last_approvals is not None
    assert last_effective_at is not None
    assert last_group is not None
    replayed, existing = apply_financial_correction(
        state,
        proposal=last_proposal,
        approvals=last_approvals,
        effective_at=last_effective_at,
    )
    assert replayed == state
    assert existing == last_group
    assert len(replayed.groups) == 64

    new_proposal = _proposal(
        correction_id="correction:ceiling:64",
        idempotency_key="financial-correction:ceiling:64",
        postings=(
            CompensatingPosting("balance:alice", -1, "transfer"),
            CompensatingPosting("balance:alice", 1, "transfer"),
        ),
    )
    opening_positions = replayed.opening_positions
    groups = replayed.groups
    replay_result = replayed._replay_result
    with pytest.raises(FinancialCorrectionError, match="checkpoint limit"):
        apply_financial_correction(
            replayed,
            proposal=new_proposal,
            approvals=_approvals(replayed, new_proposal),
            effective_at=START + timedelta(minutes=66),
        )
    assert replayed.opening_positions is opening_positions
    assert replayed.groups is groups
    assert replayed._replay_result is replay_result


def test_public_iterables_stop_after_limit_plus_one_items() -> None:
    def guarded_repetition(value: Any, limit: int):
        for index in range(limit + 2):
            if index == limit + 1:
                raise AssertionError("public iterable was consumed past its bound")
            yield value

    with pytest.raises(FinancialCorrectionError, match="accepted limit"):
        make_correction_proposal(
            correction_id="correction:bounded-generator",
            affected_ledger_ids=guarded_repetition(
                "ledger:history:2026-08-14:1",
                256,
            ),
            postings=(CompensatingPosting("balance:alice", 1, "mint"),),
            idempotency_key="financial-correction:bounded-generator",
        )
    with pytest.raises(FinancialCorrectionError, match="accepted limit"):
        make_correction_proposal(
            correction_id="correction:bounded-posting-generator",
            affected_ledger_ids=("ledger:history:2026-08-14:1",),
            postings=guarded_repetition(
                CompensatingPosting("balance:alice", 1, "mint"),
                128,
            ),
            idempotency_key="financial-correction:bounded-posting-generator",
        )

    state = _state()
    with pytest.raises(FinancialCorrectionError, match="accepted limit"):
        initial_financial_correction_state(
            opening_supply=175,
            opening_positions=guarded_repetition(
                state.opening_positions[0],
                10_000,
            ),
            published_rows=state.published_rows,
            authority_bindings=state.authority_bindings,
        )
    with pytest.raises(FinancialCorrectionError, match="accepted limit"):
        initial_financial_correction_state(
            opening_supply=175,
            opening_positions=state.opening_positions,
            published_rows=guarded_repetition(
                make_published_ledger_row("ledger:empty", b""),
                100_000,
            ),
            authority_bindings=state.authority_bindings,
        )
    with pytest.raises(FinancialCorrectionError, match="accepted limit"):
        initial_financial_correction_state(
            opening_supply=175,
            opening_positions=state.opening_positions,
            published_rows=state.published_rows,
            authority_bindings=guarded_repetition(
                state.authority_bindings[0],
                128,
            ),
        )

    proposal = _proposal()
    approvals = _approvals(state, proposal)
    with pytest.raises(FinancialCorrectionError, match="accepted limit"):
        apply_financial_correction(
            state,
            proposal=proposal,
            approvals=guarded_repetition(approvals[0], 2),
            effective_at=START + timedelta(minutes=2),
        )


def test_published_rows_reject_modified_content_and_subclasses() -> None:
    row = make_published_ledger_row("ledger:history:1", b'{"value":1}')
    with pytest.raises(FinancialCorrectionError, match="content hash"):
        PublishedLedgerRow(row.ledger_id, b'{"value":2}', row.content_hash)

    class ForgedState(FinancialCorrectionState):
        pass

    state = _state()
    forged = object.__new__(ForgedState)
    for field in fields(state):
        object.__setattr__(forged, field.name, getattr(state, field.name))
    with pytest.raises(FinancialCorrectionError, match="FinancialCorrectionState"):
        apply_financial_correction(
            forged,
            proposal=_proposal(),
            approvals=(),
            effective_at=START,
        )
