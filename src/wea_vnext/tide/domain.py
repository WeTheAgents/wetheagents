"""Domain admission around the immutable task executor, with retained Access."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .records import timestamp

SCHEMA = "wea-tide-batch-3"
SCOPE = re.compile(r"<!-- wea:domain ([a-z][a-z0-9-]*) -->")
EMPTY = {"genesis": None, "entries": [], "commits": []}


def capture(api: Any, cutoff: datetime) -> dict[str, Any]:
    """Read the canonical journal and retain only its prefix through cutoff."""
    # Access imports Tide's historical replay helpers. Keep this import lazy.
    from ..access_github import Journal

    _, genesis, entries, commits = Journal(api, verify_closure=False).read()
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


def scope(body: str, access: Any) -> str | None:
    """The original Draft body, and thus its approved hash, owns task scope."""
    markers = [line for line in body.splitlines() if "<!-- wea:domain" in line]
    if len(markers) != 1 or not (match := SCOPE.fullmatch(markers[0])):
        raise ValueError("Draft requires one exact wea:domain scope line")
    selected = match[1]
    if selected == "none":
        return None
    if access is None:
        raise ValueError("Domain scope requires an activated Access registry")
    access.registry.domain(selected)
    return selected


def require(access: Any, domain_id: str | None, agent_id: str, at: datetime) -> None:
    if domain_id is None:
        return
    if access is None or not any(
        grant.agent_id == agent_id
        and grant.domain_id == domain_id
        and grant.starts_at <= at < grant.ends_at
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
