"""Create generation-zero genomes for canonically admitted new identities."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from wea_cli.config import resolve_agent
from wea_vnext.tide.ledger import git, load

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


def _git_text(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
    )
    return result.stdout.decode("utf-8")


def _canonical_has_path(root: Path, commit: str, path: str) -> bool:
    return bool(git(root, "ls-tree", "-r", "--name-only", commit, "--", path))


def _canonical_context(root: Path) -> CanonicalGenomeContext:
    commit = git(root, "rev-parse", CANONICAL_REF)
    engine, _ = load(root, commit)
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


def _validate(
    root: Path,
    actor: str | None,
    requested: list[str],
    context: CanonicalGenomeContext,
) -> list[GenesisTarget]:
    if not actor:
        raise ValueError("Set WEA_AGENT before initializing a genome.")
    if not requested:
        requested = [actor]
    if len(requested) != len(set(requested)):
        raise ValueError("Genome initialization targets must be unique.")
    if actor == AGENT0_ID:
        if not context.agent0_active:
            raise ValueError("The canonical Agent0 role is not active.")
    elif requested != [actor]:
        raise ValueError(
            "An agent may initialize only its own genome; "
            "Agent0 may initialize a cohort."
        )

    targets: list[GenesisTarget] = []
    for agent_id in requested:
        if not _AGENT_ID.fullmatch(agent_id) or agent_id == AGENT0_ID:
            raise ValueError(f"Invalid genome target: {agent_id}")
        target = context.targets.get(agent_id)
        if target is None:
            raise ValueError(
                f"{agent_id} is not an eligible new zero-balance identity "
                f"in canonical {CANONICAL_REF}."
            )
        relative = f"genomes/{agent_id}"
        if _canonical_has_path(root, context.commit, relative):
            raise ValueError(
                f"Canonical genome already exists for {agent_id}; "
                "init cannot reset it."
            )
        if (root / relative).exists():
            raise ValueError(
                f"Working-tree genome path already exists for {agent_id}; "
                "init cannot overwrite it."
            )
        targets.append(target)
    return targets


def _write(
    root: Path,
    context: CanonicalGenomeContext,
    targets: list[GenesisTarget],
) -> None:
    genomes = root / "genomes"
    staging = genomes / f".genome-init-{uuid.uuid4().hex}"
    staged: list[tuple[Path, Path]] = []
    moved: list[Path] = []
    try:
        staging.mkdir()
        for target in targets:
            source = staging / target.agent_id
            source.mkdir()
            (source / "AGENTS.local.md").write_text(context.template, encoding="utf-8")
            (source / "genome_meta.json").write_text(
                json.dumps(_metadata(target), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            staged.append((source, genomes / target.agent_id))
        for source, destination in staged:
            source.replace(destination)
            moved.append(destination)
    except Exception:
        for destination in moved:
            shutil.rmtree(destination)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def init(args) -> int:
    """Validate and create one or more new genomes."""
    from .cli import EXIT_DOMAIN_ERROR, EXIT_OK, EXIT_RUNTIME_ERROR, resolve_repo_root

    try:
        root = resolve_repo_root(args.root)
        context = _canonical_context(root)
        actor = resolve_agent(None)
        targets = _validate(root, actor, list(args.targets), context)
    except ValueError as exc:
        print(f"Genome initialization rejected: {exc}")
        return EXIT_DOMAIN_ERROR
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Genome initialization failed: {exc}")
        return EXIT_RUNTIME_ERROR

    paths = [f"genomes/{target.agent_id}/" for target in targets]
    if args.dry_run:
        print(f"Genome initialization valid at {context.commit} (dry run):")
        for path in paths:
            print(f"- {path}")
        return EXIT_OK
    try:
        _write(root, context, targets)
    except OSError as exc:
        print(f"Genome initialization failed without retained partial output: {exc}")
        return EXIT_RUNTIME_ERROR
    print(
        f"Initialized {len(targets)} generation-zero genome(s) "
        f"from {context.commit}:"
    )
    for path in paths:
        print(f"- {path}")
    return EXIT_OK
