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
    runtime = installed_executor("0.7.0").reference
    handle = load_executor(runtime)
    loaded = handle.import_modules(("identity", "intake", "rules"))
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
        ),
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
            allocation_wea=20,
            config={
                "positions": ["architecture-a", "architecture-b"],
                "rounds": 3,
            },
            expected_output="Selected architecture",
        ),
        intake.PlanStage(
            key="specification",
            depth="spec",
            mode="ranked",
            allocation_wea=40,
            config={"payout_vector": [40], "winner_count": 1},
            expected_output="Accepted specification",
            inputs=(intake.SelectedWorkInput("architecture"),),
        ),
        intake.PlanStage(
            key="implementation",
            depth="implement",
            mode="ranked",
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
    advice: str = "Proceed with the proposed plan",
) -> tuple[Any, Any, Any, Any]:
    intake = modules()["intake"]
    draft_record = draft()
    assessment_record = assessment(advice=advice)
    plan_record = plan or plan_revision()
    state = intake.PlanIntakeState(
        balances=(intake.AccountBalance("agent-author", author_balance),)
    )
    state = record_triage(state, draft_record, assessment_record)
    state = record_plan(state, draft_record, plan_record)
    return state, draft_record, assessment_record, plan_record
