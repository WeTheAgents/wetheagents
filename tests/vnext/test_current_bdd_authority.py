from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from wea_vnext import resolution_plan

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    decision,
    digest,
    github_state,
    lifecycle_event,
    modules,
    record_decision,
    registry,
    replace_decision,
    stage,
    state_with_plan,
)


def test_s_01c_verified_wrapper_does_not_store_authority_calls_or_runtime() -> None:
    lifecycle = resolution_plan.make_lifecycle_event.__globals__["_LIFECYCLE"]

    with pytest.raises(AttributeError):
        object.__getattribute__(lifecycle, "_ReadOnlyModule__verified_calls")
    with pytest.raises(AttributeError):
        object.__getattribute__(lifecycle, "_ReadOnlyModule__reference")

    raw_module = object.__getattribute__(lifecycle, "_ReadOnlyModule__module")
    assert "apply_lifecycle_event" not in vars(raw_module)
    assert "_WEA_VERIFIER_CAPABILITY" not in vars(raw_module)


def test_s_01c_validator_cannot_impersonate_a_participant_or_role() -> None:
    duel = stage(
        key="duel",
        depth="explore",
        mode="duel",
        allocation_wea=20,
    )
    state = activated_runtime(plan_stages=(duel,), total_bank_wea=20)
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    forged_join = lifecycle_event(
        state,
        "duel_join",
        {"contract_id": contract_id, "position": "a"},
        sequence=1,
        actor_kind="validator",
        actor_id="forged-agent",
        actor_account_id="unbound-account",
    )
    with pytest.raises(modules()["intake"].PlanError, match="exact actor kind"):
        apply_event(state, forged_join)
    assert modules()["lifecycle"].project_runtime(state).current_stage.works == ()

    stop = lifecycle_event(
        state,
        "author_stop",
        {},
        sequence=2,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    stopped = apply_event(
        state,
        stop,
        evidence_state=github_state(forged_join, stop),
    )
    assert modules()["lifecycle"].project_runtime(stopped).plan_status == "stopped"

    state = assign_role(state, generation=1, sequence=1)
    before = state.state_hash
    forged_result = lifecycle_event(
        state,
        "role_result",
        {
            "generation": 1,
            "result_hash": digest("forged-role-result"),
            "role_id": "review-role",
            "target_id": "target-a",
        },
        sequence=2,
        actor_kind="validator",
        actor_id="agent-alpha",
        actor_account_id="account-alpha",
    )
    with pytest.raises(modules()["intake"].PlanError, match="exact actor kind"):
        apply_event(state, forged_result)
    assert state.state_hash == before


def test_s_01c_lifecycle_rejects_a_registry_mutated_after_validation() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    event = lifecycle_event(
        state,
        "author_stop",
        {},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    tampered = registry()
    object.__setattr__(tampered, "bindings", ())

    with pytest.raises(modules()["intake"].PlanError, match="registry changed"):
        modules()["lifecycle"].call_verified(
            "apply_lifecycle_event",
            state,
            event,
            registry=tampered,
            github_state=github_state(event),
        )

    assert modules()["lifecycle"].project_runtime(state).plan_status == "active"


def test_s_01c_lifecycle_requires_exact_accepted_github_source() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    event = lifecycle_event(
        state,
        "author_stop",
        {},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
    conflicting_source = lifecycle_event(
        state,
        "author_stop",
        {"forged": True},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )

    for evidence in (github_state(), github_state(conflicting_source)):
        with pytest.raises(
            modules()["intake"].PlanError,
            match=r"GitHub revision is missing|content does not match",
        ):
            apply_event(state, event, evidence_state=evidence)

    assert modules()["lifecycle"].project_runtime(state).plan_status == "active"


def test_s_01c_lifecycle_idempotency_key_is_deterministic() -> None:
    state = activated_runtime()
    event = lifecycle_event(
        state,
        "author_stop",
        {},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )

    with pytest.raises(
        modules()["intake"].PlanError,
        match="lifecycle idempotency key is not deterministic",
    ):
        replace(event, idempotency_key="caller-selected-key")


def test_s_01c_lifecycle_event_cannot_predate_plan_activation() -> None:
    ranked = stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    before = state.state_hash
    event = lifecycle_event(
        state,
        "author_stop",
        {},
        sequence=1,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
        effective_at=state.activation.plan.activated_at - timedelta(microseconds=1),
    )

    with pytest.raises(modules()["intake"].PlanError, match="predates"):
        apply_event(state, event)

    assert state.state_hash == before
    assert modules()["lifecycle"].project_runtime(state).plan_status == "active"


def test_s_01c_non_author_cannot_approve_a_plan() -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    valid = decision(plan)
    invalid = replace_decision(
        valid,
        author_agent_id="agent-reviewer",
        author_github_account_id="account-reviewer",
        author_binding_id="reviewer-binding",
    )
    before = state.state_hash

    with pytest.raises(intake.PlanError, match="author"):
        record_decision(state, draft, invalid)

    assert state.state_hash == before
    assert state.plans == state.escrows == state.contracts == state.tasks == ()


def test_s_01c_operator_or_agent0_cannot_replace_author_approval() -> None:
    intake = modules()["intake"]
    state, draft, _, plan = state_with_plan()
    valid = decision(plan)
    for account_id, agent_id, binding_id in (
        ("account-agent0", "agent0@system", "agent0-role-binding"),
        ("unknown-account", "operator@system", "unknown-binding"),
    ):
        invalid = replace_decision(
            valid,
            author_agent_id=agent_id,
            author_github_account_id=account_id,
            author_binding_id=binding_id,
        )
        with pytest.raises(intake.PlanError):
            record_decision(state, draft, invalid)

    assert state.plans == state.escrows == state.ledger == ()
