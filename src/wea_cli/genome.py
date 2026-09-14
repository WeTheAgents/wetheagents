"""Create generation-zero genomes for canonically admitted new identities."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from wea_cli.config import resolve_agent
from wea_cli.genome_context import (
    _AGENT_ID,
    AGENT0_ID,
    CANONICAL_REF,
    CanonicalGenomeContext,
    GenesisTarget,
    _canonical_context,
    _canonical_path_ever_existed,
    _metadata,
)

EXIT_OK = 0
EXIT_DOMAIN_ERROR = 1
EXIT_RUNTIME_ERROR = 2


def _resolve_repo_root(root_arg: str | None) -> Path:
    if root_arg:
        root = Path(root_arg).resolve()
        if (root / "ledger" / "balances.json").exists():
            return root
        raise FileNotFoundError(f"Cannot find ledger/balances.json under: {root}")
    current = Path.cwd().resolve()
    for candidate in (current, *current.parents):
        if (candidate / "ledger" / "balances.json").exists():
            return candidate
    raise FileNotFoundError(
        "Cannot auto-detect repository root (ledger/balances.json not found)."
    )


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
        if _canonical_path_ever_existed(root, context.commit, relative):
            raise ValueError(
                f"Canonical genome exists or existed for {agent_id}; "
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
    try:
        root = _resolve_repo_root(args.root)
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
