"""Pure state transitions for the 0.6.0 protocol event envelope."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from .events import ConfirmedReadBoundary, GitHubEvent, GitHubEventBatch
from .model import ProtocolState, ReadBlocker, TransitionEffect, TransitionResult


def _apply_events(
    state: ProtocolState,
    events: Iterable[GitHubEvent],
    *,
    boundaries: tuple[ConfirmedReadBoundary, ...] | None = None,
    read_blockers: tuple[ReadBlocker, ...] | None = None,
) -> TransitionResult:
    """Apply a globally ordered event stream with one state rebuild."""
    if boundaries is None:
        raise ValueError("events must be applied through a confirmed batch")
    known_revisions = {
        event.revision_identity: event.semantic_fingerprint for event in state.events
    }
    known_keys = {
        event.idempotency_key: event.revision_identity for event in state.events
    }
    accepted: list[GitHubEvent] = []
    effects: list[TransitionEffect] = []
    for event in sorted(events, key=lambda item: item.canonical_order_key):
        key = event.idempotency_key
        fingerprint = event.semantic_fingerprint
        previous_fingerprint = known_revisions.get(event.revision_identity)
        if previous_fingerprint is not None:
            outcome = (
                "duplicate"
                if previous_fingerprint == fingerprint
                else "revision-conflict"
            )
            reason = (
                "exact revision already applied"
                if outcome == "duplicate"
                else "one immutable revision ID resolved to different semantic bytes"
            )
            effects.append(TransitionEffect(outcome, key, reason))
            continue
        previous_identity = known_keys.get(key)
        if (
            previous_identity is not None
            and previous_identity != event.revision_identity
        ):
            effects.append(
                TransitionEffect("event-key-conflict", key, "event key collision")
            )
            continue
        known_revisions[event.revision_identity] = fingerprint
        known_keys[key] = event.revision_identity
        accepted.append(event)
        effects.append(
            TransitionEffect("accepted", key, "canonical GitHub revision recorded")
        )

    if not accepted:
        next_state = (
            state
            if boundaries is None and read_blockers is None
            else replace(
                state,
                boundaries=state.boundaries if boundaries is None else boundaries,
                read_blockers=(
                    state.read_blockers if read_blockers is None else read_blockers
                ),
            )
        )
        return TransitionResult(next_state, tuple(effects))
    ordered_events = tuple(
        sorted(
            (*state.events, *accepted),
            key=lambda item: item.canonical_order_key,
        )
    )
    next_state = replace(
        state,
        boundaries=state.boundaries if boundaries is None else boundaries,
        read_blockers=(
            state.read_blockers if read_blockers is None else read_blockers
        ),
        processed_event_keys=tuple(item.idempotency_key for item in ordered_events),
        events=ordered_events,
    )
    return TransitionResult(next_state, tuple(effects))


def _batch_order(batch: GitHubEventBatch) -> tuple[object, ...]:
    return (
        batch.boundary.repository_id,
        batch.boundary.read_sequence,
        batch.boundary.captured_at,
        batch.batch_hash,
    )


def apply_batches(
    state: ProtocolState, batches: Iterable[GitHubEventBatch]
) -> TransitionResult:
    """Validate read windows atomically, then apply all accepted events globally."""
    boundaries = {boundary.repository_id: boundary for boundary in state.boundaries}
    known_revisions = {
        event.revision_identity: event.semantic_fingerprint for event in state.events
    }
    known_keys = {
        event.idempotency_key: event.revision_identity for event in state.events
    }
    accepted_events: list[GitHubEvent] = []
    batch_effects: list[TransitionEffect] = []
    read_blockers = {
        blocker.repository_id: blocker for blocker in state.read_blockers
    }

    ordered_batches = tuple(sorted(batches, key=_batch_order))
    hashes_by_boundary: dict[tuple[str, int], set[str]] = {}
    for batch in ordered_batches:
        if not batch.boundary.complete:
            continue
        identity = (batch.boundary.repository_id, batch.boundary.read_sequence)
        hashes_by_boundary.setdefault(identity, set()).add(batch.batch_hash)
    divergent_boundaries = {
        identity for identity, hashes in hashes_by_boundary.items() if len(hashes) > 1
    }

    for batch in ordered_batches:
        boundary_identity = (
            batch.boundary.repository_id,
            batch.boundary.read_sequence,
        )
        repository_id = batch.boundary.repository_id
        previous_boundary = boundaries.get(repository_id)
        if boundary_identity in divergent_boundaries:
            if (
                previous_boundary is not None
                and batch.boundary.order_key < previous_boundary.order_key
            ):
                batch_effects.append(
                    TransitionEffect(
                        "boundary-stale",
                        None,
                        "read boundary precedes confirmed state",
                    )
                )
                continue
            read_blockers[repository_id] = ReadBlocker(
                repository_id,
                batch.boundary.read_sequence,
                "boundary-conflict",
            )
            batch_effects.append(
                TransitionEffect(
                    "boundary-conflict",
                    None,
                    "one immutable read boundary resolved to different batch bytes",
                )
            )
            continue

        blocker = read_blockers.get(repository_id)
        if blocker is not None:
            retry_resolves_incomplete = (
                blocker.outcome == "read-incomplete"
                and batch.boundary.complete
                and batch.boundary.read_sequence == blocker.read_sequence
            )
            if retry_resolves_incomplete:
                del read_blockers[repository_id]
            else:
                outcome = (
                    "read-incomplete"
                    if blocker.outcome == "read-incomplete"
                    else "boundary-conflict"
                )
                batch_effects.append(
                    TransitionEffect(
                        outcome,
                        None,
                        "repository has an unresolved earlier read blocker",
                    )
                )
                continue

        if not batch.boundary.complete:
            confirmed_sequence = (
                previous_boundary.read_sequence
                if previous_boundary is not None
                else 0
            )
            has_complete_retry = boundary_identity in hashes_by_boundary
            if (
                batch.boundary.read_sequence > confirmed_sequence
                and not has_complete_retry
            ):
                read_blockers[repository_id] = ReadBlocker(
                    repository_id,
                    batch.boundary.read_sequence,
                    "read-incomplete",
                )
            batch_effects.append(
                TransitionEffect(
                    "read-incomplete", None, "GitHub pagination was incomplete"
                )
            )
            continue
        if previous_boundary is not None:
            if batch.boundary.order_key < previous_boundary.order_key:
                batch_effects.append(
                    TransitionEffect(
                        "boundary-stale",
                        None,
                        "read boundary precedes confirmed state",
                    )
                )
                continue
            if batch.boundary.order_key == previous_boundary.order_key:
                outcome = (
                    "boundary-duplicate"
                    if batch.batch_hash == previous_boundary.batch_hash
                    else "boundary-conflict"
                )
                reason = (
                    "exact read boundary already applied"
                    if outcome == "boundary-duplicate"
                    else "one immutable read boundary resolved to different batch bytes"
                )
                batch_effects.append(TransitionEffect(outcome, None, reason))
                if outcome == "boundary-conflict":
                    read_blockers[repository_id] = ReadBlocker(
                        repository_id,
                        batch.boundary.read_sequence,
                        outcome,
                    )
                continue
            if batch.boundary.captured_at < previous_boundary.captured_at:
                batch_effects.append(
                    TransitionEffect(
                        "boundary-stale",
                        None,
                        "read capture time precedes confirmed state",
                    )
                )
                continue
        batch_revisions: dict[tuple[str, str, str, str], str] = {}
        batch_keys: dict[str, tuple[str, str, str, str]] = {}
        conflict: TransitionEffect | None = None
        for event in batch.ordered_events:
            fingerprint = event.semantic_fingerprint
            previous_fingerprint = batch_revisions.get(
                event.revision_identity,
                known_revisions.get(event.revision_identity),
            )
            if previous_fingerprint is not None and previous_fingerprint != fingerprint:
                conflict = TransitionEffect(
                    "revision-conflict",
                    event.idempotency_key,
                    "complete batch contains conflicting semantic bytes",
                )
                break
            previous_identity = batch_keys.get(
                event.idempotency_key,
                known_keys.get(event.idempotency_key),
            )
            if (
                previous_identity is not None
                and previous_identity != event.revision_identity
            ):
                conflict = TransitionEffect(
                    "event-key-conflict",
                    event.idempotency_key,
                    "complete batch contains an event key collision",
                )
                break
            batch_revisions[event.revision_identity] = fingerprint
            batch_keys[event.idempotency_key] = event.revision_identity
        if conflict is not None:
            batch_effects.append(conflict)
            read_blockers[repository_id] = ReadBlocker(
                repository_id,
                batch.boundary.read_sequence,
                conflict.outcome,
            )
            continue

        known_revisions.update(batch_revisions)
        known_keys.update(batch_keys)
        accepted_events.extend(batch.ordered_events)
        boundaries[batch.boundary.repository_id] = ConfirmedReadBoundary(
            boundary=batch.boundary,
            batch_hash=batch.batch_hash,
        )
        batch_effects.append(
            TransitionEffect("boundary-advanced", None, batch.boundary.end_cursor)
        )

    event_result = _apply_events(
        state,
        accepted_events,
        boundaries=tuple(boundaries[key] for key in sorted(boundaries)),
        read_blockers=tuple(read_blockers[key] for key in sorted(read_blockers)),
    )
    return TransitionResult(
        event_result.state,
        (*event_result.effects, *batch_effects),
    )


def apply_batch(state: ProtocolState, batch: GitHubEventBatch) -> TransitionResult:
    """Atomically apply one complete read window and advance its boundary."""
    return apply_batches(state, (batch,))
