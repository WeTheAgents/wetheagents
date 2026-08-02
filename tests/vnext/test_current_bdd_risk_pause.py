from __future__ import annotations

import pytest

from .current_bdd_support import (
    accept_work,
    activated_runtime,
    apply_body_transition,
    apply_event,
    assign_role,
    author_event,
    digest,
    lifecycle_event,
    modules,
    resolve_role,
    stage,
    submit_role_result,
    submit_work,
)


def test_s_04b_risk_pause_blocks_payment_until_the_author_continues() -> None:
    flat = stage(
        key="options",
        depth="explore",
        mode="flat_pod",
        allocation_wea=5,
        payout_vector=[5],
        slots=1,
    )
    state = activated_runtime(plan_stages=(flat,), total_bank_wea=5)
    state = assign_role(state, sequence=1)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_warning",
            {"generation": 1, "role_id": "review-role", "warning_id": "warning-pay"},
            sequence=2,
            actor_kind="role",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_pause",
            {"warning_id": "warning-pay"},
            sequence=3,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
    )
    before = modules()["lifecycle"].project_runtime(state)

    with pytest.raises(modules()["intake"].PlanError, match="decisions"):
        accept_work(state, work_id=identifier, revision_id=revision, sequence=5)
    with pytest.raises(modules()["intake"].PlanError, match="active stage"):
        apply_event(
            state,
            lifecycle_event(
                state,
                "mode_expiry",
                {"contract_id": before.current_stage.contract.contract_id},
                sequence=11,
            ),
        )

    blocked = modules()["lifecycle"].project_runtime(state)
    assert blocked.plan_status == "paused"
    assert blocked.escrow.to_data() == before.escrow.to_data()
    state = apply_event(state, author_event(state, "author_continue", {}, sequence=5))
    state = accept_work(state, work_id=identifier, revision_id=revision, sequence=6)
    settled = modules()["lifecycle"].project_runtime(state)
    assert settled.escrow.paid_wea == 5
    assert settled.balance("agent-beta") == 5


def test_s_04b_body_resume_preserves_an_open_risk_pause() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, sequence=1)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_warning",
            {
                "generation": 1,
                "role_id": "review-role",
                "warning_id": "warning-overlap",
            },
            sequence=2,
            actor_kind="role",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_pause",
            {"warning_id": "warning-overlap"},
            sequence=3,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=4,
    )

    with pytest.raises(modules()["intake"].PlanError, match="body integrity"):
        apply_event(state, author_event(state, "author_continue", {}, sequence=5))

    state = apply_body_transition(
        state,
        "body_resume",
        body=state.activation.draft.body,
        sequence=5,
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "paused"
    assert [item.kind for item in projection.pauses if item.ended_at is None] == [
        "risk_pause"
    ]
    state, _, _ = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=6,
    )
    assert modules()["lifecycle"].project_runtime(state).plan_status == "paused"


def test_s_04b_risk_pause_keeps_only_frozen_role_obligations_open() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(
        state,
        funding="treasury",
        amount_wea=3,
        sequence=1,
    )
    state = submit_role_result(state, sequence=2)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_warning",
            {"generation": 1, "role_id": "review-role", "warning_id": "warning-role"},
            sequence=3,
            actor_kind="role",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_pause",
            {"warning_id": "warning-role"},
            sequence=4,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )

    with pytest.raises(modules()["intake"].PlanError, match="active boundary"):
        assign_role(state, role_id="new-role", sequence=5)

    state = resolve_role(state, sequence=5)
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "paused"
    assert projection.roles[0].status == "completed"
    assert projection.balance("agent-alpha") == 3
    assert projection.escrow.paid_wea == 0


def test_s_04b_risk_pause_keeps_duel_joins_and_moves_open() -> None:
    duel = stage(
        key="architecture",
        depth="explore",
        mode="duel",
        allocation_wea=20,
    )
    state = activated_runtime(plan_stages=(duel,), total_bank_wea=20)
    state = assign_role(state, sequence=1)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_warning",
            {"generation": 1, "role_id": "review-role", "warning_id": "warning-duel"},
            sequence=2,
            actor_kind="role",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
        ),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_pause",
            {"warning_id": "warning-duel"},
            sequence=3,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    for sequence, agent_id, account_id, position in (
        (4, "agent-alpha", "account-alpha", "a"),
        (5, "agent-beta", "account-beta", "b"),
    ):
        state = apply_event(
            state,
            lifecycle_event(
                state,
                "duel_join",
                {"contract_id": contract_id, "position": position},
                sequence=sequence,
                actor_kind="agent",
                actor_id=agent_id,
                actor_account_id=account_id,
            ),
        )
    lifecycle = modules()["lifecycle"]
    identifier = lifecycle.work_id(contract_id, "agent-alpha")
    revision_id = lifecycle.work_revision_id(identifier, 1)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "duel_move",
            {
                "content_hash": digest("first move"),
                "contract_id": contract_id,
                "move_number": 1,
                "revision_id": revision_id,
            },
            sequence=6,
            actor_kind="agent",
            actor_id="agent-alpha",
            actor_account_id="account-alpha",
        ),
    )

    projection = lifecycle.project_runtime(state)
    assert projection.plan_status == "paused"
    assert projection.current_stage.phase == "moves"
    assert projection.current_stage.works[0].revisions[0].revision_id == revision_id


def test_s_04b_assigned_warning_needs_agent0_and_keeps_author_decision() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, sequence=1)
    warning = lifecycle_event(
        state,
        "risk_warning",
        {"generation": 1, "role_id": "review-role", "warning_id": "warning-1"},
        sequence=2,
        actor_kind="role",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
    )
    state = apply_event(state, warning)
    before_pause = modules()["lifecycle"].project_runtime(state)
    assert before_pause.plan_status == "active"
    before_money = before_pause.escrow.to_data()

    pause = lifecycle_event(
        state,
        "risk_pause",
        {"warning_id": "warning-1"},
        sequence=3,
        actor_kind="agent0",
        actor_id="agent0@system",
        actor_account_id="account-agent0",
    )
    state = apply_event(state, pause)
    paused = modules()["lifecycle"].project_runtime(state)
    assert paused.plan_status == "paused"
    assert paused.escrow.to_data() == before_money
    contract_before = paused.current_stage.contract.to_data()

    state, _, _ = submit_work(
        state,
        agent_id="agent-beta",
        account_id="account-beta",
        sequence=4,
    )
    still_paused = modules()["lifecycle"].project_runtime(state)
    assert still_paused.plan_status == "paused"
    assert len(still_paused.current_stage.works) == 1
    assert still_paused.current_stage.contract.to_data() == contract_before

    continued = apply_event(
        state, author_event(state, "author_continue", {}, sequence=5)
    )
    assert modules()["lifecycle"].project_runtime(continued).plan_status == "active"


def test_s_04b_unassigned_warning_cannot_support_a_risk_pause() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    warning = lifecycle_event(
        state,
        "risk_warning",
        {"generation": 1, "role_id": "missing-role", "warning_id": "warning-x"},
        sequence=1,
        actor_kind="role",
        actor_id="agent-beta",
        actor_account_id="account-beta",
    )
    with pytest.raises(modules()["intake"].PlanError, match="exact active"):
        apply_event(state, warning)
    assert modules()["lifecycle"].project_runtime(state).plan_status == "active"


def test_s_04b_stale_role_generation_cannot_publish_a_risk_warning() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, sequence=1)
    state = submit_role_result(state, sequence=2)
    state = resolve_role(state, sequence=3)
    warning = lifecycle_event(
        state,
        "risk_warning",
        {"generation": 1, "role_id": "review-role", "warning_id": "stale"},
        sequence=4,
        actor_kind="role",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
    )
    with pytest.raises(modules()["intake"].PlanError, match="exact active"):
        apply_event(state, warning)


def test_s_04b_non_review_role_cannot_publish_a_risk_warning() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(state, role_kind="implementation", sequence=1)
    warning = lifecycle_event(
        state,
        "risk_warning",
        {"generation": 1, "role_id": "review-role", "warning_id": "wrong-kind"},
        sequence=2,
        actor_kind="role",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
    )
    with pytest.raises(modules()["intake"].PlanError, match="Triage or review"):
        apply_event(state, warning)
