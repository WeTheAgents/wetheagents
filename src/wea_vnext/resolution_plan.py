"""Explicit facade for the inactive Resolution Plan executor 0.8.0."""

from __future__ import annotations

from typing import Any

from .engine import installed_executor, load_executor

_FACADE_EXECUTOR_VERSION = "0.8.0"
_RUNTIME = installed_executor(_FACADE_EXECUTOR_VERSION).reference
_MODULES = load_executor(_RUNTIME).import_modules(
    ("get10", "identity", "intake", "lifecycle", "rules")
)
_GET10 = _MODULES["get10"]
_IDENTITY = _MODULES["identity"]
_INTAKE = _MODULES["intake"]
_LIFECYCLE = _MODULES["lifecycle"]
_RULES = _MODULES["rules"]

Binding = _IDENTITY.Binding
ControlGroupBinding = _IDENTITY.ControlGroupBinding
GitHubAccount = _IDENTITY.GitHubAccount
IdentityError = _IDENTITY.IdentityError
IdentityRegistry = _IDENTITY.IdentityRegistry

AcceptedResolutionPlan = _INTAKE.AcceptedResolutionPlan
AccountBalance = _INTAKE.AccountBalance
AuthorPlanDecision = _INTAKE.AuthorPlanDecision
DraftIssue = _INTAKE.DraftIssue
LedgerTransition = _INTAKE.LedgerTransition
PlanActivation = _INTAKE.PlanActivation
PlanError = _INTAKE.PlanError
PlanIntakeState = _INTAKE.PlanIntakeState
PlanStage = _INTAKE.PlanStage
ProgramEscrow = _INTAKE.ProgramEscrow
ResolutionPlanRevision = _INTAKE.ResolutionPlanRevision
ResolvedWorkInput = _INTAKE.ResolvedWorkInput
SelectedWorkInput = _INTAKE.SelectedWorkInput
StageContract = _INTAKE.StageContract
StageDeadline = _INTAKE.StageDeadline
StageSchedule = _INTAKE.StageSchedule
StageTask = _INTAKE.StageTask
TriageAssessment = _INTAKE.TriageAssessment
GitHubEvent = _INTAKE.GitHubEvent
GitHubEventBatch = _INTAKE.GitHubEventBatch
GitHubReadBoundary = _INTAKE.GitHubReadBoundary
ProtocolState = _INTAKE.ProtocolState

Ruleset = _RULES.Ruleset
RulesetError = _RULES.RulesetError

LifecycleEvent = _LIFECYCLE.LifecycleEvent
NextAction = _LIFECYCLE.NextAction
PauseState = _LIFECYCLE.PauseState
ReleaseInvitation = _LIFECYCLE.ReleaseInvitation
ResolutionPlanRuntimeState = _LIFECYCLE.ResolutionPlanRuntimeState
RoleState = _LIFECYCLE.RoleState
RuntimeProjection = _LIFECYCLE.RuntimeProjection
Settlement = _LIFECYCLE.Settlement
StageState = _LIFECYCLE.StageState
StageTaskState = _LIFECYCLE.StageTaskState
TriageFeedback = _LIFECYCLE.TriageFeedback
WorkRevision = _LIFECYCLE.WorkRevision
WorkState = _LIFECYCLE.WorkState

Get10PriorArt = _GET10.Get10PriorArt
GET10_ISSUE_NUMBER = _GET10.GET10_ISSUE_NUMBER
GET10_PAYOUT_VECTOR = _GET10.GET10_PAYOUT_VECTOR
GET10_PRIOR_ART = _GET10.GET10_PRIOR_ART
GET10_VALIDATOR_ID = _GET10.GET10_VALIDATOR_ID
GET10_VALIDATOR_VERSION = _GET10.GET10_VALIDATOR_VERSION
Get10Validation = _GET10.Get10Validation


def load_ruleset() -> Any:
    return _RULES.load_ruleset()


def record_triage_assessment(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.call_verified("record_triage_assessment", *args, **kwargs)


def record_plan_revision(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.call_verified("record_plan_revision", *args, **kwargs)


def record_author_plan_decision(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.call_verified("record_author_plan_decision", *args, **kwargs)


def activate_resolution_plan(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.call_verified("activate_resolution_plan", *args, **kwargs)


def apply_lifecycle_event(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.call_verified("apply_lifecycle_event", *args, **kwargs)


def initial_github_evidence_state() -> Any:
    return _INTAKE.initial_github_evidence_state()


def accept_github_evidence_batch(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.accept_github_evidence_batch(*args, **kwargs)


def resolution_plan_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.resolution_plan_id(*args, **kwargs)


def resolution_plan_revision_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.resolution_plan_revision_id(*args, **kwargs)


def program_escrow_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.program_escrow_id(*args, **kwargs)


def stage_contract_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.stage_contract_id(*args, **kwargs)


def stage_task_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.stage_task_id(*args, **kwargs)


def triage_assessment_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.triage_assessment_id(*args, **kwargs)


def triage_assignment_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.triage_assignment_id(*args, **kwargs)


def triage_completion_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.triage_completion_id(*args, **kwargs)


def author_plan_decision_id(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.author_plan_decision_id(*args, **kwargs)


def author_plan_decision_key(*args: Any, **kwargs: Any) -> Any:
    return _INTAKE.author_plan_decision_key(*args, **kwargs)


def start_runtime(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.start_runtime(*args, **kwargs)


def project_runtime(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.project_runtime(*args, **kwargs)


def next_action(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.next_action(*args, **kwargs)


def make_lifecycle_event(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.make_lifecycle_event(*args, **kwargs)


def lifecycle_event_id(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.lifecycle_event_id(*args, **kwargs)


def work_id(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.work_id(*args, **kwargs)


def work_revision_id(*args: Any, **kwargs: Any) -> Any:
    return _LIFECYCLE.work_revision_id(*args, **kwargs)


def classify_legacy_expression(*args: Any, **kwargs: Any) -> Any:
    return _GET10.classify_legacy_expression(*args, **kwargs)


def new_epoch_config(*args: Any, **kwargs: Any) -> Any:
    return _GET10.new_epoch_config(*args, **kwargs)


def validate_get10_candidate(*args: Any, **kwargs: Any) -> Any:
    return _GET10.validate_candidate(*args, **kwargs)


__all__ = [
    "GET10_ISSUE_NUMBER",
    "GET10_PAYOUT_VECTOR",
    "GET10_PRIOR_ART",
    "GET10_VALIDATOR_ID",
    "GET10_VALIDATOR_VERSION",
    "AcceptedResolutionPlan",
    "AccountBalance",
    "AuthorPlanDecision",
    "Binding",
    "ControlGroupBinding",
    "DraftIssue",
    "Get10PriorArt",
    "Get10Validation",
    "GitHubAccount",
    "GitHubEvent",
    "GitHubEventBatch",
    "GitHubReadBoundary",
    "IdentityError",
    "IdentityRegistry",
    "LedgerTransition",
    "LifecycleEvent",
    "NextAction",
    "PauseState",
    "PlanActivation",
    "PlanError",
    "PlanIntakeState",
    "PlanStage",
    "ProgramEscrow",
    "ProtocolState",
    "ReleaseInvitation",
    "ResolutionPlanRevision",
    "ResolutionPlanRuntimeState",
    "ResolvedWorkInput",
    "RoleState",
    "Ruleset",
    "RulesetError",
    "RuntimeProjection",
    "SelectedWorkInput",
    "Settlement",
    "StageContract",
    "StageDeadline",
    "StageSchedule",
    "StageState",
    "StageTask",
    "StageTaskState",
    "TriageAssessment",
    "TriageFeedback",
    "WorkRevision",
    "WorkState",
    "accept_github_evidence_batch",
    "activate_resolution_plan",
    "apply_lifecycle_event",
    "author_plan_decision_id",
    "author_plan_decision_key",
    "classify_legacy_expression",
    "initial_github_evidence_state",
    "lifecycle_event_id",
    "load_ruleset",
    "make_lifecycle_event",
    "new_epoch_config",
    "next_action",
    "program_escrow_id",
    "project_runtime",
    "record_author_plan_decision",
    "record_plan_revision",
    "record_triage_assessment",
    "resolution_plan_id",
    "resolution_plan_revision_id",
    "stage_contract_id",
    "stage_task_id",
    "start_runtime",
    "triage_assessment_id",
    "triage_assignment_id",
    "triage_completion_id",
    "validate_get10_candidate",
    "work_id",
    "work_revision_id",
]
