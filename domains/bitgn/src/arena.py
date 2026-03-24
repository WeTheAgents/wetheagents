"""Local Arena — training ground for BitGN agent.

Runs agent against local vaults with custom tasks and scoring.
Returns BenchmarkTrace compatible with evolve.py.

Usage:
    uv run python src/arena.py                     # run all arena tasks
    uv run python src/arena.py inj-email-01        # run specific task
    uv run python src/arena.py --category injection # run category
    uv run python src/arena.py --provider anthropic # switch provider
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from dataclasses import dataclass

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)
# Fix Windows cp1251 encoding errors — LLM output may contain arbitrary Unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")

from src.config import DEFAULT_CONFIG, AgentConfig
from src.prompts import build_system_prompt
from src.scorer import ScoringCriteria, score_task
from src.tools import local_dispatcher
from src.trace import BenchmarkTrace, TaskTrace
from src.vault_runtime import LocalVaultRuntime

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"

ARENA_DIR = os.path.join(_PROJECT_ROOT, "arena")
TASKS_DIR = os.path.join(ARENA_DIR, "tasks")
VAULTS_DIR = os.path.join(ARENA_DIR, "vaults")


@dataclass
class ArenaTask:
    """A single arena task definition."""
    id: str
    category: str
    difficulty: str
    instruction: str
    vault: str  # vault directory name under arena/vaults/
    scoring: ScoringCriteria

    @classmethod
    def from_file(cls, path: str) -> ArenaTask:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls(
            id=d["id"],
            category=d.get("category", "misc"),
            difficulty=d.get("difficulty", "medium"),
            instruction=d["instruction"],
            vault=d["vault"],
            scoring=ScoringCriteria.from_dict(d.get("scoring", {})),
        )


def load_arena_tasks(
    task_filter: list[str] | None = None,
    category_filter: str | None = None,
) -> list[ArenaTask]:
    """Load task definitions from arena/tasks/*.json."""
    if not os.path.isdir(TASKS_DIR):
        print(f"{CLI_RED}Arena tasks directory not found: {TASKS_DIR}{CLI_CLR}")
        return []

    tasks = []
    for fname in sorted(os.listdir(TASKS_DIR)):
        if not fname.endswith(".json"):
            continue
        try:
            task = ArenaTask.from_file(os.path.join(TASKS_DIR, fname))
        except Exception as e:
            print(f"{CLI_YELLOW}Warning: failed to load {fname}: {e}{CLI_CLR}")
            continue

        if task_filter and task.id not in task_filter:
            continue
        if category_filter and task.category != category_filter:
            continue
        tasks.append(task)

    return tasks


def run_arena(
    provider_name: str,
    prompt_template: str | None = None,
    task_filter: list[str] | None = None,
    category_filter: str | None = None,
    prompt_version: str = "default",
    config: AgentConfig | None = None,
) -> BenchmarkTrace:
    """Run all arena tasks locally.

    Returns BenchmarkTrace — same format as run_benchmark() for evolve.py compatibility.
    """
    config = config or DEFAULT_CONFIG
    from src.main import create_provider

    provider = create_provider(provider_name)
    prompt_text = prompt_template or ""

    trace = BenchmarkTrace(
        provider=provider.provider_name(),
        prompt_version=prompt_version,
        prompt_text=prompt_text,
    )

    tasks = load_arena_tasks(task_filter, category_filter)
    if not tasks:
        print(f"{CLI_RED}No arena tasks found.{CLI_CLR}")
        return trace

    print(f"\n{CLI_BLUE}=== Arena: {len(tasks)} tasks ==={CLI_CLR}")
    print(f"Provider: {provider_name}")
    if category_filter:
        print(f"Category: {category_filter}")
    print()

    for task in tasks:
        print("=" * 60)
        print(f"TASK: {task.id} [{task.category}/{task.difficulty}]")
        print(f"Instruction: {task.instruction}\n")

        vault_dir = os.path.join(VAULTS_DIR, task.vault)
        if not os.path.isdir(vault_dir):
            print(f"{CLI_RED}Vault not found: {vault_dir}{CLI_CLR}")
            task_trace = TaskTrace(
                task_id=task.id,
                instruction=task.instruction,
                error=f"Vault not found: {task.vault}",
            )
            trace.traces.append(task_trace)
            continue

        # Create vault runtime and dispatcher
        vault = LocalVaultRuntime(vault_dir)
        dispatcher = local_dispatcher(vault)

        # Build system prompt
        system_prompt = build_system_prompt(task.instruction, prompt_template)

        try:
            if provider_name == "anthropic":
                from src.agent import run_agent_anthropic
                task_trace = run_agent_anthropic(
                    provider, dispatcher, task.instruction,
                    system_prompt_override=system_prompt,
                    config=config,
                )
            else:
                from src.agent import run_agent_openai
                task_trace = run_agent_openai(
                    provider, dispatcher, task.instruction,
                    system_prompt_override=system_prompt,
                    config=config,
                )
        except Exception as e:
            print(f"{CLI_RED}Agent error: {e}{CLI_CLR}")
            import traceback
            traceback.print_exc()
            task_trace = TaskTrace(
                task_id=task.id,
                instruction=task.instruction,
                error=str(e),
            )
            trace.traces.append(task_trace)
            vault.cleanup()
            continue

        # Score locally
        agent_answer = None
        agent_refs = []
        if vault.answer_data:
            agent_answer = vault.answer_data.get("answer")
            agent_refs = vault.answer_data.get("refs", [])

        score, detail = score_task(task.scoring, agent_answer, agent_refs, vault)

        task_trace.task_id = task.id
        task_trace.score = score
        task_trace.score_detail = detail

        style = CLI_GREEN if score >= 1.0 else CLI_RED
        explain = textwrap.indent("\n".join(detail), "  ")
        print(f"\n{style}Score: {score:.2f}\n{explain}\n{CLI_CLR}")

        trace.traces.append(task_trace)
        vault.cleanup()

    trace.finalize()
    return trace


def print_arena_summary(trace: BenchmarkTrace) -> None:
    """Print score summary."""
    if not trace.traces:
        return

    print("\n" + "=" * 60)
    print("ARENA RESULTS:")
    for t in trace.traces:
        style = CLI_GREEN if t.score >= 1.0 else CLI_RED
        print(f"  {t.task_id}: {style}{t.score:.2f}{CLI_CLR}")

    pct = trace.total_score * 100.0
    style = CLI_GREEN if trace.total_score >= 0.80 else CLI_RED
    print(f"\n  FINAL: {style}{pct:.2f}%{CLI_CLR} "
          f"({len(trace.passed_tasks)}/{len(trace.traces)} passed)")


def main() -> None:
    from src.main import _parse_config_from_args

    task_filter: list[str] = []
    category_filter: str | None = None
    provider_name = os.getenv("LLM_PROVIDER", "openai")

    args = sys.argv[1:]
    args, config = _parse_config_from_args(args)

    i = 0
    while i < len(args):
        if args[i] == "--provider" and i + 1 < len(args):
            provider_name = args[i + 1]
            i += 2
        elif args[i].startswith("--provider="):
            provider_name = args[i].split("=", 1)[1]
            i += 1
        elif args[i] == "--category" and i + 1 < len(args):
            category_filter = args[i + 1]
            i += 2
        elif args[i].startswith("--category="):
            category_filter = args[i].split("=", 1)[1]
            i += 1
        else:
            task_filter.append(args[i])
            i += 1

    trace = run_arena(
        provider_name=provider_name,
        task_filter=task_filter if task_filter else None,
        category_filter=category_filter,
        config=config,
    )

    print_arena_summary(trace)


if __name__ == "__main__":
    main()
