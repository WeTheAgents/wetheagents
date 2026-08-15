from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timedelta, timezone

import pytest

from wea_vnext.domain_access import (
    ACCESS_DURATION,
    AccessError,
    AccessExpiry,
    AccessGrant,
    DomainAccessState,
    IdempotencyRecord,
    build_domain_registry,
    expire_access,
    grant_access,
    initial_access_state,
    is_access_active,
    make_domain_record,
)

NOW = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)


def _state():
    records = (
        make_domain_record(
            domain_id="circle-1",
            repository_id="R_kgDOPublicCircle1",
            repository_locator="https://github.com/WeTheAgents/circle-1",
            revision="1" * 40,
        ),
        make_domain_record(
            domain_id="second-domain",
            repository_id="R_kgDOSecondDomain",
            repository_locator="https://github.com/WeTheAgents/second-domain",
            revision="2" * 40,
        ),
    )
    return initial_access_state(build_domain_registry(records))


def _grant(state, **overrides):
    values = {
        "authority_kind": "operator",
        "authority_id": "operator@system",
        "authority_revision_id": "decision-1",
        "agent_id": "codex-2@codex",
        "domain_id": "circle-1",
        "effective_at": NOW,
        "idempotency_key": "grant:circle-1:codex-2:2026-08-15",
    }
    values.update(overrides)
    return grant_access(state, **values)


@pytest.mark.parametrize("authority_kind", ("operator", "agent0"))
def test_s_11a_authorized_source_grants_exactly_seven_days(
    authority_kind: str,
) -> None:
    state, access = _grant(
        _state(),
        authority_kind=authority_kind,
        authority_id=f"{authority_kind}@system",
    )

    assert state.grants == (access,)
    assert access.starts_at == NOW
    assert access.ends_at == NOW + ACCESS_DURATION
    assert access.ends_at - access.starts_at == timedelta(days=7)
    assert access.domain_id == "circle-1"
    assert access.registry_hash == state.registry.registry_hash
    assert is_access_active(access, NOW)
    assert is_access_active(access, access.ends_at - timedelta(microseconds=1))
    assert not is_access_active(access, access.ends_at)


def test_s_11a_rejects_unknown_authority_or_domain_without_state_change() -> None:
    state = _state()

    with pytest.raises(AccessError, match="authority"):
        _grant(state, authority_kind="agent")
    with pytest.raises(AccessError, match="Domain"):
        _grant(state, domain_id="missing-domain")

    assert state.grants == ()
    assert state.expiries == ()
    assert state.idempotency_records == ()


def test_s_11a_one_agent_cannot_hold_overlapping_access_across_domains() -> None:
    state, first = _grant(_state())

    with pytest.raises(AccessError, match="overlapping Access"):
        _grant(
            state,
            domain_id="second-domain",
            effective_at=NOW + timedelta(days=6),
            idempotency_key="grant:second:overlap",
        )

    state, replacement = _grant(
        state,
        domain_id="second-domain",
        effective_at=first.ends_at,
        idempotency_key="grant:second:boundary",
    )
    assert replacement.starts_at == first.ends_at
    assert len(state.grants) == 2


def test_s_11a_grant_replay_is_exact_and_conflicting_reuse_is_rejected() -> None:
    state, access = _grant(_state())

    replayed_state, replayed_access = _grant(state)

    assert replayed_state is state
    assert replayed_access is access
    with pytest.raises(AccessError, match="idempotency key"):
        _grant(state, domain_id="second-domain")


def test_s_11b_access_expires_only_at_the_exact_boundary_and_replays() -> None:
    state, access = _grant(_state())

    with pytest.raises(AccessError, match="exact ends_at"):
        expire_access(
            state,
            access_id=access.access_id,
            effective_at=access.ends_at - timedelta(microseconds=1),
            idempotency_key="expire:circle-1:early",
        )

    expired_state, expiry = expire_access(
        state,
        access_id=access.access_id,
        effective_at=access.ends_at,
        idempotency_key="expire:circle-1:boundary",
    )
    assert expired_state.expiries == (expiry,)
    assert expiry.effective_at == access.ends_at

    replayed_state, replayed_expiry = expire_access(
        expired_state,
        access_id=access.access_id,
        effective_at=access.ends_at,
        idempotency_key="expire:circle-1:boundary",
    )
    assert replayed_state is expired_state
    assert replayed_expiry is expiry


def test_access_has_no_revoke_extend_permission_work_or_money_surface() -> None:
    forbidden_names = {
        "amount",
        "github_permission",
        "money",
        "renewed_at",
        "revoked_at",
        "work_id",
    }

    assert forbidden_names.isdisjoint(field.name for field in fields(AccessGrant))
    assert forbidden_names.isdisjoint(field.name for field in fields(AccessExpiry))

    import wea_vnext.domain_access as domain_access

    assert not hasattr(domain_access, "revoke_access")
    assert not hasattr(domain_access, "renew_access")
    assert not hasattr(domain_access, "extend_access")


def test_access_rejects_naive_time_and_conflicting_expiry_replay() -> None:
    state = _state()
    with pytest.raises(AccessError, match="timezone-aware"):
        _grant(state, effective_at=NOW.replace(tzinfo=None))

    state, access = _grant(state)
    state, _ = expire_access(
        state,
        access_id=access.access_id,
        effective_at=access.ends_at,
        idempotency_key="expiry-key",
    )
    with pytest.raises(AccessError, match="idempotency key"):
        expire_access(
            state,
            access_id="access:missing",
            effective_at=access.ends_at,
            idempotency_key="expiry-key",
        )


def test_access_state_revalidates_global_overlap_and_idempotency_links() -> None:
    first_state, _ = _grant(_state())
    second_state, _ = _grant(
        _state(),
        effective_at=NOW + timedelta(days=1),
        idempotency_key="second-independent-grant",
    )

    with pytest.raises(AccessError, match="overlapping Access"):
        DomainAccessState(
            registry=first_state.registry,
            grants=(*first_state.grants, *second_state.grants),
            idempotency_records=(
                *first_state.idempotency_records,
                *second_state.idempotency_records,
            ),
        )

    dangling = IdempotencyRecord(
        key="dangling-key",
        operation="grant_access",
        request_hash="a" * 64,
        object_id="access:missing",
    )
    with pytest.raises(AccessError, match="unknown Access"):
        DomainAccessState(
            registry=first_state.registry,
            grants=first_state.grants,
            idempotency_records=(*first_state.idempotency_records, dangling),
        )

    original = first_state.idempotency_records[0]
    wrong_hash = IdempotencyRecord(
        key=original.key,
        operation=original.operation,
        request_hash="a" * 64,
        object_id=original.object_id,
    )
    with pytest.raises(AccessError, match="exact request"):
        DomainAccessState(
            registry=first_state.registry,
            grants=first_state.grants,
            idempotency_records=(wrong_hash,),
        )

    alias = IdempotencyRecord(
        key="second-key-for-the-same-object",
        operation=original.operation,
        request_hash=original.request_hash,
        object_id=original.object_id,
    )
    with pytest.raises(AccessError, match="idempotency object reference"):
        DomainAccessState(
            registry=first_state.registry,
            grants=first_state.grants,
            idempotency_records=(original, alias),
        )


def test_access_rejects_noncanonical_domain_as_an_access_error() -> None:
    with pytest.raises(AccessError, match="domain_id"):
        _grant(_state(), domain_id="Circle One")
