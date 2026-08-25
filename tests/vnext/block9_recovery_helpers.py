from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from wea_vnext.block9.common import sha256_hex
from wea_vnext.block9.cutover import AppendOnlyEventStore
from wea_vnext.block9.recovery import (
    CorrectionSignature,
    DurableEventTransaction,
    build_correction_request,
)
from wea_vnext.financial_correction import CorrectionApproval, CorrectionProposal


@dataclass(frozen=True)
class RecoverySnapshot:
    head: str = "a" * 40
    authority_hash: str = "3" * 64
    bootstrap: object | None = None
    repository_id: str = "repo-1"
    target_ref: str = "refs/heads/main"
    head_commit: object | None = None
    event_hashes: tuple[str, ...] = ()


class RecoveryRemote:
    """Test double: staging immediately simulates the later reviewed merge."""

    def __init__(self) -> None:
        self.snapshot = RecoverySnapshot()
        self.staged: list[tuple[bytes, ...]] = []

    def event_hashes(self) -> tuple[str, ...]:
        return self.snapshot.event_hashes

    def stage(self, events: tuple[bytes, ...]) -> None:
        self.staged.append(events)
        digest = sha256_hex(b"".join(events))
        self.snapshot = replace(
            self.snapshot,
            head=digest[:40],
            event_hashes=tuple(sha256_hex(event) for event in events),
        )


def durable_transaction(
    root: Path,
    remote: RecoveryRemote | None = None,
) -> tuple[DurableEventTransaction, RecoveryRemote]:
    selected = remote or RecoveryRemote()
    return (
        DurableEventTransaction(
            AppendOnlyEventStore(root),
            selected.event_hashes,
            selected.stage,
        ),
        selected,
    )


def correction_signatures(
    proposal: CorrectionProposal,
    approvals: tuple[CorrectionApproval, CorrectionApproval],
    effective_at,
) -> tuple[CorrectionSignature, CorrectionSignature]:
    _, request_hash = build_correction_request(
        proposal=proposal,
        approvals=approvals,
        effective_at=effective_at,
    )
    by_role = {item.authority_kind: item for item in approvals}
    return tuple(
        CorrectionSignature(
            role=role,
            source_identity=(
                "agent0@system" if role == "agent0" else "operator@local"
            ),
            authority_id=by_role[role].authority_id,
            source_revision=by_role[role].authority_revision_id,
            binding_id=by_role[role].binding_id,
            binding_version=by_role[role].binding_version,
            binding_hash=("1" if role == "operator" else "2") * 64,
            request_hash=request_hash,
            signature=f"{role}-signature".encode(),
        )
        for role in ("operator", "agent0")
    )  # type: ignore[return-value]


def verify_test_signature(payload: bytes, signature: bytes, namespace: str) -> bool:
    return bool(payload and signature) and namespace == "wea-vnext-financial-correction"
