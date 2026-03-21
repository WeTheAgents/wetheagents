"""Evolution loop orchestrator for BitGN agent prompt self-improvement.

Usage:
    uv run python src/evolve.py                      # full evolution loop
    uv run python src/evolve.py --max-gen 5           # quick test (5 generations)
    uv run python src/evolve.py --subset t01,t02,t03  # iterate on task subset
    uv run python src/evolve.py --dry-run             # single baseline run, no mutation
    uv run python src/evolve.py --weak                # start from weak baseline
    uv run python src/evolve.py --blind               # blind mode (no score feedback)
"""

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field

# Ensure project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)

from src.config import DEFAULT_CONFIG, AgentConfig
from src.fitness import compute_fitness, should_accept
from src.history import load_history, save_history
from src.main import print_summary, run_benchmark
from src.prompts import SYSTEM_PROMPT_TEMPLATE, WEAK_BASELINE_PROMPT
from src.redteam import RedTeam
from src.trace import load_trace, save_trace

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"

# Directories for artifacts
PROMPTS_DIR = os.path.join(_PROJECT_ROOT, "prompts")
TRACES_DIR = os.path.join(_PROJECT_ROOT, "traces")
STATE_FILE = os.path.join(_PROJECT_ROOT, "evolution.json")

# Default agent provider
AGENT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")


@dataclass
class EvolutionState:
    current_gen: int = 0
    best_gen: int = 0
    best_score: float = 0.0
    best_prompt_file: str = ""
    mutations_accepted: int = 0
    mutations_rejected: int = 0
    history: list[dict] = field(default_factory=list)


def load_state() -> EvolutionState:
    """Load evolution state from JSON, or create fresh."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return EvolutionState(**data)
    return EvolutionState()


def save_state(state: EvolutionState) -> None:
    """Save evolution state to JSON."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2, ensure_ascii=False)


def prompt_path(gen: int) -> str:
    return os.path.join(PROMPTS_DIR, f"gen_{gen:03d}.txt")


def trace_path(gen: int) -> str:
    return os.path.join(TRACES_DIR, f"gen_{gen:03d}.json")


def save_prompt(path: str, prompt: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)


def load_prompt(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def evolve(
    max_generations: int = 83,
    task_subset: list[str] | None = None,
    dry_run: bool = False,
    weak_baseline: str | None = None,
    blind: bool = False,
    config: AgentConfig | None = None,
) -> None:
    """Run the evolution loop.

    Args:
        max_generations: Maximum number of mutation generations.
        task_subset: Optional list of task_ids for quick iteration.
        dry_run: If True, run baseline only (no mutation).
        weak_baseline: If provided, use this prompt as gen_000 instead of the tuned one.
        blind: If True, use blind review mode (no score feedback to red team).
        config: Optional AgentConfig for feature flags during benchmark runs.
    """
    config = config or DEFAULT_CONFIG
    os.makedirs(PROMPTS_DIR, exist_ok=True)
    os.makedirs(TRACES_DIR, exist_ok=True)

    state = load_state()
    redteam = RedTeam()
    history = load_history()

    mode_label = "BLIND" if blind else "SCORE-DRIVEN"
    print(f"\n{CLI_BLUE}=== BitGN Evolution Loop ({mode_label}) ==={CLI_CLR}")
    print(f"Agent: {AGENT_PROVIDER}")
    print(f"Max generations: {max_generations}")
    if task_subset:
        print(f"Task subset: {', '.join(task_subset)}")
    h_stats = history.stats()
    print(f"History: {h_stats['total']} records, {h_stats['unique_tasks']} unique tasks")
    print(f"State: gen={state.current_gen}, best={state.best_gen}, "
          f"score={state.best_score:.2%}")
    print()

    # --- Step 0: Baseline (gen_000) ---
    if state.current_gen == 0:
        print(f"{CLI_YELLOW}--- Generation 0: BASELINE ---{CLI_CLR}")
        baseline_prompt = weak_baseline if weak_baseline else SYSTEM_PROMPT_TEMPLATE
        save_prompt(prompt_path(0), baseline_prompt)

        baseline_trace = run_benchmark(
            provider_name=AGENT_PROVIDER,
            prompt_template=baseline_prompt,
            task_filter=task_subset,
            prompt_version="gen_000",
            config=config,
        )
        save_trace(trace_path(0), baseline_trace)
        history.ingest_trace(baseline_trace)
        save_history(history)

        state.best_score = baseline_trace.total_score
        state.best_gen = 0
        state.best_prompt_file = prompt_path(0)
        state.current_gen = 1

        fitness = compute_fitness(baseline_trace)
        print(f"\n{CLI_BLUE}Baseline: {fitness['score']:.2%} "
              f"({fitness['passed']}/{fitness['total']} passed, "
              f"avg {fitness['avg_steps']:.1f} steps){CLI_CLR}")

        baseline_desc = ("weak baseline (no trust model, no injection defense)"
                         if weak_baseline else
                         "tuned baseline (trust model + injection defense)")
        state.history.append({
            "gen": 0,
            "desc": baseline_desc,
            "score": baseline_trace.total_score,
            "delta": 0.0,
            "accepted": True,
            "regressed": [],
        })

        save_state(state)
        print_summary(baseline_trace)

        if dry_run:
            print(f"\n{CLI_YELLOW}Dry run complete. Baseline saved.{CLI_CLR}")
            return

    # --- Evolution loop ---
    for gen in range(state.current_gen, max_generations + 1):
        print(f"\n{CLI_YELLOW}{'='*60}")
        print(f"--- Generation {gen} ---")
        print(f"{'='*60}{CLI_CLR}")

        # Load current best
        best_prompt = load_prompt(prompt_path(state.best_gen))
        best_trace = load_trace(trace_path(state.best_gen))

        # Check if already perfect
        failed = [t for t in best_trace.traces if t.score < 1.0]
        if not failed:
            print(f"\n{CLI_GREEN}PERFECT SCORE at gen {state.best_gen} — "
                  f"evolution complete!{CLI_CLR}")
            break

        print(f"Current best: gen_{state.best_gen:03d} = {state.best_score:.2%}")
        print(f"Failed tasks: {', '.join(t.task_id for t in failed)}")

        # REDTEAM: analyze failures, generate mutation
        use_v2 = config.redteam_version == "v2"
        started = time.time()
        try:
            if blind:
                new_prompt, desc = redteam.blind_review(
                    best_prompt, best_trace.traces, history, state.history
                )
                if "NO_MUTATION_NEEDED" in desc:
                    print(f"  {CLI_GREEN}Red team: no mutation needed{CLI_CLR}")
                    break
            elif use_v2:
                new_prompt, desc = redteam.analyze_and_mutate_v2(
                    best_prompt, failed, state.history
                )
            else:
                new_prompt, desc = redteam.analyze_and_mutate(
                    best_prompt, failed, state.history
                )
        except Exception as e:
            print(f"{CLI_RED}Red team error: {e}{CLI_CLR}")
            state.current_gen = gen + 1
            save_state(state)
            continue

        print(f"  Mutation: {desc} ({time.time() - started:.1f}s)")
        save_prompt(prompt_path(gen), new_prompt)

        # VALIDATE: run benchmark with mutated prompt
        print(f"\n  Validating gen_{gen:03d}...")
        new_trace = run_benchmark(
            provider_name=AGENT_PROVIDER,
            prompt_template=new_prompt,
            task_filter=task_subset,
            prompt_version=f"gen_{gen:03d}",
            config=config,
        )
        save_trace(trace_path(gen), new_trace)
        history.ingest_trace(new_trace)
        save_history(history)

        new_fitness = compute_fitness(new_trace)

        # ACCEPT/REJECT
        accepted, reason = should_accept(new_trace, best_trace)

        state.history.append({
            "gen": gen,
            "desc": desc,
            "score": new_trace.total_score,
            "delta": new_trace.total_score - best_trace.total_score,
            "accepted": accepted,
            "regressed": [] if accepted else [
                t.task_id for t in best_trace.traces
                if t.score >= 1.0 and any(
                    ct.task_id == t.task_id and ct.score < 1.0
                    for ct in new_trace.traces
                )
            ],
        })

        if accepted:
            state.best_gen = gen
            state.best_score = new_trace.total_score
            state.best_prompt_file = prompt_path(gen)
            state.mutations_accepted += 1
            print(f"\n  {CLI_GREEN}ACCEPTED: {desc}{CLI_CLR}")
            print(f"  {CLI_GREEN}Score: {new_fitness['score']:.2%} "
                  f"({new_fitness['passed']}/{new_fitness['total']}) — {reason}{CLI_CLR}")
        else:
            state.mutations_rejected += 1
            print(f"\n  {CLI_RED}REJECTED: {desc}{CLI_CLR}")
            print(f"  {CLI_RED}Score: {new_fitness['score']:.2%} — {reason}{CLI_CLR}")

        state.current_gen = gen + 1
        save_state(state)

        print_summary(new_trace)

        # Progress report
        total_mutations = state.mutations_accepted + state.mutations_rejected
        accept_rate = (state.mutations_accepted / total_mutations * 100
                       if total_mutations else 0)
        print(f"\n  Progress: {state.mutations_accepted} accepted, "
              f"{state.mutations_rejected} rejected "
              f"({accept_rate:.0f}% acceptance rate)")

    # Final report
    print(f"\n{CLI_BLUE}{'='*60}")
    print("EVOLUTION COMPLETE")
    print(f"{'='*60}{CLI_CLR}")
    print(f"Best generation: gen_{state.best_gen:03d}")
    print(f"Best score: {state.best_score:.2%}")
    print(f"Prompt file: {state.best_prompt_file}")
    print(f"Mutations: {state.mutations_accepted} accepted, "
          f"{state.mutations_rejected} rejected")


def main() -> None:
    from src.main import _parse_config_from_args

    max_gen = 83
    task_subset = None
    dry_run = False
    use_weak = False
    use_blind = False

    args = sys.argv[1:]
    args, config = _parse_config_from_args(args)

    i = 0
    while i < len(args):
        if args[i] == "--max-gen" and i + 1 < len(args):
            max_gen = int(args[i + 1])
            i += 2
        elif args[i].startswith("--max-gen="):
            max_gen = int(args[i].split("=", 1)[1])
            i += 1
        elif args[i] == "--subset" and i + 1 < len(args):
            task_subset = args[i + 1].split(",")
            i += 2
        elif args[i].startswith("--subset="):
            task_subset = args[i].split("=", 1)[1].split(",")
            i += 1
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        elif args[i] == "--weak":
            use_weak = True
            i += 1
        elif args[i] == "--blind":
            use_blind = True
            i += 1
        else:
            print(f"Unknown arg: {args[i]}")
            i += 1

    evolve(
        max_generations=max_gen,
        task_subset=task_subset,
        dry_run=dry_run,
        weak_baseline=WEAK_BASELINE_PROMPT if use_weak else None,
        blind=use_blind,
        config=config,
    )


if __name__ == "__main__":
    main()
