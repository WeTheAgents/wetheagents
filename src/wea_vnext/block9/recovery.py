"""Durable correction and non-financial forward-repair adapters."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType

from ..financial_correction import (
    CompensatingPosting,
    CorrectionApproval,
    CorrectionGroup,
    CorrectionLedgerRow,
    CorrectionProposal,
    FinancialCorrectionState,
    apply_financial_correction,
    initial_financial_correction_state,
    make_published_ledger_row,
)
from .common import (
    Block9Error,
    canonical_bytes,
    require_hash,
    require_positive_int,
    require_text,
    sha256_hex,
)
from .cutover import AppendOnlyEventStore

DURABLE_CORRECTION_VERSION = "block9-financial-correction-1"
DURABLE_CORRECTION_HASH = sha256_hex(
    canonical_bytes(
        {
            "checkpoint": "complete-state-after-64-groups",
            "event_schema": "wea-vnext-financial-correction-event-1",
            "semantic_validator": "s13c-spec-1.1",
            "version": DURABLE_CORRECTION_VERSION,
        }
    )
)
REPLAY_REPAIR_VERSION = "block9-replay-repair-1"
_REPAIR_OPERATIONS = {
    "executor_override",
    "void_event",
    "supersede_record",
    "cursor_reset",
}
REPLAY_REPAIR_HASH = sha256_hex(
    canonical_bytes(
        {
            "event_schema": "wea-vnext-replay-repair-event-1",
            "operations": sorted(_REPAIR_OPERATIONS),
            "version": REPLAY_REPAIR_VERSION,
        }
    )
)
_FINANCIAL_KEYS = (
    "balances",
    "escrows",
    "opening_supply",
    "total_minted",
    "financial_rows",
)
_FAULTS = {
    "before_append",
    "after_append",
    "before_file_replace",
    "before_commit_creation",
    "before_push",
    "before_remote_confirmation",
    "after_remote_confirmation",
    "before_projection_confirmation",
}


@dataclass(frozen=True, slots=True)
class _FinancialCorrectionImplementation:
    implementation_hash: str
    apply: Callable[..., tuple[FinancialCorrectionState, CorrectionGroup]]
    checkpoint: Callable[[FinancialCorrectionState], dict[str, object]]
    rollover: Callable[[FinancialCorrectionState], FinancialCorrectionState]


@dataclass(frozen=True, slots=True)
class _ReplayRepairImplementation:
    implementation_hash: str
    apply_operation: Callable[
        [Mapping[str, object], str, tuple[str, ...], Mapping[str, object]],
        dict[str, object],
    ]


_FINANCIAL_CORRECTION_IMPLEMENTATIONS: Mapping[str, _FinancialCorrectionImplementation]
_REPLAY_REPAIR_IMPLEMENTATIONS: Mapping[str, _ReplayRepairImplementation]


def _financial_correction_implementation(
    version: object, implementation_hash: object
) -> _FinancialCorrectionImplementation:
    if type(version) is not str:
        raise Block9Error("durable correction implementation version changed")
    implementation = _FINANCIAL_CORRECTION_IMPLEMENTATIONS.get(version)
    if implementation is None:
        raise Block9Error("durable correction implementation version changed")
    if implementation_hash != implementation.implementation_hash:
        raise Block9Error("durable correction implementation hash changed")
    return implementation


def _replay_repair_implementation(
    version: object, implementation_hash: object
) -> _ReplayRepairImplementation:
    if type(version) is not str:
        raise Block9Error("replay repair implementation version changed")
    implementation = _REPLAY_REPAIR_IMPLEMENTATIONS.get(version)
    if implementation is None:
        raise Block9Error("replay repair implementation version changed")
    if implementation_hash != implementation.implementation_hash:
        raise Block9Error("replay repair implementation hash changed")
    return implementation


def _json_mapping(value: Mapping[str, object], *, field: str) -> dict[str, object]:
    try:
        rebuilt = json.loads(canonical_bytes(dict(value)))
    except (TypeError, ValueError) as exc:
        raise Block9Error(f"{field} is not canonical JSON") from exc
    if type(rebuilt) is not dict:
        raise Block9Error(f"{field} must be a mapping")
    return rebuilt


def _event_payloads(store: AppendOnlyEventStore) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for raw in store.read_all():
        event = json.loads(raw)
        payload = event.get("payload")
        if type(payload) is not dict:
            raise Block9Error("durable event payload is incomplete")
        result.append(payload)
    return tuple(result)


def _financial_state_hash(state: FinancialCorrectionState) -> str:
    payload = {
        "opening_supply": state.opening_supply,
        "opening_total_minted": state.opening_total_minted,
        "opening_snapshot_hash": state.opening_snapshot_hash,
        "positions": [
            {"position_id": item.position_id, "kind": item.kind, "amount": item.amount}
            for item in state.positions
        ],
        "total_minted": state.total_minted,
        "groups": [item.group_hash for item in state.groups],
        "rows": [
            {
                "row_id": item.row_id,
                "row_hash": item.row_hash,
                "correction_id": item.correction_id,
            }
            for item in state.correction_rows
        ],
    }
    return sha256_hex(canonical_bytes(payload))


def _group_mapping(group: CorrectionGroup) -> dict[str, object]:
    return {
        "group_id": group.group_id,
        "sequence_number": group.sequence_number,
        "previous_group_hash": group.previous_group_hash,
        "proposal": group.proposal.to_mapping(),
        "operator_approval": group.operator_approval.to_mapping(),
        "agent0_approval": group.agent0_approval.to_mapping(),
        "rows": [item.to_mapping() for item in group.rows],
        "effective_at": group.effective_at.isoformat().replace("+00:00", "Z"),
        "pre_state_hash": group.pre_state_hash,
        "post_state_hash": group.post_state_hash,
        "group_hash": group.group_hash,
    }


def _financial_result_mapping(state: FinancialCorrectionState) -> dict[str, object]:
    return {
        "positions": [item.to_mapping() for item in state.positions],
        "total_minted": state.total_minted,
        "correction_rows": [item.to_mapping() for item in state.correction_rows],
        "group_count": len(state.groups),
        "state_hash": _financial_state_hash(state),
    }


@dataclass(frozen=True, slots=True)
class CorrectionSignature:
    role: str
    source_identity: str
    authority_id: str
    source_revision: str
    binding_id: str
    binding_version: int
    binding_hash: str
    request_hash: str
    signature: bytes

    def __post_init__(self) -> None:
        if self.role not in {"operator", "agent0"}:
            raise Block9Error("correction signature role is invalid")
        for field in (
            "source_identity",
            "authority_id",
            "source_revision",
            "binding_id",
        ):
            require_text(getattr(self, field), field=f"correction signature {field}")
        require_positive_int(self.binding_version, field="correction binding_version")
        require_hash(self.binding_hash, field="correction binding_hash")
        require_hash(self.request_hash, field="correction request_hash")
        if type(self.signature) is not bytes or not self.signature:
            raise Block9Error("correction signature bytes are missing")
        if self.role == "agent0" and self.source_identity != "agent0@system":
            raise Block9Error("correction Agent0 identity is not agent0@system")

    def payload(self) -> bytes:
        return canonical_bytes(
            {
                "binding_hash": self.binding_hash,
                "binding_id": self.binding_id,
                "binding_version": self.binding_version,
                "authority_id": self.authority_id,
                "request_hash": self.request_hash,
                "role": self.role,
                "source_identity": self.source_identity,
                "source_revision": self.source_revision,
            }
        )


def _correction_signature_mapping(value: CorrectionSignature) -> dict[str, object]:
    return {
        "authority_id": value.authority_id,
        "binding_hash": value.binding_hash,
        "binding_id": value.binding_id,
        "binding_version": value.binding_version,
        "request_hash": value.request_hash,
        "role": value.role,
        "signature_hex": value.signature.hex(),
        "source_identity": value.source_identity,
        "source_revision": value.source_revision,
    }


def _correction_signature_from_mapping(value: object) -> CorrectionSignature:
    fields = {
        "authority_id",
        "binding_hash",
        "binding_id",
        "binding_version",
        "request_hash",
        "role",
        "signature_hex",
        "source_identity",
        "source_revision",
    }
    if type(value) is not dict or set(value) != fields:
        raise Block9Error("durable correction signature is incomplete")
    signature_hex = value["signature_hex"]
    if type(signature_hex) is not str:
        raise Block9Error("durable correction signature is invalid")
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise Block9Error("durable correction signature is invalid") from exc
    return CorrectionSignature(
        role=value["role"],
        source_identity=value["source_identity"],
        authority_id=value["authority_id"],
        source_revision=value["source_revision"],
        binding_id=value["binding_id"],
        binding_version=value["binding_version"],
        binding_hash=value["binding_hash"],
        request_hash=value["request_hash"],
        signature=signature,
    )


def _verify_correction_signatures(
    *,
    request_hash: str,
    approvals: tuple[CorrectionApproval, CorrectionApproval],
    signatures: tuple[CorrectionSignature, CorrectionSignature],
    verifier: Callable[[bytes, bytes, str], bool],
) -> None:
    if type(signatures) is not tuple or len(signatures) != 2:
        raise Block9Error("correction needs exactly two signed approval sources")
    by_role = {
        item.role: item for item in signatures if type(item) is CorrectionSignature
    }
    approval_by_role = {
        item.authority_kind: item
        for item in approvals
        if type(item) is CorrectionApproval
    }
    if set(by_role) != {"operator", "agent0"} or set(approval_by_role) != {
        "operator",
        "agent0",
    }:
        raise Block9Error("correction signatures must be operator and Agent0")
    if by_role["operator"].source_identity == by_role["agent0"].source_identity:
        raise Block9Error("correction operator and Agent0 identities must differ")
    if by_role["operator"].binding_hash == by_role["agent0"].binding_hash:
        raise Block9Error("correction signature bindings must differ")
    for role in ("operator", "agent0"):
        signed = by_role[role]
        approval = approval_by_role[role]
        if signed.request_hash != request_hash:
            raise Block9Error("correction signature request hash changed")
        if (
            signed.authority_id != approval.authority_id
            or signed.source_revision != approval.authority_revision_id
            or signed.binding_id != approval.binding_id
            or signed.binding_version != approval.binding_version
        ):
            raise Block9Error("correction signed authority source changed")
        if not verifier(
            signed.payload(), signed.signature, "wea-vnext-financial-correction"
        ):
            raise Block9Error(f"{role} correction signature did not verify")


def build_correction_request(
    *,
    proposal: CorrectionProposal,
    approvals: tuple[CorrectionApproval, CorrectionApproval],
    effective_at: datetime,
) -> tuple[dict[str, object], str]:
    """Build the exact request that both durable approval sources sign."""

    if type(proposal) is not CorrectionProposal:
        raise Block9Error("correction proposal must use the exact type")
    if (
        type(approvals) is not tuple
        or len(approvals) != 2
        or any(type(item) is not CorrectionApproval for item in approvals)
    ):
        raise Block9Error("correction approvals must use the exact tuple")
    if (
        type(effective_at) is not datetime
        or effective_at.tzinfo is None
        or effective_at.utcoffset() is None
    ):
        raise Block9Error("correction effective_at must be timezone-aware")
    request = {
        "proposal": proposal.to_mapping(),
        "approvals": [
            item.to_mapping()
            for item in sorted(approvals, key=lambda item: item.authority_kind)
        ],
        "effective_at": effective_at.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    return request, sha256_hex(canonical_bytes(request))


def _parse_timestamp(value: object, *, field: str) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise Block9Error(f"{field} is not a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise Block9Error(f"{field} is invalid") from exc
    return parsed


def _proposal_from_mapping(value: object) -> CorrectionProposal:
    if type(value) is not dict or set(value) != {
        "affected_ledger_ids",
        "correction_id",
        "idempotency_key",
        "postings",
        "proposal_hash",
    }:
        raise Block9Error("durable correction proposal is incomplete")
    postings = value["postings"]
    affected = value["affected_ledger_ids"]
    if type(postings) is not list or type(affected) is not list:
        raise Block9Error("durable correction proposal collections are invalid")
    rebuilt_postings: list[CompensatingPosting] = []
    for posting in postings:
        if type(posting) is not dict or set(posting) != {
            "delta",
            "kind",
            "position_id",
        }:
            raise Block9Error("durable correction posting is incomplete")
        rebuilt_postings.append(
            CompensatingPosting(
                position_id=posting["position_id"],
                delta=posting["delta"],
                kind=posting["kind"],
            )
        )
    return CorrectionProposal(
        correction_id=value["correction_id"],
        affected_ledger_ids=tuple(affected),
        postings=tuple(rebuilt_postings),
        idempotency_key=value["idempotency_key"],
        proposal_hash=value["proposal_hash"],
    )


def _approval_from_mapping(value: object) -> CorrectionApproval:
    fields = {
        "authority_id",
        "authority_kind",
        "authority_revision_id",
        "binding_effective_from",
        "binding_effective_until",
        "binding_id",
        "binding_version",
        "confirmed_at",
        "proposal_hash",
        "approval_hash",
    }
    if type(value) is not dict or set(value) != fields:
        raise Block9Error("durable correction approval is incomplete")
    until = value["binding_effective_until"]
    return CorrectionApproval(
        authority_kind=value["authority_kind"],
        authority_id=value["authority_id"],
        authority_revision_id=value["authority_revision_id"],
        binding_id=value["binding_id"],
        binding_version=value["binding_version"],
        binding_effective_from=_parse_timestamp(
            value["binding_effective_from"], field="binding_effective_from"
        ),
        binding_effective_until=(
            None
            if until is None
            else _parse_timestamp(until, field="binding_effective_until")
        ),
        proposal_hash=value["proposal_hash"],
        confirmed_at=_parse_timestamp(value["confirmed_at"], field="confirmed_at"),
        approval_hash=value["approval_hash"],
    )


def _row_from_mapping(value: object) -> CorrectionLedgerRow:
    fields = {
        "correction_id",
        "effective_at",
        "posting",
        "posting_index",
        "proposal_hash",
        "row_hash",
        "row_id",
    }
    if type(value) is not dict or set(value) != fields:
        raise Block9Error("durable correction row is incomplete")
    posting = value["posting"]
    if type(posting) is not dict or set(posting) != {"delta", "kind", "position_id"}:
        raise Block9Error("durable correction row posting is incomplete")
    return CorrectionLedgerRow(
        row_id=value["row_id"],
        correction_id=value["correction_id"],
        proposal_hash=value["proposal_hash"],
        posting_index=value["posting_index"],
        posting=CompensatingPosting(
            position_id=posting["position_id"],
            delta=posting["delta"],
            kind=posting["kind"],
        ),
        effective_at=_parse_timestamp(value["effective_at"], field="effective_at"),
        row_hash=value["row_hash"],
    )


def _group_from_mapping(value: object) -> CorrectionGroup:
    fields = {
        "group_id",
        "sequence_number",
        "previous_group_hash",
        "proposal",
        "operator_approval",
        "agent0_approval",
        "rows",
        "effective_at",
        "pre_state_hash",
        "post_state_hash",
        "group_hash",
    }
    if type(value) is not dict or set(value) != fields:
        raise Block9Error("durable correction group is incomplete")
    rows = value["rows"]
    if type(rows) is not list:
        raise Block9Error("durable correction group rows are incomplete")
    return CorrectionGroup(
        group_id=value["group_id"],
        sequence_number=value["sequence_number"],
        previous_group_hash=value["previous_group_hash"],
        proposal=_proposal_from_mapping(value["proposal"]),
        operator_approval=_approval_from_mapping(value["operator_approval"]),
        agent0_approval=_approval_from_mapping(value["agent0_approval"]),
        rows=tuple(_row_from_mapping(item) for item in rows),
        effective_at=_parse_timestamp(value["effective_at"], field="effective_at"),
        pre_state_hash=value["pre_state_hash"],
        post_state_hash=value["post_state_hash"],
        group_hash=value["group_hash"],
    )


def _rollover_correction_state(
    state: FinancialCorrectionState,
) -> FinancialCorrectionState:
    if len(state.groups) != 64:
        raise Block9Error("correction rollover requires exactly 64 groups")
    carried_rows = tuple(
        make_published_ledger_row(row.row_id, canonical_bytes(row.to_mapping()))
        for row in state.correction_rows
    )
    return initial_financial_correction_state(
        opening_supply=state.opening_supply,
        opening_total_minted=state.total_minted,
        opening_positions=state.positions,
        published_rows=(*state.published_rows, *carried_rows),
        authority_bindings=state.authority_bindings,
    )


def replay_durable_corrections(
    opening_state: FinancialCorrectionState,
    store: AppendOnlyEventStore,
    *,
    verifier: Callable[[bytes, bytes, str], bool],
) -> FinancialCorrectionState:
    """Rebuild financial state from genesis/opening state and canonical events."""

    if (
        type(opening_state) is not FinancialCorrectionState
        or type(store) is not AppendOnlyEventStore
    ):
        raise Block9Error("durable correction replay inputs must use exact types")
    state = opening_state
    for payload in _event_payloads(store):
        if payload.get("event_type") != "financial_correction":
            continue
        implementation = _financial_correction_implementation(
            payload.get("implementation_version"),
            payload.get("implementation_hash"),
        )
        request = payload.get("request")
        if type(request) is not dict or set(request) != {
            "proposal",
            "approvals",
            "effective_at",
        }:
            raise Block9Error("durable correction request is incomplete")
        approval_values = request["approvals"]
        if type(approval_values) is not list or len(approval_values) != 2:
            raise Block9Error("durable correction approvals are incomplete")
        proposal = _proposal_from_mapping(request["proposal"])
        approvals = (
            _approval_from_mapping(approval_values[0]),
            _approval_from_mapping(approval_values[1]),
        )
        request_hash = sha256_hex(canonical_bytes(request))
        signature_values = payload.get("approval_signatures")
        if type(signature_values) is not list or len(signature_values) != 2:
            raise Block9Error("durable correction signatures are incomplete")
        signatures = (
            _correction_signature_from_mapping(signature_values[0]),
            _correction_signature_from_mapping(signature_values[1]),
        )
        _verify_correction_signatures(
            request_hash=request_hash,
            approvals=approvals,
            signatures=signatures,
            verifier=verifier,
        )
        updated, group = implementation.apply(
            state,
            proposal=proposal,
            approvals=approvals,
            effective_at=_parse_timestamp(
                request["effective_at"], field="correction effective_at"
            ),
        )
        if payload.get("request_hash") != request_hash:
            raise Block9Error("durable correction request hash changed")
        if payload.get("group") != _group_mapping(group):
            raise Block9Error("durable correction group changed during replay")
        checkpoint = payload.get("checkpoint")
        if checkpoint is not None:
            if checkpoint != implementation.checkpoint(updated):
                raise Block9Error("durable correction checkpoint changed")
            updated = implementation.rollover(updated)
        elif len(updated.groups) == 64:
            raise Block9Error("durable correction checkpoint is missing")
        if payload.get("result") != _financial_result_mapping(updated):
            raise Block9Error("durable correction result changed during replay")
        state = updated
    return state


def build_correction_checkpoint(state: FinancialCorrectionState) -> dict[str, object]:
    if type(state) is not FinancialCorrectionState:
        raise Block9Error("correction checkpoint state must use the exact type")
    if len(state.groups) != 64:
        raise Block9Error("correction checkpoint requires exactly 64 groups")
    next_opening = _rollover_correction_state(state)
    payload = {
        "schema": "wea-vnext-correction-checkpoint-1",
        "group_count": 64,
        "ledger_head_hash": state.groups[-1].group_hash,
        "prior_segment_hash": state.opening_snapshot_hash,
        "positions": [
            {"position_id": item.position_id, "kind": item.kind, "amount": item.amount}
            for item in state.positions
        ],
        "total_minted": state.total_minted,
        "authority_registry": [
            {
                "authority_kind": item.authority_kind,
                "authority_id": item.authority_id,
                "binding_id": item.binding_id,
                "binding_version": item.binding_version,
            }
            for item in state.authority_bindings
        ],
        "state_hash": _financial_state_hash(state),
        "next_opening_snapshot_hash": next_opening.opening_snapshot_hash,
        "next_published_row_count": len(next_opening.published_rows),
    }
    canonical_bytes(payload)
    return payload


class DurableEventTransaction:
    """Stage complete event chains for the GitHub-native candidate workflow."""

    def __init__(
        self,
        store: AppendOnlyEventStore,
        canonical_event_hashes: Callable[[], tuple[str, ...]],
        stage_candidate: Callable[[tuple[bytes, ...]], object],
    ) -> None:
        if type(store) is not AppendOnlyEventStore:
            raise Block9Error("durable event store must use the exact type")
        if not callable(canonical_event_hashes) or not callable(stage_candidate):
            raise Block9Error("durable event transaction inputs are invalid")
        self.store = store
        self.canonical_event_hashes = canonical_event_hashes
        self.stage_candidate = stage_candidate

    def read_all(self) -> tuple[bytes, ...]:
        return self.store.read_all()

    def ensure_staged(self, sequence: int, event: bytes) -> None:
        events = self.store.read_all()
        if sequence >= len(events) or events[sequence] != event:
            raise Block9Error("durable event candidate changed")
        canonical_hashes = self.canonical_event_hashes()
        expected_hashes = tuple(sha256_hex(item) for item in events)
        if canonical_hashes == expected_hashes:
            return
        if canonical_hashes != expected_hashes[: len(canonical_hashes)]:
            raise Block9Error("canonical event chain does not match the local chain")
        if len(canonical_hashes) != sequence:
            raise Block9Error("canonical event sequence is not contiguous")
        self.stage_candidate(events)

    def append(
        self,
        *,
        sequence: int,
        payload: Mapping[str, object],
        after_local_append: Callable[[], object] | None = None,
    ) -> bytes:
        existing = self.store.read_all()
        event = self.store.prepare(sequence=sequence, payload=payload)
        if sequence < len(existing):
            self.ensure_staged(sequence, event)
            return event
        events = (*existing, event)
        existing_hashes = tuple(sha256_hex(item) for item in existing)
        if self.canonical_event_hashes() != existing_hashes:
            raise Block9Error("local event chain does not match canonical history")
        stored = self.store.append(sequence=sequence, payload=payload)
        if stored != event:
            raise Block9Error("durable event bytes changed during append")
        if after_local_append is not None:
            after_local_append()
        self.stage_candidate(events)
        return stored


class DurableCorrectionAdapter:
    """Bind the accepted S13C result to one append-only transaction event."""

    def __init__(self, transaction: DurableEventTransaction) -> None:
        if type(transaction) is not DurableEventTransaction:
            raise Block9Error("durable correction transaction must use the exact type")
        self.transaction = transaction
        self.store = transaction.store

    def apply(
        self,
        state: FinancialCorrectionState,
        *,
        proposal: CorrectionProposal,
        approvals: tuple[CorrectionApproval, CorrectionApproval],
        signatures: tuple[CorrectionSignature, CorrectionSignature],
        verifier: Callable[[bytes, bytes, str], bool],
        effective_at: datetime,
        fault: str | None = None,
    ) -> tuple[FinancialCorrectionState, CorrectionGroup, bytes]:
        if fault is not None and fault not in _FAULTS:
            raise Block9Error("unknown correction fault point")
        implementation = _financial_correction_implementation(
            DURABLE_CORRECTION_VERSION, DURABLE_CORRECTION_HASH
        )
        request_payload, request_hash = build_correction_request(
            proposal=proposal,
            approvals=approvals,
            effective_at=effective_at,
        )
        _verify_correction_signatures(
            request_hash=request_hash,
            approvals=approvals,
            signatures=signatures,
            verifier=verifier,
        )
        signature_payload = [
            _correction_signature_mapping(item)
            for item in sorted(signatures, key=lambda item: item.role)
        ]
        stored_events = self.store.read_all()
        stored_payloads = _event_payloads(self.store)
        matching_retry = False
        for sequence, (stored_raw, stored) in enumerate(
            zip(stored_events, stored_payloads, strict=True)
        ):
            if stored.get("idempotency_key") != proposal.idempotency_key:
                continue
            if stored.get("request_hash") != request_hash:
                raise Block9Error("correction idempotency key conflicts")
            if stored.get("approval_signatures") != signature_payload:
                raise Block9Error("correction signed approval evidence changed")
            matching_retry = True
            stored_result = stored.get("result")
            if type(stored_result) is dict and stored_result.get(
                "state_hash"
            ) == _financial_state_hash(state):
                self.transaction.ensure_staged(sequence, stored_raw)
                return state, _group_from_mapping(stored.get("group")), stored_raw
        prior_results = [
            stored.get("result")
            for stored in stored_payloads
            if stored.get("event_type") == "financial_correction"
        ]
        if (
            not matching_retry
            and prior_results
            and prior_results[-1] != _financial_result_mapping(state)
        ):
            raise Block9Error("financial correction state is stale")
        updated, group = implementation.apply(
            state,
            proposal=proposal,
            approvals=approvals,
            effective_at=effective_at,
        )
        if request_payload["effective_at"] != group.effective_at.isoformat().replace(
            "+00:00", "Z"
        ):
            raise Block9Error("correction effective_at normalization changed")
        checkpoint = (
            implementation.checkpoint(updated) if len(updated.groups) == 64 else None
        )
        result_state = (
            implementation.rollover(updated) if checkpoint is not None else updated
        )
        payload: dict[str, object] = {
            "event_type": "financial_correction",
            "implementation_version": DURABLE_CORRECTION_VERSION,
            "implementation_hash": DURABLE_CORRECTION_HASH,
            "request_hash": request_hash,
            "approval_signatures": signature_payload,
            "idempotency_key": proposal.idempotency_key,
            "request": request_payload,
            "group": _group_mapping(group),
            "result": _financial_result_mapping(result_state),
            "idempotency_result": {
                "idempotency_key": proposal.idempotency_key,
                "group_id": group.group_id,
                "status": "applied",
            },
        }
        if checkpoint is not None:
            payload["checkpoint"] = checkpoint
        for sequence, (stored_raw, stored) in enumerate(
            zip(stored_events, stored_payloads, strict=True)
        ):
            if stored.get("idempotency_key") != proposal.idempotency_key:
                continue
            if stored.get("request_hash") != request_hash:
                raise Block9Error("correction idempotency key conflicts")
            if stored.get("approval_signatures") != signature_payload:
                raise Block9Error("correction signed approval evidence changed")
            self.transaction.ensure_staged(sequence, stored_raw)
            if stored.get("group") == _group_mapping(group) and stored.get(
                "result"
            ) == _financial_result_mapping(result_state):
                return result_state, group, stored_raw
            stored_result = stored.get("result")
            if type(stored_result) is dict and stored_result.get(
                "state_hash"
            ) == _financial_state_hash(state):
                return state, _group_from_mapping(stored.get("group")), stored_raw
            raise Block9Error("correction retry state does not match the stored result")
        if fault in {"before_append", "before_file_replace"}:
            raise RuntimeError("injected correction failure before append")
        sequence = len(self.store.read_all())

        def fail_after_append() -> None:
            if fault in {
                "after_append",
                "before_commit_creation",
                "before_push",
                "before_remote_confirmation",
            }:
                raise RuntimeError("injected correction failure after append")

        stored_event = self.transaction.append(
            sequence=sequence,
            payload=payload,
            after_local_append=fail_after_append,
        )
        if fault in {"after_remote_confirmation", "before_projection_confirmation"}:
            raise RuntimeError("injected correction failure after remote confirmation")
        return result_state, group, stored_event


@dataclass(frozen=True, slots=True)
class RepairApproval:
    role: str
    source_identity: str
    binding_hash: str
    payload_hash: str
    signature: bytes

    def __post_init__(self) -> None:
        if self.role not in {"operator", "agent0"}:
            raise Block9Error("repair approval role is invalid")
        require_text(self.source_identity, field="repair approval source_identity")
        require_hash(self.binding_hash, field="repair approval binding_hash")
        require_hash(self.payload_hash, field="repair approval payload_hash")
        if type(self.signature) is not bytes or not self.signature:
            raise Block9Error("repair approval signature is missing")
        if self.role == "agent0" and self.source_identity != "agent0@system":
            raise Block9Error("repair Agent0 identity is not agent0@system")


def _repair_state_hash(state: Mapping[str, object]) -> str:
    return sha256_hex(canonical_bytes(_json_mapping(state, field="repair state")))


def _financial_projection_hash(state: Mapping[str, object]) -> str:
    value = _json_mapping(state, field="repair state")
    if any(key not in value for key in _FINANCIAL_KEYS):
        raise Block9Error("repair state has an incomplete financial projection")
    return sha256_hex(canonical_bytes({key: value[key] for key in _FINANCIAL_KEYS}))


def _apply_operation_v1(
    state: Mapping[str, object],
    operation: str,
    affected_ids: tuple[str, ...],
    patch: Mapping[str, object],
) -> dict[str, object]:
    updated = _json_mapping(state, field="repair state")
    patch_value = _json_mapping(patch, field="repair patch")
    expected_fields = {
        "void_event": set(),
        "executor_override": {"replacement"},
        "supersede_record": {"replacement"},
        "cursor_reset": {"cursor"},
    }
    if set(patch_value) != expected_fields.get(operation):
        raise Block9Error("repair patch fields do not match the operation")
    if operation == "void_event":
        current = updated.get("void_events")
        if type(current) is not list:
            raise Block9Error("void event projection is incomplete")
        updated["void_events"] = sorted(set(current) | set(affected_ids))
    elif operation == "executor_override":
        current = updated.get("executor_overrides")
        if type(current) is not dict:
            raise Block9Error("executor override projection is incomplete")
        replacement = patch_value.get("replacement")
        require_text(replacement, field="executor replacement")
        updated["executor_overrides"] = {
            **current,
            **{item: replacement for item in affected_ids},
        }
    elif operation == "supersede_record":
        current = updated.get("superseded_records")
        if type(current) is not dict:
            raise Block9Error("supersede projection is incomplete")
        replacement = patch_value.get("replacement")
        require_text(replacement, field="superseding record")
        updated["superseded_records"] = {
            **current,
            **{item: replacement for item in affected_ids},
        }
    elif operation == "cursor_reset":
        updated["cursor"] = require_text(
            patch_value.get("cursor"), field="repair cursor"
        )
    else:  # pragma: no cover - constructor proof
        raise Block9Error("repair operation is invalid")
    return updated


@dataclass(frozen=True, slots=True)
class ReplayRepairRequest:
    repair_id: str
    operation: str
    affected_ids: tuple[str, ...]
    violated_rule: str
    implementation_hashes: tuple[tuple[str, str], ...]
    implementation_version: str
    implementation_hash: str
    effective_transaction: int
    pre_state_hash: str
    post_state_hash: str
    post_state_bytes: bytes
    patch_bytes: bytes
    idempotency_key: str
    payload_hash: str

    @classmethod
    def create(
        cls,
        *,
        repair_id: str,
        operation: str,
        affected_ids: tuple[str, ...],
        violated_rule: str,
        implementation_hashes: Mapping[str, str],
        effective_transaction: int,
        pre_state: Mapping[str, object],
        patch: Mapping[str, object],
        post_state: Mapping[str, object] | None = None,
        idempotency_key: str,
        _implementation_version: str | None = None,
        _implementation_hash: str | None = None,
    ) -> ReplayRepairRequest:
        require_text(repair_id, field="repair_id")
        if operation not in _REPAIR_OPERATIONS:
            raise Block9Error("repair operation is not accepted")
        if type(affected_ids) is not tuple or not affected_ids:
            raise Block9Error("repair affected_ids must be a non-empty tuple")
        if len(set(affected_ids)) != len(affected_ids):
            raise Block9Error("repair affected_ids contain duplicates")
        for item in affected_ids:
            require_text(item, field="repair affected_id")
        require_text(violated_rule, field="violated_rule")
        if not isinstance(implementation_hashes, Mapping) or not implementation_hashes:
            raise Block9Error("repair implementation hashes are missing")
        hashes: list[tuple[str, str]] = []
        for name, digest in sorted(implementation_hashes.items()):
            require_text(name, field="repair implementation name")
            require_hash(digest, field=f"repair implementation {name}")
            hashes.append((name, digest))
        selected_version = (
            REPLAY_REPAIR_VERSION
            if _implementation_version is None
            else _implementation_version
        )
        selected_hash = (
            REPLAY_REPAIR_HASH if _implementation_hash is None else _implementation_hash
        )
        implementation = _replay_repair_implementation(selected_version, selected_hash)
        require_positive_int(effective_transaction, field="effective_transaction")
        require_text(idempotency_key, field="repair idempotency_key")
        before = _json_mapping(pre_state, field="repair pre_state")
        patch_value = _json_mapping(patch, field="repair patch")
        immediate = implementation.apply_operation(
            before, operation, affected_ids, patch_value
        )
        after = (
            immediate
            if post_state is None
            else _json_mapping(post_state, field="repair post_state")
        )
        control_field = {
            "void_event": "void_events",
            "executor_override": "executor_overrides",
            "supersede_record": "superseded_records",
            "cursor_reset": "cursor",
        }[operation]
        if after.get(control_field) != immediate.get(control_field):
            raise Block9Error(
                "repair post-state does not contain the approved operation"
            )
        if _financial_projection_hash(before) != _financial_projection_hash(after):
            raise Block9Error("replay repair changed the financial projection")
        pre_hash = _repair_state_hash(before)
        post_hash = _repair_state_hash(after)
        core = {
            "repair_id": repair_id,
            "operation": operation,
            "affected_ids": list(affected_ids),
            "violated_rule": violated_rule,
            "implementation_hashes": dict(hashes),
            "effective_transaction": effective_transaction,
            "pre_state_hash": pre_hash,
            "post_state_hash": post_hash,
            "patch": patch_value,
            "idempotency_key": idempotency_key,
            "repair_implementation_version": selected_version,
            "repair_implementation_hash": selected_hash,
        }
        return cls(
            repair_id,
            operation,
            affected_ids,
            violated_rule,
            tuple(hashes),
            selected_version,
            selected_hash,
            effective_transaction,
            pre_hash,
            post_hash,
            canonical_bytes(after),
            canonical_bytes(patch_value),
            idempotency_key,
            sha256_hex(canonical_bytes(core)),
        )

    @property
    def patch(self) -> dict[str, object]:
        value = json.loads(self.patch_bytes)
        if type(value) is not dict:  # pragma: no cover - constructor proof
            raise Block9Error("repair patch is not a mapping")
        return value

    @property
    def post_state(self) -> dict[str, object]:
        value = json.loads(self.post_state_bytes)
        if type(value) is not dict:  # pragma: no cover - constructor proof
            raise Block9Error("repair post-state is not a mapping")
        return value


def _verify_repair_approvals(
    request: ReplayRepairRequest,
    approvals: tuple[RepairApproval, RepairApproval],
    verifier: Callable[[bytes, bytes, str], bool],
) -> None:
    if type(approvals) is not tuple or len(approvals) != 2:
        raise Block9Error("repair needs exactly two approvals")
    by_role = {item.role: item for item in approvals if type(item) is RepairApproval}
    if set(by_role) != {"operator", "agent0"}:
        raise Block9Error("repair approvals must be operator and Agent0")
    if by_role["operator"].source_identity == by_role["agent0"].source_identity:
        raise Block9Error("repair operator and Agent0 identities must differ")
    if by_role["operator"].binding_hash == by_role["agent0"].binding_hash:
        raise Block9Error("repair authority bindings must differ")
    for role in ("operator", "agent0"):
        approval = by_role[role]
        if approval.payload_hash != request.payload_hash:
            raise Block9Error("repair approval payload hash does not match")
        payload = canonical_bytes(
            {
                "role": approval.role,
                "source_identity": approval.source_identity,
                "binding_hash": approval.binding_hash,
                "payload_hash": approval.payload_hash,
            }
        )
        if not verifier(payload, approval.signature, "wea-vnext-replay-repair"):
            raise Block9Error(f"{role} repair signature did not verify")


def _repair_approval_mapping(approval: RepairApproval) -> dict[str, object]:
    return {
        "role": approval.role,
        "source_identity": approval.source_identity,
        "binding_hash": approval.binding_hash,
        "payload_hash": approval.payload_hash,
        "signature_hex": approval.signature.hex(),
    }


def _repair_approval_from_mapping(value: object) -> RepairApproval:
    if type(value) is not dict or set(value) != {
        "role",
        "source_identity",
        "binding_hash",
        "payload_hash",
        "signature_hex",
    }:
        raise Block9Error("durable repair approval is incomplete")
    signature_hex = value["signature_hex"]
    if type(signature_hex) is not str:
        raise Block9Error("durable repair signature is invalid")
    try:
        signature = bytes.fromhex(signature_hex)
    except ValueError as exc:
        raise Block9Error("durable repair signature is invalid") from exc
    return RepairApproval(
        role=value["role"],
        source_identity=value["source_identity"],
        binding_hash=value["binding_hash"],
        payload_hash=value["payload_hash"],
        signature=signature,
    )


def apply_replay_repair(
    transaction: DurableEventTransaction,
    state: Mapping[str, object],
    request: ReplayRepairRequest,
    *,
    opening_state: Mapping[str, object],
    approvals: tuple[RepairApproval, RepairApproval],
    verifier: Callable[[bytes, bytes, str], bool],
    event_reducer: Callable[
        [Mapping[str, object], Mapping[str, object], int], Mapping[str, object]
    ],
) -> tuple[dict[str, object], bytes]:
    if (
        type(transaction) is not DurableEventTransaction
        or type(request) is not ReplayRepairRequest
    ):
        raise Block9Error("repair inputs must use exact types")
    before = _json_mapping(state, field="repair state")
    _verify_repair_approvals(request, approvals, verifier)
    for sequence, (stored_raw, stored) in enumerate(
        zip(transaction.read_all(), _event_payloads(transaction.store), strict=True)
    ):
        if stored.get("idempotency_key") != request.idempotency_key:
            continue
        if stored.get("request_hash") != request.payload_hash:
            raise Block9Error("repair idempotency key conflicts")
        raw_result = stored.get("result")
        if type(raw_result) is not dict:
            raise Block9Error("stored repair result is incomplete")
        stored_result = _json_mapping(raw_result, field="repair result")
        if _repair_state_hash(stored_result) != request.post_state_hash:
            raise Block9Error("stored repair result changed")
        current_hash = _repair_state_hash(before)
        if current_hash == request.pre_state_hash:
            expected_result = request.post_state
            if expected_result != stored_result:
                raise Block9Error("stored repair result changed")
        elif current_hash == request.post_state_hash:
            if before != stored_result:
                raise Block9Error("repair post-state bytes changed")
        else:
            raise Block9Error("repair retry state does not match stored result")
        transaction.ensure_staged(sequence, stored_raw)
        return stored_result, stored_raw
    if _repair_state_hash(before) != request.pre_state_hash:
        raise Block9Error("repair pre-state hash changed")
    existing_payloads = _event_payloads(transaction.store)
    if (
        request.effective_transaction > len(existing_payloads)
        or existing_payloads[request.effective_transaction - 1].get("event_type")
        == "replay_repair"
    ):
        raise Block9Error("repair effective transaction is not in prior history")
    after = request.post_state
    if _financial_projection_hash(before) != _financial_projection_hash(after):
        raise Block9Error("replay repair changed the financial projection")
    if _repair_state_hash(after) != request.post_state_hash:
        raise Block9Error("repair post-state hash changed")
    replayed = replay_durable_repairs(
        opening_state,
        transaction.store,
        verifier=verifier,
        event_reducer=event_reducer,
        _candidate=request,
    )
    if replayed != after:
        raise Block9Error("repair post-state does not match deterministic replay")
    payload = {
        "event_type": "replay_repair",
        "implementation_version": request.implementation_version,
        "implementation_hash": request.implementation_hash,
        "repair_id": request.repair_id,
        "operation": request.operation,
        "affected_ids": list(request.affected_ids),
        "violated_rule": request.violated_rule,
        "implementation_hashes": dict(request.implementation_hashes),
        "effective_transaction": request.effective_transaction,
        "pre_state_hash": request.pre_state_hash,
        "post_state_hash": request.post_state_hash,
        "patch": request.patch,
        "idempotency_key": request.idempotency_key,
        "request_hash": request.payload_hash,
        "approval_hashes": [
            sha256_hex(
                canonical_bytes({"role": item.role, "payload_hash": item.payload_hash})
            )
            for item in sorted(approvals, key=lambda item: item.role)
        ],
    }
    sequence = len(transaction.read_all())
    payload["approvals"] = [
        _repair_approval_mapping(item)
        for item in sorted(approvals, key=lambda item: item.role)
    ]
    payload["result"] = after
    event = transaction.append(sequence=sequence, payload=payload)
    return after, event


def _replay_repair_prefix(
    opening_state: Mapping[str, object],
    payloads: tuple[dict[str, object], ...],
    repairs: tuple[ReplayRepairRequest, ...],
    *,
    stop: int,
    event_reducer: Callable[
        [Mapping[str, object], Mapping[str, object], int], Mapping[str, object]
    ],
) -> dict[str, object]:
    state = _json_mapping(opening_state, field="repair opening state")
    by_transaction: dict[int, list[ReplayRepairRequest]] = {}
    for repair in repairs:
        by_transaction.setdefault(repair.effective_transaction, []).append(repair)
    for sequence, payload in enumerate(payloads[:stop]):
        transaction_number = sequence + 1
        for repair in by_transaction.get(transaction_number, []):
            implementation = _replay_repair_implementation(
                repair.implementation_version, repair.implementation_hash
            )
            state = implementation.apply_operation(
                state, repair.operation, repair.affected_ids, repair.patch
            )
        if payload.get("event_type") == "replay_repair":
            continue
        reduced = event_reducer(state, payload, transaction_number)
        state = _json_mapping(reduced, field="repair event reducer result")
    return state


def replay_durable_repairs(
    opening_state: Mapping[str, object],
    store: AppendOnlyEventStore,
    *,
    verifier: Callable[[bytes, bytes, str], bool],
    event_reducer: Callable[
        [Mapping[str, object], Mapping[str, object], int], Mapping[str, object]
    ],
    _candidate: ReplayRepairRequest | None = None,
) -> dict[str, object]:
    """Rebuild non-financial derived state and verify every repair approval."""

    if type(store) is not AppendOnlyEventStore:
        raise Block9Error("durable repair replay store must use the exact type")
    if not callable(event_reducer):
        raise Block9Error("durable repair replay needs an event reducer")
    payloads = _event_payloads(store)
    repairs: list[ReplayRepairRequest] = []
    seen_idempotency: dict[str, str] = {}
    for sequence, payload in enumerate(payloads):
        if payload.get("event_type") != "replay_repair":
            continue
        implementation_version = require_text(
            payload.get("implementation_version"),
            field="repair implementation version",
        )
        implementation_hash = require_hash(
            payload.get("implementation_hash"),
            field="repair implementation hash",
        )
        _replay_repair_implementation(implementation_version, implementation_hash)
        idempotency_key = require_text(
            payload.get("idempotency_key"), field="repair idempotency_key"
        )
        request_hash = require_hash(
            payload.get("request_hash"), field="repair request_hash"
        )
        previous_request = seen_idempotency.get(idempotency_key)
        if previous_request is not None:
            if previous_request != request_hash:
                raise Block9Error("repair idempotency key conflicts during replay")
            raise Block9Error("repair idempotency key repeats during replay")
        implementation_hashes = payload.get("implementation_hashes")
        affected_ids = payload.get("affected_ids")
        patch = payload.get("patch")
        if (
            type(implementation_hashes) is not dict
            or type(affected_ids) is not list
            or type(patch) is not dict
        ):
            raise Block9Error("durable repair request is incomplete")
        effective_transaction = require_positive_int(
            payload.get("effective_transaction"), field="effective_transaction"
        )
        if (
            effective_transaction > sequence
            or payloads[effective_transaction - 1].get("event_type") == "replay_repair"
        ):
            raise Block9Error("repair effective transaction is not prior history")
        before = _replay_repair_prefix(
            opening_state,
            payloads,
            tuple(repairs),
            stop=sequence,
            event_reducer=event_reducer,
        )
        raw_result = payload.get("result")
        if type(raw_result) is not dict:
            raise Block9Error("durable repair result is incomplete")
        request = ReplayRepairRequest.create(
            repair_id=require_text(payload.get("repair_id"), field="repair_id"),
            operation=require_text(payload.get("operation"), field="repair operation"),
            affected_ids=tuple(affected_ids),
            violated_rule=require_text(
                payload.get("violated_rule"), field="violated_rule"
            ),
            implementation_hashes=implementation_hashes,
            effective_transaction=effective_transaction,
            pre_state=before,
            patch=patch,
            post_state=raw_result,
            idempotency_key=idempotency_key,
            _implementation_version=implementation_version,
            _implementation_hash=implementation_hash,
        )
        if request.payload_hash != request_hash:
            raise Block9Error("durable repair request hash changed")
        approval_values = payload.get("approvals")
        if type(approval_values) is not list or len(approval_values) != 2:
            raise Block9Error("durable repair approvals are incomplete")
        approvals = (
            _repair_approval_from_mapping(approval_values[0]),
            _repair_approval_from_mapping(approval_values[1]),
        )
        _verify_repair_approvals(request, approvals, verifier)
        expected_approval_hashes = [
            sha256_hex(
                canonical_bytes({"role": item.role, "payload_hash": item.payload_hash})
            )
            for item in sorted(approvals, key=lambda item: item.role)
        ]
        if payload.get("approval_hashes") != expected_approval_hashes:
            raise Block9Error("durable repair approval hashes changed")
        updated = _replay_repair_prefix(
            opening_state,
            payloads,
            (*repairs, request),
            stop=sequence,
            event_reducer=event_reducer,
        )
        if _financial_projection_hash(before) != _financial_projection_hash(updated):
            raise Block9Error("durable repair changed the financial projection")
        if _repair_state_hash(updated) != request.post_state_hash:
            raise Block9Error("durable repair result hash changed")
        if raw_result != updated:
            raise Block9Error("durable repair result changed during replay")
        seen_idempotency[request.idempotency_key] = request.payload_hash
        repairs.append(request)
    current = _replay_repair_prefix(
        opening_state,
        payloads,
        tuple(repairs),
        stop=len(payloads),
        event_reducer=event_reducer,
    )
    if _candidate is None:
        return current
    if type(_candidate) is not ReplayRepairRequest:
        raise Block9Error("repair candidate must use the exact type")
    if (
        _candidate.effective_transaction > len(payloads)
        or payloads[_candidate.effective_transaction - 1].get("event_type")
        == "replay_repair"
    ):
        raise Block9Error("repair effective transaction is not prior history")
    if _repair_state_hash(current) != _candidate.pre_state_hash:
        raise Block9Error("repair candidate pre-state changed during replay")
    return _replay_repair_prefix(
        opening_state,
        payloads,
        (*repairs, _candidate),
        stop=len(payloads),
        event_reducer=event_reducer,
    )


# This registry is append-only after activation. A behavior change adds a new
# version and handler; it never replaces the handler needed by historical events.
_FINANCIAL_CORRECTION_IMPLEMENTATIONS = MappingProxyType(
    {
        DURABLE_CORRECTION_VERSION: _FinancialCorrectionImplementation(
            DURABLE_CORRECTION_HASH,
            apply_financial_correction,
            build_correction_checkpoint,
            _rollover_correction_state,
        )
    }
)
_REPLAY_REPAIR_IMPLEMENTATIONS = MappingProxyType(
    {
        REPLAY_REPAIR_VERSION: _ReplayRepairImplementation(
            REPLAY_REPAIR_HASH,
            _apply_operation_v1,
        )
    }
)


def select_recovery_mode(*, sequence_zero_present: bool, chain_valid: bool) -> str:
    if type(sequence_zero_present) is not bool or type(chain_valid) is not bool:
        raise Block9Error("recovery evidence must be boolean")
    if not chain_valid:
        return "blocked"
    return "forward-repair" if sequence_zero_present else "pre-cutover"


__all__ = [
    "DURABLE_CORRECTION_HASH",
    "DURABLE_CORRECTION_VERSION",
    "REPLAY_REPAIR_HASH",
    "REPLAY_REPAIR_VERSION",
    "CorrectionSignature",
    "DurableCorrectionAdapter",
    "DurableEventTransaction",
    "RepairApproval",
    "ReplayRepairRequest",
    "apply_replay_repair",
    "build_correction_checkpoint",
    "build_correction_request",
    "replay_durable_corrections",
    "replay_durable_repairs",
    "select_recovery_mode",
]
