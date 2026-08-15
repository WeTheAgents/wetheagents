"""Inactive append-only financial-correction control plane for WEA vNext.

This pure module owns no persistence, current-ledger writer, runtime facade,
network access, or GitHub integration. It validates immutable correction state
and returns a complete new state only after every S-13C condition passes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import islice
from typing import TypeVar

_HASH = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._:@/-]{0,510}[a-z0-9])?")
_POSITION_KINDS = frozenset({"balance", "escrow"})
_POSTING_KINDS = frozenset({"transfer", "mint", "burn"})
_AUTHORITY_KINDS = frozenset({"operator", "agent0"})
_MAX_ROW_BYTES = 1024 * 1024
_MAX_PUBLISHED_BYTES = 64 * 1024 * 1024
_MAX_OPENING_POSITIONS = 10_000
_MAX_PUBLISHED_ROWS = 100_000
_MAX_AUTHORITY_BINDINGS = 128
_MAX_AFFECTED_LEDGER_IDS = 256
_MAX_POSTINGS_PER_PROPOSAL = 128
_MAX_CORRECTION_GROUPS = 64

_T = TypeVar("_T")
_HashableT = TypeVar("_HashableT", bound=Hashable)


class FinancialCorrectionError(ValueError):
    """A correction value or transition violates the accepted S-13C contract."""


def _bounded_tuple(
    values: Iterable[_T],
    *,
    limit: int,
    field: str,
) -> tuple[_T, ...]:
    """Collect no more than one item beyond a public iterable's limit."""

    try:
        items = tuple(islice(values, limit + 1))
    except TypeError as exc:
        raise FinancialCorrectionError(f"{field} must be iterable") from exc
    if len(items) > limit:
        raise FinancialCorrectionError(f"{field} exceed the accepted limit")
    return items


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise FinancialCorrectionError(
            "value is not canonicalizable JSON"
        ) from exc


def _hash_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_hash(value: object, *, field: str) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        raise FinancialCorrectionError(f"{field} must be a lowercase SHA-256")
    return value


def _require_identifier(value: object, *, field: str) -> str:
    if type(value) is not str or not _IDENTIFIER.fullmatch(value):
        raise FinancialCorrectionError(f"{field} must be a canonical identifier")
    return value


def _require_nonnegative_integer(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise FinancialCorrectionError(
            f"{field} must be a non-negative integer"
        )
    return value


def _require_integer(value: object, *, field: str) -> int:
    if type(value) is not int:
        raise FinancialCorrectionError(f"{field} must be an integer")
    return value


def _utc(value: datetime, *, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None:
        raise FinancialCorrectionError(
            f"{field} must be a timezone-aware datetime"
        )
    try:
        if value.utcoffset() is None:
            raise FinancialCorrectionError(
                f"{field} must have a defined UTC offset"
            )
        return value.astimezone(timezone.utc)
    except FinancialCorrectionError:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise FinancialCorrectionError(
            f"{field} cannot be normalized to UTC"
        ) from exc


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _require_unique(
    values: Iterable[_HashableT],
    *,
    field: str,
) -> tuple[_HashableT, ...]:
    items = tuple(values)
    if len(items) != len(set(items)):
        raise FinancialCorrectionError(f"state contains duplicate {field}")
    return items


@dataclass(frozen=True)
class MoneyPosition:
    """One known balance or escrow position at a state boundary."""

    position_id: str
    kind: str
    amount: int

    def __post_init__(self) -> None:
        _require_identifier(self.position_id, field="position_id")
        if type(self.kind) is not str or self.kind not in _POSITION_KINDS:
            raise FinancialCorrectionError("position kind must be balance or escrow")
        _require_nonnegative_integer(self.amount, field="position amount")

    def to_mapping(self) -> dict[str, object]:
        return {
            "amount": self.amount,
            "kind": self.kind,
            "position_id": self.position_id,
        }


def _rebuild_position(position: MoneyPosition) -> MoneyPosition:
    if type(position) is not MoneyPosition:
        raise FinancialCorrectionError(
            "positions must use the exact MoneyPosition type"
        )
    try:
        return MoneyPosition(position.position_id, position.kind, position.amount)
    except AttributeError as exc:
        raise FinancialCorrectionError("money position is incomplete") from exc


@dataclass(frozen=True)
class PublishedLedgerRow:
    """Exact prior ledger bytes and their immutable row identity."""

    ledger_id: str
    content: bytes
    content_hash: str

    def __post_init__(self) -> None:
        _require_identifier(self.ledger_id, field="ledger_id")
        if type(self.content) is not bytes or len(self.content) > _MAX_ROW_BYTES:
            raise FinancialCorrectionError(
                "published row content must be bounded exact bytes"
            )
        _require_hash(self.content_hash, field="published row content_hash")
        if hashlib.sha256(self.content).hexdigest() != self.content_hash:
            raise FinancialCorrectionError(
                "published row content hash does not match its bytes"
            )


def make_published_ledger_row(
    ledger_id: str,
    content: bytes,
) -> PublishedLedgerRow:
    """Bind exact published bytes to a canonical ledger identity."""

    ledger_id = _require_identifier(ledger_id, field="ledger_id")
    if type(content) is not bytes or len(content) > _MAX_ROW_BYTES:
        raise FinancialCorrectionError(
            "published row content must be bounded exact bytes"
        )
    return PublishedLedgerRow(
        ledger_id=ledger_id,
        content=content,
        content_hash=hashlib.sha256(content).hexdigest(),
    )


def _rebuild_published_row(row: PublishedLedgerRow) -> PublishedLedgerRow:
    if type(row) is not PublishedLedgerRow:
        raise FinancialCorrectionError(
            "published rows must use the exact PublishedLedgerRow type"
        )
    try:
        return PublishedLedgerRow(row.ledger_id, row.content, row.content_hash)
    except AttributeError as exc:
        raise FinancialCorrectionError("published ledger row is incomplete") from exc


def _rebuild_published_rows(
    rows: Iterable[PublishedLedgerRow],
) -> tuple[PublishedLedgerRow, ...]:
    rebuilt: list[PublishedLedgerRow] = []
    content_bytes = 0
    for row in rows:
        if type(row) is not PublishedLedgerRow:
            raise FinancialCorrectionError(
                "published rows must use the exact PublishedLedgerRow type"
            )
        try:
            content = row.content
        except AttributeError as exc:
            raise FinancialCorrectionError(
                "published ledger row is incomplete"
            ) from exc
        if type(content) is not bytes or len(content) > _MAX_ROW_BYTES:
            raise FinancialCorrectionError(
                "published row content must be bounded exact bytes"
            )
        content_bytes += len(content)
        if content_bytes > _MAX_PUBLISHED_BYTES:
            raise FinancialCorrectionError(
                "published row content exceeds the aggregate byte limit"
            )
        rebuilt.append(_rebuild_published_row(row))
    return tuple(rebuilt)


@dataclass(frozen=True)
class VerifiedCorrectionAuthority:
    """One verified operator or Agent0 authority binding."""

    authority_kind: str
    authority_id: str
    authority_revision_id: str
    binding_id: str
    binding_version: int
    effective_from: datetime
    effective_until: datetime | None = None

    def __post_init__(self) -> None:
        if (
            type(self.authority_kind) is not str
            or self.authority_kind not in _AUTHORITY_KINDS
        ):
            raise FinancialCorrectionError(
                "authority_kind must be operator or agent0"
            )
        _require_identifier(self.authority_id, field="authority_id")
        _require_identifier(
            self.authority_revision_id,
            field="authority_revision_id",
        )
        _require_identifier(self.binding_id, field="binding_id")
        if type(self.binding_version) is not int or self.binding_version < 1:
            raise FinancialCorrectionError(
                "binding_version must be a positive integer"
            )
        effective_from = _utc(self.effective_from, field="effective_from")
        effective_until = (
            None
            if self.effective_until is None
            else _utc(self.effective_until, field="effective_until")
        )
        if effective_until is not None and effective_until <= effective_from:
            raise FinancialCorrectionError(
                "authority binding interval must be positive"
            )
        object.__setattr__(self, "effective_from", effective_from)
        object.__setattr__(self, "effective_until", effective_until)

    def active_at(self, at: datetime) -> bool:
        instant = _utc(at, field="authority active_at")
        return self.effective_from <= instant and (
            self.effective_until is None or instant < self.effective_until
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "authority_id": self.authority_id,
            "authority_kind": self.authority_kind,
            "authority_revision_id": self.authority_revision_id,
            "binding_id": self.binding_id,
            "binding_version": self.binding_version,
            "effective_from": _timestamp(self.effective_from),
            "effective_until": (
                None
                if self.effective_until is None
                else _timestamp(self.effective_until)
            ),
        }


def _rebuild_authority(
    authority: VerifiedCorrectionAuthority,
) -> VerifiedCorrectionAuthority:
    if type(authority) is not VerifiedCorrectionAuthority:
        raise FinancialCorrectionError(
            "authority bindings must use the exact verified type"
        )
    try:
        return VerifiedCorrectionAuthority(
            authority_kind=authority.authority_kind,
            authority_id=authority.authority_id,
            authority_revision_id=authority.authority_revision_id,
            binding_id=authority.binding_id,
            binding_version=authority.binding_version,
            effective_from=authority.effective_from,
            effective_until=authority.effective_until,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError("authority binding is incomplete") from exc


def _authority_sort_key(
    authority: VerifiedCorrectionAuthority,
) -> tuple[str, str, str, str, int, str, str]:
    return (
        authority.authority_kind,
        authority.authority_id,
        authority.authority_revision_id,
        authority.binding_id,
        authority.binding_version,
        _timestamp(authority.effective_from),
        (
            ""
            if authority.effective_until is None
            else _timestamp(authority.effective_until)
        ),
    )


def _opening_snapshot_payload(
    *,
    opening_supply: int,
    opening_total_minted: int,
    opening_positions: tuple[MoneyPosition, ...],
    published_rows: tuple[PublishedLedgerRow, ...],
    authority_bindings: tuple[VerifiedCorrectionAuthority, ...],
) -> dict[str, object]:
    return {
        "authority_bindings": [item.to_mapping() for item in authority_bindings],
        "opening_positions": [item.to_mapping() for item in opening_positions],
        "opening_supply": opening_supply,
        "opening_total_minted": opening_total_minted,
        "published_rows": [
            {
                "content_hash": row.content_hash,
                "content_length": len(row.content),
                "ledger_id": row.ledger_id,
            }
            for row in published_rows
        ],
    }


def _opening_snapshot_hash(
    *,
    opening_supply: int,
    opening_total_minted: int,
    opening_positions: tuple[MoneyPosition, ...],
    published_rows: tuple[PublishedLedgerRow, ...],
    authority_bindings: tuple[VerifiedCorrectionAuthority, ...],
) -> str:
    return _hash_value(
        _opening_snapshot_payload(
            opening_supply=opening_supply,
            opening_total_minted=opening_total_minted,
            opening_positions=opening_positions,
            published_rows=published_rows,
            authority_bindings=authority_bindings,
        )
    )


@dataclass(frozen=True)
class CompensatingPosting:
    """One exact signed financial-position change."""

    position_id: str
    delta: int
    kind: str

    def __post_init__(self) -> None:
        _require_identifier(self.position_id, field="posting position_id")
        if type(self.delta) is not int or self.delta == 0:
            raise FinancialCorrectionError(
                "posting delta must be a non-zero integer"
            )
        if type(self.kind) is not str or self.kind not in _POSTING_KINDS:
            raise FinancialCorrectionError(
                "posting kind must be transfer, mint, or burn"
            )
        if self.kind == "mint" and self.delta < 0:
            raise FinancialCorrectionError("mint posting delta must be positive")
        if self.kind == "burn" and self.delta > 0:
            raise FinancialCorrectionError("burn posting delta must be negative")

    def to_mapping(self) -> dict[str, object]:
        return {
            "delta": self.delta,
            "kind": self.kind,
            "position_id": self.position_id,
        }


def _rebuild_posting(posting: CompensatingPosting) -> CompensatingPosting:
    if type(posting) is not CompensatingPosting:
        raise FinancialCorrectionError(
            "postings must use the exact CompensatingPosting type"
        )
    try:
        return CompensatingPosting(
            posting.position_id,
            posting.delta,
            posting.kind,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError("compensating posting is incomplete") from exc


def _proposal_payload(
    *,
    correction_id: str,
    affected_ledger_ids: tuple[str, ...],
    postings: tuple[CompensatingPosting, ...],
    idempotency_key: str,
) -> dict[str, object]:
    return {
        "affected_ledger_ids": list(affected_ledger_ids),
        "correction_id": correction_id,
        "idempotency_key": idempotency_key,
        "postings": [posting.to_mapping() for posting in postings],
    }


@dataclass(frozen=True)
class CorrectionProposal:
    """One exact canonical proposal approved by both required roles."""

    correction_id: str
    affected_ledger_ids: tuple[str, ...]
    postings: tuple[CompensatingPosting, ...]
    idempotency_key: str
    proposal_hash: str

    def __post_init__(self) -> None:
        _require_identifier(self.correction_id, field="correction_id")
        _require_identifier(self.idempotency_key, field="idempotency_key")
        if type(self.affected_ledger_ids) is not tuple or not self.affected_ledger_ids:
            raise FinancialCorrectionError(
                "affected_ledger_ids must be a non-empty immutable tuple"
            )
        if len(self.affected_ledger_ids) > _MAX_AFFECTED_LEDGER_IDS:
            raise FinancialCorrectionError(
                "affected_ledger_ids exceed the correction proposal limit"
            )
        affected = tuple(
            _require_identifier(value, field="affected ledger_id")
            for value in self.affected_ledger_ids
        )
        if affected != tuple(sorted(affected)) or len(affected) != len(set(affected)):
            raise FinancialCorrectionError(
                "affected_ledger_ids must be sorted and duplicate-free"
            )
        if type(self.postings) is not tuple or not self.postings:
            raise FinancialCorrectionError(
                "postings must be a non-empty immutable tuple"
            )
        if len(self.postings) > _MAX_POSTINGS_PER_PROPOSAL:
            raise FinancialCorrectionError(
                "postings exceed the correction proposal limit"
            )
        postings = tuple(_rebuild_posting(posting) for posting in self.postings)
        object.__setattr__(self, "postings", postings)
        _require_hash(self.proposal_hash, field="proposal_hash")
        expected = _hash_value(
            _proposal_payload(
                correction_id=self.correction_id,
                affected_ledger_ids=affected,
                postings=postings,
                idempotency_key=self.idempotency_key,
            )
        )
        if self.proposal_hash != expected:
            raise FinancialCorrectionError(
                "proposal hash does not match the exact correction payload"
            )

    def payload(self) -> dict[str, object]:
        return _proposal_payload(
            correction_id=self.correction_id,
            affected_ledger_ids=self.affected_ledger_ids,
            postings=self.postings,
            idempotency_key=self.idempotency_key,
        )

    def to_mapping(self) -> dict[str, object]:
        return {**self.payload(), "proposal_hash": self.proposal_hash}


def make_correction_proposal(
    *,
    correction_id: str,
    affected_ledger_ids: Iterable[str],
    postings: Iterable[CompensatingPosting],
    idempotency_key: str,
) -> CorrectionProposal:
    """Validate and hash one complete correction proposal."""

    correction_id = _require_identifier(correction_id, field="correction_id")
    idempotency_key = _require_identifier(
        idempotency_key,
        field="idempotency_key",
    )
    affected_values = _bounded_tuple(
        affected_ledger_ids,
        limit=_MAX_AFFECTED_LEDGER_IDS,
        field="affected_ledger_ids",
    )
    affected = tuple(
        sorted(
            _require_identifier(value, field="affected ledger_id")
            for value in affected_values
        )
    )
    if not affected or len(affected) != len(set(affected)):
        raise FinancialCorrectionError(
            "affected_ledger_ids must be non-empty and duplicate-free"
        )
    posting_values = _bounded_tuple(
        postings,
        limit=_MAX_POSTINGS_PER_PROPOSAL,
        field="postings",
    )
    posting_tuple = tuple(_rebuild_posting(posting) for posting in posting_values)
    if not posting_tuple:
        raise FinancialCorrectionError("postings must be non-empty")
    payload = _proposal_payload(
        correction_id=correction_id,
        affected_ledger_ids=affected,
        postings=posting_tuple,
        idempotency_key=idempotency_key,
    )
    return CorrectionProposal(
        correction_id=correction_id,
        affected_ledger_ids=affected,
        postings=posting_tuple,
        idempotency_key=idempotency_key,
        proposal_hash=_hash_value(payload),
    )


def _rebuild_proposal(proposal: CorrectionProposal) -> CorrectionProposal:
    if type(proposal) is not CorrectionProposal:
        raise FinancialCorrectionError(
            "proposal must use the exact CorrectionProposal type"
        )
    try:
        return CorrectionProposal(
            correction_id=proposal.correction_id,
            affected_ledger_ids=proposal.affected_ledger_ids,
            postings=proposal.postings,
            idempotency_key=proposal.idempotency_key,
            proposal_hash=proposal.proposal_hash,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError("correction proposal is incomplete") from exc


def _approval_payload(
    *,
    authority_kind: str,
    authority_id: str,
    authority_revision_id: str,
    binding_id: str,
    binding_version: int,
    binding_effective_from: datetime,
    binding_effective_until: datetime | None,
    proposal_hash: str,
    confirmed_at: datetime,
) -> dict[str, object]:
    return {
        "authority_id": authority_id,
        "authority_kind": authority_kind,
        "authority_revision_id": authority_revision_id,
        "binding_effective_from": _timestamp(binding_effective_from),
        "binding_effective_until": (
            None
            if binding_effective_until is None
            else _timestamp(binding_effective_until)
        ),
        "binding_id": binding_id,
        "binding_version": binding_version,
        "confirmed_at": _timestamp(confirmed_at),
        "proposal_hash": proposal_hash,
    }


@dataclass(frozen=True)
class CorrectionApproval:
    """Immutable evidence that one configured role approved one proposal hash."""

    authority_kind: str
    authority_id: str
    authority_revision_id: str
    binding_id: str
    binding_version: int
    binding_effective_from: datetime
    binding_effective_until: datetime | None
    proposal_hash: str
    confirmed_at: datetime
    approval_hash: str

    def __post_init__(self) -> None:
        if (
            type(self.authority_kind) is not str
            or self.authority_kind not in _AUTHORITY_KINDS
        ):
            raise FinancialCorrectionError(
                "approval authority_kind must be operator or agent0"
            )
        _require_identifier(self.authority_id, field="approval authority_id")
        _require_identifier(
            self.authority_revision_id,
            field="approval authority_revision_id",
        )
        _require_identifier(self.binding_id, field="approval binding_id")
        if type(self.binding_version) is not int or self.binding_version < 1:
            raise FinancialCorrectionError(
                "approval binding_version must be a positive integer"
            )
        effective_from = _utc(
            self.binding_effective_from,
            field="approval binding_effective_from",
        )
        effective_until = (
            None
            if self.binding_effective_until is None
            else _utc(
                self.binding_effective_until,
                field="approval binding_effective_until",
            )
        )
        confirmed_at = _utc(self.confirmed_at, field="approval confirmed_at")
        if effective_until is not None and effective_until <= effective_from:
            raise FinancialCorrectionError(
                "approval authority interval must be positive"
            )
        if confirmed_at < effective_from or (
            effective_until is not None and confirmed_at >= effective_until
        ):
            raise FinancialCorrectionError(
                "approval was not made inside its authority interval"
            )
        object.__setattr__(self, "binding_effective_from", effective_from)
        object.__setattr__(self, "binding_effective_until", effective_until)
        object.__setattr__(self, "confirmed_at", confirmed_at)
        _require_hash(self.proposal_hash, field="approval proposal_hash")
        _require_hash(self.approval_hash, field="approval_hash")
        expected = _hash_value(
            _approval_payload(
                authority_kind=self.authority_kind,
                authority_id=self.authority_id,
                authority_revision_id=self.authority_revision_id,
                binding_id=self.binding_id,
                binding_version=self.binding_version,
                binding_effective_from=effective_from,
                binding_effective_until=effective_until,
                proposal_hash=self.proposal_hash,
                confirmed_at=confirmed_at,
            )
        )
        if self.approval_hash != expected:
            raise FinancialCorrectionError(
                "approval hash does not match its exact evidence"
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            **_approval_payload(
                authority_kind=self.authority_kind,
                authority_id=self.authority_id,
                authority_revision_id=self.authority_revision_id,
                binding_id=self.binding_id,
                binding_version=self.binding_version,
                binding_effective_from=self.binding_effective_from,
                binding_effective_until=self.binding_effective_until,
                proposal_hash=self.proposal_hash,
                confirmed_at=self.confirmed_at,
            ),
            "approval_hash": self.approval_hash,
        }


def _rebuild_approval(approval: CorrectionApproval) -> CorrectionApproval:
    if type(approval) is not CorrectionApproval:
        raise FinancialCorrectionError(
            "approvals must use the exact CorrectionApproval type"
        )
    try:
        return CorrectionApproval(
            authority_kind=approval.authority_kind,
            authority_id=approval.authority_id,
            authority_revision_id=approval.authority_revision_id,
            binding_id=approval.binding_id,
            binding_version=approval.binding_version,
            binding_effective_from=approval.binding_effective_from,
            binding_effective_until=approval.binding_effective_until,
            proposal_hash=approval.proposal_hash,
            confirmed_at=approval.confirmed_at,
            approval_hash=approval.approval_hash,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError("correction approval is incomplete") from exc


def _row_payload(
    *,
    correction_id: str,
    proposal_hash: str,
    posting_index: int,
    posting: CompensatingPosting,
    effective_at: datetime,
) -> dict[str, object]:
    return {
        "correction_id": correction_id,
        "effective_at": _timestamp(effective_at),
        "posting": posting.to_mapping(),
        "posting_index": posting_index,
        "proposal_hash": proposal_hash,
    }


@dataclass(frozen=True)
class CorrectionLedgerRow:
    """One deterministic append-only row for one compensating posting."""

    row_id: str
    correction_id: str
    proposal_hash: str
    posting_index: int
    posting: CompensatingPosting
    effective_at: datetime
    row_hash: str

    def __post_init__(self) -> None:
        _require_identifier(self.row_id, field="correction row_id")
        _require_identifier(self.correction_id, field="row correction_id")
        _require_hash(self.proposal_hash, field="row proposal_hash")
        if type(self.posting_index) is not int or self.posting_index < 0:
            raise FinancialCorrectionError(
                "posting_index must be a non-negative integer"
            )
        posting = _rebuild_posting(self.posting)
        effective_at = _utc(self.effective_at, field="row effective_at")
        object.__setattr__(self, "posting", posting)
        object.__setattr__(self, "effective_at", effective_at)
        payload = _row_payload(
            correction_id=self.correction_id,
            proposal_hash=self.proposal_hash,
            posting_index=self.posting_index,
            posting=posting,
            effective_at=effective_at,
        )
        digest = _hash_value(payload)
        if self.row_id != f"correction-row:{digest}":
            raise FinancialCorrectionError(
                "correction row_id does not match its exact payload"
            )
        _require_hash(self.row_hash, field="correction row_hash")
        if self.row_hash != _hash_value({**payload, "row_id": self.row_id}):
            raise FinancialCorrectionError(
                "correction row hash does not match its exact payload"
            )

    def to_mapping(self) -> dict[str, object]:
        return {
            **_row_payload(
                correction_id=self.correction_id,
                proposal_hash=self.proposal_hash,
                posting_index=self.posting_index,
                posting=self.posting,
                effective_at=self.effective_at,
            ),
            "row_hash": self.row_hash,
            "row_id": self.row_id,
        }


def _build_rows(
    proposal: CorrectionProposal,
    effective_at: datetime,
) -> tuple[CorrectionLedgerRow, ...]:
    rows: list[CorrectionLedgerRow] = []
    for index, posting in enumerate(proposal.postings):
        payload = _row_payload(
            correction_id=proposal.correction_id,
            proposal_hash=proposal.proposal_hash,
            posting_index=index,
            posting=posting,
            effective_at=effective_at,
        )
        row_id = f"correction-row:{_hash_value(payload)}"
        rows.append(
            CorrectionLedgerRow(
                row_id=row_id,
                correction_id=proposal.correction_id,
                proposal_hash=proposal.proposal_hash,
                posting_index=index,
                posting=posting,
                effective_at=effective_at,
                row_hash=_hash_value({**payload, "row_id": row_id}),
            )
        )
    return tuple(rows)


def _rebuild_row(row: CorrectionLedgerRow) -> CorrectionLedgerRow:
    if type(row) is not CorrectionLedgerRow:
        raise FinancialCorrectionError(
            "correction rows must use the exact CorrectionLedgerRow type"
        )
    try:
        return CorrectionLedgerRow(
            row_id=row.row_id,
            correction_id=row.correction_id,
            proposal_hash=row.proposal_hash,
            posting_index=row.posting_index,
            posting=row.posting,
            effective_at=row.effective_at,
            row_hash=row.row_hash,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError("correction ledger row is incomplete") from exc


def _group_payload(
    *,
    sequence_number: int,
    previous_group_hash: str,
    proposal: CorrectionProposal,
    operator_approval: CorrectionApproval,
    agent0_approval: CorrectionApproval,
    rows: tuple[CorrectionLedgerRow, ...],
    effective_at: datetime,
    pre_state_hash: str,
    post_state_hash: str,
) -> dict[str, object]:
    return {
        "agent0_approval_hash": agent0_approval.approval_hash,
        "effective_at": _timestamp(effective_at),
        "operator_approval_hash": operator_approval.approval_hash,
        "post_state_hash": post_state_hash,
        "pre_state_hash": pre_state_hash,
        "previous_group_hash": previous_group_hash,
        "proposal_hash": proposal.proposal_hash,
        "row_ids": [row.row_id for row in rows],
        "sequence_number": sequence_number,
    }


@dataclass(frozen=True)
class CorrectionGroup:
    """One complete accepted proposal and all append-only correction rows."""

    group_id: str
    sequence_number: int
    previous_group_hash: str
    proposal: CorrectionProposal
    operator_approval: CorrectionApproval
    agent0_approval: CorrectionApproval
    rows: tuple[CorrectionLedgerRow, ...]
    effective_at: datetime
    pre_state_hash: str
    post_state_hash: str
    group_hash: str

    def __post_init__(self) -> None:
        _require_identifier(self.group_id, field="correction group_id")
        _require_nonnegative_integer(
            self.sequence_number,
            field="correction group sequence_number",
        )
        _require_hash(
            self.previous_group_hash,
            field="correction group previous_group_hash",
        )
        proposal = _rebuild_proposal(self.proposal)
        operator_approval = _rebuild_approval(self.operator_approval)
        agent0_approval = _rebuild_approval(self.agent0_approval)
        if operator_approval.authority_kind != "operator":
            raise FinancialCorrectionError(
                "operator_approval must have operator authority"
            )
        if agent0_approval.authority_kind != "agent0":
            raise FinancialCorrectionError(
                "agent0_approval must have Agent0 authority"
            )
        if type(self.rows) is not tuple or not self.rows:
            raise FinancialCorrectionError(
                "correction group rows must be a non-empty tuple"
            )
        rows = tuple(_rebuild_row(row) for row in self.rows)
        effective_at = _utc(self.effective_at, field="group effective_at")
        _require_hash(self.pre_state_hash, field="pre_state_hash")
        _require_hash(self.post_state_hash, field="post_state_hash")
        object.__setattr__(self, "proposal", proposal)
        object.__setattr__(self, "operator_approval", operator_approval)
        object.__setattr__(self, "agent0_approval", agent0_approval)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "effective_at", effective_at)
        payload = _group_payload(
            sequence_number=self.sequence_number,
            previous_group_hash=self.previous_group_hash,
            proposal=proposal,
            operator_approval=operator_approval,
            agent0_approval=agent0_approval,
            rows=rows,
            effective_at=effective_at,
            pre_state_hash=self.pre_state_hash,
            post_state_hash=self.post_state_hash,
        )
        digest = _hash_value(payload)
        if self.group_id != f"correction-group:{digest}":
            raise FinancialCorrectionError(
                "correction group_id does not match its exact payload"
            )
        _require_hash(self.group_hash, field="group_hash")
        if self.group_hash != _hash_value({**payload, "group_id": self.group_id}):
            raise FinancialCorrectionError(
                "correction group hash does not match its exact payload"
            )


def _build_group(
    *,
    sequence_number: int,
    previous_group_hash: str,
    proposal: CorrectionProposal,
    operator_approval: CorrectionApproval,
    agent0_approval: CorrectionApproval,
    rows: tuple[CorrectionLedgerRow, ...],
    effective_at: datetime,
    pre_state_hash: str,
    post_state_hash: str,
) -> CorrectionGroup:
    payload = _group_payload(
        sequence_number=sequence_number,
        previous_group_hash=previous_group_hash,
        proposal=proposal,
        operator_approval=operator_approval,
        agent0_approval=agent0_approval,
        rows=rows,
        effective_at=effective_at,
        pre_state_hash=pre_state_hash,
        post_state_hash=post_state_hash,
    )
    group_id = f"correction-group:{_hash_value(payload)}"
    return CorrectionGroup(
        group_id=group_id,
        sequence_number=sequence_number,
        previous_group_hash=previous_group_hash,
        proposal=proposal,
        operator_approval=operator_approval,
        agent0_approval=agent0_approval,
        rows=rows,
        effective_at=effective_at,
        pre_state_hash=pre_state_hash,
        post_state_hash=post_state_hash,
        group_hash=_hash_value({**payload, "group_id": group_id}),
    )


def _rebuild_group(group: CorrectionGroup) -> CorrectionGroup:
    if type(group) is not CorrectionGroup:
        raise FinancialCorrectionError(
            "groups must use the exact CorrectionGroup type"
        )
    try:
        return CorrectionGroup(
            group_id=group.group_id,
            sequence_number=group.sequence_number,
            previous_group_hash=group.previous_group_hash,
            proposal=group.proposal,
            operator_approval=group.operator_approval,
            agent0_approval=group.agent0_approval,
            rows=group.rows,
            effective_at=group.effective_at,
            pre_state_hash=group.pre_state_hash,
            post_state_hash=group.post_state_hash,
            group_hash=group.group_hash,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError("correction group is incomplete") from exc


@dataclass(frozen=True)
class CorrectionIdempotencyRecord:
    """Exact mapping from one proposal request to one accepted group."""

    key: str
    proposal_hash: str
    group_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.key, field="correction idempotency key")
        _require_hash(self.proposal_hash, field="idempotency proposal_hash")
        _require_identifier(self.group_id, field="idempotency group_id")


def _rebuild_idempotency(
    record: CorrectionIdempotencyRecord,
) -> CorrectionIdempotencyRecord:
    if type(record) is not CorrectionIdempotencyRecord:
        raise FinancialCorrectionError(
            "idempotency records must use the exact correction record type"
        )
    try:
        return CorrectionIdempotencyRecord(
            key=record.key,
            proposal_hash=record.proposal_hash,
            group_id=record.group_id,
        )
    except AttributeError as exc:
        raise FinancialCorrectionError(
            "correction idempotency record is incomplete"
        ) from exc


@dataclass(frozen=True)
class _ReplayResult:
    positions: tuple[MoneyPosition, ...]
    total_minted: int
    correction_rows: tuple[CorrectionLedgerRow, ...]
    idempotency_records: tuple[CorrectionIdempotencyRecord, ...]


def _financial_hash(
    *,
    opening_supply: int,
    positions: tuple[MoneyPosition, ...],
    total_minted: int,
) -> str:
    return _hash_value(
        {
            "opening_supply": opening_supply,
            "positions": [position.to_mapping() for position in positions],
            "total_minted": total_minted,
        }
    )


def _check_invariant(
    *,
    opening_supply: int,
    positions: tuple[MoneyPosition, ...],
    total_minted: int,
    boundary: str,
) -> None:
    resulting_supply = opening_supply + total_minted
    if resulting_supply < 0:
        raise FinancialCorrectionError(
            f"{boundary} resulting supply must be non-negative"
        )
    if sum(position.amount for position in positions) != resulting_supply:
        raise FinancialCorrectionError(
            f"{boundary} financial invariant does not hold"
        )


def _resolve_approvals(
    *,
    authority_bindings: tuple[VerifiedCorrectionAuthority, ...],
    proposal: CorrectionProposal,
    approvals: tuple[CorrectionApproval, ...],
    effective_at: datetime,
) -> tuple[CorrectionApproval, CorrectionApproval]:
    if len(approvals) != 2:
        raise FinancialCorrectionError(
            "correction requires exactly one operator and one Agent0 approval"
        )
    by_kind = {approval.authority_kind: approval for approval in approvals}
    if set(by_kind) != _AUTHORITY_KINDS or len(by_kind) != 2:
        raise FinancialCorrectionError(
            "correction requires exactly one operator and one Agent0 approval"
        )
    operator = by_kind["operator"]
    agent0 = by_kind["agent0"]
    for approval in (operator, agent0):
        if approval.proposal_hash != proposal.proposal_hash:
            raise FinancialCorrectionError(
                "approval proposal hash does not match the correction"
            )
        if effective_at < approval.confirmed_at:
            raise FinancialCorrectionError(
                "correction effective_at cannot precede confirmation"
            )
        matches = [
            binding
            for binding in authority_bindings
            if binding.authority_kind == approval.authority_kind
            and binding.authority_id == approval.authority_id
            and binding.authority_revision_id == approval.authority_revision_id
            and binding.binding_id == approval.binding_id
            and binding.binding_version == approval.binding_version
            and binding.effective_from == approval.binding_effective_from
            and binding.effective_until == approval.binding_effective_until
            and binding.active_at(approval.confirmed_at)
        ]
        if len(matches) != 1:
            raise FinancialCorrectionError(
                "approval must resolve to one configured active authority binding"
            )
    if (
        operator.authority_id == agent0.authority_id
        or operator.authority_revision_id == agent0.authority_revision_id
    ):
        raise FinancialCorrectionError(
            "operator and Agent0 approval sources must be independent"
        )
    return operator, agent0


def _apply_postings(
    *,
    opening_supply: int,
    positions: tuple[MoneyPosition, ...],
    total_minted: int,
    postings: tuple[CompensatingPosting, ...],
) -> tuple[tuple[MoneyPosition, ...], int]:
    transfer_delta = sum(
        posting.delta for posting in postings if posting.kind == "transfer"
    )
    if transfer_delta != 0:
        raise FinancialCorrectionError("transfer postings must net to zero")
    amounts = {position.position_id: position.amount for position in positions}
    position_kinds = {
        position.position_id: position.kind for position in positions
    }
    for posting in postings:
        if posting.position_id not in amounts:
            raise FinancialCorrectionError(
                f"unknown financial position: {posting.position_id}"
            )
        amounts[posting.position_id] += posting.delta
    if any(amount < 0 for amount in amounts.values()):
        raise FinancialCorrectionError("correction would create a negative position")
    minted_delta = sum(
        posting.delta for posting in postings if posting.kind in {"mint", "burn"}
    )
    resulting_minted = total_minted + minted_delta
    resulting = tuple(
        MoneyPosition(position_id, position_kinds[position_id], amounts[position_id])
        for position_id in sorted(amounts)
    )
    _check_invariant(
        opening_supply=opening_supply,
        positions=resulting,
        total_minted=resulting_minted,
        boundary="post-correction",
    )
    return resulting, resulting_minted


def _replay_groups(
    *,
    opening_supply: int,
    opening_total_minted: int,
    opening_snapshot_hash: str,
    opening_positions: tuple[MoneyPosition, ...],
    published_rows: tuple[PublishedLedgerRow, ...],
    authority_bindings: tuple[VerifiedCorrectionAuthority, ...],
    groups: tuple[CorrectionGroup, ...],
) -> _ReplayResult:
    positions = opening_positions
    total_minted = opening_total_minted
    known_row_ids = {row.ledger_id for row in published_rows}
    correction_rows: list[CorrectionLedgerRow] = []
    idempotency: list[CorrectionIdempotencyRecord] = []
    correction_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    group_ids: set[str] = set()
    previous_group_hash = opening_snapshot_hash
    _check_invariant(
        opening_supply=opening_supply,
        positions=positions,
        total_minted=total_minted,
        boundary="opening",
    )
    for sequence_number, group in enumerate(groups):
        proposal = group.proposal
        if proposal.correction_id in correction_ids:
            raise FinancialCorrectionError("state contains duplicate correction ID")
        if proposal.idempotency_key in idempotency_keys:
            raise FinancialCorrectionError(
                "state contains duplicate correction idempotency key"
            )
        if group.group_id in group_ids:
            raise FinancialCorrectionError(
                "state contains duplicate correction group_id"
            )
        unknown = sorted(set(proposal.affected_ledger_ids) - known_row_ids)
        if unknown:
            raise FinancialCorrectionError(
                f"unknown affected ledger ID: {unknown[0]}"
            )
        operator, agent0 = _resolve_approvals(
            authority_bindings=authority_bindings,
            proposal=proposal,
            approvals=(group.operator_approval, group.agent0_approval),
            effective_at=group.effective_at,
        )
        pre_hash = _financial_hash(
            opening_supply=opening_supply,
            positions=positions,
            total_minted=total_minted,
        )
        updated_positions, updated_total_minted = _apply_postings(
            opening_supply=opening_supply,
            positions=positions,
            total_minted=total_minted,
            postings=proposal.postings,
        )
        post_hash = _financial_hash(
            opening_supply=opening_supply,
            positions=updated_positions,
            total_minted=updated_total_minted,
        )
        expected_rows = _build_rows(proposal, group.effective_at)
        if any(row.row_id in known_row_ids for row in expected_rows):
            raise FinancialCorrectionError("correction row identity collides")
        expected_group = _build_group(
            sequence_number=sequence_number,
            previous_group_hash=previous_group_hash,
            proposal=proposal,
            operator_approval=operator,
            agent0_approval=agent0,
            rows=expected_rows,
            effective_at=group.effective_at,
            pre_state_hash=pre_hash,
            post_state_hash=post_hash,
        )
        if group != expected_group:
            raise FinancialCorrectionError(
                "correction group does not match deterministic replay"
            )
        correction_ids.add(proposal.correction_id)
        idempotency_keys.add(proposal.idempotency_key)
        group_ids.add(group.group_id)
        known_row_ids.update(row.row_id for row in expected_rows)
        correction_rows.extend(expected_rows)
        idempotency.append(
            CorrectionIdempotencyRecord(
                key=proposal.idempotency_key,
                proposal_hash=proposal.proposal_hash,
                group_id=group.group_id,
            )
        )
        positions = updated_positions
        total_minted = updated_total_minted
        previous_group_hash = expected_group.group_hash
    return _ReplayResult(
        positions=positions,
        total_minted=total_minted,
        correction_rows=tuple(correction_rows),
        idempotency_records=tuple(idempotency),
    )


@dataclass(frozen=True)
class FinancialCorrectionState:
    """Self-validating immutable opening evidence and accepted correction groups."""

    opening_supply: int
    opening_total_minted: int
    opening_snapshot_hash: str
    opening_positions: tuple[MoneyPosition, ...]
    published_rows: tuple[PublishedLedgerRow, ...]
    authority_bindings: tuple[VerifiedCorrectionAuthority, ...]
    groups: tuple[CorrectionGroup, ...] = ()
    idempotency_records: tuple[CorrectionIdempotencyRecord, ...] = ()
    _replay_result: _ReplayResult = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        opening_supply = _require_nonnegative_integer(
            self.opening_supply,
            field="opening_supply",
        )
        opening_total_minted = _require_integer(
            self.opening_total_minted,
            field="opening_total_minted",
        )
        if type(self.opening_positions) is not tuple or not self.opening_positions:
            raise FinancialCorrectionError(
                "opening_positions must be a non-empty immutable tuple"
            )
        if len(self.opening_positions) > _MAX_OPENING_POSITIONS:
            raise FinancialCorrectionError("opening_positions exceed the state limit")
        positions = tuple(
            _rebuild_position(position) for position in self.opening_positions
        )
        if tuple(position.position_id for position in positions) != tuple(
            sorted(position.position_id for position in positions)
        ):
            raise FinancialCorrectionError(
                "opening_positions must use canonical position_id order"
            )
        _require_unique(
            (position.position_id for position in positions),
            field="position_id",
        )
        if type(self.published_rows) is not tuple or not self.published_rows:
            raise FinancialCorrectionError(
                "published_rows must be a non-empty immutable tuple"
            )
        if len(self.published_rows) > _MAX_PUBLISHED_ROWS:
            raise FinancialCorrectionError("published_rows exceed the state limit")
        published_rows = _rebuild_published_rows(self.published_rows)
        _require_unique(
            (row.ledger_id for row in published_rows),
            field="published ledger_id",
        )
        if type(self.authority_bindings) is not tuple:
            raise FinancialCorrectionError(
                "authority_bindings must be an immutable tuple"
            )
        if len(self.authority_bindings) > _MAX_AUTHORITY_BINDINGS:
            raise FinancialCorrectionError(
                "authority_bindings exceed the state limit"
            )
        authorities = tuple(
            _rebuild_authority(authority) for authority in self.authority_bindings
        )
        if authorities != tuple(sorted(authorities, key=_authority_sort_key)):
            raise FinancialCorrectionError(
                "authority_bindings must use canonical authority order"
            )
        _require_unique(
            (
                (authority.binding_id, authority.binding_version)
                for authority in authorities
            ),
            field="authority binding identity and version",
        )
        opening_snapshot_hash = _require_hash(
            self.opening_snapshot_hash,
            field="opening_snapshot_hash",
        )
        expected_opening_snapshot_hash = _opening_snapshot_hash(
            opening_supply=opening_supply,
            opening_total_minted=opening_total_minted,
            opening_positions=positions,
            published_rows=published_rows,
            authority_bindings=authorities,
        )
        if opening_snapshot_hash != expected_opening_snapshot_hash:
            raise FinancialCorrectionError(
                "opening snapshot hash does not match exact opening evidence"
            )
        if type(self.groups) is not tuple:
            raise FinancialCorrectionError("groups must be an immutable tuple")
        if len(self.groups) > _MAX_CORRECTION_GROUPS:
            raise FinancialCorrectionError("groups exceed the correction history limit")
        groups = tuple(_rebuild_group(group) for group in self.groups)
        if type(self.idempotency_records) is not tuple:
            raise FinancialCorrectionError(
                "idempotency_records must be an immutable tuple"
            )
        if len(self.idempotency_records) > _MAX_CORRECTION_GROUPS:
            raise FinancialCorrectionError(
                "idempotency_records exceed the correction history limit"
            )
        idempotency = tuple(
            _rebuild_idempotency(record)
            for record in self.idempotency_records
        )
        object.__setattr__(self, "opening_positions", positions)
        object.__setattr__(self, "published_rows", published_rows)
        object.__setattr__(self, "authority_bindings", authorities)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "idempotency_records", idempotency)
        replay = _replay_groups(
            opening_supply=opening_supply,
            opening_total_minted=opening_total_minted,
            opening_snapshot_hash=opening_snapshot_hash,
            opening_positions=positions,
            published_rows=published_rows,
            authority_bindings=authorities,
            groups=groups,
        )
        if idempotency != replay.idempotency_records:
            raise FinancialCorrectionError(
                "state idempotency records do not match correction history"
            )
        object.__setattr__(self, "_replay_result", replay)

    def _replay(self) -> _ReplayResult:
        return self._replay_result

    @property
    def positions(self) -> tuple[MoneyPosition, ...]:
        return self._replay().positions

    @property
    def total_minted(self) -> int:
        return self._replay().total_minted

    @property
    def correction_rows(self) -> tuple[CorrectionLedgerRow, ...]:
        return self._replay().correction_rows

    @property
    def ledger_rows(
        self,
    ) -> tuple[PublishedLedgerRow | CorrectionLedgerRow, ...]:
        return (*self.published_rows, *self.correction_rows)


def initial_financial_correction_state(
    *,
    opening_supply: int,
    opening_positions: Iterable[MoneyPosition],
    published_rows: Iterable[PublishedLedgerRow],
    authority_bindings: Iterable[VerifiedCorrectionAuthority],
    opening_total_minted: int = 0,
) -> FinancialCorrectionState:
    """Build one validated inactive correction state from explicit evidence."""

    try:
        position_values = _bounded_tuple(
            opening_positions,
            limit=_MAX_OPENING_POSITIONS,
            field="opening_positions",
        )
        positions = tuple(
            sorted(
                (_rebuild_position(item) for item in position_values),
                key=lambda item: item.position_id,
            )
        )
        row_values = _bounded_tuple(
            published_rows,
            limit=_MAX_PUBLISHED_ROWS,
            field="published_rows",
        )
        rows = _rebuild_published_rows(row_values)
        authority_values = _bounded_tuple(
            authority_bindings,
            limit=_MAX_AUTHORITY_BINDINGS,
            field="authority_bindings",
        )
        authorities = tuple(
            sorted(
                (_rebuild_authority(item) for item in authority_values),
                key=_authority_sort_key,
            )
        )
        snapshot_hash = _opening_snapshot_hash(
            opening_supply=opening_supply,
            opening_total_minted=opening_total_minted,
            opening_positions=positions,
            published_rows=rows,
            authority_bindings=authorities,
        )
        return FinancialCorrectionState(
            opening_supply=opening_supply,
            opening_total_minted=opening_total_minted,
            opening_snapshot_hash=snapshot_hash,
            opening_positions=positions,
            published_rows=rows,
            authority_bindings=authorities,
        )
    except (AttributeError, TypeError) as exc:
        raise FinancialCorrectionError(
            "opening correction evidence is incomplete"
        ) from exc


def _require_state(state: FinancialCorrectionState) -> FinancialCorrectionState:
    if type(state) is not FinancialCorrectionState:
        raise FinancialCorrectionError(
            "state must use the exact FinancialCorrectionState type"
        )
    try:
        return FinancialCorrectionState(
            opening_supply=state.opening_supply,
            opening_total_minted=state.opening_total_minted,
            opening_snapshot_hash=state.opening_snapshot_hash,
            opening_positions=state.opening_positions,
            published_rows=state.published_rows,
            authority_bindings=state.authority_bindings,
            groups=state.groups,
            idempotency_records=state.idempotency_records,
        )
    except (AttributeError, TypeError) as exc:
        raise FinancialCorrectionError(
            "financial correction state is incomplete"
        ) from exc


def confirm_correction(
    state: FinancialCorrectionState,
    *,
    proposal: CorrectionProposal,
    authority_kind: str,
    authority_id: str,
    authority_revision_id: str,
    confirmed_at: datetime,
) -> CorrectionApproval:
    """Snapshot one exact configured authority confirmation."""

    state = _require_state(state)
    proposal = _rebuild_proposal(proposal)
    if type(authority_kind) is not str or authority_kind not in _AUTHORITY_KINDS:
        raise FinancialCorrectionError(
            "authority_kind must be operator or agent0"
        )
    authority_id = _require_identifier(authority_id, field="authority_id")
    authority_revision_id = _require_identifier(
        authority_revision_id,
        field="authority_revision_id",
    )
    at = _utc(confirmed_at, field="confirmed_at")
    matches = [
        authority
        for authority in state.authority_bindings
        if authority.authority_kind == authority_kind
        and authority.authority_id == authority_id
        and authority.authority_revision_id == authority_revision_id
        and authority.active_at(at)
    ]
    if len(matches) != 1:
        raise FinancialCorrectionError(
            "authority must resolve to one configured active binding"
        )
    authority = matches[0]
    payload = _approval_payload(
        authority_kind=authority.authority_kind,
        authority_id=authority.authority_id,
        authority_revision_id=authority.authority_revision_id,
        binding_id=authority.binding_id,
        binding_version=authority.binding_version,
        binding_effective_from=authority.effective_from,
        binding_effective_until=authority.effective_until,
        proposal_hash=proposal.proposal_hash,
        confirmed_at=at,
    )
    return CorrectionApproval(
        authority_kind=authority.authority_kind,
        authority_id=authority.authority_id,
        authority_revision_id=authority.authority_revision_id,
        binding_id=authority.binding_id,
        binding_version=authority.binding_version,
        binding_effective_from=authority.effective_from,
        binding_effective_until=authority.effective_until,
        proposal_hash=proposal.proposal_hash,
        confirmed_at=at,
        approval_hash=_hash_value(payload),
    )


def _existing_group_by_id(
    state: FinancialCorrectionState,
    group_id: str,
) -> CorrectionGroup:
    for group in state.groups:
        if group.group_id == group_id:
            return group
    raise FinancialCorrectionError(
        "idempotency record refers to an unknown correction group"
    )


def apply_financial_correction(
    state: FinancialCorrectionState,
    *,
    proposal: CorrectionProposal,
    approvals: Iterable[CorrectionApproval],
    effective_at: datetime,
) -> tuple[FinancialCorrectionState, CorrectionGroup]:
    """Atomically append one approved correction group or reject unchanged."""

    state = _require_state(state)
    proposal = _rebuild_proposal(proposal)
    approval_values = _bounded_tuple(
        approvals,
        limit=2,
        field="approvals",
    )
    approval_tuple = tuple(
        _rebuild_approval(value) for value in approval_values
    )
    at = _utc(effective_at, field="effective_at")
    operator, agent0 = _resolve_approvals(
        authority_bindings=state.authority_bindings,
        proposal=proposal,
        approvals=approval_tuple,
        effective_at=at,
    )
    for record in state.idempotency_records:
        if record.key != proposal.idempotency_key:
            continue
        existing = _existing_group_by_id(state, record.group_id)
        if (
            record.proposal_hash == proposal.proposal_hash
            and existing.proposal == proposal
            and existing.operator_approval == operator
            and existing.agent0_approval == agent0
            and existing.effective_at == at
        ):
            return state, existing
        raise FinancialCorrectionError(
            "correction idempotency key was reused with different input"
        )
    for existing in state.groups:
        if existing.proposal.correction_id == proposal.correction_id:
            raise FinancialCorrectionError(
                "correction ID was reused with different input"
            )
    if len(state.groups) >= _MAX_CORRECTION_GROUPS:
        raise FinancialCorrectionError(
            "correction history reached its checkpoint limit"
        )
    known_row_ids = {row.ledger_id for row in state.published_rows} | {
        row.row_id for row in state.correction_rows
    }
    unknown = sorted(set(proposal.affected_ledger_ids) - known_row_ids)
    if unknown:
        raise FinancialCorrectionError(
            f"unknown affected ledger ID: {unknown[0]}"
        )
    positions = state.positions
    total_minted = state.total_minted
    _check_invariant(
        opening_supply=state.opening_supply,
        positions=positions,
        total_minted=total_minted,
        boundary="pre-correction",
    )
    pre_hash = _financial_hash(
        opening_supply=state.opening_supply,
        positions=positions,
        total_minted=total_minted,
    )
    updated_positions, updated_total_minted = _apply_postings(
        opening_supply=state.opening_supply,
        positions=positions,
        total_minted=total_minted,
        postings=proposal.postings,
    )
    post_hash = _financial_hash(
        opening_supply=state.opening_supply,
        positions=updated_positions,
        total_minted=updated_total_minted,
    )
    rows = _build_rows(proposal, at)
    if any(row.row_id in known_row_ids for row in rows):
        raise FinancialCorrectionError("correction row identity collides")
    group = _build_group(
        sequence_number=len(state.groups),
        previous_group_hash=(
            state.groups[-1].group_hash
            if state.groups
            else state.opening_snapshot_hash
        ),
        proposal=proposal,
        operator_approval=operator,
        agent0_approval=agent0,
        rows=rows,
        effective_at=at,
        pre_state_hash=pre_hash,
        post_state_hash=post_hash,
    )
    record = CorrectionIdempotencyRecord(
        key=proposal.idempotency_key,
        proposal_hash=proposal.proposal_hash,
        group_id=group.group_id,
    )
    updated = FinancialCorrectionState(
        opening_supply=state.opening_supply,
        opening_total_minted=state.opening_total_minted,
        opening_snapshot_hash=state.opening_snapshot_hash,
        opening_positions=state.opening_positions,
        published_rows=state.published_rows,
        authority_bindings=state.authority_bindings,
        groups=(*state.groups, group),
        idempotency_records=(*state.idempotency_records, record),
    )
    return updated, group


__all__ = [
    "CompensatingPosting",
    "CorrectionApproval",
    "CorrectionGroup",
    "CorrectionIdempotencyRecord",
    "CorrectionLedgerRow",
    "CorrectionProposal",
    "FinancialCorrectionError",
    "FinancialCorrectionState",
    "MoneyPosition",
    "PublishedLedgerRow",
    "VerifiedCorrectionAuthority",
    "apply_financial_correction",
    "confirm_correction",
    "initial_financial_correction_state",
    "make_correction_proposal",
    "make_published_ledger_row",
]
