"""Gene-level evolution loop with Release Sessions and sandbox validation.

Cycle:
  1. Full run → identify failed tasks
  2. Release Session: agents reflect → coordinator approves mutations (max 3)
  3. Apply mutations → sandbox validation (only failed tasks)
  4. Regression check (15 random passing tasks)
  5. Accept/reject → next generation

Usage:
    uv run python src/gene_evolve.py --arena                  # full evolution on arena
    uv run python src/gene_evolve.py --arena --max-gen 5      # quick test
    uv run python src/gene_evolve.py --arena --dry-run        # baseline only
    uv run python src/gene_evolve.py                          # BitGN API mode
"""

import json
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)

from src.config import AgentConfig
from src.fitness import compute_fitness
from src.genome import Genome, load_genome, save_genome
from src.history import load_history, save_history
from src.main import print_summary, run_benchmark
from src.trace import BenchmarkTrace, load_trace, save_trace

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"

GENOMES_DIR = Path(_PROJECT_ROOT) / "genomes"
HISTORY_DIR = GENOMES_DIR / "history"
PROVENANCE_FILE = GENOMES_DIR / "provenance.json"
TRACES_DIR = Path(_PROJECT_ROOT) / "traces"
STATE_FILE = Path(_PROJECT_ROOT) / "gene_evolution.json"

AGENT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
REGRESSION_SAMPLE_SIZE = 15


@dataclass
class GeneEvolutionState:
    current_gen: int = 0
    best_gen: int = 0
    best_score: float = 0.0
    mutations_accepted: int = 0
    mutations_rejected: int = 0
    history: list[dict] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    passing_ids: list[str] = field(default_factory=list)


def _load_state() -> GeneEvolutionState:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return GeneEvolutionState(**data)
    return GeneEvolutionState()


def _save_state(state: GeneEvolutionState) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2, ensure_ascii=False)


def _save_provenance(entry: dict) -> None:
    GENOMES_DIR.mkdir(parents=True, exist_ok=True)
    data = {"mutations": []}
    if PROVENANCE_FILE.exists():
        with open(PROVENANCE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    data["mutations"].append(entry)
    with open(PROVENANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _archive_genome(genome: Genome, gen: int) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    save_genome(genome, HISTORY_DIR / f"{genome.name}_gen_{gen:03d}.yaml")


def _make_genome_config() -> AgentConfig:
    return AgentConfig(
        use_genome=True,
        warmup=True,
        enrichment=True,
        step_validator=True,
        compress_history=True,
        defense_mode="soft_block",
        watchdog=True,
    )


def _run_eval(
    provider: str,
    config: AgentConfig,
    task_subset: list[str] | None,
    prompt_version: str,
    use_arena: bool,
) -> BenchmarkTrace:
    if use_arena:
        from src.arena import run_arena
        return run_arena(
            provider_name=provider,
            task_filter=task_subset,
            prompt_version=prompt_version,
            config=config,
        )
    else:
        return run_benchmark(
            provider_name=provider,
            task_filter=task_subset,
            prompt_version=prompt_version,
            config=config,
        )


def _backup_genomes() -> dict[str, Genome]:
    """Snapshot current genomes for rollback."""
    backup = {}
    for name in ("executor", "planner", "watchdog"):
        try:
            backup[name] = load_genome(name)
        except FileNotFoundError:
            pass
    return backup


def _restore_genomes(backup: dict[str, Genome]) -> None:
    """Restore genomes from backup."""
    for name, genome in backup.items():
        save_genome(genome)


def gene_evolve(
    max_generations: int = 50,
    task_subset: list[str] | None = None,
    dry_run: bool = False,
    use_arena: bool = False,
) -> None:
    """Run gene evolution with Release Sessions and sandbox validation."""
    GENOMES_DIR.mkdir(parents=True, exist_ok=True)
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    state = _load_state()
    history = load_history()
    config = _make_genome_config()

    mode = "ARENA (local)" if use_arena else "BENCHMARK (BitGN API)"
    print(f"\n{CLI_BLUE}=== BitGN Gene Evolution ({mode}) ==={CLI_CLR}")
    print(f"Agent: {AGENT_PROVIDER}")
    print(f"Models: action={config.action_model}, delib={config.deliberation_model}, "
          f"delib+complex={config.deliberation_complex_model}")
    print(f"Max generations: {max_generations}")
    if task_subset:
        print(f"Task subset: {', '.join(task_subset)}")
    print(f"State: gen={state.current_gen}, best={state.best_gen}, "
          f"score={state.best_score:.2%}")
    print()

    # --- Step 0: Full baseline ---
    if state.current_gen == 0:
        print(f"{CLI_YELLOW}--- Generation 0: FULL BASELINE ---{CLI_CLR}")

        for name in ("executor", "planner", "watchdog"):
            try:
                _archive_genome(load_genome(name), 0)
            except FileNotFoundError:
                pass

        baseline_trace = _run_eval(
            AGENT_PROVIDER, config, task_subset, "gene_000", use_arena,
        )
        save_trace(str(TRACES_DIR / "gene_000.json"), baseline_trace)
        history.ingest_trace(baseline_trace)
        save_history(history)

        fitness = compute_fitness(baseline_trace)
        state.best_score = baseline_trace.total_score
        state.best_gen = 0
        state.current_gen = 1
        state.failed_ids = [t.task_id for t in baseline_trace.traces if t.score < 1.0]
        state.passing_ids = [t.task_id for t in baseline_trace.traces if t.score >= 1.0]

        state.history.append({
            "gen": 0, "desc": "genome baseline", "gene": None,
            "score": baseline_trace.total_score, "delta": 0.0,
            "accepted": True, "regressed": [],
        })
        _save_state(state)

        print(f"\n{CLI_BLUE}Baseline: {fitness['score']:.2%} "
              f"({fitness['passed']}/{fitness['total']} passed){CLI_CLR}")
        print(f"Failed: {', '.join(state.failed_ids)}")
        print(f"Passing: {len(state.passing_ids)} tasks")
        print_summary(baseline_trace)

        if dry_run:
            print(f"\n{CLI_YELLOW}Dry run complete.{CLI_CLR}")
            return

    # --- Evolution loop ---
    for gen in range(state.current_gen, max_generations + 1):
        print(f"\n{CLI_YELLOW}{'='*60}")
        print(f"--- Generation {gen} ---")
        print(f"{'='*60}{CLI_CLR}")

        if not state.failed_ids:
            print(f"\n{CLI_GREEN}PERFECT SCORE — no failed tasks!{CLI_CLR}")
            break

        print(f"Sandbox: {len(state.failed_ids)} failed tasks")
        print(f"  {', '.join(state.failed_ids)}")

        # Load best trace for release session context
        best_trace = load_trace(str(TRACES_DIR / f"gene_{state.best_gen:03d}.json"))

        # === PHASE 1: Release Session ===
        print(f"\n{CLI_BLUE}Phase 1: Release Session{CLI_CLR}")
        from src.release_session import run_release_session

        session = run_release_session(
            best_trace,
            mutation_history=state.history,
        )

        if not session.approved:
            print(f"{CLI_RED}No mutations approved — agents found nothing actionable{CLI_CLR}")
            state.current_gen = gen + 1
            _save_state(state)
            continue

        # === PHASE 2: Apply mutations ===
        print(f"\n{CLI_BLUE}Phase 2: Apply {len(session.approved)} mutation(s){CLI_CLR}")
        backup = _backup_genomes()

        for m in session.approved:
            genome = load_genome(m.agent)
            if m.gene_name in genome.genes:
                print(f"  {m.agent}/{m.gene_name}: {m.description[:60]}")
                genome.set_gene_content(m.gene_name, m.new_content)
                genome.generation = gen
                save_genome(genome)
            else:
                print(f"  {CLI_RED}SKIP: gene '{m.gene_name}' not in {m.agent} genome{CLI_CLR}")

        # === PHASE 3: Sandbox validation (failed tasks only) ===
        print(f"\n{CLI_BLUE}Phase 3: Sandbox — {len(state.failed_ids)} failed tasks{CLI_CLR}")
        sandbox_trace = _run_eval(
            AGENT_PROVIDER, config, state.failed_ids, f"gene_{gen:03d}_sandbox", use_arena,
        )
        save_trace(str(TRACES_DIR / f"gene_{gen:03d}_sandbox.json"), sandbox_trace)

        # Check improvements
        old_scores = {t.task_id: t.score for t in best_trace.traces}
        new_scores = {t.task_id: t.score for t in sandbox_trace.traces}

        improved = []
        for tid in state.failed_ids:
            old = old_scores.get(tid, 0)
            new = new_scores.get(tid, 0)
            delta = new - old
            status = f"{CLI_GREEN}+{delta:.2f}{CLI_CLR}" if delta > 0 else (
                f"{CLI_RED}{delta:.2f}{CLI_CLR}" if delta < 0 else "=")
            print(f"  {tid}: {old:.2f} → {new:.2f} {status}")
            if new > old:
                improved.append(tid)

        if not improved:
            print(f"\n{CLI_RED}No improvements — rolling back{CLI_CLR}")
            _restore_genomes(backup)
            state.history.append({
                "gen": gen, "desc": "; ".join(m.description[:40] for m in session.approved),
                "gene": ", ".join(m.gene_name for m in session.approved),
                "score": state.best_score, "delta": 0.0,
                "accepted": False, "regressed": [], "reason": "no sandbox improvement",
            })
            state.mutations_rejected += 1
            state.current_gen = gen + 1
            _save_state(state)
            continue

        print(f"\n  {CLI_GREEN}Improved: {', '.join(improved)}{CLI_CLR}")

        # === PHASE 4: Regression check (random passing sample) ===
        sample_size = min(REGRESSION_SAMPLE_SIZE, len(state.passing_ids))
        if sample_size > 0:
            regression_sample = random.sample(state.passing_ids, sample_size)
            print(f"\n{CLI_BLUE}Phase 4: Regression — {sample_size} passing tasks{CLI_CLR}")

            regression_trace = _run_eval(
                AGENT_PROVIDER, config, regression_sample, f"gene_{gen:03d}_regr", use_arena,
            )

            regressed = []
            for t in regression_trace.traces:
                if t.score < 1.0 and t.task_id in state.passing_ids:
                    regressed.append(t.task_id)
                    print(f"  {CLI_YELLOW}REGRESSED: {t.task_id} ({t.score:.2f}) → added to sandbox{CLI_CLR}")

            if regressed:
                # Soft policy: accept mutations, move regressions to failed pool
                print(f"\n{CLI_YELLOW}{len(regressed)} regression(s) — accepting anyway, "
                      f"adding to next sandbox{CLI_CLR}")
                for tid in regressed:
                    if tid in state.passing_ids:
                        state.passing_ids.remove(tid)
                    if tid not in state.failed_ids:
                        state.failed_ids.append(tid)
            else:
                print(f"  {CLI_GREEN}No regressions!{CLI_CLR}")

        # === PHASE 5: Accept ===
        state.mutations_accepted += 1
        state.best_gen = gen

        # Update failed/passing lists
        newly_passing = [tid for tid in state.failed_ids if new_scores.get(tid, 0) >= 1.0]
        for tid in newly_passing:
            state.failed_ids.remove(tid)
            state.passing_ids.append(tid)

        # Compute new overall score estimate
        total_tasks = len(state.failed_ids) + len(state.passing_ids)
        estimated_score = len(state.passing_ids) / total_tasks if total_tasks else 0
        state.best_score = estimated_score

        # Archive genomes
        for name in ("executor", "planner", "watchdog"):
            try:
                _archive_genome(load_genome(name), gen)
            except FileNotFoundError:
                pass

        # Save full sandbox trace as generation trace
        save_trace(str(TRACES_DIR / f"gene_{gen:03d}.json"), sandbox_trace)

        # Provenance
        for m in session.approved:
            _save_provenance({
                "generation": gen, "agent": m.agent, "gene": m.gene_name,
                "description": m.description,
                "target_failures": m.target_failures,
                "fixed": [tid for tid in m.target_failures if tid in newly_passing],
                "regressed": [],
                "timestamp": sandbox_trace.timestamp,
            })

        state.history.append({
            "gen": gen,
            "desc": "; ".join(m.description[:40] for m in session.approved),
            "gene": ", ".join(m.gene_name for m in session.approved),
            "score": estimated_score,
            "delta": estimated_score - (state.history[-1]["score"] if state.history else 0),
            "accepted": True, "regressed": [],
            "improved": improved, "newly_passing": newly_passing,
        })
        _save_state(state)

        print(f"\n{CLI_GREEN}=== ACCEPTED ==={CLI_CLR}")
        print(f"  Improved: {', '.join(improved)}")
        print(f"  Newly passing: {', '.join(newly_passing) or 'none (partial improvements)'}")
        print(f"  Remaining failures: {len(state.failed_ids)}")
        print(f"  Estimated score: {estimated_score:.2%}")

        total = state.mutations_accepted + state.mutations_rejected
        rate = state.mutations_accepted / total * 100 if total else 0
        print(f"  Progress: {state.mutations_accepted} accepted, "
              f"{state.mutations_rejected} rejected ({rate:.0f}%)")

    # Final report
    print(f"\n{CLI_BLUE}{'='*60}")
    print("GENE EVOLUTION COMPLETE")
    print(f"{'='*60}{CLI_CLR}")
    print(f"Best generation: gen_{state.best_gen:03d}")
    print(f"Estimated score: {state.best_score:.2%}")
    print(f"Remaining failures: {len(state.failed_ids)}")
    if state.failed_ids:
        print(f"  {', '.join(state.failed_ids)}")
    print(f"Mutations: {state.mutations_accepted} accepted, "
          f"{state.mutations_rejected} rejected")


def main() -> None:
    max_gen = 50
    task_subset = None
    dry_run = False
    use_arena = False

    args = sys.argv[1:]
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
        elif args[i] == "--arena":
            use_arena = True
            i += 1
        else:
            print(f"Unknown arg: {args[i]}")
            i += 1

    gene_evolve(
        max_generations=max_gen,
        task_subset=task_subset,
        dry_run=dry_run,
        use_arena=use_arena,
    )


if __name__ == "__main__":
    main()
