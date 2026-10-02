"""Fixed-format private Access decisions; no task or financial mutations."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .domain_access import (
    DomainAccessState,
    VerifiedAccessAuthority,
    grant_access,
    load_domain_registry_bytes,
)
from .engine import installed_executor, load_executor
from .tide import records
from .tide.activation import OPERATOR
from .tide.collection import REPOSITORY_ID
from .tide.replay import canonical, digest, json_data

MARKER = "<!-- wea-access -->\n"
ACTIVATION_MARKER = "<!-- wea-access-activate -->\n"
SCHEMA = "wea-access-1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: str) -> datetime:
    return records.timestamp(value).astimezone(timezone.utc)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strict_json(text: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise ValueError("non-finite JSON value")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return value
    except RecursionError:
        raise ValueError("JSON nesting exceeds the supported bound") from None
    except UnicodeEncodeError:
        raise ValueError("JSON contains invalid Unicode") from None


def request(body: str) -> dict[str, Any]:
    if not body.startswith(MARKER) or len(body.encode()) > 16384:
        raise ValueError("missing Access marker or oversized request")
    value = strict_json(body[len(MARKER) :])
    if type(value) is not dict or set(value) != {
        "schema",
        "request_id",
        "agent_id",
        "domain_id",
        "issuer",
        "registry_hash",
    }:
        raise ValueError("request fields differ from Access format 1")
    if value["schema"] != SCHEMA:
        raise ValueError("unsupported Access format")
    if str(UUID(value["request_id"])) != value["request_id"]:
        raise ValueError("request_id must be a canonical UUID")
    for key in ("agent_id", "domain_id", "registry_hash"):
        if type(value[key]) is not str or not value[key].strip():
            raise ValueError(f"invalid {key}")
    issuer = value["issuer"]
    if type(issuer) is not dict or set(issuer) != {
        "kind",
        "subject",
        "binding_id",
        "binding_version",
    }:
        raise ValueError("issuer must select an explicit canonical role")
    if issuer["kind"] not in {"operator", "agent0"}:
        raise ValueError("only operator or Agent0 may grant Access")
    if type(issuer["binding_version"]) is not int or issuer["binding_version"] < 1:
        raise ValueError("invalid binding version")
    if any(
        type(issuer[k]) is not str or not issuer[k] for k in ("subject", "binding_id")
    ):
        raise ValueError("invalid issuer identity")
    return value


def initial_state(genesis: dict[str, Any]) -> DomainAccessState:
    raw = genesis["registry_text"]
    registry = load_domain_registry_bytes(raw.encode("utf-8"), source="Access genesis")
    if registry.registry_hash != genesis["registry_hash"]:
        raise ValueError("genesis Domain registry hash differs")
    return DomainAccessState(registry=registry)


def authority(
    source: dict[str, Any],
    command: dict[str, Any],
    identities: dict[str, Any],
    at: datetime,
    *,
    require_recipient: bool = True,
) -> VerifiedAccessAuthority:
    modules = load_executor(installed_executor("0.9.0").reference).import_modules(
        ("identity",)
    )
    registry = records.registry(modules, identities)
    identity = modules["identity"]
    issuer = command["issuer"]
    account = source["original_author_account_id"]
    if account != source["actor_account_id"]:
        raise ValueError("source editor is not its original author")
    if issuer["kind"] == "operator" and account != str(OPERATOR):
        raise ValueError("source is not the canonical operator")
    if issuer["kind"] == "agent0" and issuer["subject"] != "agent0@system":
        raise ValueError("Agent0 subject differs")
    role_bindings = tuple(
        b for b in registry.bindings if b.actor_kind == issuer["kind"]
    )
    # The canonical operator account may have no separate Agent role binding.
    if issuer["kind"] == "operator":
        if issuer != {
            "kind": "operator",
            "subject": str(OPERATOR),
            "binding_id": "canonical-operator",
            "binding_version": 1,
        }:
            raise ValueError("operator authority selector differs")
        start, end = timestamp("1970-01-01T00:00:00Z"), None
        evidence: Any = issuer
    else:
        bindings = [
            identity.resolve_binding(
                role_bindings,
                github_account_id=account,
                subject_id=issuer["subject"],
                effective_at=instant,
            )
            for instant in (timestamp(source["created_at"]), at)
        ]
        if (
            any(
                b.binding_id != issuer["binding_id"]
                or b.version != issuer["binding_version"]
                for b in bindings
            )
            or bindings[0] != bindings[1]
        ):
            raise ValueError("declared role differs at declaration or acceptance")
        start, end = bindings[0].effective_from, bindings[0].effective_until
        evidence = json_data(bindings[0])
    recipients = [
        b
        for b in registry.bindings
        if b.actor_kind == "agent"
        and b.subject_id == command["agent_id"]
        and b.active_at(at)
    ]
    if require_recipient and (
        len(recipients) != 1
        or not any(
            a.github_account_id == recipients[0].github_account_id
            for a in registry.accounts
        )
    ):
        raise ValueError("recipient is not canonically registered at acceptance")
    return VerifiedAccessAuthority(
        authority_kind=issuer["kind"],
        authority_id=issuer["subject"],
        authority_revision_id=source["revision_id"],
        binding_id="access-witness:" + digest([evidence, source["revision_id"]]),
        binding_version=issuer["binding_version"],
        effective_from=start,
        effective_until=end,
    )


def decide(
    genesis: dict[str, Any],
    state: DomainAccessState,
    previous: list[dict[str, Any]],
    source: dict[str, Any],
    identities: dict[str, Any],
    accepted_at: str,
) -> tuple[DomainAccessState, dict[str, Any]]:
    """Replay one retained source using its original acceptance clock."""
    result: dict[str, Any] = {
        "status": "rejected",
        "request_key": None,
        "request": None,
    }
    try:
        if (
            source["repository_id"] != str(REPOSITORY_ID)
            or source["issue_number"] != genesis["issue_number"]
        ):
            raise ValueError("source belongs to another repository or Issue")
        if sha256(source["body"]) != source["content_hash"]:
            raise ValueError("retained source hash differs")
        command = request(source["body"])
        result["request"] = command
        if (
            source["revision_status"] != "confirmed"
            or source["edit_history"]
            or not source["revision_id"].endswith(":created")
        ):
            raise ValueError("Access requires an unedited confirmed source")
        at = timestamp(accepted_at)
        created = timestamp(source["created_at"])
        if not timestamp(genesis["cutoff"]) < created <= at:
            raise ValueError("source is outside the activation/acceptance interval")
        key = ":".join(
            (
                str(REPOSITORY_ID),
                source["original_author_account_id"],
                command["request_id"],
            )
        )
        result.update(request_key=key, request=command)
        original = next(
            (r for r in previous if r["decision"]["request_key"] == key), None
        )
        if original is not None:
            if original["decision"]["request"] != command:
                raise ValueError("request ID already belongs to a different payload")
            return state, {
                **original["decision"],
                "duplicate_of": original["source"]["object_id"],
            }
        if command["registry_hash"] != genesis["registry_hash"]:
            raise ValueError("requested Domain registry differs")
        from .initiatives import State

        if isinstance(state, State):
            raise ValueError(
                "active initiative policy requires an explicit binding grant"
            )
        witness = authority(source, command, identities, at)
        candidate = replace(
            state, authority_bindings=(*state.authority_bindings, witness)
        )
        candidate, grant = grant_access(
            candidate,
            authority_kind=witness.authority_kind,
            authority_id=witness.authority_id,
            authority_revision_id=witness.authority_revision_id,
            agent_id=command["agent_id"],
            domain_id=command["domain_id"],
            effective_at=at,
            idempotency_key=key,
        )
        return candidate, {
            **result,
            "status": "granted",
            "grant": json_data(grant),
            "authority": json_data(witness),
            "attribution": "declared-agent; authenticated-account",
        }
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return state, {**result, "reason": str(exc)}


def replay(genesis: dict[str, Any], entries: list[dict[str, Any]]) -> DomainAccessState:
    from . import access_protocol, initiatives

    state = initial_state(genesis)
    package = access_protocol.package(genesis, [])
    previous: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_at = timestamp(genesis["cutoff"])
    for entry in entries:
        source_id = entry["source"]["object_id"]
        if source_id in seen or timestamp(entry["accepted_at"]) < last_at:
            raise ValueError("journal repeats a source or moves clock backwards")
        if entry["schema"] == access_protocol.SCHEMA:
            access_protocol.validate(genesis, package, entry)
            package = access_protocol.package(genesis, [entry])
            seen.add(source_id)
            last_at = timestamp(entry["accepted_at"])
            continue
        if entry["schema"] == initiatives.SCHEMA:
            if set(entry) != {
                "schema",
                "source",
                "identities",
                "identity_commit",
                "accepted_at",
                "provenance",
                "decision",
                "repositories",
            }:
                raise ValueError("initiative journal fields differ")
            if not re.fullmatch(r"[0-9a-f]{40}", entry["identity_commit"]):
                raise ValueError("initiative identity commit differs")
            state, expected = initiatives.decide(
                genesis,
                state,
                previous,
                entry["source"],
                entry["identities"],
                entry["accepted_at"],
                entry["repositories"],
                package,
                entry["provenance"],
            )
            if canonical(expected) != canonical(entry["decision"]):
                raise ValueError("initiative decision differs from evidence replay")
            previous.append(entry)
            seen.add(source_id)
            last_at = timestamp(entry["accepted_at"])
            continue
        if set(entry) != {
            "schema",
            "source",
            "identities",
            "identity_commit",
            "accepted_at",
            "provenance",
            "decision",
        }:
            raise ValueError("journal entry fields differ")
        if entry["schema"] != SCHEMA or not re.fullmatch(
            r"[0-9a-f]{40}", entry["identity_commit"]
        ):
            raise ValueError("journal format or identity commit differs")
        source_id = entry["source"]["object_id"]
        if source_id in seen or timestamp(entry["accepted_at"]) < last_at:
            raise ValueError("journal repeats a source or moves clock backwards")
        state, expected = decide(
            genesis,
            state,
            previous,
            entry["source"],
            entry["identities"],
            entry["accepted_at"],
        )
        if canonical(expected) != canonical(entry["decision"]):
            raise ValueError("journal decision differs from retained evidence replay")
        previous.append(entry)
        seen.add(source_id)
        last_at = timestamp(entry["accepted_at"])
    return state


def view(entry: dict[str, Any], commit: str, at: datetime) -> dict[str, Any]:
    decision = entry["decision"]
    result = {
        **decision,
        "source_url": entry["source"]["url"],
        "journal_commit": commit,
        "evaluated_at": json_data(at),
        "evaluation": "actual-utc-read",
    }
    if decision["status"] == "granted":
        grant = decision["grant"]
        result["status"] = (
            "active"
            if timestamp(grant["starts_at"]) <= at < timestamp(grant["ends_at"])
            else "expired"
        )
    return result
