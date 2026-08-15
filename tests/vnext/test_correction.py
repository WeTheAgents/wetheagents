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
) -> FinancialCorrectionState:
    return FinancialCorrectionState(
        opening_supply=state.opening_supply,
        opening_total_minted=state.opening_total_minted,
        opening_positions=state.opening_positions,
        published_rows=state.published_rows,
        authority_bindings=state.authority_bindings,
        groups=state.groups if groups is None else groups,
        idempotency_records=state.idempotency_records,
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

    assert replayed is updated
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
