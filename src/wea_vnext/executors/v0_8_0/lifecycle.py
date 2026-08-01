"""Append-only Resolution Plan lifecycle for ruleset 0.8."""

from __future__ import annotations

import hashlib
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_dumps, canonical_hash, freeze_json, thaw_json
from .deadlines import apply_pause_offset, duel_windows, materialize_deadline
from .identity import (
    IdentityError,
    IdentityRegistry,
    authorize_agent,
    resolve_binding,
)
from .intake import (
    AccountBalance,
    PlanActivation,
    PlanError,
    PlanIntakeState,
    PlanStage,
    ProgramEscrow,
    ProtocolState,
    ResolvedWorkInput,
    SelectedWorkInput,
    StageContract,
    StageDeadline,
    StageSchedule,
    _rebuild_github_state,
    _require_github_event,
    _snapshot_runtime,
    _verified_runtime,
    initial_stage_deadlines,
    stage_contract_id,
)
from .rules import load_ruleset

_EVENT_KINDS = {
    "author_continue",
    "author_stop",
    "birdie",
    "body_pause",
    "body_resume",
    "downstream_blocker",
    "duel_decision",
    "duel_join",
    "duel_move",
    "frontier_close",
    "mode_expiry",
    "ranked_order",
    "risk_pause",
    "risk_warning",
    "role_assignment",
    "role_resolution",
    "role_result",
    "suffix_replan",
    "work_acceptance",
    "work_revision",
}
_HASH_LENGTH = 64
_BOUND_RUNTIME: tuple[str, str, str] | None = None
_WEA_VERIFIER_CAPABILITY: object | None = globals().get("_WEA_VERIFIER_CAPABILITY")


def _bind_verified_runtime(runtime: Any, verifier_capability: object) -> None:
    global _BOUND_RUNTIME
    if (
        _WEA_VERIFIER_CAPABILITY is None
        or verifier_capability is not _WEA_VERIFIER_CAPABILITY
    ):
        raise PlanError("runtime: lifecycle binding requires the manifest verifier")
    candidate = _snapshot_runtime(runtime)
    if candidate != _verified_runtime():
        raise PlanError("runtime: lifecycle does not match executor 0.8.0")
    if _BOUND_RUNTIME is not None and _BOUND_RUNTIME != candidate:
        raise PlanError("runtime: lifecycle is already bound differently")
    _BOUND_RUNTIME = candidate


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


def _hash(field: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != _HASH_LENGTH
        or any(item not in "0123456789abcdef" for item in value)
    ):
        raise PlanError(f"{field}: must be a lowercase SHA-256 digest")
    return value


def _utc(field: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
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


def _rebuild(value: Any, expected: type[Any], name: str) -> Any:
    if type(value) is not expected:
        raise PlanError(f"evidence_boundary: {name} must use exact verified type")
    try:
        return expected(
            **{
                field.name: object.__getattribute__(value, field.name)
                for field in fields(expected)
                if field.init
            }
        )
    except PlanError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise PlanError(f"evidence_boundary: {name} is malformed") from exc


def work_id(contract_id: str, agent_id: str) -> str:
    return f"{_text('contract_id', contract_id)}:work:{_text('agent_id', agent_id)}"


def work_revision_id(work: str, revision_number: int) -> str:
    work = _text("work_id", work)
    revision_number = _positive_int("revision", revision_number)
    return f"{work}:revision:{revision_number}"


def lifecycle_event_id(plan_id: str, kind: str, source_revision_id: str) -> str:
    return (
        f"{_text('plan_id', plan_id)}:event:{_text('kind', kind)}:"
        f"{_text('source_revision_id', source_revision_id)}"
    )


@dataclass(frozen=True)
class LifecycleEvent:
    event_id: str
    plan_id: str
    kind: str
    actor_kind: str
    actor_id: str
    actor_account_id: str
    source_id: str
    source_revision_id: str
    source_snapshot: str
    source_snapshot_hash: str
    payload: Mapping[str, Any]
    effective_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        for field in (
            "event_id",
            "plan_id",
            "actor_kind",
            "actor_id",
            "actor_account_id",
            "source_id",
            "source_revision_id",
            "source_snapshot",
            "idempotency_key",
        ):
            _text(field, getattr(self, field))
        if self.kind not in _EVENT_KINDS:
            raise PlanError("declaration: lifecycle event kind is not supported")
        if self.event_id != lifecycle_event_id(
            self.plan_id, self.kind, self.source_revision_id
        ):
            raise PlanError(
                "evidence_boundary: lifecycle event ID is not deterministic"
            )
        effective_at = _utc("effective_at", self.effective_at)
        object.__setattr__(self, "effective_at", effective_at)
        try:
            payload = freeze_json(self.payload)
        except (TypeError, ValueError) as exc:
            raise PlanError(
                "declaration: lifecycle payload is not canonical JSON"
            ) from exc
        object.__setattr__(self, "payload", payload)
        expected = canonical_dumps(
            {
                "actor_account_id": self.actor_account_id,
                "actor_id": self.actor_id,
                "actor_kind": self.actor_kind,
                "effective_at": _timestamp(effective_at),
                "event_id": self.event_id,
                "kind": self.kind,
                "payload": thaw_json(payload),
                "plan_id": self.plan_id,
                "source_id": self.source_id,
                "source_revision_id": self.source_revision_id,
            }
        ).decode("utf-8")
        if self.source_snapshot != expected:
            raise PlanError("declaration: lifecycle snapshot does not match event")
        actual_hash = hashlib.sha256(self.source_snapshot.encode("utf-8")).hexdigest()
        if _hash("source_snapshot_hash", self.source_snapshot_hash) != actual_hash:
            raise PlanError("source_snapshot_hash: does not match exact snapshot")

    @property
    def order_key(self) -> tuple[datetime, str, str, str]:
        return (
            self.effective_at,
            self.source_id,
            self.source_revision_id,
            self.event_id,
        )

    def to_data(self) -> dict[str, object]:
        return {
            "actor_account_id": self.actor_account_id,
            "actor_id": self.actor_id,
            "actor_kind": self.actor_kind,
            "effective_at": _timestamp(self.effective_at),
            "event_id": self.event_id,
            "idempotency_key": self.idempotency_key,
            "kind": self.kind,
            "payload": thaw_json(self.payload),
            "plan_id": self.plan_id,
            "source_id": self.source_id,
            "source_revision_id": self.source_revision_id,
            "source_snapshot": self.source_snapshot,
            "source_snapshot_hash": self.source_snapshot_hash,
        }


def make_lifecycle_event(
    *,
    plan_id: str,
    kind: str,
    actor_kind: str,
    actor_id: str,
    actor_account_id: str,
    source_id: str,
    source_revision_id: str,
    payload: Mapping[str, Any],
    effective_at: datetime,
    idempotency_key: str | None = None,
) -> LifecycleEvent:
    event_id = lifecycle_event_id(plan_id, kind, source_revision_id)
    normalized_time = _utc("effective_at", effective_at)
    normalized_payload = thaw_json(freeze_json(payload))
    declaration = {
        "actor_account_id": actor_account_id,
        "actor_id": actor_id,
        "actor_kind": actor_kind,
        "effective_at": _timestamp(normalized_time),
        "event_id": event_id,
        "kind": kind,
        "payload": normalized_payload,
        "plan_id": plan_id,
        "source_id": source_id,
        "source_revision_id": source_revision_id,
    }
    snapshot = canonical_dumps(declaration).decode("utf-8")
    return LifecycleEvent(
        event_id=event_id,
        plan_id=plan_id,
        kind=kind,
        actor_kind=actor_kind,
        actor_id=actor_id,
        actor_account_id=actor_account_id,
        source_id=source_id,
        source_revision_id=source_revision_id,
        source_snapshot=snapshot,
        source_snapshot_hash=hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        payload=normalized_payload,
        effective_at=normalized_time,
        idempotency_key=idempotency_key or f"lifecycle:{source_revision_id}",
    )


@dataclass(frozen=True)
class WorkRevision:
    revision_id: str
    content_hash: str
    effective_at: datetime
    eligible: bool
    snapshot_identity: tuple[str, str, str] | None = None


@dataclass(frozen=True)
class WorkState:
    work_id: str
    contract_id: str
    agent_id: str
    revisions: tuple[WorkRevision, ...]
    accepted_revision_id: str | None = None
    needs_author: bool = False

    @property
    def eligible(self) -> bool:
        return bool(self.revisions and self.revisions[-1].eligible)


@dataclass(frozen=True)
class RoleState:
    role_id: str
    role_kind: str
    generation: int
    assigned_agent_id: str
    assigned_account_id: str
    target_ids: tuple[str, ...]
    base_due_at: datetime
    effective_due_at: datetime
    funding: str
    amount_wea: int
    escrow_id: str | None = None
    escrow_available_wea: int = 0
    results: tuple[tuple[str, str, datetime], ...] = ()
    status: str = "active"
    pause_ids: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return set(item[0] for item in self.results) == set(self.target_ids)

    @property
    def last_result_at(self) -> datetime | None:
        return max((item[2] for item in self.results), default=None)

    @property
    def timely_complete(self) -> bool:
        return bool(
            self.complete
            and self.last_result_at is not None
            and self.last_result_at <= self.effective_due_at
        )


@dataclass(frozen=True)
class PauseState:
    pause_id: str
    kind: str
    started_at: datetime
    cause_id: str
    ended_at: datetime | None = None


@dataclass(frozen=True)
class Settlement:
    settlement_id: str
    kind: str
    source_account_id: str
    recipient_agent_id: str
    amount_wea: int
    basis_id: str
    prior_financial_hash: str
    result_financial_hash: str


@dataclass(frozen=True)
class ReleaseInvitation:
    invitation_id: str
    recipient_agent_id: str
    source_kind: str
    source_id: str


@dataclass(frozen=True)
class TriageFeedback:
    assessment_id: str
    reviewer_agent_id: str
    polarity: str
    reason: str
    source_event_id: str


@dataclass(frozen=True)
class StageState:
    stage_index: int
    stage_key: str
    contract: StageContract
    status: str
    phase: str
    deadlines: tuple[StageDeadline, ...]
    works: tuple[WorkState, ...] = ()
    selected_revision_id: str | None = None
    paid_wea: int = 0
    refunded_wea: int = 0
    birdie_at: datetime | None = None
    duel_participants: tuple[tuple[str, str], ...] = ()
    duel_moves: tuple[tuple[int, str, datetime], ...] = ()


@dataclass(frozen=True)
class RuntimeProjection:
    plan_id: str
    plan_status: str
    current_stage_index: int
    balances: tuple[AccountBalance, ...]
    escrow: ProgramEscrow
    stages: tuple[StageState, ...]
    roles: tuple[RoleState, ...]
    pauses: tuple[PauseState, ...]
    settlements: tuple[Settlement, ...]
    releases: tuple[ReleaseInvitation, ...]
    triage_feedback: tuple[TriageFeedback, ...]
    future_stages: tuple[PlanStage, ...]

    def balance(self, agent_id: str) -> int:
        return next(
            (item.amount_wea for item in self.balances if item.account_id == agent_id),
            0,
        )

    @property
    def current_stage(self) -> StageState:
        return next(
            item for item in self.stages if item.stage_index == self.current_stage_index
        )


@dataclass(frozen=True)
class NextAction:
    plan_id: str
    stage_key: str
    contract_id: str
    depth: str
    mode: str
    actor_id: str
    action: str
    boundary_at: datetime | None


def _runtime_state_seals() -> tuple[Any, Any]:
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
        current = seals.get(id(state))
        if current is None or current[0]() is not state:
            return None
        return current[1]

    return remember, read


_remember_runtime_state, _read_runtime_state = _runtime_state_seals()
del _runtime_state_seals
_RUNTIME_STATE_CAPABILITY = object()


def _assert_activation_group(activation: PlanActivation) -> None:
    if type(activation) is not PlanActivation or type(activation.created) is not bool:
        raise PlanError("evidence_boundary: activation must use exact verified type")
    if type(activation.state) is not PlanIntakeState:
        raise PlanError("evidence_boundary: activation state has an invalid type")
    activation.state._assert_unchanged()
    plan_matches = [
        item
        for item in activation.state.plans
        if item.plan_id == activation.plan.plan_id
    ]
    escrow_matches = [
        item
        for item in activation.state.escrows
        if item.plan_id == activation.plan.plan_id
    ]
    contract_matches = [
        item
        for item in activation.state.contracts
        if item.plan_id == activation.plan.plan_id
    ]
    task_matches = [
        item
        for item in activation.state.tasks
        if item.plan_id == activation.plan.plan_id
    ]
    debit_matches = [
        item
        for item in activation.state.ledger
        if item.basis_id == activation.plan.plan_id
    ]
    revision_matches = [
        item
        for item in activation.state.plan_revisions
        if item.revision_id == activation.plan.plan_revision_id
    ]
    if any(
        len(items) != 1
        for items in (
            plan_matches,
            escrow_matches,
            contract_matches,
            task_matches,
            debit_matches,
            revision_matches,
        )
    ):
        raise PlanError("evidence_boundary: activation group is not in verified state")
    if (
        activation.plan != plan_matches[0]
        or activation.escrow != escrow_matches[0]
        or activation.contract != contract_matches[0]
        or activation.task != task_matches[0]
        or activation.debit != debit_matches[0]
    ):
        raise PlanError("evidence_boundary: activation group does not match state")
    revision = revision_matches[0]
    if (
        activation.draft.repository_id != revision.repository_id
        or activation.draft.issue_id != revision.issue_id
        or activation.draft.issue_revision_id != revision.issue_revision_id
        or activation.draft.body_hash != revision.body_hash
        or activation.draft.author_agent_id != revision.author_agent_id
    ):
        raise PlanError("evidence_boundary: activation Draft does not match state")


@dataclass(frozen=True)
class ResolutionPlanRuntimeState:
    activation: PlanActivation
    events: tuple[LifecycleEvent, ...] = ()

    def __post_init__(self) -> None:
        if type(self.activation) is not PlanActivation:
            raise PlanError(
                "evidence_boundary: activation must use exact verified type"
            )
        _assert_activation_group(self.activation)
        if type(self.events) is not tuple or any(
            type(item) is not LifecycleEvent for item in self.events
        ):
            raise PlanError("evidence_boundary: lifecycle events require exact types")
        if self.events and getattr(self, "_verified_marker", None) is not (
            _RUNTIME_STATE_CAPABILITY
        ):
            raise PlanError("evidence_boundary: non-empty runtime requires replay")
        rebuilt = tuple(
            _rebuild(item, LifecycleEvent, "lifecycle event") for item in self.events
        )
        object.__setattr__(self, "events", rebuilt)
        _remember_runtime_state(self, self.state_hash)

    @property
    def state_hash(self) -> str:
        return canonical_hash(
            {
                "activation_state_hash": self.activation.state.state_hash,
                "plan_id": self.activation.plan.plan_id,
                "events": [item.to_data() for item in self.events],
            }
        )

    def _assert_unchanged(self) -> None:
        if _read_runtime_state(self) != self.state_hash:
            raise PlanError("evidence_boundary: runtime state changed after validation")


def _verified_runtime_state(
    activation: PlanActivation, events: tuple[LifecycleEvent, ...]
) -> ResolutionPlanRuntimeState:
    state = object.__new__(ResolutionPlanRuntimeState)
    object.__setattr__(state, "activation", activation)
    object.__setattr__(state, "events", events)
    object.__setattr__(state, "_verified_marker", _RUNTIME_STATE_CAPABILITY)
    try:
        state.__post_init__()
    finally:
        object.__delattr__(state, "_verified_marker")
    return state


def start_runtime(activation: PlanActivation) -> ResolutionPlanRuntimeState:
    _assert_activation_group(activation)
    return ResolutionPlanRuntimeState(activation=activation)


@dataclass
class _Model:
    plan_status: str
    current_stage_index: int
    balances: dict[str, int]
    escrow_paid: int
    escrow_refunded: int
    stages: dict[int, StageState]
    roles: dict[tuple[str, int], RoleState]
    pauses: list[PauseState]
    settlements: list[Settlement]
    releases: list[ReleaseInvitation]
    triage_feedback: list[TriageFeedback]
    future_stages: list[PlanStage]
    warnings: dict[str, str]


def _initial_model(activation: PlanActivation) -> _Model:
    first = StageState(
        stage_index=0,
        stage_key=activation.contract.stage_key,
        contract=activation.contract,
        status="active",
        phase="join" if activation.contract.mode == "duel" else "intake",
        deadlines=activation.contract.deadlines,
    )
    return _Model(
        plan_status="active",
        current_stage_index=0,
        balances={
            item.account_id: item.amount_wea for item in activation.state.balances
        },
        escrow_paid=0,
        escrow_refunded=0,
        stages={0: first},
        roles={},
        pauses=[],
        settlements=[],
        releases=[],
        triage_feedback=[],
        future_stages=list(activation.plan.stages),
        warnings={},
    )


def _financial_data(model: _Model, activation: PlanActivation) -> dict[str, object]:
    return {
        "balances": [
            {"account_id": key, "amount_wea": value}
            for key, value in sorted(model.balances.items())
        ],
        "escrow": {
            "deposited_wea": activation.escrow.deposited_wea,
            "paid_wea": model.escrow_paid,
            "refunded_wea": model.escrow_refunded,
        },
        "role_escrows": [
            {
                "available_wea": role.escrow_available_wea,
                "escrow_id": role.escrow_id,
            }
            for role in sorted(
                model.roles.values(), key=lambda item: (item.role_id, item.generation)
            )
            if role.escrow_id is not None
        ],
    }


def _settle(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    *,
    label: str,
    kind: str,
    recipient: str,
    amount: int,
    basis_id: str,
) -> None:
    amount = _positive_int("amount_wea", amount)
    prior = canonical_hash(_financial_data(model, activation))
    available = (
        activation.escrow.deposited_wea - model.escrow_paid - model.escrow_refunded
    )
    if amount > available:
        raise PlanError("money: program escrow is insufficient")
    if kind == "refund":
        model.escrow_refunded += amount
    else:
        model.escrow_paid += amount
    model.balances[recipient] = model.balances.get(recipient, 0) + amount
    result = canonical_hash(_financial_data(model, activation))
    model.settlements.append(
        Settlement(
            settlement_id=f"{event.event_id}:settlement:{label}",
            kind=kind,
            source_account_id=activation.escrow.escrow_id,
            recipient_agent_id=recipient,
            amount_wea=amount,
            basis_id=basis_id,
            prior_financial_hash=prior,
            result_financial_hash=result,
        )
    )


def _payload(event: LifecycleEvent, keys: set[str]) -> dict[str, Any]:
    value = thaw_json(event.payload)
    if type(value) is not dict or set(value) != keys:
        raise PlanError(f"declaration: {event.kind} payload has invalid keys")
    return value


def _current(model: _Model) -> StageState:
    if model.current_stage_index not in model.stages:
        raise PlanError("evidence_boundary: current stage is not materialized")
    return model.stages[model.current_stage_index]


def _stage_for_contract(model: _Model, contract_id: str) -> StageState:
    matches = [
        item
        for item in model.stages.values()
        if item.contract.contract_id == contract_id
    ]
    if len(matches) != 1:
        raise PlanError("evidence_boundary: child Contract is not active in this Plan")
    return matches[0]


def _replace_stage(model: _Model, stage: StageState, **changes: object) -> StageState:
    updated = replace(stage, **changes)
    model.stages[stage.stage_index] = updated
    return updated


def _work(stage: StageState, identifier: str) -> WorkState:
    matches = [item for item in stage.works if item.work_id == identifier]
    if len(matches) != 1:
        raise PlanError("evidence_boundary: Work is not in the child Contract")
    return matches[0]


def _replace_work(stage: StageState, work: WorkState, **changes: object) -> StageState:
    updated = replace(work, **changes)
    return replace(
        stage,
        works=tuple(
            updated if item.work_id == work.work_id else item for item in stage.works
        ),
    )


def _active_body_pause(model: _Model) -> PauseState | None:
    return next(
        (
            item
            for item in reversed(model.pauses)
            if item.kind == "body_integrity_pause" and item.ended_at is None
        ),
        None,
    )


def _active_pause(model: _Model, kind: str) -> PauseState | None:
    return next(
        (
            item
            for item in reversed(model.pauses)
            if item.kind == kind and item.ended_at is None
        ),
        None,
    )


def _active_contract_accepts_work(model: _Model) -> bool:
    """A risk pause does not freeze revisions in the active Contract."""
    if _active_body_pause(model) is not None:
        return False
    if model.plan_status == "active":
        return True
    return (
        model.plan_status == "paused" and _active_pause(model, "risk_pause") is not None
    )


def _progression_is_usable(model: _Model) -> bool:
    """Settlement and stage progression require every pause to be resolved."""
    return (
        model.plan_status == "active"
        and _active_body_pause(model) is None
        and _active_pause(model, "risk_pause") is None
        and _active_pause(model, "progression_pause") is None
    )


def _stage_deadline(stage: StageState, kind: str) -> StageDeadline:
    try:
        return next(item for item in reversed(stage.deadlines) if item.kind == kind)
    except StopIteration as exc:
        raise PlanError(f"state: active stage has no {kind} deadline") from exc


def _deadline(
    deadline_id: str, kind: str, anchor: datetime, duration: int
) -> StageDeadline:
    due = materialize_deadline(anchor, duration)
    return StageDeadline(deadline_id, kind, anchor, duration, due, due)


def _close_stage(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    stage: StageState,
    *,
    selected_revision_id: str | None,
) -> None:
    stage = _replace_stage(
        model,
        stage,
        status="completed",
        phase="closed",
        selected_revision_id=selected_revision_id,
    )
    if stage.stage_index == len(model.future_stages) - 1:
        model.plan_status = "completed"
        _finalize_success(model, activation, event)
        return
    if any(
        item.kind in {"risk_pause", "progression_pause"} and item.ended_at is None
        for item in model.pauses
    ):
        model.plan_status = "paused"
        return
    _materialize_next(model, activation, event, stage)


def _selected_input(stage: StageState, revision_id: str) -> ResolvedWorkInput:
    matches = [
        (work, revision)
        for work in stage.works
        for revision in work.revisions
        if revision.revision_id == revision_id
        and work.accepted_revision_id == revision_id
    ]
    if len(matches) != 1:
        raise PlanError("evidence_boundary: selector must name one accepted revision")
    work, revision = matches[0]
    return ResolvedWorkInput(
        source_stage_key=stage.stage_key,
        source_contract_id=stage.contract.contract_id,
        work_id=work.work_id,
        revision_id=revision.revision_id,
        content_hash=revision.content_hash,
    )


def _materialize_next(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    completed: StageState,
) -> None:
    next_index = completed.stage_index + 1
    template = model.future_stages[next_index]
    try:
        resolved = tuple(
            _selected_input(
                model.stages[
                    next(
                        index
                        for index, candidate in enumerate(model.future_stages)
                        if candidate.key == selector.source_stage_key
                    )
                ],
                model.stages[
                    next(
                        index
                        for index, candidate in enumerate(model.future_stages)
                        if candidate.key == selector.source_stage_key
                    )
                ].selected_revision_id
                or "",
            )
            for selector in template.inputs
        )
    except (PlanError, StopIteration):
        pause = PauseState(
            pause_id=f"{event.event_id}:progression-pause",
            kind="progression_pause",
            started_at=event.effective_at,
            cause_id=completed.contract.contract_id,
        )
        model.pauses.append(pause)
        model.plan_status = "paused"
        return
    identifier = stage_contract_id(activation.plan.plan_id, template.key)
    contract = StageContract(
        contract_id=identifier,
        plan_id=activation.plan.plan_id,
        plan_revision_id=activation.plan.plan_revision_id,
        plan_content_hash=activation.plan.plan_content_hash,
        stage_index=next_index,
        stage_key=template.key,
        depth=template.depth,
        mode=template.mode,
        schedule=template.schedule,
        config=template.config,
        expected_output=template.expected_output,
        allocation_wea=template.allocation_wea,
        author_agent_id=activation.plan.author_agent_id,
        payer_agent_id=activation.plan.payer_agent_id,
        resolved_inputs=resolved,
        deadlines=initial_stage_deadlines(
            identifier, template.mode, template.schedule, event.effective_at
        ),
        ruleset_hash=activation.plan.ruleset_hash,
        tide_interface_version=activation.plan.tide_interface_version,
        executor_manifest_hash=activation.plan.executor_manifest_hash,
        activated_at=event.effective_at,
    )
    model.stages[next_index] = StageState(
        stage_index=next_index,
        stage_key=template.key,
        contract=contract,
        status="active",
        phase="join" if template.mode == "duel" else "intake",
        deadlines=contract.deadlines,
    )
    model.current_stage_index = next_index


def _release(model: _Model, recipient: str, source_kind: str, source_id: str) -> None:
    invitation = ReleaseInvitation(
        invitation_id=f"release:{source_kind}:{source_id}:{recipient}",
        recipient_agent_id=recipient,
        source_kind=source_kind,
        source_id=source_id,
    )
    if invitation not in model.releases:
        model.releases.append(invitation)


def _activation_assessment(activation: PlanActivation) -> Any:
    assessment_id = next(
        revision.triage_assessment_id
        for revision in activation.state.plan_revisions
        if revision.revision_id == activation.plan.plan_revision_id
    )
    return next(
        item
        for item in activation.state.triage_assessments
        if item.assessment_id == assessment_id
    )


def _finalize_success(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    if model.escrow_paid + model.escrow_refunded < activation.escrow.deposited_wea:
        amount = (
            activation.escrow.deposited_wea - model.escrow_paid - model.escrow_refunded
        )
        _settle(
            model,
            activation,
            event,
            label="terminal-unused",
            kind="refund",
            recipient=activation.plan.author_agent_id,
            amount=amount,
            basis_id=activation.plan.plan_id,
        )
    final_stage = _current(model)
    if final_stage.contract.depth == "implement":
        for work in final_stage.works:
            if work.accepted_revision_id is not None:
                _release(model, work.agent_id, "implement_work", work.work_id)
    assessment = _activation_assessment(activation)
    if not any(
        item.assessment_id == assessment.assessment_id and item.polarity == "negative"
        for item in model.triage_feedback
    ):
        _release(
            model, assessment.reviewer_agent_id, "triage", assessment.assessment_id
        )


def _authorize_event(
    projection: RuntimeProjection,
    activation: PlanActivation,
    event: LifecycleEvent,
    registry: IdentityRegistry,
) -> None:
    if type(registry) is not IdentityRegistry:
        raise PlanError("identity: registry must use exact verified type")
    try:
        registry._assert_unchanged()
    except IdentityError as exc:
        raise PlanError("identity: registry changed after validation") from exc
    if event.actor_kind in {"author", "agent", "role"}:
        try:
            authority = authorize_agent(
                github_account_id=event.actor_account_id,
                agent_id=event.actor_id,
                effective_at=event.effective_at,
                registry=registry,
            )
        except IdentityError as exc:
            raise PlanError("authority: lifecycle actor is not authorized") from exc
        if authority.agent_id != event.actor_id:
            raise PlanError("authority: lifecycle actor binding does not match")
    elif event.actor_kind == "agent0":
        try:
            resolve_binding(
                tuple(
                    item for item in registry.bindings if item.actor_kind == "agent0"
                ),
                github_account_id=event.actor_account_id,
                subject_id="agent0@system",
                effective_at=event.effective_at,
            )
        except IdentityError as exc:
            raise PlanError("authority: Agent0 is not authorized") from exc
        if event.actor_id != "agent0@system":
            raise PlanError("authority: Agent0 actor ID is invalid")
    elif event.actor_kind == "tide":
        if (event.actor_id, event.actor_account_id) != (
            "tide@system",
            "tide@system",
        ):
            raise PlanError("authority: Tide boundary identity is invalid")
    elif event.actor_kind == "validator":
        _text("validator_id", event.actor_id)
    else:
        raise PlanError("authority: lifecycle actor kind is invalid")
    author_kinds = {
        "author_continue",
        "author_stop",
        "birdie",
        "duel_decision",
        "frontier_close",
        "ranked_order",
        "suffix_replan",
    }
    if event.kind in author_kinds and (
        event.actor_kind != "author"
        or event.actor_id != activation.plan.author_agent_id
    ):
        raise PlanError("authority: exact Plan author is required")
    if event.kind in {"risk_pause", "role_assignment", "role_resolution"} and (
        event.actor_kind != "agent0" or event.actor_id != "agent0@system"
    ):
        raise PlanError("authority: exact Agent0 declaration is required")
    if event.kind in {"mode_expiry", "body_pause", "body_resume"} and (
        event.actor_kind != "tide"
    ):
        raise PlanError("authority: Tide boundary is required")
    if event.kind == "role_result":
        data = thaw_json(event.payload)
        role_id = data.get("role_id")
        generation = data.get("generation")
        matches = [
            item
            for item in projection.roles
            if item.role_id == role_id and item.generation == generation
        ]
        if len(matches) != 1 or event.actor_id != matches[0].assigned_agent_id:
            raise PlanError("authority: role result requires the assigned actor")
    if event.kind == "role_assignment":
        data = thaw_json(event.payload)
        try:
            authorize_agent(
                github_account_id=data.get("assigned_account_id"),
                agent_id=data.get("assigned_agent_id"),
                effective_at=event.effective_at,
                registry=registry,
            )
        except (IdentityError, TypeError) as exc:
            raise PlanError("authority: assigned role actor is not authorized") from exc
    if event.kind == "downstream_blocker" and event.actor_kind == "role":
        role_id = thaw_json(event.payload).get("role_id")
        matches = [
            item
            for item in projection.roles
            if item.role_id == role_id and item.status == "active"
        ]
        if not matches or event.actor_id != matches[-1].assigned_agent_id:
            raise PlanError("authority: blocker requires the assigned active role")


def _work_revision(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(
        event,
        {"content_hash", "contract_id", "eligible", "revision_id", "snapshot"},
    )
    if not _active_contract_accepts_work(model):
        raise PlanError("state: Plan does not accept Work")
    stage = _stage_for_contract(model, _text("contract_id", data["contract_id"]))
    if (
        stage.contract.mode not in {"ranked", "flat_pod", "frontier"}
        or stage.status != "active"
        or stage.phase != "intake"
        or event.effective_at > _stage_deadline(stage, "intake").effective_due_at
    ):
        raise PlanError("state: Work is late or child Contract is closed")
    if event.actor_kind != "agent":
        raise PlanError("authority: Work revision requires a participating Agent")
    if event.actor_id == stage.contract.author_agent_id:
        raise PlanError("authority: author cannot submit Work to own Plan")
    identifier = work_id(stage.contract.contract_id, event.actor_id)
    existing = next((item for item in stage.works if item.work_id == identifier), None)
    revisions = () if existing is None else existing.revisions
    expected_revision = work_revision_id(identifier, len(revisions) + 1)
    if data["revision_id"] != expected_revision:
        raise PlanError("evidence_boundary: Work revision ID is not deterministic")
    snapshot_identity = None
    if stage.contract.mode == "frontier":
        snapshot = data["snapshot"]
        if type(snapshot) is not dict or set(snapshot) != {
            "genome",
            "model",
            "runtime",
        }:
            raise PlanError("declaration: Frontier snapshot identity is incomplete")
        snapshot_identity = (
            _text("model", snapshot["model"]),
            _text("genome", snapshot["genome"]),
            _text("runtime", snapshot["runtime"]),
        )
        if any(
            revision.snapshot_identity == snapshot_identity
            for work in stage.works
            for revision in work.revisions
        ):
            raise PlanError("matrix: Frontier snapshot already exists")
    elif data["snapshot"] is not None:
        raise PlanError("declaration: snapshot identity belongs only to Frontier")
    revision = WorkRevision(
        revision_id=expected_revision,
        content_hash=_hash("content_hash", data["content_hash"]),
        effective_at=event.effective_at,
        eligible=type(data["eligible"]) is bool and data["eligible"],
        snapshot_identity=snapshot_identity,
    )
    work = WorkState(
        work_id=identifier,
        contract_id=stage.contract.contract_id,
        agent_id=event.actor_id,
        revisions=(*revisions, revision),
        accepted_revision_id=(
            None if existing is None else existing.accepted_revision_id
        ),
        needs_author=False if existing is None else existing.needs_author,
    )
    works = (
        (*stage.works, work)
        if existing is None
        else tuple(work if item.work_id == identifier else item for item in stage.works)
    )
    _replace_stage(model, stage, works=works)


def _acceptance_authority(
    stage: StageState, event: LifecycleEvent, *, needs_author: bool
) -> None:
    config = thaw_json(stage.contract.config)
    acceptance = config.get("acceptance")
    if type(acceptance) is not dict or "kind" not in acceptance:
        raise PlanError("matrix: child Contract has no acceptance authority")
    if needs_author:
        if (
            event.actor_kind != "author"
            or event.actor_id != stage.contract.author_agent_id
        ):
            raise PlanError("authority: deferred verdict requires the exact author")
    elif acceptance["kind"] == "author":
        if (
            event.actor_kind != "author"
            or event.actor_id != stage.contract.author_agent_id
        ):
            raise PlanError("authority: exact author acceptance is required")
    elif acceptance["kind"] == "normalized_validator":
        if (
            event.actor_kind != "validator"
            or event.actor_id != acceptance.get("validator_id")
            or event.actor_account_id != acceptance.get("version")
        ):
            raise PlanError("authority: pinned validator result is required")
    else:
        raise PlanError("matrix: acceptance authority is invalid")


def _work_acceptance(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(
        event,
        {"contract_id", "novel", "revision_id", "verdict", "work_id"},
    )
    if not _progression_is_usable(model):
        raise PlanError("state: Plan does not accept Work decisions")
    stage = _stage_for_contract(model, _text("contract_id", data["contract_id"]))
    acceptance_phase = stage.phase == "intake" or (
        stage.contract.mode == "flat_pod" and stage.phase == "closed-intake"
    )
    acceptance_due = (
        stage.birdie_at or _stage_deadline(stage, "intake").effective_due_at
    )
    if (
        stage.contract.mode not in {"flat_pod", "frontier"}
        or stage.status != "active"
        or not acceptance_phase
        or event.effective_at > acceptance_due
    ):
        raise PlanError("matrix: Work acceptance does not apply to this mode")
    work = _work(stage, _text("work_id", data["work_id"]))
    _acceptance_authority(stage, event, needs_author=work.needs_author)
    revision = next(
        (item for item in work.revisions if item.revision_id == data["revision_id"]),
        None,
    )
    if revision is None or not revision.eligible:
        raise PlanError("matrix: accepted Work revision must be eligible")
    verdict = data["verdict"]
    if verdict == "needs_author":
        if event.actor_kind != "validator":
            raise PlanError("authority: only validator can defer to author")
        updated = _replace_work(stage, work, needs_author=True)
        _replace_stage(model, stage, works=updated.works)
        return
    if verdict != "accept":
        raise PlanError("declaration: Work verdict is invalid")
    if work.accepted_revision_id is not None:
        raise PlanError("state: one Work can consume at most one slot")
    if stage.contract.mode == "frontier" and data["novel"] is not True:
        raise PlanError("matrix: Frontier Work must advance prior art")
    accepted = [item for item in stage.works if item.accepted_revision_id is not None]
    vector = tuple(thaw_json(stage.contract.config)["payout_vector"])
    if len(accepted) >= len(vector):
        raise PlanError("state: mode slot cap is already full")
    amount = vector[len(accepted)]
    _settle(
        model,
        activation,
        event,
        label=f"slot-{len(accepted) + 1}",
        kind="payout",
        recipient=work.agent_id,
        amount=amount,
        basis_id=work.work_id,
    )
    updated = _replace_work(
        stage, work, accepted_revision_id=revision.revision_id, needs_author=False
    )
    stage = _replace_stage(
        model,
        stage,
        works=updated.works,
        paid_wea=stage.paid_wea + amount,
    )
    if len(accepted) + 1 == len(vector):
        _close_additive(model, activation, event, stage, None)


def _ranked_order(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(event, {"contract_id", "ordered_work_ids", "selected_revision_id"})
    if not _progression_is_usable(model):
        raise PlanError("state: Plan is not active")
    stage = _stage_for_contract(model, _text("contract_id", data["contract_id"]))
    if (
        stage.contract.mode != "ranked"
        or stage.status != "active"
        or stage.phase != "decision"
        or event.effective_at
        > _stage_deadline(stage, "author_decision").effective_due_at
    ):
        raise PlanError("matrix: Ranked order does not apply")
    ordered = data["ordered_work_ids"]
    if type(ordered) is not list or not ordered or len(ordered) != len(set(ordered)):
        raise PlanError("declaration: Ranked order must be non-empty and unique")
    eligible = {item.work_id for item in stage.works if item.eligible}
    vector = tuple(thaw_json(stage.contract.config)["payout_vector"])
    if set(ordered) != eligible or len(ordered) > len(vector):
        raise PlanError("matrix: Ranked order must contain every eligible Work")
    selected = _text("selected_revision_id", data["selected_revision_id"])
    winner = _work(stage, ordered[0])
    if selected not in {item.revision_id for item in winner.revisions if item.eligible}:
        raise PlanError("matrix: selected revision must belong to rank one")
    works = list(stage.works)
    for rank, identifier in enumerate(ordered):
        work = _work(stage, identifier)
        revision = next(item for item in reversed(work.revisions) if item.eligible)
        accepted_revision_id = selected if rank == 0 else revision.revision_id
        amount = vector[rank]
        _settle(
            model,
            activation,
            event,
            label=f"rank-{rank + 1}",
            kind="payout",
            recipient=work.agent_id,
            amount=amount,
            basis_id=work.work_id,
        )
        works = [
            replace(item, accepted_revision_id=accepted_revision_id)
            if item.work_id == identifier
            else item
            for item in works
        ]
    refund = sum(vector[len(ordered) :])
    if refund:
        _settle(
            model,
            activation,
            event,
            label="rank-underfill",
            kind="refund",
            recipient=activation.plan.author_agent_id,
            amount=refund,
            basis_id=stage.contract.contract_id,
        )
    stage = _replace_stage(
        model,
        stage,
        works=tuple(works),
        paid_wea=sum(vector[: len(ordered)]),
        refunded_wea=refund,
    )
    _close_stage(model, activation, event, stage, selected_revision_id=selected)


def _close_additive(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    stage: StageState,
    selected_revision_id: str | None,
) -> None:
    vector = tuple(thaw_json(stage.contract.config)["payout_vector"])
    accepted = sum(item.accepted_revision_id is not None for item in stage.works)
    refund = sum(vector[accepted:])
    if refund:
        _settle(
            model,
            activation,
            event,
            label="unused-slots",
            kind="refund",
            recipient=activation.plan.author_agent_id,
            amount=refund,
            basis_id=stage.contract.contract_id,
        )
    stage = _replace_stage(model, stage, refunded_wea=stage.refunded_wea + refund)
    if (
        stage.stage_index < len(model.future_stages) - 1
        and selected_revision_id is None
    ):
        pause = PauseState(
            pause_id=f"{event.event_id}:progression-pause",
            kind="progression_pause",
            started_at=event.effective_at,
            cause_id=stage.contract.contract_id,
        )
        model.pauses.append(pause)
        model.plan_status = "paused"
        _replace_stage(model, stage, status="completed", phase="closed")
        return
    _close_stage(
        model,
        activation,
        event,
        stage,
        selected_revision_id=selected_revision_id,
    )


def _birdie(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(event, {"contract_id", "work_id"})
    if not _progression_is_usable(model):
        raise PlanError("state: birdie requires an active Plan")
    stage = _stage_for_contract(model, data["contract_id"])
    if stage.contract.mode not in {"ranked", "flat_pod"}:
        raise PlanError("matrix: birdie applies only to Ranked or Flat PoD")
    if (
        stage.phase != "intake"
        or event.effective_at > stage.deadlines[0].effective_due_at
    ):
        raise PlanError("state: birdie is outside the intake boundary")
    work = _work(stage, data["work_id"])
    if not work.eligible:
        raise PlanError("matrix: birdie requires an exact eligible Work")
    deadlines = stage.deadlines
    if stage.contract.mode == "ranked":
        duration = stage.contract.schedule.author_decision_seconds
        assert duration is not None
        deadlines = (
            *deadlines,
            _deadline(
                f"{stage.contract.contract_id}:deadline:author-decision",
                "author_decision",
                event.effective_at,
                duration,
            ),
        )
    _replace_stage(
        model,
        stage,
        phase="decision" if stage.contract.mode == "ranked" else "closed-intake",
        deadlines=deadlines,
        birdie_at=event.effective_at,
    )


def _mode_expiry(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(event, {"contract_id"})
    stage = _stage_for_contract(model, data["contract_id"])
    if stage.status != "active" or not _progression_is_usable(model):
        raise PlanError("state: mode expiry requires an active stage")
    if stage.contract.mode == "ranked" and stage.phase == "intake":
        due = _stage_deadline(stage, "intake").effective_due_at
    elif stage.contract.mode == "ranked" and stage.phase == "decision":
        due = _stage_deadline(stage, "author_decision").effective_due_at
    elif stage.contract.mode in {"flat_pod", "frontier"} and stage.phase in {
        "intake",
        "closed-intake",
    }:
        due = stage.birdie_at or _stage_deadline(stage, "intake").effective_due_at
    elif stage.contract.mode == "duel" and stage.phase == "join":
        due = _stage_deadline(stage, "join").effective_due_at
    elif stage.contract.mode == "duel" and stage.phase == "moves":
        due = _stage_deadline(stage, "move-6").effective_due_at
    elif stage.contract.mode == "duel" and stage.phase == "decision":
        due = _stage_deadline(stage, "author_decision").effective_due_at
    else:
        raise PlanError("state: active mode has no expirable boundary")
    if event.effective_at <= due:
        raise PlanError("state: mode boundary has not expired")
    if stage.contract.mode == "ranked" and stage.phase == "intake":
        duration = stage.contract.schedule.author_decision_seconds
        assert duration is not None
        deadline = _deadline(
            f"{stage.contract.contract_id}:deadline:author-decision",
            "author_decision",
            due,
            duration,
        )
        _replace_stage(
            model, stage, phase="decision", deadlines=(*stage.deadlines, deadline)
        )
        return
    if stage.contract.mode == "ranked":
        amount = stage.contract.allocation_wea
        _settle(
            model,
            activation,
            event,
            label="ranked-no-decision",
            kind="refund",
            recipient=activation.plan.author_agent_id,
            amount=amount,
            basis_id=stage.contract.contract_id,
        )
        stage = _replace_stage(model, stage, refunded_wea=amount)
        _close_stage(model, activation, event, stage, selected_revision_id=None)
    elif stage.contract.mode in {"flat_pod", "frontier"}:
        _close_additive(model, activation, event, stage, None)
    elif stage.phase == "join":
        _stop_duel(model, activation, event, stage, "duel-underfilled")
    elif stage.phase == "moves":
        completers = _duel_completers(stage)
        if not completers:
            _stop_duel(model, activation, event, stage, "duel-no-completers")
            return
        duration = stage.contract.schedule.author_decision_seconds
        assert duration is not None
        deadline = _deadline(
            f"{stage.contract.contract_id}:deadline:author-decision",
            "author_decision",
            due,
            duration,
        )
        _replace_stage(
            model, stage, phase="decision", deadlines=(*stage.deadlines, deadline)
        )
    else:
        _stop_duel(model, activation, event, stage, "duel-no-valid-decision")


def _duel_join(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(event, {"contract_id", "position"})
    stage = _stage_for_contract(model, data["contract_id"])
    if (
        stage.contract.mode != "duel"
        or stage.phase != "join"
        or stage.status != "active"
        or not _active_contract_accepts_work(model)
    ):
        raise PlanError("matrix: Duel join does not apply")
    if event.effective_at > stage.deadlines[0].effective_due_at:
        raise PlanError("state: Duel join is late")
    config = thaw_json(stage.contract.config)
    positions = tuple(config["positions"])
    position = _text("position", data["position"])
    if position not in positions:
        raise PlanError("matrix: Duel position is invalid")
    if event.actor_id == stage.contract.author_agent_id:
        raise PlanError("authority: author cannot join own Duel")
    if config["admission"] == "invited" and not any(
        item["agent_id"] == event.actor_id and item["position"] == position
        for item in config["invitations"]
    ):
        raise PlanError("authority: Agent is not invited to this Duel position")
    if any(
        agent == event.actor_id or existing == position
        for agent, existing in stage.duel_participants
    ):
        raise PlanError("state: Duel join must add a distinct Agent and position")
    participants = (*stage.duel_participants, (event.actor_id, position))
    deadlines = stage.deadlines
    phase = stage.phase
    if len(participants) == 2:
        windows = duel_windows(event.effective_at, stage.contract.schedule.move_seconds)
        deadlines = (
            *deadlines,
            *tuple(
                StageDeadline(
                    deadline_id=f"{stage.contract.contract_id}:deadline:move-{index}",
                    kind=f"move-{index}",
                    anchor_at=window.opens_at,
                    duration_seconds=duration,
                    base_due_at=window.due_at,
                    effective_due_at=window.due_at,
                )
                for index, (window, duration) in enumerate(
                    zip(windows, stage.contract.schedule.move_seconds, strict=True),
                    start=1,
                )
            ),
        )
        phase = "moves"
    _replace_stage(
        model, stage, duel_participants=participants, deadlines=deadlines, phase=phase
    )


def _duel_move(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(
        event, {"content_hash", "contract_id", "move_number", "revision_id"}
    )
    stage = _stage_for_contract(model, data["contract_id"])
    if (
        stage.contract.mode != "duel"
        or stage.phase != "moves"
        or not _active_contract_accepts_work(model)
    ):
        raise PlanError("matrix: Duel move does not apply")
    number = _positive_int("move_number", data["move_number"])
    if number > 6 or any(item[0] == number for item in stage.duel_moves):
        raise PlanError("state: Duel move order is invalid")
    expected_agent = stage.duel_participants[(number - 1) % 2][0]
    if event.actor_id != expected_agent:
        raise PlanError("authority: Duel move belongs to the other participant")
    deadline = next(item for item in stage.deadlines if item.kind == f"move-{number}")
    effective_anchor = deadline.effective_anchor_at
    assert effective_anchor is not None
    if not effective_anchor <= event.effective_at <= deadline.effective_due_at:
        raise PlanError("state: Duel move is outside its exact window")
    identifier = work_id(stage.contract.contract_id, event.actor_id)
    existing = next((item for item in stage.works if item.work_id == identifier), None)
    revisions = () if existing is None else existing.revisions
    expected_revision = work_revision_id(identifier, len(revisions) + 1)
    if data["revision_id"] != expected_revision:
        raise PlanError("evidence_boundary: Duel revision ID is not deterministic")
    revision = WorkRevision(
        revision_id=expected_revision,
        content_hash=_hash("content_hash", data["content_hash"]),
        effective_at=event.effective_at,
        eligible=True,
    )
    work = WorkState(
        work_id=identifier,
        contract_id=stage.contract.contract_id,
        agent_id=event.actor_id,
        revisions=(*revisions, revision),
        accepted_revision_id=None
        if existing is None
        else existing.accepted_revision_id,
    )
    works = (
        (*stage.works, work)
        if existing is None
        else tuple(work if item.work_id == identifier else item for item in stage.works)
    )
    moves = (*stage.duel_moves, (number, event.actor_id, event.effective_at))
    phase = stage.phase
    deadlines = stage.deadlines
    if number == 6:
        duration = stage.contract.schedule.author_decision_seconds
        assert duration is not None
        deadlines = (
            *deadlines,
            _deadline(
                f"{stage.contract.contract_id}:deadline:author-decision",
                "author_decision",
                event.effective_at,
                duration,
            ),
        )
        phase = "decision"
    _replace_stage(
        model,
        stage,
        works=works,
        duel_moves=moves,
        phase=phase,
        deadlines=deadlines,
    )


def _duel_completers(stage: StageState) -> list[str]:
    return [
        agent
        for agent, _ in stage.duel_participants
        if sum(move[1] == agent for move in stage.duel_moves) == 3
    ]


def _stop_duel(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    stage: StageState,
    reason: str,
) -> None:
    amount = stage.contract.allocation_wea
    _settle(
        model,
        activation,
        event,
        label="duel-refund",
        kind="refund",
        recipient=activation.plan.author_agent_id,
        amount=amount,
        basis_id=stage.contract.contract_id,
    )
    _replace_stage(
        model,
        stage,
        status="stopped",
        phase="closed",
        refunded_wea=amount,
    )
    model.plan_status = "stopped"
    assessment = _activation_assessment(activation)
    model.triage_feedback.append(
        TriageFeedback(
            assessment_id=assessment.assessment_id,
            reviewer_agent_id=assessment.reviewer_agent_id,
            polarity="negative",
            reason=reason,
            source_event_id=event.event_id,
        )
    )


def _settle_duel(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    stage: StageState,
    outcome: str,
    winner_agent_id: str | None = None,
) -> None:
    participants = [item[0] for item in stage.duel_participants]
    completers = _duel_completers(stage)
    table = thaw_json(load_ruleset().content)["modes"]["duel"]["outcome_percentages"]
    if outcome not in table:
        raise PlanError("declaration: Duel outcome is invalid")
    if outcome == "winner":
        if winner_agent_id not in completers or len(completers) != 2:
            raise PlanError("declaration: Duel winner must be one of two completers")
        ordered = [
            winner_agent_id,
            next(item for item in participants if item != winner_agent_id),
        ]
    elif outcome == "single_completer":
        if len(completers) != 1 or winner_agent_id not in {None, completers[0]}:
            raise PlanError("state: Duel does not have one completer")
        ordered = [completers[0]]
    elif outcome == "inconclusive":
        if len(completers) != 2 or winner_agent_id is not None:
            raise PlanError("state: inconclusive Duel requires two completers")
        ordered = participants
    else:
        raise PlanError("declaration: no-completer settlement requires Tide expiry")
    vector = table[outcome]
    paid = 0
    for index, percentage in enumerate(vector[:2]):
        if percentage and index < len(ordered):
            amount = stage.contract.allocation_wea * percentage // 100
            _settle(
                model,
                activation,
                event,
                label=f"duel-{index + 1}",
                kind="payout",
                recipient=ordered[index],
                amount=amount,
                basis_id=stage.contract.contract_id,
            )
            paid += amount
    refund = stage.contract.allocation_wea - paid
    if refund:
        _settle(
            model,
            activation,
            event,
            label="duel-refund",
            kind="refund",
            recipient=activation.plan.author_agent_id,
            amount=refund,
            basis_id=stage.contract.contract_id,
        )
    selected_revision_id = None
    if outcome in {"winner", "single_completer"}:
        selected_agent = ordered[0]
        selected_work = next(
            item for item in stage.works if item.agent_id == selected_agent
        )
        selected_revision_id = selected_work.revisions[-1].revision_id
        works = tuple(
            replace(item, accepted_revision_id=selected_revision_id)
            if item.work_id == selected_work.work_id
            else item
            for item in stage.works
        )
    else:
        works = stage.works
    stage = _replace_stage(
        model,
        stage,
        works=works,
        paid_wea=paid,
        refunded_wea=refund,
    )
    _close_stage(
        model,
        activation,
        event,
        stage,
        selected_revision_id=selected_revision_id,
    )


def _duel_decision(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(event, {"contract_id", "outcome", "winner_agent_id"})
    stage = _stage_for_contract(model, data["contract_id"])
    if (
        stage.contract.mode != "duel"
        or stage.phase != "decision"
        or not _progression_is_usable(model)
        or event.effective_at
        > _stage_deadline(stage, "author_decision").effective_due_at
    ):
        raise PlanError("matrix: Duel decision does not apply")
    _settle_duel(
        model,
        activation,
        event,
        stage,
        data["outcome"],
        data["winner_agent_id"],
    )


def _role_assignment(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(
        event,
        {
            "amount_wea",
            "assigned_account_id",
            "assigned_agent_id",
            "duration_seconds",
            "funding",
            "generation",
            "role_id",
            "role_kind",
            "target_ids",
        },
    )
    if not _progression_is_usable(model):
        raise PlanError("state: role assignment is outside the active boundary")
    role_id = _text("role_id", data["role_id"])
    generation = _positive_int("generation", data["generation"])
    key = (role_id, generation)
    if key in model.roles:
        raise PlanError("state: role generation already exists")
    previous = [item for item in model.roles if item[0] == role_id]
    if generation != len(previous) + 1:
        raise PlanError("state: role generation must be contiguous")
    targets = data["target_ids"]
    if type(targets) is not list or not targets or len(targets) != len(set(targets)):
        raise PlanError("declaration: role targets must be unique and non-empty")
    funding = data["funding"]
    amount = _non_negative_int("amount_wea", data["amount_wea"])
    if (
        funding not in {"free", "treasury"}
        or (funding == "free" and amount != 0)
        or (funding == "treasury" and amount < 1)
    ):
        raise PlanError("money: role funding terms are invalid")
    duration = _positive_int("duration_seconds", data["duration_seconds"])
    due = materialize_deadline(event.effective_at, duration)
    escrow_id = None
    prior_hash = None
    if funding == "treasury":
        available = model.balances.get("treasury", 0)
        if available < amount:
            raise PlanError("money: treasury cannot fund the assigned role")
        escrow_id = f"role-escrow:{role_id}:generation:{generation}"
        prior_hash = canonical_hash(_financial_data(model, activation))
        model.balances["treasury"] = available - amount
    role = RoleState(
        role_id=role_id,
        role_kind=_text("role_kind", data["role_kind"]),
        generation=generation,
        assigned_agent_id=_text("assigned_agent_id", data["assigned_agent_id"]),
        assigned_account_id=_text("assigned_account_id", data["assigned_account_id"]),
        target_ids=tuple(_text("target_id", item) for item in targets),
        base_due_at=due,
        effective_due_at=due,
        funding=funding,
        amount_wea=amount,
        escrow_id=escrow_id,
        escrow_available_wea=amount if funding == "treasury" else 0,
    )
    model.roles[key] = role
    if funding == "treasury":
        assert escrow_id is not None and prior_hash is not None
        result_hash = canonical_hash(_financial_data(model, activation))
        model.settlements.append(
            Settlement(
                settlement_id=f"{event.event_id}:settlement:role-reserve",
                kind="treasury-reserve",
                source_account_id="treasury",
                recipient_agent_id=escrow_id,
                amount_wea=amount,
                basis_id=f"{role_id}:{generation}",
                prior_financial_hash=prior_hash,
                result_financial_hash=result_hash,
            )
        )


def _role_result(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(event, {"generation", "result_hash", "role_id", "target_id"})
    key = (
        _text("role_id", data["role_id"]),
        _positive_int("generation", data["generation"]),
    )
    role = model.roles.get(key)
    if role is None or role.status != "active":
        raise PlanError("state: role generation is not active")
    if model.plan_status in {"completed", "stopped"} or _active_body_pause(model):
        raise PlanError("state: role evidence is outside the active boundary")
    target = _text("target_id", data["target_id"])
    if target not in role.target_ids or any(item[0] == target for item in role.results):
        raise PlanError("declaration: role result target is invalid or duplicate")
    result = (target, _hash("result_hash", data["result_hash"]), event.effective_at)
    model.roles[key] = replace(role, results=(*role.results, result))


def _close_role_funding(
    model: _Model,
    activation: PlanActivation,
    event: LifecycleEvent,
    key: tuple[str, int],
    role: RoleState,
    *,
    status: str,
    recipient: str,
    kind: str,
) -> None:
    if role.funding == "free":
        model.roles[key] = replace(role, status=status)
        return
    if (
        role.escrow_id is None
        or role.escrow_available_wea != role.amount_wea
        or role.amount_wea < 1
    ):
        raise PlanError("money: role escrow is not fully available")
    prior = canonical_hash(_financial_data(model, activation))
    model.roles[key] = replace(role, status=status, escrow_available_wea=0)
    model.balances[recipient] = model.balances.get(recipient, 0) + role.amount_wea
    result = canonical_hash(_financial_data(model, activation))
    model.settlements.append(
        Settlement(
            settlement_id=(
                f"{event.event_id}:settlement:role-{role.role_id}-"
                f"{role.generation}-{kind}"
            ),
            kind=kind,
            source_account_id=role.escrow_id,
            recipient_agent_id=recipient,
            amount_wea=role.amount_wea,
            basis_id=f"{role.role_id}:{role.generation}",
            prior_financial_hash=prior,
            result_financial_hash=result,
        )
    )


def _role_resolution(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(event, {"generation", "outcome", "role_id"})
    key = (
        _text("role_id", data["role_id"]),
        _positive_int("generation", data["generation"]),
    )
    role = model.roles.get(key)
    if role is None or role.status != "active":
        raise PlanError("state: role generation is not active")
    outcome = data["outcome"]
    if outcome == "accepted":
        if not role.timely_complete:
            raise PlanError("state: accepted role result is not complete and timely")
        _close_role_funding(
            model,
            activation,
            event,
            key,
            role,
            status="completed",
            recipient=role.assigned_agent_id,
            kind="treasury",
        )
        if role.role_kind != "triage":
            _release(
                model,
                role.assigned_agent_id,
                "role",
                f"{role.role_id}:{role.generation}",
            )
    elif outcome == "rejected":
        _close_role_funding(
            model,
            activation,
            event,
            key,
            role,
            status="rejected",
            recipient="treasury",
            kind="treasury-refund",
        )
    else:
        raise PlanError("declaration: role outcome is invalid")


def _body_pause(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(event, {"issue_revision_id"})
    if _active_body_pause(model) is not None:
        raise PlanError("state: body integrity pause is already active")
    pause = PauseState(
        pause_id=f"{event.event_id}:pause",
        kind="body_integrity_pause",
        started_at=event.effective_at,
        cause_id=_text("issue_revision_id", data["issue_revision_id"]),
    )
    model.pauses.append(pause)
    model.plan_status = "paused"


def _offset_deadline(
    deadline: StageDeadline, pause: PauseState, restored_at: datetime
) -> StageDeadline:
    if (
        pause.pause_id in deadline.pause_ids
        or pause.started_at >= deadline.effective_due_at
    ):
        return deadline
    effective_anchor = deadline.effective_anchor_at
    assert effective_anchor is not None
    offset = restored_at - pause.started_at
    return replace(
        deadline,
        effective_anchor_at=(
            effective_anchor + offset
            if pause.started_at < effective_anchor
            else effective_anchor
        ),
        effective_due_at=apply_pause_offset(
            deadline.effective_due_at, pause.started_at, restored_at
        ),
        pause_ids=(*deadline.pause_ids, pause.pause_id),
    )


def _body_resume(model: _Model, event: LifecycleEvent) -> None:
    _payload(event, {"issue_revision_id"})
    pause = _active_body_pause(model)
    if pause is None:
        raise PlanError("state: no body integrity pause is active")
    model.pauses[model.pauses.index(pause)] = replace(
        pause, ended_at=event.effective_at
    )
    for index, stage in tuple(model.stages.items()):
        live_kinds = {
            "join": {"join"},
            "intake": {"intake"},
            "moves": {f"move-{number}" for number in range(1, 7)},
            "decision": {"author_decision"},
        }.get(stage.phase, set())
        model.stages[index] = replace(
            stage,
            deadlines=tuple(
                _offset_deadline(item, pause, event.effective_at)
                if stage.status == "active" and item.kind in live_kinds
                else item
                for item in stage.deadlines
            ),
        )
    for key, role in tuple(model.roles.items()):
        if (
            role.status == "active"
            and pause.started_at < role.effective_due_at
            and pause.pause_id not in role.pause_ids
        ):
            model.roles[key] = replace(
                role,
                effective_due_at=apply_pause_offset(
                    role.effective_due_at, pause.started_at, event.effective_at
                ),
                pause_ids=(*role.pause_ids, pause.pause_id),
            )
    model.plan_status = (
        "paused"
        if any(
            _active_pause(model, kind) is not None
            for kind in ("risk_pause", "progression_pause")
        )
        else "active"
    )


def _risk_warning(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(event, {"generation", "role_id", "warning_id"})
    role_id = _text("role_id", data["role_id"])
    generation = _positive_int("generation", data["generation"])
    role = model.roles.get((role_id, generation))
    if (
        role is None
        or role.status != "active"
        or role.role_kind not in {"triage", "review"}
        or event.actor_kind != "role"
        or event.actor_id != role.assigned_agent_id
        or event.actor_account_id != role.assigned_account_id
    ):
        raise PlanError(
            "authority: warning requires the exact active Triage or review role"
        )
    warning_id = _text("warning_id", data["warning_id"])
    if warning_id in model.warnings:
        raise PlanError("evidence_boundary: warning ID already exists")
    model.warnings[warning_id] = f"{role_id}:{generation}"


def _risk_pause(model: _Model, event: LifecycleEvent) -> None:
    data = _payload(event, {"warning_id"})
    warning_id = _text("warning_id", data["warning_id"])
    if warning_id not in model.warnings:
        raise PlanError("evidence_boundary: risk pause requires exact warning")
    if _active_pause(model, "risk_pause") is not None:
        raise PlanError("state: risk pause is already active")
    model.pauses.append(
        PauseState(
            pause_id=f"{event.event_id}:pause",
            kind="risk_pause",
            started_at=event.effective_at,
            cause_id=warning_id,
        )
    )
    model.plan_status = "paused"


def _author_continue(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    _payload(event, set())
    if _active_body_pause(model) is not None:
        raise PlanError("state: body integrity pause must be resolved first")
    open_pauses = [
        item
        for item in model.pauses
        if item.ended_at is None and item.kind in {"risk_pause", "progression_pause"}
    ]
    if not open_pauses:
        raise PlanError("state: no author-controlled pause is active")
    for pause in open_pauses:
        model.pauses[model.pauses.index(pause)] = replace(
            pause, ended_at=event.effective_at
        )
    model.plan_status = "active"
    current = _current(model)
    if (
        current.status == "completed"
        and current.stage_index < len(model.future_stages) - 1
    ):
        _materialize_next(model, activation, event, current)


def _stage_from_data(value: object) -> PlanStage:
    if type(value) is not dict or set(value) != {
        "allocation_wea",
        "config",
        "depth",
        "expected_output",
        "inputs",
        "key",
        "mode",
        "schedule",
    }:
        raise PlanError("declaration: suffix stage has invalid fields")
    schedule = value["schedule"]
    if type(schedule) is not dict or set(schedule) != {
        "author_decision_seconds",
        "intake_seconds",
        "join_seconds",
        "move_seconds",
    }:
        raise PlanError("declaration: suffix schedule has invalid fields")
    inputs = value["inputs"]
    if type(inputs) is not list or any(
        type(item) is not dict or set(item) != {"kind", "source_stage_key"}
        for item in inputs
    ):
        raise PlanError("declaration: suffix inputs have invalid fields")
    return PlanStage(
        key=value["key"],
        depth=value["depth"],
        mode=value["mode"],
        schedule=StageSchedule(
            intake_seconds=schedule["intake_seconds"],
            join_seconds=schedule["join_seconds"],
            move_seconds=tuple(schedule["move_seconds"]),
            author_decision_seconds=schedule["author_decision_seconds"],
        ),
        allocation_wea=value["allocation_wea"],
        config=value["config"],
        expected_output=value["expected_output"],
        inputs=tuple(SelectedWorkInput(item["source_stage_key"]) for item in inputs),
    )


def _suffix_replan(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    data = _payload(event, {"replacement_suffix"})
    if (
        model.plan_status != "paused"
        or _active_body_pause(model) is not None
        or not any(
            _active_pause(model, kind) is not None
            for kind in ("risk_pause", "progression_pause")
        )
    ):
        raise PlanError("state: suffix replan requires a paused Plan")
    current = _current(model)
    replacement = data["replacement_suffix"]
    if type(replacement) is not list or not replacement:
        raise PlanError("declaration: replacement suffix must be non-empty")
    stages = [_stage_from_data(item) for item in replacement]
    old_suffix = model.future_stages[current.stage_index + 1 :]
    if sum(item.allocation_wea for item in stages) != sum(
        item.allocation_wea for item in old_suffix
    ):
        raise PlanError("money: replacement suffix must keep future allocation")
    prefix = model.future_stages[: current.stage_index + 1]
    candidate = [*prefix, *stages]
    keys = [item.key for item in candidate]
    if len(keys) != len(set(keys)):
        raise PlanError("declaration: replacement suffix stage keys must be unique")
    for index, item in enumerate(candidate):
        earlier = set(keys[:index])
        if any(selector.source_stage_key not in earlier for selector in item.inputs):
            raise PlanError("declaration: replacement suffix selector is not earlier")
    model.future_stages = candidate
    for pause in [item for item in model.pauses if item.ended_at is None]:
        model.pauses[model.pauses.index(pause)] = replace(
            pause, ended_at=event.effective_at
        )
    model.plan_status = "active"
    if current.status == "completed":
        _materialize_next(model, activation, event, current)


def _author_stop(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    _payload(event, set())
    if model.plan_status in {"completed", "stopped"}:
        raise PlanError("state: Plan is already closed")
    if any(
        role.status == "active" and role.timely_complete
        for role in model.roles.values()
    ):
        raise PlanError("state: complete timely role result must be resolved first")
    for key, role in sorted(model.roles.items()):
        if role.status == "active":
            _close_role_funding(
                model,
                activation,
                event,
                key,
                role,
                status="stopped",
                recipient="treasury",
                kind="treasury-refund",
            )
    available = (
        activation.escrow.deposited_wea - model.escrow_paid - model.escrow_refunded
    )
    if available:
        _settle(
            model,
            activation,
            event,
            label="plan-stop",
            kind="refund",
            recipient=activation.plan.author_agent_id,
            amount=available,
            basis_id=activation.plan.plan_id,
        )
    current = _current(model)
    if current.status == "active":
        _replace_stage(model, current, status="stopped", phase="closed")
    model.plan_status = "stopped"
    assessment = _activation_assessment(activation)
    model.triage_feedback.append(
        TriageFeedback(
            assessment_id=assessment.assessment_id,
            reviewer_agent_id=assessment.reviewer_agent_id,
            polarity="negative",
            reason="plan-stopped",
            source_event_id=event.event_id,
        )
    )


def _downstream_blocker(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    expected = {"reason", "role_id"} if event.actor_kind == "role" else {"reason"}
    data = _payload(event, expected)
    if event.actor_kind not in {"agent0", "role"}:
        raise PlanError("authority: blocker requires Agent0 or assigned role")
    assessment = _activation_assessment(activation)
    model.triage_feedback.append(
        TriageFeedback(
            assessment_id=assessment.assessment_id,
            reviewer_agent_id=assessment.reviewer_agent_id,
            polarity="negative",
            reason=_text("reason", data["reason"]),
            source_event_id=event.event_id,
        )
    )
    model.plan_status = "paused"
    model.pauses.append(
        PauseState(
            pause_id=f"{event.event_id}:pause",
            kind="risk_pause",
            started_at=event.effective_at,
            cause_id=event.event_id,
        )
    )


def _apply_event(
    model: _Model, activation: PlanActivation, event: LifecycleEvent
) -> None:
    if model.plan_status in {"completed", "stopped"}:
        raise PlanError("state: terminal Plan rejects later lifecycle events")
    if event.kind == "work_revision":
        _work_revision(model, event)
    elif event.kind == "work_acceptance":
        _work_acceptance(model, activation, event)
    elif event.kind == "ranked_order":
        _ranked_order(model, activation, event)
    elif event.kind == "birdie":
        _birdie(model, event)
    elif event.kind == "mode_expiry":
        _mode_expiry(model, activation, event)
    elif event.kind == "frontier_close":
        data = _payload(event, {"contract_id", "selected_revision_id"})
        stage = _stage_for_contract(model, data["contract_id"])
        if (
            stage.contract.mode != "frontier"
            or stage.phase != "intake"
            or stage.status != "active"
            or not _progression_is_usable(model)
            or event.effective_at > _stage_deadline(stage, "intake").effective_due_at
        ):
            raise PlanError("matrix: Frontier close does not apply")
        selected_revision_id = data["selected_revision_id"]
        if selected_revision_id is not None:
            _selected_input(stage, _text("selected_revision_id", selected_revision_id))
        _close_additive(model, activation, event, stage, selected_revision_id)
    elif event.kind == "duel_join":
        _duel_join(model, event)
    elif event.kind == "duel_move":
        _duel_move(model, event)
    elif event.kind == "duel_decision":
        _duel_decision(model, activation, event)
    elif event.kind == "role_assignment":
        _role_assignment(model, activation, event)
    elif event.kind == "role_result":
        _role_result(model, event)
    elif event.kind == "role_resolution":
        _role_resolution(model, activation, event)
    elif event.kind == "body_pause":
        _body_pause(model, event)
    elif event.kind == "body_resume":
        _body_resume(model, event)
    elif event.kind == "risk_warning":
        _risk_warning(model, event)
    elif event.kind == "risk_pause":
        _risk_pause(model, event)
    elif event.kind == "author_continue":
        _author_continue(model, activation, event)
    elif event.kind == "suffix_replan":
        _suffix_replan(model, activation, event)
    elif event.kind == "author_stop":
        _author_stop(model, activation, event)
    elif event.kind == "downstream_blocker":
        _downstream_blocker(model, activation, event)
    else:  # pragma: no cover - event class has a closed kind set
        raise PlanError("declaration: unsupported lifecycle event")


def _projection(
    activation: PlanActivation, events: tuple[LifecycleEvent, ...]
) -> RuntimeProjection:
    model = _initial_model(activation)
    for event in events:
        _apply_event(model, activation, event)
    deposited = activation.escrow.deposited_wea
    escrow = ProgramEscrow(
        escrow_id=activation.escrow.escrow_id,
        plan_id=activation.escrow.plan_id,
        payer_agent_id=activation.escrow.payer_agent_id,
        deposited_wea=deposited,
        paid_wea=model.escrow_paid,
        refunded_wea=model.escrow_refunded,
        status=(
            "closed"
            if model.plan_status in {"completed", "stopped"}
            or model.escrow_paid + model.escrow_refunded == deposited
            else "active"
        ),
    )
    return RuntimeProjection(
        plan_id=activation.plan.plan_id,
        plan_status=model.plan_status,
        current_stage_index=model.current_stage_index,
        balances=tuple(
            AccountBalance(key, value) for key, value in sorted(model.balances.items())
        ),
        escrow=escrow,
        stages=tuple(model.stages[index] for index in sorted(model.stages)),
        roles=tuple(model.roles[index] for index in sorted(model.roles)),
        pauses=tuple(model.pauses),
        settlements=tuple(model.settlements),
        releases=tuple(model.releases),
        triage_feedback=tuple(model.triage_feedback),
        future_stages=tuple(model.future_stages),
    )


def project_runtime(state: ResolutionPlanRuntimeState) -> RuntimeProjection:
    if type(state) is not ResolutionPlanRuntimeState:
        raise PlanError("evidence_boundary: runtime state must use exact verified type")
    state._assert_unchanged()
    return _projection(state.activation, state.events)


def _require_issue_body_evidence(
    state: ResolutionPlanRuntimeState,
    projection: RuntimeProjection,
    event: LifecycleEvent,
    github_state: ProtocolState,
) -> None:
    if event.kind not in {"body_pause", "body_resume"}:
        return
    data = thaw_json(event.payload)
    if type(data) is not dict or set(data) != {"issue_revision_id"}:
        raise PlanError(f"declaration: {event.kind} payload has invalid keys")
    revision_id = _text("issue_revision_id", data["issue_revision_id"])
    issue_events = [
        item
        for item in github_state.events
        if item.repository_id == state.activation.draft.repository_id
        and item.object_kind == "issue"
        and item.object_id == state.activation.draft.issue_id
    ]
    matches = [item for item in issue_events if item.revision_id == revision_id]
    if len(matches) != 1:
        raise PlanError("evidence_boundary: exact Issue body revision is missing")
    revision = matches[0]
    if revision != max(issue_events, key=lambda item: item.canonical_order_key):
        raise PlanError("evidence_boundary: Issue body revision is not current")
    if revision.effective_at > event.effective_at:
        raise PlanError("evidence_boundary: Issue body evidence is from the future")
    exact_body = (
        revision.body == state.activation.draft.body
        and revision.content_hash == state.activation.draft.body_hash
    )
    if event.kind == "body_pause":
        if revision.effective_at < state.activation.plan.activated_at or exact_body:
            raise PlanError(
                "evidence_boundary: body pause requires a current changed Issue body"
            )
        return
    pause = next(
        (
            item
            for item in reversed(projection.pauses)
            if item.kind == "body_integrity_pause" and item.ended_at is None
        ),
        None,
    )
    if pause is None or revision.effective_at < pause.started_at or not exact_body:
        raise PlanError(
            "evidence_boundary: body resume requires a current restored Issue body"
        )


def apply_lifecycle_event(
    state: ResolutionPlanRuntimeState,
    event: LifecycleEvent,
    *,
    registry: IdentityRegistry,
    github_state: ProtocolState,
    _verified_runtime_reference: Any,
) -> ResolutionPlanRuntimeState:
    if type(state) is not ResolutionPlanRuntimeState:
        raise PlanError("evidence_boundary: runtime state must use exact verified type")
    state._assert_unchanged()
    if _snapshot_runtime(_verified_runtime_reference) != _verified_runtime():
        raise PlanError("runtime: call does not belong to executor 0.8.0")
    event = _rebuild(event, LifecycleEvent, "lifecycle event")
    github_state = _rebuild_github_state(github_state)
    if event.plan_id != state.activation.plan.plan_id:
        raise PlanError("evidence_boundary: lifecycle event belongs to another Plan")
    if event.effective_at < state.activation.plan.activated_at:
        raise PlanError("evidence_boundary: lifecycle event predates Plan activation")
    _require_github_event(
        github_state,
        repository_id=state.activation.draft.repository_id,
        object_kind="issue_comment",
        object_id=event.source_id,
        revision_id=event.source_revision_id,
        actor_account_id=event.actor_account_id,
        body=event.source_snapshot,
        body_hash=event.source_snapshot_hash,
        effective_at=event.effective_at,
        must_be_latest=True,
    )
    intake_source_revisions = {
        state.activation.draft.issue_revision_id,
        *(item.source_revision_id for item in state.activation.state.plan_revisions),
        *(item.source_revision_id for item in state.activation.state.decisions),
        *(
            source_revision_id
            for item in state.activation.state.triage_assessments
            for source_revision_id in (
                item.assignment_source_revision_id,
                item.source_revision_id,
                item.completion_source_revision_id,
            )
        ),
    }
    if event.source_revision_id in intake_source_revisions:
        raise PlanError("evidence_boundary: source revision is globally single-use")
    for existing in state.events:
        if (
            existing.event_id == event.event_id
            or existing.idempotency_key == event.idempotency_key
        ):
            if existing == event:
                return state
            raise PlanError("evidence_boundary: lifecycle key was reused differently")
        if existing.source_revision_id == event.source_revision_id:
            raise PlanError("evidence_boundary: source revision is globally single-use")
    if state.events and event.order_key <= state.events[-1].order_key:
        raise PlanError("evidence_boundary: lifecycle event must append in exact order")
    current = project_runtime(state)
    _require_issue_body_evidence(state, current, event, github_state)
    _authorize_event(current, state.activation, event, registry)
    candidate_events = (*state.events, event)
    _projection(state.activation, candidate_events)
    return _verified_runtime_state(state.activation, candidate_events)


def next_action(state: ResolutionPlanRuntimeState, actor_agent_id: str) -> NextAction:
    actor_agent_id = _text("actor_agent_id", actor_agent_id)
    projection = project_runtime(state)
    stage = projection.current_stage
    open_pause_kinds = {
        item.kind for item in projection.pauses if item.ended_at is None
    }
    is_author = actor_agent_id == state.activation.plan.author_agent_id
    if projection.plan_status in {"completed", "stopped"}:
        action = f"no action; Plan is {projection.plan_status}"
        boundary = None
    elif "body_integrity_pause" in open_pause_kinds:
        action = (
            "restore the exact Issue body or stop"
            if is_author
            else "wait for exact Issue body restoration"
        )
        boundary = None
    elif projection.plan_status == "paused" and is_author:
        action = "continue, approve a suffix replan, or stop"
        boundary = None
    elif "progression_pause" in open_pause_kinds:
        action = "wait for the author"
        boundary = None
    elif projection.plan_status == "paused" and stage.status != "active":
        action = "wait for the author"
        boundary = None
    else:
        assigned = [
            item
            for item in projection.roles
            if item.assigned_agent_id == actor_agent_id and item.status == "active"
        ]
        if assigned:
            action = "submit the complete assigned-role target set"
            boundary = assigned[-1].effective_due_at
        elif stage.contract.mode == "ranked" and stage.phase == "decision":
            action = (
                "publish the exact Ranked order"
                if is_author
                else "wait for the author decision"
            )
            boundary = _stage_deadline(stage, "author_decision").effective_due_at
        elif stage.contract.mode == "duel" and stage.phase == "join":
            action = (
                "wait for two eligible Duel joins"
                if is_author
                else "join one eligible Duel position"
            )
            boundary = _stage_deadline(stage, "join").effective_due_at
        elif stage.contract.mode == "duel" and stage.phase == "moves":
            number = max((item[0] for item in stage.duel_moves), default=0) + 1
            expected = stage.duel_participants[(number - 1) % 2][0]
            action = (
                "publish the next Duel move"
                if actor_agent_id == expected
                else "wait for the other Duel participant"
            )
            boundary = next(
                item.effective_due_at
                for item in stage.deadlines
                if item.kind == f"move-{number}"
            )
        elif stage.contract.mode == "duel" and stage.phase == "decision":
            action = (
                "publish the exact Duel outcome"
                if is_author
                else "wait for the author decision"
            )
            boundary = _stage_deadline(stage, "author_decision").effective_due_at
        elif is_author:
            action = (
                "accept eligible Work or close the mode"
                if stage.contract.mode in {"flat_pod", "frontier"}
                else "wait for eligible Work or close intake early"
            )
            boundary = (
                stage.birdie_at or _stage_deadline(stage, "intake").effective_due_at
            )
        else:
            action = "submit eligible Work"
            boundary = (
                stage.birdie_at or _stage_deadline(stage, "intake").effective_due_at
            )
    return NextAction(
        plan_id=projection.plan_id,
        stage_key=stage.stage_key,
        contract_id=stage.contract.contract_id,
        depth=stage.contract.depth,
        mode=stage.contract.mode,
        actor_id=actor_agent_id,
        action=action,
        boundary_at=boundary,
    )


__all__ = [
    "LifecycleEvent",
    "NextAction",
    "PauseState",
    "ReleaseInvitation",
    "ResolutionPlanRuntimeState",
    "RoleState",
    "RuntimeProjection",
    "Settlement",
    "StageState",
    "TriageFeedback",
    "WorkRevision",
    "WorkState",
    "apply_lifecycle_event",
    "lifecycle_event_id",
    "make_lifecycle_event",
    "next_action",
    "project_runtime",
    "start_runtime",
    "work_id",
    "work_revision_id",
]
