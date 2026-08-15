from __future__ import annotations

import json
from pathlib import Path

import pytest

from wea_vnext.domain_access import (
    DomainRecord,
    DomainRegistry,
    DomainRegistryError,
    build_domain_registry,
    load_domain_registry,
    load_domain_registry_bytes,
    make_domain_record,
    serialize_domain_registry,
)

REPOSITORY_ID = "R_kgDOPublicCircle1"
REVISION = "1" * 40
LOCATOR = "https://github.com/WeTheAgents/circle-1"
LIVE_REGISTRY = Path("domains/registry/v1.json")


def _registry_bytes() -> bytes:
    record = make_domain_record(
        domain_id="circle-1",
        repository_id=REPOSITORY_ID,
        repository_locator=LOCATOR,
        revision=REVISION,
    )
    return serialize_domain_registry(build_domain_registry((record,)))


def test_s_11a_loads_one_canonical_immutable_domain_record(tmp_path: Path) -> None:
    raw = _registry_bytes()
    path = tmp_path / "v1.json"
    path.write_bytes(raw)

    registry = load_domain_registry(path)

    assert serialize_domain_registry(registry) == raw
    assert registry.schema_version == 1
    assert len(registry.records) == 1
    assert registry.records[0].domain_id == "circle-1"
    assert registry.records[0].repository_id == REPOSITORY_ID
    assert registry.records[0].repository_locator == LOCATOR
    assert registry.records[0].revision == REVISION
    assert len(registry.records[0].record_hash) == 64
    assert len(registry.registry_hash) == 64


def test_s_11a_live_registry_pins_the_public_circle1_revision() -> None:
    registry = load_domain_registry(LIVE_REGISTRY)

    assert serialize_domain_registry(registry) == LIVE_REGISTRY.read_bytes()
    assert len(registry.records) == 1
    assert registry.records[0].domain_id == "circle-1"
    assert registry.records[0].repository_id == "R_kgDOT4-F-Q"
    assert registry.records[0].repository_locator == LOCATOR
    assert registry.records[0].revision == (
        "36a71440840351aa462e61a8ad5955881f55ecb0"
    )


def test_registry_rejects_noncanonical_or_ambiguous_json() -> None:
    canonical = _registry_bytes()
    parsed = json.loads(canonical)
    duplicate_key = canonical.replace(
        b'{"records":',
        b'{"records":[],"records":',
        1,
    )

    invalid_inputs = (
        canonical + b"\n",
        json.dumps(parsed, indent=2).encode("utf-8"),
        duplicate_key,
        b"\xef\xbb\xbf" + canonical,
    )
    for raw in invalid_inputs:
        with pytest.raises(DomainRegistryError):
            load_domain_registry_bytes(raw)


def test_registry_rejects_changed_record_or_registry_hash() -> None:
    parsed = json.loads(_registry_bytes())
    parsed["records"][0]["revision"] = "2" * 40
    changed_record = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    with pytest.raises(DomainRegistryError, match="record hash"):
        load_domain_registry_bytes(changed_record)

    parsed = json.loads(_registry_bytes())
    parsed["registry_hash"] = "f" * 64
    changed_registry = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    with pytest.raises(DomainRegistryError, match="registry hash"):
        load_domain_registry_bytes(changed_registry)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("domain_id", "Circle One", "domain_id"),
        ("repository_id", "", "repository_id"),
        ("repository_locator", "git@github.com:WeTheAgents/circle-1.git", "locator"),
        ("repository_locator", LOCATOR + "/", "locator"),
        ("repository_locator", "https://github.com/WeTheAgents/.", "locator"),
        ("repository_locator", "https://github.com/-owner/circle-1", "locator"),
        ("repository_locator", LOCATOR + ".git", "locator"),
        ("revision", "abc123", "revision"),
    ),
)
def test_domain_record_rejects_noncanonical_identity_fields(
    field: str,
    value: str,
    message: str,
) -> None:
    values = {
        "domain_id": "circle-1",
        "repository_id": REPOSITORY_ID,
        "repository_locator": LOCATOR,
        "revision": REVISION,
    }
    values[field] = value

    with pytest.raises(DomainRegistryError, match=message):
        make_domain_record(**values)


def test_registry_rejects_duplicate_stable_identities() -> None:
    circle = make_domain_record(
        domain_id="circle-1",
        repository_id=REPOSITORY_ID,
        repository_locator=LOCATOR,
        revision=REVISION,
    )
    same_domain = make_domain_record(
        domain_id="circle-1",
        repository_id="R_kgDOOther",
        repository_locator="https://github.com/WeTheAgents/other",
        revision="2" * 40,
    )
    same_repository = make_domain_record(
        domain_id="other",
        repository_id=REPOSITORY_ID,
        repository_locator="https://github.com/WeTheAgents/renamed-circle",
        revision="3" * 40,
    )

    with pytest.raises(DomainRegistryError, match="domain_id"):
        build_domain_registry((circle, same_domain))
    with pytest.raises(DomainRegistryError, match="repository_id"):
        build_domain_registry((circle, same_repository))


def test_registry_load_does_not_use_a_network_or_mutable_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network lookup is outside the registry boundary")

    monkeypatch.setattr("socket.create_connection", forbidden)
    registry = load_domain_registry_bytes(_registry_bytes())

    assert registry.records[0].repository_locator == LOCATOR


def test_registry_normalizes_oversized_integer_parse_failure() -> None:
    raw = (
        b'{"records":[],"registry_hash":"'
        + b"0" * 64
        + b'","schema_version":'
        + b"9" * 5000
        + b"}"
    )

    with pytest.raises(DomainRegistryError, match="strict JSON"):
        load_domain_registry_bytes(raw)


def test_registry_rejects_forged_record_and_registry_subclasses() -> None:
    class ForgedRecord(DomainRecord):
        def __post_init__(self) -> None:
            pass

    class ForgedRegistry(DomainRegistry):
        def __post_init__(self) -> None:
            pass

    forged_record = ForgedRecord(
        domain_id="circle-1",
        repository_id=REPOSITORY_ID,
        repository_locator=LOCATOR,
        revision=REVISION,
        record_hash="f" * 64,
    )
    with pytest.raises(DomainRegistryError, match="DomainRecord"):
        build_domain_registry((forged_record,))

    valid_record = make_domain_record(
        domain_id="circle-1",
        repository_id=REPOSITORY_ID,
        repository_locator=LOCATOR,
        revision=REVISION,
    )
    forged_registry = ForgedRegistry(
        schema_version=2,
        records=(valid_record,),
        registry_hash="f" * 64,
    )
    with pytest.raises(DomainRegistryError, match="DomainRegistry"):
        serialize_domain_registry(forged_registry)
