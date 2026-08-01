from __future__ import annotations

import pytest

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)

VALIDATOR = ("normalized-code", "1")


def _frontier():
    return stage(
        key="frontier",
        depth="explore",
        mode="frontier",
        allocation_wea=6,
        payout_vector=[1, 2, 3],
        acceptance={
            "kind": "normalized_validator",
            "validator_id": VALIDATOR[0],
            "version": VALIDATOR[1],
        },
    )


def test_s_61_frontier_pays_only_valid_novel_unique_snapshots() -> None:
    state = activated_runtime(plan_stages=(_frontier(),), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    state = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
        validator=VALIDATOR,
    )
    assert modules()["lifecycle"].project_runtime(state).escrow.paid_wea == 1

    with pytest.raises(modules()["intake"].PlanError, match="snapshot"):
        submit_work(
            state,
            agent_id="agent-beta",
            account_id="account-beta",
            sequence=3,
            snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
        )
    state, second_work, second_revision = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
        snapshot={"model": "m2", "genome": "g2", "runtime": "r2"},
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="prior art"):
        accept_work(
            state,
            work_id=second_work,
            revision_id=second_revision,
            sequence=5,
            novel=False,
            validator=VALIDATOR,
        )
    assert state.state_hash == before


def test_s_62_validator_defers_semantic_novelty_to_exact_author() -> None:
    state = activated_runtime(plan_stages=(_frontier(),), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    deferred = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
        verdict="needs_author",
        validator=VALIDATOR,
    )
    projection = modules()["lifecycle"].project_runtime(deferred)
    assert projection.escrow.paid_wea == 0
    assert projection.current_stage.works[0].needs_author is True

    accepted = accept_work(
        deferred,
        work_id=identifier,
        revision_id=revision,
        sequence=3,
    )
    assert modules()["lifecycle"].project_runtime(accepted).escrow.paid_wea == 1


def test_s_63_author_closes_frontier_and_refunds_unused_suffix() -> None:
    state = activated_runtime(plan_stages=(_frontier(),), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
        snapshot={"model": "m1", "genome": "g1", "runtime": "r1"},
    )
    state = accept_work(
        state,
        work_id=identifier,
        revision_id=revision,
        sequence=2,
        validator=VALIDATOR,
    )
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "frontier_close",
            {"contract_id": contract_id, "selected_revision_id": revision},
            sequence=3,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "completed"
    assert projection.escrow.paid_wea == 1
    assert projection.escrow.refunded_wea == 5
