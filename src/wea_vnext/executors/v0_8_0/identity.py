"""Versioned identity authority used by the 0.6.3 executor."""

from __future__ import annotations

import hashlib
import weakref
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_hash
from .declarations import Declaration, DeclarationError, parse_declaration


def _registry_seal_functions() -> tuple[Any, Any]:
    """Create construction seals without leaving their store module-mutable."""
    seals: dict[int, tuple[weakref.ReferenceType[Any], str]] = {}

    def remember(registry: Any, digest: str) -> None:
        identity = id(registry)

        def forget(reference: weakref.ReferenceType[Any]) -> None:
            current = seals.get(identity)
            if current is not None and current[0] is reference:
                seals.pop(identity, None)

        reference = weakref.ref(registry, forget)
        seals[identity] = (reference, digest)

    def seal(registry: Any) -> str | None:
        sealed = seals.get(id(registry))
        if sealed is None or sealed[0]() is not registry:
            return None
        return sealed[1]

    return remember, seal


_remember_registry_seal, _registry_seal = _registry_seal_functions()
del _registry_seal_functions


class IdentityError(ValueError):
    """Raised when identity authority is absent, ambiguous, or inconsistent."""


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value:
        raise IdentityError(f"{name} must be a non-empty string")
    return value


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise IdentityError("binding timestamps must be timezone-aware")
    offset = value.utcoffset()
    if offset is None:
        raise IdentityError("binding timestamps must be timezone-aware")
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


def _positive_version(value: object) -> int:
    if type(value) is not int or value < 1:
        raise IdentityError("binding version must be a positive integer")
    return value


def _active_interval(
    effective_from: datetime, effective_until: datetime | None
) -> tuple[datetime, datetime | None]:
    start = _utc(effective_from)
    end = None if effective_until is None else _utc(effective_until)
    if end is not None and end <= start:
        raise IdentityError("binding interval must be positive")
    return start, end


def _intervals_overlap(
    first_start: datetime,
    first_end: datetime | None,
    second_start: datetime,
    second_end: datetime | None,
) -> bool:
    return (first_end is None or second_start < first_end) and (
        second_end is None or first_start < second_end
    )


def _unquote(value: str) -> str:
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def _timestamp(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Binding:
    """A versioned GitHub-account binding for an Agent or system role."""

    binding_id: str
    actor_kind: str
    github_account_id: str
    subject_id: str
    version: int
    effective_from: datetime
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        for field, value in (
            ("binding_id", self.binding_id),
            ("github_account_id", self.github_account_id),
            ("subject_id", self.subject_id),
        ):
            _text(field, value)
        if self.actor_kind not in {"agent", "agent0", "operator"}:
            raise IdentityError("actor_kind must be agent, agent0, or operator")
        _positive_version(self.version)
        start, end = _active_interval(self.effective_from, self.effective_until)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)

    def active_at(self, effective_at: datetime) -> bool:
        effective_at = _utc(effective_at)
        return self.effective_from <= effective_at and (
            self.effective_until is None or effective_at < self.effective_until
        )

    def to_data(self) -> dict[str, object]:
        return {
            "actor_kind": self.actor_kind,
            "binding_id": self.binding_id,
            "effective_from": _timestamp(self.effective_from),
            "effective_until": None
            if self.effective_until is None
            else _timestamp(self.effective_until),
            "github_account_id": self.github_account_id,
            "subject_id": self.subject_id,
            "version": self.version,
        }


@dataclass(frozen=True)
class ControlGroupBinding:
    """A versioned common-control group binding for one Agent ID."""

    binding_id: str
    agent_id: str
    control_group_id: str
    version: int
    effective_from: datetime
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        _text("binding_id", self.binding_id)
        _text("agent_id", self.agent_id)
        _text("control_group_id", self.control_group_id)
        _positive_version(self.version)
        start, end = _active_interval(self.effective_from, self.effective_until)
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)

    def active_at(self, effective_at: datetime) -> bool:
        effective_at = _utc(effective_at)
        return self.effective_from <= effective_at and (
            self.effective_until is None or effective_at < self.effective_until
        )

    def to_data(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "binding_id": self.binding_id,
            "control_group_id": self.control_group_id,
            "effective_from": _timestamp(self.effective_from),
            "effective_until": None
            if self.effective_until is None
            else _timestamp(self.effective_until),
            "version": self.version,
        }


@dataclass(frozen=True)
class GitHubAccount:
    """Permanent account identity and its immutable Hello World recipient."""

    github_account_id: str
    owner: str
    base_agent_id: str

    def __post_init__(self) -> None:
        _text("github_account_id", self.github_account_id)
        _text("owner", self.owner)
        _text("base_agent_id", self.base_agent_id)

    @property
    def hello_world_mint_key(self) -> str:
        return f"hello-world:{self.github_account_id}"

    def to_data(self) -> dict[str, str]:
        return {
            "base_agent_id": self.base_agent_id,
            "github_account_id": self.github_account_id,
            "hello_world_mint_key": self.hello_world_mint_key,
            "owner": self.owner,
        }


@dataclass(frozen=True)
class IdentityAuthority:
    """Frozen authority resolved at the event's effective time."""

    github_account_id: str
    agent_id: str
    account_binding_id: str
    account_binding_version: int
    control_group_id: str
    control_group_binding_id: str
    control_group_binding_version: int
    effective_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "github_account_id",
            "agent_id",
            "account_binding_id",
            "control_group_id",
            "control_group_binding_id",
        ):
            _text(name, getattr(self, name))
        _positive_version(self.account_binding_version)
        _positive_version(self.control_group_binding_version)
        object.__setattr__(self, "effective_at", _utc(self.effective_at))

    def to_data(self) -> dict[str, object]:
        return {
            "account_binding_id": self.account_binding_id,
            "account_binding_version": self.account_binding_version,
            "agent_id": self.agent_id,
            "control_group_binding_id": self.control_group_binding_id,
            "control_group_binding_version": self.control_group_binding_version,
            "control_group_id": self.control_group_id,
            "effective_at": _timestamp(self.effective_at),
            "github_account_id": self.github_account_id,
        }


@dataclass(frozen=True)
class ControlDisclosure:
    """Frozen common-control evidence that gates selection and settlement."""

    contract_id: str
    work_id: str
    control_group_id: str
    author_agent_id: str
    participant_agent_id: str
    author_group_binding_id: str
    author_group_binding_version: int
    participant_group_binding_id: str
    participant_group_binding_version: int
    effective_at: datetime
    revision_id: str | None = None
    snapshot: str | None = None
    snapshot_hash: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "contract_id",
            "work_id",
            "control_group_id",
            "author_agent_id",
            "participant_agent_id",
            "author_group_binding_id",
            "participant_group_binding_id",
        ):
            _text(name, getattr(self, name))
        _positive_version(self.author_group_binding_version)
        _positive_version(self.participant_group_binding_version)
        object.__setattr__(self, "effective_at", _utc(self.effective_at))
        confirmation = (self.revision_id, self.snapshot, self.snapshot_hash)
        if all(item is None for item in confirmation):
            return
        if any(item is None for item in confirmation):
            raise IdentityError("control disclosure confirmation must be complete")
        revision_id = _text("revision_id", self.revision_id)
        snapshot = _text("snapshot", self.snapshot)
        snapshot_hash = _text("snapshot_hash", self.snapshot_hash)
        if snapshot != self.expected_snapshot:
            raise IdentityError(
                "control disclosure must contain the exact disclosure content"
            )
        expected = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        if snapshot_hash != expected:
            raise IdentityError("control disclosure snapshot hash does not match")
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(self, "snapshot", snapshot)
        object.__setattr__(self, "snapshot_hash", snapshot_hash)

    @property
    def confirmed(self) -> bool:
        return self.revision_id is not None

    @property
    def selection_allowed(self) -> bool:
        return self.confirmed

    @property
    def settlement_allowed(self) -> bool:
        return self.confirmed

    @property
    def expected_snapshot(self) -> str:
        return "\n".join(
            (
                "### WEA common-control disclosure",
                f"- contract_id: `{self.contract_id}`",
                f"- work_id: `{self.work_id}`",
                f"- control_group_id: `{self.control_group_id}`",
                f"- author_agent_id: `{self.author_agent_id}`",
                f"- participant_agent_id: `{self.participant_agent_id}`",
            )
        )

    def confirm(self, *, revision_id: str, snapshot: str) -> ControlDisclosure:
        revision_id = _text("revision_id", revision_id)
        snapshot = _text("snapshot", snapshot)
        if snapshot != self.expected_snapshot:
            raise IdentityError(
                "control disclosure must contain the exact disclosure content"
            )
        digest = hashlib.sha256(snapshot.encode("utf-8")).hexdigest()
        if self.confirmed:
            if self.revision_id == revision_id and self.snapshot_hash == digest:
                return self
            raise IdentityError("control disclosure is already confirmed")
        return replace(
            self,
            revision_id=revision_id,
            snapshot=snapshot,
            snapshot_hash=digest,
        )

    def to_data(self) -> dict[str, object]:
        return {
            "author_agent_id": self.author_agent_id,
            "author_group_binding_id": self.author_group_binding_id,
            "author_group_binding_version": self.author_group_binding_version,
            "control_group_id": self.control_group_id,
            "contract_id": self.contract_id,
            "effective_at": _timestamp(self.effective_at),
            "participant_agent_id": self.participant_agent_id,
            "participant_group_binding_id": self.participant_group_binding_id,
            "participant_group_binding_version": (
                self.participant_group_binding_version
            ),
            "revision_id": self.revision_id,
            "snapshot": self.snapshot,
            "snapshot_hash": self.snapshot_hash,
            "work_id": self.work_id,
        }


@dataclass(frozen=True)
class IdentityRegistry:
    """Canonical immutable identity records used for deterministic resolution."""

    accounts: tuple[GitHubAccount, ...] = ()
    bindings: tuple[Binding, ...] = ()
    control_group_bindings: tuple[ControlGroupBinding, ...] = ()

    def __post_init__(
        self,
        _remember_seal: Any = _remember_registry_seal,  # noqa: RUF033
    ) -> None:
        if any(type(item) is not GitHubAccount for item in self.accounts):
            raise IdentityError("accounts must use verified GitHubAccount records")
        if any(type(item) is not Binding for item in self.bindings):
            raise IdentityError("bindings must use verified Binding records")
        if any(
            type(item) is not ControlGroupBinding
            for item in self.control_group_bindings
        ):
            raise IdentityError(
                "control groups must use verified ControlGroupBinding records"
            )
        accounts = tuple(sorted(self.accounts, key=lambda item: item.github_account_id))
        bindings = tuple(
            sorted(
                self.bindings,
                key=lambda item: (
                    item.actor_kind,
                    item.subject_id,
                    item.effective_from,
                    item.version,
                    item.binding_id,
                ),
            )
        )
        groups = tuple(
            sorted(
                self.control_group_bindings,
                key=lambda item: (
                    item.agent_id,
                    item.effective_from,
                    item.version,
                    item.binding_id,
                ),
            )
        )
        object.__setattr__(self, "accounts", accounts)
        object.__setattr__(self, "bindings", bindings)
        object.__setattr__(self, "control_group_bindings", groups)
        self._validate_unique_ids()
        self._validate_binding_timelines(bindings)
        self._validate_group_timelines(groups)
        self._validate_accounts()
        _remember_seal(self, canonical_hash(self.to_data()))

    def _assert_unchanged(self, _get_seal: Any = _registry_seal) -> None:
        if _get_seal(self) != canonical_hash(self.to_data()):
            raise IdentityError("registry changed after validation")

    def _validate_unique_ids(self) -> None:
        account_ids = [item.github_account_id for item in self.accounts]
        if len(account_ids) != len(set(account_ids)):
            raise IdentityError("GitHub account IDs must be unique")
        binding_ids = [item.binding_id for item in self.bindings]
        binding_ids.extend(item.binding_id for item in self.control_group_bindings)
        if len(binding_ids) != len(set(binding_ids)):
            raise IdentityError("identity binding IDs must be unique")

    @staticmethod
    def _validate_binding_timelines(bindings: tuple[Binding, ...]) -> None:
        versions: set[tuple[str, str, int]] = set()
        previous_versions: dict[tuple[str, str], int] = {}
        for index, current in enumerate(bindings):
            version_key = (current.actor_kind, current.subject_id, current.version)
            if version_key in versions:
                raise IdentityError("identity binding versions must be unique")
            versions.add(version_key)
            timeline_key = (current.actor_kind, current.subject_id)
            previous_version = previous_versions.get(timeline_key)
            if previous_version is not None and current.version <= previous_version:
                raise IdentityError("identity binding versions must increase over time")
            previous_versions[timeline_key] = current.version
            for other in bindings[index + 1 :]:
                if (current.actor_kind, current.subject_id) != (
                    other.actor_kind,
                    other.subject_id,
                ):
                    continue
                if _intervals_overlap(
                    current.effective_from,
                    current.effective_until,
                    other.effective_from,
                    other.effective_until,
                ):
                    raise IdentityError("identity binding intervals overlap")

    @staticmethod
    def _validate_group_timelines(
        bindings: tuple[ControlGroupBinding, ...],
    ) -> None:
        versions: set[tuple[str, int]] = set()
        previous_versions: dict[str, int] = {}
        for index, current in enumerate(bindings):
            version_key = (current.agent_id, current.version)
            if version_key in versions:
                raise IdentityError("control-group binding versions must be unique")
            versions.add(version_key)
            previous_version = previous_versions.get(current.agent_id)
            if previous_version is not None and current.version <= previous_version:
                raise IdentityError(
                    "control-group binding versions must increase over time"
                )
            previous_versions[current.agent_id] = current.version
            for other in bindings[index + 1 :]:
                if current.agent_id != other.agent_id:
                    continue
                if _intervals_overlap(
                    current.effective_from,
                    current.effective_until,
                    other.effective_from,
                    other.effective_until,
                ):
                    raise IdentityError("control-group binding intervals overlap")

    def _validate_accounts(self) -> None:
        agent_ids = {
            *(item.base_agent_id for item in self.accounts),
            *(item.subject_id for item in self.bindings if item.actor_kind == "agent"),
            *(item.agent_id for item in self.control_group_bindings),
        }
        if "treasury" in agent_ids or any(
            agent_id.startswith(("plan-escrow:", "task-escrow:", "triage-escrow:"))
            for agent_id in agent_ids
        ):
            raise IdentityError("reserved system account cannot be an Agent ID")
        known_accounts = {item.github_account_id for item in self.accounts}
        for binding in self.bindings:
            if binding.github_account_id not in known_accounts:
                raise IdentityError("binding references an unknown GitHub account")
        for account in self.accounts:
            if not any(
                binding.actor_kind == "agent"
                and binding.github_account_id == account.github_account_id
                and binding.subject_id == account.base_agent_id
                for binding in self.bindings
            ):
                raise IdentityError("base_agent_id must belong to its GitHub account")
        known_agents = {
            binding.subject_id
            for binding in self.bindings
            if binding.actor_kind == "agent"
        }
        if any(
            binding.agent_id not in known_agents
            for binding in self.control_group_bindings
        ):
            raise IdentityError("control group references an unknown Agent ID")

    def account(self, github_account_id: str) -> GitHubAccount:
        github_account_id = _text("github_account_id", github_account_id)
        matches = [
            item
            for item in self.accounts
            if item.github_account_id == github_account_id
        ]
        if len(matches) != 1:
            raise IdentityError("GitHub account must resolve exactly once")
        return matches[0]

    def register_agent(
        self,
        *,
        account: GitHubAccount,
        account_binding: Binding,
        control_group_binding: ControlGroupBinding,
    ) -> IdentityRegistry:
        """Atomically add one Agent mapping without changing an account's base."""
        if type(account) is not GitHubAccount:
            raise IdentityError("account must use the verified GitHubAccount record")
        if (
            type(account_binding) is not Binding
            or account_binding.actor_kind != "agent"
        ):
            raise IdentityError("account binding must be a verified Agent binding")
        if type(control_group_binding) is not ControlGroupBinding:
            raise IdentityError("control group must use the verified binding record")
        if account_binding.github_account_id != account.github_account_id:
            raise IdentityError("Agent binding does not belong to the GitHub account")
        if control_group_binding.agent_id != account_binding.subject_id:
            raise IdentityError("control-group binding does not belong to the Agent ID")
        existing_accounts = {item.github_account_id: item for item in self.accounts}
        existing_account = existing_accounts.get(account.github_account_id)
        if existing_account is not None:
            if existing_account.base_agent_id != account.base_agent_id:
                raise IdentityError("base_agent_id is immutable for a GitHub account")
            account = existing_account
        elif account_binding.subject_id != account.base_agent_id:
            raise IdentityError("first Agent binding must belong to base_agent_id")
        existing_binding = next(
            (
                item
                for item in self.bindings
                if item.binding_id == account_binding.binding_id
            ),
            None,
        )
        existing_group = next(
            (
                item
                for item in self.control_group_bindings
                if item.binding_id == control_group_binding.binding_id
            ),
            None,
        )
        if existing_binding is not None or existing_group is not None:
            if (
                existing_binding == account_binding
                and existing_group == control_group_binding
            ):
                return self
            raise IdentityError("registration binding ID already has other content")
        accounts = self.accounts
        if existing_account is None:
            accounts = (*accounts, account)
        return IdentityRegistry(
            accounts=accounts,
            bindings=(*self.bindings, account_binding),
            control_group_bindings=(
                *self.control_group_bindings,
                control_group_binding,
            ),
        )

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, object]:
        return {
            "accounts": [item.to_data() for item in self.accounts],
            "bindings": [item.to_data() for item in self.bindings],
            "control_group_bindings": [
                item.to_data() for item in self.control_group_bindings
            ],
        }


del _remember_registry_seal, _registry_seal


def resolve_binding(
    bindings: Iterable[Binding],
    *,
    github_account_id: str,
    subject_id: str,
    effective_at: datetime,
) -> Binding:
    github_account_id = _text("github_account_id", github_account_id)
    subject_id = _text("subject_id", subject_id)
    bindings = tuple(bindings)
    if any(type(binding) is not Binding for binding in bindings):
        raise IdentityError("bindings must use verified Binding records")
    matches = [
        binding
        for binding in bindings
        if binding.github_account_id == github_account_id
        and binding.subject_id == subject_id
        and binding.active_at(effective_at)
    ]
    if len(matches) != 1:
        raise IdentityError("identity binding must resolve to exactly one version")
    return matches[0]


def resolve_control_group_binding(
    bindings: Iterable[ControlGroupBinding],
    *,
    agent_id: str,
    effective_at: datetime,
) -> ControlGroupBinding:
    agent_id = _text("agent_id", agent_id)
    bindings = tuple(bindings)
    if any(type(binding) is not ControlGroupBinding for binding in bindings):
        raise IdentityError("control groups must use verified binding records")
    matches = [
        binding
        for binding in bindings
        if binding.agent_id == agent_id and binding.active_at(effective_at)
    ]
    if len(matches) != 1:
        raise IdentityError("control-group binding must resolve to exactly one version")
    return matches[0]


def authorize_agent(
    *,
    github_account_id: str,
    agent_id: str,
    effective_at: datetime,
    registry: IdentityRegistry,
) -> IdentityAuthority:
    if type(registry) is not IdentityRegistry:
        raise IdentityError("identity registry must use the verified record type")
    registry.account(github_account_id)
    account_binding = resolve_binding(
        tuple(
            binding for binding in registry.bindings if binding.actor_kind == "agent"
        ),
        github_account_id=github_account_id,
        subject_id=agent_id,
        effective_at=effective_at,
    )
    group_binding = resolve_control_group_binding(
        registry.control_group_bindings,
        agent_id=agent_id,
        effective_at=effective_at,
    )
    return IdentityAuthority(
        github_account_id=account_binding.github_account_id,
        agent_id=account_binding.subject_id,
        account_binding_id=account_binding.binding_id,
        account_binding_version=account_binding.version,
        control_group_id=group_binding.control_group_id,
        control_group_binding_id=group_binding.binding_id,
        control_group_binding_version=group_binding.version,
        effective_at=effective_at,
    )


def authorize_issue_author(
    *,
    author_agent_id: str,
    github_account_id: str,
    effective_at: datetime,
    registry: IdentityRegistry,
) -> IdentityAuthority:
    return authorize_agent(
        github_account_id=github_account_id,
        agent_id=_text("author_agent_id", author_agent_id),
        effective_at=effective_at,
        registry=registry,
    )


def authorize_manual_declaration(
    comment: str,
    *,
    github_account_id: str,
    effective_at: datetime,
    registry: IdentityRegistry,
) -> IdentityAuthority:
    declaration = parse_declaration(comment)
    if declaration is None:
        raise IdentityError("comment is not a WEA declaration")
    raw_agent_id = declaration.get("agent_id")
    if raw_agent_id is None:
        raise IdentityError("manual declaration requires agent_id")
    return authorize_agent(
        github_account_id=github_account_id,
        agent_id=_unquote(raw_agent_id),
        effective_at=effective_at,
        registry=registry,
    )


def select_cli_authority(
    *,
    selected_binding_ids: Iterable[str],
    github_account_id: str,
    effective_at: datetime,
    registry: IdentityRegistry,
) -> IdentityAuthority:
    selected_values = tuple(selected_binding_ids)
    if any(type(item) is not str or not item for item in selected_values):
        raise IdentityError("selected binding IDs must be non-empty strings")
    if len(selected_values) != 1:
        raise IdentityError("CLI requires exactly one selected active binding")
    selected = set(selected_values)
    matches = [
        binding
        for binding in registry.bindings
        if binding.binding_id in selected
        and binding.actor_kind == "agent"
        and binding.github_account_id == github_account_id
        and binding.active_at(effective_at)
    ]
    if len(matches) != 1:
        raise IdentityError("CLI requires exactly one selected active binding")
    return authorize_agent(
        github_account_id=github_account_id,
        agent_id=matches[0].subject_id,
        effective_at=effective_at,
        registry=registry,
    )


def control_disclosure_requirement(
    *,
    contract_id: str,
    work_id: str,
    author: IdentityAuthority,
    participant: IdentityAuthority,
    registry: IdentityRegistry,
) -> ControlDisclosure | None:
    if (
        type(author) is not IdentityAuthority
        or type(participant) is not IdentityAuthority
    ):
        raise IdentityError("identity authority must use the verified record type")
    if type(registry) is not IdentityRegistry:
        raise IdentityError("registry must use the verified identity record type")
    contract_id = _text("contract_id", contract_id)
    work_id = _text("work_id", work_id)
    resolved_author = authorize_agent(
        github_account_id=author.github_account_id,
        agent_id=author.agent_id,
        effective_at=author.effective_at,
        registry=registry,
    )
    resolved_participant = authorize_agent(
        github_account_id=participant.github_account_id,
        agent_id=participant.agent_id,
        effective_at=participant.effective_at,
        registry=registry,
    )
    if resolved_author != author or resolved_participant != participant:
        raise IdentityError("identity authority does not match registry")
    if author.agent_id == participant.agent_id:
        raise IdentityError("the same Agent ID cannot participate in its own contract")
    if author.effective_at != participant.effective_at:
        raise IdentityError("control groups must be resolved at one effective_at")
    if author.control_group_id != participant.control_group_id:
        return None
    return ControlDisclosure(
        contract_id=contract_id,
        work_id=work_id,
        control_group_id=author.control_group_id,
        author_agent_id=author.agent_id,
        participant_agent_id=participant.agent_id,
        author_group_binding_id=author.control_group_binding_id,
        author_group_binding_version=author.control_group_binding_version,
        participant_group_binding_id=participant.control_group_binding_id,
        participant_group_binding_version=participant.control_group_binding_version,
        effective_at=author.effective_at,
    )


__all__ = [
    "Binding",
    "ControlDisclosure",
    "ControlGroupBinding",
    "Declaration",
    "DeclarationError",
    "GitHubAccount",
    "IdentityAuthority",
    "IdentityError",
    "IdentityRegistry",
    "authorize_agent",
    "authorize_issue_author",
    "authorize_manual_declaration",
    "control_disclosure_requirement",
    "resolve_binding",
    "resolve_control_group_binding",
    "select_cli_authority",
]
