"""Read and validate canonical context for generation-zero genome creation."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from wea_vnext.tide.replay import Replay, ReplayError, canonical

AGENT0_ID = "agent0@system"
CANONICAL_REF = "origin/main"
TEMPLATE_PATH = "genomes/base/AGENTS.local.template.md"
_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*@[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class GenesisTarget:
    agent_id: str
    admitted_at: datetime


@dataclass(frozen=True)
class CanonicalGenomeContext:
    commit: str
    template: str
    targets: dict[str, GenesisTarget]
    agent0_active: bool


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True
    )
    return result.stdout.decode("utf-8").strip()


def _git_text(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True
    )
    return result.stdout.decode("utf-8")


def _read(root: Path, commit: str, path: str) -> Any:
    raw = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        capture_output=True,
        check=True,
    ).stdout
    data = json.loads(raw)
    if canonical(data) + b"\n" != raw:
        raise ReplayError(f"canonical JSON is required: {path}")
    return data


def load(root: Path, commit: str) -> Replay:
    """Replay retained Tide JSON without importing its writer-capable module."""
    bootstrap = "ledger/vnext/tide-bootstrap.json"
    journal = "ledger/vnext/tides/"
    state = "ledger/vnext/tide-state.json"
    engine = Replay(_read(root, commit, bootstrap))
    paths = git(
        root, "ls-tree", "-r", "--name-only", commit, "--", journal
    ).splitlines()
    for index, path in enumerate(paths, 1):
        if path != f"{journal}{index:016d}.json":
            raise ReplayError("canonical Tide history has a gap or extra path")
        engine.apply(_read(root, commit, path))
    if engine.state() != _read(root, commit, state):
        raise ReplayError("canonical projection does not match task replay")
    return engine


def _canonical_path_ever_existed(root: Path, commit: str, path: str) -> bool:
    if git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise ValueError(
            "Complete origin/main history is required to prove that a genome "
            "never existed."
        )
    return bool(git(root, "log", "-1", "--format=%H", commit, "--", path))


def _canonical_context(root: Path) -> CanonicalGenomeContext:
    commit = git(root, "rev-parse", CANONICAL_REF)
    engine = load(root, commit)
    state = engine.state()

    new_agents: dict[str, bool] = {}
    for request in state["participants"].values():
        for item in request["agents"]:
            agent_id = item["agent_id"]
            preserve = item["preserve_balance"]
            if agent_id in new_agents and new_agents[agent_id] != preserve:
                raise ValueError(f"conflicting admission history for {agent_id}")
            new_agents[agent_id] = preserve

    active_bindings = {
        binding.subject_id: binding
        for binding in engine.registry.bindings
        if binding.actor_kind == "agent" and binding.effective_until is None
    }
    targets = {
        agent_id: GenesisTarget(agent_id, active_bindings[agent_id].effective_from)
        for agent_id, preserve in new_agents.items()
        if not preserve
        and agent_id in active_bindings
        and state["balances"].get(agent_id) == 0
    }
    agent0_active = any(
        binding.actor_kind == "agent0"
        and binding.subject_id == AGENT0_ID
        and binding.effective_until is None
        for binding in engine.registry.bindings
    )
    template = _git_text(root, "show", f"{commit}:{TEMPLATE_PATH}")
    if not template.strip():
        raise ValueError("canonical genome template is empty")
    return CanonicalGenomeContext(commit, template, targets, agent0_active)


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _metadata(target: GenesisTarget) -> dict[str, object]:
    created_at = _timestamp(target.admitted_at)
    return {
        "agent_id": target.agent_id,
        "generation": 0,
        "parent": None,
        "created_at": created_at,
        "last_snapshot": created_at,
        "role": "unassigned",
        "fitness": {
            "tasks_completed": 0,
            "tasks_created": 0,
            "initiative_ratio": None,
            "acceptance_rate": None,
            "rework_rate": None,
            "avg_time_in_stage_hours": None,
            "zero_code_ratio": None,
            "review_quality": None,
            "composite_score": None,
            "total_earned": 0,
            "total_minted": 0,
            "gauntlet_slots": 0,
            "total_income": 0,
        },
        "lineage": [],
        "mutations": [],
    }
