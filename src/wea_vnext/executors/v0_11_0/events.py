"""Canonical GitHub revision events and complete read boundaries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .canonical import canonical_hash, freeze_json, sha256_hex, thaw_json


class EventValidationError(ValueError):
    """Raised when a GitHub event cannot be ordered or replayed safely."""


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise EventValidationError(f"{field} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventValidationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _require_non_empty_string(value: Any, *, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise EventValidationError(f"{field} must be a non-empty string")


def timestamp_text(value: datetime) -> str:
    return (
        _utc(value, field="timestamp")
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class GitHubReadBoundary:
    repository: str
    repository_id: str
    captured_at: datetime
    read_sequence: int
    end_cursor: str
    complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.complete, bool):
            raise EventValidationError("complete must be a boolean")
        if not isinstance(self.repository, str) or "/" not in self.repository:
            raise EventValidationError("repository must use owner/name")
        _require_non_empty_string(self.repository_id, field="immutable repository_id")
        if (
            isinstance(self.read_sequence, bool)
            or not isinstance(self.read_sequence, int)
            or self.read_sequence < 1
        ):
            raise EventValidationError("read_sequence must be a positive integer")
        _require_non_empty_string(self.end_cursor, field="end_cursor")
        object.__setattr__(
            self, "captured_at", _utc(self.captured_at, field="captured_at")
        )

    @property
    def order_key(self) -> int:
        return self.read_sequence

    def to_data(self) -> dict[str, Any]:
        return {
            "captured_at": timestamp_text(self.captured_at),
            "complete": self.complete,
            "end_cursor": self.end_cursor,
            "read_sequence": self.read_sequence,
            "repository": self.repository,
            "repository_id": self.repository_id,
        }


@dataclass(frozen=True)
class GitHubEvent:
    repository_id: str
    object_kind: str
    object_id: str
    revision_id: str
    effective_at: datetime
    body: str
    content_hash: str
    actor_account_id: str
    payload: Any

    def __post_init__(self) -> None:
        _require_non_empty_string(self.repository_id, field="immutable repository_id")
        if not isinstance(self.object_kind, str) or self.object_kind not in {
            "issue",
            "issue_comment",
        }:
            raise EventValidationError("object_kind must be issue or issue_comment")
        for field, value in (
            ("object_id", self.object_id),
            ("revision_id", self.revision_id),
            ("actor_account_id", self.actor_account_id),
        ):
            _require_non_empty_string(value, field=field)
        if not isinstance(self.body, str):
            raise EventValidationError("body must be a string")
        object.__setattr__(
            self, "effective_at", _utc(self.effective_at, field="effective_at")
        )
        expected_hash = sha256_hex(self.body.encode("utf-8"))
        if self.content_hash != expected_hash:
            raise EventValidationError(
                "content_hash does not match the exact UTF-8 body"
            )
        object.__setattr__(self, "payload", freeze_json(self.payload))

    @classmethod
    def from_revision(
        cls,
        *,
        repository: str,
        repository_id: str,
        object_kind: str,
        object_id: str,
        revision_id: str,
        effective_at: datetime,
        body: str,
        actor_account_id: str,
        payload: Any,
    ) -> GitHubEvent:
        if not isinstance(repository, str) or "/" not in repository:
            raise EventValidationError("repository must use owner/name")
        return cls(
            repository_id=repository_id,
            object_kind=object_kind,
            object_id=object_id,
            revision_id=revision_id,
            effective_at=effective_at,
            body=body,
            content_hash=sha256_hex(body.encode("utf-8")),
            actor_account_id=actor_account_id,
            payload=payload,
        )

    @property
    def order_key(self) -> tuple[datetime, str, str]:
        return self.effective_at, self.object_id, self.revision_id

    @property
    def canonical_order_key(self) -> tuple[datetime, str, str, str]:
        """Return the ruleset order with a deterministic semantic tie-breaker."""
        return (*self.order_key, self.semantic_fingerprint)

    @property
    def revision_identity(self) -> tuple[str, str, str, str]:
        return self.repository_id, self.object_kind, self.object_id, self.revision_id

    @property
    def idempotency_key(self) -> str:
        digest = canonical_hash(
            {
                "content_hash": self.content_hash,
                "object_id": self.object_id,
                "object_kind": self.object_kind,
                "repository_id": self.repository_id,
                "revision_id": self.revision_id,
            }
        )
        return f"github-event:{digest}"

    @property
    def semantic_fingerprint(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "actor_account_id": self.actor_account_id,
            "body": self.body,
            "content_hash": self.content_hash,
            "effective_at": timestamp_text(self.effective_at),
            "idempotency_key": self.idempotency_key,
            "object_id": self.object_id,
            "object_kind": self.object_kind,
            "payload": thaw_json(self.payload),
            "repository_id": self.repository_id,
            "revision_id": self.revision_id,
        }


@dataclass(frozen=True)
class GitHubEventBatch:
    boundary: GitHubReadBoundary
    events: tuple[GitHubEvent, ...]

    def __init__(self, *, boundary: GitHubReadBoundary, events: Any) -> None:
        event_tuple = tuple(events)
        if any(event.repository_id != boundary.repository_id for event in event_tuple):
            raise EventValidationError(
                "all events must belong to the boundary repository ID"
            )
        if any(event.effective_at > boundary.captured_at for event in event_tuple):
            raise EventValidationError("event cannot occur after its read boundary")
        object.__setattr__(self, "boundary", boundary)
        object.__setattr__(self, "events", event_tuple)

    @property
    def ordered_events(self) -> tuple[GitHubEvent, ...]:
        return tuple(sorted(self.events, key=lambda event: event.canonical_order_key))

    def to_data(self) -> dict[str, Any]:
        return {
            "boundary": self.boundary.to_data(),
            "events": [event.to_data() for event in self.ordered_events],
        }

    @property
    def batch_hash(self) -> str:
        return canonical_hash(self.to_data())


@dataclass(frozen=True)
class ConfirmedReadBoundary:
    """A read boundary paired with the exact accepted pagination snapshot."""

    boundary: GitHubReadBoundary
    batch_hash: str

    def __post_init__(self) -> None:
        if not self.boundary.complete:
            raise EventValidationError(
                "confirmed read boundary must come from a complete read"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.batch_hash):
            raise EventValidationError("batch_hash must be a SHA-256 digest")

    @property
    def repository(self) -> str:
        return self.boundary.repository

    @property
    def repository_id(self) -> str:
        return self.boundary.repository_id

    @property
    def captured_at(self) -> datetime:
        return self.boundary.captured_at

    @property
    def read_sequence(self) -> int:
        return self.boundary.read_sequence

    @property
    def end_cursor(self) -> str:
        return self.boundary.end_cursor

    @property
    def order_key(self) -> int:
        return self.boundary.order_key

    def to_data(self) -> dict[str, Any]:
        return {"batch_hash": self.batch_hash, **self.boundary.to_data()}
