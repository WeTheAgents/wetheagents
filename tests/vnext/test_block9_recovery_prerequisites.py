from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta

import pytest

import wea_vnext.block9.recovery as recovery
from wea_vnext.block9.common import Block9Error, sha256_hex
from wea_vnext.block9.recovery import (
    DURABLE_CORRECTION_VERSION,
    DurableCorrectionAdapter,
    replay_durable_corrections,
)
from wea_vnext.financial_correction import CompensatingPosting

from .block9_recovery_helpers import (
    correction_signatures,
    durable_transaction,
    verify_test_signature,
)
from .test_correction import START, _approvals, _proposal, _state


def test_durable_correction_binds_s13c_result_and_exact_retry(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    transaction, remote = durable_transaction(tmp_path)
    store = transaction.store
    adapter = DurableCorrectionAdapter(transaction)

    updated, group, event = adapter.apply(
        state,
        proposal=proposal,
        approvals=approvals,
        signatures=correction_signatures(
            proposal, approvals, START + timedelta(minutes=2)
        ),
        verifier=verify_test_signature,
        effective_at=START + timedelta(minutes=2),
    )
    restarted, _ = durable_transaction(tmp_path, remote)
    retry_state, retry_group, retry_event = DurableCorrectionAdapter(restarted).apply(
        state,
        proposal=proposal,
        approvals=approvals,
        signatures=correction_signatures(
            proposal, approvals, START + timedelta(minutes=2)
        ),
        verifier=verify_test_signature,
        effective_at=START + timedelta(minutes=2),
    )

    assert retry_state == updated
    assert retry_group == group
    assert retry_event == event
    assert DURABLE_CORRECTION_VERSION.encode() in event
    assert len(store.read_all()) == 1
    monkeypatch.setattr(
        recovery,
        "DURABLE_CORRECTION_VERSION",
        "block9-financial-correction-2",
    )
    monkeypatch.setattr(recovery, "DURABLE_CORRECTION_HASH", "9" * 64)
    assert (
        replay_durable_corrections(state, store, verifier=verify_test_signature)
        == updated
    )


def test_correction_crash_before_append_is_empty_and_after_append_retries(
    tmp_path,
) -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    transaction, remote = durable_transaction(tmp_path)
    store = transaction.store
    adapter = DurableCorrectionAdapter(transaction)

    with pytest.raises(RuntimeError, match="before append"):
        adapter.apply(
            state,
            proposal=proposal,
            approvals=approvals,
            signatures=correction_signatures(
                proposal, approvals, START + timedelta(minutes=2)
            ),
            verifier=verify_test_signature,
            effective_at=START + timedelta(minutes=2),
            fault="before_append",
        )
    assert store.read_all() == ()

    with pytest.raises(RuntimeError, match="after append"):
        adapter.apply(
            state,
            proposal=proposal,
            approvals=approvals,
            signatures=correction_signatures(
                proposal, approvals, START + timedelta(minutes=2)
            ),
            verifier=verify_test_signature,
            effective_at=START + timedelta(minutes=2),
            fault="after_append",
        )
    assert len(store.read_all()) == 1
    restarted, _ = durable_transaction(tmp_path, remote)
    DurableCorrectionAdapter(restarted).apply(
        state,
        proposal=proposal,
        approvals=approvals,
        signatures=correction_signatures(
            proposal, approvals, START + timedelta(minutes=2)
        ),
        verifier=verify_test_signature,
        effective_at=START + timedelta(minutes=2),
    )
    assert len(store.read_all()) == 1


def test_new_event_rejects_a_stale_local_chain_before_publication(tmp_path) -> None:
    canonical, remote = durable_transaction(tmp_path / "canonical")
    original = canonical.append(sequence=0, payload={"event_type": "original"})
    original_head = remote.snapshot.head
    stale, _ = durable_transaction(tmp_path / "stale", remote)

    with pytest.raises(Block9Error, match="local event chain"):
        stale.append(sequence=0, payload={"event_type": "replacement"})

    assert stale.store.read_all() == ()
    assert remote.snapshot.head == original_head
    assert remote.snapshot.event_hashes == (sha256_hex(original),)


def test_new_event_stages_the_complete_event_chain(tmp_path) -> None:
    transaction, remote = durable_transaction(tmp_path)
    first = transaction.append(sequence=0, payload={"event_type": "first"})
    second = transaction.append(sequence=1, payload={"event_type": "second"})

    assert remote.staged[-1] == (first, second)
    assert remote.snapshot.event_hashes == (sha256_hex(first), sha256_hex(second))


def test_distinct_correction_rejects_a_stale_caller_state(tmp_path) -> None:
    opening = _state()
    first = _proposal()
    first_approvals = _approvals(opening, first)
    transaction, _ = durable_transaction(tmp_path)
    adapter = DurableCorrectionAdapter(transaction)
    current, _, _ = adapter.apply(
        opening,
        proposal=first,
        approvals=first_approvals,
        signatures=correction_signatures(
            first, first_approvals, START + timedelta(minutes=2)
        ),
        verifier=verify_test_signature,
        effective_at=START + timedelta(minutes=2),
    )
    second = _proposal(
        correction_id="correction:stale-state:2",
        idempotency_key="financial-correction:stale-state:2",
    )
    second_approvals = _approvals(current, second)
    with pytest.raises(Block9Error, match="state is stale"):
        adapter.apply(
            opening,
            proposal=second,
            approvals=second_approvals,
            signatures=correction_signatures(
                second, second_approvals, START + timedelta(minutes=4)
            ),
            verifier=verify_test_signature,
            effective_at=START + timedelta(minutes=4),
        )
    assert len(transaction.store.read_all()) == 1


def test_correction_is_durable_before_its_candidate_is_staged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    transaction, remote = durable_transaction(tmp_path)
    original = transaction.store.append
    appended = False

    def observed_append(*, sequence: int, payload):
        nonlocal appended
        result = original(sequence=sequence, payload=payload)
        appended = True
        return result

    def checked_stage(events):
        assert appended
        remote.stage(events)

    monkeypatch.setattr(transaction.store, "append", observed_append)
    transaction.stage_candidate = checked_stage
    DurableCorrectionAdapter(transaction).apply(
        state,
        proposal=proposal,
        approvals=approvals,
        signatures=correction_signatures(
            proposal, approvals, START + timedelta(minutes=2)
        ),
        verifier=verify_test_signature,
        effective_at=START + timedelta(minutes=2),
    )


def test_correction_requires_two_verified_signed_authority_sources(tmp_path) -> None:
    state = _state()
    proposal = _proposal()
    approvals = _approvals(state, proposal)
    effective_at = START + timedelta(minutes=2)
    signatures = correction_signatures(proposal, approvals, effective_at)
    transaction, _ = durable_transaction(tmp_path)
    with pytest.raises(Block9Error, match="signed authority source changed"):
        DurableCorrectionAdapter(transaction).apply(
            state,
            proposal=proposal,
            approvals=approvals,
            signatures=(
                replace(signatures[0], source_revision="substituted-revision"),
                signatures[1],
            ),
            verifier=verify_test_signature,
            effective_at=effective_at,
        )
    assert transaction.store.read_all() == ()

    with pytest.raises(Block9Error, match="identities must differ"):
        DurableCorrectionAdapter(transaction).apply(
            state,
            proposal=proposal,
            approvals=approvals,
            signatures=(
                replace(signatures[0], source_identity="agent0@system"),
                signatures[1],
            ),
            verifier=verify_test_signature,
            effective_at=effective_at,
        )
    assert transaction.store.read_all() == ()


def test_group_64_emits_a_checkpoint_bound_to_the_complete_state(tmp_path) -> None:
    opening = _state()
    state = opening
    transaction, _ = durable_transaction(tmp_path)
    adapter = DurableCorrectionAdapter(transaction)
    for index in range(64):
        proposal = _proposal(
            correction_id=f"correction:checkpoint:{index}",
            idempotency_key=f"financial-correction:checkpoint:{index}",
            affected_ledger_ids=("ledger:history:2026-08-14:1",),
            postings=(
                CompensatingPosting("balance:alice", -1, "transfer"),
                CompensatingPosting("balance:bob", 1, "transfer"),
            ),
        )
        approvals = _approvals(state, proposal)
        effective_at = START + timedelta(minutes=2 + index * 2)
        state, group, event = adapter.apply(
            state,
            proposal=proposal,
            approvals=approvals,
            signatures=correction_signatures(proposal, approvals, effective_at),
            verifier=verify_test_signature,
            effective_at=effective_at,
        )
    checkpoint = json.loads(event)["payload"]["checkpoint"]
    assert checkpoint["group_count"] == 64
    assert checkpoint["ledger_head_hash"] == group.group_hash
    assert b'"checkpoint"' in event
    assert state.groups == ()

    approvals = _approvals(state, proposal)
    effective_at = START + timedelta(minutes=2 + 63 * 2)
    retry_state, retry_group, retry_event = adapter.apply(
        state,
        proposal=proposal,
        approvals=approvals,
        signatures=correction_signatures(proposal, approvals, effective_at),
        verifier=verify_test_signature,
        effective_at=effective_at,
    )
    assert retry_state == state
    assert retry_group == group
    assert retry_event == event

    next_proposal = _proposal(
        correction_id="correction:checkpoint:64",
        idempotency_key="financial-correction:checkpoint:64",
        affected_ledger_ids=("ledger:history:2026-08-14:1",),
        postings=(
            CompensatingPosting("balance:alice", -1, "transfer"),
            CompensatingPosting("balance:bob", 1, "transfer"),
        ),
    )
    approvals = _approvals(state, next_proposal)
    effective_at = START + timedelta(minutes=132)
    state, _, _ = adapter.apply(
        state,
        proposal=next_proposal,
        approvals=approvals,
        signatures=correction_signatures(next_proposal, approvals, effective_at),
        verifier=verify_test_signature,
        effective_at=effective_at,
    )
    assert len(state.groups) == 1
    assert (
        replay_durable_corrections(
            opening, transaction.store, verifier=verify_test_signature
        )
        == state
    )
