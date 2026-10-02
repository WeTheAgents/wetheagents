"""Append-only initiative and Domain revisions outside released executors.

This module has no I/O and owns no financial state. Live intake supplies verified
repository observations; replay checks the retained observations against sources.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from . import access_control as c
from .domain_access import (
    DomainAccessState,
    DomainRecord,
    build_domain_registry,
    grant_access,
)
from .tide.replay import digest, json_data

SCHEMA = "wea-initiative-1"
MARKER = "<!-- wea-initiative -->\n"
POLICY = "wea-long-lived-initiatives:1"
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


@dataclass(frozen=True)
class State:
    """Keep legacy grants in their original registry-specific state values."""

    groups: tuple[DomainAccessState, ...]
    boundaries: tuple[datetime, ...]
    activation_at: datetime
    initiatives: dict[str, Any]
    history: tuple[tuple[datetime, dict[str, Any]], ...] = ()
    observations: tuple[dict[str, Any], ...] = ()

    @property
    def registry(self):
        return self.groups[-1].registry

    @property
    def grants(self):
        return tuple(g for group in self.groups for g in group.grants)

    def binding(self, domain_id: str, at: datetime | None = None):
        selected = self.groups[-1]
        if at is not None:
            selected = self.groups[0]
            for boundary, group in zip(self.boundaries, self.groups, strict=True):
                if boundary <= at:
                    selected = group
        return selected.registry.domain(domain_id)

    def grant_binding(self, grant):
        return next(
            group.registry.domain(grant.domain_id).record_hash
            for group in self.groups
            if group.registry.registry_hash == grant.registry_hash
        )

    def assignable(self, initiative_id: str, at: datetime) -> str:
        initiatives: dict[str, Any] = {}
        for boundary, snapshot in self.history:
            if boundary <= at:
                initiatives.update(snapshot)
        card = initiatives.get(initiative_id)
        if not card or card["status"] != "active" or not card["steward"]:
            raise ValueError("new initiative assignment requires an active Steward")
        return card["steward"]


def text(value: Any, name: str, limit: int = 4096) -> str:
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {name}")
    return value


def fields(value: Any, names: set[str]) -> None:
    if type(value) is not dict or set(value) != names:
        raise ValueError("operation fields differ")


def request(body: str) -> dict[str, Any]:
    if not body.startswith(MARKER) or len(body.encode()) > 65536:
        raise ValueError("missing initiative marker or oversized request")
    value = c.strict_json(body[len(MARKER) :])
    fields(value, {"schema", "request_id", "actor", "operation", "payload"})
    if (
        value["schema"] != SCHEMA
        or str(UUID(value["request_id"])) != value["request_id"]
    ):
        raise ValueError("unsupported schema or request UUID")
    fields(value["actor"], {"kind", "subject", "binding_id", "binding_version"})
    for key in ("subject", "binding_id"):
        text(value["actor"][key], key, 256)
    if (
        type(value["actor"]["binding_version"]) is not int
        or value["actor"]["binding_version"] < 1
    ):
        raise ValueError("actor binding version must be a positive integer")
    if value["actor"]["kind"] not in {"agent", "agent0", "operator"}:
        raise ValueError("unsupported actor kind")
    if type(value["payload"]) is not dict:
        raise ValueError("payload must be an object")
    text(value["operation"], "operation", 64)
    return value


def actor(source: dict, command: dict, identities: dict, at: datetime) -> str:
    selected = command["actor"]
    if selected["kind"] in {"operator", "agent0"}:
        c.authority(
            source,
            {"issuer": selected, "agent_id": selected["subject"]},
            identities,
            at,
            require_recipient=False,
        )
        return selected["subject"]
    modules = c.load_executor(c.installed_executor("0.9.0").reference).import_modules(
        ("identity",)
    )
    registry = c.records.registry(modules, identities)
    bindings = [
        modules["identity"].resolve_binding(
            tuple(b for b in registry.bindings if b.actor_kind == "agent"),
            github_account_id=source["original_author_account_id"],
            subject_id=selected["subject"],
            effective_at=instant,
        )
        for instant in (c.timestamp(source["created_at"]), at)
    ]
    if (
        bindings[0] != bindings[1]
        or bindings[0].binding_id != selected["binding_id"]
        or bindings[0].version != selected["binding_version"]
        or type(selected["binding_version"]) is not int
    ):
        raise ValueError("actor binding differs at source or acceptance")
    return selected["subject"]


def repository_refs(command: dict) -> list[dict]:
    payload = command["payload"]
    if command["operation"] in {
        "registry-add",
        "registry-replace",
        "repository-observe",
    }:
        record = payload.get("record", {})
        return [
            {
                "repository_id": record.get("repository_id"),
                "repository_locator": record.get("repository_locator"),
            }
        ]
    if command["operation"] in {"create", "references"}:
        return payload.get("repositories", [])
    return []


def repositories(command: dict, observations: list[dict]) -> None:
    refs = repository_refs(command)
    if type(refs) is not list or len(refs) > 32 or len(observations) != len(refs):
        raise ValueError("repository observations differ")
    for ref, observed in zip(refs, observations, strict=True):
        fields(ref, {"repository_id", "repository_locator"})
        # Reuse the strict permanent ID and canonical locator validation.
        payload = {"domain_id": "observation", **ref, "revision": "0" * 40}
        DomainRecord(**payload, record_hash=digest(payload))
        context = command["operation"] in {"registry-add", "registry-replace"}
        fields(
            observed,
            {"requested_locator", "repository_id", "repository_locator"}
            | ({"context_revision"} if context else set()),
        )
        if (
            observed["requested_locator"] != ref["repository_locator"]
            or observed["repository_id"] != ref["repository_id"]
        ):
            raise ValueError("resolved repository ID differs")
        if context:
            record = DomainRecord(**command["payload"]["record"])
            if observed["context_revision"] != record.revision:
                raise ValueError("resolved repository context revision differs")
        current = {**payload, "repository_locator": observed["repository_locator"]}
        DomainRecord(**current, record_hash=digest(current))


def decide(
    genesis: dict,
    state: DomainAccessState | State,
    previous: list[dict],
    source: dict,
    identities: dict,
    accepted_at: str,
    observations: list[dict],
    package: dict,
    provenance: dict,
) -> tuple[DomainAccessState | State, dict]:
    result: dict[str, Any] = {
        "status": "rejected",
        "request_key": None,
        "request": None,
    }
    try:
        command = request(source["body"])
        result["request"] = command
        if (
            source["repository_id"] != str(c.REPOSITORY_ID)
            or source["object_kind"] != "issue_comment"
            or source["issue_number"] != genesis["issue_number"]
            or source["actor_account_id"] != source["original_author_account_id"]
            or source["content_hash"] != c.sha256(source["body"])
            or source["revision_status"] != "confirmed"
            or source["edit_history"]
            or not source["revision_id"].endswith(":created")
        ):
            raise ValueError(
                "initiative requires a confirmed unedited canonical source"
            )
        at, created = c.timestamp(accepted_at), c.timestamp(source["created_at"])
        last = c.timestamp(
            previous[-1]["accepted_at"] if previous else genesis["cutoff"]
        )
        if not c.timestamp(genesis["cutoff"]) < created <= at or at < last:
            raise ValueError("source or trusted acceptance boundary differs")
        key = ":".join(
            (
                str(c.REPOSITORY_ID),
                source["original_author_account_id"],
                command["request_id"],
            )
        )
        result["request_key"] = key
        original = next(
            (e for e in previous if e["decision"].get("request_key") == key), None
        )
        if original:
            if original["decision"]["request"] != command:
                raise ValueError("request ID belongs to a different payload")
            return state, {
                **original["decision"],
                "duplicate_of": original["source"]["object_id"],
            }
        subject = actor(source, command, identities, at)
        op, payload = command["operation"], command["payload"]
        if op == "activate-policy":
            fields(payload, {"policy", "code_sha", "protocol_hash"})
            if observations:
                raise ValueError("activation has no repository observations")
            if isinstance(state, State):
                raise ValueError("initiative policy is already active")
            if (
                command["actor"]["kind"] != "operator"
                or payload
                != {
                    "policy": POLICY,
                    "code_sha": package["code_sha"],
                    "protocol_hash": digest(package["protocol_files"]),
                }
                or "src/wea_vnext/initiatives.py" not in package["protocol_files"]
                or provenance.get("initiative_activation") != source["content_hash"]
                or provenance.get("event") != "workflow_dispatch"
                or provenance.get("workflow") != ".github/workflows/access.yml"
                or provenance.get("code_sha") != package["code_sha"]
            ):
                raise ValueError(
                    "policy activation requires exact operator dispatch "
                    "and installed package"
                )
            candidate = State((state,), (c.timestamp(genesis["cutoff"]),), at, {})
        else:
            if not isinstance(state, State) or created <= state.activation_at:
                raise ValueError("initiative policy is not active at the source time")
            repositories(command, observations)
            if op.startswith("registry-") or op == "repository-observe":
                candidate = registry_decision(state, command, observations, at)
            elif op == "grant":
                if command["actor"] != payload.get("issuer"):
                    raise ValueError("grant actor must select its explicit issuer role")
                candidate, grant = scoped_grant(
                    state, source, payload, identities, at, key
                )
                return candidate, {
                    **result,
                    "status": "granted",
                    "grant": json_data(grant),
                    "binding_revision": candidate.grant_binding(grant),
                }
            else:
                candidate = initiative_decision(state, command, subject, source, at)
        return candidate, {
            **result,
            "status": "recorded",
            "effect": op,
            "revision": digest(json_data(candidate)),
        }
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return state, {**result, "reason": str(exc)}


def registry_decision(
    state: State, command: dict, observations: list, at: datetime
) -> State:
    op, payload = command["operation"], command["payload"]
    fields(payload, {"previous_registry", "record", "reason"})
    text(payload["reason"], "reason")
    if payload["previous_registry"] != state.registry.registry_hash:
        raise ValueError("registry predecessor differs")
    fields(
        payload["record"],
        {"domain_id", "repository_id", "repository_locator", "revision", "record_hash"},
    )
    record = DomainRecord(**payload["record"])
    old = next(
        (r for r in state.registry.records if r.domain_id == record.domain_id), None
    )
    if op == "repository-observe":
        if not old or old.repository_id != record.repository_id:
            raise ValueError(
                "observation requires the existing permanent repository ID"
            )
        return replace(
            state,
            observations=(
                *state.observations,
                {"domain_id": old.domain_id, "at": json_data(at), **observations[0]},
            ),
        )
    if command["actor"]["kind"] not in {"operator", "agent0"}:
        raise ValueError("registry additions require Agent0 or operator")
    if op == "registry-add" and old is not None:
        raise ValueError("Domain already exists; use an exact replacement")
    if op == "registry-replace" and (
        old is None
        or command["actor"]["kind"] != "operator"
        or old.repository_id == record.repository_id
    ):
        raise ValueError("replacement requires operator and a different repository ID")
    if op not in {"registry-add", "registry-replace"}:
        raise ValueError("unknown registry operation")
    registry = build_domain_registry(
        (
            *[r for r in state.registry.records if r.domain_id != record.domain_id],
            record,
        )
    )
    return replace(
        state,
        groups=(*state.groups, DomainAccessState(registry=registry)),
        boundaries=(*state.boundaries, at),
    )


def scoped_grant(
    state: State, source: dict, payload: dict, identities: dict, at: datetime, key: str
):
    fields(
        payload,
        {"agent_id", "domain_id", "registry_hash", "binding_revision", "issuer"},
    )
    if payload["registry_hash"] != state.registry.registry_hash:
        raise ValueError("requested registry is stale")
    if payload["binding_revision"] != state.binding(payload["domain_id"]).record_hash:
        raise ValueError("requested binding differs")
    witness = c.authority(source, payload, identities, at)
    if any(
        g.agent_id == payload["agent_id"] and g.starts_at <= at < g.ends_at
        for g in state.grants
    ):
        raise ValueError("agent already has a globally overlapping trip")
    group = replace(
        state.groups[-1],
        authority_bindings=(*state.groups[-1].authority_bindings, witness),
    )
    group, grant = grant_access(
        group,
        authority_kind=witness.authority_kind,
        authority_id=witness.authority_id,
        authority_revision_id=witness.authority_revision_id,
        agent_id=payload["agent_id"],
        domain_id=payload["domain_id"],
        effective_at=at,
        idempotency_key=key,
    )
    return replace(state, groups=(*state.groups[:-1], group)), grant


def initiative_decision(
    state: State, command: dict, subject: str, source: dict, at: datetime
) -> State:
    op, payload = command["operation"], command["payload"]
    if command["actor"]["kind"] != "agent" and not (
        op == "handoff-propose" and command["actor"]["kind"] == "operator"
    ):
        raise ValueError(
            "initiative responsibility requires a registered agent binding"
        )
    cards = copy.deepcopy(state.initiatives)
    identifier = payload.get("initiative_id")
    if type(identifier) is not str or not SLUG.fullmatch(identifier):
        raise ValueError("initiative ID must be a canonical slug")
    if op == "create":
        fields(
            payload,
            {"initiative_id", "title", "question", "responsibility", "repositories"},
        )
        if identifier in cards or command["actor"]["kind"] == "operator":
            raise ValueError("initiative exists or proposer is not a registered agent")
        cards[identifier] = {
            "initiative_id": identifier,
            "title": text(payload["title"], "title", 256),
            "question": text(payload["question"], "question"),
            "proposer": subject,
            "steward": subject,
            "status": "proposed",
            "revision": 1,
            "participants": {
                subject: text(payload["responsibility"], "responsibility")
            },
            "repositories": payload["repositories"],
            "decisions": [],
            "handoff": None,
        }
    else:
        card = cards.get(identifier)
        if not card or payload.get("previous_revision") != digest(card):
            raise ValueError("initiative predecessor differs")
        base = {"initiative_id", "previous_revision"}
        if op == "participate":
            fields(payload, base | {"responsibility"})
            if card["status"] != "active" or not card["steward"]:
                raise ValueError("new participation requires an active Steward")
            if command["actor"]["kind"] == "operator":
                raise ValueError("participant requires an agent binding")
            card["participants"][subject] = text(
                payload["responsibility"], "responsibility"
            )
        elif op == "handoff-consent":
            fields(payload, base | {"proposal_hash"})
            proposal = card["handoff"]
            if (
                not proposal
                or proposal["next_steward"] != subject
                or digest(proposal) != payload["proposal_hash"]
            ):
                raise ValueError("new Steward consent differs")
            card["steward"] = subject
            card["participants"][subject] = "Steward"
            card["handoff"] = None
        elif op == "leave":
            fields(payload, base | {"reason"})
            text(payload["reason"], "reason")
            if subject not in card["participants"]:
                raise ValueError("only a participant can leave its own responsibility")
            card["participants"].pop(subject)
            if card["steward"] == subject:
                card.update(steward=None, status="paused", handoff=None)
        else:
            operator_override = (
                op == "handoff-propose" and command["actor"]["kind"] == "operator"
            )
            if card["steward"] != subject and not operator_override:
                raise ValueError("only the current Steward can change direction")
            if op == "references":
                fields(payload, base | {"repositories", "reason"})
                text(payload["reason"], "reason")
                card["repositories"] = payload["repositories"]
            elif op == "handoff-propose":
                fields(payload, base | {"next_steward", "reason"})
                card["handoff"] = {
                    "next_steward": text(payload["next_steward"], "next Steward", 256),
                    "previous_revision": payload["previous_revision"],
                    "reason": text(payload["reason"], "reason"),
                    "source": source["revision_id"],
                    "operator_resolution": operator_override,
                }
            elif op == "decision":
                fields(
                    payload,
                    base | {"status", "reason", "next_question", "evidence", "tasks"},
                )
                if payload["status"] not in {"active", "paused", "archived"}:
                    raise ValueError("invalid lifecycle status")
                text(payload["reason"], "reason")
                text(payload["next_question"], "next question or closure reason")
                if type(payload["tasks"]) is not list or any(
                    type(t) is not str or not t.startswith("https://github.com/")
                    for t in payload["tasks"]
                ):
                    raise ValueError("task links require exact GitHub references")
                evidence = payload["evidence"]
                fields(
                    evidence,
                    {
                        "inputs",
                        "method",
                        "result",
                        "limitations",
                        "references",
                        "common_control",
                        "downstream_use",
                    },
                )
                for name in (
                    "inputs",
                    "method",
                    "result",
                    "limitations",
                    "common_control",
                ):
                    text(evidence[name], name)
                for name in ("references", "downstream_use"):
                    if type(evidence[name]) is not list or any(
                        type(r) is not str or not r.strip() for r in evidence[name]
                    ):
                        raise ValueError("evidence references must be explicit")
                card["status"] = payload["status"]
                card["question"] = payload["next_question"]
            else:
                raise ValueError("unknown initiative operation")
        # An intervening change invalidates an outstanding handoff proposal.
        if op not in {"handoff-propose", "handoff-consent"}:
            card["handoff"] = None
        card["revision"] += 1
    cards[identifier]["decisions"].append(
        {
            "operation": op,
            "payload": payload,
            "actor": subject,
            "source": source["revision_id"],
            "accepted_at": json_data(at),
        }
    )
    responsibility = {
        identifier: {
            "status": cards[identifier]["status"],
            "steward": cards[identifier]["steward"],
        }
    }
    return replace(
        state, initiatives=cards, history=(*state.history, (at, responsibility))
    )


def meaningful(snapshot: dict | None) -> Any:
    """Ignore initiative metadata for batch triggers, never for retained replay."""
    if not snapshot or snapshot["genesis"] is None:
        return None
    selected = []
    for entry, commit in zip(snapshot["entries"], snapshot["commits"], strict=True):
        if (
            entry["schema"] != SCHEMA
            or entry["decision"].get("effect")
            in {"activate-policy", "registry-add", "registry-replace"}
            or entry["decision"]["status"] == "granted"
        ):
            selected.append((entry, commit))
    return snapshot["genesis"], selected
