from __future__ import annotations

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def _ranked_state():
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=10,
        payout_vector=[5, 3, 2],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=10)
    records = []
    for sequence, agent_id, account_id in (
        (1, "agent-alpha", "account-alpha"),
        (2, "agent-beta", "account-beta"),
        (3, "agent-gamma", "account-gamma"),
    ):
        state, identifier, revision = submit_work(
            state,
            agent_id=agent_id,
            account_id=account_id,
            sequence=sequence,
        )
        records.append((identifier, revision))
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    return state, contract_id, records


def test_s_70_ranked_total_order_settles_all_ranks_atomically() -> None:
    state, contract_id, records = _ranked_state()
    event = lifecycle_event(
        state,
        "ranked_order",
        {
            "contract_id": contract_id,
            "ordered_work_ids": [item[0] for item in records],
            "selected_revision_id": records[0][1],
        },
        sequence=12,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    settled = apply_event(state, event)
    projection = modules()["lifecycle"].project_runtime(settled)
    assert projection.plan_status == "completed"
    assert [
        projection.balance(item)
        for item in ("agent-alpha", "agent-beta", "agent-gamma")
    ] == [5, 3, 2]
    assert projection.escrow.paid_wea == 10
    assert projection.escrow.refunded_wea == 0
    assert apply_event(settled, event) == settled


@pytest.mark.parametrize(
    "order",
    (
        lambda rows: [rows[0][0], rows[0][0], rows[2][0]],
        lambda rows: [rows[0][0], rows[1][0]],
        lambda rows: [rows[0][0], rows[1][0], "foreign-work"],
    ),
)
def test_s_70_invalid_ranked_order_has_no_partial_settlement(order) -> None:
    state, contract_id, records = _ranked_state()
    before = state.state_hash
    event = lifecycle_event(
        state,
        "ranked_order",
        {
            "contract_id": contract_id,
            "ordered_work_ids": order(records),
            "selected_revision_id": records[0][1],
        },
        sequence=12,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    with pytest.raises(modules()["intake"].PlanError):
        apply_event(state, event)
    assert state.state_hash == before
    assert modules()["lifecycle"].project_runtime(state).escrow.paid_wea == 0
