"""Hybrid controller — reviews executor progress and decides next phase.

The controller is a single LLM call per checkpoint that sees the full
execution trace and vault context. It replaces both the watchdog and the
planner's static brief with real-time oversight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.planner import _call_planner_model
from src.trace import StepRecord

CONTROLLER_SYSTEM = """\
You are a task controller for a vault agent. Your goal is to GET THE TASK DONE correctly and efficiently.

You receive: the original task, vault context (AGENTS.MD + folder outline), and a compact trace of executor steps so far.

YOUR ROLE: You plan the work, the executor executes your plan. You are responsible for the outcome — both for getting the right answer AND for finishing promptly.

At each checkpoint:
1. Review what the executor found. Extract the key facts from tool results.
2. Check for HARD BLOCKERS ONLY: did a file reveal a policy that BLOCKS the task? (e.g., "do not write to X directly", "archive instead of deleting", HOLD/FREEZE, legal hold).
3. If no blockers: give the next instruction, or approve the completion.

Respond with EXACTLY ONE format (first word determines action):

CONTINUE: <2-3 sentence instruction for the next phase>
COMPLETE: <final answer text>|REFS: <comma-separated file paths>
CORRECT: <what went wrong> → <concrete action to take>

WHEN TO USE EACH:

COMPLETE — use when:
- Executor proposed an answer and it contains correct data. Accept it.
- Executor found "file not found", "path not found", "empty folder" — absence IS the answer. Do not send executor to search more locations. Report that the target does not exist.
- Executor has gathered enough evidence to answer, even if not every file was read.
- 10+ steps have been executed — finish with the best available data.

CONTINUE — use when:
- Executor just started and needs direction for the next batch of reads/searches.
- Key data sources identified in the vault outline have not been checked yet.

CORRECT — use ONLY when:
- Executor wrote to a path that AGENTS.MD explicitly forbids. Action: "Delete the file you wrote and explain the policy constraint in your answer instead."
- Executor's proposed answer contains a WRONG data value that you can verify from the trace. Action: "The correct value is X, not Y. Resubmit with X."
- Executor violated a policy you can see in the trace (e.g., deleted instead of archiving). Action: "Undo the delete, archive to [path] instead."
- NEVER use CORRECT for: "not fully confirmed", "should double-check", "didn't verify all locations", "the conclusion is too strong". These waste steps.

CRITICAL PRINCIPLES:

1. TRUST THE EXECUTOR'S DATA. You see a compact trace with 150-char previews — the executor saw the full file. If it extracted a value, trust it. Do not CORRECT because you think the value might be wrong based on partial trace data.

2. ABSENCE IS AN ANSWER. "File not found" and "empty folder" are valid, complete answers. When the executor tried to read/list/delete a target and got "not found" or "error" — that means the target does not exist. Report it as the answer. Do not send the executor to re-list the same folder or try alternative paths unless you have a SPECIFIC path from the vault outline that was not checked.

3. EVERY CORRECT MUST HAVE A CONCRETE ACTION. Never write "the executor violated X" without saying exactly what to do next: which file to delete/write/read, what the answer should say. If you cannot name a concrete action, use COMPLETE instead.

4. PRESERVE EXECUTOR'S REFS. When you approve with COMPLETE, include ALL refs from the executor's proposed completion. Do not drop refs.

5. STEP BUDGET AWARENESS. If the trace shows 10+ steps, the executor is running low on budget. Prefer COMPLETE over CONTINUE. If 15+ steps, you MUST complete with current evidence — do not send the executor back for more exploration.

6. REPEATED ANSWER = CONVERGENCE. If the executor submits a second time with the same or similar answer after a CORRECT, this means the executor — who saw the full file contents — is confident in its conclusion. You must either: (a) COMPLETE and accept the answer as correct, or (b) give a fundamentally DIFFERENT plan with NEW tool calls to new files, not a rephrased version of the same objection. The executor cannot fix what it doesn't see as broken. If you cannot point to a specific file the executor hasn't read yet, accept the answer."""


@dataclass
class ControllerResult:
    """Parsed controller response."""
    action: str  # "continue" | "complete" | "correct"
    instruction: str = ""  # for continue/correct
    answer: str = ""  # for complete
    refs: list[str] | None = None  # for complete


def format_steps_compact(steps: list[StepRecord], max_output: int = 150) -> str:
    """Format executor trace compactly for the controller."""
    if not steps:
        return "(no steps yet)"
    lines = []
    for i, s in enumerate(steps):
        args = ", ".join(
            f"{k}={str(v)[:50]!r}"
            for k, v in s.tool_input.items()
            if k != "tool"
        )
        preview = s.output[:max_output].replace("\n", " ") if s.output else ""
        lines.append(f"  {i+1}. {s.tool_name}({args})")
        if preview:
            lines.append(f"     → {preview}")
    return "\n".join(lines)


def _build_controller_prompt(
    task_text: str,
    warmup_context: str,
    steps: list[StepRecord],
    proposed_completion: dict | None = None,
) -> str:
    """Build the full prompt for a controller checkpoint."""
    parts = [CONTROLLER_SYSTEM]

    if warmup_context:
        parts.append(f"VAULT CONTEXT:\n{warmup_context}")

    parts.append(f"TASK:\n{task_text}")

    trace_text = format_steps_compact(steps)
    parts.append(f"EXECUTOR TRACE ({len(steps)} steps):\n{trace_text}")

    if proposed_completion:
        answer = proposed_completion.get("answer", "")
        refs = proposed_completion.get("refs", [])
        parts.append(
            f"PROPOSED COMPLETION:\n"
            f"  Answer: {answer}\n"
            f"  Refs: {', '.join(refs) if isinstance(refs, list) else refs}\n"
            f"\nIs this correct and complete? Reply COMPLETE to approve or CORRECT to fix."
        )
    else:
        parts.append("What should the executor do next?")

    return "\n\n".join(parts)


def parse_controller_response(raw: str) -> ControllerResult:
    """Parse the controller's raw LLM output into a structured result."""
    text = raw.strip()

    # COMPLETE: <answer>|REFS: <refs>
    if text.upper().startswith("COMPLETE:"):
        body = text[len("COMPLETE:"):].strip()
        # Try to split on |REFS:
        refs_match = re.search(r'\|REFS:\s*(.+)', body, re.IGNORECASE)
        if refs_match:
            answer = body[:refs_match.start()].strip()
            refs_str = refs_match.group(1).strip()
            refs = [r.strip() for r in refs_str.split(",") if r.strip()]
        else:
            answer = body
            refs = []
        return ControllerResult(action="complete", answer=answer, refs=refs)

    # CORRECT: <instruction>
    if text.upper().startswith("CORRECT:"):
        instruction = text[len("CORRECT:"):].strip()
        return ControllerResult(action="correct", instruction=instruction)

    # CONTINUE: <instruction>
    if text.upper().startswith("CONTINUE:"):
        instruction = text[len("CONTINUE:"):].strip()
        return ControllerResult(action="continue", instruction=instruction)

    # Fallback — treat as continue instruction
    return ControllerResult(action="continue", instruction=text)


def call_controller(
    model: str,
    task_text: str,
    warmup_context: str,
    steps: list[StepRecord],
    proposed_completion: dict | None = None,
) -> ControllerResult:
    """Run a single controller checkpoint.

    Args:
        model: LLM model for the controller (e.g., "gpt-5.4-mini").
        task_text: The original task instruction.
        warmup_context: Vault outline + AGENTS.MD content.
        steps: Executor steps completed so far.
        proposed_completion: If executor called report_completion, its args.

    Returns:
        ControllerResult with action + instruction/answer.
    """
    prompt = _build_controller_prompt(
        task_text, warmup_context, steps, proposed_completion,
    )
    raw = _call_planner_model(prompt, model)
    return parse_controller_response(raw)
