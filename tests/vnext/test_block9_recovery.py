from __future__ import annotations

import json

import pytest

import wea_vnext.block9.recovery as recovery
from wea_vnext.block9.common import Block9Error, canonical_bytes, sha256_hex
from wea_vnext.block9.cutover import AppendOnlyEventStore
from wea_vnext.block9.recovery import (
    RepairApproval,
    ReplayRepairRequest,
    apply_replay_repair,
    replay_durable_repairs,
    select_recovery_mode,
)

from .block9_recovery_helpers import durable_transaction


def test_retry_rejects_a_divergent_remote_event_tail(tmp_path) -> None:
    transaction, remote = durable_transaction(tmp_path)
    event = transaction.append(sequence=0, payload={"event_type": "one"})
    snapshot = remote.snapshot
    remote.snapshot = snapshot.__class__(
        head=snapshot.head,
        authority_hash=snapshot.authority_hash,
        bootstrap=snapshot.bootstrap,
        repository_id=snapshot.repository_id,
        target_ref=snapshot.target_ref,
        head_commit=snapshot.head_commit,
        event_hashes=(sha256_hex(event), "f" * 64),
    )

    with pytest.raises(Block9Error, match="canonical event chain"):
        transaction.ensure_staged(0, event)


def _state() -> dict[str, object]:
    return {
        "balances": {"alice": 10},
        "escrows": {},
        "opening_supply": 10,
        "total_minted": 0,
        "financial_rows": [],
        "cursor": "cursor-1",
        "cursor_seen": "cursor-1",
        "void_events": [],
        "executor_overrides": {},
        "superseded_records": {},
    }


def _approval(role: str, payload_hash: str) -> RepairApproval:
    return RepairApproval(
        role=role,
        source_identity="operator@local" if role == "operator" else "agent0@system",
        binding_hash=("1" if role == "operator" else "2") * 64,
        payload_hash=payload_hash,
        signature=b"signed",
    )


def _event_reducer(state, payload, transaction_number):
    updated = json.loads(json.dumps(state))
    if payload.get("event_type") == "observe_cursor":
        updated["cursor_seen"] = updated["cursor"]
    updated["last_transaction"] = transaction_number
    return updated


def _seed_history(transaction) -> dict[str, object]:
    for sequence, event_type in enumerate(("noop", "observe_cursor", "noop", "noop")):
        transaction.append(
            sequence=sequence,
            payload={"event_type": event_type, "event_id": f"event-{sequence + 1}"},
        )
    return replay_durable_repairs(
        _state(),
        transaction.store,
        verifier=lambda *_: True,
        event_reducer=_event_reducer,
    )


def test_replay_repair_rejects_any_money_change(tmp_path) -> None:
    with pytest.raises(Block9Error, match="patch fields"):
        ReplayRepairRequest.create(
            repair_id="repair-1",
            operation="cursor_reset",
            affected_ids=("cursor-1",),
            violated_rule="R-B9-08",
            implementation_hashes={"executor": "4" * 64},
            effective_transaction=4,
            pre_state=_state(),
            patch={"balances": {"alice": 999}, "cursor": "cursor-2"},
            idempotency_key="repair:1",
        )


def test_replay_repair_is_append_only_idempotent_and_restart_safe(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transaction, remote = durable_transaction(tmp_path)
    store = transaction.store
    before = _seed_history(transaction)
    corrected = {**before, "cursor": "cursor-2", "cursor_seen": "cursor-2"}
    request = ReplayRepairRequest.create(
        repair_id="repair-2",
        operation="cursor_reset",
        affected_ids=("cursor-1",),
        violated_rule="R-B9-08",
        implementation_hashes={"executor": "4" * 64},
        effective_transaction=1,
        pre_state=before,
        patch={"cursor": "cursor-2"},
        post_state=corrected,
        idempotency_key="repair:2",
    )
    updated, event = apply_replay_repair(
        transaction,
        before,
        request,
        opening_state=_state(),
        approvals=(
            _approval("operator", request.payload_hash),
            _approval("agent0", request.payload_hash),
        ),
        verifier=lambda payload, signature, namespace: bool(signature)
        and namespace == "wea-vnext-replay-repair",
        event_reducer=_event_reducer,
    )
    restarted, _ = durable_transaction(tmp_path, remote)
    retry, retry_event = apply_replay_repair(
        restarted,
        before,
        request,
        opening_state=_state(),
        approvals=(
            _approval("operator", request.payload_hash),
            _approval("agent0", request.payload_hash),
        ),
        verifier=lambda *_: True,
        event_reducer=_event_reducer,
    )
    assert updated["cursor"] == "cursor-2"
    assert retry == updated
    assert retry_event == event
    assert json.loads(store.read_all()[4])["payload"]["operation"] == "cursor_reset"
    monkeypatch.setattr(recovery, "REPLAY_REPAIR_VERSION", "block9-replay-repair-2")
    monkeypatch.setattr(recovery, "REPLAY_REPAIR_HASH", "9" * 64)
    assert (
        replay_durable_repairs(
            _state(),
            store,
            verifier=lambda *_: True,
            event_reducer=_event_reducer,
        )
        == updated
    )
    assert updated["cursor_seen"] == "cursor-2"

    duplicate_payload = json.loads(event)["payload"]
    store.append(sequence=5, payload=duplicate_payload)
    with pytest.raises(Block9Error, match="idempotency key repeats"):
        replay_durable_repairs(
            _state(),
            store,
            verifier=lambda *_: True,
            event_reducer=_event_reducer,
        )


def test_event_is_durable_before_the_github_candidate_is_staged(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    transaction.append(sequence=0, payload={"event_type": "stage-proof"})


def test_repair_authority_rotation_and_idempotency_conflict_reject(tmp_path) -> None:
    state = _state()
    request = ReplayRepairRequest.create(
        repair_id="repair-3",
        operation="void_event",
        affected_ids=("event-3",),
        violated_rule="R-B9-08",
        implementation_hashes={"executor": "4" * 64},
        effective_transaction=5,
        pre_state=state,
        patch={},
        idempotency_key="repair:3",
    )
    rotated = RepairApproval(
        role="agent0",
        source_identity="agent0@system",
        binding_hash="9" * 64,
        payload_hash="3" * 64,
        signature=b"signed",
    )
    with pytest.raises(Block9Error, match="approval payload hash"):
        transaction, _ = durable_transaction(tmp_path)
        apply_replay_repair(
            transaction,
            state,
            request,
            opening_state=_state(),
            approvals=(_approval("operator", request.payload_hash), rotated),
            verifier=lambda *_: True,
            event_reducer=_event_reducer,
        )

    same_identity = RepairApproval(
        role="operator",
        source_identity="agent0@system",
        binding_hash="1" * 64,
        payload_hash=request.payload_hash,
        signature=b"signed",
    )
    with pytest.raises(Block9Error, match="identities must differ"):
        transaction, _ = durable_transaction(tmp_path)
        apply_replay_repair(
            transaction,
            state,
            request,
            opening_state=_state(),
            approvals=(same_identity, _approval("agent0", request.payload_hash)),
            verifier=lambda *_: True,
            event_reducer=_event_reducer,
        )


@pytest.mark.parametrize(
    ("sequence_zero", "chain_valid", "expected"),
    [
        (False, True, "pre-cutover"),
        (False, False, "blocked"),
        (True, True, "forward-repair"),
        (True, False, "blocked"),
    ],
)
def test_recovery_mode_never_falls_back_to_v1_after_sequence_zero(
    sequence_zero: bool,
    chain_valid: bool,
    expected: str,
) -> None:
    assert (
        select_recovery_mode(
            sequence_zero_present=sequence_zero, chain_valid=chain_valid
        )
        == expected
    )


def test_exact_repair_retry_accepts_the_reconstructed_post_state(tmp_path) -> None:
    transaction, remote = durable_transaction(tmp_path)
    state = _seed_history(transaction)
    corrected = {**state, "cursor": "cursor-2", "cursor_seen": "cursor-2"}
    request = ReplayRepairRequest.create(
        repair_id="repair-post-state",
        operation="cursor_reset",
        affected_ids=("cursor-1",),
        violated_rule="R-B9-08",
        implementation_hashes={"executor": "4" * 64},
        effective_transaction=1,
        pre_state=state,
        patch={"cursor": "cursor-2"},
        post_state=corrected,
        idempotency_key="repair:post-state",
    )
    approvals = (
        _approval("operator", request.payload_hash),
        _approval("agent0", request.payload_hash),
    )
    updated, event = apply_replay_repair(
        transaction,
        state,
        request,
        opening_state=_state(),
        approvals=approvals,
        verifier=lambda *_: True,
        event_reducer=_event_reducer,
    )
    restarted, _ = durable_transaction(tmp_path, remote)
    retry, retry_event = apply_replay_repair(
        restarted,
        updated,
        request,
        opening_state=_state(),
        approvals=approvals,
        verifier=lambda *_: True,
        event_reducer=_event_reducer,
    )
    assert retry == updated
    assert retry_event == event


def test_repair_rejects_post_state_not_produced_by_deterministic_replay(
    tmp_path,
) -> None:
    transaction, _ = durable_transaction(tmp_path)
    before = _seed_history(transaction)
    request = ReplayRepairRequest.create(
        repair_id="repair-forged-post-state",
        operation="cursor_reset",
        affected_ids=("cursor-1",),
        violated_rule="R-B9-08",
        implementation_hashes={"executor": "4" * 64},
        effective_transaction=1,
        pre_state=before,
        patch={"cursor": "cursor-2"},
        post_state={
            **before,
            "cursor": "cursor-2",
            "cursor_seen": "cursor-2",
            "unrelated": "forged",
        },
        idempotency_key="repair:forged-post-state",
    )
    with pytest.raises(Block9Error, match="deterministic replay"):
        apply_replay_repair(
            transaction,
            before,
            request,
            opening_state=_state(),
            approvals=(
                _approval("operator", request.payload_hash),
                _approval("agent0", request.payload_hash),
            ),
            verifier=lambda *_: True,
            event_reducer=_event_reducer,
        )
    assert len(transaction.store.read_all()) == 4


def test_tampered_event_bytes_block_restart(tmp_path) -> None:
    store = AppendOnlyEventStore(tmp_path)
    store.append(sequence=0, payload={"event_type": "repair"})
    path = next((tmp_path / "events").glob("*.json"))
    path.write_bytes(
        canonical_bytes({"sequence": 0, "payload": {"event_type": "forged"}}) + b"\n"
    )
    with pytest.raises(Block9Error, match="non-canonical"):
        store.read_all()
