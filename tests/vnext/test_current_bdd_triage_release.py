from __future__ import annotations

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    author_event,
    lifecycle_event,
    modules,
    stage,
    submit_work,
)


def _ranked():
    return stage(
        key="rank",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )


def test_s_10_triage_release_waits_for_successful_whole_plan() -> None:
    stopped = activated_runtime(plan_stages=(_ranked(),), total_bank_wea=5)
    stopped = apply_event(stopped, author_event(stopped, "author_stop", {}, sequence=1))
    stopped_projection = modules()["lifecycle"].project_runtime(stopped)
    assert not any(item.source_kind == "triage" for item in stopped_projection.releases)

    blocked = activated_runtime(plan_stages=(_ranked(),), total_bank_wea=5)
    blocked = apply_event(
        blocked,
        lifecycle_event(
            blocked,
            "downstream_blocker",
            {"reason": "Spec found an irreconcilable contradiction"},
            sequence=1,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    blocked_projection = modules()["lifecycle"].project_runtime(blocked)
    assert not any(item.source_kind == "triage" for item in blocked_projection.releases)
    assert blocked_projection.triage_feedback[-1].polarity == "negative"
    assert "contradiction" in blocked_projection.triage_feedback[-1].reason

    blocked = apply_event(
        blocked, author_event(blocked, "author_continue", {}, sequence=2)
    )
    blocked, work_id, revision_id = submit_work(
        blocked,
        agent_id="agent-alpha",
        account_id="account-alpha",
        sequence=3,
    )
    contract_id = (
        modules()["lifecycle"]
        .project_runtime(blocked)
        .current_stage.contract.contract_id
    )
    blocked = apply_event(
        blocked,
        lifecycle_event(
            blocked, "mode_expiry", {"contract_id": contract_id}, sequence=11
        ),
    )
    blocked = apply_event(
        blocked,
        author_event(
            blocked,
            "ranked_order",
            {
                "contract_id": contract_id,
                "ordered_work_ids": [work_id],
                "selected_revision_id": revision_id,
            },
            sequence=12,
        ),
    )
    recovered = modules()["lifecycle"].project_runtime(blocked)
    assert recovered.plan_status == "completed"
    assert not any(item.source_kind == "triage" for item in recovered.releases)


def test_s_10_successful_plan_creates_exact_triage_release() -> None:
    from .test_release_lifecycle import _complete_ranked

    projection = modules()["lifecycle"].project_runtime(_complete_ranked("explore"))
    triage = [item for item in projection.releases if item.source_kind == "triage"]
    assert len(triage) == 1
    assert triage[0].recipient_agent_id == "agent-reviewer"
