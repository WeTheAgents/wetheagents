from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_body_transition,
    apply_event,
    assign_role,
    author_event,
    common_control_registry,
    confirm_control_disclosure,
    digest,
    lifecycle_event,
    modules,
    stage,
)


def _duel_state():
    duel = stage(
        key="architecture-duel",
        depth="explore",
        mode="duel",
        allocation_wea=20,
    )
    return activated_runtime(plan_stages=(duel,), total_bank_wea=20)


def _join(
    state,
    agent_id,
    account_id,
    position,
    sequence,
    *,
    identity_registry=None,
):
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    return apply_event(
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
        identity_registry=identity_registry,
    )


def _move(
    state,
    agent_id,
    account_id,
    number,
    sequence,
    *,
    identity_registry=None,
    effective_at=None,
):
    lifecycle = modules()["lifecycle"]
    projection = lifecycle.project_runtime(state)
    contract_id = projection.current_stage.contract.contract_id
    identifier = lifecycle.work_id(contract_id, agent_id)
    work = next(
        (item for item in projection.current_stage.works if item.work_id == identifier),
        None,
    )
    revision_id = lifecycle.work_revision_id(
        identifier, 1 if work is None else len(work.revisions) + 1
    )
    return apply_event(
        state,
        lifecycle_event(
            state,
            "duel_move",
            {
                "content_hash": digest(f"duel-{agent_id}-{number}"),
                "contract_id": contract_id,
                "move_number": number,
                "revision_id": revision_id,
            },
            sequence=sequence,
            actor_kind="agent",
            actor_id=agent_id,
            actor_account_id=account_id,
            effective_at=effective_at,
        ),
        identity_registry=identity_registry,
    )


def _move_expiry(state, contract_id):
    current = modules()["lifecycle"].project_runtime(state).current_stage
    due = next(
        item.effective_due_at for item in current.deadlines if item.kind == "move-6"
    )
    return lifecycle_event(
        state,
        "mode_expiry",
        {"contract_id": contract_id},
        sequence=8,
        effective_at=due + timedelta(microseconds=1),
    )


def test_s_08_duel_second_join_materializes_six_moves_and_winner_split() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    projection = modules()["lifecycle"].project_runtime(state)
    assert [item.kind for item in projection.current_stage.deadlines[-6:]] == [
        "move-1",
        "move-2",
        "move-3",
        "move-4",
        "move-5",
        "move-6",
    ]
    for number in range(1, 7):
        if number % 2:
            agent_id, account_id = "agent-alpha", "account-alpha"
        else:
            agent_id, account_id = "agent-beta", "account-beta"
        state = _move(state, agent_id, account_id, number, number + 2)
        if number == 5:
            current = modules()["lifecycle"].project_runtime(state).current_stage
            assert current.phase == "moves"
            assert any(item.kind == "author_decision" for item in current.deadlines)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        author_event(
            state,
            "duel_decision",
            {
                "contract_id": contract_id,
                "outcome": "winner",
                "winner_agent_id": "agent-alpha",
            },
            sequence=9,
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "completed"
    assert projection.balance("agent-alpha") == 18
    assert projection.balance("agent-beta") == 2
    assert not any(
        item.recipient_agent_id in {"agent-alpha", "agent-beta"}
        for item in projection.releases
    )


def test_s_08a_duel_no_completers_refunds_and_has_no_release() -> None:
    state = _duel_state()
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "stopped"
    assert projection.escrow.refunded_wea == 20
    assert projection.releases == ()


def test_s_08a_duel_stop_refunds_an_active_role_escrow() -> None:
    state = assign_role(
        _duel_state(),
        targets=("a", "b"),
        funding="treasury",
        amount_wea=3,
        sequence=1,
    )
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    stopped = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.roles[0].status == "stopped"
    assert projection.roles[0].escrow_available_wea == 0
    assert projection.balance("treasury") == 100
    assert [item.kind for item in projection.settlements] == [
        "treasury-reserve",
        "treasury-refund",
        "refund",
    ]


def test_s_08b_duel_rejects_duplicate_position_and_out_of_order_move() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    with pytest.raises(modules()["intake"].PlanError, match="distinct"):
        _join(state, "agent-beta", "account-beta", "a", 2)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    before = state.state_hash
    before_window = state.activation.plan.activated_at + timedelta(
        minutes=2, seconds=30
    )
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    identifier = modules()["lifecycle"].work_id(contract_id, "agent-beta")
    event = lifecycle_event(
        state,
        "duel_move",
        {
            "content_hash": digest("early move"),
            "contract_id": contract_id,
            "move_number": 2,
            "revision_id": modules()["lifecycle"].work_revision_id(identifier, 1),
        },
        sequence=3,
        actor_kind="agent",
        actor_id="agent-beta",
        actor_account_id="account-beta",
        effective_at=before_window,
    )
    with pytest.raises(modules()["intake"].PlanError, match="window"):
        apply_event(state, event)
    assert state.state_hash == before

    boundary = next(
        item.effective_due_at
        for item in modules()["lifecycle"]
        .project_runtime(state)
        .current_stage.deadlines
        if item.kind == "move-1"
    )
    move_two = lifecycle_event(
        state,
        "duel_move",
        {
            "content_hash": digest("move two at shared boundary"),
            "contract_id": contract_id,
            "move_number": 2,
            "revision_id": modules()["lifecycle"].work_revision_id(identifier, 1),
        },
        sequence=4,
        actor_kind="agent",
        actor_id="agent-beta",
        actor_account_id="account-beta",
        effective_at=boundary,
    )
    state = apply_event(state, move_two)
    alpha_work = modules()["lifecycle"].work_id(contract_id, "agent-alpha")
    reverse_move = lifecycle_event(
        state,
        "duel_move",
        {
            "content_hash": digest("reverse move one"),
            "contract_id": contract_id,
            "move_number": 1,
            "revision_id": modules()["lifecycle"].work_revision_id(alpha_work, 1),
        },
        sequence=5,
        actor_kind="agent",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
        effective_at=boundary,
    )
    before_reverse = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="move order"):
        apply_event(state, reverse_move)
    assert state.state_hash == before_reverse


def test_s_08_single_completer_gets_90_percent_and_selected_output() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = _move(state, "agent-alpha", "account-alpha", 1, 3)
    state = _move(state, "agent-alpha", "account-alpha", 3, 5)
    state = _move(state, "agent-alpha", "account-alpha", 5, 7)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    stage_projection = modules()["lifecycle"].project_runtime(state).current_stage
    decision_deadline = next(
        item for item in stage_projection.deadlines if item.kind == "author_decision"
    )
    assert stage_projection.phase == "moves"
    assert decision_deadline.effective_anchor_at == stage_projection.duel_moves[-1][2]
    author_action = modules()["lifecycle"].next_action(state, "agent-author")
    participant_action = modules()["lifecycle"].next_action(state, "agent-beta")
    assert author_action.action == "publish the exact Duel outcome"
    assert author_action.boundary_at == decision_deadline.effective_due_at
    assert participant_action.action == "publish the next Duel move"
    state = apply_event(
        state,
        author_event(
            state,
            "duel_decision",
            {
                "contract_id": contract_id,
                "outcome": "single_completer",
                "winner_agent_id": "agent-alpha",
            },
            sequence=9,
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "completed"
    assert projection.balance("agent-alpha") == 18
    assert projection.balance("agent-beta") == 0
    assert projection.escrow.refunded_wea == 2
    selected = projection.current_stage.selected_revision_id
    assert selected == projection.current_stage.works[0].revisions[-1].revision_id


def test_s_03f_common_control_blocks_duel_selection_and_settlement() -> None:
    identity_registry = common_control_registry("agent-alpha")
    state = _join(
        _duel_state(),
        "agent-alpha",
        "account-alpha",
        "a",
        1,
        identity_registry=identity_registry,
    )
    state = _join(
        state,
        "agent-beta",
        "account-beta",
        "b",
        2,
        identity_registry=identity_registry,
    )
    for number, sequence in ((1, 3), (3, 5), (5, 7)):
        state = _move(
            state,
            "agent-alpha",
            "account-alpha",
            number,
            sequence,
            identity_registry=identity_registry,
        )
    projection = modules()["lifecycle"].project_runtime(state)
    contract_id = projection.current_stage.contract.contract_id
    alpha_work = next(
        item
        for item in projection.current_stage.works
        if item.agent_id == "agent-alpha"
    )
    assert alpha_work.authority.disclosure is not None
    expiry = _move_expiry(state, contract_id)
    decision = lifecycle_event(
        state,
        "duel_decision",
        {
            "contract_id": contract_id,
            "outcome": "single_completer",
            "winner_agent_id": "agent-alpha",
        },
        sequence=17,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
        effective_at=expiry.effective_at + timedelta(seconds=5),
    )
    with pytest.raises(modules()["intake"].PlanError, match="common-control"):
        apply_event(state, decision, identity_registry=identity_registry)
    assert modules()["lifecycle"].project_runtime(state).escrow.paid_wea == 0

    state = confirm_control_disclosure(
        state,
        work_id=alpha_work.work_id,
        sequence=18,
        identity_registry=identity_registry,
        effective_at=expiry.effective_at + timedelta(seconds=10),
    )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "duel_decision",
            {
                "contract_id": contract_id,
                "outcome": "single_completer",
                "winner_agent_id": "agent-alpha",
            },
            sequence=19,
            actor_kind="author",
            actor_id="agent-author",
            actor_account_id="account-author",
            effective_at=expiry.effective_at + timedelta(seconds=20),
        ),
        identity_registry=identity_registry,
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "completed"
    assert projection.balance("agent-alpha") == 18


def test_s_08e_inconclusive_duel_splits_bank_equally() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    for number in range(1, 7):
        agent_id, account_id = (
            ("agent-alpha", "account-alpha")
            if number % 2
            else ("agent-beta", "account-beta")
        )
        state = _move(state, agent_id, account_id, number, number + 2)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        author_event(
            state,
            "duel_decision",
            {
                "contract_id": contract_id,
                "outcome": "inconclusive",
                "winner_agent_id": None,
            },
            sequence=9,
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.balance("agent-alpha") == 10
    assert projection.balance("agent-beta") == 10
    assert projection.escrow.refunded_wea == 0


def test_s_08f_no_completer_after_six_windows_stops_and_refunds() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = _move(state, "agent-alpha", "account-alpha", 1, 3)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    expiry = _move_expiry(state, contract_id)
    state = apply_event(state, expiry)
    replay = apply_event(state, expiry)
    projection = modules()["lifecycle"].project_runtime(state)
    assert replay == state
    assert projection.plan_status == "stopped"
    assert projection.escrow.refunded_wea == 20
    assert projection.escrow.paid_wea == 0


def test_s_08f_accepted_final_move_with_no_completer_stops_immediately() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = _move(state, "agent-beta", "account-beta", 6, 8)

    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "stopped"
    assert projection.current_stage.phase == "closed"
    assert projection.current_task.close_result == "stopped"
    assert projection.escrow.refunded_wea == 20
    assert projection.escrow.paid_wea == 0
    assert projection.current_stage.duel_moves[-1][0] == 6


def test_s_04b_risk_pause_defers_final_move_stop_until_continue() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = assign_role(state, sequence=3)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "risk_warning",
            {"generation": 1, "role_id": "review-role", "warning_id": "duel-risk"},
            sequence=4,
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
            {"warning_id": "duel-risk"},
            sequence=5,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    state = _move(state, "agent-beta", "account-beta", 6, 8)
    paused = modules()["lifecycle"].project_runtime(state)
    assert paused.plan_status == "paused"
    assert paused.escrow.refunded_wea == 0
    assert paused.current_stage.duel_moves[-1][0] == 6

    state = apply_event(
        state, author_event(state, "author_continue", {}, sequence=9)
    )
    action = modules()["lifecycle"].next_action(state, "agent-author")
    assert action.action == "wait for Tide to close the Duel"
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=10
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "stopped"
    assert projection.escrow.refunded_wea == 20


def test_s_08g_remaining_move_cannot_outlive_early_decision_deadline() -> None:
    intake = modules()["intake"]
    duel = stage(
        key="short-decision-duel",
        depth="explore",
        mode="duel",
        allocation_wea=20,
    )
    duel = replace(
        duel,
        schedule=intake.StageSchedule(
            join_seconds=600,
            move_seconds=(60, 60, 60, 60, 60, 60),
            author_decision_seconds=30,
        ),
    )
    state = activated_runtime(plan_stages=(duel,), total_bank_wea=20)
    state = _join(state, "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = _move(state, "agent-alpha", "account-alpha", 1, 3)
    state = _move(state, "agent-alpha", "account-alpha", 3, 5)
    state = _move(state, "agent-alpha", "account-alpha", 5, 7)
    deadline = next(
        item
        for item in modules()["lifecycle"]
        .project_runtime(state)
        .current_stage.deadlines
        if item.kind == "author_decision"
    )

    with pytest.raises(modules()["intake"].PlanError, match="boundary has expired"):
        _move(
            state,
            "agent-beta",
            "account-beta",
            6,
            8,
            effective_at=deadline.effective_due_at + timedelta(microseconds=1),
        )
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "mode_expiry",
            {
                "contract_id": modules()["lifecycle"]
                .project_runtime(state)
                .current_stage.contract.contract_id
            },
            sequence=9,
            effective_at=deadline.effective_due_at + timedelta(microseconds=1),
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "stopped"
    assert projection.escrow.refunded_wea == 20


def test_s_08g_invalid_or_missing_author_decision_never_pays() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = _move(state, "agent-alpha", "account-alpha", 1, 3)
    state = _move(state, "agent-alpha", "account-alpha", 3, 5)
    state = _move(state, "agent-alpha", "account-alpha", 5, 7)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        _move_expiry(state, contract_id),
    )
    before = state.state_hash
    with pytest.raises(modules()["intake"].PlanError, match="two completers"):
        apply_event(
            state,
            author_event(
                state,
                "duel_decision",
                {
                    "contract_id": contract_id,
                    "outcome": "winner",
                    "winner_agent_id": "agent-beta",
                },
                sequence=9,
            ),
        )
    assert state.state_hash == before
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=14
        ),
    )
    projection = modules()["lifecycle"].project_runtime(state)
    assert projection.plan_status == "stopped"
    assert projection.escrow.paid_wea == 0
    assert projection.escrow.refunded_wea == 20


def test_s_08c_invited_join_and_exact_join_boundary_are_enforced() -> None:
    duel = stage(
        key="invited-duel",
        depth="explore",
        mode="duel",
        allocation_wea=20,
        duel_admission="invited",
        duel_invitations=[
            {"agent_id": "agent-alpha", "position": "a"},
            {"agent_id": "agent-beta", "position": "b"},
        ],
    )
    state = activated_runtime(plan_stages=(duel,), total_bank_wea=20)
    with pytest.raises(modules()["intake"].PlanError, match="own Duel"):
        _join(state, "agent-author", "account-author", "a", 1)
    with pytest.raises(modules()["intake"].PlanError, match="not invited"):
        _join(state, "agent-gamma", "account-gamma", "a", 2)
    with pytest.raises(modules()["intake"].PlanError, match="not invited"):
        _join(state, "agent-alpha", "account-alpha", "b", 3)
    boundary = state.activation.plan.activated_at + timedelta(minutes=10)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    for sequence, (agent_id, account_id, position) in enumerate(
        (
            ("agent-alpha", "account-alpha", "a"),
            ("agent-beta", "account-beta", "b"),
        ),
        start=10,
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
                effective_at=boundary,
            ),
        )
    assert modules()["lifecycle"].project_runtime(state).current_stage.phase == "moves"
    with pytest.raises(modules()["intake"].PlanError, match="does not apply"):
        _join(state, "agent-gamma", "account-gamma", "a", 12)


def test_s_08d_body_pause_offsets_active_and_future_duel_windows_once() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    pause_at = state.activation.plan.activated_at + timedelta(minutes=3)
    resume_at = pause_at + timedelta(minutes=2)
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=3,
        effective_at=pause_at,
    )
    state = apply_body_transition(
        state,
        "body_resume",
        body=state.activation.draft.body,
        sequence=5,
        effective_at=resume_at,
    )
    deadlines = {
        item.kind: item
        for item in modules()["lifecycle"]
        .project_runtime(state)
        .current_stage.deadlines
    }
    assert deadlines["move-1"].effective_due_at == pause_at
    assert deadlines["move-2"].effective_anchor_at == pause_at
    assert deadlines["move-2"].effective_due_at == resume_at + timedelta(minutes=1)
    assert (
        deadlines["move-3"].effective_anchor_at == deadlines["move-2"].effective_due_at
    )
    assert all(len(item.pause_ids) <= 1 for item in deadlines.values())


def test_s_08d_body_pause_offsets_open_move_and_early_decision_once() -> None:
    state = _join(_duel_state(), "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    state = _move(state, "agent-alpha", "account-alpha", 1, 3)
    state = _move(state, "agent-alpha", "account-alpha", 3, 5)
    state = _move(state, "agent-alpha", "account-alpha", 5, 7)
    lifecycle = modules()["lifecycle"]
    before = {
        item.kind: item.effective_due_at
        for item in lifecycle.project_runtime(state).current_stage.deadlines
        if item.kind in {"move-6", "author_decision"}
    }
    pause_at = state.activation.plan.activated_at + timedelta(minutes=7, seconds=30)
    resume_at = pause_at + timedelta(minutes=1)
    state = apply_body_transition(
        state,
        "body_pause",
        body="Changed Issue body",
        sequence=20,
        effective_at=pause_at,
    )
    state = apply_body_transition(
        state,
        "body_resume",
        body=state.activation.draft.body,
        sequence=21,
        effective_at=resume_at,
    )
    after = {
        item.kind: item
        for item in lifecycle.project_runtime(state).current_stage.deadlines
        if item.kind in {"move-6", "author_decision"}
    }
    assert set(after) == {"move-6", "author_decision"}
    for kind in after:
        assert after[kind].effective_due_at == before[kind] + timedelta(minutes=1)
        assert len(after[kind].pause_ids) == 1


def test_duel_winner_revision_materializes_the_next_stage_input() -> None:
    intake = modules()["intake"]
    duel = stage(
        key="architecture",
        depth="explore",
        mode="duel",
        allocation_wea=20,
    )
    specification = stage(
        key="specification",
        depth="spec",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
        inputs=(intake.SelectedWorkInput("architecture"),),
    )
    state = activated_runtime(plan_stages=(duel, specification), total_bank_wea=25)
    state = _join(state, "agent-alpha", "account-alpha", "a", 1)
    state = _join(state, "agent-beta", "account-beta", "b", 2)
    for number in range(1, 7):
        agent_id, account_id = (
            ("agent-alpha", "account-alpha")
            if number % 2
            else ("agent-beta", "account-beta")
        )
        state = _move(state, agent_id, account_id, number, number + 2)
    projection = modules()["lifecycle"].project_runtime(state)
    duel_contract_id = projection.current_stage.contract.contract_id
    alpha = next(
        item
        for item in projection.current_stage.works
        if item.agent_id == "agent-alpha"
    )
    expected = alpha.revisions[-1]
    state = apply_event(
        state,
        author_event(
            state,
            "duel_decision",
            {
                "contract_id": duel_contract_id,
                "outcome": "winner",
                "winner_agent_id": "agent-alpha",
            },
            sequence=9,
        ),
    )
    resolved = (
        modules()["lifecycle"]
        .project_runtime(state)
        .current_stage.contract.resolved_inputs
    )
    assert len(resolved) == 1
    assert resolved[0].revision_id == expected.revision_id
    assert resolved[0].content_hash == expected.content_hash
