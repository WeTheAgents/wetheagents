"""Domain admission around the immutable task executor, with retained Access."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .records import timestamp

SCHEMA = "wea-tide-batch-3"
REVISION_SCHEMA = "wea-tide-batch-4"
BINDING = re.compile(r"<!-- wea:binding ([0-9a-f]{64}) -->")
INITIATIVE = re.compile(r"<!-- wea:initiative ([a-z0-9-]{1,63}) -->")
SCOPE = re.compile(r"<!-- wea:domain ([a-z0-9-]{1,63}) -->")
EMPTY = {"genesis": None, "entries": [], "commits": []}


def capture(api: Any, cutoff: datetime) -> dict[str, Any]:
    """Read the canonical journal and retain only its prefix through cutoff."""
    # Access imports Tide's historical replay helpers. Keep this import lazy.
    from ..access_github import GitHub, GitHubClient, Journal

    # Production uses the existing bounded Git transfer, not REST per object.
    reader = (
        GitHub(api.token)
        if isinstance(api, GitHubClient) and not isinstance(api, GitHub)
        else api
    )
    try:
        _, genesis, entries, commits = Journal(reader, verify_closure=False).read()
    finally:
        if reader is not api:
            reader.close()
    if genesis is None or timestamp(genesis["cutoff"]) > cutoff:
        return {"genesis": None, "entries": [], "commits": []}
    count = sum(timestamp(item["accepted_at"]) <= cutoff for item in entries)
    return {"genesis": genesis, "entries": entries[:count], "commits": commits[:count]}


def restore(snapshot: dict[str, Any], cutoff: datetime, previous: Any) -> Any:
    """Rebuild authority without a live clock or network and forbid history loss."""
    from ..access_control import replay
    from ..access_github import validate_genesis

    if type(snapshot) is not dict or set(snapshot) != set(EMPTY):
        raise ValueError("domain admission requires a complete Access snapshot")
    genesis, entries, commits = (snapshot[key] for key in EMPTY)
    if type(entries) is not list or type(commits) is not list:
        raise ValueError("Access snapshot entries and commits must be lists")
    if len(entries) != len(commits) or len(set(commits)) != len(commits):
        raise ValueError("Access snapshot commit sequence differs")
    if any(type(c) is not str or not re.fullmatch(r"[0-9a-f]{40}", c) for c in commits):
        raise ValueError("Access snapshot requires exact commit IDs")
    if previous and previous["genesis"] is not None:
        size = len(previous["entries"])
        if (
            genesis != previous["genesis"]
            or entries[:size] != previous["entries"]
            or commits[:size] != previous["commits"]
        ):
            raise ValueError("Access snapshot changed or lost retained history")
    if genesis is None:
        if entries or commits:
            raise ValueError("Access snapshot has decisions without genesis")
        return None
    # Historical data replay does not execute the old writer. Live grants still
    # require its exact installed closure in access_github.run/process.
    validate_genesis(genesis, verify_closure=False)
    if timestamp(genesis["cutoff"]) > cutoff or any(
        timestamp(entry["accepted_at"]) > cutoff for entry in entries
    ):
        raise ValueError("Access snapshot contains evidence after Tide cutoff")
    return replay(genesis, entries)


def scope(body: str, access: Any, at: datetime | None = None) -> Any:
    """The original Draft body, and thus its approved hash, owns task scope."""
    markers = [line for line in body.splitlines() if "<!-- wea:domain" in line]
    if len(markers) != 1 or not (match := SCOPE.fullmatch(markers[0])):
        raise ValueError("Draft requires one exact wea:domain scope line")
    selected = match[1]
    # A dash cannot be a Domain ID; valid IDs such as "none" stay domains.
    if selected == "-":
        return None
    if access is None:
        raise ValueError("Domain scope requires an activated Access registry")
    from ..initiatives import State

    if isinstance(access, State) and at is not None and at > access.activation_at:
        binding = [line for line in body.splitlines() if "<!-- wea:binding" in line]
        if len(binding) != 1 or not (revision := BINDING.fullmatch(binding[0])):
            raise ValueError("Draft requires one exact binding revision")
        record = access.binding(selected, at)
        if revision[1] != record.record_hash:
            raise ValueError("Draft binding differs at its authenticated source time")
        return {"domain_id": selected, "binding_revision": revision[1]}
    access.binding(selected, at) if isinstance(
        access, State
    ) else access.registry.domain(selected)
    return selected


def require(access: Any, domain_id: str | None, agent_id: str, at: datetime) -> None:
    if domain_id is None:
        return
    from ..initiatives import State

    expected = None
    if isinstance(domain_id, dict):
        expected = domain_id["binding_revision"]
        domain_id = domain_id["domain_id"]
    elif isinstance(access, State):
        # Legacy scope strings always retain the genesis binding.
        expected = access.groups[0].registry.domain(domain_id).record_hash
    if access is None or not any(
        grant.agent_id == agent_id
        and grant.domain_id == domain_id
        and grant.starts_at <= at < grant.ends_at
        and (
            expected is None
            or (isinstance(access, State) and access.grant_binding(grant) == expected)
        )
        for grant in access.grants
    ):
        raise ValueError(
            f"domain admission: {agent_id} needs active Access to {domain_id} "
            "at the source time"
        )


def admit(access: Any, domain_id: str | None, event: Any) -> None:
    """Gate entry, never payment or completion of an existing role obligation."""
    if event.kind in {"work_revision", "duel_join"}:
        require(access, domain_id, event.actor_id, event.effective_at)
    elif event.kind == "role_assignment":
        require(
            access, domain_id, event.payload["assigned_agent_id"], event.effective_at
        )


def initiative_scope(
    body: str, access: Any, at: datetime, registry: Any = None
) -> str | None:
    from ..initiatives import State

    # Old Draft bodies remain governed by their historical schema.
    if not isinstance(access, State) or at <= access.activation_at:
        return None
    lines = [line for line in body.splitlines() if "<!-- wea:initiative" in line]
    if not lines:
        return None
    if len(lines) != 1 or not (match := INITIATIVE.fullmatch(lines[0])):
        raise ValueError("Draft requires one exact initiative reference")
    steward = access.assignable(match[1], at)
    if (
        registry is not None
        and len(
            [
                b
                for b in registry.bindings
                if b.actor_kind == "agent"
                and b.subject_id == steward
                and b.active_at(at)
            ]
        )
        != 1
    ):
        raise ValueError("new assignment requires a canonically registered Steward")
    return match[1]


def batch_schema(snapshot: dict) -> str:
    from ..initiatives import SCHEMA as INITIATIVE_SCHEMA

    if type(snapshot) is not dict or set(snapshot) != set(EMPTY):
        raise ValueError("domain admission requires a complete Access snapshot")
    if type(snapshot["entries"]) is not list:
        raise ValueError("Access snapshot entries must be a list")
    return (
        REVISION_SCHEMA
        if any(
            e["schema"] == INITIATIVE_SCHEMA
            and e["decision"].get("effect") == "activate-policy"
            and e["decision"]["status"] == "recorded"
            for e in snapshot["entries"]
        )
        else SCHEMA
    )
