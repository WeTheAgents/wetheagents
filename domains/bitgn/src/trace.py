"""Execution tracing for BitGN benchmark runs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime


@dataclass
class StepRecord:
    tool_name: str
    tool_input: dict
    output: str  # truncated to keep traces manageable
    elapsed: float


@dataclass
class TaskTrace:
    task_id: str
    instruction: str
    score: float = 0.0
    score_detail: list[str] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    total_steps: int = 0
    error: str | None = None
    # Genome system fields (populated when use_genome=True)
    executor_mode: str = ""  # "lean" or "complete" — which executor path was used
    genes_used: list[str] = field(default_factory=list)
    taxonomy_trace: list[dict] = field(default_factory=list)
    taxonomy_rounds: int = 0
    taxonomy_result: dict = field(default_factory=dict)
    taxonomy_overrides: list[dict] = field(default_factory=list)
    planner_trace: list[dict] = field(default_factory=list)
    watchdog_interventions: list[dict] = field(default_factory=list)
    planner_rounds: int = 0
    replan_events: list[dict] = field(default_factory=list)
    gate_rejections: list[dict] = field(default_factory=list)
    action_brakes: list[dict] = field(default_factory=list)
    planner_model: str = ""
    executor_model: str = ""
    executor_tier_routing_disabled: bool = False
    watchdog_mode: str = ""
    failure_bucket: str = ""
    final_completion_snapshot: dict = field(default_factory=dict)


@dataclass
class BenchmarkTrace:
    provider: str
    prompt_version: str  # e.g. "gen_003"
    prompt_text: str  # full prompt for reproducibility
    traces: list[TaskTrace] = field(default_factory=list)
    total_score: float = 0.0
    passed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def finalize(self) -> None:
        """Compute summary fields from individual traces."""
        if not self.traces:
            return
        self.passed_tasks = [t.task_id for t in self.traces if t.score >= 1.0]
        self.failed_tasks = [t.task_id for t in self.traces if t.score < 1.0]
        self.total_score = sum(t.score for t in self.traces) / len(self.traces)


# --- Serialization helpers ---

OUTPUT_TRUNCATE = 500  # max chars for tool output in traces


def truncate_output(text: str) -> str:
    if len(text) <= OUTPUT_TRUNCATE:
        return text
    return text[:OUTPUT_TRUNCATE] + "..."


def save_trace(path: str, trace: BenchmarkTrace) -> None:
    """Save a benchmark trace to JSON."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(trace), f, indent=2, ensure_ascii=False)


def load_trace(path: str) -> BenchmarkTrace:
    """Load a benchmark trace from JSON."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    traces = []
    for td in data.get("traces", []):
        steps = [StepRecord(**s) for s in td.pop("steps", [])]
        traces.append(TaskTrace(**td, steps=steps))

    data.pop("traces", None)
    return BenchmarkTrace(**data, traces=traces)


def build_failure_digest(trace: BenchmarkTrace) -> list[dict]:
    digest: list[dict] = []
    for task in trace.traces:
        if task.score >= 1.0:
            continue
        last_gate = task.gate_rejections[-1]["category"] if task.gate_rejections else ""
        last_brake = task.action_brakes[-1]["category"] if task.action_brakes else ""
        repeated = []
        seen: set[str] = set()
        for step in task.steps:
            target = (
                step.tool_input.get("path")
                or step.tool_input.get("root")
                or step.tool_input.get("pattern")
                or ""
            )
            if target and target in seen and target not in repeated:
                repeated.append(str(target))
            elif target:
                seen.add(str(target))
        final_status = "completed_scored_failed" if any(s.tool_name == "report_completion" for s in task.steps) else ""
        if task.error and not final_status:
            final_status = "error"
        digest.append(
            {
                "task_id": task.task_id,
                "score": task.score,
                "error": task.error,
                "last_gate_category": last_gate,
                "last_brake_category": last_brake,
                "planner_rounds": task.planner_rounds,
                "taxonomy_rounds": task.taxonomy_rounds,
                "taxonomy_route_candidate": task.taxonomy_result.get("route_candidate", ""),
                "taxonomy_override_happened": bool(task.taxonomy_overrides),
                "taxonomy_override_count": len(task.taxonomy_overrides),
                "replan_kinds": [event.get("kind", "") for event in task.replan_events],
                "repeated_read_set": repeated[:8],
                "final_completion_attempt_status": final_status,
                "failure_bucket": task.failure_bucket,
                "final_completion_snapshot": task.final_completion_snapshot,
            }
        )
    return digest
