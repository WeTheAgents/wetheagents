"""Aggregate blind-run traces into per-task majority recommendations."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict

from src.trace import BenchmarkTrace, build_answers_digest, load_trace


def _answer_key(item: dict) -> str:
    code = str(item.get("answer_code", "")).strip()
    answer = str(item.get("answer", "")).strip()
    return f"{code}||{answer}"


def _clean_text(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def normalize_answer(item: dict) -> dict:
    """Collapse semantically equivalent answer variants into conservative families."""
    code = str(item.get("answer_code", "")).strip()
    answer = str(item.get("answer", "")).strip()
    refs = list(item.get("refs", []) or [])
    code_lower = code.lower()
    answer_clean = _clean_text(answer)
    refs_joined = " ".join(str(ref) for ref in refs).lower()

    placeholder_statuses = {
        "todo",
        "tbd",
        "wip",
        "not ready",
        "notready",
    }
    amount_labels = {
        "ask for amount",
        "missing total",
        "amount required",
    }

    security_signals = [
        "outcome_denied_security",
        "prompt injection",
        "embedded injection",
        "hidden override",
        "destructive instruction",
        "no action taken",
        "refusing the task",
        "request denied for security",
    ]

    if "denied_security" in code_lower or any(signal in answer_clean for signal in security_signals):
        return {
            "family": "security_refusal",
            "canonical_code": "OUTCOME_DENIED_SECURITY",
            "canonical_answer": "OUTCOME_DENIED_SECURITY",
            "reason": "security refusal wording normalized",
        }

    if answer_clean in placeholder_statuses:
        return {
            "family": "placeholder_status",
            "canonical_code": code or "completed",
            "canonical_answer": "TODO",
            "reason": "placeholder status wording normalized",
        }

    if answer_clean in amount_labels:
        return {
            "family": "amount_clarification",
            "canonical_code": code or "completed",
            "canonical_answer": "ASK-FOR-AMOUNT",
            "reason": "missing-amount wording normalized",
        }

    normalized_path = answer.replace("\\", "/").lstrip("./")
    if refs and normalized_path.lower() == refs_joined.strip():
        normalized_path = normalized_path

    return {
        "family": "exact",
        "canonical_code": code,
        "canonical_answer": normalized_path,
        "reason": "",
    }


def _normalized_key(item: dict) -> str:
    normalized = normalize_answer(item)
    return f"{normalized['canonical_code']}||{normalized['canonical_answer']}"


def summarize_traces(traces: list[BenchmarkTrace]) -> dict:
    """Summarize multiple benchmark traces for blind-run majority selection."""
    per_task: dict[str, list[dict]] = defaultdict(list)
    run_summaries: list[dict] = []

    for trace in traces:
        answers = build_answers_digest(trace)
        run_summaries.append(
            {
                "timestamp": trace.timestamp,
                "provider": trace.provider,
                "prompt_version": trace.prompt_version,
                "total_score": trace.total_score,
                "passed_tasks": list(trace.passed_tasks),
                "failed_tasks": list(trace.failed_tasks),
            }
        )
        for item in answers:
            normalized = normalize_answer(item)
            per_task[item["task_id"]].append(
                {
                    "timestamp": trace.timestamp,
                    "score": item["score"],
                    "answer_code": item["answer_code"],
                    "answer": item["answer"],
                    "normalized_family": normalized["family"],
                    "normalized_answer_code": normalized["canonical_code"],
                    "normalized_answer": normalized["canonical_answer"],
                    "normalization_reason": normalized["reason"],
                    "refs": item["refs"],
                    "total_steps": item["total_steps"],
                    "error": item["error"],
                }
            )

    task_reports: list[dict] = []
    for task_id in sorted(per_task.keys(), key=lambda tid: (int(tid[1:]) if tid[1:].isdigit() else 0, tid)):
        records = per_task[task_id]
        counts = Counter(_answer_key(item) for item in records)
        best_key, best_count = counts.most_common(1)[0]
        best_code, best_answer = best_key.split("||", 1)
        normalized_counts = Counter(_normalized_key(item) for item in records)
        normalized_best_key, normalized_best_count = normalized_counts.most_common(1)[0]
        normalized_best_code, normalized_best_answer = normalized_best_key.split("||", 1)

        task_reports.append(
            {
                "task_id": task_id,
                "num_runs": len(records),
                "recommended_answer_code": best_code,
                "recommended_answer": best_answer,
                "majority_count": best_count,
                "majority_fraction": best_count / len(records),
                "unanimous": best_count == len(records),
                "ambiguous": best_count <= len(records) / 2,
                "recommended_normalized_answer_code": normalized_best_code,
                "recommended_normalized_answer": normalized_best_answer,
                "normalized_majority_count": normalized_best_count,
                "normalized_majority_fraction": normalized_best_count / len(records),
                "normalized_unanimous": normalized_best_count == len(records),
                "normalized_ambiguous": normalized_best_count <= len(records) / 2,
                "answer_histogram": [
                    {
                        "answer_code": key.split("||", 1)[0],
                        "answer": key.split("||", 1)[1],
                        "count": count,
                    }
                    for key, count in counts.most_common()
                ],
                "normalized_answer_histogram": [
                    {
                        "answer_code": key.split("||", 1)[0],
                        "answer": key.split("||", 1)[1],
                        "count": count,
                    }
                    for key, count in normalized_counts.most_common()
                ],
                "runs": records,
            }
        )

    return {
        "num_runs": len(traces),
        "run_summaries": run_summaries,
        "tasks": task_reports,
    }


def load_traces(paths: list[str]) -> list[BenchmarkTrace]:
    """Load multiple trace files."""
    return [load_trace(path) for path in paths]


def save_summary(path: str, summary: dict) -> None:
    """Persist blind-run majority summary to JSON."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def print_summary(summary: dict) -> None:
    """Print a concise blind-run majority report."""
    print("=" * 60)
    print(f"BLIND MAJORITY SUMMARY ({summary['num_runs']} runs)")
    for run in summary["run_summaries"]:
        print(
            f"  {run['timestamp']}: {run['total_score']:.2f} "
            f"passed={','.join(run['passed_tasks']) or '-'}"
        )
    print()
    for task in summary["tasks"]:
        marker = "OK" if not task["normalized_ambiguous"] else "REVIEW"
        print(
            f"  {task['task_id']}: {marker} "
            f"{task['recommended_normalized_answer_code']} / {task['recommended_normalized_answer']!r} "
            f"({task['normalized_majority_count']}/{task['num_runs']})"
        )
        for item in task["normalized_answer_histogram"]:
            print(f"    - {item['count']}x {item['answer_code']} / {item['answer']!r}")


def main() -> None:
    import sys

    args = sys.argv[1:]
    output_path = ""
    trace_paths: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--out" and i + 1 < len(args):
            output_path = args[i + 1]
            i += 2
            continue
        trace_paths.append(args[i])
        i += 1

    if not trace_paths:
        raise SystemExit("usage: python -m src.blind_report [--out path] trace1.json trace2.json ...")

    summary = summarize_traces(load_traces(trace_paths))
    print_summary(summary)
    if output_path:
        save_summary(output_path, summary)
        print(f"\nSaved blind summary: {output_path}")


if __name__ == "__main__":
    main()
