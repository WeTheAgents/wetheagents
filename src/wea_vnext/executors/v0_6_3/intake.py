"""Draft, Triage, and atomic ordinary Contract activation semantics."""

from __future__ import annotations

import hashlib
import weakref
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_hash, freeze_json, thaw_json
from .identity import (
    Binding,
    IdentityAuthority,
    IdentityError,
    IdentityRegistry,
    authorize_agent,
    authorize_issue_author,
)
from .money import (
    MoneyRuleError,
    best_x_payout_vector,
    duel_outcome_vectors,
    linear_payout_vector,
    pod_payout_vector,
    progressive_payout_vector,
    validate_contract_bank,
    winner_take_all_vector,
)
from .rules import Ruleset, load_ruleset


class IntakeError(ValueError):
    """Raised when a Draft or ordinary Contract transition is invalid."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


_ROUTES = {"direct-pr", "duel", "full-build", "reject", "spec-only"}
_PROFILES = {"direct-pr", "duel", "full-build", "spec-only"}
_WEA_VERIFIER_CAPABILITY: object | None = globals().get("_WEA_VERIFIER_CAPABILITY")


def _state_seal_functions() -> tuple[Any, Any]:
    """Create construction seals without leaving their store module-mutable."""
    seals: dict[int, tuple[weakref.ReferenceType[Any], str]] = {}

    def remember(state: Any, digest: str) -> None:
        identity = id(state)

        def forget(reference: weakref.ReferenceType[Any]) -> None:
            current = seals.get(identity)
            if current is not None and current[0] is reference:
                seals.pop(identity, None)

        reference = weakref.ref(state, forget)
        seals[identity] = (reference, digest)

    def seal(state: Any) -> str | None:
        sealed = seals.get(id(state))
        if sealed is None or sealed[0]() is not state:
            return None
        return sealed[1]

    return remember, seal


_remember_state_seal, _state_seal = _state_seal_functions()
del _state_seal_functions


def _text(field: str, value: object) -> str:
    if type(value) is not str or not value:
        raise IntakeError(field, "must be a non-empty string")
    return value


def _non_negative_int(field: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise IntakeError(field, "must be a non-negative integer WEA value")
    return value


def _positive_int(field: str, value: object) -> int:
    value = _non_negative_int(field, value)
    if value == 0:
        raise IntakeError(field, "must be a positive integer WEA value")
    return value


def _utc(field: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IntakeError(field, "must be timezone-aware")
    offset = value.utcoffset()
    if offset is None:
        raise IntakeError(field, "must be timezone-aware")
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
    return value.isoformat().replace("+00:00", "Z")


def _source_order_key(record: Any) -> tuple[datetime, str, str]:
    """Order immutable GitHub evidence by the protocol's canonical event key."""
    return (record.effective_at, record.comment_id, record.revision_id)


def _hash_text(value: str) -> str:
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise IntakeError("snapshot", "contains a lone Unicode surrogate") from exc
    return hashlib.sha256(raw).hexdigest()


def _hash(field: str, value: object) -> str:
    value = _text(field, value)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise IntakeError(field, "must be a lowercase SHA-256 digest")
    return value


def ordinary_contract_id(issue_id: str) -> str:
    """Return the sole ordinary Contract ID permitted for an Issue."""
    issue_id = _text("issue_id", issue_id)
    return f"contract:{canonical_hash({'issue_id': issue_id})}"


def _task_escrow_id(contract_id: str) -> str:
    return f"task-escrow:{_text('contract_id', contract_id)}"


def triage_role_id(issue_id: str) -> str:
    """Return the permanent pre-Contract Triage role/payment-slot ID."""
    issue_id = _text("issue_id", issue_id)
    return f"triage:{canonical_hash({'issue_id': issue_id})}"


def triage_escrow_id(issue_id: str) -> str:
    """Return the sole treasury escrow ID permitted for an Issue's Triage role."""
    issue_id = _text("issue_id", issue_id)
    return f"triage-escrow:{canonical_hash({'issue_id': issue_id})}"


def _bind_verified_runtime(runtime: Any, verifier_capability: object) -> None:
    """Accept binding only from the manifest verifier; runtime stays verifier-owned."""
    if (
        _WEA_VERIFIER_CAPABILITY is None
        or verifier_capability is not _WEA_VERIFIER_CAPABILITY
    ):
        raise IntakeError("runtime", "binding requires the manifest verifier")
    candidate = tuple(runtime)
    if len(candidate) != 3 or any(type(value) is not str for value in candidate):
        raise IntakeError("runtime", "verified triple must contain exact strings")
    expected_ruleset_hash = (
        "21538935ed5e0b3662589a3f631e8d7220ddc0bc12f7a182cb6c592b7848fa9b"
    )
    if candidate[0] != expected_ruleset_hash:
        raise IntakeError("runtime", "ruleset does not match executor 0.6.3")
    if candidate[1] != "0.6":
        raise IntakeError("runtime", "Tide interface does not match executor 0.6.3")


@dataclass(frozen=True)
class MechanicTerms:
    mechanic: str
    review_fee_wea: int
    payout_vector: tuple[int, ...]
    config: Any

    def __post_init__(self) -> None:
        _text("mechanic", self.mechanic)
        _non_negative_int("review_fee_wea", self.review_fee_wea)
        if not isinstance(self.payout_vector, tuple):
            raise IntakeError("payout_vector", "must be an exact tuple")
        if any(type(amount) is not int or amount < 1 for amount in self.payout_vector):
            raise IntakeError("payout_vector", "must contain positive integer WEA")
        if self.mechanic == "duel" and self.payout_vector:
            raise IntakeError("payout_vector", "duel uses exact outcome vectors")
        if self.mechanic != "duel" and not self.payout_vector:
            raise IntakeError("payout_vector", "cannot be empty")
        object.__setattr__(self, "config", freeze_json(self.config))

    @property
    def bank_wea(self) -> int:
        if self.mechanic == "duel":
            raise IntakeError("bank_wea", "duel bank is defined by the Draft")
        return self.review_fee_wea + sum(self.payout_vector)

    @property
    def config_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "config": thaw_json(self.config),
            "mechanic": self.mechanic,
            "payout_vector": list(self.payout_vector),
            "review_fee_wea": self.review_fee_wea,
        }


@dataclass(frozen=True)
class DraftIssue:
    issue_id: str
    issue_revision_id: str
    creator_github_account_id: str
    author_agent_id: str
    body: str
    bank_wea: int
    profile: str
    terms: MechanicTerms

    def __post_init__(self) -> None:
        for field in (
            "issue_id",
            "issue_revision_id",
            "creator_github_account_id",
            "author_agent_id",
        ):
            _text(field, getattr(self, field))
        _text("body", self.body)
        _positive_int("bank_wea", self.bank_wea)
        if self.profile not in _PROFILES:
            raise IntakeError("profile", "is not an ordinary vNext profile")
        if type(self.terms) is not MechanicTerms:
            raise IntakeError("terms", "must use the verified MechanicTerms record")

    @property
    def body_hash(self) -> str:
        return _hash_text(self.body)

    def to_data(self) -> dict[str, Any]:
        return {
            "author_agent_id": self.author_agent_id,
            "bank_wea": self.bank_wea,
            "body": self.body,
            "body_hash": self.body_hash,
            "creator_github_account_id": self.creator_github_account_id,
            "issue_id": self.issue_id,
            "issue_revision_id": self.issue_revision_id,
            "profile": self.profile,
            "terms": self.terms.to_data(),
        }


@dataclass(frozen=True)
class DraftValidation:
    draft: DraftIssue
    author: IdentityAuthority
    balance_sufficient: bool | None

    @property
    def status(self) -> str:
        return "draft"


@dataclass(frozen=True)
class AccountBalance:
    account_id: str
    amount_wea: int

    def __post_init__(self) -> None:
        _text("account_id", self.account_id)
        _non_negative_int("amount_wea", self.amount_wea)

    def to_data(self) -> dict[str, Any]:
        return {"account_id": self.account_id, "amount_wea": self.amount_wea}


@dataclass(frozen=True)
class Escrow:
    escrow_id: str
    kind: str
    basis_id: str
    source_account_id: str
    refund_agent_id: str | None
    amount_wea: int
    settlement_transition_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("escrow_id", "basis_id", "source_account_id"):
            _text(field, getattr(self, field))
        if self.kind not in {"task", "triage-role"}:
            raise IntakeError("escrow.kind", "is not supported")
        if self.refund_agent_id is not None:
            _text("refund_agent_id", self.refund_agent_id)
        if self.settlement_transition_id is not None:
            _text("settlement_transition_id", self.settlement_transition_id)
        _positive_int("escrow.amount_wea", self.amount_wea)

    def to_data(self) -> dict[str, Any]:
        return {
            "amount_wea": self.amount_wea,
            "basis_id": self.basis_id,
            "escrow_id": self.escrow_id,
            "kind": self.kind,
            "refund_agent_id": self.refund_agent_id,
            "settlement_transition_id": self.settlement_transition_id,
            "source_account_id": self.source_account_id,
        }


@dataclass(frozen=True)
class LedgerTransition:
    transition_id: str
    kind: str
    debit_account_id: str
    credit_account_id: str
    amount_wea: int
    basis_id: str

    def __post_init__(self) -> None:
        for field in (
            "transition_id",
            "debit_account_id",
            "credit_account_id",
            "basis_id",
        ):
            _text(field, getattr(self, field))
        if self.kind not in {
            "contract-bank",
            "triage-payout",
            "triage-treasury",
        }:
            raise IntakeError("ledger.kind", "is not supported")
        _positive_int("ledger.amount_wea", self.amount_wea)

    def to_data(self) -> dict[str, Any]:
        return {
            "amount_wea": self.amount_wea,
            "basis_id": self.basis_id,
            "credit_account_id": self.credit_account_id,
            "debit_account_id": self.debit_account_id,
            "kind": self.kind,
            "transition_id": self.transition_id,
        }


@dataclass(frozen=True)
class TriageRole:
    role_id: str
    issue_id: str
    funding_source: str
    amount_wea: int = 0
    escrow_id: str | None = None

    def __post_init__(self) -> None:
        for field in ("role_id", "issue_id"):
            _text(field, getattr(self, field))
        if self.role_id != triage_role_id(self.issue_id):
            raise IntakeError("role_id", "must be derived from the immutable Issue ID")
        if self.funding_source == "free":
            if self.amount_wea != 0 or self.escrow_id is not None:
                raise IntakeError("funding_source", "free Triage cannot create money")
        elif self.funding_source == "treasury":
            _positive_int("amount_wea", self.amount_wea)
            _text("escrow_id", self.escrow_id)
            if self.escrow_id != triage_escrow_id(self.issue_id):
                raise IntakeError(
                    "escrow_id", "must be derived from the immutable Issue ID"
                )
        else:
            raise IntakeError("funding_source", "must be free or treasury")

    def to_data(self) -> dict[str, Any]:
        return {
            "amount_wea": self.amount_wea,
            "escrow_id": self.escrow_id,
            "funding_source": self.funding_source,
            "issue_id": self.issue_id,
            "role_id": self.role_id,
        }


@dataclass(frozen=True)
class TriageAssignment:
    assignment_id: str
    role_id: str
    generation: int
    reviewer_agent_id: str
    reviewer_github_account_id: str
    reviewer_binding_id: str
    reviewer_binding_version: int
    agent0_github_account_id: str
    agent0_binding_id: str
    agent0_binding_version: int
    comment_id: str
    revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        for field in (
            "assignment_id",
            "role_id",
            "reviewer_agent_id",
            "reviewer_github_account_id",
            "reviewer_binding_id",
            "agent0_github_account_id",
            "agent0_binding_id",
            "comment_id",
            "revision_id",
            "snapshot",
            "idempotency_key",
        ):
            _text(field, getattr(self, field))
        _positive_int("generation", self.generation)
        _positive_int("reviewer_binding_version", self.reviewer_binding_version)
        _positive_int("agent0_binding_version", self.agent0_binding_version)
        _hash("snapshot_hash", self.snapshot_hash)
        if self.snapshot_hash != _hash_text(self.snapshot):
            raise IntakeError(
                "snapshot_hash", "does not match the exact assignment snapshot"
            )
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "agent0_binding_id": self.agent0_binding_id,
            "agent0_binding_version": self.agent0_binding_version,
            "agent0_github_account_id": self.agent0_github_account_id,
            "assignment_id": self.assignment_id,
            "comment_id": self.comment_id,
            "effective_at": _timestamp(self.effective_at),
            "generation": self.generation,
            "idempotency_key": self.idempotency_key,
            "reviewer_agent_id": self.reviewer_agent_id,
            "reviewer_binding_id": self.reviewer_binding_id,
            "reviewer_binding_version": self.reviewer_binding_version,
            "reviewer_github_account_id": self.reviewer_github_account_id,
            "revision_id": self.revision_id,
            "role_id": self.role_id,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
        }


@dataclass(frozen=True)
class TriageRecord:
    role_id: str
    assignment_generation: int
    reviewer_agent_id: str
    reviewer_github_account_id: str
    reviewer_binding_id: str
    reviewer_binding_version: int
    issue_id: str
    issue_revision_id: str
    body_hash: str
    route: str
    risks: tuple[str, ...]
    comment_id: str
    revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "role_id",
            "reviewer_agent_id",
            "reviewer_github_account_id",
            "reviewer_binding_id",
            "issue_id",
            "issue_revision_id",
            "comment_id",
            "revision_id",
            "snapshot",
        ):
            _text(field, getattr(self, field))
        _positive_int("assignment_generation", self.assignment_generation)
        _positive_int("reviewer_binding_version", self.reviewer_binding_version)
        _hash("body_hash", self.body_hash)
        _hash("snapshot_hash", self.snapshot_hash)
        if self.snapshot_hash != _hash_text(self.snapshot):
            raise IntakeError(
                "snapshot_hash", "does not match the exact Triage snapshot"
            )
        if self.route not in _ROUTES:
            raise IntakeError("route", "is not a supported Triage route")
        if not isinstance(self.risks, tuple) or any(
            type(item) is not str for item in self.risks
        ):
            raise IntakeError("risks", "must be an exact tuple of strings")
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "body_hash": self.body_hash,
            "assignment_generation": self.assignment_generation,
            "comment_id": self.comment_id,
            "effective_at": _timestamp(self.effective_at),
            "issue_id": self.issue_id,
            "issue_revision_id": self.issue_revision_id,
            "reviewer_agent_id": self.reviewer_agent_id,
            "reviewer_binding_id": self.reviewer_binding_id,
            "reviewer_binding_version": self.reviewer_binding_version,
            "reviewer_github_account_id": self.reviewer_github_account_id,
            "revision_id": self.revision_id,
            "risks": list(self.risks),
            "role_id": self.role_id,
            "route": self.route,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
        }


@dataclass(frozen=True)
class TriageCompletion:
    completion_id: str
    role_id: str
    assignment_generation: int
    triage_revision_id: str
    reviewer_agent_id: str
    agent0_github_account_id: str
    agent0_binding_id: str
    agent0_binding_version: int
    comment_id: str
    revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime
    idempotency_key: str

    def __post_init__(self) -> None:
        for field in (
            "completion_id",
            "role_id",
            "triage_revision_id",
            "reviewer_agent_id",
            "agent0_github_account_id",
            "agent0_binding_id",
            "comment_id",
            "revision_id",
            "snapshot",
            "idempotency_key",
        ):
            _text(field, getattr(self, field))
        _positive_int("assignment_generation", self.assignment_generation)
        _positive_int("agent0_binding_version", self.agent0_binding_version)
        _hash("snapshot_hash", self.snapshot_hash)
        if self.snapshot_hash != _hash_text(self.snapshot):
            raise IntakeError(
                "snapshot_hash", "does not match the exact completion snapshot"
            )
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "agent0_binding_id": self.agent0_binding_id,
            "agent0_binding_version": self.agent0_binding_version,
            "agent0_github_account_id": self.agent0_github_account_id,
            "assignment_generation": self.assignment_generation,
            "comment_id": self.comment_id,
            "completion_id": self.completion_id,
            "effective_at": _timestamp(self.effective_at),
            "idempotency_key": self.idempotency_key,
            "reviewer_agent_id": self.reviewer_agent_id,
            "revision_id": self.revision_id,
            "role_id": self.role_id,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "triage_revision_id": self.triage_revision_id,
        }


@dataclass(frozen=True)
class RouteOverride:
    override_id: str
    issue_id: str
    triage_role_id: str
    triage_revision_id: str
    triage_snapshot_hash: str
    original_route: str
    new_route: str
    reason: str
    operator_github_account_id: str
    operator_binding_id: str
    operator_binding_version: int
    comment_id: str
    revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime

    def __post_init__(self) -> None:
        for field in (
            "override_id",
            "issue_id",
            "triage_role_id",
            "triage_revision_id",
            "reason",
            "operator_github_account_id",
            "operator_binding_id",
            "comment_id",
            "revision_id",
            "snapshot",
        ):
            _text(field, getattr(self, field))
        _hash("triage_snapshot_hash", self.triage_snapshot_hash)
        _hash("snapshot_hash", self.snapshot_hash)
        _positive_int("operator_binding_version", self.operator_binding_version)
        if self.snapshot_hash != _hash_text(self.snapshot):
            raise IntakeError(
                "snapshot_hash", "does not match the exact override snapshot"
            )
        if self.original_route not in _ROUTES or self.new_route not in _PROFILES:
            raise IntakeError("route", "override routes are invalid")
        if self.original_route == self.new_route:
            raise IntakeError("new_route", "must differ from the Triage route")
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "effective_at": _timestamp(self.effective_at),
            "issue_id": self.issue_id,
            "new_route": self.new_route,
            "operator_binding_id": self.operator_binding_id,
            "operator_binding_version": self.operator_binding_version,
            "operator_github_account_id": self.operator_github_account_id,
            "original_route": self.original_route,
            "override_id": self.override_id,
            "reason": self.reason,
            "revision_id": self.revision_id,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "triage_revision_id": self.triage_revision_id,
            "triage_role_id": self.triage_role_id,
            "triage_snapshot_hash": self.triage_snapshot_hash,
        }


@dataclass(frozen=True)
class AuthorConsent:
    consent_id: str
    author_agent_id: str
    github_account_id: str
    account_binding_id: str
    account_binding_version: int
    comment_id: str
    revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime
    issue_id: str
    issue_revision_id: str
    body_hash: str
    bank_wea: int
    profile: str
    mechanic: str
    mechanic_config_hash: str
    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str
    triage_role_id: str
    triage_revision_id: str
    triage_snapshot_hash: str
    route: str
    override_id: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "consent_id",
            "author_agent_id",
            "github_account_id",
            "account_binding_id",
            "comment_id",
            "revision_id",
            "snapshot",
            "issue_id",
            "issue_revision_id",
            "profile",
            "mechanic",
            "tide_interface_version",
            "triage_role_id",
            "triage_revision_id",
        ):
            _text(field, getattr(self, field))
        _positive_int("account_binding_version", self.account_binding_version)
        _positive_int("bank_wea", self.bank_wea)
        for field in (
            "snapshot_hash",
            "body_hash",
            "mechanic_config_hash",
            "ruleset_hash",
            "executor_manifest_hash",
            "triage_snapshot_hash",
        ):
            _hash(field, getattr(self, field))
        if self.snapshot_hash != _hash_text(self.snapshot):
            raise IntakeError(
                "snapshot_hash", "does not match the exact consent snapshot"
            )
        if self.route not in _PROFILES:
            raise IntakeError("route", "is not an activatable profile")
        if self.override_id is not None:
            _text("override_id", self.override_id)
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "account_binding_id": self.account_binding_id,
            "account_binding_version": self.account_binding_version,
            "author_agent_id": self.author_agent_id,
            "bank_wea": self.bank_wea,
            "body_hash": self.body_hash,
            "comment_id": self.comment_id,
            "consent_id": self.consent_id,
            "effective_at": _timestamp(self.effective_at),
            "executor_manifest_hash": self.executor_manifest_hash,
            "github_account_id": self.github_account_id,
            "issue_id": self.issue_id,
            "issue_revision_id": self.issue_revision_id,
            "mechanic": self.mechanic,
            "mechanic_config_hash": self.mechanic_config_hash,
            "override_id": self.override_id,
            "profile": self.profile,
            "revision_id": self.revision_id,
            "route": self.route,
            "ruleset_hash": self.ruleset_hash,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "tide_interface_version": self.tide_interface_version,
            "triage_revision_id": self.triage_revision_id,
            "triage_role_id": self.triage_role_id,
            "triage_snapshot_hash": self.triage_snapshot_hash,
        }


@dataclass(frozen=True)
class ContractReadiness:
    readiness_id: str
    issue_id: str
    agent0_github_account_id: str
    agent0_binding_id: str
    agent0_binding_version: int
    comment_id: str
    revision_id: str
    snapshot: str
    snapshot_hash: str
    effective_at: datetime
    consent_id: str
    consent_revision_id: str
    triage_role_id: str
    triage_revision_id: str
    triage_snapshot_hash: str
    override_id: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "readiness_id",
            "issue_id",
            "agent0_github_account_id",
            "agent0_binding_id",
            "comment_id",
            "revision_id",
            "snapshot",
            "consent_id",
            "consent_revision_id",
            "triage_role_id",
            "triage_revision_id",
        ):
            _text(field, getattr(self, field))
        _hash("snapshot_hash", self.snapshot_hash)
        _hash("triage_snapshot_hash", self.triage_snapshot_hash)
        _positive_int("agent0_binding_version", self.agent0_binding_version)
        if self.snapshot_hash != _hash_text(self.snapshot):
            raise IntakeError(
                "snapshot_hash", "does not match the exact readiness snapshot"
            )
        if self.override_id is not None:
            _text("override_id", self.override_id)
        object.__setattr__(
            self, "effective_at", _utc("effective_at", self.effective_at)
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "agent0_binding_id": self.agent0_binding_id,
            "agent0_binding_version": self.agent0_binding_version,
            "agent0_github_account_id": self.agent0_github_account_id,
            "comment_id": self.comment_id,
            "consent_id": self.consent_id,
            "consent_revision_id": self.consent_revision_id,
            "effective_at": _timestamp(self.effective_at),
            "issue_id": self.issue_id,
            "override_id": self.override_id,
            "readiness_id": self.readiness_id,
            "revision_id": self.revision_id,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "triage_revision_id": self.triage_revision_id,
            "triage_role_id": self.triage_role_id,
            "triage_snapshot_hash": self.triage_snapshot_hash,
        }


@dataclass(frozen=True)
class ContractCandidate:
    contract_id: str
    draft: DraftIssue
    route: str
    triage_revision_id: str

    def __post_init__(self) -> None:
        _text("contract_id", self.contract_id)
        if type(self.draft) is not DraftIssue:
            raise IntakeError("draft", "must use the verified DraftIssue record")
        if self.route not in _PROFILES:
            raise IntakeError("route", "is not an activatable profile")
        if self.route != self.draft.profile:
            raise IntakeError("route", "must equal the Contract candidate profile")
        _text("triage_revision_id", self.triage_revision_id)
        if self.contract_id != ordinary_contract_id(self.draft.issue_id):
            raise IntakeError("contract_id", "must be derived from the Issue ID")


@dataclass(frozen=True)
class OrdinaryContract:
    contract_id: str
    issue_id: str
    issue_revision_id: str
    body: str
    body_hash: str
    author_agent_id: str
    payer_agent_id: str
    bank_wea: int
    profile: str
    mechanic: str
    mechanic_terms: MechanicTerms
    triage_role_id: str
    triage_revision_id: str
    triage_snapshot_hash: str
    consent_id: str
    consent_revision_id: str
    consent_snapshot_hash: str
    readiness_id: str
    override_id: str | None
    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str

    def __post_init__(self) -> None:
        for field in (
            "contract_id",
            "issue_id",
            "issue_revision_id",
            "body",
            "author_agent_id",
            "payer_agent_id",
            "profile",
            "mechanic",
            "triage_role_id",
            "triage_revision_id",
            "consent_id",
            "consent_revision_id",
            "readiness_id",
            "tide_interface_version",
        ):
            _text(field, getattr(self, field))
        for field in (
            "body_hash",
            "triage_snapshot_hash",
            "consent_snapshot_hash",
            "ruleset_hash",
            "executor_manifest_hash",
        ):
            _hash(field, getattr(self, field))
        if self.body_hash != _hash_text(self.body):
            raise IntakeError("body_hash", "does not match the exact Contract body")
        _positive_int("bank_wea", self.bank_wea)
        if self.profile not in _PROFILES:
            raise IntakeError("profile", "is not an ordinary vNext profile")
        if self.author_agent_id != self.payer_agent_id:
            raise IntakeError("payer_agent_id", "must equal the Contract author")
        if type(self.mechanic_terms) is not MechanicTerms:
            raise IntakeError("mechanic_terms", "must use the verified record type")
        if self.mechanic != self.mechanic_terms.mechanic:
            raise IntakeError("mechanic", "does not match mechanic terms")
        if self.override_id is not None:
            _text("override_id", self.override_id)
        _validate_mechanic_terms(
            profile_name=self.profile,
            bank_wea=self.bank_wea,
            terms=self.mechanic_terms,
            rules=load_ruleset(),
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "author_agent_id": self.author_agent_id,
            "bank_wea": self.bank_wea,
            "body": self.body,
            "body_hash": self.body_hash,
            "consent_id": self.consent_id,
            "consent_revision_id": self.consent_revision_id,
            "consent_snapshot_hash": self.consent_snapshot_hash,
            "contract_id": self.contract_id,
            "executor_manifest_hash": self.executor_manifest_hash,
            "issue_id": self.issue_id,
            "issue_revision_id": self.issue_revision_id,
            "mechanic": self.mechanic,
            "mechanic_terms": self.mechanic_terms.to_data(),
            "override_id": self.override_id,
            "payer_agent_id": self.payer_agent_id,
            "profile": self.profile,
            "readiness_id": self.readiness_id,
            "ruleset_hash": self.ruleset_hash,
            "tide_interface_version": self.tide_interface_version,
            "triage_revision_id": self.triage_revision_id,
            "triage_role_id": self.triage_role_id,
            "triage_snapshot_hash": self.triage_snapshot_hash,
        }


@dataclass(frozen=True)
class Task:
    task_id: str
    contract_id: str
    profile: str
    stage: str
    status: str = "active"

    def __post_init__(self) -> None:
        for field in ("task_id", "contract_id", "profile", "stage"):
            _text(field, getattr(self, field))
        if self.profile not in _PROFILES:
            raise IntakeError("task.profile", "is not supported")
        if self.status != "active":
            raise IntakeError("task.status", "new ordinary Task must be active")

    def to_data(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "profile": self.profile,
            "stage": self.stage,
            "status": self.status,
            "task_id": self.task_id,
        }


@dataclass(frozen=True)
class IntakeState:
    balances: tuple[AccountBalance, ...] = ()
    triage_roles: tuple[TriageRole, ...] = ()
    triage_assignments: tuple[TriageAssignment, ...] = ()
    triages: tuple[TriageRecord, ...] = ()
    triage_completions: tuple[TriageCompletion, ...] = ()
    overrides: tuple[RouteOverride, ...] = ()
    consents: tuple[AuthorConsent, ...] = ()
    readiness: tuple[ContractReadiness, ...] = ()
    contracts: tuple[OrdinaryContract, ...] = ()
    tasks: tuple[Task, ...] = ()
    escrows: tuple[Escrow, ...] = ()
    ledger: tuple[LedgerTransition, ...] = ()

    def __post_init__(
        self,
        _remember_seal: Any = _remember_state_seal,  # noqa: RUF033
    ) -> None:
        collections = (
            (self.balances, AccountBalance, "account_id"),
            (self.triage_roles, TriageRole, "role_id"),
            (self.triage_assignments, TriageAssignment, "assignment_id"),
            (self.triages, TriageRecord, "revision_id"),
            (self.triage_completions, TriageCompletion, "completion_id"),
            (self.overrides, RouteOverride, "override_id"),
            (self.consents, AuthorConsent, "consent_id"),
            (self.readiness, ContractReadiness, "readiness_id"),
            (self.contracts, OrdinaryContract, "contract_id"),
            (self.tasks, Task, "task_id"),
            (self.escrows, Escrow, "escrow_id"),
            (self.ledger, LedgerTransition, "transition_id"),
        )
        for records, record_type, key in collections:
            if not isinstance(records, tuple) or any(
                type(item) is not record_type for item in records
            ):
                raise IntakeError(key, "state contains a foreign record")
            values = [getattr(item, key) for item in records]
            if values != sorted(values) or len(values) != len(set(values)):
                raise IntakeError(key, "state records must be unique and sorted")
        balance_account_ids = {item.account_id for item in self.balances}
        escrow_ids = {item.escrow_id for item in self.escrows}
        if balance_account_ids & escrow_ids:
            raise IntakeError("escrow_id", "cannot collide with a balance account")
        self._validate_activation_groups()
        _remember_seal(self, canonical_hash(self.to_data()))

    def _assert_unchanged(self, _get_seal: Any = _state_seal) -> None:
        if _get_seal(self) != canonical_hash(self.to_data()):
            raise IntakeError("state", "changed after validation")

    def _validate_activation_groups(self) -> None:
        role_issues = [item.issue_id for item in self.triage_roles]
        if len(role_issues) != len(set(role_issues)):
            raise IntakeError("triage role", "each Issue has one permanent role")
        roles = {item.role_id: item for item in self.triage_roles}
        role_ids = set(roles)
        assignment_keys = [
            (item.role_id, item.generation) for item in self.triage_assignments
        ]
        if len(assignment_keys) != len(set(assignment_keys)):
            raise IntakeError("triage assignment", "generation must be unique")
        source_records = (
            *self.triage_assignments,
            *self.triages,
            *self.triage_completions,
            *self.overrides,
            *self.consents,
            *self.readiness,
        )
        source_revisions = [
            (item.comment_id, item.revision_id) for item in source_records
        ]
        if len(source_revisions) != len(set(source_revisions)):
            raise IntakeError(
                "source revision", "must authorize at most one intake record"
            )
        if any(item.role_id not in role_ids for item in self.triage_assignments):
            raise IntakeError("triage assignment", "must belong to a role")
        assignments = {
            (item.role_id, item.generation): item for item in self.triage_assignments
        }
        for role_id in role_ids:
            role_assignments = sorted(
                (item for item in self.triage_assignments if item.role_id == role_id),
                key=lambda item: item.generation,
            )
            if [item.generation for item in role_assignments] != list(
                range(1, len(role_assignments) + 1)
            ):
                raise IntakeError("triage assignment", "generations must be contiguous")
            for current in role_assignments[1:]:
                previous_generation = current.generation - 1
                previous_triages = [
                    item
                    for item in self.triages
                    if item.role_id == role_id
                    and item.assignment_generation == previous_generation
                ]
                completed_revisions = {
                    item.triage_revision_id
                    for item in self.triage_completions
                    if item.role_id == role_id
                    and item.assignment_generation == previous_generation
                }
                if not previous_triages or any(
                    item.revision_id not in completed_revisions
                    for item in previous_triages
                ):
                    raise IntakeError(
                        "triage assignment",
                        "prior generation must be terminal before reassignment",
                    )
                prior_evidence_keys: list[tuple[datetime, str, str]] = []
                for item in (
                    *role_assignments,
                    *self.triages,
                    *self.triage_completions,
                ):
                    evidence_generation = (
                        item.generation
                        if isinstance(item, TriageAssignment)
                        else item.assignment_generation
                    )
                    if (
                        item.role_id == role_id
                        and evidence_generation < current.generation
                    ):
                        prior_evidence_keys.append(_source_order_key(item))
                if prior_evidence_keys and _source_order_key(current) <= max(
                    prior_evidence_keys
                ):
                    raise IntakeError(
                        "triage assignment",
                        "new generation must follow all prior role evidence",
                    )
        for triage in self.triages:
            assignment = assignments.get((triage.role_id, triage.assignment_generation))
            if assignment is None or (
                roles[triage.role_id].issue_id != triage.issue_id
                or assignment.reviewer_agent_id != triage.reviewer_agent_id
                or assignment.reviewer_github_account_id
                != triage.reviewer_github_account_id
                or assignment.reviewer_binding_id != triage.reviewer_binding_id
                or assignment.reviewer_binding_version
                != triage.reviewer_binding_version
                or _source_order_key(assignment) > _source_order_key(triage)
            ):
                raise IntakeError("Triage", "must belong to its exact assignment")
        idempotency_keys = [
            item.idempotency_key
            for item in (*self.triage_assignments, *self.triage_completions)
        ]
        if len(idempotency_keys) != len(set(idempotency_keys)):
            raise IntakeError("idempotency_key", "must be globally unique")
        completed_revisions = [
            item.triage_revision_id for item in self.triage_completions
        ]
        if len(completed_revisions) != len(set(completed_revisions)):
            raise IntakeError(
                "triage_revision_id", "each Triage revision completes at most once"
            )
        for completion in self.triage_completions:
            assignment = assignments.get(
                (completion.role_id, completion.assignment_generation)
            )
            triages = [
                item
                for item in self.triages
                if item.revision_id == completion.triage_revision_id
            ]
            if (
                assignment is None
                or len(triages) != 1
                or triages[0].role_id != completion.role_id
                or triages[0].assignment_generation != completion.assignment_generation
                or assignment.reviewer_agent_id != completion.reviewer_agent_id
                or _source_order_key(completion) < _source_order_key(triages[0])
            ):
                raise IntakeError("triage completion", "evidence does not match")
        contracts = {item.contract_id: item for item in self.contracts}
        for field, values in (
            ("issue_id", [item.issue_id for item in self.contracts]),
            ("consent_id", [item.consent_id for item in self.contracts]),
            ("readiness_id", [item.readiness_id for item in self.contracts]),
        ):
            if len(values) != len(set(values)):
                raise IntakeError(field, "cannot activate more than one Contract")
        if any(
            item.contract_id != ordinary_contract_id(item.issue_id)
            for item in self.contracts
        ):
            raise IntakeError("contract_id", "must be derived from the Issue ID")
        task_contracts = {item.contract_id for item in self.tasks}
        escrow_contracts = {
            item.basis_id for item in self.escrows if item.kind == "task"
        }
        debit_contracts = {
            item.basis_id for item in self.ledger if item.kind == "contract-bank"
        }
        contract_ids = set(contracts)
        if not (contract_ids == task_contracts == escrow_contracts == debit_contracts):
            raise IntakeError(
                "activation", "Contract, Task, task escrow, and debit must be atomic"
            )
        for contract_id, contract in contracts.items():
            tasks = [item for item in self.tasks if item.contract_id == contract_id]
            escrows = [
                item
                for item in self.escrows
                if item.kind == "task" and item.basis_id == contract_id
            ]
            debits = [
                item
                for item in self.ledger
                if item.kind == "contract-bank" and item.basis_id == contract_id
            ]
            if not (len(tasks) == len(escrows) == len(debits) == 1):
                raise IntakeError("activation", "must contain one complete group")
            if (
                tasks[0].task_id != f"task:{contract_id}"
                or debits[0].transition_id != f"contract-bank:{contract_id}"
                or escrows[0].escrow_id != _task_escrow_id(contract_id)
                or escrows[0].amount_wea != contract.bank_wea
                or debits[0].amount_wea != contract.bank_wea
                or escrows[0].refund_agent_id != contract.author_agent_id
                or escrows[0].source_account_id != contract.payer_agent_id
                or escrows[0].settlement_transition_id is not None
                or debits[0].debit_account_id != contract.author_agent_id
                or debits[0].debit_account_id != escrows[0].source_account_id
                or debits[0].credit_account_id != escrows[0].escrow_id
            ):
                raise IntakeError("activation", "money does not match the Contract")
            consent = [
                item for item in self.consents if item.consent_id == contract.consent_id
            ]
            readiness = [
                item
                for item in self.readiness
                if item.readiness_id == contract.readiness_id
            ]
            triage = [
                item
                for item in self.triages
                if item.revision_id == contract.triage_revision_id
            ]
            if not (len(consent) == len(readiness) == len(triage) == 1):
                raise IntakeError("activation", "evidence must resolve exactly once")
            completions = [
                item
                for item in self.triage_completions
                if item.role_id == contract.triage_role_id
                and item.triage_revision_id == contract.triage_revision_id
            ]
            if len(completions) != 1:
                raise IntakeError("activation", "completed Triage evidence is missing")
            consent_record = consent[0]
            readiness_record = readiness[0]
            triage_record = triage[0]
            completion_record = completions[0]
            evidence_matches = (
                contract.issue_id
                == consent_record.issue_id
                == readiness_record.issue_id
                == triage_record.issue_id
                and contract.issue_revision_id
                == consent_record.issue_revision_id
                == triage_record.issue_revision_id
                and contract.body_hash
                == consent_record.body_hash
                == triage_record.body_hash
                and contract.author_agent_id == consent_record.author_agent_id
                and contract.payer_agent_id == consent_record.author_agent_id
                and contract.bank_wea == consent_record.bank_wea
                and contract.profile == consent_record.profile == consent_record.route
                and contract.mechanic == consent_record.mechanic
                and contract.mechanic_terms.config_hash
                == consent_record.mechanic_config_hash
                and contract.ruleset_hash == consent_record.ruleset_hash
                and contract.tide_interface_version
                == consent_record.tide_interface_version
                and contract.executor_manifest_hash
                == consent_record.executor_manifest_hash
                and consent_record.revision_id == contract.consent_revision_id
                and consent_record.snapshot_hash == contract.consent_snapshot_hash
                and consent_record.triage_role_id
                == readiness_record.triage_role_id
                == triage_record.role_id
                == contract.triage_role_id
                and consent_record.triage_revision_id
                == readiness_record.triage_revision_id
                == triage_record.revision_id
                == contract.triage_revision_id
                and consent_record.triage_snapshot_hash
                == readiness_record.triage_snapshot_hash
                == triage_record.snapshot_hash
                == contract.triage_snapshot_hash
                and readiness_record.consent_id == contract.consent_id
                and readiness_record.consent_revision_id == consent_record.revision_id
                and readiness_record.override_id
                == consent_record.override_id
                == contract.override_id
                and _source_order_key(triage_record)
                <= _source_order_key(completion_record)
                <= _source_order_key(consent_record)
                <= _source_order_key(readiness_record)
            )
            if not evidence_matches:
                raise IntakeError("activation", "evidence does not match the Contract")
            if contract.override_id is None:
                if triage_record.route != contract.profile:
                    raise IntakeError(
                        "activation", "Triage route does not match Contract"
                    )
            else:
                overrides = [
                    item
                    for item in self.overrides
                    if item.override_id == contract.override_id
                ]
                if len(overrides) != 1:
                    raise IntakeError("activation", "operator override is missing")
                override = overrides[0]
                if not (
                    override.issue_id == contract.issue_id
                    and override.triage_role_id == triage_record.role_id
                    and override.triage_revision_id == triage_record.revision_id
                    and override.triage_snapshot_hash == triage_record.snapshot_hash
                    and override.original_route == triage_record.route
                    and override.new_route == contract.profile
                    and _source_order_key(override) < _source_order_key(consent_record)
                ):
                    raise IntakeError("activation", "operator override does not match")
            first_stage = load_ruleset().content["profiles"][contract.profile][
                "stages"
            ][0]
            if tasks[0].profile != contract.profile or tasks[0].stage != first_stage:
                raise IntakeError("activation", "Task does not match the Contract")
        triage_escrow_records = [
            item for item in self.escrows if item.kind == "triage-role"
        ]
        triage_debit_records = [
            item for item in self.ledger if item.kind == "triage-treasury"
        ]
        triage_payout_records = [
            item for item in self.ledger if item.kind == "triage-payout"
        ]
        triage_escrows = {item.basis_id: item for item in triage_escrow_records}
        triage_debits = {item.basis_id: item for item in triage_debit_records}
        triage_payouts = {item.basis_id: item for item in triage_payout_records}
        if len(triage_escrows) != len(triage_escrow_records) or len(
            triage_debits
        ) != len(triage_debit_records):
            raise IntakeError("triage funding", "must contain one group per role")
        if len(triage_payouts) != len(triage_payout_records):
            raise IntakeError("triage payout", "must occur at most once per role")
        if not (
            set(triage_escrows) <= role_ids
            and set(triage_debits) <= role_ids
            and set(triage_payouts) <= role_ids
        ):
            raise IntakeError("triage funding", "cannot exist without its role")
        for role in self.triage_roles:
            escrow = triage_escrows.get(role.role_id)
            debit = triage_debits.get(role.role_id)
            payout = triage_payouts.get(role.role_id)
            completions = [
                item for item in self.triage_completions if item.role_id == role.role_id
            ]
            completed = bool(completions)
            if role.funding_source == "free":
                if escrow is not None or debit is not None or payout is not None:
                    raise IntakeError("triage funding", "free role cannot move money")
                continue
            if escrow is None or debit is None:
                raise IntakeError("triage funding", "treasury role must be atomic")
            if (
                escrow.escrow_id != role.escrow_id
                or escrow.amount_wea != role.amount_wea
                or debit.amount_wea != role.amount_wea
                or debit.debit_account_id != "treasury"
                or escrow.source_account_id != "treasury"
                or debit.debit_account_id != escrow.source_account_id
                or debit.credit_account_id != escrow.escrow_id
            ):
                raise IntakeError("triage funding", "does not match its role")
            if completed:
                first_completion = min(
                    completions,
                    key=_source_order_key,
                )
                if payout is None or (
                    escrow.settlement_transition_id != payout.transition_id
                    or payout.debit_account_id != escrow.escrow_id
                    or payout.credit_account_id != first_completion.reviewer_agent_id
                    or payout.amount_wea != role.amount_wea
                ):
                    raise IntakeError("triage payout", "does not match completion")
            elif payout is not None or escrow.settlement_transition_id is not None:
                raise IntakeError("triage payout", "cannot precede completion")

    def balance(self, account_id: str) -> int:
        matches = [
            item.amount_wea for item in self.balances if item.account_id == account_id
        ]
        if len(matches) != 1:
            raise IntakeError("balance", "account must resolve exactly once")
        return matches[0]

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "balances": [item.to_data() for item in self.balances],
            "consents": [item.to_data() for item in self.consents],
            "contracts": [item.to_data() for item in self.contracts],
            "escrows": [item.to_data() for item in self.escrows],
            "ledger": [item.to_data() for item in self.ledger],
            "overrides": [item.to_data() for item in self.overrides],
            "readiness": [item.to_data() for item in self.readiness],
            "tasks": [item.to_data() for item in self.tasks],
            "triage_assignments": [item.to_data() for item in self.triage_assignments],
            "triage_completions": [item.to_data() for item in self.triage_completions],
            "triage_roles": [item.to_data() for item in self.triage_roles],
            "triages": [item.to_data() for item in self.triages],
        }


del _remember_state_seal, _state_seal


@dataclass(frozen=True)
class ContractActivation:
    state: IntakeState
    contract: OrdinaryContract
    task: Task
    escrow: Escrow
    debit: LedgerTransition
    created: bool


_STATE_COLLECTIONS = (
    ("balances", AccountBalance),
    ("triage_roles", TriageRole),
    ("triage_assignments", TriageAssignment),
    ("triages", TriageRecord),
    ("triage_completions", TriageCompletion),
    ("overrides", RouteOverride),
    ("consents", AuthorConsent),
    ("readiness", ContractReadiness),
    ("contracts", OrdinaryContract),
    ("tasks", Task),
    ("escrows", Escrow),
    ("ledger", LedgerTransition),
)


def _rebuild_mechanic_terms(terms: MechanicTerms) -> MechanicTerms:
    if type(terms) is not MechanicTerms:
        raise IntakeError("mechanic_terms", "must use the verified record type")
    try:
        return MechanicTerms(
            mechanic=terms.mechanic,
            review_fee_wea=terms.review_fee_wea,
            payout_vector=terms.payout_vector,
            config=thaw_json(terms.config),
        )
    except (AttributeError, TypeError) as exc:
        raise IntakeError("mechanic_terms", "record is malformed") from exc


def _rebuild_draft(draft: DraftIssue) -> DraftIssue:
    if type(draft) is not DraftIssue:
        raise IntakeError("draft", "must use the verified DraftIssue record")
    try:
        return replace(draft, terms=_rebuild_mechanic_terms(draft.terms))
    except (AttributeError, TypeError) as exc:
        raise IntakeError("draft", "record is malformed") from exc


def _rebuild_candidate(candidate: ContractCandidate) -> ContractCandidate:
    if type(candidate) is not ContractCandidate:
        raise IntakeError("activation", "requires a verified Contract candidate")
    try:
        return replace(candidate, draft=_rebuild_draft(candidate.draft))
    except (AttributeError, TypeError) as exc:
        raise IntakeError("activation", "Contract candidate is malformed") from exc


def _rebuild_state_record(record: Any, record_type: type[Any]) -> Any:
    if type(record) is not record_type:
        raise IntakeError("state", "contains a foreign record")
    try:
        if record_type is OrdinaryContract:
            return replace(
                record,
                mechanic_terms=_rebuild_mechanic_terms(record.mechanic_terms),
            )
        return replace(record)
    except (AttributeError, TypeError) as exc:
        raise IntakeError("state", "contains a malformed record") from exc


def _rebuild_transition_record(record: Any, record_type: type[Any], field: str) -> Any:
    """Reconstruct one caller-owned transition record through its validator."""
    if type(record) is not record_type:
        raise IntakeError(field, "must use the verified record type")
    try:
        return replace(record)
    except IntakeError:
        raise
    except (AttributeError, TypeError) as exc:
        raise IntakeError(field, "record is malformed") from exc


def _validated_state(state: IntakeState) -> IntakeState:
    """Detach and revalidate state while rejecting mutation after construction."""
    if type(state) is not IntakeState:
        raise IntakeError("state", "must use the verified IntakeState record")
    try:
        state._assert_unchanged()
        values = {
            name: tuple(
                _rebuild_state_record(record, record_type)
                for record in getattr(state, name)
            )
            for name, record_type in _STATE_COLLECTIONS
        }
        return IntakeState(**values)
    except IntakeError:
        raise
    except (AttributeError, TypeError) as exc:
        raise IntakeError("state", "record is malformed") from exc


def _validated_registry(registry: IdentityRegistry) -> IdentityRegistry:
    """Detach identity evidence and enforce its construction-time snapshot."""
    if type(registry) is not IdentityRegistry:
        raise IntakeError("registry", "must use the verified IdentityRegistry")
    try:
        registry._assert_unchanged()
        return IdentityRegistry(
            accounts=tuple(replace(item) for item in registry.accounts),
            bindings=tuple(replace(item) for item in registry.bindings),
            control_group_bindings=tuple(
                replace(item) for item in registry.control_group_bindings
            ),
        )
    except (IdentityError, AttributeError, TypeError) as exc:
        raise IntakeError("registry", str(exc)) from exc


def _replace_balance(
    state: IntakeState, account_id: str, amount_wea: int
) -> tuple[AccountBalance, ...]:
    replacement = AccountBalance(account_id, amount_wea)
    return tuple(
        sorted(
            (
                replacement if item.account_id == account_id else item
                for item in state.balances
            ),
            key=lambda item: item.account_id,
        )
    )


def _credit_balance(
    state: IntakeState,
    account_id: str,
    amount_wea: int,
) -> tuple[AccountBalance, ...]:
    matches = [item for item in state.balances if item.account_id == account_id]
    if len(matches) > 1:
        raise IntakeError("balance", "account must resolve at most once")
    current = 0 if not matches else matches[0].amount_wea
    credited = AccountBalance(
        account_id, current + _positive_int("amount_wea", amount_wea)
    )
    if matches:
        return _replace_balance(state, account_id, credited.amount_wea)
    return tuple(sorted((*state.balances, credited), key=lambda item: item.account_id))


def _append(records: tuple[Any, ...], record: Any, key: str) -> tuple[Any, ...]:
    return tuple(sorted((*records, record), key=lambda item: getattr(item, key)))


def _validate_mechanic_terms(
    *,
    profile_name: str,
    bank_wea: int,
    terms: MechanicTerms,
    rules: Ruleset,
) -> None:
    profile = rules.content["profiles"][profile_name]
    config = thaw_json(terms.config)
    if not isinstance(config, dict):
        raise IntakeError("mechanic_config", "must be a JSON object")
    if terms.mechanic not in profile["mechanics"]:
        raise IntakeError("mechanic", "is not allowed by the selected profile")
    if profile_name == "duel" or terms.mechanic == "duel":
        if profile_name != "duel" or terms.mechanic != "duel":
            raise IntakeError("mechanic", "duel profile and mechanic must match")
        if terms.review_fee_wea != 0:
            raise IntakeError("review_fee_wea", "duel has no task-bank review fee")
        if set(config) != {"outcome_vectors"}:
            raise IntakeError("mechanic_config", "Duel config keys must be exact")
        try:
            vectors = duel_outcome_vectors(bank_wea)
        except MoneyRuleError as exc:
            raise IntakeError("bank_wea", str(exc)) from exc
        expected_vectors = {
            outcome: {
                "payout_vector": list(payouts),
                "refund_wea": refund,
            }
            for outcome, (payouts, refund) in vectors.items()
        }
        if config.get("outcome_vectors") != expected_vectors:
            raise IntakeError(
                "mechanic_config.outcome_vectors",
                "does not match the exact Duel bank",
            )
        return
    additional = config.get("additional_review_stages", [])
    if not isinstance(additional, list) or any(
        not isinstance(item, dict) for item in additional
    ):
        raise IntakeError(
            "mechanic_config.additional_review_stages",
            "must be a list of exact stage objects",
        )
    stage_ids: list[str] = []
    for stage in additional:
        expected_stage_keys = {
            "duration_seconds",
            "extension_point",
            "on_approved_stage",
            "on_changes_stage",
            "stage_id",
            "targets",
        }
        if set(stage) != expected_stage_keys:
            raise IntakeError("additional_review_stage", "keys must be exact")
        stage_id = _text("additional_review_stage.stage_id", stage["stage_id"])
        stage_ids.append(stage_id)
        extension_point = _text(
            "additional_review_stage.extension_point", stage["extension_point"]
        )
        if extension_point not in profile["extension_points"]:
            raise IntakeError(
                "additional_review_stage.extension_point",
                "is not allowed by the profile",
            )
        base_stage = extension_point.removeprefix("after-")
        expected_exits = {
            event: destination
            for source, event, destination in rules.content["transitions"][profile_name]
            if source == base_stage and event in {"review-approved", "review-changes"}
        }
        if set(expected_exits) != {"review-approved", "review-changes"}:
            raise IntakeError(
                "additional_review_stage.extension_point",
                "does not identify a complete versioned review transition",
            )
        _positive_int(
            "additional_review_stage.duration_seconds", stage["duration_seconds"]
        )
        targets = stage["targets"]
        if (
            not isinstance(targets, list)
            or not targets
            or any(type(item) is not str or not item for item in targets)
        ):
            raise IntakeError(
                "additional_review_stage.targets", "must be a non-empty string list"
            )
        for outcome, event in (
            ("on_approved_stage", "review-approved"),
            ("on_changes_stage", "review-changes"),
        ):
            if stage[outcome] != expected_exits[event]:
                raise IntakeError(
                    f"additional_review_stage.{outcome}",
                    "must match the extension point's versioned transition",
                )
        if stage_id in profile["stages"]:
            raise IntakeError(
                "additional_review_stage.stage_id",
                "must not collide with a profile stage",
            )
    if len(stage_ids) != len(set(stage_ids)):
        raise IntakeError("additional_review_stage.stage_id", "must be unique")
    required_keys = {
        "best-x": {"mode", "prize_pool_wea", "winners"},
        "linear": {"mode", "slots"},
        "pod": {"mode", "payout_wea", "slots"},
        "progressive": {"mode", "slots"},
        "winner-take-all": {"mode", "prize_pool_wea"},
    }[terms.mechanic]
    allowed_keys = required_keys | {"additional_review_stages"}
    if set(config) - allowed_keys or not required_keys <= set(config):
        raise IntakeError("mechanic_config", "keys do not match the mechanic")
    expected_mode = rules.content["mechanics"][terms.mechanic]["mode"]
    if config["mode"] != expected_mode:
        raise IntakeError("mechanic_config.mode", "does not match the ruleset")
    try:
        if terms.mechanic == "pod":
            expected_vector = pod_payout_vector(
                _positive_int("mechanic_config.slots", config["slots"]),
                _positive_int("mechanic_config.payout_wea", config["payout_wea"]),
            )
        elif terms.mechanic == "progressive":
            expected_vector = progressive_payout_vector(
                _positive_int("mechanic_config.slots", config["slots"])
            )
        elif terms.mechanic == "linear":
            expected_vector = linear_payout_vector(
                _positive_int("mechanic_config.slots", config["slots"])
            )
        elif terms.mechanic == "winner-take-all":
            expected_vector = winner_take_all_vector(
                _positive_int(
                    "mechanic_config.prize_pool_wea", config["prize_pool_wea"]
                )
            )
        else:
            expected_vector = best_x_payout_vector(
                _positive_int(
                    "mechanic_config.prize_pool_wea", config["prize_pool_wea"]
                ),
                _positive_int("mechanic_config.winners", config["winners"]),
                rules,
            )
    except MoneyRuleError as exc:
        raise IntakeError("mechanic_config", str(exc)) from exc
    if terms.payout_vector != expected_vector:
        raise IntakeError("payout_vector", "does not match the exact mechanic rules")
    base_review_fee = sum(
        rules.content["review_stages"][stage]["fee_wea"]
        for stage in profile["base_review_stages"]
    )
    if terms.review_fee_wea != base_review_fee + len(additional):
        raise IntakeError(
            "review_fee_wea",
            "does not match the profile and additional review stages",
        )
    try:
        validate_contract_bank(bank_wea, terms.review_fee_wea, terms.payout_vector)
    except MoneyRuleError as exc:
        raise IntakeError("bank_wea", str(exc)) from exc
    if bank_wea != terms.bank_wea:
        raise IntakeError("bank_wea", "does not equal the immutable mechanic terms")


def _validate_draft_core(
    draft: DraftIssue,
    *,
    effective_at: datetime,
    registry: IdentityRegistry,
    runtime: tuple[str, str, str],
    available_balance_wea: int | None = None,
) -> DraftValidation:
    """Validate one source-independent Draft without writing protocol state."""
    draft = _rebuild_draft(draft)
    registry = _validated_registry(registry)
    rules = load_ruleset()
    _validate_mechanic_terms(
        profile_name=draft.profile,
        bank_wea=draft.bank_wea,
        terms=draft.terms,
        rules=rules,
    )
    if runtime[:2] != (rules.content_hash, rules.interface_version):
        raise IntakeError("runtime", "ruleset does not match the verified executor")
    try:
        author = authorize_issue_author(
            author_agent_id=draft.author_agent_id,
            github_account_id=draft.creator_github_account_id,
            effective_at=effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise IntakeError("author_agent_id", str(exc)) from exc
    sufficient = None
    if available_balance_wea is not None:
        sufficient = (
            _non_negative_int("available_balance_wea", available_balance_wea)
            >= draft.bank_wea
        )
    return DraftValidation(draft=draft, author=author, balance_sufficient=sufficient)


def validate_draft(
    draft: DraftIssue,
    *,
    effective_at: datetime,
    registry: IdentityRegistry,
    available_balance_wea: int | None = None,
    _verified_runtime_reference: Any,
) -> DraftValidation:
    runtime = (
        _verified_runtime_reference.ruleset_hash,
        _verified_runtime_reference.tide_interface_version,
        _verified_runtime_reference.executor_manifest_hash,
    )
    return _validate_draft_core(
        draft,
        effective_at=effective_at,
        registry=registry,
        runtime=runtime,
        available_balance_wea=available_balance_wea,
    )


def assign_triage(
    state: IntakeState,
    role: TriageRole,
    assignment: TriageAssignment,
    *,
    registry: IdentityRegistry,
) -> IntakeState:
    """Atomically create a free Triage or a treasury-funded role escrow."""
    state = _validated_state(state)
    registry = _validated_registry(registry)
    role = _rebuild_transition_record(role, TriageRole, "role")
    assignment = _rebuild_transition_record(assignment, TriageAssignment, "assignment")
    _expect("assignment.role_id", assignment.role_id, role.role_id)
    binding = _authorize_system_role(
        registry=registry,
        actor_kind="agent0",
        github_account_id=assignment.agent0_github_account_id,
        binding_id=assignment.agent0_binding_id,
        effective_at=assignment.effective_at,
    )
    _expect(
        "assignment.agent0_binding_version",
        assignment.agent0_binding_version,
        binding.version,
    )
    try:
        reviewer = authorize_agent(
            github_account_id=assignment.reviewer_github_account_id,
            agent_id=assignment.reviewer_agent_id,
            effective_at=assignment.effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise IntakeError("assignment.reviewer_agent_id", str(exc)) from exc
    _expect(
        "assignment.reviewer_binding_id",
        assignment.reviewer_binding_id,
        reviewer.account_binding_id,
    )
    _expect(
        "assignment.reviewer_binding_version",
        assignment.reviewer_binding_version,
        reviewer.account_binding_version,
    )
    role_matches = [item for item in state.triage_roles if item.role_id == role.role_id]
    if role_matches and role_matches[0] != role:
        raise IntakeError("role_id", "is already assigned with different content")
    issue_matches = [
        item for item in state.triage_roles if item.issue_id == role.issue_id
    ]
    if issue_matches and issue_matches[0].role_id != role.role_id:
        raise IntakeError("issue_id", "already has a Triage role")
    reserved_account_ids = {
        "treasury",
        *(item.account_id for item in state.balances),
        *(item.github_account_id for item in registry.accounts),
        *(item.base_agent_id for item in registry.accounts),
        *(item.subject_id for item in registry.bindings),
    }
    if role.role_id in reserved_account_ids:
        raise IntakeError("role_id", "cannot collide with an account principal")
    if role.escrow_id is not None and role.escrow_id in reserved_account_ids:
        raise IntakeError("escrow_id", "cannot collide with a balance account")
    existing_assignments = [
        item
        for item in state.triage_assignments
        if item.assignment_id == assignment.assignment_id
    ]
    if existing_assignments:
        if existing_assignments[0] == assignment:
            return state
        raise IntakeError("assignment_id", "is already used with different content")
    if any(
        item.idempotency_key == assignment.idempotency_key
        for item in (*state.triage_assignments, *state.triage_completions)
    ):
        raise IntakeError("idempotency_key", "is already used")
    generations = [
        item.generation
        for item in state.triage_assignments
        if item.role_id == role.role_id
    ]
    expected_generation = 1 if not generations else max(generations) + 1
    if assignment.generation != expected_generation:
        raise IntakeError("generation", "must continue the role assignment sequence")
    if generations:
        previous_generation = expected_generation - 1
        previous_triages = [
            item
            for item in state.triages
            if item.role_id == role.role_id
            and item.assignment_generation == previous_generation
        ]
        completed_revisions = {
            item.triage_revision_id
            for item in state.triage_completions
            if item.role_id == role.role_id
            and item.assignment_generation == previous_generation
        }
        if not previous_triages or any(
            item.revision_id not in completed_revisions for item in previous_triages
        ):
            raise IntakeError(
                "generation", "prior generation must be terminal before reassignment"
            )
        prior_evidence_keys = [
            _source_order_key(item)
            for item in (
                *state.triage_assignments,
                *state.triages,
                *state.triage_completions,
            )
            if item.role_id == role.role_id
        ]
        if _source_order_key(assignment) <= max(prior_evidence_keys):
            raise IntakeError(
                "effective_at", "new assignment must follow all prior role evidence"
            )
    balances = state.balances
    escrows = state.escrows
    ledger = state.ledger
    if not role_matches and role.funding_source == "treasury":
        treasury_account_id = "treasury"
        balance = state.balance(treasury_account_id)
        if balance < role.amount_wea:
            raise IntakeError("treasury_balance", "is insufficient for the Triage role")
        assert role.escrow_id is not None
        escrow = Escrow(
            escrow_id=role.escrow_id,
            kind="triage-role",
            basis_id=role.role_id,
            source_account_id=treasury_account_id,
            refund_agent_id=None,
            amount_wea=role.amount_wea,
        )
        debit = LedgerTransition(
            transition_id=f"triage-fund:{role.role_id}",
            kind="triage-treasury",
            debit_account_id=treasury_account_id,
            credit_account_id=escrow.escrow_id,
            amount_wea=role.amount_wea,
            basis_id=role.role_id,
        )
        if any(item.escrow_id == escrow.escrow_id for item in escrows):
            raise IntakeError("escrow_id", "is already in use")
        if any(item.transition_id == debit.transition_id for item in ledger):
            raise IntakeError("transition_id", "is already in use")
        balances = _replace_balance(
            state, treasury_account_id, balance - role.amount_wea
        )
        escrows = _append(escrows, escrow, "escrow_id")
        ledger = _append(ledger, debit, "transition_id")
    return replace(
        state,
        balances=balances,
        escrows=escrows,
        ledger=ledger,
        triage_assignments=_append(
            state.triage_assignments, assignment, "assignment_id"
        ),
        triage_roles=(
            state.triage_roles
            if role_matches
            else _append(state.triage_roles, role, "role_id")
        ),
    )


def record_triage(
    state: IntakeState,
    triage: TriageRecord,
    *,
    registry: IdentityRegistry,
) -> IntakeState:
    """Record reviewer output without granting it payment authority."""
    state = _validated_state(state)
    registry = _validated_registry(registry)
    triage = _rebuild_transition_record(triage, TriageRecord, "triage")
    roles = [item for item in state.triage_roles if item.role_id == triage.role_id]
    if len(roles) != 1:
        raise IntakeError("role_id", "Triage role is not assigned")
    role = roles[0]
    assignments = [
        item
        for item in state.triage_assignments
        if item.role_id == triage.role_id
        and item.generation == triage.assignment_generation
    ]
    if len(assignments) != 1:
        raise IntakeError("role_id", "Triage record does not belong to its assignment")
    assignment = assignments[0]
    if (
        role.issue_id != triage.issue_id
        or assignment.reviewer_agent_id != triage.reviewer_agent_id
        or assignment.reviewer_github_account_id != triage.reviewer_github_account_id
        or assignment.reviewer_binding_id != triage.reviewer_binding_id
        or assignment.reviewer_binding_version != triage.reviewer_binding_version
    ):
        raise IntakeError("role_id", "Triage record does not belong to its assignment")
    if _source_order_key(assignment) > _source_order_key(triage):
        raise IntakeError("effective_at", "Triage must not precede its assignment")
    try:
        reviewer = authorize_agent(
            github_account_id=triage.reviewer_github_account_id,
            agent_id=triage.reviewer_agent_id,
            effective_at=triage.effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise IntakeError("reviewer_agent_id", str(exc)) from exc
    _expect(
        "reviewer_binding_id",
        triage.reviewer_binding_id,
        reviewer.account_binding_id,
    )
    _expect(
        "reviewer_binding_version",
        triage.reviewer_binding_version,
        reviewer.account_binding_version,
    )
    existing = [
        item for item in state.triages if item.revision_id == triage.revision_id
    ]
    if existing:
        if existing[0] == triage:
            return state
        raise IntakeError("revision_id", "is already used by another Triage record")
    if triage.assignment_generation != max(
        item.generation
        for item in state.triage_assignments
        if item.role_id == triage.role_id
    ):
        raise IntakeError("assignment_generation", "is no longer current")
    return replace(state, triages=_append(state.triages, triage, "revision_id"))


def complete_triage(
    state: IntakeState,
    completion: TriageCompletion,
    *,
    registry: IdentityRegistry,
) -> IntakeState:
    """Accept Agent0 completion and settle a paid role at most once."""
    state = _validated_state(state)
    registry = _validated_registry(registry)
    completion = _rebuild_transition_record(completion, TriageCompletion, "completion")
    triage = _find_triage(state, completion.triage_revision_id)
    for field, actual, expected in (
        ("role_id", completion.role_id, triage.role_id),
        (
            "assignment_generation",
            completion.assignment_generation,
            triage.assignment_generation,
        ),
        ("reviewer_agent_id", completion.reviewer_agent_id, triage.reviewer_agent_id),
    ):
        _expect(f"completion.{field}", actual, expected)
    assignments = [
        item
        for item in state.triage_assignments
        if item.role_id == completion.role_id
        and item.generation == completion.assignment_generation
    ]
    if len(assignments) != 1:
        raise IntakeError("completion.assignment", "must resolve exactly once")
    assignment = assignments[0]
    _authorize_triage_evidence(
        registry=registry,
        assignment=assignment,
        triage=triage,
    )
    existing = [
        item
        for item in state.triage_completions
        if item.completion_id == completion.completion_id
    ]
    if existing:
        if existing[0] == completion:
            return state
        raise IntakeError("completion_id", "is already used with different content")
    if completion.assignment_generation != max(
        item.generation
        for item in state.triage_assignments
        if item.role_id == completion.role_id
    ):
        raise IntakeError("completion.generation", "assignment is no longer current")
    if _source_order_key(completion) < _source_order_key(triage):
        raise IntakeError("completion.effective_at", "must not precede Triage")
    binding = _authorize_system_role(
        registry=registry,
        actor_kind="agent0",
        github_account_id=completion.agent0_github_account_id,
        binding_id=completion.agent0_binding_id,
        effective_at=completion.effective_at,
    )
    _expect(
        "completion.agent0_binding_version",
        completion.agent0_binding_version,
        binding.version,
    )
    if any(
        item.triage_revision_id == completion.triage_revision_id
        for item in state.triage_completions
    ):
        raise IntakeError("triage_revision_id", "is already completed")
    if any(
        item.idempotency_key == completion.idempotency_key
        for item in (*state.triage_assignments, *state.triage_completions)
    ):
        raise IntakeError("idempotency_key", "is already used")
    role = next(item for item in state.triage_roles if item.role_id == triage.role_id)
    balances = state.balances
    escrows = state.escrows
    ledger = state.ledger
    first_completion = not any(
        item.role_id == role.role_id for item in state.triage_completions
    )
    if role.funding_source == "treasury" and first_completion:
        role_escrows = [
            item
            for item in state.escrows
            if item.kind == "triage-role" and item.basis_id == role.role_id
        ]
        if len(role_escrows) != 1:
            raise IntakeError("triage payout", "role escrow must resolve exactly once")
        escrow = role_escrows[0]
        if escrow.settlement_transition_id is not None:
            raise IntakeError("triage payout", "role escrow is already settled")
        payout = LedgerTransition(
            transition_id=f"triage-payout:{role.role_id}",
            kind="triage-payout",
            debit_account_id=escrow.escrow_id,
            credit_account_id=completion.reviewer_agent_id,
            amount_wea=role.amount_wea,
            basis_id=role.role_id,
        )
        if any(item.transition_id == payout.transition_id for item in state.ledger):
            raise IntakeError("triage payout", "transition ID is already in use")
        settled = replace(
            escrow,
            settlement_transition_id=payout.transition_id,
        )
        escrows = tuple(
            settled if item.escrow_id == settled.escrow_id else item
            for item in state.escrows
        )
        ledger = _append(state.ledger, payout, "transition_id")
        balances = _credit_balance(
            state,
            completion.reviewer_agent_id,
            role.amount_wea,
        )
    return replace(
        state,
        balances=balances,
        escrows=escrows,
        ledger=ledger,
        triage_completions=_append(
            state.triage_completions, completion, "completion_id"
        ),
    )


def record_route_override(
    state: IntakeState,
    override: RouteOverride,
    *,
    registry: IdentityRegistry,
) -> IntakeState:
    state = _validated_state(state)
    registry = _validated_registry(registry)
    override = _rebuild_transition_record(override, RouteOverride, "override")
    triage = _find_triage(state, override.triage_revision_id)
    if (
        override.issue_id != triage.issue_id
        or override.triage_role_id != triage.role_id
        or override.triage_snapshot_hash != triage.snapshot_hash
        or override.original_route != triage.route
    ):
        raise IntakeError("override", "does not identify the exact Triage revision")
    if _source_order_key(override) < _source_order_key(triage):
        raise IntakeError("override.effective_at", "must not precede Triage")
    binding = _authorize_system_role(
        registry=registry,
        actor_kind="operator",
        github_account_id=override.operator_github_account_id,
        binding_id=override.operator_binding_id,
        effective_at=override.effective_at,
    )
    _expect(
        "operator_binding_version",
        override.operator_binding_version,
        binding.version,
    )
    existing = [
        item for item in state.overrides if item.override_id == override.override_id
    ]
    if existing:
        if existing[0] == override:
            return state
        raise IntakeError("override_id", "is already used with different content")
    return replace(state, overrides=_append(state.overrides, override, "override_id"))


def record_author_consent(
    state: IntakeState,
    consent: AuthorConsent,
    *,
    registry: IdentityRegistry,
) -> IntakeState:
    state = _validated_state(state)
    registry = _validated_registry(registry)
    consent = _rebuild_transition_record(consent, AuthorConsent, "consent")
    triage = _find_triage(state, consent.triage_revision_id)
    for field, actual, expected in (
        ("triage_role_id", consent.triage_role_id, triage.role_id),
        ("triage_snapshot_hash", consent.triage_snapshot_hash, triage.snapshot_hash),
        ("issue_id", consent.issue_id, triage.issue_id),
    ):
        _expect(f"consent.{field}", actual, expected)
    if _source_order_key(consent) < _source_order_key(triage):
        raise IntakeError("consent.effective_at", "must not precede Triage")
    completions = [
        item
        for item in state.triage_completions
        if item.triage_revision_id == triage.revision_id
    ]
    if len(completions) != 1 or _source_order_key(completions[0]) > _source_order_key(
        consent
    ):
        raise IntakeError(
            "consent.triage_revision_id",
            "must name a completed same-revision Triage",
        )
    try:
        authority = authorize_issue_author(
            author_agent_id=consent.author_agent_id,
            github_account_id=consent.github_account_id,
            effective_at=consent.effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise IntakeError("consent.author_agent_id", str(exc)) from exc
    _expect(
        "consent.account_binding_id",
        consent.account_binding_id,
        authority.account_binding_id,
    )
    _expect(
        "consent.account_binding_version",
        consent.account_binding_version,
        authority.account_binding_version,
    )
    if consent.override_id is not None:
        overrides = [
            item for item in state.overrides if item.override_id == consent.override_id
        ]
        if len(overrides) != 1:
            raise IntakeError("consent.override_id", "must resolve exactly once")
        if _source_order_key(overrides[0]) >= _source_order_key(consent):
            raise IntakeError(
                "consent.override_id", "operator override must precede consent"
            )
    existing = [
        item for item in state.consents if item.consent_id == consent.consent_id
    ]
    if existing:
        if existing[0] == consent:
            return state
        raise IntakeError("consent_id", "is already used with different content")
    return replace(state, consents=_append(state.consents, consent, "consent_id"))


def record_contract_readiness(
    state: IntakeState,
    readiness: ContractReadiness,
    *,
    registry: IdentityRegistry,
) -> IntakeState:
    """Record Agent0's exact declaration linking consent and Triage evidence."""
    state = _validated_state(state)
    registry = _validated_registry(registry)
    readiness = _rebuild_transition_record(readiness, ContractReadiness, "readiness")
    consents = [
        item for item in state.consents if item.consent_id == readiness.consent_id
    ]
    if len(consents) != 1:
        raise IntakeError("consent_id", "readiness must link one recorded consent")
    consent = consents[0]
    triage = _find_triage(state, readiness.triage_revision_id)
    for field, actual, expected in (
        ("issue_id", readiness.issue_id, consent.issue_id),
        ("consent_revision_id", readiness.consent_revision_id, consent.revision_id),
        ("triage_role_id", readiness.triage_role_id, triage.role_id),
        ("triage_snapshot_hash", readiness.triage_snapshot_hash, triage.snapshot_hash),
        ("override_id", readiness.override_id, consent.override_id),
    ):
        _expect(f"readiness.{field}", actual, expected)
    if _source_order_key(consent) > _source_order_key(readiness):
        raise IntakeError("readiness.effective_at", "must not precede consent")
    binding = _authorize_system_role(
        registry=registry,
        actor_kind="agent0",
        github_account_id=readiness.agent0_github_account_id,
        binding_id=readiness.agent0_binding_id,
        effective_at=readiness.effective_at,
    )
    _expect(
        "readiness.agent0_binding_version",
        readiness.agent0_binding_version,
        binding.version,
    )
    existing = [
        item for item in state.readiness if item.readiness_id == readiness.readiness_id
    ]
    if existing:
        if existing[0] == readiness:
            return state
        raise IntakeError("readiness_id", "is already used with different content")
    return replace(
        state,
        readiness=_append(state.readiness, readiness, "readiness_id"),
    )


def _find_triage(state: IntakeState, revision_id: str) -> TriageRecord:
    matches = [item for item in state.triages if item.revision_id == revision_id]
    if len(matches) != 1:
        raise IntakeError("triage_revision_id", "must resolve exactly once")
    return matches[0]


def _authorize_system_role(
    *,
    registry: IdentityRegistry,
    actor_kind: str,
    github_account_id: str,
    binding_id: str,
    effective_at: datetime,
) -> Binding:
    matches = [
        item
        for item in registry.bindings
        if item.actor_kind == actor_kind
        and item.github_account_id == github_account_id
        and item.binding_id == binding_id
        and item.active_at(effective_at)
    ]
    if len(matches) != 1:
        raise IntakeError(actor_kind, "authority must resolve to one active binding")
    return matches[0]


def _expect(field: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise IntakeError(field, "does not match the Contract candidate")


def _authorize_triage_evidence(
    *,
    registry: IdentityRegistry,
    assignment: TriageAssignment,
    triage: TriageRecord,
) -> None:
    assignment_agent0 = _authorize_system_role(
        registry=registry,
        actor_kind="agent0",
        github_account_id=assignment.agent0_github_account_id,
        binding_id=assignment.agent0_binding_id,
        effective_at=assignment.effective_at,
    )
    _expect(
        "assignment.agent0_binding_version",
        assignment.agent0_binding_version,
        assignment_agent0.version,
    )
    for evidence_name, reviewer_agent_id, reviewer_github_account_id, (
        reviewer_binding_id,
        reviewer_binding_version,
    ), evidence_at in (
        (
            "assignment",
            assignment.reviewer_agent_id,
            assignment.reviewer_github_account_id,
            (assignment.reviewer_binding_id, assignment.reviewer_binding_version),
            assignment.effective_at,
        ),
        (
            "triage",
            triage.reviewer_agent_id,
            triage.reviewer_github_account_id,
            (triage.reviewer_binding_id, triage.reviewer_binding_version),
            triage.effective_at,
        ),
    ):
        try:
            reviewer = authorize_agent(
                github_account_id=reviewer_github_account_id,
                agent_id=reviewer_agent_id,
                effective_at=evidence_at,
                registry=registry,
            )
        except IdentityError as exc:
            raise IntakeError(f"{evidence_name}.reviewer", str(exc)) from exc
        _expect(
            f"{evidence_name}.reviewer_binding_id",
            reviewer_binding_id,
            reviewer.account_binding_id,
        )
        _expect(
            f"{evidence_name}.reviewer_binding_version",
            reviewer_binding_version,
            reviewer.account_binding_version,
        )


def activate_contract(
    state: IntakeState,
    candidate: ContractCandidate,
    *,
    consent_id: str,
    payer_agent_id: str,
    payer_github_account_id: str,
    effective_at: datetime,
    readiness_id: str,
    registry: IdentityRegistry,
    _verified_runtime_reference: Any,
) -> ContractActivation:
    """Validate first, then atomically debit bank and create Contract, Task, escrow."""
    state = _validated_state(state)
    candidate = _rebuild_candidate(candidate)
    registry = _validated_registry(registry)
    effective_at = _utc("effective_at", effective_at)
    readiness_id = _text("readiness_id", readiness_id)
    draft = candidate.draft
    _expect("contract_id", candidate.contract_id, ordinary_contract_id(draft.issue_id))
    runtime = (
        _verified_runtime_reference.ruleset_hash,
        _verified_runtime_reference.tide_interface_version,
        _verified_runtime_reference.executor_manifest_hash,
    )
    validation = _validate_draft_core(
        draft,
        effective_at=effective_at,
        registry=registry,
        runtime=runtime,
    )
    _expect("payer_agent_id", payer_agent_id, draft.author_agent_id)
    _expect(
        "payer_github_account_id",
        payer_github_account_id,
        draft.creator_github_account_id,
    )
    if validation.author.agent_id != payer_agent_id:
        raise IntakeError("payer_agent_id", "is not the authorized Issue author")
    consent_matches = [item for item in state.consents if item.consent_id == consent_id]
    if len(consent_matches) != 1:
        raise IntakeError("consent_id", "must resolve exactly once")
    consent = consent_matches[0]
    readiness_matches = [
        item for item in state.readiness if item.readiness_id == readiness_id
    ]
    if len(readiness_matches) != 1:
        raise IntakeError("readiness_id", "must resolve exactly once")
    readiness = readiness_matches[0]
    readiness_binding = _authorize_system_role(
        registry=registry,
        actor_kind="agent0",
        github_account_id=readiness.agent0_github_account_id,
        binding_id=readiness.agent0_binding_id,
        effective_at=readiness.effective_at,
    )
    _expect(
        "readiness.agent0_binding_version",
        readiness.agent0_binding_version,
        readiness_binding.version,
    )
    triage = _find_triage(state, candidate.triage_revision_id)
    role_matches = [
        item for item in state.triage_roles if item.role_id == triage.role_id
    ]
    if len(role_matches) != 1:
        raise IntakeError("triage_role_id", "must resolve to an assigned role")
    completions = [
        item
        for item in state.triage_completions
        if item.triage_revision_id == triage.revision_id
    ]
    if len(completions) != 1:
        raise IntakeError("triage_completion", "must resolve exactly once")
    completion = completions[0]
    assignment_matches = [
        item
        for item in state.triage_assignments
        if item.role_id == triage.role_id
        and item.generation == triage.assignment_generation
    ]
    if len(assignment_matches) != 1:
        raise IntakeError("triage_assignment", "must resolve exactly once")
    assignment = assignment_matches[0]
    _authorize_triage_evidence(
        registry=registry,
        assignment=assignment,
        triage=triage,
    )
    completion_agent0 = _authorize_system_role(
        registry=registry,
        actor_kind="agent0",
        github_account_id=completion.agent0_github_account_id,
        binding_id=completion.agent0_binding_id,
        effective_at=completion.effective_at,
    )
    _expect(
        "completion.agent0_binding_version",
        completion.agent0_binding_version,
        completion_agent0.version,
    )
    for field, actual, expected in (
        ("triage.issue_id", triage.issue_id, draft.issue_id),
        (
            "triage.issue_revision_id",
            triage.issue_revision_id,
            draft.issue_revision_id,
        ),
        ("triage.body_hash", triage.body_hash, draft.body_hash),
    ):
        _expect(field, actual, expected)
    if (
        _source_order_key(triage) > _source_order_key(consent)
        or _source_order_key(completion) > _source_order_key(consent)
        or _source_order_key(consent) > _source_order_key(readiness)
        or readiness.effective_at > effective_at
    ):
        raise IntakeError(
            "effective_at", "Triage, consent, and readiness are out of order"
        )
    for field, actual, expected in (
        ("readiness.issue_id", readiness.issue_id, draft.issue_id),
        ("readiness.consent_id", readiness.consent_id, consent.consent_id),
        (
            "readiness.consent_revision_id",
            readiness.consent_revision_id,
            consent.revision_id,
        ),
        ("readiness.triage_role_id", readiness.triage_role_id, triage.role_id),
        (
            "readiness.triage_revision_id",
            readiness.triage_revision_id,
            triage.revision_id,
        ),
        (
            "readiness.triage_snapshot_hash",
            readiness.triage_snapshot_hash,
            triage.snapshot_hash,
        ),
        ("readiness.override_id", readiness.override_id, consent.override_id),
    ):
        _expect(field, actual, expected)

    route_override: RouteOverride | None = None
    if candidate.route != triage.route:
        if consent.override_id is None:
            raise IntakeError(
                "route", "differs from Triage without an operator override"
            )
        matches = [
            item for item in state.overrides if item.override_id == consent.override_id
        ]
        if len(matches) != 1:
            raise IntakeError("override_id", "must resolve exactly once")
        route_override = matches[0]
        override_binding = _authorize_system_role(
            registry=registry,
            actor_kind="operator",
            github_account_id=route_override.operator_github_account_id,
            binding_id=route_override.operator_binding_id,
            effective_at=route_override.effective_at,
        )
        _expect(
            "operator_binding_version",
            route_override.operator_binding_version,
            override_binding.version,
        )
        for field, actual, expected in (
            ("override.issue_id", route_override.issue_id, draft.issue_id),
            ("override.triage_role_id", route_override.triage_role_id, triage.role_id),
            (
                "override.triage_revision_id",
                route_override.triage_revision_id,
                triage.revision_id,
            ),
            (
                "override.triage_snapshot_hash",
                route_override.triage_snapshot_hash,
                triage.snapshot_hash,
            ),
            ("override.original_route", route_override.original_route, triage.route),
            ("override.new_route", route_override.new_route, candidate.route),
        ):
            _expect(field, actual, expected)
        if _source_order_key(route_override) >= _source_order_key(consent):
            raise IntakeError("override.effective_at", "must precede author consent")
    elif consent.override_id is not None:
        raise IntakeError(
            "override_id", "is not applicable to the accepted Triage route"
        )

    for field, actual, expected in (
        ("author_agent_id", consent.author_agent_id, draft.author_agent_id),
        (
            "github_account_id",
            consent.github_account_id,
            draft.creator_github_account_id,
        ),
        ("issue_id", consent.issue_id, draft.issue_id),
        ("issue_revision_id", consent.issue_revision_id, draft.issue_revision_id),
        ("body_hash", consent.body_hash, draft.body_hash),
        ("bank_wea", consent.bank_wea, draft.bank_wea),
        ("profile", consent.profile, draft.profile),
        ("mechanic", consent.mechanic, draft.terms.mechanic),
        ("mechanic_config_hash", consent.mechanic_config_hash, draft.terms.config_hash),
        ("ruleset_hash", consent.ruleset_hash, runtime[0]),
        ("tide_interface_version", consent.tide_interface_version, runtime[1]),
        ("executor_manifest_hash", consent.executor_manifest_hash, runtime[2]),
        ("triage_role_id", consent.triage_role_id, triage.role_id),
        ("triage_revision_id", consent.triage_revision_id, triage.revision_id),
        ("triage_snapshot_hash", consent.triage_snapshot_hash, triage.snapshot_hash),
        ("route", consent.route, candidate.route),
    ):
        _expect(field, actual, expected)
    try:
        consent_authority = authorize_issue_author(
            author_agent_id=consent.author_agent_id,
            github_account_id=consent.github_account_id,
            effective_at=consent.effective_at,
            registry=registry,
        )
    except IdentityError as exc:
        raise IntakeError("consent.author_agent_id", str(exc)) from exc
    _expect(
        "account_binding_id",
        consent.account_binding_id,
        consent_authority.account_binding_id,
    )
    _expect(
        "account_binding_version",
        consent.account_binding_version,
        consent_authority.account_binding_version,
    )

    rules = load_ruleset()
    first_stage = rules.content["profiles"][candidate.route]["stages"][0]
    contract = OrdinaryContract(
        contract_id=candidate.contract_id,
        issue_id=draft.issue_id,
        issue_revision_id=draft.issue_revision_id,
        body=draft.body,
        body_hash=draft.body_hash,
        author_agent_id=draft.author_agent_id,
        payer_agent_id=payer_agent_id,
        bank_wea=draft.bank_wea,
        profile=draft.profile,
        mechanic=draft.terms.mechanic,
        mechanic_terms=draft.terms,
        triage_role_id=triage.role_id,
        triage_revision_id=triage.revision_id,
        triage_snapshot_hash=triage.snapshot_hash,
        consent_id=consent.consent_id,
        consent_revision_id=consent.revision_id,
        consent_snapshot_hash=consent.snapshot_hash,
        readiness_id=readiness.readiness_id,
        override_id=None if route_override is None else route_override.override_id,
        ruleset_hash=runtime[0],
        tide_interface_version=runtime[1],
        executor_manifest_hash=runtime[2],
    )
    task = Task(
        task_id=f"task:{candidate.contract_id}",
        contract_id=candidate.contract_id,
        profile=candidate.route,
        stage=first_stage,
    )
    escrow = Escrow(
        escrow_id=_task_escrow_id(candidate.contract_id),
        kind="task",
        basis_id=candidate.contract_id,
        source_account_id=payer_agent_id,
        refund_agent_id=draft.author_agent_id,
        amount_wea=draft.bank_wea,
    )
    reserved_account_ids = {
        *(item.account_id for item in state.balances),
        *(item.github_account_id for item in registry.accounts),
        *(item.base_agent_id for item in registry.accounts),
        *(item.subject_id for item in registry.bindings),
    }
    if escrow.escrow_id in reserved_account_ids:
        raise IntakeError(
            "escrow_id", "cannot collide with a balance or identity account"
        )
    debit = LedgerTransition(
        transition_id=f"contract-bank:{candidate.contract_id}",
        kind="contract-bank",
        debit_account_id=payer_agent_id,
        credit_account_id=escrow.escrow_id,
        amount_wea=draft.bank_wea,
        basis_id=candidate.contract_id,
    )
    existing = [
        item for item in state.contracts if item.contract_id == candidate.contract_id
    ]
    if existing:
        matches = (
            existing[0] == contract
            and task in state.tasks
            and escrow in state.escrows
            and debit in state.ledger
        )
        if not matches:
            raise IntakeError(
                "contract_id", "is already activated with different content"
            )
        return ContractActivation(state, existing[0], task, escrow, debit, False)

    for field, records, identifier in (
        ("task_id", state.tasks, task.task_id),
        ("escrow_id", state.escrows, escrow.escrow_id),
        ("transition_id", state.ledger, debit.transition_id),
    ):
        if any(getattr(item, field) == identifier for item in records):
            raise IntakeError(field, "is already in use")
    balance = state.balance(payer_agent_id)
    if balance < draft.bank_wea:
        raise IntakeError(
            "author_balance", "is insufficient for the full Contract bank"
        )
    next_state = replace(
        state,
        balances=_replace_balance(state, payer_agent_id, balance - draft.bank_wea),
        contracts=_append(state.contracts, contract, "contract_id"),
        tasks=_append(state.tasks, task, "task_id"),
        escrows=_append(state.escrows, escrow, "escrow_id"),
        ledger=_append(state.ledger, debit, "transition_id"),
    )
    return ContractActivation(next_state, contract, task, escrow, debit, True)


__all__ = [
    "AccountBalance",
    "AuthorConsent",
    "ContractActivation",
    "ContractCandidate",
    "ContractReadiness",
    "DraftIssue",
    "DraftValidation",
    "Escrow",
    "IntakeError",
    "IntakeState",
    "LedgerTransition",
    "MechanicTerms",
    "OrdinaryContract",
    "RouteOverride",
    "Task",
    "TriageAssignment",
    "TriageCompletion",
    "TriageRecord",
    "TriageRole",
    "activate_contract",
    "assign_triage",
    "complete_triage",
    "ordinary_contract_id",
    "record_author_consent",
    "record_contract_readiness",
    "record_route_override",
    "record_triage",
    "triage_escrow_id",
    "triage_role_id",
    "validate_draft",
]
