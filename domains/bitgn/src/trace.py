"""Execution tracing for BitGN benchmark runs."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


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


@dataclass
class BenchmarkTrace:
    provider: str
    prompt_version: str  # e.g. "gen_003"
    prompt_text: str  # full prompt for reproducibility
    traces: list[TaskTrace] = field(default_factory=list)
    total_score: float = 0.0
    passed_tasks: list[str] = field(default_factory=list)
    failed_tasks: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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
