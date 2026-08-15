"""Offline Domain registry validation and fixed-duration Access state.

This control-plane module is outside every immutable vNext executor closure. It
does not call GitHub, grant repository permissions, create Work, or touch money.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ACCESS_DURATION = timedelta(days=7)

_DOMAIN_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_HASH = re.compile(r"[0-9a-f]{64}")
_REPOSITORY_ID = re.compile(r"[A-Za-z0-9_=-]{1,128}")
_REPOSITORY_LOCATOR = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
)
_REVISION = re.compile(r"[0-9a-f]{40}")
_ALLOWED_AUTHORITIES = frozenset({"agent0", "operator"})
_RECORD_KEYS = frozenset(
    {
        "domain_id",
        "record_hash",
        "repository_id",
        "repository_locator",
        "revision",
    }
)
_REGISTRY_KEYS = frozenset({"records", "registry_hash", "schema_version"})
_MAX_REGISTRY_BYTES = 1024 * 1024
_MAX_RECORDS = 10_000


class DomainRegistryError(ValueError):
    """The Domain registry is not canonical, complete, or internally valid."""


class AccessError(ValueError):
    """An Access transition violates the accepted control-plane contract."""


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
        raise DomainRegistryError("value is not canonicalizable JSON") from exc


def _hash_value(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_string(value: object, *, field: str, error: type[ValueError]) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise error(f"{field} must be a non-empty bounded string")
    return value


def _record_payload(
    *,
    domain_id: str,
    repository_id: str,
    repository_locator: str,
    revision: str,
) -> dict[str, str]:
    return {
        "domain_id": domain_id,
        "repository_id": repository_id,
        "repository_locator": repository_locator,
        "revision": revision,
    }


@dataclass(frozen=True)
class DomainRecord:
    """One immutable Domain binding to a permanent repository and revision."""

    domain_id: str
    repository_id: str
    repository_locator: str
    revision: str
    record_hash: str

    def __post_init__(self) -> None:
        _validate_domain_id(self.domain_id)
        _validate_repository_id(self.repository_id)
        _validate_repository_locator(self.repository_locator)
        _validate_revision(self.revision)
        if not isinstance(self.record_hash, str) or not _HASH.fullmatch(
            self.record_hash
        ):
            raise DomainRegistryError("record_hash must be a lowercase SHA-256")
        expected = _hash_value(self.payload())
        if self.record_hash != expected:
            raise DomainRegistryError("record hash does not match the Domain record")

    def payload(self) -> dict[str, str]:
        return _record_payload(
            domain_id=self.domain_id,
            repository_id=self.repository_id,
            repository_locator=self.repository_locator,
            revision=self.revision,
        )

    def to_mapping(self) -> dict[str, str]:
        return {**self.payload(), "record_hash": self.record_hash}


def _validate_domain_id(value: object) -> str:
    value = _require_string(value, field="domain_id", error=DomainRegistryError)
    if not _DOMAIN_ID.fullmatch(value):
        raise DomainRegistryError("domain_id must be a canonical lowercase slug")
    return value


def _validate_repository_id(value: object) -> str:
    value = _require_string(
        value,
        field="repository_id",
        error=DomainRegistryError,
    )
    if not _REPOSITORY_ID.fullmatch(value):
        raise DomainRegistryError("repository_id must be a permanent repository ID")
    return value


def _validate_repository_locator(value: object) -> str:
    value = _require_string(
        value,
        field="repository_locator",
        error=DomainRegistryError,
    )
    if not _REPOSITORY_LOCATOR.fullmatch(value):
        raise DomainRegistryError(
            "repository locator must be a canonical GitHub HTTPS URL"
        )
    return value


def _validate_revision(value: object) -> str:
    value = _require_string(value, field="revision", error=DomainRegistryError)
    if not _REVISION.fullmatch(value):
        raise DomainRegistryError("revision must be a full lowercase Git commit SHA")
    return value


def make_domain_record(
    *,
    domain_id: str,
    repository_id: str,
    repository_locator: str,
    revision: str,
) -> DomainRecord:
    """Build a Domain record and bind its identity fields with a content hash."""

    payload = _record_payload(
        domain_id=_validate_domain_id(domain_id),
        repository_id=_validate_repository_id(repository_id),
        repository_locator=_validate_repository_locator(repository_locator),
        revision=_validate_revision(revision),
    )
    return DomainRecord(**payload, record_hash=_hash_value(payload))


def _registry_payload(
    schema_version: int,
    records: Iterable[DomainRecord],
) -> dict[str, object]:
    return {
        "records": [record.to_mapping() for record in records],
        "schema_version": schema_version,
    }


@dataclass(frozen=True)
class DomainRegistry:
    """A validated immutable registry manifest."""

    schema_version: int
    records: tuple[DomainRecord, ...]
    registry_hash: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise DomainRegistryError("schema_version must be the integer 1")
        if not isinstance(self.records, tuple) or not self.records:
            raise DomainRegistryError(
                "registry must contain at least one Domain record"
            )
        if len(self.records) > _MAX_RECORDS:
            raise DomainRegistryError("registry contains too many Domain records")
        if any(not isinstance(record, DomainRecord) for record in self.records):
            raise DomainRegistryError("registry records must be DomainRecord values")
        if tuple(sorted(self.records, key=lambda item: item.domain_id)) != self.records:
            raise DomainRegistryError("registry records must be sorted by domain_id")
        _require_unique(
            (record.domain_id for record in self.records),
            field="domain_id",
        )
        _require_unique(
            (record.repository_id for record in self.records),
            field="repository_id",
        )
        if not isinstance(self.registry_hash, str) or not _HASH.fullmatch(
            self.registry_hash
        ):
            raise DomainRegistryError("registry_hash must be a lowercase SHA-256")
        expected = _hash_value(_registry_payload(self.schema_version, self.records))
        if self.registry_hash != expected:
            raise DomainRegistryError("registry hash does not match the manifest")

    def domain(self, domain_id: str) -> DomainRecord:
        for record in self.records:
            if record.domain_id == domain_id:
                return record
        raise AccessError(f"Domain is not present in this registry: {domain_id}")

    def to_mapping(self) -> dict[str, object]:
        return {
            **_registry_payload(self.schema_version, self.records),
            "registry_hash": self.registry_hash,
        }


def _require_unique(values: Iterable[str], *, field: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise DomainRegistryError(f"registry contains duplicate {field}: {value}")
        seen.add(value)


def build_domain_registry(records: Iterable[DomainRecord]) -> DomainRegistry:
    """Build a sorted registry and bind its full record set with a hash."""

    ordered = tuple(sorted(records, key=lambda item: item.domain_id))
    payload = _registry_payload(1, ordered)
    return DomainRegistry(
        schema_version=1,
        records=ordered,
        registry_hash=_hash_value(payload),
    )


def serialize_domain_registry(registry: DomainRegistry) -> bytes:
    """Return the exact canonical bytes for a validated registry."""

    if not isinstance(registry, DomainRegistry):
        raise DomainRegistryError("registry must be a DomainRegistry value")
    return _canonical_bytes(registry.to_mapping())


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DomainRegistryError(f"registry contains duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(_value: str) -> object:
    raise DomainRegistryError("registry contains a non-integer JSON number")


def _load_json(raw: bytes, *, source: str) -> Mapping[str, object]:
    if len(raw) > _MAX_REGISTRY_BYTES:
        raise DomainRegistryError(f"{source} exceeds the registry size limit")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise DomainRegistryError(f"{source} contains a UTF-8 BOM")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except DomainRegistryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise DomainRegistryError(f"{source} is not strict JSON") from exc
    if not isinstance(value, dict):
        raise DomainRegistryError(f"{source} must contain one JSON object")
    if _canonical_bytes(value) != raw:
        raise DomainRegistryError(f"{source} must use exact canonical JSON bytes")
    return value


def _exact_keys(
    value: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DomainRegistryError(
            f"{label} keys do not match the schema; missing={missing}, extra={extra}"
        )


def load_domain_registry_bytes(
    raw: bytes,
    *,
    source: str = "<registry-bytes>",
) -> DomainRegistry:
    """Validate canonical manifest bytes without any network or mutable lookup."""

    value = _load_json(raw, source=source)
    _exact_keys(value, _REGISTRY_KEYS, "registry")
    schema_version = value["schema_version"]
    if type(schema_version) is not int:
        raise DomainRegistryError("schema_version must be an integer")
    raw_records = value["records"]
    if not isinstance(raw_records, list):
        raise DomainRegistryError("records must be a JSON array")
    records: list[DomainRecord] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict):
            raise DomainRegistryError(f"record {index} must be a JSON object")
        _exact_keys(raw_record, _RECORD_KEYS, f"record {index}")
        records.append(
            DomainRecord(
                domain_id=_validate_domain_id(raw_record["domain_id"]),
                repository_id=_validate_repository_id(
                    raw_record["repository_id"]
                ),
                repository_locator=_validate_repository_locator(
                    raw_record["repository_locator"]
                ),
                revision=_validate_revision(raw_record["revision"]),
                record_hash=_require_string(
                    raw_record["record_hash"],
                    field="record_hash",
                    error=DomainRegistryError,
                ),
            )
        )
    registry_hash = value["registry_hash"]
    if not isinstance(registry_hash, str):
        raise DomainRegistryError("registry_hash must be a string")
    return DomainRegistry(
        schema_version=schema_version,
        records=tuple(records),
        registry_hash=registry_hash,
    )


def load_domain_registry(path: Path) -> DomainRegistry:
    """Load one explicit local registry file."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DomainRegistryError(f"cannot read Domain registry: {path}") from exc
    return load_domain_registry_bytes(raw, source=str(path))


def _access_string(value: object, *, field: str) -> str:
    return _require_string(value, field=field, error=AccessError)


def _access_domain_id(value: object) -> str:
    value = _access_string(value, field="domain_id")
    if not _DOMAIN_ID.fullmatch(value):
        raise AccessError("domain_id must be a canonical lowercase slug")
    return value


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AccessError(f"{field} must be a timezone-aware datetime")
    try:
        return value.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise AccessError(f"{field} cannot be normalized to UTC") from exc


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _access_payload(
    *,
    authority_kind: str,
    authority_id: str,
    authority_revision_id: str,
    agent_id: str,
    domain_id: str,
    registry_hash: str,
    starts_at: datetime,
    ends_at: datetime,
) -> dict[str, str]:
    return {
        "agent_id": agent_id,
        "authority_id": authority_id,
        "authority_kind": authority_kind,
        "authority_revision_id": authority_revision_id,
        "domain_id": domain_id,
        "ends_at": _timestamp(ends_at),
        "registry_hash": registry_hash,
        "starts_at": _timestamp(starts_at),
    }


@dataclass(frozen=True)
class AccessGrant:
    access_id: str
    authority_kind: str
    authority_id: str
    authority_revision_id: str
    agent_id: str
    domain_id: str
    registry_hash: str
    starts_at: datetime
    ends_at: datetime

    def __post_init__(self) -> None:
        authority_kind = _access_string(
            self.authority_kind,
            field="authority_kind",
        )
        if authority_kind not in _ALLOWED_AUTHORITIES:
            raise AccessError("authority_kind must be operator or agent0")
        _access_string(self.authority_id, field="authority_id")
        _access_string(self.authority_revision_id, field="authority_revision_id")
        _access_string(self.agent_id, field="agent_id")
        _access_domain_id(self.domain_id)
        if not isinstance(self.registry_hash, str) or not _HASH.fullmatch(
            self.registry_hash
        ):
            raise AccessError("registry_hash must be a lowercase SHA-256")
        starts_at = _utc(self.starts_at, field="starts_at")
        ends_at = _utc(self.ends_at, field="ends_at")
        object.__setattr__(self, "starts_at", starts_at)
        object.__setattr__(self, "ends_at", ends_at)
        if ends_at - starts_at != ACCESS_DURATION:
            raise AccessError("Access interval must be exactly seven days")
        payload = _access_payload(
            authority_kind=self.authority_kind,
            authority_id=self.authority_id,
            authority_revision_id=self.authority_revision_id,
            agent_id=self.agent_id,
            domain_id=self.domain_id,
            registry_hash=self.registry_hash,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        if self.access_id != f"access:{_hash_value(payload)}":
            raise AccessError("access_id does not match the canonical grant")


@dataclass(frozen=True)
class AccessExpiry:
    expiry_id: str
    access_id: str
    effective_at: datetime

    def __post_init__(self) -> None:
        _access_string(self.access_id, field="access_id")
        effective_at = _utc(self.effective_at, field="effective_at")
        object.__setattr__(self, "effective_at", effective_at)
        payload = {
            "access_id": self.access_id,
            "effective_at": _timestamp(effective_at),
        }
        if self.expiry_id != f"access-expiry:{_hash_value(payload)}":
            raise AccessError("expiry_id does not match the canonical expiry")


@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    operation: str
    request_hash: str
    object_id: str

    def __post_init__(self) -> None:
        _access_string(self.key, field="idempotency key")
        if self.operation not in {"grant_access", "expire_access"}:
            raise AccessError("idempotency operation is not supported")
        if not _HASH.fullmatch(self.request_hash):
            raise AccessError("idempotency request_hash must be a SHA-256")
        _access_string(self.object_id, field="idempotency object_id")


@dataclass(frozen=True)
class DomainAccessState:
    registry: DomainRegistry
    grants: tuple[AccessGrant, ...] = ()
    expiries: tuple[AccessExpiry, ...] = ()
    idempotency_records: tuple[IdempotencyRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.registry, DomainRegistry):
            raise AccessError("state registry must be a DomainRegistry")
        for field, values, expected_type in (
            ("grants", self.grants, AccessGrant),
            ("expiries", self.expiries, AccessExpiry),
            ("idempotency_records", self.idempotency_records, IdempotencyRecord),
        ):
            if not isinstance(values, tuple) or any(
                not isinstance(value, expected_type) for value in values
            ):
                raise AccessError(f"state {field} must be an immutable typed tuple")
        _access_unique(
            (grant.access_id for grant in self.grants),
            label="access_id",
        )
        _access_unique(
            (expiry.expiry_id for expiry in self.expiries),
            label="expiry_id",
        )
        _access_unique(
            (record.key for record in self.idempotency_records),
            label="idempotency key",
        )
        known_domains = {record.domain_id for record in self.registry.records}
        known_access = {grant.access_id for grant in self.grants}
        known_expiry = {expiry.expiry_id for expiry in self.expiries}
        for grant in self.grants:
            if grant.domain_id not in known_domains:
                raise AccessError("Access refers to an unknown Domain")
            if grant.registry_hash != self.registry.registry_hash:
                raise AccessError("Access refers to a different registry manifest")
        for expiry in self.expiries:
            if expiry.access_id not in known_access:
                raise AccessError("expiry refers to an unknown Access")
            access = next(
                grant for grant in self.grants if grant.access_id == expiry.access_id
            )
            if expiry.effective_at != access.ends_at:
                raise AccessError("expiry does not match the exact Access ends_at")
        _access_unique(
            (expiry.access_id for expiry in self.expiries),
            label="expiry Access reference",
        )
        by_agent: dict[str, list[AccessGrant]] = {}
        for grant in self.grants:
            by_agent.setdefault(grant.agent_id, []).append(grant)
        for grants in by_agent.values():
            ordered = sorted(
                grants,
                key=lambda item: (item.starts_at, item.ends_at, item.access_id),
            )
            latest_end: datetime | None = None
            for grant in ordered:
                if latest_end is not None and grant.starts_at < latest_end:
                    raise AccessError("state contains overlapping Access for one agent")
                latest_end = grant.ends_at
        mapped_objects: set[str] = set()
        for record in self.idempotency_records:
            if record.operation == "grant_access":
                if record.object_id not in known_access:
                    raise AccessError("idempotency result refers to an unknown Access")
            elif record.object_id not in known_expiry:
                raise AccessError("idempotency result refers to an unknown expiry")
            mapped_objects.add(record.object_id)
        if mapped_objects != known_access | known_expiry:
            raise AccessError("state objects must have exact idempotency results")


def _access_unique(values: Iterable[str], *, label: str) -> None:
    values = tuple(values)
    if len(values) != len(set(values)):
        raise AccessError(f"state contains duplicate {label}")


def initial_access_state(registry: DomainRegistry) -> DomainAccessState:
    """Create empty control-plane state for one validated registry manifest."""

    return DomainAccessState(registry=registry)


def _idempotency_request(
    *,
    operation: str,
    payload: Mapping[str, object],
) -> str:
    return _hash_value({"operation": operation, "payload": payload})


def _replay_record(
    state: DomainAccessState,
    *,
    key: str,
    operation: str,
    request_hash: str,
) -> IdempotencyRecord | None:
    _access_string(key, field="idempotency key")
    for record in state.idempotency_records:
        if record.key != key:
            continue
        if record.operation != operation or record.request_hash != request_hash:
            raise AccessError("idempotency key was reused with different input")
        return record
    return None


def _grant_by_id(state: DomainAccessState, access_id: str) -> AccessGrant:
    for grant in state.grants:
        if grant.access_id == access_id:
            return grant
    raise AccessError(f"Access is not present in state: {access_id}")


def grant_access(
    state: DomainAccessState,
    *,
    authority_kind: str,
    authority_id: str,
    authority_revision_id: str,
    agent_id: str,
    domain_id: str,
    effective_at: datetime,
    idempotency_key: str,
) -> tuple[DomainAccessState, AccessGrant]:
    """Grant one fixed Access if source, Domain, and global overlap checks pass."""

    if not isinstance(state, DomainAccessState):
        raise AccessError("state must be a DomainAccessState")
    authority_kind = _access_string(authority_kind, field="authority_kind")
    authority_id = _access_string(authority_id, field="authority_id")
    authority_revision_id = _access_string(
        authority_revision_id,
        field="authority_revision_id",
    )
    agent_id = _access_string(agent_id, field="agent_id")
    domain_id = _access_domain_id(domain_id)
    starts_at = _utc(effective_at, field="effective_at")
    try:
        ends_at = starts_at + ACCESS_DURATION
    except OverflowError as exc:
        raise AccessError("effective_at cannot form a seven-day Access") from exc
    request = _access_payload(
        authority_kind=authority_kind,
        authority_id=authority_id,
        authority_revision_id=authority_revision_id,
        agent_id=agent_id,
        domain_id=domain_id,
        registry_hash=state.registry.registry_hash,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    request_hash = _idempotency_request(operation="grant_access", payload=request)
    replay = _replay_record(
        state,
        key=idempotency_key,
        operation="grant_access",
        request_hash=request_hash,
    )
    if replay is not None:
        return state, _grant_by_id(state, replay.object_id)
    if authority_kind not in _ALLOWED_AUTHORITIES:
        raise AccessError("authority_kind must be operator or agent0")
    state.registry.domain(domain_id)
    for existing in state.grants:
        if (
            existing.agent_id == agent_id
            and starts_at < existing.ends_at
            and existing.starts_at < ends_at
        ):
            raise AccessError("agent already has overlapping Access")
    access = AccessGrant(
        access_id=f"access:{_hash_value(request)}",
        authority_kind=authority_kind,
        authority_id=authority_id,
        authority_revision_id=authority_revision_id,
        agent_id=agent_id,
        domain_id=domain_id,
        registry_hash=state.registry.registry_hash,
        starts_at=starts_at,
        ends_at=ends_at,
    )
    record = IdempotencyRecord(
        key=idempotency_key,
        operation="grant_access",
        request_hash=request_hash,
        object_id=access.access_id,
    )
    return (
        DomainAccessState(
            registry=state.registry,
            grants=(*state.grants, access),
            expiries=state.expiries,
            idempotency_records=(*state.idempotency_records, record),
        ),
        access,
    )


def expire_access(
    state: DomainAccessState,
    *,
    access_id: str,
    effective_at: datetime,
    idempotency_key: str,
) -> tuple[DomainAccessState, AccessExpiry]:
    """Record the deterministic expiry at the grant's exact ends_at boundary."""

    if not isinstance(state, DomainAccessState):
        raise AccessError("state must be a DomainAccessState")
    access_id = _access_string(access_id, field="access_id")
    at = _utc(effective_at, field="effective_at")
    request = {"access_id": access_id, "effective_at": _timestamp(at)}
    request_hash = _idempotency_request(operation="expire_access", payload=request)
    replay = _replay_record(
        state,
        key=idempotency_key,
        operation="expire_access",
        request_hash=request_hash,
    )
    if replay is not None:
        for expiry in state.expiries:
            if expiry.expiry_id == replay.object_id:
                return state, expiry
        raise AccessError("idempotency result refers to an unknown expiry")
    access = _grant_by_id(state, access_id)
    if at != access.ends_at:
        raise AccessError("Access expiry must use the exact ends_at boundary")
    if any(expiry.access_id == access_id for expiry in state.expiries):
        raise AccessError("Access already has an expiry record")
    expiry = AccessExpiry(
        expiry_id=f"access-expiry:{_hash_value(request)}",
        access_id=access_id,
        effective_at=at,
    )
    record = IdempotencyRecord(
        key=idempotency_key,
        operation="expire_access",
        request_hash=request_hash,
        object_id=expiry.expiry_id,
    )
    return (
        DomainAccessState(
            registry=state.registry,
            grants=state.grants,
            expiries=(*state.expiries, expiry),
            idempotency_records=(*state.idempotency_records, record),
        ),
        expiry,
    )


def is_access_active(access: AccessGrant, at: datetime) -> bool:
    """Return whether a time is inside the fixed half-open Access interval."""

    if not isinstance(access, AccessGrant):
        raise AccessError("access must be an AccessGrant")
    instant = _utc(at, field="at")
    return access.starts_at <= instant < access.ends_at


__all__ = [
    "ACCESS_DURATION",
    "AccessError",
    "AccessExpiry",
    "AccessGrant",
    "DomainAccessState",
    "DomainRecord",
    "DomainRegistry",
    "DomainRegistryError",
    "IdempotencyRecord",
    "build_domain_registry",
    "expire_access",
    "grant_access",
    "initial_access_state",
    "is_access_active",
    "load_domain_registry",
    "load_domain_registry_bytes",
    "make_domain_record",
    "serialize_domain_registry",
]
