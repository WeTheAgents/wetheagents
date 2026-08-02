from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    assign_role,
    author_event,
    lifecycle_event,
    modules,
    resolve_role,
    stage,
    submit_role_result,
    submit_work,
)


def _complete_ranked(depth: str):
    ranked = stage(
        key=f"{depth}-stage",
        depth=depth,
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state, identifier, revision = submit_work(
        state,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=1,
    )
    contract_id = (
        modules()["lifecycle"].project_runtime(state).current_stage.contract.contract_id
    )
    state = apply_event(
        state,
        lifecycle_event(
            state, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    return apply_event(
        state,
        author_event(
            state,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [identifier],
                "selected_revision_id": revision,
            },
            sequence=12,
        ),
    )


def test_s_67_release_depends_on_implement_depth_or_completed_role() -> None:
    explore = modules()["lifecycle"].project_runtime(_complete_ranked("explore"))
    spec = modules()["lifecycle"].project_runtime(_complete_ranked("spec"))
    implement = modules()["lifecycle"].project_runtime(_complete_ranked("implement"))
    assert not any(item.source_kind == "implement_work" for item in explore.releases)
    assert not any(item.source_kind == "implement_work" for item in spec.releases)
    assert any(
        item.source_kind == "implement_work"
        and item.recipient_agent_id == "agent-alpha"
        for item in implement.releases
    )

    ranked = stage(
        key="explore-stage",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(ranked,), total_bank_wea=5)
    state = assign_role(
        state,
        assigned_agent_id="agent-beta",
        assigned_account_id="account-beta",
        sequence=1,
    )
    state = submit_role_result(
        state,
        assigned_agent_id="agent-beta",
        assigned_account_id="account-beta",
        sequence=2,
    )
    state = resolve_role(state, sequence=3)
    projection = modules()["lifecycle"].project_runtime(state)
    assert any(
        item.source_kind == "role" and item.recipient_agent_id == "agent-beta"
        for item in projection.releases
    )
