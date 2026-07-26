"""Versioned binding primitives used by the 0.6.0 executor."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone


class IdentityError(ValueError):
    """Raised when identity authority is absent or ambiguous."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IdentityError("binding timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Binding:
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
            if type(value) is not str or not value:
                raise IdentityError(f"{field} must be a non-empty string")
        if self.actor_kind not in {"agent", "agent0", "operator"}:
            raise IdentityError("actor_kind must be agent, agent0, or operator")
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
        ):
            raise IdentityError("binding version must be a positive integer")
        start = _utc(self.effective_from)
        end = None if self.effective_until is None else _utc(self.effective_until)
        if end is not None and end <= start:
            raise IdentityError("binding interval must be positive")
        object.__setattr__(self, "effective_from", start)
        object.__setattr__(self, "effective_until", end)

    def active_at(self, effective_at: datetime) -> bool:
        effective_at = _utc(effective_at)
        return self.effective_from <= effective_at and (
            self.effective_until is None or effective_at < self.effective_until
        )


def resolve_binding(
    bindings: Iterable[Binding],
    *,
    github_account_id: str,
    subject_id: str,
    effective_at: datetime,
) -> Binding:
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
