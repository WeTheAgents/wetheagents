"""Construct typed inputs; authority remains in the manifest-verified executor."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from datetime import datetime
from typing import Any


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp requires a timezone")
    return result


def registry(modules: Any, data: dict[str, Any]) -> Any:
    identity = modules["identity"]

    def binding(cls: Any, item: dict[str, Any]) -> Any:
        values = dict(item)
        for key in ("effective_from", "effective_until"):
            values[key] = None if values[key] is None else timestamp(values[key])
        return cls(**values)

    return identity.IdentityRegistry(
        accounts=tuple(
            identity.GitHubAccount(
                **{k: v for k, v in item.items() if k != "hello_world_mint_key"}
            )
            for item in data["accounts"]
        ),
        bindings=tuple(binding(identity.Binding, item) for item in data["bindings"]),
        control_group_bindings=tuple(
            binding(identity.ControlGroupBinding, item)
            for item in data["control_group_bindings"]
        ),
    )


def normalized_record(
    modules: Any, source: Any
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = modules["sources"].normalized(source)
    content = json.loads(snapshot)
    extra = {
        "source_comment_id": source.object_id,
        "source_revision_id": source.revision_id,
        "snapshot": snapshot,
        "snapshot_hash": hashlib.sha256(snapshot.encode()).hexdigest(),
        "effective_at": source.effective_at,
    }
    return content, extra


def draft(modules: Any, source: Any) -> Any:
    content, _ = normalized_record(modules, source)
    if content.pop("kind") != "draft_issue" or source.object_kind != "issue":
        raise ValueError("Draft requires an Issue source")
    return modules["intake"].DraftIssue(
        **content,
        repository_id=source.repository_id,
        issue_id=source.object_id,
        issue_revision_id=source.revision_id,
        creator_github_account_id=source.actor_account_id,
        body=source.body,
        effective_at=source.effective_at,
    )


def plan(modules: Any, source: Any) -> Any:
    intake = modules["intake"]
    content, extra = normalized_record(modules, source)
    if content.pop("kind") != "resolution_plan_revision":
        raise ValueError("Plan requires a Plan revision source")
    stages = []
    for item in content.pop("stages"):
        item = dict(item)
        schedule = dict(item.pop("schedule"))
        schedule["move_seconds"] = tuple(schedule["move_seconds"])
        inputs = tuple(
            intake.SelectedWorkInput(value["source_stage_key"])
            for value in item.pop("inputs")
        )
        stages.append(
            intake.PlanStage(
                **item, schedule=intake.StageSchedule(**schedule), inputs=inputs
            )
        )
    return intake.ResolutionPlanRevision(**content, **extra, stages=tuple(stages))


def decision(modules: Any, source: Any) -> Any:
    content, extra = normalized_record(modules, source)
    if content.pop("kind") != "author_plan_decision":
        raise ValueError("Decision requires an author source")
    return modules["intake"].AuthorPlanDecision(**content, **extra)


def authenticate_triage(modules: Any, source: Any, identity_registry: Any) -> None:
    data, _ = normalized_record(modules, source)
    if data.get("kind") == "triage_assignment":
        binding = modules["identity"].resolve_binding(
            tuple(
                item
                for item in identity_registry.bindings
                if item.actor_kind == "agent0"
            ),
            github_account_id=source.actor_account_id,
            subject_id="agent0@system",
            effective_at=source.effective_at,
        )
        if (
            source.actor_account_id != data["agent0_github_account_id"]
            or binding.binding_id != data["agent0_binding_id"]
            or binding.version != data["agent0_binding_version"]
        ):
            raise ValueError("Triage source authority differs")
    elif data.get("kind") == "triage_assessment":
        authority = modules["identity"].authorize_agent(
            github_account_id=source.actor_account_id,
            agent_id=data["reviewer_agent_id"],
            effective_at=source.effective_at,
            registry=identity_registry,
        )
        if (
            source.actor_account_id != data["reviewer_github_account_id"]
            or authority.account_binding_id != data["reviewer_binding_id"]
            or authority.account_binding_version != data["reviewer_binding_version"]
        ):
            raise ValueError("Triage source authority differs")


def assessment(
    modules: Any, completion: Any, sources: list[Any], identity_registry: Any
) -> Any:
    content, completion_extra = normalized_record(modules, completion)
    if content["kind"] != "triage_completion":
        raise ValueError("Assessment requires exact completion")
    candidates = []
    for source in sources:
        try:
            data, extra = normalized_record(modules, source)
            authenticate_triage(modules, source, identity_registry)
        except (ValueError, KeyError, TypeError):
            continue
        if source.effective_at <= completion.effective_at:
            candidates.append((data, extra))

    def exact(kind: str, field: str) -> tuple[dict[str, Any], dict[str, Any]]:
        matches = [
            (data, extra)
            for data, extra in candidates
            if data.get("kind") == kind and data.get(field) == content[field]
        ]
        if len(matches) != 1:
            raise ValueError(
                f"evidence_boundary: exact {kind} source is missing or ambiguous"
            )
        return matches[0]

    _, assignment_extra = exact("triage_assignment", "assignment_id")
    assessment_data, assessment_extra = exact("triage_assessment", "assessment_id")
    result = {**assessment_data, **assessment_extra}
    for prefix, extra in (
        ("assignment", assignment_extra),
        ("completion", completion_extra),
    ):
        result.update({f"{prefix}_{key}": value for key, value in extra.items()})
    result["risks"] = tuple(result["risks"])
    names = {field.name for field in fields(modules["intake"].TriageAssessment)}
    return modules["intake"].TriageAssessment(
        **{key: value for key, value in result.items() if key in names}
    )
