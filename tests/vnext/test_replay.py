from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from time import perf_counter
from types import SimpleNamespace

import pytest

import wea_vnext.store as vnext_store
from wea_vnext.engine import (
    ExecutorDescriptor,
    ExecutorRegistry,
    RuntimeReference,
    installed_executor,
    load_executor,
)
from wea_vnext.executors.v0_6_0.events import (
    ConfirmedReadBoundary,
    EventValidationError,
    GitHubEvent,
    GitHubEventBatch,
    GitHubReadBoundary,
)
from wea_vnext.executors.v0_6_0.model import ProtocolState
from wea_vnext.store import replay, write_shadow_report

REPOSITORY = "WeTheAgents/wetheagents"
REPOSITORY_ID = "R_kgDOWeTheAgents"
OTHER_REPOSITORY_ID = "R_kgDOOther"
T0 = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def _event(
    *,
    revision: str,
    at: datetime,
    body: str,
    repository: str = REPOSITORY,
    repository_id: str = REPOSITORY_ID,
    actor_account_id: str = "U_kgDOExample",
    payload: object | None = None,
) -> GitHubEvent:
    return GitHubEvent.from_revision(
        repository=repository,
        repository_id=repository_id,
        object_kind="issue_comment",
        object_id="IC_kwDOExample",
        revision_id=revision,
        effective_at=at,
        body=body,
        actor_account_id=actor_account_id,
        payload=({"declaration": "deliverable"} if payload is None else payload),
    )


def _batch(
    *events: GitHubEvent,
    cursor: str = "cursor-1",
    complete: bool = True,
    captured_at: datetime | None = None,
    repository: str = REPOSITORY,
    repository_id: str = REPOSITORY_ID,
    read_sequence: int = 1,
) -> GitHubEventBatch:
    return GitHubEventBatch(
        boundary=GitHubReadBoundary(
            repository=repository,
            repository_id=repository_id,
            captured_at=captured_at or T0 + timedelta(hours=1),
            read_sequence=read_sequence,
            end_cursor=cursor,
            complete=complete,
        ),
        events=events,
    )


@pytest.mark.parametrize("repository_id", [123, True, object()])
def test_repository_id_must_be_a_non_empty_string(repository_id: object) -> None:
    with pytest.raises(EventValidationError, match="non-empty string"):
        GitHubReadBoundary(
            repository=REPOSITORY,
            repository_id=repository_id,  # type: ignore[arg-type]
            captured_at=T0,
            read_sequence=1,
            end_cursor="cursor-1",
            complete=True,
        )

    with pytest.raises(EventValidationError, match="non-empty string"):
        _event(
            revision="edit-A1",
            at=T0,
            body="A",
            repository_id=repository_id,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("end_cursor", [123, True, object(), ""])
def test_read_boundary_requires_a_non_empty_string_cursor(end_cursor: object) -> None:
    with pytest.raises(EventValidationError, match=r"end_cursor.*non-empty string"):
        GitHubReadBoundary(
            repository=REPOSITORY,
            repository_id=REPOSITORY_ID,
            captured_at=T0,
            read_sequence=1,
            end_cursor=end_cursor,  # type: ignore[arg-type]
            complete=True,
        )


@pytest.mark.parametrize("field", ["object_id", "revision_id", "actor_account_id"])
@pytest.mark.parametrize("value", [123, True, object(), ""])
def test_event_permanent_ids_must_be_non_empty_strings(
    field: str, value: object
) -> None:
    baseline = _event(revision="edit-A", at=T0, body="A")
    values = {
        "repository_id": baseline.repository_id,
        "object_kind": baseline.object_kind,
        "object_id": baseline.object_id,
        "revision_id": baseline.revision_id,
        "effective_at": baseline.effective_at,
        "body": baseline.body,
        "content_hash": baseline.content_hash,
        "actor_account_id": baseline.actor_account_id,
        "payload": baseline.payload,
    }
    values[field] = value

    with pytest.raises(EventValidationError, match=f"{field}.*non-empty string"):
        GitHubEvent(**values)  # type: ignore[arg-type]


def test_replay_orders_events_and_preserves_a_to_b_to_a_revisions() -> None:
    event_a1 = _event(revision="edit-A1", at=T0, body="A")
    event_b = _event(revision="edit-B", at=T0 + timedelta(seconds=1), body="B")
    event_a2 = _event(revision="edit-A2", at=T0 + timedelta(seconds=2), body="A")
    descriptor = installed_executor("0.6.0")

    ordered = replay([_batch(event_a1, event_b, event_a2)], descriptor.reference)
    scrambled = replay([_batch(event_a2, event_a1, event_b)], descriptor.reference)

    assert ordered.state_bytes == scrambled.state_bytes
    assert ordered.report_bytes == scrambled.report_bytes
    assert len(ordered.state.events) == 3
    assert event_a1.content_hash == event_a2.content_hash
    assert event_a1.idempotency_key != event_a2.idempotency_key
    assert [item.revision_id for item in ordered.state.events] == [
        "edit-A1",
        "edit-B",
        "edit-A2",
    ]


def test_adding_a_future_executor_does_not_change_existing_replay_bytes() -> None:
    event = _event(revision="edit-A", at=T0, body="A")
    current = installed_executor("0.6.0")
    future_reference = current.reference._replace(
        ruleset_hash="1" * 64,
        executor_manifest_hash="2" * 64,
    )
    extended_registry = ExecutorRegistry(
        (
            current,
            ExecutorDescriptor(
                reference=future_reference,
                module_name="future.executor",
            ),
        )
    )

    before = replay([_batch(event)], current.reference)
    after = replay(
        [_batch(event)],
        current.reference,
        registry=extended_registry,
    )

    assert after.state_bytes == before.state_bytes
    assert after.report_bytes == before.report_bytes


def test_duplicate_event_is_idempotent() -> None:
    event = _event(revision="edit-A", at=T0, body="A")
    report = replay([_batch(event, event)], installed_executor("0.6.0").reference)

    assert len(report.state.events) == 1
    assert [effect.outcome for effect in report.effects].count("accepted") == 1
    assert [effect.outcome for effect in report.effects].count("duplicate") == 1


def test_same_immutable_revision_id_cannot_resolve_to_different_content() -> None:
    first = _event(revision="edit-A", at=T0, body="A")
    conflicting = _event(
        revision="edit-A",
        at=T0 + timedelta(seconds=1),
        body="different bytes",
    )

    descriptor = installed_executor("0.6.0")
    forward = replay([_batch(first, conflicting)], descriptor.reference)
    reverse = replay([_batch(conflicting, first)], descriptor.reference)

    assert forward.state_bytes == reverse.state_bytes
    assert forward.report_bytes == reverse.report_bytes
    assert len(forward.state.events) == 0
    assert forward.state.boundaries == ()
    assert [effect.outcome for effect in forward.effects] == ["revision-conflict"]


@pytest.mark.parametrize(
    "changed",
    [
        {"actor_account_id": "U_other"},
        {"at": T0 + timedelta(seconds=1)},
        {"payload": {"declaration": "different"}},
    ],
)
def test_same_revision_with_different_semantics_fails_closed(
    changed: dict[str, object],
) -> None:
    baseline = {
        "revision": "edit-A",
        "at": T0,
        "body": "A",
        "actor_account_id": "U_kgDOExample",
        "payload": {"declaration": "deliverable"},
    }
    first = _event(**baseline)
    conflicting = _event(**(baseline | changed))
    descriptor = installed_executor("0.6.0")

    forward = replay([_batch(first, conflicting)], descriptor.reference)
    reverse = replay([_batch(conflicting, first)], descriptor.reference)

    assert forward.state_bytes == reverse.state_bytes
    assert forward.report_bytes == reverse.report_bytes
    assert forward.state.boundaries == ()
    assert [effect.outcome for effect in forward.effects] == ["revision-conflict"]


def test_event_payload_is_recursively_immutable() -> None:
    payload = {"declaration": {"targets": ["one"]}}
    event = _event(revision="edit-A", at=T0, body="A", payload=payload)
    report = replay([_batch(event)], installed_executor("0.6.0").reference)
    original_bytes = report.state_bytes

    payload["declaration"]["targets"].append("two")
    with pytest.raises(TypeError):
        event.payload["declaration"]["targets"][0] = "changed"

    assert report.state_bytes == original_bytes


def test_incomplete_read_applies_nothing_and_does_not_advance_boundary() -> None:
    first = _event(revision="edit-A", at=T0, body="A")
    second = _event(revision="edit-B", at=T0 + timedelta(seconds=1), body="B")
    descriptor = installed_executor("0.6.0")
    complete = replay([_batch(first, cursor="cursor-1")], descriptor.reference)
    partial = replay(
        [
            _batch(first, cursor="cursor-1"),
            _batch(
                second,
                cursor="cursor-2",
                complete=False,
                read_sequence=2,
            ),
        ],
        descriptor.reference,
    )

    assert [event.to_data() for event in partial.state.events] == [
        event.to_data() for event in complete.state.events
    ]
    assert partial.state.boundaries[0].end_cursor == "cursor-1"
    assert partial.state.read_blockers[0].read_sequence == 2
    assert partial.state.read_blockers[0].outcome == "read-incomplete"
    assert partial.effects[-1].outcome == "read-incomplete"


def test_complete_retry_after_incomplete_read_can_confirm_same_sequence() -> None:
    first = _event(revision="edit-A", at=T0, body="A")
    second = _event(revision="edit-B", at=T0 + timedelta(seconds=1), body="B")
    incomplete = _batch(first, complete=False, read_sequence=1)
    complete = _batch(first, second, complete=True, read_sequence=1)
    reference = installed_executor("0.6.0").reference

    forward = replay([incomplete, complete], reference)
    reverse = replay([complete, incomplete], reference)

    assert forward.report_bytes == reverse.report_bytes
    assert [event.revision_id for event in forward.state.events] == [
        "edit-A",
        "edit-B",
    ]
    assert forward.state.boundaries[0].batch_hash == complete.batch_hash
    assert {effect.outcome for effect in forward.effects} >= {
        "read-incomplete",
        "boundary-advanced",
    }
    assert forward.state.read_blockers == ()


def test_incomplete_read_blocks_a_later_sequence_in_the_same_replay() -> None:
    incomplete = _batch(
        _event(revision="edit-missed", at=T0, body="missed"),
        complete=False,
        read_sequence=1,
    )
    later = _batch(
        _event(revision="edit-later", at=T0 + timedelta(seconds=1), body="later"),
        cursor="cursor-2",
        captured_at=T0 + timedelta(hours=2),
        read_sequence=2,
    )

    report = replay([incomplete, later], installed_executor("0.6.0").reference)

    assert report.state.events == ()
    assert report.state.boundaries == ()
    assert report.state.read_blockers[0].read_sequence == 1
    assert [effect.outcome for effect in report.effects] == [
        "read-incomplete",
        "read-incomplete",
    ]


def test_incremental_complete_retry_resolves_an_incomplete_read_blocker() -> None:
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module
    incomplete = _batch(
        _event(revision="edit-A", at=T0, body="A"),
        complete=False,
        read_sequence=1,
    )
    complete = _batch(
        _event(revision="edit-A", at=T0, body="A"),
        _event(revision="edit-B", at=T0 + timedelta(seconds=1), body="B"),
        complete=True,
        read_sequence=1,
    )

    blocked = executor.apply_batch(executor.initial_state(reference), incomplete)
    resolved = executor.apply_batch(blocked.state, complete)

    assert blocked.state.read_blockers[0].outcome == "read-incomplete"
    assert resolved.state.read_blockers == ()
    assert [event.revision_id for event in resolved.state.events] == [
        "edit-A",
        "edit-B",
    ]


def test_restored_state_cannot_confirm_an_incomplete_read_boundary() -> None:
    incomplete = _batch(
        _event(revision="edit-incomplete", at=T0, body="incomplete"),
        complete=False,
        read_sequence=1,
    )

    with pytest.raises(
        EventValidationError,
        match="confirmed read boundary must come from a complete read",
    ):
        ConfirmedReadBoundary(
            boundary=incomplete.boundary,
            batch_hash=incomplete.batch_hash,
        )


@pytest.mark.parametrize("complete", [None, 0, 1, "false"])
def test_read_boundary_requires_an_exact_boolean(complete: object) -> None:
    with pytest.raises(EventValidationError, match="complete must be a boolean"):
        GitHubReadBoundary(
            repository=REPOSITORY,
            repository_id=REPOSITORY_ID,
            captured_at=T0,
            read_sequence=1,
            end_cursor="cursor",
            complete=complete,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("read_sequence", [None, 0, True, "1"])
def test_read_boundary_requires_a_positive_integer_sequence(
    read_sequence: object,
) -> None:
    with pytest.raises(EventValidationError, match="positive integer"):
        GitHubReadBoundary(
            repository=REPOSITORY,
            repository_id=REPOSITORY_ID,
            captured_at=T0,
            read_sequence=read_sequence,  # type: ignore[arg-type]
            end_cursor="opaque-cursor",
            complete=True,
        )


def test_batch_rejects_an_event_after_its_capture_boundary() -> None:
    event = _event(revision="future-edit", at=T0 + timedelta(hours=2), body="future")

    with pytest.raises(ValueError, match="after its read boundary"):
        _batch(event)


def test_replay_canonicalizes_batches_and_keeps_one_boundary_per_repository() -> None:
    other_repository = "WeTheAgents/other"
    first = _event(revision="edit-A", at=T0, body="A")
    second = _event(
        revision="edit-B",
        at=T0,
        body="B",
        repository=other_repository,
        repository_id=OTHER_REPOSITORY_ID,
    )
    batches = (
        _batch(
            first,
            cursor="cursor-a",
            captured_at=T0 + timedelta(minutes=2),
        ),
        _batch(
            second,
            cursor="cursor-b",
            captured_at=T0 + timedelta(minutes=1),
            repository=other_repository,
            repository_id=OTHER_REPOSITORY_ID,
        ),
    )
    descriptor = installed_executor("0.6.0")

    forward = replay(batches, descriptor.reference)
    reverse = replay(reversed(batches), descriptor.reference)

    assert forward.state_bytes == reverse.state_bytes
    assert forward.report_bytes == reverse.report_bytes
    assert {item.repository for item in forward.state.boundaries} == {
        REPOSITORY,
        other_repository,
    }
    assert len(forward.state.events) == 2


def test_replay_applies_events_globally_before_capture_order() -> None:
    other_repository = "WeTheAgents/other"
    newer = _event(
        revision="edit-newer",
        at=T0 + timedelta(minutes=20),
        body="newer",
    )
    older = _event(
        revision="edit-older",
        at=T0 + timedelta(minutes=10),
        body="older",
        repository=other_repository,
        repository_id=OTHER_REPOSITORY_ID,
    )
    batches = (
        _batch(
            newer,
            cursor="cursor-newer",
            captured_at=T0 + timedelta(minutes=30),
        ),
        _batch(
            older,
            cursor="cursor-older",
            captured_at=T0 + timedelta(minutes=40),
            repository=other_repository,
            repository_id=OTHER_REPOSITORY_ID,
        ),
    )
    descriptor = installed_executor("0.6.0")

    forward = replay(batches, descriptor.reference)
    reverse = replay(reversed(batches), descriptor.reference)
    accepted = [
        effect.event_key for effect in forward.effects if effect.outcome == "accepted"
    ]

    assert forward.report_bytes == reverse.report_bytes
    assert [event.revision_id for event in forward.state.events] == [
        "edit-older",
        "edit-newer",
    ]
    assert accepted == [older.idempotency_key, newer.idempotency_key]


def test_replay_one_thousand_events_stays_below_checkpoint_threshold() -> None:
    events = tuple(
        _event(
            revision=f"edit-{index:04}",
            at=T0 + timedelta(microseconds=index),
            body=str(index),
        )
        for index in range(1000)
    )

    started = perf_counter()
    report = replay([_batch(*events)], installed_executor("0.6.0").reference)
    elapsed = perf_counter() - started

    assert len(report.state.events) == 1000
    assert elapsed < 5.0


def test_opaque_cursors_use_explicit_read_sequence_in_both_input_orders() -> None:
    first = _event(revision="edit-A", at=T0, body="A")
    second = _event(revision="edit-B", at=T0, body="B")
    captured_at = T0 + timedelta(minutes=1)
    batches = (
        _batch(
            first,
            cursor="lexically-later-z",
            captured_at=captured_at,
            read_sequence=1,
        ),
        _batch(
            second,
            cursor="lexically-earlier-a",
            captured_at=captured_at,
            read_sequence=2,
        ),
    )
    descriptor = installed_executor("0.6.0")

    forward = replay(batches, descriptor.reference)
    reverse = replay(reversed(batches), descriptor.reference)

    assert forward.state_bytes == reverse.state_bytes
    assert forward.report_bytes == reverse.report_bytes
    assert len(forward.state.events) == 2
    assert forward.state.boundaries[0].end_cursor == "lexically-earlier-a"
    assert forward.state.boundaries[0].read_sequence == 2


def test_sequential_boundary_cannot_regress_by_read_sequence() -> None:
    event = _event(revision="edit-A", at=T0, body="A")
    captured_at = T0 + timedelta(minutes=1)
    descriptor = installed_executor("0.6.0")
    executor = load_executor(descriptor.reference).module
    state = executor.initial_state(descriptor.reference)

    after_newer = executor.apply_batch(
        state,
        _batch(
            event,
            cursor="lexically-earlier-a",
            captured_at=captured_at,
            read_sequence=2,
        ),
    )
    after_older = executor.apply_batch(
        after_newer.state,
        _batch(
            event,
            cursor="lexically-later-z",
            captured_at=captured_at,
            read_sequence=1,
        ),
    )

    assert after_older.state == after_newer.state
    assert after_older.effects[-1].outcome == "boundary-stale"


def test_higher_sequence_cannot_regress_capture_time() -> None:
    event = _event(revision="edit-A", at=T0, body="A")
    first = _batch(
        event,
        read_sequence=1,
        captured_at=T0 + timedelta(hours=2),
    )
    regressive = _batch(
        read_sequence=2,
        captured_at=T0 + timedelta(hours=1),
        cursor="cursor-2",
    )

    report = replay([first, regressive], installed_executor("0.6.0").reference)

    assert report.state.boundaries[0].read_sequence == 1
    assert report.state.boundaries[0].captured_at == first.boundary.captured_at
    assert any(
        effect.outcome == "boundary-stale"
        and "capture time" in effect.reason
        for effect in report.effects
    )


def test_protocol_state_requires_a_boundary_covering_every_event() -> None:
    reference = installed_executor("0.6.0").reference
    event = _event(revision="edit-uncovered", at=T0, body="uncovered")
    fields = {
        "schema_version": 1,
        "ruleset_hash": reference.ruleset_hash,
        "tide_interface_version": reference.tide_interface_version,
        "executor_manifest_hash": reference.executor_manifest_hash,
        "processed_event_keys": (event.idempotency_key,),
        "events": (event,),
    }

    with pytest.raises(ValueError, match="covered by a confirmed boundary"):
        ProtocolState(**fields)

    earlier = GitHubReadBoundary(
        repository=REPOSITORY,
        repository_id=REPOSITORY_ID,
        captured_at=T0 - timedelta(seconds=1),
        read_sequence=1,
        end_cursor="cursor-earlier",
        complete=True,
    )
    with pytest.raises(ValueError, match="covered by a confirmed boundary"):
        ProtocolState(
            **fields,
            boundaries=(
                ConfirmedReadBoundary(boundary=earlier, batch_hash="0" * 64),
            ),
        )


def test_repository_rename_uses_immutable_repository_id() -> None:
    before_rename = _event(revision="edit-A", at=T0, body="A")
    after_rename = _event(
        revision="edit-A",
        at=T0,
        body="A",
        repository="WeTheAgents/renamed",
    )
    report = replay(
        [
            _batch(before_rename, read_sequence=1),
            _batch(
                after_rename,
                repository="WeTheAgents/renamed",
                read_sequence=2,
            ),
        ],
        installed_executor("0.6.0").reference,
    )

    assert len(report.state.events) == 1
    assert len(report.state.boundaries) == 1
    assert report.state.boundaries[0].repository == "WeTheAgents/renamed"
    assert [effect.outcome for effect in report.effects].count("duplicate") == 1


def test_event_state_discards_mutable_repository_path() -> None:
    before_rename = _event(revision="edit-A", at=T0, body="A")
    after_rename = _event(
        revision="edit-A",
        at=T0,
        body="A",
        repository="WeTheAgents/renamed",
    )
    batch = _batch(
        before_rename,
        after_rename,
        repository="WeTheAgents/renamed",
    )
    reversed_batch = _batch(
        after_rename,
        before_rename,
        repository="WeTheAgents/renamed",
    )
    reference = installed_executor("0.6.0").reference

    forward = replay([batch], reference)
    reverse = replay([reversed_batch], reference)

    assert not hasattr(forward.state.events[0], "repository")
    assert forward.state_bytes == reverse.state_bytes
    assert forward.report_bytes == reverse.report_bytes


def test_divergent_batches_at_one_read_sequence_fail_closed() -> None:
    first = _batch(_event(revision="edit-A", at=T0, body="A"))
    second = _batch(_event(revision="edit-B", at=T0, body="B"))
    descriptor = installed_executor("0.6.0")

    forward = replay([first, second], descriptor.reference)
    reverse = replay([second, first], descriptor.reference)

    assert forward.report_bytes == reverse.report_bytes
    assert forward.state.events == ()
    assert forward.state.boundaries == ()
    assert [effect.outcome for effect in forward.effects] == [
        "boundary-conflict",
        "boundary-conflict",
    ]


def test_divergent_read_sequence_blocks_later_boundary_for_repository() -> None:
    first = _batch(_event(revision="edit-A", at=T0, body="A"))
    divergent = _batch(_event(revision="edit-B", at=T0, body="B"))
    later = _batch(
        _event(revision="edit-C", at=T0 + timedelta(seconds=1), body="C"),
        cursor="cursor-2",
        captured_at=T0 + timedelta(hours=2),
        read_sequence=2,
    )
    descriptor = installed_executor("0.6.0")

    forward = replay([first, divergent, later], descriptor.reference)
    reverse = replay([later, divergent, first], descriptor.reference)

    assert forward.report_bytes == reverse.report_bytes
    assert forward.state.events == ()
    assert forward.state.boundaries == ()
    assert [effect.outcome for effect in forward.effects] == [
        "boundary-conflict",
        "boundary-conflict",
        "boundary-conflict",
    ]


def test_confirmed_boundary_rejects_later_divergent_batch() -> None:
    first = _batch(_event(revision="edit-A", at=T0, body="A"))
    divergent = _batch(_event(revision="edit-B", at=T0, body="B"))
    descriptor = installed_executor("0.6.0")
    executor = load_executor(descriptor.reference).module
    state = executor.initial_state(descriptor.reference)

    accepted = executor.apply_batch(state, first)
    rejected = executor.apply_batch(accepted.state, divergent)

    assert rejected.state.events == accepted.state.events
    assert rejected.state.boundaries == accepted.state.boundaries
    assert rejected.state.read_blockers[0].outcome == "boundary-conflict"
    assert rejected.effects[-1].outcome == "boundary-conflict"
    assert rejected.state.boundaries[0].batch_hash == first.batch_hash


def test_incremental_boundary_conflict_blocks_later_sequences() -> None:
    first = _batch(_event(revision="edit-A", at=T0, body="A"))
    divergent = _batch(_event(revision="edit-B", at=T0, body="B"))
    later = _batch(
        _event(revision="edit-C", at=T0 + timedelta(seconds=1), body="C"),
        cursor="cursor-2",
        captured_at=T0 + timedelta(hours=2),
        read_sequence=2,
    )
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module

    accepted = executor.apply_batch(executor.initial_state(reference), first)
    conflicted = executor.apply_batch(accepted.state, divergent)
    blocked = executor.apply_batch(conflicted.state, later)

    assert conflicted.state.read_blockers[0].outcome == "boundary-conflict"
    assert blocked.state == conflicted.state
    assert blocked.effects[-1].outcome == "boundary-conflict"
    assert [event.revision_id for event in blocked.state.events] == ["edit-A"]
    assert blocked.state.boundaries[0].read_sequence == 1


def test_earlier_capture_for_same_sequence_is_a_durable_conflict() -> None:
    first = _batch(
        _event(revision="edit-A", at=T0, body="A"),
        captured_at=T0 + timedelta(hours=2),
    )
    divergent = _batch(
        _event(revision="edit-B", at=T0, body="B"),
        captured_at=T0 + timedelta(hours=1),
    )
    later = _batch(
        _event(revision="edit-C", at=T0 + timedelta(seconds=1), body="C"),
        cursor="cursor-2",
        captured_at=T0 + timedelta(hours=3),
        read_sequence=2,
    )
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module

    accepted = executor.apply_batch(executor.initial_state(reference), first)
    conflicted = executor.apply_batch(accepted.state, divergent)
    blocked = executor.apply_batch(conflicted.state, later)

    assert conflicted.state.read_blockers[0].outcome == "boundary-conflict"
    assert blocked.state == conflicted.state
    assert blocked.effects[-1].outcome == "boundary-conflict"
    assert [event.revision_id for event in blocked.state.events] == ["edit-A"]
    assert blocked.state.boundaries[0].read_sequence == 1


def test_executor_does_not_expose_standalone_event_application() -> None:
    handle = load_executor(installed_executor("0.6.0").reference)

    with pytest.raises(ValueError, match="internal"):
        handle.import_module("transition")


def test_replay_rebuilds_foreign_subclasses_inside_selected_executor() -> None:
    class ForeignEvent(GitHubEvent):
        @property
        def idempotency_key(self) -> str:
            return "foreign-unmanifested-event-key"

        @property
        def semantic_fingerprint(self) -> str:
            return "foreign-unmanifested-fingerprint"

    class ForeignBatch(GitHubEventBatch):
        @property
        def ordered_events(self) -> tuple[GitHubEvent, ...]:
            return tuple(reversed(self.events))

        @property
        def batch_hash(self) -> str:
            return "foreign-unmanifested-batch-hash"

    canonical_event = _event(revision="edit-A", at=T0, body="A")
    foreign_event = ForeignEvent(
        repository_id=canonical_event.repository_id,
        object_kind=canonical_event.object_kind,
        object_id=canonical_event.object_id,
        revision_id=canonical_event.revision_id,
        effective_at=canonical_event.effective_at,
        body=canonical_event.body,
        content_hash=canonical_event.content_hash,
        actor_account_id=canonical_event.actor_account_id,
        payload=canonical_event.payload,
    )
    canonical_batch = _batch(canonical_event)
    foreign_batch = ForeignBatch(
        boundary=canonical_batch.boundary,
        events=(foreign_event,),
    )
    reference = installed_executor("0.6.0").reference

    canonical_report = replay([canonical_batch], reference)
    foreign_report = replay([foreign_batch], reference)
    executor = load_executor(reference).module
    incremental = executor.apply_batch(executor.initial_state(reference), foreign_batch)

    assert foreign_report.state_bytes == canonical_report.state_bytes
    assert foreign_report.report_bytes == canonical_report.report_bytes
    assert executor.serialize_state(incremental.state) == canonical_report.state_bytes
    assert incremental.state.boundaries[0].batch_hash == canonical_batch.batch_hash
    assert "foreign-unmanifested" not in foreign_report.report_bytes.decode("utf-8")
    assert "foreign-unmanifested" not in executor.serialize_state(
        incremental.state
    ).decode("utf-8")


def test_replay_uses_the_verifier_owned_runtime_reference() -> None:
    class ForeignRuntimeReference(RuntimeReference):
        @property
        def ruleset_hash(self) -> str:
            return "0" * 64

        @property
        def executor_manifest_hash(self) -> str:
            return "f" * 64

    reference = installed_executor("0.6.0").reference
    foreign = ForeignRuntimeReference(*reference)

    report = replay([], foreign)
    handle = load_executor(foreign)

    assert type(handle.reference) is RuntimeReference
    assert report.state.ruleset_hash == reference.ruleset_hash
    assert report.state.executor_manifest_hash == reference.executor_manifest_hash
    assert b'"ruleset_hash":"000000' not in report.report_bytes
    assert b'"executor_manifest_hash":"ffffff' not in report.report_bytes


def test_incremental_api_rebuilds_foreign_protocol_state() -> None:
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module
    canonical_state = executor.initial_state(reference)

    class ForeignState(type(canonical_state)):
        def to_data(self) -> dict[str, object]:
            return {"outside_manifest": True}

        @property
        def state_hash(self) -> str:
            return "0" * 64

    foreign_state = ForeignState(
        schema_version=canonical_state.schema_version,
        ruleset_hash=canonical_state.ruleset_hash,
        tide_interface_version=canonical_state.tide_interface_version,
        executor_manifest_hash=canonical_state.executor_manifest_hash,
        boundaries=canonical_state.boundaries,
        processed_event_keys=canonical_state.processed_event_keys,
        events=canonical_state.events,
    )
    batch = _batch(_event(revision="edit-A", at=T0, body="A"))

    result = executor.apply_batch(foreign_state, batch)

    assert type(result.state) is type(canonical_state)
    assert b"outside_manifest" not in executor.serialize_state(result.state)
    assert executor.serialize_state(foreign_state) == executor.serialize_state(
        canonical_state
    )


def test_incremental_api_rejects_state_from_another_runtime() -> None:
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module
    state = executor.initial_state(reference)
    foreign_state = replace(
        state,
        ruleset_hash="0" * 64,
        executor_manifest_hash="f" * 64,
    )
    batch = _batch(_event(revision="edit-A", at=T0, body="A"))

    with pytest.raises(ValueError, match="state runtime triple"):
        executor.apply_batch(foreign_state, batch)
    with pytest.raises(ValueError, match="runtime triple"):
        executor.initial_state(reference._replace(executor_manifest_hash="f" * 64))


def test_protocol_state_rejects_boolean_schema_version() -> None:
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module

    with pytest.raises(ValueError, match="schema_version"):
        replace(executor.initial_state(reference), schema_version=True)


def test_protocol_state_rejects_a_stale_incomplete_read_blocker() -> None:
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module
    applied = executor.apply_batch(
        executor.initial_state(reference),
        _batch(_event(revision="edit-A", at=T0, body="A")),
    )
    blocker_type = type(
        executor.apply_batch(
            executor.initial_state(reference),
            _batch(
                _event(revision="edit-incomplete", at=T0, body="incomplete"),
                complete=False,
            ),
        ).state.read_blockers[0]
    )

    with pytest.raises(ValueError, match="read blocker cannot precede"):
        replace(
            applied.state,
            read_blockers=(blocker_type(REPOSITORY_ID, 1, "read-incomplete"),),
        )


def test_protocol_state_rejects_conflicting_existing_revisions() -> None:
    reference = installed_executor("0.6.0").reference
    executor = load_executor(reference).module
    first = _event(revision="same-revision", at=T0, body="A")
    conflicting = _event(revision="same-revision", at=T0, body="B")
    events = tuple(
        sorted((first, conflicting), key=lambda item: item.canonical_order_key)
    )

    with pytest.raises(ValueError, match="duplicate revision identities"):
        replace(
            executor.initial_state(reference),
            events=events,
            processed_event_keys=tuple(event.idempotency_key for event in events),
        )


def test_replay_rejects_naive_foreign_datetime_subclass() -> None:
    class ForeignDatetime(datetime):
        pass

    class RawInput:
        pass

    boundary = RawInput()
    boundary.repository = REPOSITORY
    boundary.repository_id = REPOSITORY_ID
    boundary.captured_at = ForeignDatetime(2026, 7, 22, 12)
    boundary.read_sequence = 1
    boundary.end_cursor = "cursor"
    boundary.complete = True
    batch = RawInput()
    batch.boundary = boundary
    batch.events = ()

    with pytest.raises(ValueError, match="timezone-aware"):
        replay([batch], installed_executor("0.6.0").reference)


def test_shadow_writer_has_one_fixed_repo_local_namespace(tmp_path) -> None:
    event = _event(revision="edit-A", at=T0, body="A")
    report = replay([_batch(event)], installed_executor("0.6.0").reference)

    path = write_shadow_report(tmp_path, "run-001", report)

    assert path == tmp_path / ".wea_runs" / "vnext-shadow" / "run-001.json"
    assert path.read_bytes() == report.report_bytes
    assert write_shadow_report(tmp_path, "run-001", report) == path

    other_report = replay(
        [_batch(_event(revision="edit-B", at=T0, body="B"))],
        installed_executor("0.6.0").reference,
    )
    with pytest.raises(FileExistsError, match="different bytes"):
        write_shadow_report(tmp_path, "run-001", other_report)
    with pytest.raises(ValueError, match="run_id"):
        write_shadow_report(tmp_path, "../ledger", report)


def test_shadow_writer_does_not_publish_a_partial_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = replay([], installed_executor("0.6.0").reference)
    destination = tmp_path / ".wea_runs" / "vnext-shadow" / "retry.json"
    original_fsync = vnext_store.os.fsync
    failed = False

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("simulated transient fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(vnext_store.os, "fsync", fail_first_fsync)
    with pytest.raises(OSError, match="simulated transient"):
        write_shadow_report(tmp_path, "retry", report)

    assert failed
    assert not destination.exists()
    assert not list(destination.parent.glob(".retry.*.tmp"))

    monkeypatch.setattr(vnext_store.os, "fsync", original_fsync)
    assert write_shadow_report(tmp_path, "retry", report) == destination
    assert destination.read_bytes() == report.report_bytes


def test_shadow_writer_pins_temp_file_through_publication(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "nt":
        pytest.skip("Windows pathname replacement regression")
    report = replay([], installed_executor("0.6.0").reference)
    destination = tmp_path / ".wea_runs" / "vnext-shadow" / "pinned.json"
    original_link = vnext_store.os.link
    attempted = False

    def replace_temp_before_link(source, target, *args, **kwargs):
        nonlocal attempted
        attempted = True
        Path(source).unlink()
        Path(source).write_bytes(b"replacement")
        return original_link(source, target, *args, **kwargs)

    monkeypatch.setattr(vnext_store.os, "link", replace_temp_before_link)
    with pytest.raises(OSError):
        write_shadow_report(tmp_path, "pinned", report)

    assert attempted
    assert not destination.exists()
    assert not list(destination.parent.glob(".pinned.*.tmp"))


@pytest.mark.parametrize(
    "run_id",
    ["NUL", "nul.report", "CON", "COM1", "LPT9.trace"],
)
def test_shadow_writer_rejects_windows_device_names(tmp_path, run_id: str) -> None:
    report = replay([], installed_executor("0.6.0").reference)

    with pytest.raises(ValueError, match="reserved Windows device"):
        write_shadow_report(tmp_path, run_id, report)

    assert not (tmp_path / ".wea_runs").exists()


def test_shadow_report_preserves_an_incomplete_attempted_boundary() -> None:
    attempted = _batch(
        _event(revision="edit-incomplete", at=T0, body="incomplete"),
        cursor="cursor-incomplete",
        complete=False,
        captured_at=T0 + timedelta(minutes=1),
    )

    report = replay([attempted], installed_executor("0.6.0").reference)
    payload = json.loads(report.report_bytes)

    assert payload["read_attempts"] == [
        {
            "batch_hash": attempted.batch_hash,
            "boundary": attempted.boundary.to_data(),
        }
    ]
    assert report.read_attempts[0][0] == attempted.batch_hash
    assert report.read_attempts[0][1].to_data() == attempted.boundary.to_data()
    assert report.state.boundaries == ()


def test_shadow_writer_rejects_linked_parent_before_external_creation(tmp_path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / ".wea_runs"
    if os.name == "nt":
        created = subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            pytest.skip(f"directory junctions unavailable: {created.stderr}")
    else:
        os.symlink(outside, link, target_is_directory=True)
    report = replay([], installed_executor("0.6.0").reference)

    with pytest.raises(ValueError, match="links or junctions"):
        write_shadow_report(tmp_path, "run-001", report)

    assert not (outside / "vnext-shadow").exists()


def test_shadow_writer_pins_parent_during_final_creation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-race-outside"
    outside.mkdir()
    report = replay([], installed_executor("0.6.0").reference)
    original_open = vnext_store._open_relative_windows
    attempted = False

    def try_replacing_parent(directory_handle, name, *, create):
        nonlocal attempted
        if (
            create
            and name.startswith(".race.")
            and name.endswith(".tmp")
            and not attempted
        ):
            attempted = True
            shadow = tmp_path / ".wea_runs" / "vnext-shadow"
            shadow.rmdir()
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(shadow), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                pytest.skip(f"directory junctions unavailable: {created.stderr}")
        return original_open(directory_handle, name, create=create)

    if os.name != "nt":
        pytest.skip("Windows junction race regression")
    monkeypatch.setattr(vnext_store, "_open_relative_windows", try_replacing_parent)
    try:
        write_shadow_report(tmp_path, "race", report)
    except OSError:
        pass

    assert attempted
    assert not (outside / "race.json").exists()


def test_windows_shadow_writer_pins_runs_before_creating_shadow(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name != "nt":
        pytest.skip("Windows junction creation regression")
    outside = tmp_path.parent / f"{tmp_path.name}-runs-race-outside"
    outside.mkdir()
    moved_runs = outside / "moved-runs"
    report = replay([], installed_executor("0.6.0").reference)
    original_open = vnext_store._open_relative_windows_directory
    attempted = False

    def try_replacing_runs(directory_handle: int, name: str) -> int:
        nonlocal attempted
        if name == "vnext-shadow" and not attempted:
            attempted = True
            runs = tmp_path / ".wea_runs"
            try:
                runs.rename(moved_runs)
            except OSError:
                pass
            else:
                created = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(runs), str(outside)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if created.returncode != 0:
                    pytest.skip(f"directory junctions unavailable: {created.stderr}")
        return original_open(directory_handle, name)

    monkeypatch.setattr(
        vnext_store,
        "_open_relative_windows_directory",
        try_replacing_runs,
    )
    write_shadow_report(tmp_path, "race-parent", report)

    assert attempted
    assert not (outside / "vnext-shadow").exists()


def test_posix_shadow_pin_closes_root_if_child_open_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_descriptor = 41
    closed: list[int] = []
    identity = SimpleNamespace(st_dev=1, st_ino=2)
    monkeypatch.setattr(vnext_store.os, "open", lambda *_args, **_kwargs: 41)
    monkeypatch.setattr(vnext_store.os, "fstat", lambda _descriptor: identity)
    monkeypatch.setattr(vnext_store.os, "stat", lambda *_args, **_kwargs: identity)
    monkeypatch.setattr(vnext_store.os, "close", closed.append)

    def fail_child_open(*_args, **_kwargs):
        raise OSError("shadow directory disappeared")

    monkeypatch.setattr(vnext_store, "_open_beneath_posix", fail_child_open)
    shadow = tmp_path / ".wea_runs" / "vnext-shadow"

    with pytest.raises(OSError, match="disappeared"):
        with vnext_store._pin_shadow_directory_posix(tmp_path, shadow):
            pass

    assert closed == [root_descriptor]


def test_posix_existing_shadow_report_must_be_regular(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[int, str, dict[str, object]]] = []
    closed: list[int] = []

    def open_fifo(root_descriptor, relative_path, **kwargs):
        opened.append((root_descriptor, relative_path, kwargs))
        return 42

    monkeypatch.setattr(vnext_store, "_open_beneath_posix", open_fifo)
    monkeypatch.setattr(
        vnext_store.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(st_mode=stat.S_IFIFO),
    )
    monkeypatch.setattr(vnext_store.os, "close", closed.append)

    with pytest.raises(ValueError, match="regular file"):
        vnext_store._open_existing_shadow_report_posix(17, "run.json")

    assert opened == [
        (17, "run.json", {"create": False, "nonblocking": True})
    ]
    assert closed == [42]


def test_posix_shadow_writer_resolves_final_create_beneath_pinned_root(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX rename race regression")
    outside = tmp_path.parent / f"{tmp_path.name}-posix-race-outside"
    outside.mkdir()
    moved_shadow = outside / "moved-shadow"
    report = replay([], installed_executor("0.6.0").reference)
    original_open = vnext_store._open_beneath_posix
    attempted = False
    shadow_descriptor: int | None = None

    def move_parent_before_create(
        root_descriptor,
        relative_path,
        *,
        create,
        directory=False,
        nonblocking=False,
    ):
        nonlocal attempted, shadow_descriptor
        if directory:
            shadow_descriptor = original_open(
                root_descriptor,
                relative_path,
                create=create,
                directory=True,
                nonblocking=nonblocking,
            )
            return shadow_descriptor
        if (
            create
            and relative_path.startswith(".race.")
            and relative_path.endswith(".tmp")
            and not attempted
        ):
            assert root_descriptor == shadow_descriptor
            assert "/" not in relative_path
            attempted = True
            shadow = tmp_path / ".wea_runs" / "vnext-shadow"
            shadow.rename(moved_shadow)
            os.symlink(moved_shadow, shadow, target_is_directory=True)
        return original_open(
            root_descriptor,
            relative_path,
            create=create,
            directory=directory,
            nonblocking=nonblocking,
        )

    monkeypatch.setattr(vnext_store, "_open_beneath_posix", move_parent_before_create)
    with pytest.raises((OSError, ValueError)):
        write_shadow_report(tmp_path, "race", report)

    assert attempted
    assert not (moved_shadow / "race.json").exists()


def test_posix_shadow_writer_rejects_move_immediately_before_final_link(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX final-link race regression")
    outside = tmp_path.parent / f"{tmp_path.name}-posix-link-race-outside"
    outside.mkdir()
    moved_shadow = outside / "moved-shadow"
    report = replay([], installed_executor("0.6.0").reference)
    original_link = vnext_store._link_pinned_posix
    ready = Event()
    proceed = Event()
    failures: list[BaseException] = []
    link_targets: list[tuple[int, str]] = []

    def pause_before_link(*args, **kwargs):
        link_targets.append((args[1], args[2]))
        ready.set()
        if not proceed.wait(10):
            raise TimeoutError("test did not release final publication")
        return original_link(*args, **kwargs)

    def write() -> None:
        try:
            write_shadow_report(tmp_path, "final-race", report)
        except BaseException as exc:
            failures.append(exc)

    monkeypatch.setattr(vnext_store, "_link_pinned_posix", pause_before_link)
    writer = Thread(target=write)
    writer.start()
    try:
        assert ready.wait(10)
        shadow = tmp_path / ".wea_runs" / "vnext-shadow"
        shadow.rename(moved_shadow)
        os.symlink(moved_shadow, shadow, target_is_directory=True)
    finally:
        proceed.set()
        writer.join(10)

    assert not writer.is_alive()
    assert len(link_targets) == 1
    assert link_targets[0][1] == "final-race.json"
    assert failures
    assert not (moved_shadow / "final-race.json").exists()
    shadow.unlink()
    moved_shadow.rename(shadow)
