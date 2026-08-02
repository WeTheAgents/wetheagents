from __future__ import annotations

import pytest

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_event,
    author_event,
    digest,
    github_state,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def test_s_02b_stop_preserves_legal_settlement_and_refunds_unused_bank() -> None:
    flat = stage(
        key="answers",
        depth="explore",
        mode="flat_pod",
        allocation_wea=6,
        payout_vector=[2, 2, 2],
        slots=3,
    )
    state = activated_runtime(plan_stages=(flat,), total_bank_wea=6)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
    )
    state = accept_work(state, work_id=identifier, revision_id=revision, sequence=2)
    stopped = apply_event(state, author_event(state, "author_stop", {}, sequence=3))
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.balance("agent-alpha") == 2
    assert projection.escrow.paid_wea == 2
    assert projection.escrow.refunded_wea == 4
    assert projection.current_task.status == "closed"
    assert projection.current_task.close_result == "stopped"

    before = stopped.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="terminal"):
        submit_work(
            stopped,
            agent_id="agent-beta",
            account_id="account-beta",
            sequence=4,
        )
    assert stopped.state_hash == before


def test_s_02b_stop_cannot_skip_earlier_accepted_work_declarations() -> None:
    flat = stage(
        key="answers",
        depth="explore",
        mode="flat_pod",
        allocation_wea=6,
        payout_vector=[2, 2, 2],
        slots=3,
    )
    state = activated_runtime(plan_stages=(flat,), total_bank_wea=6)
    lifecycle = modules()["lifecycle"]
    contract_id = lifecycle.project_runtime(state).current_stage.contract.contract_id
    identifier = lifecycle.work_id(contract_id, "agent-alpha")
    revision_id = lifecycle.work_revision_id(identifier, 1)
    work = lifecycle_event(
        state,
        "work_revision",
        {
            "content_hash": digest(revision_id),
            "contract_id": contract_id,
            "eligible": True,
            "normalized_output": None,
            "revision_id": revision_id,
            "snapshot": None,
        },
        sequence=1,
        actor_kind="agent",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
    )
    acceptance = lifecycle_event(
        state,
        "work_acceptance",
        {
            "contract_id": contract_id,
            "novel": True,
            "revision_id": revision_id,
            "verdict": "accept",
            "work_id": identifier,
        },
        sequence=2,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    stop = author_event(state, "author_stop", {}, sequence=3)
    evidence = github_state(work, acceptance, stop)

    for earlier in (work, acceptance):
        before = state.state_hash
        with pytest.raises(
            modules()["intake"].PlanError,
            match="earlier accepted lifecycle declaration remains unapplied",
        ):
            apply_event(state, stop, evidence_state=evidence)
        assert state.state_hash == before
        state = apply_event(state, earlier, evidence_state=evidence)

    stopped = apply_event(state, stop, evidence_state=evidence)
    projection = lifecycle.project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.balance("agent-alpha") == 2
    assert projection.escrow.paid_wea == 2
    assert projection.escrow.refunded_wea == 4
