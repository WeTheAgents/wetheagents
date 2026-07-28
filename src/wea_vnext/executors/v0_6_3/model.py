"""Immutable protocol state, effects, and transition results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .canonical import canonical_hash
from .events import ConfirmedReadBoundary, GitHubEvent


@dataclass(frozen=True)
class ReadBlocker:
    """Durable reason why a repository read boundary cannot advance."""

    repository_id: str
    read_sequence: int
    outcome: str

    def __post_init__(self) -> None:
        if type(self.repository_id) is not str or not self.repository_id:
            raise ValueError("read blocker repository_id must be a non-empty string")
        if type(self.read_sequence) is not int or self.read_sequence < 1:
            raise ValueError("read blocker sequence must be a positive integer")
        if self.outcome not in {
            "read-incomplete",
            "boundary-conflict",
            "revision-conflict",
            "event-key-conflict",
        }:
            raise ValueError("read blocker outcome is not supported")

    def to_data(self) -> dict[str, str | int]:
        return {
            "outcome": self.outcome,
            "read_sequence": self.read_sequence,
            "repository_id": self.repository_id,
        }


@dataclass(frozen=True)
class ProtocolState:
    schema_version: int
    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str
    boundaries: tuple[ConfirmedReadBoundary, ...] = ()
    read_blockers: tuple[ReadBlocker, ...] = ()
    processed_event_keys: tuple[str, ...] = ()
    events: tuple[GitHubEvent, ...] = ()

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("protocol state schema_version must be 1")
        ordered_boundaries = tuple(
            sorted(self.boundaries, key=lambda boundary: boundary.repository_id)
        )
        if self.boundaries != ordered_boundaries:
            raise ValueError("protocol state boundaries must use repository ID order")
        repositories = [boundary.repository_id for boundary in self.boundaries]
        if len(repositories) != len(set(repositories)):
            raise ValueError("protocol state keeps one boundary per repository")
        ordered_blockers = tuple(
            sorted(self.read_blockers, key=lambda blocker: blocker.repository_id)
        )
        if self.read_blockers != ordered_blockers:
            raise ValueError(
                "protocol state read blockers must use repository ID order"
            )
        blocked_repositories = [
            blocker.repository_id for blocker in self.read_blockers
        ]
        if len(blocked_repositories) != len(set(blocked_repositories)):
            raise ValueError("protocol state keeps one read blocker per repository")
        boundaries_by_repository = {
            boundary.repository_id: boundary for boundary in self.boundaries
        }
        for blocker in self.read_blockers:
            boundary = boundaries_by_repository.get(blocker.repository_id)
            if boundary is None:
                continue
            if blocker.read_sequence < boundary.read_sequence or (
                blocker.outcome == "read-incomplete"
                and blocker.read_sequence == boundary.read_sequence
            ):
                raise ValueError("read blocker cannot precede confirmed state")
        ordered_events = tuple(
            sorted(self.events, key=lambda event: event.canonical_order_key)
        )
        if self.events != ordered_events:
            raise ValueError("protocol state events must use canonical GitHub order")
        revision_identities = [event.revision_identity for event in self.events]
        if len(revision_identities) != len(set(revision_identities)):
            raise ValueError(
                "protocol state cannot contain duplicate revision identities"
            )
        expected_keys = tuple(event.idempotency_key for event in self.events)
        if len(expected_keys) != len(set(expected_keys)):
            raise ValueError("protocol state cannot contain duplicate idempotency keys")
        if self.processed_event_keys != expected_keys:
            raise ValueError("processed_event_keys must exactly match canonical events")
        for event in self.events:
            boundary = boundaries_by_repository.get(event.repository_id)
            if boundary is None or event.effective_at > boundary.captured_at:
                raise ValueError(
                    "every protocol event must be covered by a confirmed boundary"
                )

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "boundaries": [boundary.to_data() for boundary in self.boundaries],
            "events": [event.to_data() for event in self.events],
            "executor_manifest_hash": self.executor_manifest_hash,
            "processed_event_keys": list(self.processed_event_keys),
            "read_blockers": [blocker.to_data() for blocker in self.read_blockers],
            "ruleset_hash": self.ruleset_hash,
            "schema_version": self.schema_version,
            "tide_interface_version": self.tide_interface_version,
        }


@dataclass(frozen=True)
class TransitionEffect:
    outcome: str
    event_key: str | None
    reason: str

    def to_data(self) -> dict[str, str | None]:
        return {
            "event_key": self.event_key,
            "outcome": self.outcome,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class TransitionResult:
    state: ProtocolState
    effects: tuple[TransitionEffect, ...]
