"""Self-contained executor for WEA ruleset and Tide interface 0.6."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .canonical import canonical_dumps
from .events import (
    ConfirmedReadBoundary,
    GitHubEvent,
    GitHubEventBatch,
    GitHubReadBoundary,
)
from .model import ProtocolState, ReadBlocker, TransitionEffect, TransitionResult
from .transition import _batch_order
from .transition import apply_batch as _apply_batch
from .transition import apply_batches as _apply_batches

_VERIFIED_RUNTIME: tuple[str, str, str] | None = None


def initial_state(runtime: Any) -> ProtocolState:
    """Create an empty state pinned to an already verified runtime triple."""
    ruleset_hash, interface_version, manifest_hash = _snapshot_runtime(runtime)
    if (ruleset_hash, interface_version, manifest_hash) != _verified_runtime():
        raise ValueError("runtime triple does not belong to the selected executor")
    return ProtocolState(
        schema_version=1,
        ruleset_hash=ruleset_hash,
        tide_interface_version=interface_version,
        executor_manifest_hash=manifest_hash,
    )


def apply_batch(state: ProtocolState, batch: GitHubEventBatch) -> TransitionResult:
    snapshot = _snapshot_batches((batch,))[0]
    local_state = _rebuild_state(_snapshot_state(state))
    return _apply_batch(local_state, _rebuild_batch(snapshot))


def serialize_state(state: ProtocolState) -> bytes:
    local_state = _rebuild_state(_snapshot_state(state))
    return canonical_dumps(local_state.to_data())


def serialize_report(
    state: ProtocolState,
    effects: Iterable[TransitionEffect],
    batch_hashes: Iterable[str],
    read_attempts: Iterable[tuple[str, Any]],
) -> bytes:
    local_state = _rebuild_state(_snapshot_state(state))
    local_effects = tuple(_rebuild_effect(effect) for effect in effects)
    local_hashes = tuple(_snapshot_json(batch_hash) for batch_hash in batch_hashes)
    local_attempts = tuple(
        (
            _snapshot_json(batch_hash),
            _rebuild_boundary(_snapshot_boundary(boundary)),
        )
        for batch_hash, boundary in read_attempts
    )
    return canonical_dumps(
        {
            "batch_hashes": list(local_hashes),
            "effects": [effect.to_data() for effect in local_effects],
            "read_attempts": [
                {
                    "batch_hash": batch_hash,
                    "boundary": boundary.to_data(),
                }
                for batch_hash, boundary in local_attempts
            ],
            "state": local_state.to_data(),
            "state_sha256": local_state.state_hash,
        }
    )


def _snapshot_json(value: Any) -> Any:
    """Detach JSON input inside this manifest-pinned executor."""
    if value is None or type(value) in {bool, int, float}:
        return value
    if isinstance(value, str):
        return str.__getitem__(value, slice(None))
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, Mapping):
        return {
            _snapshot_json(key): _snapshot_json(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_snapshot_json(item) for item in value]
    raise TypeError(f"unsupported replay payload value: {type(value).__name__}")


def _raw_field(value: Any, name: str) -> Any:
    """Read a dataclass field without accepting a subclass property override."""
    try:
        storage = object.__getattribute__(value, "__dict__")
    except AttributeError:
        storage = None
    if isinstance(storage, dict) and name in storage:
        return storage[name]
    return getattr(value, name)


def _snapshot_runtime(runtime: Any) -> tuple[Any, Any, Any]:
    if isinstance(runtime, tuple) and tuple.__len__(runtime) == 3:
        values = tuple(tuple.__getitem__(runtime, index) for index in range(3))
    else:
        values = (
            _raw_field(runtime, "ruleset_hash"),
            _raw_field(runtime, "tide_interface_version"),
            _raw_field(runtime, "executor_manifest_hash"),
        )
    return tuple(_snapshot_json(value) for value in values)  # type: ignore[return-value]


def _bind_verified_runtime(runtime: Any) -> None:
    """Bind this source closure once to the reference established by the verifier."""
    global _VERIFIED_RUNTIME
    candidate = _snapshot_runtime(runtime)
    if any(type(value) is not str for value in candidate):
        raise ValueError("verified runtime triple must contain exact strings")
    if _VERIFIED_RUNTIME is not None and _VERIFIED_RUNTIME != candidate:
        raise ValueError("executor is already bound to a different runtime triple")
    _VERIFIED_RUNTIME = candidate


def _verified_runtime() -> tuple[str, str, str]:
    if _VERIFIED_RUNTIME is None:
        raise ValueError("executor must be loaded through the manifest verifier")
    return _VERIFIED_RUNTIME


def _snapshot_datetime(value: Any) -> Any:
    if type(value) is datetime:
        return value
    if isinstance(value, datetime):
        return datetime(
            datetime.year.__get__(value, datetime),
            datetime.month.__get__(value, datetime),
            datetime.day.__get__(value, datetime),
            datetime.hour.__get__(value, datetime),
            datetime.minute.__get__(value, datetime),
            datetime.second.__get__(value, datetime),
            datetime.microsecond.__get__(value, datetime),
            tzinfo=datetime.tzinfo.__get__(value, datetime),
            fold=datetime.fold.__get__(value, datetime),
        )
    return value


def _snapshot_boundary(boundary: Any) -> dict[str, Any]:
    return {
        "captured_at": _snapshot_datetime(_raw_field(boundary, "captured_at")),
        "complete": _snapshot_json(_raw_field(boundary, "complete")),
        "end_cursor": _snapshot_json(_raw_field(boundary, "end_cursor")),
        "read_sequence": _snapshot_json(_raw_field(boundary, "read_sequence")),
        "repository": _snapshot_json(_raw_field(boundary, "repository")),
        "repository_id": _snapshot_json(_raw_field(boundary, "repository_id")),
    }


def _snapshot_event(event: Any) -> dict[str, Any]:
    return {
        "actor_account_id": _snapshot_json(_raw_field(event, "actor_account_id")),
        "body": _snapshot_json(_raw_field(event, "body")),
        "content_hash": _snapshot_json(_raw_field(event, "content_hash")),
        "effective_at": _snapshot_datetime(_raw_field(event, "effective_at")),
        "object_id": _snapshot_json(_raw_field(event, "object_id")),
        "object_kind": _snapshot_json(_raw_field(event, "object_kind")),
        "payload": _snapshot_json(_raw_field(event, "payload")),
        "repository_id": _snapshot_json(_raw_field(event, "repository_id")),
        "revision_id": _snapshot_json(_raw_field(event, "revision_id")),
    }


def _snapshot_batches(batches: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """Select raw adapter fields without trusting foreign derived behavior."""
    snapshots: list[dict[str, Any]] = []
    for batch in batches:
        boundary = _raw_field(batch, "boundary")
        events = _raw_field(batch, "events")
        snapshots.append(
            {
                "boundary": _snapshot_boundary(boundary),
                "events": [_snapshot_event(event) for event in events],
            }
        )
    return tuple(snapshots)


def _snapshot_state(state: Any) -> dict[str, Any]:
    boundaries = _raw_field(state, "boundaries")
    read_blockers = _raw_field(state, "read_blockers")
    events = _raw_field(state, "events")
    return {
        "schema_version": _snapshot_json(_raw_field(state, "schema_version")),
        "ruleset_hash": _snapshot_json(_raw_field(state, "ruleset_hash")),
        "tide_interface_version": _snapshot_json(
            _raw_field(state, "tide_interface_version")
        ),
        "executor_manifest_hash": _snapshot_json(
            _raw_field(state, "executor_manifest_hash")
        ),
        "boundaries": [
            {
                "boundary": _snapshot_boundary(_raw_field(item, "boundary")),
                "batch_hash": _snapshot_json(_raw_field(item, "batch_hash")),
            }
            for item in boundaries
        ],
        "read_blockers": [
            {
                "outcome": _snapshot_json(_raw_field(item, "outcome")),
                "read_sequence": _snapshot_json(
                    _raw_field(item, "read_sequence")
                ),
                "repository_id": _snapshot_json(
                    _raw_field(item, "repository_id")
                ),
            }
            for item in read_blockers
        ],
        "processed_event_keys": [
            _snapshot_json(item)
            for item in _raw_field(state, "processed_event_keys")
        ],
        "events": [_snapshot_event(event) for event in events],
    }


def _rebuild_boundary(data: Mapping[str, Any]) -> GitHubReadBoundary:
    return GitHubReadBoundary(
        repository=data["repository"],
        repository_id=data["repository_id"],
        captured_at=data["captured_at"],
        read_sequence=data["read_sequence"],
        end_cursor=data["end_cursor"],
        complete=data["complete"],
    )


def _rebuild_event(data: Mapping[str, Any]) -> GitHubEvent:
    return GitHubEvent(
        repository_id=data["repository_id"],
        object_kind=data["object_kind"],
        object_id=data["object_id"],
        revision_id=data["revision_id"],
        effective_at=data["effective_at"],
        body=data["body"],
        content_hash=data["content_hash"],
        actor_account_id=data["actor_account_id"],
        payload=data["payload"],
    )


def _rebuild_state(data: Mapping[str, Any]) -> ProtocolState:
    state = ProtocolState(
        schema_version=data["schema_version"],
        ruleset_hash=data["ruleset_hash"],
        tide_interface_version=data["tide_interface_version"],
        executor_manifest_hash=data["executor_manifest_hash"],
        boundaries=tuple(
            ConfirmedReadBoundary(
                boundary=_rebuild_boundary(item["boundary"]),
                batch_hash=item["batch_hash"],
            )
            for item in data["boundaries"]
        ),
        read_blockers=tuple(
            ReadBlocker(
                repository_id=item["repository_id"],
                read_sequence=item["read_sequence"],
                outcome=item["outcome"],
            )
            for item in data["read_blockers"]
        ),
        processed_event_keys=tuple(data["processed_event_keys"]),
        events=tuple(_rebuild_event(item) for item in data["events"]),
    )
    state_runtime = (
        state.ruleset_hash,
        state.tide_interface_version,
        state.executor_manifest_hash,
    )
    if state_runtime != _verified_runtime():
        raise ValueError("state runtime triple does not belong to this executor")
    return state


def _rebuild_effect(effect: Any) -> TransitionEffect:
    return TransitionEffect(
        outcome=_snapshot_json(_raw_field(effect, "outcome")),
        event_key=_snapshot_json(_raw_field(effect, "event_key")),
        reason=_snapshot_json(_raw_field(effect, "reason")),
    )


def _rebuild_batch(data: Mapping[str, Any]) -> GitHubEventBatch:
    """Reconstruct inputs with this executor's exact, manifest-pinned classes."""
    boundary_data = data["boundary"]
    event_data = data["events"]
    if not isinstance(boundary_data, Mapping) or not isinstance(event_data, list):
        raise TypeError("replay input must contain one boundary and an event list")
    boundary = _rebuild_boundary(boundary_data)
    events = []
    for item in event_data:
        if not isinstance(item, Mapping):
            raise TypeError("replay event input must be a mapping")
        events.append(_rebuild_event(item))
    return GitHubEventBatch(boundary=boundary, events=events)


def replay(batches: Iterable[Any], runtime: Any) -> tuple[Any, ...]:
    """Replay complete windows in canonical order inside the versioned closure."""
    state = initial_state(runtime)
    rebuilt_batches = tuple(
        _rebuild_batch(batch) for batch in _snapshot_batches(batches)
    )
    ordered_batches = sorted(rebuilt_batches, key=_batch_order)
    result = _apply_batches(state, ordered_batches)
    state = result.state
    frozen_effects = result.effects
    read_attempts = tuple(
        (batch.batch_hash, batch.boundary) for batch in ordered_batches
    )
    frozen_hashes = tuple(batch_hash for batch_hash, _boundary in read_attempts)
    return (
        state,
        frozen_effects,
        frozen_hashes,
        read_attempts,
        serialize_state(state),
        serialize_report(state, frozen_effects, frozen_hashes, read_attempts),
    )


__all__ = [
    "apply_batch",
    "initial_state",
    "replay",
    "serialize_report",
    "serialize_state",
]
