from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from wea_vnext.engine import installed_executor, load_executor

NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)
TRIAGE_AT = NOW - timedelta(minutes=30)
TRIAGE_ASSIGNED_AT = TRIAGE_AT - timedelta(minutes=2)
TRIAGE_COMPLETED_AT = TRIAGE_AT + timedelta(minutes=5)
PLAN_AT = NOW - timedelta(minutes=20)
DECISION_AT = NOW - timedelta(minutes=5)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_snapshot(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@lru_cache(maxsize=1)
def modules() -> dict[str, Any]:
    runtime = installed_executor("0.8.0").reference
    handle = load_executor(runtime)
    loaded = handle.import_modules(
        ("get10", "identity", "intake", "lifecycle", "rules")
    )
    result = dict(loaded)
    result["runtime"] = runtime
    return result


def registry() -> Any:
    identity = modules()["identity"]
    started = NOW - timedelta(days=1)
    accounts = (
        identity.GitHubAccount("account-agent0", "agent0", "agent0-base"),
        identity.GitHubAccount("account-author", "author", "agent-author"),
        identity.GitHubAccount("account-reviewer", "reviewer", "agent-reviewer"),
        identity.GitHubAccount("account-alpha", "alpha", "agent-alpha"),
        identity.GitHubAccount("account-beta", "beta", "agent-beta"),
        identity.GitHubAccount("account-gamma", "gamma", "agent-gamma"),
    )
    return identity.IdentityRegistry(
        accounts=accounts,
        bindings=(
            identity.Binding(
                "agent0-base-binding",
                "agent",
                "account-agent0",
                "agent0-base",
                1,
                started,
            ),
            identity.Binding(
                "agent0-role-binding",
                "agent0",
                "account-agent0",
                "agent0@system",
                1,
                started,
            ),
            identity.Binding(
                "author-binding",
                "agent",
                "account-author",
                "agent-author",
                1,
                started,
            ),
            identity.Binding(
                "reviewer-binding",
                "agent",
                "account-reviewer",
                "agent-reviewer",
                1,
                started,
            ),
            identity.Binding(
                "alpha-binding",
                "agent",
                "account-alpha",
                "agent-alpha",
                1,
                started,
            ),
            identity.Binding(
                "beta-binding",
                "agent",
                "account-beta",
                "agent-beta",
                1,
                started,
            ),
            identity.Binding(
                "gamma-binding",
                "agent",
                "account-gamma",
                "agent-gamma",
                1,
                started,
            ),
        ),
        control_group_bindings=(
            identity.ControlGroupBinding(
                "group-agent0", "agent0-base", "owner-agent0", 1, started
            ),
            identity.ControlGroupBinding(
                "group-author", "agent-author", "owner-author", 1, started
            ),
            identity.ControlGroupBinding(
                "group-reviewer", "agent-reviewer", "owner-reviewer", 1, started
            ),
            identity.ControlGroupBinding(
                "group-alpha", "agent-alpha", "owner-alpha", 1, started
            ),
            identity.ControlGroupBinding(
                "group-beta", "agent-beta", "owner-beta", 1, started
            ),
            identity.ControlGroupBinding(
                "group-gamma", "agent-gamma", "owner-gamma", 1, started
            ),
        ),
    )


def common_control_registry(*agent_ids: str) -> Any:
    identity = modules()["identity"]
    base = registry()
    selected = set(agent_ids or ("agent-alpha",))
    groups = tuple(
        replace(item, control_group_id="owner-author")
        if item.agent_id in selected
        else item
        for item in base.control_group_bindings
    )
    return identity.IdentityRegistry(
        accounts=base.accounts,
        bindings=base.bindings,
        control_group_bindings=groups,
    )


def draft(*, max_bank_wea: int = 100) -> Any:
    intake = modules()["intake"]
    return intake.DraftIssue(
        repository_id="repository-1",
        issue_id="issue-42",
        issue_number=42,
        issue_revision_id="issue-revision-1",
        creator_github_account_id="account-author",
        author_agent_id="agent-author",
        author_binding_id="author-binding",
        author_binding_version=1,
        body="Solve the exact problem",
        max_bank_wea=max_bank_wea,
        effective_at=TRIAGE_AT - timedelta(minutes=5),
    )


def assessment(*, advice: str = "Proceed with the proposed plan") -> Any:
    intake = modules()["intake"]
    assessment_id = intake.triage_assessment_id(
        "repository-1", "issue-42", "issue-revision-1"
    )
    assignment_id = intake.triage_assignment_id(assessment_id)
    completion_id = intake.triage_completion_id(assessment_id)
    assignment_snapshot = canonical_snapshot(
        {
            "agent0_binding_id": "agent0-role-binding",
            "agent0_binding_version": 1,
            "agent0_github_account_id": "account-agent0",
            "assignment_id": assignment_id,
            "issue_id": "issue-42",
            "issue_revision_id": "issue-revision-1",
            "kind": "triage_assignment",
            "repository_id": "repository-1",
            "reviewer_agent_id": "agent-reviewer",
            "reviewer_binding_id": "reviewer-binding",
            "reviewer_binding_version": 1,
            "reviewer_github_account_id": "account-reviewer",
        }
    )
    snapshot = canonical_snapshot(
        {
            "advice": advice,
            "agent0_binding_id": "agent0-role-binding",
            "agent0_binding_version": 1,
            "agent0_github_account_id": "account-agent0",
            "assessment_id": assessment_id,
            "assignment_id": assignment_id,
            "body_hash": digest("Solve the exact problem"),
            "completion_id": completion_id,
            "issue_id": "issue-42",
            "issue_revision_id": "issue-revision-1",
            "kind": "triage_assessment",
            "repository_id": "repository-1",
            "reviewer_agent_id": "agent-reviewer",
            "reviewer_binding_id": "reviewer-binding",
            "reviewer_binding_version": 1,
            "reviewer_github_account_id": "account-reviewer",
            "risks": ["architecture choice"],
        }
    )
    completion_snapshot = canonical_snapshot(
        {
            "agent0_binding_id": "agent0-role-binding",
            "agent0_binding_version": 1,
            "agent0_github_account_id": "account-agent0",
            "assessment_id": assessment_id,
            "assignment_id": assignment_id,
            "completion_id": completion_id,
            "issue_id": "issue-42",
            "issue_revision_id": "issue-revision-1",
            "kind": "triage_completion",
            "repository_id": "repository-1",
        }
    )
    return intake.TriageAssessment(
        repository_id="repository-1",
        assessment_id=assessment_id,
        assignment_id=assignment_id,
        completion_id=completion_id,
        reviewer_agent_id="agent-reviewer",
        reviewer_github_account_id="account-reviewer",
        reviewer_binding_id="reviewer-binding",
        reviewer_binding_version=1,
        agent0_github_account_id="account-agent0",
        agent0_binding_id="agent0-role-binding",
        agent0_binding_version=1,
        assignment_source_comment_id="triage-assignment-comment-1",
        assignment_source_revision_id="triage-assignment-source-revision-1",
        assignment_snapshot=assignment_snapshot,
        assignment_snapshot_hash=digest(assignment_snapshot),
        assignment_effective_at=TRIAGE_ASSIGNED_AT,
        completion_source_comment_id="triage-completion-comment-1",
        completion_source_revision_id="triage-completion-source-revision-1",
        completion_snapshot=completion_snapshot,
        completion_snapshot_hash=digest(completion_snapshot),
        completion_effective_at=TRIAGE_COMPLETED_AT,
        issue_id="issue-42",
        issue_revision_id="issue-revision-1",
        body_hash=digest("Solve the exact problem"),
        risks=("architecture choice",),
        advice=advice,
        source_comment_id="triage-comment-1",
        source_revision_id="triage-source-revision-1",
        snapshot=snapshot,
        snapshot_hash=digest(snapshot),
        effective_at=TRIAGE_AT,
    )


def replace_assessment(record: Any, **changes: Any) -> Any:
    values = {
        "advice": record.advice,
        "agent0_binding_id": record.agent0_binding_id,
        "agent0_binding_version": record.agent0_binding_version,
        "agent0_github_account_id": record.agent0_github_account_id,
        "assessment_id": record.assessment_id,
        "assignment_id": record.assignment_id,
        "body_hash": record.body_hash,
        "completion_id": record.completion_id,
        "issue_id": record.issue_id,
        "issue_revision_id": record.issue_revision_id,
        "repository_id": record.repository_id,
        "reviewer_agent_id": record.reviewer_agent_id,
        "reviewer_binding_id": record.reviewer_binding_id,
        "reviewer_binding_version": record.reviewer_binding_version,
        "reviewer_github_account_id": record.reviewer_github_account_id,
        "risks": list(record.risks),
    }
    values.update({key: value for key, value in changes.items() if key in values})
    assignment_values = {
        "agent0_binding_id": values["agent0_binding_id"],
        "agent0_binding_version": values["agent0_binding_version"],
        "agent0_github_account_id": values["agent0_github_account_id"],
        "assignment_id": values["assignment_id"],
        "issue_id": values["issue_id"],
        "issue_revision_id": values["issue_revision_id"],
        "kind": "triage_assignment",
        "repository_id": values["repository_id"],
        "reviewer_agent_id": values["reviewer_agent_id"],
        "reviewer_binding_id": values["reviewer_binding_id"],
        "reviewer_binding_version": values["reviewer_binding_version"],
        "reviewer_github_account_id": values["reviewer_github_account_id"],
    }
    snapshot = canonical_snapshot({"kind": "triage_assessment", **values})
    completion_values = {
        "agent0_binding_id": values["agent0_binding_id"],
        "agent0_binding_version": values["agent0_binding_version"],
        "agent0_github_account_id": values["agent0_github_account_id"],
        "assessment_id": values["assessment_id"],
        "assignment_id": values["assignment_id"],
        "completion_id": values["completion_id"],
        "issue_id": values["issue_id"],
        "issue_revision_id": values["issue_revision_id"],
        "kind": "triage_completion",
        "repository_id": values["repository_id"],
    }
    assignment_snapshot = canonical_snapshot(assignment_values)
    completion_snapshot = canonical_snapshot(completion_values)
    return replace(
        record,
        **changes,
        assignment_snapshot=assignment_snapshot,
        assignment_snapshot_hash=digest(assignment_snapshot),
        snapshot=snapshot,
        snapshot_hash=digest(snapshot),
        completion_snapshot=completion_snapshot,
        completion_snapshot_hash=digest(completion_snapshot),
    )


def stages() -> tuple[Any, ...]:
    intake = modules()["intake"]
    return (
        intake.PlanStage(
            key="architecture",
            depth="explore",
            mode="duel",
            schedule=intake.StageSchedule(
                join_seconds=600,
                move_seconds=(300, 300, 300, 300, 300, 300),
                author_decision_seconds=600,
            ),
            allocation_wea=20,
            config={
                "admission": "open",
                "invitations": [],
                "positions": ["architecture-a", "architecture-b"],
                "rounds": 3,
            },
            expected_output="Selected architecture",
        ),
        intake.PlanStage(
            key="specification",
            depth="spec",
            mode="ranked",
            schedule=intake.StageSchedule(
                intake_seconds=3600,
                author_decision_seconds=600,
            ),
            allocation_wea=40,
            config={"payout_vector": [40], "winner_count": 1},
            expected_output="Accepted specification",
            inputs=(intake.SelectedWorkInput("architecture"),),
        ),
        intake.PlanStage(
            key="implementation",
            depth="implement",
            mode="ranked",
            schedule=intake.StageSchedule(
                intake_seconds=7200,
                author_decision_seconds=900,
            ),
            allocation_wea=40,
            config={"payout_vector": [40], "winner_count": 1},
            expected_output="Working implementation",
            inputs=(intake.SelectedWorkInput("specification"),),
        ),
    )


def plan_revision(
    *,
    revision_number: int = 1,
    proposer_kind: str = "triage",
    parent_revision_id: str | None = None,
    plan_stages: tuple[Any, ...] | None = None,
    total_bank_wea: int = 100,
) -> Any:
    intake = modules()["intake"]
    plan_id = intake.resolution_plan_id("repository-1", "issue-42")
    revision_id = intake.resolution_plan_revision_id(plan_id, revision_number)
    selected_stages = plan_stages or stages()
    if proposer_kind == "triage":
        proposer_agent_id = "agent-reviewer"
        proposer_github_account_id = "account-reviewer"
        proposer_binding_id = "reviewer-binding"
    else:
        proposer_agent_id = "agent-author"
        proposer_github_account_id = "account-author"
        proposer_binding_id = "author-binding"
    content = {
        "author_agent_id": "agent-author",
        "body_hash": digest("Solve the exact problem"),
        "issue_id": "issue-42",
        "issue_revision_id": "issue-revision-1",
        "parent_revision_id": parent_revision_id,
        "plan_id": plan_id,
        "proposer_agent_id": proposer_agent_id,
        "proposer_binding_id": proposer_binding_id,
        "proposer_binding_version": 1,
        "proposer_github_account_id": proposer_github_account_id,
        "proposer_kind": proposer_kind,
        "repository_id": "repository-1",
        "revision_id": revision_id,
        "revision_number": revision_number,
        "stages": [item.to_data() for item in selected_stages],
        "total_bank_wea": total_bank_wea,
        "triage_assessment_id": intake.triage_assessment_id(
            "repository-1", "issue-42", "issue-revision-1"
        ),
    }
    snapshot = canonical_snapshot({"kind": "resolution_plan_revision", **content})
    return intake.ResolutionPlanRevision(
        plan_id=plan_id,
        revision_id=revision_id,
        revision_number=revision_number,
        parent_revision_id=parent_revision_id,
        repository_id="repository-1",
        issue_id="issue-42",
        issue_revision_id="issue-revision-1",
        body_hash=digest("Solve the exact problem"),
        triage_assessment_id=intake.triage_assessment_id(
            "repository-1", "issue-42", "issue-revision-1"
        ),
        proposer_kind=proposer_kind,
        proposer_agent_id=proposer_agent_id,
        proposer_github_account_id=proposer_github_account_id,
        proposer_binding_id=proposer_binding_id,
        proposer_binding_version=1,
        author_agent_id="agent-author",
        total_bank_wea=total_bank_wea,
        stages=selected_stages,
        source_comment_id=f"plan-comment-{revision_number}",
        source_revision_id=f"plan-source-revision-{revision_number}",
        snapshot=snapshot,
        snapshot_hash=digest(snapshot),
        effective_at=PLAN_AT + timedelta(minutes=revision_number),
    )


def replace_plan_revision(record: Any, **changes: Any) -> Any:
    values = {
        "author_agent_id": record.author_agent_id,
        "body_hash": record.body_hash,
        "issue_id": record.issue_id,
        "issue_revision_id": record.issue_revision_id,
        "parent_revision_id": record.parent_revision_id,
        "plan_id": record.plan_id,
        "proposer_agent_id": record.proposer_agent_id,
        "proposer_binding_id": record.proposer_binding_id,
        "proposer_binding_version": record.proposer_binding_version,
        "proposer_github_account_id": record.proposer_github_account_id,
        "proposer_kind": record.proposer_kind,
        "repository_id": record.repository_id,
        "revision_id": record.revision_id,
        "revision_number": record.revision_number,
        "stages": [item.to_data() for item in record.stages],
        "total_bank_wea": record.total_bank_wea,
        "triage_assessment_id": record.triage_assessment_id,
    }
    values.update(
        {
            key: [item.to_data() for item in value] if key == "stages" else value
            for key, value in changes.items()
            if key in values
        }
    )
    snapshot = canonical_snapshot({"kind": "resolution_plan_revision", **values})
    return replace(
        record,
        **changes,
        snapshot=snapshot,
        snapshot_hash=digest(snapshot),
    )


def decision(plan: Any, *, outcome: str = "approve") -> Any:
    intake = modules()["intake"]
    source_revision_id = f"author-source-{plan.revision_number}-{outcome}"
    decision_id = intake.author_plan_decision_id(plan.revision_id, source_revision_id)
    idempotency_key = intake.author_plan_decision_key(
        plan.revision_id, source_revision_id
    )
    snapshot = canonical_snapshot(
        {
            "author_agent_id": "agent-author",
            "author_binding_id": "author-binding",
            "author_binding_version": 1,
            "author_github_account_id": "account-author",
            "decision_id": decision_id,
            "idempotency_key": idempotency_key,
            "kind": "author_plan_decision",
            "outcome": outcome,
            "plan_content_hash": plan.content_hash,
            "plan_id": plan.plan_id,
            "plan_revision_id": plan.revision_id,
        }
    )
    return intake.AuthorPlanDecision(
        decision_id=decision_id,
        outcome=outcome,
        plan_id=plan.plan_id,
        plan_revision_id=plan.revision_id,
        plan_content_hash=plan.content_hash,
        author_agent_id="agent-author",
        author_github_account_id="account-author",
        author_binding_id="author-binding",
        author_binding_version=1,
        source_comment_id=f"author-comment-{plan.revision_number}-{outcome}",
        source_revision_id=source_revision_id,
        snapshot=snapshot,
        snapshot_hash=digest(snapshot),
        effective_at=DECISION_AT + timedelta(minutes=plan.revision_number),
        idempotency_key=idempotency_key,
    )


def replace_decision(record: Any, **changes: Any) -> Any:
    intake = modules()["intake"]
    if "source_revision_id" in changes or "plan_revision_id" in changes:
        plan_revision_id = changes.get("plan_revision_id", record.plan_revision_id)
        source_revision_id = changes.get(
            "source_revision_id", record.source_revision_id
        )
        changes.setdefault(
            "decision_id",
            intake.author_plan_decision_id(plan_revision_id, source_revision_id),
        )
        changes.setdefault(
            "idempotency_key",
            intake.author_plan_decision_key(plan_revision_id, source_revision_id),
        )
    values = {
        "author_agent_id": record.author_agent_id,
        "author_binding_id": record.author_binding_id,
        "author_binding_version": record.author_binding_version,
        "author_github_account_id": record.author_github_account_id,
        "decision_id": record.decision_id,
        "idempotency_key": record.idempotency_key,
        "outcome": record.outcome,
        "plan_content_hash": record.plan_content_hash,
        "plan_id": record.plan_id,
        "plan_revision_id": record.plan_revision_id,
    }
    values.update({key: value for key, value in changes.items() if key in values})
    snapshot = canonical_snapshot({"kind": "author_plan_decision", **values})
    return replace(
        record,
        **changes,
        snapshot=snapshot,
        snapshot_hash=digest(snapshot),
    )


def github_state(*records: Any) -> Any:
    intake = modules()["intake"]
    events: dict[tuple[str, str, str, str], Any] = {}

    def add_event(
        *,
        repository_id: str,
        object_kind: str,
        object_id: str,
        revision_id: str,
        effective_at: datetime,
        body: str,
        actor_account_id: str,
        payload: object | None = None,
    ) -> None:
        event = intake.GitHubEvent.from_revision(
            repository="owner/repository",
            repository_id=repository_id,
            object_kind=object_kind,
            object_id=object_id,
            revision_id=revision_id,
            effective_at=effective_at,
            body=body,
            actor_account_id=actor_account_id,
            payload={} if payload is None else payload,
        )
        events[event.revision_identity] = event

    for record in records:
        if type(record) is intake.DraftIssue:
            add_event(
                repository_id=record.repository_id,
                object_kind="issue",
                object_id=record.issue_id,
                revision_id=record.issue_revision_id,
                effective_at=record.effective_at,
                body=record.body,
                actor_account_id=record.creator_github_account_id,
                payload={
                    "author_agent_id": record.author_agent_id,
                    "author_binding_id": record.author_binding_id,
                    "author_binding_version": record.author_binding_version,
                    "issue_number": record.issue_number,
                    "kind": "draft_issue",
                    "max_bank_wea": record.max_bank_wea,
                },
            )
        elif type(record) is intake.TriageAssessment:
            for object_id, revision_id, effective_at, body, actor in (
                (
                    record.assignment_source_comment_id,
                    record.assignment_source_revision_id,
                    record.assignment_effective_at,
                    record.assignment_snapshot,
                    record.agent0_github_account_id,
                ),
                (
                    record.source_comment_id,
                    record.source_revision_id,
                    record.effective_at,
                    record.snapshot,
                    record.reviewer_github_account_id,
                ),
                (
                    record.completion_source_comment_id,
                    record.completion_source_revision_id,
                    record.completion_effective_at,
                    record.completion_snapshot,
                    record.agent0_github_account_id,
                ),
            ):
                add_event(
                    repository_id=record.repository_id,
                    object_kind="issue_comment",
                    object_id=object_id,
                    revision_id=revision_id,
                    effective_at=effective_at,
                    body=body,
                    actor_account_id=actor,
                )
        elif type(record) is intake.ResolutionPlanRevision:
            add_event(
                repository_id=record.repository_id,
                object_kind="issue_comment",
                object_id=record.source_comment_id,
                revision_id=record.source_revision_id,
                effective_at=record.effective_at,
                body=record.snapshot,
                actor_account_id=record.proposer_github_account_id,
            )
        elif type(record) is intake.AuthorPlanDecision:
            add_event(
                repository_id="repository-1",
                object_kind="issue_comment",
                object_id=record.source_comment_id,
                revision_id=record.source_revision_id,
                effective_at=record.effective_at,
                body=record.snapshot,
                actor_account_id=record.author_github_account_id,
            )
        elif type(record) is modules()["lifecycle"].LifecycleEvent:
            add_event(
                repository_id="repository-1",
                object_kind="issue_comment",
                object_id=record.source_id,
                revision_id=record.source_revision_id,
                effective_at=record.effective_at,
                body=record.source_snapshot,
                actor_account_id=record.actor_account_id,
            )
        elif type(record) is intake.GitHubEvent:
            events[record.revision_identity] = record
        else:  # pragma: no cover - helper misuse
            raise AssertionError(f"unsupported evidence record: {type(record)!r}")

    boundary = intake.GitHubReadBoundary(
        repository="owner/repository",
        repository_id="repository-1",
        captured_at=NOW + timedelta(hours=1),
        read_sequence=1,
        end_cursor="cursor-1",
        complete=True,
    )
    batch = intake.GitHubEventBatch(boundary=boundary, events=tuple(events.values()))
    return intake.accept_github_evidence_batch(
        intake.initial_github_evidence_state(), batch
    )


def verified_call(name: str, *args: Any, **kwargs: Any) -> Any:
    return modules()["intake"].call_verified(name, *args, **kwargs)


def record_triage(
    state: Any,
    draft_record: Any,
    assessment_record: Any,
    *,
    identity_registry: Any | None = None,
    evidence_state: Any | None = None,
) -> Any:
    return verified_call(
        "record_triage_assessment",
        state,
        draft_record,
        assessment_record,
        registry=identity_registry or registry(),
        github_state=evidence_state or github_state(draft_record, assessment_record),
    )


def record_plan(
    state: Any,
    draft_record: Any,
    plan_record: Any,
    *,
    identity_registry: Any | None = None,
    evidence_state: Any | None = None,
) -> Any:
    evidence = (
        draft_record,
        *state.triage_assessments,
        *state.plan_revisions,
        *state.decisions,
        plan_record,
    )
    return verified_call(
        "record_plan_revision",
        state,
        draft_record,
        plan_record,
        registry=identity_registry or registry(),
        github_state=evidence_state or github_state(*evidence),
    )


def record_decision(
    state: Any,
    draft_record: Any,
    decision_record: Any,
    *,
    identity_registry: Any | None = None,
    evidence_state: Any | None = None,
) -> Any:
    evidence = (
        draft_record,
        *state.triage_assessments,
        *state.plan_revisions,
        *state.decisions,
        decision_record,
    )
    return verified_call(
        "record_author_plan_decision",
        state,
        draft_record,
        decision_record,
        registry=identity_registry or registry(),
        github_state=evidence_state or github_state(*evidence),
    )


def activate_plan(
    state: Any,
    draft_record: Any,
    plan_record: Any,
    decision_record: Any,
    *,
    identity_registry: Any | None = None,
    evidence_state: Any | None = None,
    **changes: Any,
) -> Any:
    evidence = (
        draft_record,
        *state.triage_assessments,
        *state.plan_revisions,
        *state.decisions,
    )
    values = {
        "plan_revision_id": plan_record.revision_id,
        "decision_id": decision_record.decision_id,
        "payer_agent_id": "agent-author",
        "payer_github_account_id": "account-author",
        "effective_at": decision_record.effective_at,
    }
    values.update(changes)
    return verified_call(
        "activate_resolution_plan",
        state,
        draft_record,
        **values,
        registry=identity_registry or registry(),
        github_state=evidence_state or github_state(*evidence),
    )


def state_with_plan(
    *,
    plan: Any | None = None,
    author_balance: int = 150,
    treasury_balance: int = 100,
    advice: str = "Proceed with the proposed plan",
) -> tuple[Any, Any, Any, Any]:
    intake = modules()["intake"]
    plan_record = plan or plan_revision()
    draft_record = draft(max_bank_wea=max(100, plan_record.total_bank_wea))
    assessment_record = assessment(advice=advice)
    state = intake.PlanIntakeState(
        balances=(
            intake.AccountBalance("agent-author", author_balance),
            intake.AccountBalance("treasury", treasury_balance),
        )
    )
    state = record_triage(state, draft_record, assessment_record)
    state = record_plan(state, draft_record, plan_record)
    return state, draft_record, assessment_record, plan_record


def activated_runtime(
    *,
    plan_stages: tuple[Any, ...] | None = None,
    total_bank_wea: int = 100,
    author_balance: int = 200,
    treasury_balance: int = 100,
) -> Any:
    plan = plan_revision(
        plan_stages=plan_stages,
        total_bank_wea=total_bank_wea,
    )
    state, draft_record, _, plan = state_with_plan(
        plan=plan,
        author_balance=author_balance,
        treasury_balance=treasury_balance,
    )
    approval = decision(plan)
    state = record_decision(state, draft_record, approval)
    activation = activate_plan(state, draft_record, plan, approval)
    return modules()["lifecycle"].start_runtime(activation)


def lifecycle_event(
    state: Any,
    kind: str,
    payload: dict[str, Any],
    *,
    sequence: int,
    actor_kind: str = "tide",
    actor_id: str = "tide@system",
    actor_account_id: str = "tide@system",
    effective_at: datetime | None = None,
) -> Any:
    lifecycle = modules()["lifecycle"]
    return lifecycle.make_lifecycle_event(
        plan_id=state.activation.plan.plan_id,
        kind=kind,
        actor_kind=actor_kind,
        actor_id=actor_id,
        actor_account_id=actor_account_id,
        source_id=f"source-{sequence:04d}",
        source_revision_id=f"source-revision-{sequence:04d}",
        payload=payload,
        effective_at=effective_at
        or state.activation.plan.activated_at + timedelta(minutes=sequence),
    )


def apply_event(
    state: Any,
    event: Any,
    *,
    evidence_state: Any | None = None,
    identity_registry: Any | None = None,
    plan_revision_record: Any | None = None,
) -> Any:
    return modules()["lifecycle"].call_verified(
        "apply_lifecycle_event",
        state,
        event,
        registry=identity_registry or registry(),
        github_state=evidence_state or github_state(event),
        plan_revision=plan_revision_record,
    )


def suffix_replan_records(
    state: Any,
    replacement_suffix: tuple[Any, ...],
    *,
    sequence: int,
) -> tuple[Any, Any, Any]:
    intake = modules()["intake"]
    projection = modules()["lifecycle"].project_runtime(state)
    current = projection.plan_revisions[-1]
    revision_number = current.revision_number + 1
    revision_id = intake.resolution_plan_revision_id(
        current.plan_id, revision_number
    )
    approval_at = state.activation.plan.activated_at + timedelta(minutes=sequence)
    revision = replace_plan_revision(
        current,
        revision_id=revision_id,
        revision_number=revision_number,
        parent_revision_id=current.revision_id,
        stages=(
            *projection.future_stages[: projection.current_stage_index + 1],
            *replacement_suffix,
        ),
        source_comment_id=f"suffix-plan-comment-{sequence:04d}",
        source_revision_id=f"suffix-plan-revision-{sequence:04d}",
        effective_at=approval_at - timedelta(seconds=1),
    )
    event = lifecycle_event(
        state,
        "suffix_replan",
        {
            "plan_content_hash": revision.content_hash,
            "plan_revision_id": revision.revision_id,
        },
        sequence=sequence,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
        effective_at=approval_at,
    )
    return revision, event, github_state(revision, event)


def apply_suffix_replan(
    state: Any,
    replacement_suffix: tuple[Any, ...],
    *,
    sequence: int,
) -> Any:
    revision, event, evidence = suffix_replan_records(
        state, replacement_suffix, sequence=sequence
    )
    return apply_event(
        state,
        event,
        evidence_state=evidence,
        plan_revision_record=revision,
    )


def confirm_control_disclosure(
    state: Any,
    *,
    work_id: str,
    sequence: int,
    identity_registry: Any | None = None,
    effective_at: datetime | None = None,
) -> Any:
    intake = modules()["intake"]
    projection = modules()["lifecycle"].project_runtime(state)
    work = next(
        item
        for stage_record in projection.stages
        for item in stage_record.works
        if item.work_id == work_id
    )
    disclosure = work.authority.disclosure
    assert disclosure is not None and not disclosure.confirmed
    event = lifecycle_event(
        state,
        "control_disclosure",
        {
            "contract_id": work.contract_id,
            "disclosure_revision_id": f"disclosure-revision-{sequence:04d}",
            "disclosure_source_id": f"disclosure-source-{sequence:04d}",
            "work_id": work.work_id,
        },
        sequence=sequence,
        effective_at=effective_at,
    )
    evidence = intake.GitHubEvent.from_revision(
        repository="owner/repository",
        repository_id="repository-1",
        object_kind="issue_comment",
        object_id=f"disclosure-source-{sequence:04d}",
        revision_id=f"disclosure-revision-{sequence:04d}",
        effective_at=event.effective_at - timedelta(seconds=1),
        body=disclosure.expected_snapshot,
        actor_account_id=event.actor_account_id,
        payload={},
    )
    return apply_event(
        state,
        event,
        evidence_state=github_state(event, evidence),
        identity_registry=identity_registry,
    )


def body_transition_event(
    state: Any,
    kind: str,
    *,
    body: str,
    sequence: int,
    effective_at: datetime | None = None,
) -> tuple[Any, Any]:
    if kind not in {"body_pause", "body_resume"}:  # pragma: no cover - helper misuse
        raise AssertionError(kind)
    transition_at = effective_at or (
        state.activation.plan.activated_at + timedelta(minutes=sequence)
    )
    revision_id = f"issue-body-revision-{sequence:04d}"
    issue_event = modules()["intake"].GitHubEvent.from_revision(
        repository="owner/repository",
        repository_id=state.activation.draft.repository_id,
        object_kind="issue",
        object_id=state.activation.draft.issue_id,
        revision_id=revision_id,
        effective_at=transition_at - timedelta(seconds=1),
        body=body,
        actor_account_id="account-author",
        payload={},
    )
    event = lifecycle_event(
        state,
        kind,
        {"issue_revision_id": revision_id},
        sequence=sequence,
        effective_at=transition_at,
    )
    return event, github_state(issue_event, event)


def apply_body_transition(
    state: Any,
    kind: str,
    *,
    body: str,
    sequence: int,
    effective_at: datetime | None = None,
) -> Any:
    event, evidence = body_transition_event(
        state,
        kind,
        body=body,
        sequence=sequence,
        effective_at=effective_at,
    )
    return apply_event(state, event, evidence_state=evidence)


def stage(
    *,
    key: str,
    depth: str,
    mode: str,
    allocation_wea: int,
    payout_vector: list[int] | None = None,
    slots: int | None = None,
    acceptance: dict[str, str] | None = None,
    inputs: tuple[Any, ...] = (),
    duel_admission: str = "open",
    duel_invitations: list[dict[str, str]] | None = None,
) -> Any:
    intake = modules()["intake"]
    if mode == "ranked":
        assert payout_vector is not None
        config: dict[str, Any] = {
            "payout_vector": payout_vector,
            "winner_count": len(payout_vector),
        }
        schedule = intake.StageSchedule(
            intake_seconds=600,
            author_decision_seconds=300,
        )
    elif mode == "flat_pod":
        assert payout_vector is not None and slots is not None
        config = {
            "acceptance": acceptance or {"kind": "author"},
            "additive": True,
            "payout_vector": payout_vector,
            "slots": slots,
        }
        schedule = intake.StageSchedule(intake_seconds=600)
    elif mode == "frontier":
        assert payout_vector is not None
        config = {
            "acceptance": acceptance or {"kind": "author"},
            "incentive": "linear",
            "payout_vector": payout_vector,
            "prior_art": [],
            "snapshot_identity": "model+genome+runtime",
        }
        schedule = intake.StageSchedule(intake_seconds=600)
    elif mode == "duel":
        config = {
            "admission": duel_admission,
            "invitations": duel_invitations or [],
            "positions": ["a", "b"],
            "rounds": 3,
        }
        schedule = intake.StageSchedule(
            join_seconds=600,
            move_seconds=(60, 60, 60, 60, 60, 60),
            author_decision_seconds=300,
        )
    else:  # pragma: no cover - helper misuse
        raise AssertionError(mode)
    return intake.PlanStage(
        key=key,
        depth=depth,
        mode=mode,
        schedule=schedule,
        allocation_wea=allocation_wea,
        config=config,
        expected_output=f"{key} output",
        inputs=inputs,
    )


def submit_work(
    state: Any,
    *,
    agent_id: str,
    account_id: str,
    sequence: int,
    eligible: bool = True,
    content: str | None = None,
    snapshot: dict[str, str] | None = None,
    identity_registry: Any | None = None,
) -> tuple[Any, str, str]:
    lifecycle = modules()["lifecycle"]
    projection = lifecycle.project_runtime(state)
    contract_id = projection.current_stage.contract.contract_id
    identifier = lifecycle.work_id(contract_id, agent_id)
    existing = next(
        (item for item in projection.current_stage.works if item.work_id == identifier),
        None,
    )
    revision_id = lifecycle.work_revision_id(
        identifier, 1 if existing is None else len(existing.revisions) + 1
    )
    acceptance = projection.current_stage.contract.config.get("acceptance")
    uses_normalized_validator = (
        acceptance is not None
        and acceptance.get("kind") == "normalized_validator"
    )
    source_content = content or (
        f"valid:{revision_id}" if uses_normalized_validator else revision_id
    )
    normalized_output = source_content if uses_normalized_validator else None
    event = lifecycle_event(
        state,
        "work_revision",
        {
            "content_hash": digest(source_content),
            "contract_id": contract_id,
            "eligible": eligible,
            "normalized_output": normalized_output,
            "revision_id": revision_id,
            "snapshot": snapshot,
        },
        sequence=sequence,
        actor_kind="agent",
        actor_id=agent_id,
        actor_account_id=account_id,
    )
    return (
        apply_event(state, event, identity_registry=identity_registry),
        identifier,
        revision_id,
    )


def accept_work(
    state: Any,
    *,
    work_id: str,
    revision_id: str,
    sequence: int,
    novel: bool = True,
    verdict: str = "accept",
    validator: tuple[str, str] | None = None,
) -> Any:
    projection = modules()["lifecycle"].project_runtime(state)
    if validator is None:
        actor_kind = "author"
        actor_id = "agent-author"
        actor_account_id = "account-author"
    else:
        actor_kind = "validator"
        actor_id, actor_account_id = validator
    event = lifecycle_event(
        state,
        "work_acceptance",
        {
            "contract_id": projection.current_stage.contract.contract_id,
            "novel": novel,
            "revision_id": revision_id,
            "verdict": verdict,
            "work_id": work_id,
        },
        sequence=sequence,
        actor_kind=actor_kind,
        actor_id=actor_id,
        actor_account_id=actor_account_id,
    )
    return apply_event(state, event)


def assign_role(
    state: Any,
    *,
    role_id: str = "review-role",
    role_kind: str = "review",
    generation: int = 1,
    targets: tuple[str, ...] = ("target-a",),
    duration_seconds: int = 600,
    funding: str = "free",
    amount_wea: int = 0,
    assigned_agent_id: str = "agent-alpha",
    assigned_account_id: str = "account-alpha",
    sequence: int = 1,
) -> Any:
    return apply_event(
        state,
        lifecycle_event(
            state,
            "role_assignment",
            {
                "amount_wea": amount_wea,
                "assigned_account_id": assigned_account_id,
                "assigned_agent_id": assigned_agent_id,
                "duration_seconds": duration_seconds,
                "funding": funding,
                "generation": generation,
                "role_id": role_id,
                "role_kind": role_kind,
                "target_ids": list(targets),
            },
            sequence=sequence,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )


def submit_role_result(
    state: Any,
    *,
    role_id: str = "review-role",
    generation: int = 1,
    target_id: str = "target-a",
    sequence: int,
    assigned_agent_id: str = "agent-alpha",
    assigned_account_id: str = "account-alpha",
    identity_registry: Any | None = None,
) -> Any:
    return apply_event(
        state,
        lifecycle_event(
            state,
            "role_result",
            {
                "generation": generation,
                "result_hash": digest(f"{role_id}:{generation}:{target_id}"),
                "role_id": role_id,
                "target_id": target_id,
            },
            sequence=sequence,
            actor_kind="role",
            actor_id=assigned_agent_id,
            actor_account_id=assigned_account_id,
        ),
        identity_registry=identity_registry,
    )


def resolve_role(
    state: Any,
    *,
    role_id: str = "review-role",
    generation: int = 1,
    outcome: str = "accepted",
    sequence: int,
) -> Any:
    return apply_event(
        state,
        lifecycle_event(
            state,
            "role_resolution",
            {"generation": generation, "outcome": outcome, "role_id": role_id},
            sequence=sequence,
            actor_kind="agent0",
            actor_id="agent0@system",
            actor_account_id="account-agent0",
        ),
    )


def author_event(
    state: Any,
    kind: str,
    payload: dict[str, Any],
    *,
    sequence: int,
) -> Any:
    return lifecycle_event(
        state,
        kind,
        payload,
        sequence=sequence,
        actor_kind="author",
        actor_id="agent-author",
        actor_account_id="account-author",
    )
