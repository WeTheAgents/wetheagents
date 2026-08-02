from __future__ import annotations

from typing import Any

import pytest

from .current_bdd_support import (
    activated_runtime,
    apply_event,
    author_event,
    github_state,
    lifecycle_event,
    modules,
    replace_plan_revision,
    stage,
    suffix_replan_records,
)


def _paused_plan() -> tuple[Any, Any, Any]:
    first = stage(
        key="explore",
        depth="explore",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    second = stage(
        key="implement",
        depth="implement",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    state = activated_runtime(plan_stages=(first, second), total_bank_wea=10)
    state = apply_event(
        state,
        lifecycle_event(
            state,
            "downstream_blocker",
            {"reason": "Triage missed a blocking contradiction"},
            sequence=1,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )
    replacement = stage(
        key="corrected-implement",
        depth="implement",
        mode="ranked",
        allocation_wea=5,
        payout_vector=[5],
    )
    return state, first, replacement


def _approval_event(state: Any, revision: Any, *, sequence: int = 2) -> Any:
    return author_event(
        state,
        "suffix_replan",
        {
            "plan_content_hash": revision.content_hash,
            "plan_revision_id": revision.revision_id,
        },
        sequence=sequence,
    )


def test_s_66_replan_requires_a_separate_triage_proposal() -> None:
    intake = modules()["intake"]
    state, _, replacement = _paused_plan()
    revision, _, _ = suffix_replan_records(state, (replacement,), sequence=2)
    author_revision = replace_plan_revision(
        revision,
        proposer_kind="author",
        proposer_agent_id="agent-author",
        proposer_github_account_id="account-author",
        proposer_binding_id="author-binding",
    )
    event = _approval_event(state, author_revision)

    with pytest.raises(intake.PlanError, match="Plan and Triage"):
        apply_event(
            state,
            event,
            evidence_state=github_state(author_revision, event),
            plan_revision_record=author_revision,
        )


def test_s_66_replan_revision_must_append_to_the_current_revision() -> None:
    intake = modules()["intake"]
    state, _, replacement = _paused_plan()
    revision, _, _ = suffix_replan_records(state, (replacement,), sequence=2)
    detached = replace_plan_revision(revision, parent_revision_id="detached-parent")
    event = _approval_event(state, detached)

    with pytest.raises(intake.PlanError, match="append to current"):
        apply_event(
            state,
            event,
            evidence_state=github_state(detached, event),
            plan_revision_record=detached,
        )


def test_s_66_replan_cannot_change_the_completed_or_active_prefix() -> None:
    intake = modules()["intake"]
    state, _, replacement = _paused_plan()
    revision, _, _ = suffix_replan_records(state, (replacement,), sequence=2)
    changed_first = stage(
        key="explore",
        depth="explore",
        mode="ranked",
        allocation_wea=4,
        payout_vector=[4],
    )
    changed_replacement = stage(
        key="corrected-implement",
        depth="implement",
        mode="ranked",
        allocation_wea=6,
        payout_vector=[6],
    )
    changed = replace_plan_revision(
        revision, stages=(changed_first, changed_replacement)
    )
    event = _approval_event(state, changed)

    with pytest.raises(intake.PlanError, match="completed or active stage"):
        apply_event(
            state,
            event,
            evidence_state=github_state(changed, event),
            plan_revision_record=changed,
        )


def test_s_66_replan_requires_exact_proposal_evidence() -> None:
    intake = modules()["intake"]
    state, _, replacement = _paused_plan()
    revision, event, _ = suffix_replan_records(state, (replacement,), sequence=2)

    with pytest.raises(intake.PlanError, match="exact accepted GitHub revision"):
        apply_event(
            state,
            event,
            evidence_state=github_state(event),
            plan_revision_record=revision,
        )


def test_s_66_author_approval_must_follow_the_triage_proposal() -> None:
    intake = modules()["intake"]
    state, _, replacement = _paused_plan()
    revision, _, _ = suffix_replan_records(state, (replacement,), sequence=2)
    event = lifecycle_event(
        state,
        "suffix_replan",
        {
            "plan_content_hash": revision.content_hash,
            "plan_revision_id": revision.revision_id,
        },
        sequence=2,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
        effective_at=revision.effective_at,
    )

    with pytest.raises(intake.PlanError, match="approval must follow"):
        apply_event(
            state,
            event,
            evidence_state=github_state(revision, event),
            plan_revision_record=revision,
        )


def test_s_66_triage_proposal_source_is_globally_single_use() -> None:
    intake = modules()["intake"]
    state, _, replacement = _paused_plan()
    revision, _, _ = suffix_replan_records(state, (replacement,), sequence=2)
    reused = replace_plan_revision(
        revision,
        source_revision_id="source-revision-0001",
    )
    event = _approval_event(state, reused)

    with pytest.raises(intake.PlanError, match="globally single-use"):
        apply_event(
            state,
            event,
            evidence_state=github_state(reused, event),
            plan_revision_record=reused,
        )


def test_s_66_exact_replan_replay_is_idempotent() -> None:
    state, _, replacement = _paused_plan()
    revision, event, evidence = suffix_replan_records(
        state, (replacement,), sequence=2
    )
    applied = apply_event(
        state,
        event,
        evidence_state=evidence,
        plan_revision_record=revision,
    )
    replayed = apply_event(
        applied,
        event,
        evidence_state=evidence,
        plan_revision_record=revision,
    )

    assert replayed is applied


def test_s_66_unapplied_replan_blocks_a_later_lifecycle_event() -> None:
    state, _, replacement = _paused_plan()
    revision, event, _ = suffix_replan_records(
        state, (replacement,), sequence=2
    )
    stop = author_event(state, "author_stop", {}, sequence=3)
    evidence = github_state(revision, event, stop)

    with pytest.raises(
        modules()["intake"].PlanError,
        match="earlier accepted lifecycle declaration remains unapplied",
    ):
        apply_event(state, stop, evidence_state=evidence)

    replanned = apply_event(
        state,
        event,
        evidence_state=evidence,
        plan_revision_record=revision,
    )
    stopped = apply_event(replanned, stop, evidence_state=evidence)
    projection = modules()["lifecycle"].project_runtime(stopped)
    assert projection.plan_status == "stopped"
    assert projection.plan_revisions[-1].revision_id == revision.revision_id


def test_s_66_invalid_replan_does_not_block_a_later_valid_event() -> None:
    state, _, replacement = _paused_plan()
    revision, _, _ = suffix_replan_records(state, (replacement,), sequence=2)
    invalid = replace_plan_revision(
        revision,
        proposer_kind="author",
        proposer_agent_id="agent-author",
        proposer_github_account_id="account-author",
        proposer_binding_id="author-binding",
    )
    event = _approval_event(state, invalid)
    stop = author_event(state, "author_stop", {}, sequence=3)
    stopped = apply_event(
        state,
        stop,
        evidence_state=github_state(invalid, event, stop),
    )

    assert modules()["lifecycle"].project_runtime(stopped).plan_status == "stopped"
