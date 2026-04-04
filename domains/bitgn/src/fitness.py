"""Fitness evaluation and zero-regression checking for prompt evolution."""

from __future__ import annotations

from statistics import mean

from src.trace import BenchmarkTrace


def compute_fitness(trace: BenchmarkTrace) -> dict:
    """Compute fitness metrics from a benchmark trace.

    Returns dict with:
        score: average score across all tasks (0.0 to 1.0)
        passed: number of tasks with score == 1.0
        failed: number of tasks with score < 1.0
        total: total number of tasks
        avg_steps: average steps per task (lower is better)
    """
    if not trace.traces:
        return {"score": 0.0, "passed": 0, "failed": 0, "total": 0, "avg_steps": 0.0}

    return {
        "score": trace.total_score,
        "passed": len(trace.passed_tasks),
        "failed": len(trace.failed_tasks),
        "total": len(trace.traces),
        "avg_steps": mean(t.total_steps for t in trace.traces) if trace.traces else 0.0,
    }


def check_zero_regression(
    candidate: BenchmarkTrace,
    baseline: BenchmarkTrace,
) -> tuple[bool, list[str]]:
    """Check that no previously-passing task has regressed.

    A mutation is ONLY accepted if every task that passed in baseline
    also passes in candidate. New tasks passing is a bonus; existing
    tasks failing is a hard reject.

    Args:
        candidate: The new benchmark trace (with mutated prompt).
        baseline: The best-so-far benchmark trace.

    Returns:
        (passed, regressed_task_ids):
            passed: True if zero-regression holds.
            regressed_task_ids: list of task_ids that regressed.
    """
    baseline_passed = set(baseline.passed_tasks)
    candidate_passed = set(candidate.passed_tasks)
    regressed = sorted(baseline_passed - candidate_passed)
    return (len(regressed) == 0, regressed)


def should_accept(
    candidate: BenchmarkTrace,
    baseline: BenchmarkTrace,
) -> tuple[bool, str]:
    """Decide whether to accept a mutation.

    Acceptance policy:
    1. Zero-regression: no previously-passing task can fail
    2. Score must be >= baseline (not strictly worse)
    3. On equal score, prefer fewer avg steps

    Returns:
        (accepted, reason)
    """
    passed, regressed = check_zero_regression(candidate, baseline)
    if not passed:
        return False, f"regression on tasks: {', '.join(regressed)}"

    c_fitness = compute_fitness(candidate)
    b_fitness = compute_fitness(baseline)

    if c_fitness["score"] > b_fitness["score"]:
        delta = c_fitness["score"] - b_fitness["score"]
        return True, f"score improved by {delta:+.2%}"

    if c_fitness["score"] == b_fitness["score"]:
        if c_fitness["avg_steps"] < b_fitness["avg_steps"]:
            return True, "same score, fewer steps"
        if c_fitness["avg_steps"] == b_fitness["avg_steps"]:
            return True, "same score and steps (neutral)"
        return False, "same score but more steps"

    return False, f"score decreased: {c_fitness['score']:.2%} < {b_fitness['score']:.2%}"


def should_accept_gene(
    candidate: BenchmarkTrace,
    baseline: BenchmarkTrace,
    target_failures: list[str],
) -> tuple[bool, str]:
    """Decide whether to accept a gene-level mutation.

    Stricter than should_accept: requires both zero-regression AND
    at least one target failure to improve.

    Args:
        candidate: Benchmark trace with mutated gene.
        baseline: Benchmark trace with original gene.
        target_failures: Task IDs the mutation targets.

    Returns:
        (accepted, reason)
    """
    # 1. Zero-regression check
    passed, regressed = check_zero_regression(candidate, baseline)
    if not passed:
        return False, f"regression on tasks: {', '.join(regressed)}"

    # 2. Check that at least one target improved
    target_improved = []
    for tid in target_failures:
        old = next((t for t in baseline.traces if t.task_id == tid), None)
        new = next((t for t in candidate.traces if t.task_id == tid), None)
        if old and new and new.score > old.score:
            target_improved.append(tid)

    if not target_improved:
        c_fitness = compute_fitness(candidate)
        b_fitness = compute_fitness(baseline)
        # Allow if overall score improved even without target improvement
        if c_fitness["score"] > b_fitness["score"]:
            return True, f"score improved by {c_fitness['score'] - b_fitness['score']:+.2%} (no target fixed)"
        return False, "no target failure improved"

    return True, f"fixed {len(target_improved)} target(s): {', '.join(target_improved)}"
