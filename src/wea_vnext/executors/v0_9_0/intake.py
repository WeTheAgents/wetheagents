"""Resolution Plan intake and atomic first-child activation for ruleset 0.9."""

from __future__ import annotations

import hashlib
import re
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_dumps, canonical_hash, freeze_json, thaw_json
from .deadlines import materialize_deadline
from .events import (
    ConfirmedReadBoundary,
    GitHubEvent,
    GitHubEventBatch,
    GitHubReadBoundary,
)
from .identity import (
    IdentityAuthority,
    IdentityError,
    IdentityRegistry,
    authorize_agent,
    authorize_issue_author,
    resolve_binding,
)
from .model import ProtocolState, ReadBlocker
from .rules import load_ruleset
from .sources import normalized
from .transition import apply_batch as _apply_github_batch


class PlanError(ValueError):
    """Raised when Resolution Plan evidence or state is invalid."""


_HASH = re.compile(r"[0-9a-f]{64}")
_STAGE_KEY = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_VERIFIED_RUNTIME: tuple[str, str, str] | None = None
_WEA_VERIFIER_CAPABILITY: object | None = globals().get("_WEA_VERIFIER_CAPABILITY")


def _activation_state_functions() -> tuple[Any, Any]:
    capability = object()

    def allowed(candidate: object | None) -> bool:
        return candidate is capability

    def verified_replace(state: Any, changes: Mapping[str, object]) -> Any:
        state_type = type(state)
        candidate = object.__new__(state_type)
        for field in fields(state_type):
            if field.init:
                object.__setattr__(
                    candidate,
                    field.name,
                    changes.get(field.name, object.__getattribute__(state, field.name)),
                )
        object.__setattr__(candidate, "_verified_activation_marker", capability)
        try:
            candidate.__post_init__()
        finally:
            object.__delattr__(candidate, "_verified_activation_marker")
        return candidate

    return allowed, verified_replace


_is_verified_activation, _verified_activation_replace = _activation_state_functions()
del _activation_state_functions


def _state_seal_functions() -> tuple[Any, Any]:
    seals: dict[int, tuple[weakref.ReferenceType[Any], str]] = {}

    def remember(state: Any, digest: str) -> None:
        identity = id(state)

        def forget(reference: weakref.ReferenceType[Any]) -> None:
            current = seals.get(identity)
            if current is not None and current[0] is reference:
                seals.pop(identity, None)

        reference = weakref.ref(state, forget)
        seals[identity] = (reference, digest)

    def read(state: Any) -> str | None:
        sealed = seals.get(id(state))
        if sealed is None or sealed[0]() is not state:
            return None
        return sealed[1]

    return remember, read


_remember_state, _read_state_seal = _state_seal_functions()
del _state_seal_functions


def _text(field: str, value: object) -> str:
    if type(value) is not str or not value:
        raise PlanError(f"{field}: must be a non-empty string")
    return value


def _positive_int(field: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise PlanError(f"{field}: must be a positive integer")
    return value


def _non_negative_int(field: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise PlanError(f"{field}: must be a non-negative integer")
    return value


def _utc(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PlanError(f"{field}: must be timezone-aware")
    offset = value.utcoffset()
    if offset is None:
        raise PlanError(f"{field}: must be timezone-aware")
    converted = value.astimezone(timezone.utc)
    return datetime(
        converted.year,
        converted.month,
        converted.day,
        converted.hour,
        converted.minute,
        converted.second,
        converted.microsecond,
        tzinfo=timezone.utc,
        fold=converted.fold,
    )


def _timestamp(value: datetime) -> str:
    return _utc("timestamp", value).isoformat().replace("+00:00", "Z")


def _source_order(value: Any) -> tuple[datetime, str, str]:
    return (
        object.__getattribute__(value, "effective_at"),
        object.__getattribute__(value, "source_comment_id"),
        object.__getattribute__(value, "source_revision_id"),
    )


def _draft_source_order(value: Any) -> tuple[datetime, str, str]:
    return (
        object.__getattribute__(value, "effective_at"),
        object.__getattribute__(value, "issue_id"),
        object.__getattribute__(value, "issue_revision_id"),
    )


def _triage_assignment_source_order(value: Any) -> tuple[datetime, str, str]:
    return (
        object.__getattribute__(value, "assignment_effective_at"),
        object.__getattribute__(value, "assignment_source_comment_id"),
        object.__getattribute__(value, "assignment_source_revision_id"),
    )


def _triage_completion_source_order(value: Any) -> tuple[datetime, str, str]:
    return (
        object.__getattribute__(value, "completion_effective_at"),
        object.__getattribute__(value, "completion_source_comment_id"),
        object.__getattribute__(value, "completion_source_revision_id"),
    )


def _hash(field: str, value: object) -> str:
    if type(value) is not str or _HASH.fullmatch(value) is None:
        raise PlanError(f"{field}: must be a lowercase SHA-256 digest")
    return value


def _snapshot(field: str, value: object, digest: object) -> tuple[str, str]:
    text = _text(field, value)
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    actual = _hash(f"{field}_hash", digest)
    if actual != expected:
        raise PlanError(f"{field}_hash: does not match exact snapshot")
    return text, actual


def _canonical_snapshot(
    field: str, value: object, digest: object, declaration: Mapping[str, Any]
) -> tuple[str, str]:
    text, actual = _snapshot(field, value, digest)
    expected = canonical_dumps(declaration).decode("utf-8")
    if text != expected:
        raise PlanError(f"declaration: {field} does not match normalized evidence")
    return text, actual


def _snapshot_runtime(runtime: Any) -> tuple[Any, Any, Any]:
    if isinstance(runtime, tuple) and tuple.__len__(runtime) == 3:
        return tuple(tuple.__getitem__(runtime, index) for index in range(3))
    return (
        object.__getattribute__(runtime, "ruleset_hash"),
        object.__getattribute__(runtime, "tide_interface_version"),
        object.__getattribute__(runtime, "executor_manifest_hash"),
    )


def _rebuild_exact(value: Any, expected: type[Any], name: str) -> Any:
    """Re-run exact dataclass validation at every untrusted record boundary."""
    if type(value) is not expected:
        raise PlanError(f"evidence_boundary: {name} must use exact verified type")
    try:
        payload = {
            field.name: object.__getattribute__(value, field.name)
            for field in fields(expected)
            if field.init
        }
        return expected(**payload)
    except PlanError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError(f"evidence_boundary: {name} is malformed") from exc


def _bind_verified_runtime(runtime: Any, verifier_capability: object) -> None:
    global _VERIFIED_RUNTIME
    if (
        _WEA_VERIFIER_CAPABILITY is None
        or verifier_capability is not _WEA_VERIFIER_CAPABILITY
    ):
        raise PlanError("runtime: binding requires the manifest verifier")
    candidate = _snapshot_runtime(runtime)
    if any(type(value) is not str for value in candidate):
        raise PlanError("runtime: verified triple must contain exact strings")
    expected_ruleset_hash = load_ruleset().content_hash
    if candidate[0] != expected_ruleset_hash or candidate[1] != "0.9":
        raise PlanError("runtime: does not match executor 0.9.0")
    if _VERIFIED_RUNTIME is not None and _VERIFIED_RUNTIME != candidate:
        raise PlanError("runtime: executor is already bound to another triple")
    _VERIFIED_RUNTIME = candidate  # type: ignore[assignment]


def _verified_runtime() -> tuple[str, str, str]:
    if _VERIFIED_RUNTIME is None:
        raise PlanError("runtime: executor must be manifest verified")
    return _VERIFIED_RUNTIME


def _rebuild_github_event(value: Any) -> GitHubEvent:
    if type(value) is not GitHubEvent:
        raise PlanError("evidence_boundary: GitHub event has an invalid type")
    try:
        return GitHubEvent(
            repository_id=object.__getattribute__(value, "repository_id"),
            object_kind=object.__getattribute__(value, "object_kind"),
            object_id=object.__getattribute__(value, "object_id"),
            revision_id=object.__getattribute__(value, "revision_id"),
            effective_at=object.__getattribute__(value, "effective_at"),
            body=object.__getattribute__(value, "body"),
            content_hash=object.__getattribute__(value, "content_hash"),
            actor_account_id=object.__getattribute__(value, "actor_account_id"),
            payload=thaw_json(object.__getattribute__(value, "payload")),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError("evidence_boundary: GitHub event is malformed") from exc


def _rebuild_read_boundary(value: Any) -> GitHubReadBoundary:
    if type(value) is not GitHubReadBoundary:
        raise PlanError("evidence_boundary: GitHub boundary has an invalid type")
    try:
        return GitHubReadBoundary(
            repository=object.__getattribute__(value, "repository"),
            repository_id=object.__getattribute__(value, "repository_id"),
            captured_at=object.__getattribute__(value, "captured_at"),
            read_sequence=object.__getattribute__(value, "read_sequence"),
            end_cursor=object.__getattribute__(value, "end_cursor"),
            complete=object.__getattribute__(value, "complete"),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError("evidence_boundary: GitHub boundary is malformed") from exc


def _rebuild_confirmed_boundary(value: Any) -> ConfirmedReadBoundary:
    if type(value) is not ConfirmedReadBoundary:
        raise PlanError("evidence_boundary: confirmed boundary has an invalid type")
    try:
        return ConfirmedReadBoundary(
            boundary=_rebuild_read_boundary(object.__getattribute__(value, "boundary")),
            batch_hash=object.__getattribute__(value, "batch_hash"),
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError("evidence_boundary: confirmed boundary is malformed") from exc


def _rebuild_github_state(value: Any) -> ProtocolState:
    if type(value) is not ProtocolState:
        raise PlanError("evidence_boundary: GitHub state has an invalid type")
    try:
        rebuilt = ProtocolState(
            schema_version=object.__getattribute__(value, "schema_version"),
            ruleset_hash=object.__getattribute__(value, "ruleset_hash"),
            tide_interface_version=object.__getattribute__(
                value, "tide_interface_version"
            ),
            executor_manifest_hash=object.__getattribute__(
                value, "executor_manifest_hash"
            ),
            boundaries=tuple(
                _rebuild_confirmed_boundary(item)
                for item in object.__getattribute__(value, "boundaries")
            ),
            read_blockers=tuple(
                _rebuild_exact(item, ReadBlocker, "GitHub read blocker")
                for item in object.__getattribute__(value, "read_blockers")
            ),
            processed_event_keys=tuple(
                object.__getattribute__(value, "processed_event_keys")
            ),
            events=tuple(
                _rebuild_github_event(item)
                for item in object.__getattribute__(value, "events")
            ),
        )
    except PlanError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError("evidence_boundary: GitHub state is malformed") from exc
    if (
        rebuilt.ruleset_hash,
        rebuilt.tide_interface_version,
        rebuilt.executor_manifest_hash,
    ) != _verified_runtime():
        raise PlanError("runtime: GitHub evidence belongs to another executor")
    return rebuilt


def _rebuild_github_batch(value: Any) -> GitHubEventBatch:
    if type(value) is not GitHubEventBatch:
        raise PlanError("evidence_boundary: GitHub batch has an invalid type")
    try:
        return GitHubEventBatch(
            boundary=_rebuild_read_boundary(object.__getattribute__(value, "boundary")),
            events=tuple(
                _rebuild_github_event(item)
                for item in object.__getattribute__(value, "events")
            ),
        )
    except PlanError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError("evidence_boundary: GitHub batch is malformed") from exc


def initial_github_evidence_state() -> ProtocolState:
    ruleset_hash, interface_version, manifest_hash = _verified_runtime()
    return ProtocolState(
        schema_version=1,
        ruleset_hash=ruleset_hash,
        tide_interface_version=interface_version,
        executor_manifest_hash=manifest_hash,
    )


def accept_github_evidence_batch(
    state: ProtocolState, batch: GitHubEventBatch
) -> ProtocolState:
    state = _rebuild_github_state(state)
    batch = _rebuild_github_batch(batch)
    try:
        return _apply_github_batch(state, batch).state
    except (TypeError, ValueError) as exc:
        raise PlanError("evidence_boundary: GitHub batch was not accepted") from exc


def _require_github_event(
    github_state: ProtocolState,
    *,
    repository_id: str,
    object_kind: str,
    object_id: str,
    revision_id: str,
    actor_account_id: str,
    body: str,
    body_hash: str,
    effective_at: datetime,
    must_be_latest: bool = False,
    expected_payload: Mapping[str, Any] | None = None,
) -> GitHubEvent:
    if any(
        blocker.repository_id == repository_id for blocker in github_state.read_blockers
    ):
        raise PlanError("evidence_boundary: repository has an unresolved read blocker")
    matches = [
        item
        for item in github_state.events
        if item.repository_id == repository_id
        and item.object_kind == object_kind
        and item.object_id == object_id
        and item.revision_id == revision_id
    ]
    if len(matches) != 1:
        raise PlanError("evidence_boundary: exact accepted GitHub revision is missing")
    event = matches[0]
    try:
        comparison_body = (
            normalized(event) if object_kind == "issue_comment" else event.body
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise PlanError(
            "declaration: source cannot produce the requested record"
        ) from exc
    if (
        event.actor_account_id != actor_account_id
        or comparison_body != body
        or hashlib.sha256(comparison_body.encode("utf-8")).hexdigest() != body_hash
        or event.effective_at != effective_at
    ):
        raise PlanError(
            "evidence_boundary: accepted GitHub revision content does not match"
        )
    if expected_payload is not None:
        import json

        if json.loads(normalized(event)) != dict(expected_payload):
            raise PlanError("declaration: Issue body does not declare the exact Draft")
    if must_be_latest:
        revisions = [
            item
            for item in github_state.events
            if item.repository_id == repository_id
            and item.object_kind == object_kind
            and item.object_id == object_id
        ]
        if event is not max(revisions, key=lambda item: item.canonical_order_key):
            raise PlanError(
                "evidence_boundary: source is not the latest accepted revision"
            )
    return event


def _assert_verified_call_runtime(runtime: Any) -> None:
    if _snapshot_runtime(runtime) != _verified_runtime():
        raise PlanError("runtime: call does not belong to executor 0.9.0")


def resolution_plan_id(repository_id: str, issue_id: str) -> str:
    repository_id = _text("repository_id", repository_id)
    issue_id = _text("issue_id", issue_id)
    return f"resolution-plan:{repository_id}:{issue_id}"


def resolution_plan_revision_id(plan_id: str, revision_number: int) -> str:
    plan_id = _text("plan_id", plan_id)
    revision_number = _positive_int("revision_number", revision_number)
    return f"{plan_id}:revision:{revision_number}"


def triage_assessment_id(
    repository_id: str, issue_id: str, issue_revision_id: str
) -> str:
    return (
        "triage-assessment:"
        f"{_text('repository_id', repository_id)}:"
        f"{_text('issue_id', issue_id)}:"
        f"{_text('issue_revision_id', issue_revision_id)}"
    )


def triage_assignment_id(assessment_id: str) -> str:
    return f"triage-assignment:{_text('assessment_id', assessment_id)}"


def triage_completion_id(assessment_id: str) -> str:
    return f"triage-completion:{_text('assessment_id', assessment_id)}"


def author_plan_decision_id(plan_revision_id: str, source_revision_id: str) -> str:
    return (
        "author-plan-decision:"
        f"{_text('plan_revision_id', plan_revision_id)}:"
        f"{_text('source_revision_id', source_revision_id)}"
    )


def author_plan_decision_key(plan_revision_id: str, source_revision_id: str) -> str:
    return (
        "plan-decision:"
        f"{_text('plan_revision_id', plan_revision_id)}:"
        f"{_text('source_revision_id', source_revision_id)}"
    )


def program_escrow_id(plan_id: str) -> str:
    return f"plan-escrow:{_text('plan_id', plan_id)}"


def stage_contract_id(plan_id: str, stage_key: str) -> str:
    return f"{_text('plan_id', plan_id)}:contract:{_stage_key(stage_key)}"


def stage_task_id(contract_id: str) -> str:
    return f"task:{_text('contract_id', contract_id)}"


def _stage_key(value: object) -> str:
    value = _text("stage_key", value)
    if _STAGE_KEY.fullmatch(value) is None:
        raise PlanError("stage_key: must be a canonical lowercase identifier")
    return value


def _exact_config(config: object) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        raise PlanError("matrix: mode config must be an object")
    try:
        plain = thaw_json(freeze_json(config))
    except (TypeError, ValueError) as exc:
        raise PlanError("matrix: mode config must be canonical JSON") from exc
    if type(plain) is not dict:
        raise PlanError("matrix: mode config must be an object")
    return plain


def _payout_vector(value: object, *, field: str = "payout_vector") -> tuple[int, ...]:
    if type(value) not in {list, tuple} or not value:
        raise PlanError(f"matrix: {field} must be a non-empty finite vector")
    assert isinstance(value, (list, tuple))
    vector = tuple(value)
    if any(type(item) is not int or item < 1 for item in vector):
        raise PlanError(f"matrix: {field} must contain positive integer WEA")
    return vector


def _acceptance_config(value: object) -> Mapping[str, Any]:
    config = _exact_config(value)
    kind = config.get("kind")
    if kind == "author" and set(config) == {"kind"}:
        return freeze_json(config)
    if (
        kind == "normalized_validator"
        and set(config) == {"kind", "validator_id", "version"}
        and (config["validator_id"], config["version"])
        in {
            ("get10-normalized-code", "1"),
            ("prefixed-text-normalized-code", "1"),
        }
    ):
        return freeze_json(config)
    raise PlanError("matrix: acceptance authority is invalid")


def _validate_stage_terms(
    depth: str, mode: str, allocation_wea: int, config: object
) -> Mapping[str, Any]:
    rules = load_ruleset().content
    allowed = rules["depth_modes"].get(depth)
    if allowed is None or mode not in allowed:
        raise PlanError("matrix: depth/mode pair is not supported")
    config = _exact_config(config)
    if mode == "ranked":
        if set(config) != {"payout_vector", "winner_count"}:
            raise PlanError("matrix: Ranked config has invalid keys")
        winners = _positive_int("winner_count", config["winner_count"])
        vector = _payout_vector(config["payout_vector"])
        if len(vector) != winners:
            raise PlanError("matrix: Ranked payout length must equal winner_count")
        if sum(vector) != allocation_wea:
            raise PlanError("money: Ranked payouts must equal stage allocation")
    elif mode == "flat_pod":
        if set(config) != {"acceptance", "additive", "payout_vector", "slots"}:
            raise PlanError("matrix: Flat PoD config has invalid keys")
        _acceptance_config(config["acceptance"])
        if config["additive"] is not True:
            raise PlanError("matrix: Flat PoD must be additive")
        slots = _positive_int("slots", config["slots"])
        vector = _payout_vector(config["payout_vector"])
        if len(vector) != slots or len(set(vector)) != 1:
            raise PlanError("matrix: Flat PoD requires one equal payout per slot")
        if sum(vector) != allocation_wea:
            raise PlanError("money: Flat PoD payouts must equal stage allocation")
    elif mode == "frontier":
        if set(config) != {
            "acceptance",
            "incentive",
            "payout_vector",
            "prior_art",
            "snapshot_identity",
        }:
            raise PlanError("matrix: Frontier config has invalid keys")
        _acceptance_config(config["acceptance"])
        if type(config["prior_art"]) is not list:
            raise PlanError("matrix: Frontier prior_art must be a finite list")
        if config["incentive"] not in {"linear", "fibonacci"}:
            raise PlanError("matrix: Frontier incentive must be linear or fibonacci")
        if config["snapshot_identity"] != "model+genome+runtime":
            raise PlanError("matrix: Frontier snapshot identity is incomplete")
        vector = _payout_vector(config["payout_vector"])
        if sum(vector) != allocation_wea:
            raise PlanError("money: Frontier payouts must equal stage allocation")
        if config["incentive"] == "linear" and len(vector) > 1:
            step = vector[1] - vector[0]
            if step < 1 or any(
                vector[index] - vector[index - 1] != step
                for index in range(2, len(vector))
            ):
                raise PlanError("matrix: Linear Frontier vector is not linear")
        if config["incentive"] == "fibonacci" and any(
            vector[index] != vector[index - 1] + vector[index - 2]
            for index in range(2, len(vector))
        ):
            raise PlanError("matrix: Fibonacci Frontier vector is not contiguous")
    elif mode == "duel":
        if set(config) != {"admission", "invitations", "positions", "rounds"}:
            raise PlanError("matrix: Duel config has invalid keys")
        positions = config["positions"]
        if (
            type(positions) is not list
            or len(positions) != 2
            or any(type(item) is not str or not item for item in positions)
            or positions[0] == positions[1]
        ):
            raise PlanError("matrix: Duel requires exactly two distinct positions")
        if config["rounds"] != 3:
            raise PlanError("matrix: Duel requires exactly three rounds")
        admission = config["admission"]
        invitations = config["invitations"]
        if admission not in {"open", "invited"} or type(invitations) is not list:
            raise PlanError("matrix: Duel admission is invalid")
        if admission == "open" and invitations:
            raise PlanError("matrix: open Duel cannot contain invitations")
        if admission == "invited":
            if (
                len(invitations) != 2
                or any(
                    type(item) is not dict
                    or set(item) != {"agent_id", "position"}
                    or type(item["agent_id"]) is not str
                    or not item["agent_id"]
                    or item["position"] not in positions
                    for item in invitations
                )
                or len({item["agent_id"] for item in invitations}) != 2
                or {item["position"] for item in invitations} != set(positions)
            ):
                raise PlanError(
                    "matrix: invited Duel must bind two Agents to positions"
                )
        duel = rules["modes"]["duel"]
        if (
            allocation_wea < duel["minimum_bank_wea"]
            or allocation_wea % duel["bank_multiple_wea"] != 0
        ):
            raise PlanError("money: Duel allocation must satisfy its bank rule")
    else:  # pragma: no cover - closed by versioned matrix
        raise PlanError("matrix: unknown mode")
    return freeze_json(config)


@dataclass(frozen=True)
class AccountBalance:
    account_id: str
    amount_wea: int

    def __post_init__(self) -> None:
        _text("account_id", self.account_id)
        _non_negative_int("amount_wea", self.amount_wea)

    def to_data(self) -> dict[str, object]:
        return {"account_id": self.account_id, "amount_wea": self.amount_wea}


@dataclass(frozen=True)
class DraftIssue:
    repository_id: str
    issue_id: str
    issue_number: int
    issue_revision_id: str
    creator_github_account_id: str
    author_agent_id: str
    author_binding_id: str
    author_binding_version: int
    body: str
    max_bank_wea: int
    effective_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "repository_id",
            "issue_id",
            "issue_revision_id",
            "creator_github_account_id",
            "author_agent_id",
            "author_binding_id",
            "body",
        ):
            _text(field, getattr(self, field))
        _positive_int("issue_number", self.issue_number)
        _positive_int("author_binding_version", self.author_binding_version)
        _positive_int("max_bank_wea", self.max_bank_wea)
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    @property
    def body_hash(self) -> str:
        return hashlib.sha256(self.body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TriageAssessment:
    repository_id: str
    assessment_id: str
    assignment_id: str
    completion_id: str
    reviewer_agent_id: str
    reviewer_github_account_id: str
    reviewer_binding_id: str
    reviewer_binding_version: int
    agent0_github_account_id: str
    agent0_binding_id: str
    agent0_binding_version: int
    assignment_source_comment_id: str
    assignment_source_revision_id: str
    assignment_snapshot: str
    assignment_snapshot_hash: str
    assignment_effective_at: datetime
    completion_source_comment_id: str
    completion_source_revision_id: str
    completion_snapshot: str
    completion_snapshot_hash: str
    completion_effective_at: datetime
    issue_id: str
    issue_revision_id: str
    body_hash: str
    risks: tuple[str, ...]
    advice: str
    source_comment_id: str
    source_revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "assessment_id",
            "assignment_id",
            "completion_id",
            "reviewer_agent_id",
            "reviewer_github_account_id",
            "reviewer_binding_id",
            "agent0_github_account_id",
            "agent0_binding_id",
            "assignment_source_comment_id",
            "assignment_source_revision_id",
            "completion_source_comment_id",
            "completion_source_revision_id",
            "repository_id",
            "issue_id",
            "issue_revision_id",
            "advice",
            "source_comment_id",
            "source_revision_id",
        ):
            _text(field, getattr(self, field))
        _positive_int("reviewer_binding_version", self.reviewer_binding_version)
        _positive_int("agent0_binding_version", self.agent0_binding_version)
        expected_assessment_id = triage_assessment_id(
            self.repository_id, self.issue_id, self.issue_revision_id
        )
        if self.assessment_id != expected_assessment_id:
            raise PlanError("evidence_boundary: assessment ID is not deterministic")
        if self.assignment_id != triage_assignment_id(expected_assessment_id):
            raise PlanError("evidence_boundary: assignment ID is not deterministic")
        if self.completion_id != triage_completion_id(expected_assessment_id):
            raise PlanError("evidence_boundary: completion ID is not deterministic")
        _hash("body_hash", self.body_hash)
        assignment_effective_at = _utc(
            "assignment_effective_at", self.assignment_effective_at
        )
        review_effective_at = _utc("effective_at", self.effective_at)
        completion_effective_at = _utc(
            "completion_effective_at", self.completion_effective_at
        )
        assignment_order = (
            assignment_effective_at,
            self.assignment_source_comment_id,
            self.assignment_source_revision_id,
        )
        review_order = (
            review_effective_at,
            self.source_comment_id,
            self.source_revision_id,
        )
        completion_order = (
            completion_effective_at,
            self.completion_source_comment_id,
            self.completion_source_revision_id,
        )
        if not assignment_order < review_order < completion_order:
            raise PlanError("evidence_boundary: Triage evidence order is invalid")
        object.__setattr__(self, "assignment_effective_at", assignment_effective_at)
        object.__setattr__(self, "effective_at", review_effective_at)
        object.__setattr__(self, "completion_effective_at", completion_effective_at)
        if type(self.risks) is not tuple or any(
            type(item) is not str or not item for item in self.risks
        ):
            raise PlanError("declaration: risks must be exact non-empty strings")
        _canonical_snapshot(
            "assignment_snapshot",
            self.assignment_snapshot,
            self.assignment_snapshot_hash,
            {
                "agent0_binding_id": self.agent0_binding_id,
                "agent0_binding_version": self.agent0_binding_version,
                "agent0_github_account_id": self.agent0_github_account_id,
                "assignment_id": self.assignment_id,
                "issue_id": self.issue_id,
                "issue_revision_id": self.issue_revision_id,
                "kind": "triage_assignment",
                "repository_id": self.repository_id,
                "reviewer_agent_id": self.reviewer_agent_id,
                "reviewer_binding_id": self.reviewer_binding_id,
                "reviewer_binding_version": self.reviewer_binding_version,
                "reviewer_github_account_id": self.reviewer_github_account_id,
            },
        )
        _canonical_snapshot(
            "snapshot",
            self.snapshot,
            self.snapshot_hash,
            {
                "advice": self.advice,
                "agent0_binding_id": self.agent0_binding_id,
                "agent0_binding_version": self.agent0_binding_version,
                "agent0_github_account_id": self.agent0_github_account_id,
                "assessment_id": self.assessment_id,
                "assignment_id": self.assignment_id,
                "body_hash": self.body_hash,
                "completion_id": self.completion_id,
                "issue_id": self.issue_id,
                "issue_revision_id": self.issue_revision_id,
                "kind": "triage_assessment",
                "repository_id": self.repository_id,
                "reviewer_agent_id": self.reviewer_agent_id,
                "reviewer_binding_id": self.reviewer_binding_id,
                "reviewer_binding_version": self.reviewer_binding_version,
                "reviewer_github_account_id": self.reviewer_github_account_id,
                "risks": list(self.risks),
            },
        )
        _canonical_snapshot(
            "completion_snapshot",
            self.completion_snapshot,
            self.completion_snapshot_hash,
            {
                "agent0_binding_id": self.agent0_binding_id,
                "agent0_binding_version": self.agent0_binding_version,
                "agent0_github_account_id": self.agent0_github_account_id,
                "assessment_id": self.assessment_id,
                "assignment_id": self.assignment_id,
                "completion_id": self.completion_id,
                "issue_id": self.issue_id,
                "issue_revision_id": self.issue_revision_id,
                "kind": "triage_completion",
                "repository_id": self.repository_id,
            },
        )

    def to_data(self) -> dict[str, object]:
        return {
            "advice": self.advice,
            "agent0_binding_id": self.agent0_binding_id,
            "agent0_binding_version": self.agent0_binding_version,
            "agent0_github_account_id": self.agent0_github_account_id,
            "assessment_id": self.assessment_id,
            "assignment_effective_at": _timestamp(self.assignment_effective_at),
            "assignment_id": self.assignment_id,
            "assignment_snapshot": self.assignment_snapshot,
            "assignment_snapshot_hash": self.assignment_snapshot_hash,
            "assignment_source_comment_id": self.assignment_source_comment_id,
            "assignment_source_revision_id": self.assignment_source_revision_id,
            "body_hash": self.body_hash,
            "completion_id": self.completion_id,
            "completion_effective_at": _timestamp(self.completion_effective_at),
            "completion_snapshot": self.completion_snapshot,
            "completion_snapshot_hash": self.completion_snapshot_hash,
            "completion_source_comment_id": self.completion_source_comment_id,
            "completion_source_revision_id": self.completion_source_revision_id,
            "effective_at": _timestamp(self.effective_at),
            "issue_id": self.issue_id,
            "issue_revision_id": self.issue_revision_id,
            "reviewer_agent_id": self.reviewer_agent_id,
            "reviewer_binding_id": self.reviewer_binding_id,
            "reviewer_binding_version": self.reviewer_binding_version,
            "reviewer_github_account_id": self.reviewer_github_account_id,
            "repository_id": self.repository_id,
            "risks": list(self.risks),
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "source_comment_id": self.source_comment_id,
            "source_revision_id": self.source_revision_id,
        }


@dataclass(frozen=True)
class SelectedWorkInput:
    source_stage_key: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_stage_key", _stage_key(self.source_stage_key))

    def to_data(self) -> dict[str, str]:
        return {"kind": "selected_work_of", "source_stage_key": self.source_stage_key}


@dataclass(frozen=True)
class ResolvedWorkInput:
    source_stage_key: str
    source_contract_id: str
    work_id: str
    revision_id: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_stage_key", _stage_key(self.source_stage_key))
        for field in ("source_contract_id", "work_id", "revision_id"):
            _text(field, getattr(self, field))
        _hash("content_hash", self.content_hash)

    def to_data(self) -> dict[str, str]:
        return {
            "content_hash": self.content_hash,
            "kind": "accepted_work_revision",
            "revision_id": self.revision_id,
            "source_contract_id": self.source_contract_id,
            "source_stage_key": self.source_stage_key,
            "work_id": self.work_id,
        }


@dataclass(frozen=True)
class StageSchedule:
    intake_seconds: int | None = None
    join_seconds: int | None = None
    move_seconds: tuple[int, ...] = ()
    author_decision_seconds: int | None = None

    def __post_init__(self) -> None:
        for field in ("intake_seconds", "join_seconds", "author_decision_seconds"):
            value = getattr(self, field)
            if value is not None:
                _positive_int(field, value)
        if type(self.move_seconds) is not tuple or any(
            type(item) is not int or item < 1 for item in self.move_seconds
        ):
            raise PlanError("matrix: move_seconds must contain positive durations")

    def validate_mode(self, mode: str) -> None:
        present = {
            "author_decision_seconds": self.author_decision_seconds is not None,
            "intake_seconds": self.intake_seconds is not None,
            "join_seconds": self.join_seconds is not None,
            "move_seconds": bool(self.move_seconds),
        }
        expected = {
            "ranked": {
                "author_decision_seconds": True,
                "intake_seconds": True,
                "join_seconds": False,
                "move_seconds": False,
            },
            "flat_pod": {
                "author_decision_seconds": False,
                "intake_seconds": True,
                "join_seconds": False,
                "move_seconds": False,
            },
            "frontier": {
                "author_decision_seconds": False,
                "intake_seconds": True,
                "join_seconds": False,
                "move_seconds": False,
            },
            "duel": {
                "author_decision_seconds": True,
                "intake_seconds": False,
                "join_seconds": True,
                "move_seconds": True,
            },
        }.get(mode)
        if expected is None or present != expected:
            raise PlanError("matrix: stage schedule does not match mode")
        if mode == "duel" and len(self.move_seconds) != 6:
            raise PlanError("matrix: Duel requires exactly six move durations")

    def to_data(self) -> dict[str, object]:
        return {
            "author_decision_seconds": self.author_decision_seconds,
            "intake_seconds": self.intake_seconds,
            "join_seconds": self.join_seconds,
            "move_seconds": list(self.move_seconds),
        }


@dataclass(frozen=True)
class StageDeadline:
    deadline_id: str
    kind: str
    anchor_at: datetime
    duration_seconds: int
    base_due_at: datetime
    effective_due_at: datetime
    pause_ids: tuple[str, ...] = ()
    effective_anchor_at: datetime | None = None

    def __post_init__(self) -> None:
        _text("deadline_id", self.deadline_id)
        _text("kind", self.kind)
        anchor = _utc("anchor_at", self.anchor_at)
        duration = _positive_int("duration_seconds", self.duration_seconds)
        base = _utc("base_due_at", self.base_due_at)
        effective = _utc("effective_due_at", self.effective_due_at)
        effective_anchor = _utc(
            "effective_anchor_at",
            self.anchor_at
            if self.effective_anchor_at is None
            else self.effective_anchor_at,
        )
        if base != materialize_deadline(anchor, duration):
            raise PlanError("evidence_boundary: deadline does not match its anchor")
        if effective < base:
            raise PlanError("evidence_boundary: effective deadline precedes base")
        if effective_anchor < anchor or effective_anchor >= effective:
            raise PlanError("evidence_boundary: effective deadline window is invalid")
        if type(self.pause_ids) is not tuple or any(
            type(item) is not str or not item for item in self.pause_ids
        ):
            raise PlanError("evidence_boundary: pause IDs must be exact strings")
        if len(self.pause_ids) != len(set(self.pause_ids)):
            raise PlanError("evidence_boundary: a pause can move a deadline once")
        object.__setattr__(self, "anchor_at", anchor)
        object.__setattr__(self, "base_due_at", base)
        object.__setattr__(self, "effective_due_at", effective)
        object.__setattr__(self, "effective_anchor_at", effective_anchor)

    def to_data(self) -> dict[str, object]:
        effective_anchor = self.effective_anchor_at
        assert effective_anchor is not None
        return {
            "anchor_at": _timestamp(self.anchor_at),
            "base_due_at": _timestamp(self.base_due_at),
            "deadline_id": self.deadline_id,
            "duration_seconds": self.duration_seconds,
            "effective_due_at": _timestamp(self.effective_due_at),
            "effective_anchor_at": _timestamp(effective_anchor),
            "kind": self.kind,
            "pause_ids": list(self.pause_ids),
        }


def initial_stage_deadlines(
    contract_id: str,
    mode: str,
    schedule: StageSchedule,
    activated_at: datetime,
) -> tuple[StageDeadline, ...]:
    contract_id = _text("contract_id", contract_id)
    activated_at = _utc("activated_at", activated_at)
    schedule = _rebuild_exact(schedule, StageSchedule, "stage schedule")
    schedule.validate_mode(mode)
    if mode == "duel":
        kind = "join"
        duration = schedule.join_seconds
    else:
        kind = "intake"
        duration = schedule.intake_seconds
    assert duration is not None
    due_at = materialize_deadline(activated_at, duration)
    return (
        StageDeadline(
            deadline_id=f"{contract_id}:deadline:{kind}",
            kind=kind,
            anchor_at=activated_at,
            duration_seconds=duration,
            base_due_at=due_at,
            effective_due_at=due_at,
        ),
    )


@dataclass(frozen=True)
class PlanStage:
    key: str
    depth: str
    mode: str
    schedule: StageSchedule
    allocation_wea: int
    config: Mapping[str, Any]
    expected_output: str
    inputs: tuple[SelectedWorkInput, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "key", _stage_key(self.key))
        depth = _text("depth", self.depth)
        mode = _text("mode", self.mode)
        schedule = _rebuild_exact(self.schedule, StageSchedule, "stage schedule")
        schedule.validate_mode(mode)
        object.__setattr__(self, "schedule", schedule)
        allocation = _positive_int("allocation_wea", self.allocation_wea)
        _text("expected_output", self.expected_output)
        if type(self.inputs) is not tuple or any(
            type(item) is not SelectedWorkInput for item in self.inputs
        ):
            raise PlanError("evidence_boundary: inputs must use symbolic selectors")
        inputs = tuple(
            _rebuild_exact(item, SelectedWorkInput, "symbolic selector")
            for item in self.inputs
        )
        object.__setattr__(self, "inputs", inputs)
        if len({item.source_stage_key for item in self.inputs}) != len(self.inputs):
            raise PlanError("evidence_boundary: stage input selectors must be unique")
        object.__setattr__(
            self, "config", _validate_stage_terms(depth, mode, allocation, self.config)
        )

    def to_data(self) -> dict[str, object]:
        return {
            "allocation_wea": self.allocation_wea,
            "config": thaw_json(self.config),
            "depth": self.depth,
            "expected_output": self.expected_output,
            "inputs": [item.to_data() for item in self.inputs],
            "key": self.key,
            "mode": self.mode,
            "schedule": self.schedule.to_data(),
        }


@dataclass(frozen=True)
class ResolutionPlanRevision:
    plan_id: str
    revision_id: str
    revision_number: int
    parent_revision_id: str | None
    repository_id: str
    issue_id: str
    issue_revision_id: str
    body_hash: str
    triage_assessment_id: str
    proposer_kind: str
    proposer_agent_id: str
    proposer_github_account_id: str
    proposer_binding_id: str
    proposer_binding_version: int
    author_agent_id: str
    total_bank_wea: int
    stages: tuple[PlanStage, ...]
    source_comment_id: str
    source_revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "plan_id",
            "revision_id",
            "repository_id",
            "issue_id",
            "issue_revision_id",
            "triage_assessment_id",
            "proposer_agent_id",
            "proposer_github_account_id",
            "proposer_binding_id",
            "author_agent_id",
            "source_comment_id",
            "source_revision_id",
        ):
            _text(field, getattr(self, field))
        number = _positive_int("revision_number", self.revision_number)
        _positive_int("proposer_binding_version", self.proposer_binding_version)
        _positive_int("total_bank_wea", self.total_bank_wea)
        _hash("body_hash", self.body_hash)
        if self.plan_id != resolution_plan_id(self.repository_id, self.issue_id):
            raise PlanError("evidence_boundary: plan_id is not deterministic")
        if self.revision_id != resolution_plan_revision_id(self.plan_id, number):
            raise PlanError("evidence_boundary: revision_id is not deterministic")
        if self.proposer_kind not in {"triage", "author"}:
            raise PlanError("authority: proposer_kind must be triage or author")
        if number == 1:
            if self.parent_revision_id is not None or self.proposer_kind != "triage":
                raise PlanError(
                    "evidence_boundary: first Plan revision must come from Triage"
                )
        elif type(self.parent_revision_id) is not str or not self.parent_revision_id:
            raise PlanError("evidence_boundary: later Plan revision requires a parent")
        if (
            type(self.stages) is not tuple
            or not self.stages
            or any(type(item) is not PlanStage for item in self.stages)
        ):
            raise PlanError("matrix: Plan requires exact stage records")
        stages = tuple(
            _rebuild_exact(item, PlanStage, "Plan stage") for item in self.stages
        )
        object.__setattr__(self, "stages", stages)
        keys = [stage.key for stage in self.stages]
        if len(keys) != len(set(keys)):
            raise PlanError("matrix: stage keys must be unique")
        earlier: dict[str, str] = {}
        for stage in self.stages:
            for selector in stage.inputs:
                if selector.source_stage_key not in earlier:
                    raise PlanError(
                        "evidence_boundary: selector must name an earlier stage"
                    )
                if earlier[selector.source_stage_key] == "flat_pod":
                    raise PlanError("matrix: Flat PoD cannot supply one selected Work")
            earlier[stage.key] = stage.mode
        if sum(stage.allocation_wea for stage in self.stages) != self.total_bank_wea:
            raise PlanError("money: stage allocations must equal total bank")
        _canonical_snapshot(
            "snapshot",
            self.snapshot,
            self.snapshot_hash,
            {"kind": "resolution_plan_revision", **self.content_data()},
        )
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def content_data(self) -> dict[str, object]:
        return {
            "author_agent_id": self.author_agent_id,
            "body_hash": self.body_hash,
            "issue_id": self.issue_id,
            "issue_revision_id": self.issue_revision_id,
            "parent_revision_id": self.parent_revision_id,
            "plan_id": self.plan_id,
            "proposer_agent_id": self.proposer_agent_id,
            "proposer_binding_id": self.proposer_binding_id,
            "proposer_binding_version": self.proposer_binding_version,
            "proposer_github_account_id": self.proposer_github_account_id,
            "proposer_kind": self.proposer_kind,
            "repository_id": self.repository_id,
            "revision_id": self.revision_id,
            "revision_number": self.revision_number,
            "stages": [item.to_data() for item in self.stages],
            "total_bank_wea": self.total_bank_wea,
            "triage_assessment_id": self.triage_assessment_id,
        }

    @property
    def content_hash(self) -> str:
        return canonical_hash(self.content_data())

    def to_data(self) -> dict[str, object]:
        return {
            **self.content_data(),
            "content_hash": self.content_hash,
            "effective_at": _timestamp(self.effective_at),
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "source_comment_id": self.source_comment_id,
            "source_revision_id": self.source_revision_id,
        }


@dataclass(frozen=True)
class AuthorPlanDecision:
    decision_id: str
    outcome: str
    plan_id: str
    plan_revision_id: str
    plan_content_hash: str
    author_agent_id: str
    author_github_account_id: str
    author_binding_id: str
    author_binding_version: int
    source_comment_id: str
    source_revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        for field in (
            "decision_id",
            "plan_id",
            "plan_revision_id",
            "author_agent_id",
            "author_github_account_id",
            "author_binding_id",
            "source_comment_id",
            "source_revision_id",
            "idempotency_key",
        ):
            _text(field, getattr(self, field))
        if self.outcome not in {"approve", "decline", "request_revision"}:
            raise PlanError("declaration: unknown author Plan decision")
        _positive_int("author_binding_version", self.author_binding_version)
        _hash("plan_content_hash", self.plan_content_hash)
        if self.decision_id != author_plan_decision_id(
            self.plan_revision_id, self.source_revision_id
        ):
            raise PlanError("evidence_boundary: decision ID is not deterministic")
        if self.idempotency_key != author_plan_decision_key(
            self.plan_revision_id, self.source_revision_id
        ):
            raise PlanError(
                "evidence_boundary: decision idempotency key is not deterministic"
            )
        _canonical_snapshot(
            "snapshot",
            self.snapshot,
            self.snapshot_hash,
            {
                "author_agent_id": self.author_agent_id,
                "author_binding_id": self.author_binding_id,
                "author_binding_version": self.author_binding_version,
                "author_github_account_id": self.author_github_account_id,
                "decision_id": self.decision_id,
                "idempotency_key": self.idempotency_key,
                "kind": "author_plan_decision",
                "outcome": self.outcome,
                "plan_content_hash": self.plan_content_hash,
                "plan_id": self.plan_id,
                "plan_revision_id": self.plan_revision_id,
            },
        )
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, object]:
        return {
            "author_agent_id": self.author_agent_id,
            "author_binding_id": self.author_binding_id,
            "author_binding_version": self.author_binding_version,
            "author_github_account_id": self.author_github_account_id,
            "decision_id": self.decision_id,
            "effective_at": _timestamp(self.effective_at),
            "idempotency_key": self.idempotency_key,
            "outcome": self.outcome,
            "plan_content_hash": self.plan_content_hash,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "source_comment_id": self.source_comment_id,
            "source_revision_id": self.source_revision_id,
        }


@dataclass(frozen=True)
class ProgramEscrow:
    escrow_id: str
    plan_id: str
    payer_agent_id: str
    deposited_wea: int
    paid_wea: int = 0
    refunded_wea: int = 0
    status: str = "active"

    def __post_init__(self) -> None:
        for field in ("escrow_id", "plan_id", "payer_agent_id"):
            _text(field, getattr(self, field))
        if self.escrow_id != program_escrow_id(self.plan_id):
            raise PlanError("money: program escrow ID is not deterministic")
        deposited = _positive_int("deposited_wea", self.deposited_wea)
        paid = _non_negative_int("paid_wea", self.paid_wea)
        refunded = _non_negative_int("refunded_wea", self.refunded_wea)
        if paid + refunded > deposited:
            raise PlanError("money: program escrow is overdrawn")
        if self.status not in {"active", "closed"}:
            raise PlanError("program escrow status is invalid")

    @property
    def available_wea(self) -> int:
        return self.deposited_wea - self.paid_wea - self.refunded_wea

    def to_data(self) -> dict[str, object]:
        return {
            "available_wea": self.available_wea,
            "deposited_wea": self.deposited_wea,
            "escrow_id": self.escrow_id,
            "paid_wea": self.paid_wea,
            "payer_agent_id": self.payer_agent_id,
            "plan_id": self.plan_id,
            "refunded_wea": self.refunded_wea,
            "status": self.status,
        }


@dataclass(frozen=True)
class LedgerTransition:
    transition_id: str
    kind: str
    debit_account_id: str
    credit_account_id: str
    amount_wea: int
    basis_id: str
    idempotency_key: str
    prior_financial_hash: str
    effective_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "transition_id",
            "kind",
            "debit_account_id",
            "credit_account_id",
            "basis_id",
            "idempotency_key",
        ):
            _text(field, getattr(self, field))
        _positive_int("amount_wea", self.amount_wea)
        _hash("prior_financial_hash", self.prior_financial_hash)
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, object]:
        return {
            "amount_wea": self.amount_wea,
            "basis_id": self.basis_id,
            "credit_account_id": self.credit_account_id,
            "debit_account_id": self.debit_account_id,
            "effective_at": _timestamp(self.effective_at),
            "idempotency_key": self.idempotency_key,
            "kind": self.kind,
            "prior_financial_hash": self.prior_financial_hash,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True)
class AcceptedResolutionPlan:
    plan_id: str
    plan_revision_id: str
    plan_content_hash: str
    approval_decision_id: str
    repository_id: str
    issue_id: str
    author_agent_id: str
    payer_agent_id: str
    total_bank_wea: int
    stages: tuple[PlanStage, ...]
    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str
    activated_at: datetime
    status: str = "active"
    current_stage_index: int = 0

    def __post_init__(self) -> None:
        for field in (
            "plan_id",
            "plan_revision_id",
            "approval_decision_id",
            "repository_id",
            "issue_id",
            "author_agent_id",
            "payer_agent_id",
            "ruleset_hash",
            "tide_interface_version",
            "executor_manifest_hash",
        ):
            _text(field, getattr(self, field))
        _hash("plan_content_hash", self.plan_content_hash)
        _positive_int("total_bank_wea", self.total_bank_wea)
        if (
            type(self.stages) is not tuple
            or not self.stages
            or any(type(item) is not PlanStage for item in self.stages)
        ):
            raise PlanError("atomic activation: accepted Plan requires stages")
        stages = tuple(
            _rebuild_exact(item, PlanStage, "accepted Plan stage")
            for item in self.stages
        )
        object.__setattr__(self, "stages", stages)
        if sum(item.allocation_wea for item in stages) != self.total_bank_wea:
            raise PlanError("money: accepted Plan stages must equal total bank")
        if self.status != "active" or self.current_stage_index != 0:
            raise PlanError("atomic activation: new Plan must start at stage zero")
        object.__setattr__(
            self, "activated_at", _utc("activated_at", self.activated_at)
        )

    @property
    def stage_allocations(self) -> tuple[int, ...]:
        return tuple(stage.allocation_wea for stage in self.stages)

    def to_data(self) -> dict[str, object]:
        return {
            "activated_at": _timestamp(self.activated_at),
            "approval_decision_id": self.approval_decision_id,
            "author_agent_id": self.author_agent_id,
            "current_stage_index": self.current_stage_index,
            "executor_manifest_hash": self.executor_manifest_hash,
            "issue_id": self.issue_id,
            "payer_agent_id": self.payer_agent_id,
            "plan_content_hash": self.plan_content_hash,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "repository_id": self.repository_id,
            "ruleset_hash": self.ruleset_hash,
            "stages": [stage.to_data() for stage in self.stages],
            "status": self.status,
            "tide_interface_version": self.tide_interface_version,
            "total_bank_wea": self.total_bank_wea,
        }


@dataclass(frozen=True)
class StageContract:
    contract_id: str
    plan_id: str
    plan_revision_id: str
    plan_content_hash: str
    stage_index: int
    stage_key: str
    depth: str
    mode: str
    schedule: StageSchedule
    config: Mapping[str, Any]
    expected_output: str
    allocation_wea: int
    author_agent_id: str
    payer_agent_id: str
    resolved_inputs: tuple[ResolvedWorkInput, ...]
    deadlines: tuple[StageDeadline, ...]
    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str
    activated_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "contract_id",
            "plan_id",
            "plan_revision_id",
            "stage_key",
            "depth",
            "mode",
            "expected_output",
            "author_agent_id",
            "payer_agent_id",
            "ruleset_hash",
            "tide_interface_version",
            "executor_manifest_hash",
        ):
            _text(field, getattr(self, field))
        _hash("plan_content_hash", self.plan_content_hash)
        if self.contract_id != stage_contract_id(self.plan_id, self.stage_key):
            raise PlanError("atomic activation: child Contract ID is not deterministic")
        if type(self.stage_index) is not int or self.stage_index < 0:
            raise PlanError("evidence_boundary: stage index must be non-negative")
        schedule = _rebuild_exact(self.schedule, StageSchedule, "stage schedule")
        schedule.validate_mode(self.mode)
        object.__setattr__(self, "schedule", schedule)
        if type(self.resolved_inputs) is not tuple or any(
            type(item) is not ResolvedWorkInput for item in self.resolved_inputs
        ):
            raise PlanError("evidence_boundary: resolved inputs have invalid types")
        object.__setattr__(
            self,
            "resolved_inputs",
            tuple(
                _rebuild_exact(item, ResolvedWorkInput, "resolved Work input")
                for item in self.resolved_inputs
            ),
        )
        if type(self.deadlines) is not tuple or any(
            type(item) is not StageDeadline for item in self.deadlines
        ):
            raise PlanError("evidence_boundary: stage deadlines have invalid types")
        deadlines = tuple(
            _rebuild_exact(item, StageDeadline, "stage deadline")
            for item in self.deadlines
        )
        if deadlines != initial_stage_deadlines(
            self.contract_id, self.mode, schedule, self.activated_at
        ):
            raise PlanError("evidence_boundary: initial stage deadlines are invalid")
        object.__setattr__(self, "deadlines", deadlines)
        _positive_int("allocation_wea", self.allocation_wea)
        object.__setattr__(self, "config", freeze_json(self.config))
        object.__setattr__(
            self, "activated_at", _utc("activated_at", self.activated_at)
        )

    def to_data(self) -> dict[str, object]:
        return {
            "activated_at": _timestamp(self.activated_at),
            "allocation_wea": self.allocation_wea,
            "author_agent_id": self.author_agent_id,
            "config": thaw_json(self.config),
            "contract_id": self.contract_id,
            "depth": self.depth,
            "deadlines": [item.to_data() for item in self.deadlines],
            "executor_manifest_hash": self.executor_manifest_hash,
            "expected_output": self.expected_output,
            "mode": self.mode,
            "payer_agent_id": self.payer_agent_id,
            "plan_content_hash": self.plan_content_hash,
            "plan_id": self.plan_id,
            "plan_revision_id": self.plan_revision_id,
            "resolved_inputs": [item.to_data() for item in self.resolved_inputs],
            "ruleset_hash": self.ruleset_hash,
            "stage_index": self.stage_index,
            "stage_key": self.stage_key,
            "schedule": self.schedule.to_data(),
            "tide_interface_version": self.tide_interface_version,
        }


@dataclass(frozen=True)
class StageTask:
    task_id: str
    contract_id: str
    plan_id: str
    stage_key: str
    status: str
    activated_at: datetime

    def __post_init__(self) -> None:
        for field in ("task_id", "contract_id", "plan_id", "stage_key"):
            _text(field, getattr(self, field))
        if self.task_id != stage_task_id(self.contract_id):
            raise PlanError("atomic activation: child Task ID is not deterministic")
        if self.status != "active":
            raise PlanError("atomic activation: first child Task must be active")
        object.__setattr__(
            self, "activated_at", _utc("activated_at", self.activated_at)
        )

    def to_data(self) -> dict[str, object]:
        return {
            "activated_at": _timestamp(self.activated_at),
            "contract_id": self.contract_id,
            "plan_id": self.plan_id,
            "stage_key": self.stage_key,
            "status": self.status,
            "task_id": self.task_id,
        }


@dataclass(frozen=True)
class PlanIntakeState:
    balances: tuple[AccountBalance, ...] = ()
    triage_assessments: tuple[TriageAssessment, ...] = ()
    plan_revisions: tuple[ResolutionPlanRevision, ...] = ()
    decisions: tuple[AuthorPlanDecision, ...] = ()
    plans: tuple[AcceptedResolutionPlan, ...] = ()
    escrows: tuple[ProgramEscrow, ...] = ()
    contracts: tuple[StageContract, ...] = ()
    tasks: tuple[StageTask, ...] = ()
    ledger: tuple[LedgerTransition, ...] = ()

    def __post_init__(
        self,
        _remember: Any = _remember_state,  # noqa: RUF033
        _activation_allowed: Any = _is_verified_activation,  # noqa: RUF033
    ) -> None:
        exact = (
            ("balances", self.balances, AccountBalance),
            ("triage_assessments", self.triage_assessments, TriageAssessment),
            ("plan_revisions", self.plan_revisions, ResolutionPlanRevision),
            ("decisions", self.decisions, AuthorPlanDecision),
            ("plans", self.plans, AcceptedResolutionPlan),
            ("escrows", self.escrows, ProgramEscrow),
            ("contracts", self.contracts, StageContract),
            ("tasks", self.tasks, StageTask),
            ("ledger", self.ledger, LedgerTransition),
        )
        for field_name, values, expected in exact:
            if type(values) is not tuple or any(
                type(item) is not expected for item in values
            ):
                raise PlanError("state records must use exact verified types")
            object.__setattr__(
                self,
                field_name,
                tuple(
                    _rebuild_exact(item, expected, f"state {field_name} record")
                    for item in values
                ),
            )
        marker = getattr(self, "_verified_activation_marker", None)
        if (self.ledger or self.plans or self.escrows) and not _activation_allowed(
            marker
        ):
            raise PlanError(
                "evidence_boundary: activated state requires verified transition"
            )
        object.__setattr__(
            self,
            "balances",
            tuple(sorted(self.balances, key=lambda item: item.account_id)),
        )
        object.__setattr__(
            self,
            "triage_assessments",
            tuple(sorted(self.triage_assessments, key=lambda item: item.assessment_id)),
        )
        object.__setattr__(
            self,
            "plan_revisions",
            tuple(
                sorted(
                    self.plan_revisions,
                    key=lambda item: (item.plan_id, item.revision_number),
                )
            ),
        )
        object.__setattr__(
            self,
            "decisions",
            tuple(sorted(self.decisions, key=lambda item: item.decision_id)),
        )
        object.__setattr__(
            self, "plans", tuple(sorted(self.plans, key=lambda item: item.plan_id))
        )
        object.__setattr__(
            self,
            "escrows",
            tuple(sorted(self.escrows, key=lambda item: item.escrow_id)),
        )
        object.__setattr__(
            self,
            "contracts",
            tuple(sorted(self.contracts, key=lambda item: item.contract_id)),
        )
        object.__setattr__(
            self, "tasks", tuple(sorted(self.tasks, key=lambda item: item.task_id))
        )
        object.__setattr__(
            self,
            "ledger",
            tuple(sorted(self.ledger, key=lambda item: item.transition_id)),
        )
        self._validate_unique()
        self._validate_evidence()
        self._validate_activation_groups()
        _remember(self, self.state_hash)

    def _validate_unique(self) -> None:
        collections = (
            (self.balances, "account_id"),
            (self.triage_assessments, "assessment_id"),
            (self.plan_revisions, "revision_id"),
            (self.decisions, "decision_id"),
            (self.plans, "plan_id"),
            (self.escrows, "escrow_id"),
            (self.contracts, "contract_id"),
            (self.tasks, "task_id"),
            (self.ledger, "transition_id"),
        )
        for values, field in collections:
            ids = [getattr(item, field) for item in values]
            if len(ids) != len(set(ids)):
                raise PlanError(f"state {field} values must be unique")
        source_revisions = [item.source_revision_id for item in self.triage_assessments]
        source_revisions.extend(
            item.assignment_source_revision_id for item in self.triage_assessments
        )
        source_revisions.extend(
            item.completion_source_revision_id for item in self.triage_assessments
        )
        source_revisions.extend(item.source_revision_id for item in self.plan_revisions)
        source_revisions.extend(item.source_revision_id for item in self.decisions)
        if len(source_revisions) != len(set(source_revisions)):
            raise PlanError(
                "evidence_boundary: source revision IDs are globally single-use"
            )
        idem = [item.idempotency_key for item in self.decisions]
        idem.extend(item.idempotency_key for item in self.ledger)
        if len(idem) != len(set(idem)):
            raise PlanError(
                "evidence_boundary: idempotency keys are globally single-use"
            )
        for field in ("assignment_id", "completion_id"):
            values = [getattr(item, field) for item in self.triage_assessments]
            if len(values) != len(set(values)):
                raise PlanError(f"evidence_boundary: Triage {field} is single-use")

    def _validate_evidence(self) -> None:
        assessments = {item.assessment_id: item for item in self.triage_assessments}
        revisions = {item.revision_id: item for item in self.plan_revisions}
        decisions_by_revision: dict[str, list[AuthorPlanDecision]] = {}
        for decision in self.decisions:
            decisions_by_revision.setdefault(decision.plan_revision_id, []).append(
                decision
            )
        if any(len(items) != 1 for items in decisions_by_revision.values()):
            raise PlanError("evidence_boundary: Plan revision has multiple decisions")
        by_plan: dict[str, list[ResolutionPlanRevision]] = {}
        for revision in self.plan_revisions:
            assessment = assessments.get(revision.triage_assessment_id)
            if assessment is None:
                raise PlanError("evidence_boundary: Plan assessment is missing")
            if (
                assessment.repository_id != revision.repository_id
                or assessment.issue_id != revision.issue_id
                or assessment.issue_revision_id != revision.issue_revision_id
                or assessment.body_hash != revision.body_hash
                or _source_order(revision)
                <= _triage_completion_source_order(assessment)
            ):
                raise PlanError("evidence_boundary: Plan does not match assessment")
            by_plan.setdefault(revision.plan_id, []).append(revision)
        for plan_revisions in by_plan.values():
            for index, revision in enumerate(plan_revisions, start=1):
                if revision.revision_number != index:
                    raise PlanError(
                        "evidence_boundary: Plan revisions must be contiguous"
                    )
                if (
                    index > 1
                    and revision.parent_revision_id
                    != plan_revisions[index - 2].revision_id
                ):
                    raise PlanError("evidence_boundary: Plan parent chain is invalid")
                if index > 1:
                    parent = plan_revisions[index - 2]
                    if _source_order(revision) <= _source_order(parent):
                        raise PlanError(
                            "evidence_boundary: Plan revision evidence must follow "
                            "parent"
                        )
                    parent_decisions = decisions_by_revision.get(parent.revision_id, [])
                    if any(item.outcome == "decline" for item in parent_decisions):
                        raise PlanError("authority: declined Plan cannot be amended")
                    if revision.proposer_kind == "triage" and not any(
                        item.outcome == "request_revision"
                        and _source_order(item) < _source_order(revision)
                        for item in parent_decisions
                    ):
                        raise PlanError(
                            "authority: new Triage proposal requires an author request"
                        )
        for decision in self.decisions:
            revision = revisions.get(decision.plan_revision_id)
            if (
                revision is None
                or decision.plan_id != revision.plan_id
                or decision.plan_content_hash != revision.content_hash
                or decision.author_agent_id != revision.author_agent_id
                or _source_order(decision) <= _source_order(revision)
            ):
                raise PlanError("evidence_boundary: decision does not match exact Plan")

    def _validate_activation_groups(self) -> None:
        revisions = {item.revision_id: item for item in self.plan_revisions}
        decisions = {item.decision_id: item for item in self.decisions}
        escrows = {item.plan_id: item for item in self.escrows}
        contracts_by_plan: dict[str, list[StageContract]] = {}
        tasks_by_plan: dict[str, list[StageTask]] = {}
        ledger_by_plan: dict[str, list[LedgerTransition]] = {}
        for item in self.contracts:
            contracts_by_plan.setdefault(item.plan_id, []).append(item)
        for item in self.tasks:
            tasks_by_plan.setdefault(item.plan_id, []).append(item)
        for item in self.ledger:
            ledger_by_plan.setdefault(item.basis_id, []).append(item)
        plan_ids = {item.plan_id for item in self.plans}
        if (
            set(escrows) - plan_ids
            or set(contracts_by_plan) - plan_ids
            or set(tasks_by_plan) - plan_ids
            or set(ledger_by_plan) - plan_ids
        ):
            raise PlanError("atomic activation: orphan activation record")
        for plan in self.plans:
            revision = revisions.get(plan.plan_revision_id)
            decision = decisions.get(plan.approval_decision_id)
            escrow = escrows.get(plan.plan_id)
            contracts = contracts_by_plan.get(plan.plan_id, [])
            tasks = tasks_by_plan.get(plan.plan_id, [])
            ledger = ledger_by_plan.get(plan.plan_id, [])
            if (
                revision is None
                or decision is None
                or escrow is None
                or len(contracts) != 1
                or len(tasks) != 1
                or len(ledger) != 1
            ):
                raise PlanError("atomic activation: Plan group must be complete")
            contract = contracts[0]
            task = tasks[0]
            debit = ledger[0]
            first = revision.stages[0]
            latest_revision = max(
                (item for item in self.plan_revisions if item.plan_id == plan.plan_id),
                key=lambda item: item.revision_number,
            )
            expected_runtime = (
                plan.ruleset_hash,
                plan.tide_interface_version,
                plan.executor_manifest_hash,
            )
            if (
                decision.outcome != "approve"
                or decision.plan_id != plan.plan_id
                or decision.plan_revision_id != plan.plan_revision_id
                or decision.plan_content_hash != plan.plan_content_hash
                or decision.author_agent_id != plan.author_agent_id
                or expected_runtime != _verified_runtime()
                or latest_revision.revision_id != plan.plan_revision_id
                or plan.plan_id != revision.plan_id
                or plan.repository_id != revision.repository_id
                or plan.issue_id != revision.issue_id
                or plan.author_agent_id != revision.author_agent_id
                or plan.payer_agent_id != revision.author_agent_id
                or plan.plan_content_hash != revision.content_hash
                or plan.total_bank_wea != revision.total_bank_wea
                or plan.stages != revision.stages
                or escrow.escrow_id != program_escrow_id(plan.plan_id)
                or escrow.payer_agent_id != plan.payer_agent_id
                or escrow.deposited_wea != plan.total_bank_wea
                or escrow.paid_wea != 0
                or escrow.refunded_wea != 0
                or escrow.status != "active"
                or contract.contract_id != stage_contract_id(plan.plan_id, first.key)
                or contract.plan_revision_id != plan.plan_revision_id
                or contract.plan_content_hash != plan.plan_content_hash
                or contract.stage_key != first.key
                or contract.depth != first.depth
                or contract.mode != first.mode
                or thaw_json(contract.config) != thaw_json(first.config)
                or contract.allocation_wea != first.allocation_wea
                or contract.expected_output != first.expected_output
                or contract.author_agent_id != plan.author_agent_id
                or contract.payer_agent_id != plan.payer_agent_id
                or task.task_id != stage_task_id(contract.contract_id)
                or task.contract_id != contract.contract_id
                or task.plan_id != plan.plan_id
                or task.stage_key != first.key
                or debit.transition_id != f"plan-bank:{plan.plan_id}"
                or debit.kind != "plan-bank"
                or debit.debit_account_id != plan.payer_agent_id
                or debit.credit_account_id != escrow.escrow_id
                or debit.amount_wea != plan.total_bank_wea
                or debit.idempotency_key != f"plan-activation:{plan.plan_revision_id}"
                or not (
                    decision.effective_at
                    <= plan.activated_at
                    == contract.activated_at
                    == task.activated_at
                    == debit.effective_at
                )
                or (
                    contract.ruleset_hash,
                    contract.tide_interface_version,
                    contract.executor_manifest_hash,
                )
                != expected_runtime
            ):
                raise PlanError("atomic activation: records do not match exact Plan")
        self._validate_prior_state_chain()

    def _validate_prior_state_chain(self) -> None:
        data: dict[str, Any] = _financial_state_data(self)
        ordered = sorted(
            self.ledger,
            key=lambda item: (item.effective_at, item.transition_id),
            reverse=True,
        )
        for debit in ordered:
            plan_id = debit.basis_id
            data["plans"] = [
                item for item in data["plans"] if item["plan_id"] != plan_id
            ]
            data["escrows"] = [
                item for item in data["escrows"] if item["plan_id"] != plan_id
            ]
            data["contracts"] = [
                item for item in data["contracts"] if item["plan_id"] != plan_id
            ]
            data["tasks"] = [
                item for item in data["tasks"] if item["plan_id"] != plan_id
            ]
            data["ledger"] = [
                item
                for item in data["ledger"]
                if item["transition_id"] != debit.transition_id
            ]
            restored = False
            for balance in data["balances"]:
                if balance["account_id"] == debit.debit_account_id:
                    balance["amount_wea"] += debit.amount_wea
                    restored = True
            if not restored:
                raise PlanError("atomic activation: prior balance is missing")
            if canonical_hash(data) != debit.prior_financial_hash:
                raise PlanError(
                    "atomic activation: predecessor financial state does not match"
                )

    def _assert_unchanged(self, _read: Any = _read_state_seal) -> None:
        if _read(self) != self.state_hash:
            raise PlanError("state changed after validation")

    def balance(self, account_id: str) -> int:
        account_id = _text("account_id", account_id)
        matches = [
            item.amount_wea for item in self.balances if item.account_id == account_id
        ]
        if len(matches) > 1:
            raise PlanError("balance account must resolve exactly once")
        return matches[0] if matches else 0

    def feedback_chain(self, issue_id: str) -> tuple[str, ...]:
        assessments = [
            item for item in self.triage_assessments if item.issue_id == issue_id
        ]
        assessment_ids = {item.assessment_id for item in assessments}
        revisions = [
            item
            for item in self.plan_revisions
            if item.triage_assessment_id in assessment_ids
        ]
        revision_ids = {item.revision_id for item in revisions}
        decisions = [
            item for item in self.decisions if item.plan_revision_id in revision_ids
        ]
        evidence = (
            *(
                (item.completion_effective_at, 0, item.assessment_id)
                for item in assessments
            ),
            *((item.effective_at, 1, item.revision_id) for item in revisions),
            *((item.effective_at, 2, item.decision_id) for item in decisions),
        )
        return tuple(item[2] for item in sorted(evidence))

    def to_data(self) -> dict[str, object]:
        return {
            "balances": [item.to_data() for item in self.balances],
            "contracts": [item.to_data() for item in self.contracts],
            "decisions": [item.to_data() for item in self.decisions],
            "escrows": [item.to_data() for item in self.escrows],
            "ledger": [item.to_data() for item in self.ledger],
            "plan_revisions": [item.to_data() for item in self.plan_revisions],
            "plans": [item.to_data() for item in self.plans],
            "tasks": [item.to_data() for item in self.tasks],
            "triage_assessments": [item.to_data() for item in self.triage_assessments],
        }

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_data())


def _financial_state_data(state: PlanIntakeState) -> dict[str, Any]:
    return {
        "balances": [item.to_data() for item in state.balances],
        "contracts": [item.to_data() for item in state.contracts],
        "escrows": [item.to_data() for item in state.escrows],
        "ledger": [item.to_data() for item in state.ledger],
        "plans": [item.to_data() for item in state.plans],
        "tasks": [item.to_data() for item in state.tasks],
    }


def _replace_intake_state(
    state: PlanIntakeState,
    _verified_replace: Any = _verified_activation_replace,
    **changes: object,
) -> PlanIntakeState:
    requires_verified_transition = bool(
        state.ledger
        or state.plans
        or state.escrows
        or changes.get("ledger")
        or changes.get("plans")
        or changes.get("escrows")
    )
    if requires_verified_transition:
        return _verified_replace(state, changes)
    return replace(state, **changes)


del _is_verified_activation, _verified_activation_replace


@dataclass(frozen=True)
class PlanActivation:
    state: PlanIntakeState
    created: bool
    draft: DraftIssue
    plan: AcceptedResolutionPlan
    escrow: ProgramEscrow
    contract: StageContract
    task: StageTask
    debit: LedgerTransition


def _assert_registry(registry: IdentityRegistry) -> None:
    if type(registry) is not IdentityRegistry:
        raise PlanError("identity: registry must use exact verified type")
    try:
        registry._assert_unchanged()
    except IdentityError as exc:
        raise PlanError("identity: registry changed after validation") from exc


def _author_authority(
    draft: DraftIssue, registry: IdentityRegistry
) -> IdentityAuthority:
    try:
        authority = authorize_issue_author(
            author_agent_id=draft.author_agent_id,
            github_account_id=draft.creator_github_account_id,
            effective_at=draft.effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise PlanError("identity: Draft author is not authorized") from exc
    if (
        authority.account_binding_id != draft.author_binding_id
        or authority.account_binding_version != draft.author_binding_version
    ):
        raise PlanError("identity: Draft author binding snapshot does not match")
    return authority


def _validate_draft(draft: DraftIssue, registry: IdentityRegistry) -> IdentityAuthority:
    if type(draft) is not DraftIssue:
        raise PlanError("evidence_boundary: Draft must use exact verified type")
    _assert_registry(registry)
    return _author_authority(draft, registry)


def _authorize_assessment(
    assessment: TriageAssessment, registry: IdentityRegistry
) -> None:
    try:
        reviewer_at_assignment = authorize_agent(
            github_account_id=assessment.reviewer_github_account_id,
            agent_id=assessment.reviewer_agent_id,
            effective_at=assessment.assignment_effective_at,
            registry=registry,
        )
        reviewer_at_assessment = authorize_agent(
            github_account_id=assessment.reviewer_github_account_id,
            agent_id=assessment.reviewer_agent_id,
            effective_at=assessment.effective_at,
            registry=registry,
        )
        agent0_at_assignment = resolve_binding(
            tuple(item for item in registry.bindings if item.actor_kind == "agent0"),
            github_account_id=assessment.agent0_github_account_id,
            subject_id="agent0@system",
            effective_at=assessment.assignment_effective_at,
        )
        agent0_at_completion = resolve_binding(
            tuple(item for item in registry.bindings if item.actor_kind == "agent0"),
            github_account_id=assessment.agent0_github_account_id,
            subject_id="agent0@system",
            effective_at=assessment.completion_effective_at,
        )
    except IdentityError as exc:
        raise PlanError("authority: Triage evidence is not authorized") from exc
    if (
        reviewer_at_assignment.account_binding_id != assessment.reviewer_binding_id
        or reviewer_at_assignment.account_binding_version
        != assessment.reviewer_binding_version
        or reviewer_at_assessment.account_binding_id != assessment.reviewer_binding_id
        or reviewer_at_assessment.account_binding_version
        != assessment.reviewer_binding_version
        or agent0_at_assignment.binding_id != assessment.agent0_binding_id
        or agent0_at_assignment.version != assessment.agent0_binding_version
        or agent0_at_completion.binding_id != assessment.agent0_binding_id
        or agent0_at_completion.version != assessment.agent0_binding_version
    ):
        raise PlanError("authority: Triage binding snapshot does not match registry")


def _authorize_plan_revision(
    revision: ResolutionPlanRevision,
    assessment: TriageAssessment,
    draft: DraftIssue,
    registry: IdentityRegistry,
) -> None:
    if revision.proposer_kind == "triage":
        try:
            authority = authorize_agent(
                github_account_id=revision.proposer_github_account_id,
                agent_id=revision.proposer_agent_id,
                effective_at=revision.effective_at,
                registry=registry,
            )
        except IdentityError as exc:
            raise PlanError("authority: Triage proposer is not authorized") from exc
        if (
            revision.proposer_agent_id != assessment.reviewer_agent_id
            or revision.proposer_github_account_id
            != assessment.reviewer_github_account_id
            or revision.proposer_binding_id != assessment.reviewer_binding_id
            or revision.proposer_binding_version != assessment.reviewer_binding_version
            or authority.account_binding_id != revision.proposer_binding_id
            or authority.account_binding_version != revision.proposer_binding_version
        ):
            raise PlanError(
                "authority: Triage proposal does not match assessment reviewer"
            )
    else:
        try:
            authority = authorize_agent(
                github_account_id=revision.proposer_github_account_id,
                agent_id=revision.proposer_agent_id,
                effective_at=revision.effective_at,
                registry=registry,
            )
        except IdentityError as exc:
            raise PlanError("authority: author amendment is not authorized") from exc
        if (
            authority.agent_id != draft.author_agent_id
            or authority.account_binding_id != revision.proposer_binding_id
            or authority.account_binding_version != revision.proposer_binding_version
        ):
            raise PlanError("authority: author amendment binding does not match")


def _authorize_decision(
    decision: AuthorPlanDecision,
    revision: ResolutionPlanRevision,
    registry: IdentityRegistry,
) -> None:
    try:
        authority = authorize_agent(
            github_account_id=decision.author_github_account_id,
            agent_id=decision.author_agent_id,
            effective_at=decision.effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise PlanError("authority: author decision is not authorized") from exc
    if (
        authority.agent_id != revision.author_agent_id
        or authority.account_binding_id != decision.author_binding_id
        or authority.account_binding_version != decision.author_binding_version
    ):
        raise PlanError("authority: author decision binding does not match")


def _require_draft_event(draft: DraftIssue, github_state: ProtocolState) -> None:
    _require_github_event(
        github_state,
        repository_id=draft.repository_id,
        object_kind="issue",
        object_id=draft.issue_id,
        revision_id=draft.issue_revision_id,
        actor_account_id=draft.creator_github_account_id,
        body=draft.body,
        body_hash=draft.body_hash,
        effective_at=draft.effective_at,
        must_be_latest=True,
        expected_payload={
            "author_agent_id": draft.author_agent_id,
            "author_binding_id": draft.author_binding_id,
            "author_binding_version": draft.author_binding_version,
            "issue_number": draft.issue_number,
            "kind": "draft_issue",
            "max_bank_wea": draft.max_bank_wea,
        },
    )


def _require_assessment_events(
    assessment: TriageAssessment, github_state: ProtocolState
) -> None:
    evidence = (
        (
            assessment.assignment_source_comment_id,
            assessment.assignment_source_revision_id,
            assessment.agent0_github_account_id,
            assessment.assignment_snapshot,
            assessment.assignment_snapshot_hash,
            assessment.assignment_effective_at,
        ),
        (
            assessment.source_comment_id,
            assessment.source_revision_id,
            assessment.reviewer_github_account_id,
            assessment.snapshot,
            assessment.snapshot_hash,
            assessment.effective_at,
        ),
        (
            assessment.completion_source_comment_id,
            assessment.completion_source_revision_id,
            assessment.agent0_github_account_id,
            assessment.completion_snapshot,
            assessment.completion_snapshot_hash,
            assessment.completion_effective_at,
        ),
    )
    for object_id, revision_id, actor, body, body_hash, effective_at in evidence:
        _require_github_event(
            github_state,
            repository_id=assessment.repository_id,
            object_kind="issue_comment",
            object_id=object_id,
            revision_id=revision_id,
            actor_account_id=actor,
            body=body,
            body_hash=body_hash,
            effective_at=effective_at,
            must_be_latest=True,
        )


def _require_plan_event(
    revision: ResolutionPlanRevision, github_state: ProtocolState
) -> None:
    _require_github_event(
        github_state,
        repository_id=revision.repository_id,
        object_kind="issue_comment",
        object_id=revision.source_comment_id,
        revision_id=revision.source_revision_id,
        actor_account_id=revision.proposer_github_account_id,
        body=revision.snapshot,
        body_hash=revision.snapshot_hash,
        effective_at=revision.effective_at,
        must_be_latest=True,
    )


def _require_decision_event(
    revision: ResolutionPlanRevision,
    decision: AuthorPlanDecision,
    github_state: ProtocolState,
) -> None:
    _require_github_event(
        github_state,
        repository_id=revision.repository_id,
        object_kind="issue_comment",
        object_id=decision.source_comment_id,
        revision_id=decision.source_revision_id,
        actor_account_id=decision.author_github_account_id,
        body=decision.snapshot,
        body_hash=decision.snapshot_hash,
        effective_at=decision.effective_at,
        must_be_latest=True,
    )


def record_triage_assessment(
    state: PlanIntakeState,
    draft: DraftIssue,
    assessment: TriageAssessment,
    *,
    registry: IdentityRegistry,
    github_state: ProtocolState,
    _verified_runtime_reference: Any,
) -> PlanIntakeState:
    _assert_verified_call_runtime(_verified_runtime_reference)
    if type(state) is not PlanIntakeState or type(assessment) is not TriageAssessment:
        raise PlanError("evidence_boundary: exact intake records are required")
    state._assert_unchanged()
    draft = _rebuild_exact(draft, DraftIssue, "Draft")
    assessment = _rebuild_exact(assessment, TriageAssessment, "Triage assessment")
    github_state = _rebuild_github_state(github_state)
    _validate_draft(draft, registry)
    _authorize_assessment(assessment, registry)
    if (
        assessment.repository_id != draft.repository_id
        or assessment.issue_id != draft.issue_id
        or assessment.issue_revision_id != draft.issue_revision_id
        or assessment.body_hash != draft.body_hash
        or assessment.reviewer_agent_id == draft.author_agent_id
        or _triage_assignment_source_order(assessment) <= _draft_source_order(draft)
    ):
        raise PlanError("evidence_boundary: assessment does not match exact Draft")
    _require_draft_event(draft, github_state)
    _require_assessment_events(assessment, github_state)
    existing = next(
        (
            item
            for item in state.triage_assessments
            if item.assessment_id == assessment.assessment_id
        ),
        None,
    )
    if existing is not None:
        if existing == assessment:
            return state
        raise PlanError("evidence_boundary: assessment ID has conflicting content")
    return _replace_intake_state(
        state, triage_assessments=(*state.triage_assessments, assessment)
    )


def record_plan_revision(
    state: PlanIntakeState,
    draft: DraftIssue,
    revision: ResolutionPlanRevision,
    *,
    registry: IdentityRegistry,
    github_state: ProtocolState,
    _verified_runtime_reference: Any,
) -> PlanIntakeState:
    _assert_verified_call_runtime(_verified_runtime_reference)
    if (
        type(state) is not PlanIntakeState
        or type(revision) is not ResolutionPlanRevision
    ):
        raise PlanError("evidence_boundary: exact Plan records are required")
    state._assert_unchanged()
    draft = _rebuild_exact(draft, DraftIssue, "Draft")
    revision = _rebuild_exact(revision, ResolutionPlanRevision, "Plan revision")
    github_state = _rebuild_github_state(github_state)
    _validate_draft(draft, registry)
    assessment = next(
        (
            item
            for item in state.triage_assessments
            if item.assessment_id == revision.triage_assessment_id
        ),
        None,
    )
    if assessment is None:
        raise PlanError("evidence_boundary: completed Triage assessment is missing")
    _authorize_assessment(assessment, registry)
    _authorize_plan_revision(revision, assessment, draft, registry)
    if (
        revision.repository_id != draft.repository_id
        or revision.issue_id != draft.issue_id
        or revision.issue_revision_id != draft.issue_revision_id
        or revision.body_hash != draft.body_hash
        or revision.author_agent_id != draft.author_agent_id
        or revision.total_bank_wea > draft.max_bank_wea
        or _source_order(revision) <= _triage_completion_source_order(assessment)
    ):
        raise PlanError(
            "evidence_boundary: Plan does not match Draft/Triage or max bank"
        )
    _require_draft_event(draft, github_state)
    _require_assessment_events(assessment, github_state)
    _require_plan_event(revision, github_state)
    existing = next(
        (
            item
            for item in state.plan_revisions
            if item.revision_id == revision.revision_id
        ),
        None,
    )
    if existing is not None:
        if existing == revision:
            return state
        raise PlanError("evidence_boundary: Plan revision ID has conflicting content")
    if any(item.plan_id == revision.plan_id for item in state.plans):
        raise PlanError("authority: active Plan revisions are immutable")
    current = [
        item for item in state.plan_revisions if item.plan_id == revision.plan_id
    ]
    if current:
        latest = current[-1]
        if (
            revision.revision_number != latest.revision_number + 1
            or revision.parent_revision_id != latest.revision_id
        ):
            raise PlanError("evidence_boundary: Plan revision must append to latest")
        if _source_order(revision) <= _source_order(latest):
            raise PlanError(
                "evidence_boundary: Plan revision evidence must follow parent"
            )
        if any(
            decision.plan_revision_id == latest.revision_id
            and decision.outcome == "decline"
            for decision in state.decisions
        ):
            raise PlanError("authority: declined Plan cannot be amended")
        if revision.proposer_kind == "triage" and not any(
            decision.plan_revision_id == latest.revision_id
            and decision.outcome == "request_revision"
            and _source_order(decision) < _source_order(revision)
            for decision in state.decisions
        ):
            raise PlanError(
                "authority: another Triage proposal requires an author request"
            )
    elif revision.revision_number != 1:
        raise PlanError("evidence_boundary: first recorded Plan must be revision one")
    return _replace_intake_state(
        state, plan_revisions=(*state.plan_revisions, revision)
    )


def record_author_plan_decision(
    state: PlanIntakeState,
    draft: DraftIssue,
    decision: AuthorPlanDecision,
    *,
    registry: IdentityRegistry,
    github_state: ProtocolState,
    _verified_runtime_reference: Any,
) -> PlanIntakeState:
    _assert_verified_call_runtime(_verified_runtime_reference)
    if type(state) is not PlanIntakeState or type(decision) is not AuthorPlanDecision:
        raise PlanError("evidence_boundary: exact decision record is required")
    state._assert_unchanged()
    draft = _rebuild_exact(draft, DraftIssue, "Draft")
    decision = _rebuild_exact(decision, AuthorPlanDecision, "author decision")
    github_state = _rebuild_github_state(github_state)
    _validate_draft(draft, registry)
    _assert_registry(registry)
    revision = next(
        (
            item
            for item in state.plan_revisions
            if item.revision_id == decision.plan_revision_id
        ),
        None,
    )
    if revision is None:
        raise PlanError("evidence_boundary: decision Plan revision is missing")
    latest = [
        item for item in state.plan_revisions if item.plan_id == revision.plan_id
    ][-1]
    if latest.revision_id != revision.revision_id:
        raise PlanError(
            "evidence_boundary: author decision must target latest Plan revision"
        )
    if (
        decision.plan_id != revision.plan_id
        or decision.plan_content_hash != revision.content_hash
    ):
        raise PlanError(
            "evidence_boundary: decision content_hash does not match exact Plan"
        )
    if _source_order(decision) <= _source_order(revision):
        raise PlanError(
            "evidence_boundary: author decision evidence must follow Plan revision"
        )
    _authorize_decision(decision, revision, registry)
    assessment = next(
        item
        for item in state.triage_assessments
        if item.assessment_id == revision.triage_assessment_id
    )
    _authorize_assessment(assessment, registry)
    _authorize_plan_revision(revision, assessment, draft, registry)
    _require_draft_event(draft, github_state)
    _require_assessment_events(assessment, github_state)
    _require_plan_event(revision, github_state)
    _require_decision_event(revision, decision, github_state)
    existing = next(
        (item for item in state.decisions if item.decision_id == decision.decision_id),
        None,
    )
    if existing is not None:
        if existing == decision:
            return state
        raise PlanError("evidence_boundary: decision ID has conflicting content")
    if any(item.plan_revision_id == revision.revision_id for item in state.decisions):
        raise PlanError("authority: Plan revision already has an author decision")
    return _replace_intake_state(state, decisions=(*state.decisions, decision))


def _reauthorize_activation_chain(
    state: PlanIntakeState,
    draft: DraftIssue,
    revision: ResolutionPlanRevision,
    decision: AuthorPlanDecision,
    registry: IdentityRegistry,
    github_state: ProtocolState,
) -> None:
    _validate_draft(draft, registry)
    assessment = next(
        item
        for item in state.triage_assessments
        if item.assessment_id == revision.triage_assessment_id
    )
    if (
        revision.repository_id != draft.repository_id
        or revision.issue_id != draft.issue_id
        or revision.issue_revision_id != draft.issue_revision_id
        or revision.body_hash != draft.body_hash
        or revision.author_agent_id != draft.author_agent_id
        or revision.total_bank_wea > draft.max_bank_wea
        or assessment.repository_id != draft.repository_id
        or assessment.issue_id != draft.issue_id
        or assessment.issue_revision_id != draft.issue_revision_id
        or assessment.body_hash != draft.body_hash
        or assessment.reviewer_agent_id == draft.author_agent_id
        or _triage_assignment_source_order(assessment) <= _draft_source_order(draft)
        or _source_order(revision) <= _triage_completion_source_order(assessment)
    ):
        raise PlanError("evidence_boundary: activation Draft does not match exact Plan")
    _authorize_assessment(assessment, registry)
    _require_draft_event(draft, github_state)
    _require_assessment_events(assessment, github_state)
    for item in state.plan_revisions:
        if (
            item.plan_id == revision.plan_id
            and item.revision_number <= revision.revision_number
        ):
            _authorize_plan_revision(item, assessment, draft, registry)
            _require_plan_event(item, github_state)
    _authorize_decision(decision, revision, registry)
    _require_decision_event(revision, decision, github_state)


def _updated_balances(
    balances: tuple[AccountBalance, ...], account_id: str, amount_wea: int
) -> tuple[AccountBalance, ...]:
    result: list[AccountBalance] = []
    found = False
    for item in balances:
        if item.account_id == account_id:
            found = True
            if item.amount_wea < amount_wea:
                raise PlanError("money: author balance is insufficient")
            result.append(AccountBalance(item.account_id, item.amount_wea - amount_wea))
        else:
            result.append(item)
    if not found:
        raise PlanError("money: author balance is insufficient")
    return tuple(result)


def _activation_from_state(
    state: PlanIntakeState,
    plan: AcceptedResolutionPlan,
    draft: DraftIssue,
    *,
    created: bool,
) -> PlanActivation:
    escrow = next(item for item in state.escrows if item.plan_id == plan.plan_id)
    contract = next(item for item in state.contracts if item.plan_id == plan.plan_id)
    task = next(item for item in state.tasks if item.plan_id == plan.plan_id)
    debit = next(item for item in state.ledger if item.basis_id == plan.plan_id)
    return PlanActivation(state, created, draft, plan, escrow, contract, task, debit)


def activate_resolution_plan(
    state: PlanIntakeState,
    draft: DraftIssue,
    *,
    plan_revision_id: str,
    decision_id: str,
    payer_agent_id: str,
    payer_github_account_id: str,
    effective_at: datetime,
    registry: IdentityRegistry,
    github_state: ProtocolState,
    _verified_runtime_reference: Any,
) -> PlanActivation:
    if type(state) is not PlanIntakeState:
        raise PlanError("evidence_boundary: state must use exact verified type")
    state._assert_unchanged()
    draft = _rebuild_exact(draft, DraftIssue, "Draft")
    github_state = _rebuild_github_state(github_state)
    _validate_draft(draft, registry)
    plan_revision_id = _text("plan_revision_id", plan_revision_id)
    decision_id = _text("decision_id", decision_id)
    payer_agent_id = _text("payer_agent_id", payer_agent_id)
    payer_github_account_id = _text("payer_github_account_id", payer_github_account_id)
    effective_at = _utc("effective_at", effective_at)
    runtime_triple = _snapshot_runtime(_verified_runtime_reference)
    if runtime_triple != _verified_runtime():
        raise PlanError("runtime: triple does not belong to executor 0.9.0")
    revision = next(
        (item for item in state.plan_revisions if item.revision_id == plan_revision_id),
        None,
    )
    decision = next(
        (item for item in state.decisions if item.decision_id == decision_id), None
    )
    if revision is None or decision is None:
        raise PlanError("evidence_boundary: activation evidence is missing")
    if (
        decision.plan_revision_id != revision.revision_id
        or decision.outcome != "approve"
        or effective_at < decision.effective_at
    ):
        raise PlanError("authority: exact author approval is required")
    latest = [
        item for item in state.plan_revisions if item.plan_id == revision.plan_id
    ][-1]
    if latest.revision_id != revision.revision_id:
        raise PlanError("evidence_boundary: activation must use latest Plan revision")
    _reauthorize_activation_chain(
        state, draft, revision, decision, registry, github_state
    )
    if (
        payer_agent_id != draft.author_agent_id
        or payer_github_account_id != draft.creator_github_account_id
        or payer_github_account_id != decision.author_github_account_id
    ):
        raise PlanError("authority: payer must be the exact Issue author")
    try:
        payer = authorize_agent(
            github_account_id=payer_github_account_id,
            agent_id=payer_agent_id,
            effective_at=effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise PlanError("authority: payer is not authorized") from exc
    if payer.agent_id != decision.author_agent_id:
        raise PlanError("authority: payer must equal approving author")
    existing = next(
        (item for item in state.plans if item.plan_id == revision.plan_id), None
    )
    if existing is not None:
        if (
            existing.plan_revision_id != revision.revision_id
            or existing.approval_decision_id != decision.decision_id
            or existing.activated_at != effective_at
        ):
            raise PlanError("evidence_boundary: Plan is already activated differently")
        return _activation_from_state(state, existing, draft, created=False)
    transition_id = f"plan-bank:{revision.plan_id}"
    if state.ledger and (effective_at, transition_id) <= max(
        (item.effective_at, item.transition_id) for item in state.ledger
    ):
        raise PlanError(
            "evidence_boundary: activation must append in deterministic order"
        )
    first = revision.stages[0]
    if first.inputs:
        raise PlanError("evidence_boundary: first stage cannot have future inputs")
    ruleset_hash, interface_version, manifest_hash = runtime_triple
    accepted = AcceptedResolutionPlan(
        plan_id=revision.plan_id,
        plan_revision_id=revision.revision_id,
        plan_content_hash=revision.content_hash,
        approval_decision_id=decision.decision_id,
        repository_id=revision.repository_id,
        issue_id=revision.issue_id,
        author_agent_id=revision.author_agent_id,
        payer_agent_id=payer_agent_id,
        total_bank_wea=revision.total_bank_wea,
        stages=revision.stages,
        ruleset_hash=ruleset_hash,
        tide_interface_version=interface_version,
        executor_manifest_hash=manifest_hash,
        activated_at=effective_at,
    )
    escrow = ProgramEscrow(
        escrow_id=program_escrow_id(revision.plan_id),
        plan_id=revision.plan_id,
        payer_agent_id=payer_agent_id,
        deposited_wea=revision.total_bank_wea,
    )
    contract = StageContract(
        contract_id=stage_contract_id(revision.plan_id, first.key),
        plan_id=revision.plan_id,
        plan_revision_id=revision.revision_id,
        plan_content_hash=revision.content_hash,
        stage_index=0,
        stage_key=first.key,
        depth=first.depth,
        mode=first.mode,
        schedule=first.schedule,
        config=first.config,
        expected_output=first.expected_output,
        allocation_wea=first.allocation_wea,
        author_agent_id=revision.author_agent_id,
        payer_agent_id=payer_agent_id,
        resolved_inputs=(),
        deadlines=initial_stage_deadlines(
            stage_contract_id(revision.plan_id, first.key),
            first.mode,
            first.schedule,
            effective_at,
        ),
        ruleset_hash=ruleset_hash,
        tide_interface_version=interface_version,
        executor_manifest_hash=manifest_hash,
        activated_at=effective_at,
    )
    task = StageTask(
        task_id=stage_task_id(contract.contract_id),
        contract_id=contract.contract_id,
        plan_id=revision.plan_id,
        stage_key=first.key,
        status="active",
        activated_at=effective_at,
    )
    debit = LedgerTransition(
        transition_id=transition_id,
        kind="plan-bank",
        debit_account_id=payer_agent_id,
        credit_account_id=escrow.escrow_id,
        amount_wea=revision.total_bank_wea,
        basis_id=revision.plan_id,
        idempotency_key=f"plan-activation:{revision.revision_id}",
        prior_financial_hash=canonical_hash(_financial_state_data(state)),
        effective_at=effective_at,
    )
    balances = _updated_balances(
        state.balances, payer_agent_id, revision.total_bank_wea
    )
    activated = _replace_intake_state(
        state,
        balances=balances,
        plans=(*state.plans, accepted),
        escrows=(*state.escrows, escrow),
        contracts=(*state.contracts, contract),
        tasks=(*state.tasks, task),
        ledger=(*state.ledger, debit),
    )
    return _activation_from_state(activated, accepted, draft, created=True)


__all__ = [
    "AcceptedResolutionPlan",
    "AccountBalance",
    "AuthorPlanDecision",
    "DraftIssue",
    "GitHubEvent",
    "GitHubEventBatch",
    "GitHubReadBoundary",
    "LedgerTransition",
    "PlanActivation",
    "PlanError",
    "PlanIntakeState",
    "PlanStage",
    "ProgramEscrow",
    "ProtocolState",
    "ResolutionPlanRevision",
    "ResolvedWorkInput",
    "SelectedWorkInput",
    "StageContract",
    "StageDeadline",
    "StageSchedule",
    "StageTask",
    "TriageAssessment",
    "accept_github_evidence_batch",
    "activate_resolution_plan",
    "author_plan_decision_id",
    "author_plan_decision_key",
    "initial_github_evidence_state",
    "initial_stage_deadlines",
    "program_escrow_id",
    "record_author_plan_decision",
    "record_plan_revision",
    "record_triage_assessment",
    "resolution_plan_id",
    "resolution_plan_revision_id",
    "stage_contract_id",
    "stage_task_id",
    "triage_assessment_id",
    "triage_assignment_id",
    "triage_completion_id",
]
