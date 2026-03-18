"""Task history store — accumulates all practice runs for confidence estimation."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from src.trace import BenchmarkTrace, TaskTrace


@dataclass
class TaskRecord:
    task_id: str
    instruction: str
    score: float
    score_detail: list[str]
    total_steps: int
    answer: str
    refs: list[str]
    prompt_version: str
    provider: str
    timestamp: str


@dataclass
class TaskHistory:
    records: list[TaskRecord] = field(default_factory=list)

    def ingest_trace(self, trace: BenchmarkTrace) -> int:
        """Add all tasks from a benchmark trace. Returns number of records added."""
        added = 0
        for t in trace.traces:
            # Extract answer and refs from the last report_completion step
            answer = ""
            refs: list[str] = []
            for step in reversed(t.steps):
                if step.tool_name == "report_completion":
                    answer = step.tool_input.get("answer", "")
                    refs = step.tool_input.get("refs", [])
                    break

            self.records.append(TaskRecord(
                task_id=t.task_id,
                instruction=t.instruction,
                score=t.score,
                score_detail=t.score_detail,
                total_steps=t.total_steps,
                answer=answer,
                refs=refs,
                prompt_version=trace.prompt_version,
                provider=trace.provider,
                timestamp=trace.timestamp,
            ))
            added += 1
        return added

    def get_by_instruction(self, instruction: str) -> list[TaskRecord]:
        """Find all past records with the exact same instruction."""
        return [r for r in self.records if r.instruction == instruction]

    def get_similar(self, instruction: str, top_k: int = 5) -> list[TaskRecord]:
        """Find similar past tasks by word overlap (Jaccard)."""
        query_words = set(instruction.lower().split())
        if not query_words:
            return []

        scored = []
        seen_instructions: set[str] = set()
        for r in self.records:
            if r.instruction in seen_instructions:
                continue
            seen_instructions.add(r.instruction)
            record_words = set(r.instruction.lower().split())
            if not record_words:
                continue
            jaccard = len(query_words & record_words) / len(query_words | record_words)
            if jaccard > 0.1:
                scored.append((jaccard, r))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:top_k]]

    def confidence_for(self, instruction: str) -> tuple[float, int]:
        """Estimate confidence based on historical performance.

        Returns (avg_score, num_attempts) for exact instruction matches.
        If no exact match, returns (-1.0, 0) — unknown task.
        """
        exact = self.get_by_instruction(instruction)
        if not exact:
            return -1.0, 0
        avg = sum(r.score for r in exact) / len(exact)
        return avg, len(exact)

    def confidence_report(self, traces: list[TaskTrace]) -> str:
        """Generate a confidence report for a set of task traces (blind mode).

        For each task, reports historical confidence level.
        """
        lines = []
        for t in traces:
            conf, n = self.confidence_for(t.instruction)
            if conf < 0:
                similar = self.get_similar(t.instruction, top_k=3)
                if similar:
                    sim_scores = [s.score for s in similar]
                    avg_sim = sum(sim_scores) / len(sim_scores)
                    lines.append(
                        f"  {t.task_id}: NOVEL task. Similar tasks scored "
                        f"{avg_sim:.0%} avg ({len(similar)} similar found)"
                    )
                else:
                    lines.append(f"  {t.task_id}: NOVEL task. No similar tasks in history.")
            elif conf >= 1.0:
                lines.append(f"  {t.task_id}: HIGH confidence — {n}/{n} perfect in practice")
            elif conf >= 0.8:
                passed = sum(1 for r in self.get_by_instruction(t.instruction) if r.score >= 1.0)
                lines.append(
                    f"  {t.task_id}: MEDIUM confidence — {passed}/{n} perfect "
                    f"({conf:.0%} avg)"
                )
            else:
                lines.append(
                    f"  {t.task_id}: LOW confidence — {conf:.0%} avg over {n} attempts"
                )
        return "\n".join(lines)

    def stats(self) -> dict:
        """Overall history stats."""
        if not self.records:
            return {"total": 0, "unique_tasks": 0, "avg_score": 0.0}

        unique_instructions = set(r.instruction for r in self.records)
        return {
            "total": len(self.records),
            "unique_tasks": len(unique_instructions),
            "avg_score": sum(r.score for r in self.records) / len(self.records),
            "perfect_rate": sum(1 for r in self.records if r.score >= 1.0) / len(self.records),
        }


HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "task_history.json",
)


def load_history(path: str | None = None) -> TaskHistory:
    """Load task history from JSON."""
    p = path or HISTORY_FILE
    if not os.path.exists(p):
        return TaskHistory()
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    records = [TaskRecord(**r) for r in data.get("records", [])]
    return TaskHistory(records=records)


def save_history(history: TaskHistory, path: str | None = None) -> None:
    """Save task history to JSON."""
    p = path or HISTORY_FILE
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"records": [asdict(r) for r in history.records]}, f,
                  indent=2, ensure_ascii=False)
