"""Pure v1 identity reconciliation for the 0.6.2 executor."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .canonical import canonical_hash
from .identity import (
    Binding,
    ControlGroupBinding,
    GitHubAccount,
    IdentityError,
    IdentityRegistry,
)


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value:
        raise IdentityError(f"{name} must be a non-empty string")
    return value


def _strings(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    if type(values) is not tuple or not values:
        raise IdentityError(f"{name} must contain durable source IDs")
    for value in values:
        _text(name, value)
    if len(values) != len(set(values)):
        raise IdentityError(f"{name} must not contain duplicate source IDs")
    return tuple(sorted(values))


@dataclass(frozen=True)
class V1IdentityEvidence:
    """Operator-approved evidence row for one preserved v1 Agent ID."""

    github_account_id: str
    account_owner: str
    base_agent_id: str
    agent_id: str
    control_group_id: str
    account_binding_id: str
    account_binding_version: int
    group_binding_id: str
    group_binding_version: int
    effective_from: datetime
    issue_id: str
    comment_id: str
    revision_id: str
    ledger_history_ids: tuple[str, ...]
    idempotency_keys: tuple[str, ...]
    aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "github_account_id",
            "account_owner",
            "base_agent_id",
            "agent_id",
            "control_group_id",
            "account_binding_id",
            "group_binding_id",
            "issue_id",
            "comment_id",
            "revision_id",
        ):
            _text(name, getattr(self, name))
        for name in ("account_binding_version", "group_binding_version"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise IdentityError(f"{name} must be a positive integer")
        if (
            not isinstance(self.effective_from, datetime)
            or self.effective_from.tzinfo is None
            or self.effective_from.utcoffset() is None
        ):
            raise IdentityError("effective_from must be timezone-aware")
        effective_from = self.effective_from.astimezone(timezone.utc)
        object.__setattr__(
            self,
            "effective_from",
            datetime(
                effective_from.year,
                effective_from.month,
                effective_from.day,
                effective_from.hour,
                effective_from.minute,
                effective_from.second,
                effective_from.microsecond,
                tzinfo=timezone.utc,
                fold=effective_from.fold,
            ),
        )
        object.__setattr__(
            self,
            "ledger_history_ids",
            _strings("ledger_history_ids", self.ledger_history_ids),
        )
        object.__setattr__(
            self,
            "idempotency_keys",
            _strings("idempotency_keys", self.idempotency_keys),
        )
        object.__setattr__(self, "aliases", _strings("aliases", self.aliases))

    def to_data(self) -> dict[str, object]:
        return {
            "account_binding_id": self.account_binding_id,
            "account_binding_version": self.account_binding_version,
            "account_owner": self.account_owner,
            "agent_id": self.agent_id,
            "aliases": list(self.aliases),
            "base_agent_id": self.base_agent_id,
            "comment_id": self.comment_id,
            "control_group_id": self.control_group_id,
            "effective_from": self.effective_from.isoformat().replace("+00:00", "Z"),
            "github_account_id": self.github_account_id,
            "group_binding_id": self.group_binding_id,
            "group_binding_version": self.group_binding_version,
            "idempotency_keys": list(self.idempotency_keys),
            "issue_id": self.issue_id,
            "ledger_history_ids": list(self.ledger_history_ids),
            "revision_id": self.revision_id,
        }


def _migration_material(
    evidence: tuple[V1IdentityEvidence, ...],
) -> tuple[IdentityRegistry, tuple[V1IdentityEvidence, ...]]:
    if type(evidence) is not tuple or not evidence:
        raise IdentityError("v1 identity restoration requires evidence rows")
    if any(type(item) is not V1IdentityEvidence for item in evidence):
        raise IdentityError("v1 identity evidence must use verified record types")
    ordered = tuple(
        sorted(evidence, key=lambda item: (item.github_account_id, item.agent_id))
    )
    accounts_by_id: dict[str, GitHubAccount] = {}
    bindings: list[Binding] = []
    groups: list[ControlGroupBinding] = []
    used_source_ids: dict[str, set[str]] = {
        "alias": set(),
        "comment": set(),
        "idempotency": set(),
        "ledger_history": set(),
        "revision": set(),
    }

    def claim_source(kind: str, source_id: str) -> None:
        used = used_source_ids[kind]
        if source_id in used:
            raise IdentityError(f"v1 {kind} source ID is reused")
        used.add(source_id)

    for item in ordered:
        claim_source("comment", item.comment_id)
        claim_source("revision", item.revision_id)
        for source_id in item.ledger_history_ids:
            claim_source("ledger_history", source_id)
        for source_id in item.idempotency_keys:
            claim_source("idempotency", source_id)
        for source_id in item.aliases:
            claim_source("alias", source_id)
        account = GitHubAccount(
            item.github_account_id,
            item.account_owner,
            item.base_agent_id,
        )
        previous = accounts_by_id.get(item.github_account_id)
        if previous is not None and previous != account:
            raise IdentityError("v1 evidence disagrees about account or base_agent_id")
        accounts_by_id[item.github_account_id] = account
        bindings.append(
            Binding(
                item.account_binding_id,
                "agent",
                item.github_account_id,
                item.agent_id,
                item.account_binding_version,
                item.effective_from,
            )
        )
        groups.append(
            ControlGroupBinding(
                item.group_binding_id,
                item.agent_id,
                item.control_group_id,
                item.group_binding_version,
                item.effective_from,
            )
        )
    return (
        IdentityRegistry(
            accounts=tuple(accounts_by_id.values()),
            bindings=tuple(bindings),
            control_group_bindings=tuple(groups),
        ),
        ordered,
    )


@dataclass(frozen=True)
class IdentityMigrationPlan:
    registry: IdentityRegistry
    evidence: tuple[V1IdentityEvidence, ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        if type(self.registry) is not IdentityRegistry:
            raise IdentityError("migration registry must use the verified record type")
        if type(self.evidence) is not tuple or any(
            type(item) is not V1IdentityEvidence for item in self.evidence
        ):
            raise IdentityError("migration plan contains foreign evidence records")
        if (
            type(self.evidence_hash) is not str
            or len(self.evidence_hash) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.evidence_hash
            )
        ):
            raise IdentityError("migration evidence hash must be SHA-256")
        expected_registry, ordered = _migration_material(self.evidence)
        if self.evidence != ordered:
            raise IdentityError("migration evidence must use canonical ordering")
        if self.registry != expected_registry:
            raise IdentityError("migration registry does not match evidence")
        expected_hash = canonical_hash([item.to_data() for item in ordered])
        if self.evidence_hash != expected_hash:
            raise IdentityError("migration evidence hash does not match evidence")

    @property
    def ledger_effects(self) -> tuple[object, ...]:
        return ()


def restore_v1_identity(
    evidence: tuple[V1IdentityEvidence, ...],
) -> IdentityMigrationPlan:
    """Build canonical identity state without writing balances or external state."""
    registry, ordered = _migration_material(evidence)
    return IdentityMigrationPlan(
        registry=registry,
        evidence=ordered,
        evidence_hash=canonical_hash([item.to_data() for item in ordered]),
    )


__all__ = ["IdentityMigrationPlan", "V1IdentityEvidence", "restore_v1_identity"]
