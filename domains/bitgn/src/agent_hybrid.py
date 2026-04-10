"""Hybrid controller-executor agent loop.

Architecture:
- Controller (gpt-5.4-mini): reviews execution trace at each checkpoint,
  gives phase instructions, validates proposed completions.
- Executor (gpt-4.1 or gpt-5.4-mini): thin prompt, runs tool calls in
  batches of N steps (phase_length), follows controller instructions.

The controller sees every tool result (via compact trace) and can correct
the executor in real-time — unlike the genome-mode executor which runs
autonomously with a large static prompt.
"""

from __future__ import annotations

import json
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

from src.config import DEFAULT_CONFIG, AgentConfig
from src.controller import ControllerResult, call_controller
from src.enrichment import AgentContext, enriched_dispatcher
from src.models import ReportCompletion
from src.tools import Dispatcher
from src.trace import StepRecord, TaskTrace, truncate_output
from src.warmup import warmup_vault

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"


THIN_EXECUTOR_PROMPT = """\
You are a vault tool executor. Follow the controller's instructions precisely.

Tools available: outline, read, list, search, write, delete, report_completion.

Rules:
- Execute the controller's instruction from the last [CONTROLLER] message.
- You may call multiple tools in parallel when they are independent reads.
- Include actual data values in answers (not just "I found it").
- Include file paths you used in refs.
- If the controller told you NOT to write or NOT to do something, obey strictly.
- When you have enough data to answer the task, call report_completion."""


def _format_tc(tc) -> dict:
    """Format a tool call for OpenAI message format."""
    return {
        "type": "function",
        "id": tc.id,
        "function": {
            "name": tc.function.name,
            "arguments": tc.function.arguments,
        },
    }


def _summarize_input(d: dict) -> str:
    """One-line summary of tool input for logging."""
    parts = []
    for k, v in d.items():
        if k == "tool":
            continue
        sv = str(v)
        if len(sv) > 50:
            sv = sv[:50] + "..."
        parts.append(f"{k}={sv}")
    return ", ".join(parts)


def _get_tool_models():
    """Get tool model classes (mini runtime)."""
    from src.tool_defs import mini_tool_models
    return mini_tool_models()


def run_agent_hybrid_openai(
    provider,
    dispatcher: Dispatcher,
    task_text: str,
    system_prompt_override: str | None = None,
    config: AgentConfig | None = None,
    warmup_context: str | None = None,
    trust_chain: set[str] | None = None,
) -> TaskTrace:
    """Run the hybrid controller-executor agent loop.

    Args:
        provider: OpenAI provider instance.
        dispatcher: Base tool dispatcher (will be wrapped with enrichment).
        task_text: The task instruction.
        system_prompt_override: Ignored (hybrid builds its own prompts).
        config: Agent configuration.
        warmup_context: Pre-computed warmup text (skips warmup if provided).
        trust_chain: Pre-computed trust chain (from warmup).

    Returns:
        TaskTrace with execution history and metadata.
    """
    config = config or DEFAULT_CONFIG
    max_steps = config.hybrid_max_steps
    phase_length = config.hybrid_phase_length
    controller_model = config.hybrid_controller_model
    executor_model = config.hybrid_executor_model

    TOOL_MODELS = _get_tool_models()

    # --- Setup ---
    ctx = AgentContext(max_steps=max_steps)
    trace = TaskTrace(task_id="", instruction=task_text)

    # Warmup: use pre-computed or run fresh
    if warmup_context is not None:
        warmup_text = warmup_context
        ctx.trust_chain = trust_chain or set()
        print(f"  {CLI_BLUE}Hybrid: using pre-computed warmup{CLI_CLR}")
    else:
        warmup_text, trust_chain_computed = warmup_vault(dispatcher, read_agents_md=True)
        ctx.trust_chain = trust_chain_computed
        print(f"  {CLI_BLUE}Hybrid warmup: {len(trust_chain_computed)} trust chain files{CLI_CLR}")

    # Enrichment wrapper
    if config.enrichment:
        dispatcher = enriched_dispatcher(dispatcher, ctx, config)

    # --- Initial controller call ---
    print(f"  {CLI_BLUE}Controller ({controller_model}): initial plan...{CLI_CLR}", end=" ")
    started = time.time()
    ctrl = call_controller(
        controller_model, task_text, warmup_text, steps=[],
    )
    elapsed = time.time() - started
    print(f"({elapsed:.1f}s) → {ctrl.action}: {ctrl.instruction[:80]}")

    controller_calls = 1

    if ctrl.action == "complete":
        # Controller answered immediately from warmup context
        _finalize_completion(dispatcher, ctrl, trace)
        trace.total_steps = 0
        return trace

    # --- Build executor messages ---
    messages: list[dict] = [
        {"role": "user", "content": task_text},
        {"role": "user", "content": f"[CONTROLLER]: {ctrl.instruction}"},
    ]

    provider.model_override = executor_model
    completed = False

    # --- Main loop: alternating executor phases + controller checkpoints ---
    while ctx.step < max_steps and not completed:
        proposed: dict | None = None

        # === EXECUTOR PHASE: up to phase_length steps ===
        for phase_step in range(phase_length):
            ctx.step += 1
            if ctx.step > max_steps:
                break

            print(f"\n  exec_{ctx.step}... ", end="", flush=True)

            started = time.time()
            resp = provider.raw_call(messages, THIN_EXECUTOR_PROMPT)
            elapsed = time.time() - started

            msg = resp.choices[0].message
            thinking = (msg.content or "")[:80]
            print(f"({elapsed:.1f}s) {thinking}")

            # Append assistant message
            assistant_msg: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_msg["tool_calls"] = [_format_tc(tc) for tc in msg.tool_calls]
            messages.append(assistant_msg)

            # No tool calls → nudge
            if not msg.tool_calls:
                print(f"    {CLI_RED}No tool call{CLI_CLR}")
                messages.append({"role": "user", "content": "You must call a tool."})
                continue

            # Process tool calls
            for tc in msg.tool_calls:
                tool_name = tc.function.name
                tool_input = json.loads(tc.function.arguments)
                if "tool" not in tool_input:
                    tool_input["tool"] = tool_name

                print(f"    -> {tool_name}: {_summarize_input(tool_input)}")

                if tool_name == "report_completion":
                    # Capture proposal — don't dispatch yet, controller decides
                    proposed = tool_input
                    messages.append({
                        "role": "tool",
                        "content": "Completion proposal captured. Controller will review.",
                        "tool_call_id": tc.id,
                    })
                    print(f"    {CLI_YELLOW}Proposed completion → controller review{CLI_CLR}")
                else:
                    # Normal tool call — dispatch through enrichment
                    try:
                        model_cls = TOOL_MODELS[tool_name]
                        tool_obj = model_cls.model_validate(tool_input)
                        result_text = dispatcher(tool_obj)
                    except Exception as e:
                        result_text = json.dumps({"error": str(e)})

                    messages.append({
                        "role": "tool",
                        "content": result_text,
                        "tool_call_id": tc.id,
                    })
                    print(f"    {CLI_GREEN}OUT{CLI_CLR}: {result_text[:80]}")

                    trace.steps.append(StepRecord(
                        tool_name=tool_name,
                        tool_input={k: v for k, v in tool_input.items() if k != "tool"},
                        output=truncate_output(result_text),
                        elapsed=elapsed,
                    ))

            if proposed:
                break

        # === CONTROLLER CHECKPOINT ===
        print(f"\n  {CLI_BLUE}Controller checkpoint #{controller_calls + 1}...{CLI_CLR}", end=" ")
        started = time.time()
        ctrl = call_controller(
            controller_model, task_text, warmup_text,
            steps=trace.steps,
            proposed_completion=proposed,
        )
        elapsed = time.time() - started
        controller_calls += 1
        print(f"({elapsed:.1f}s) → {ctrl.action}: {(ctrl.instruction or ctrl.answer)[:80]}")

        if ctrl.action == "complete":
            # Controller approves completion or provides its own answer
            answer = ctrl.answer
            refs = ctrl.refs or []

            # If executor proposed and controller approved without overriding
            if proposed and not answer:
                answer = proposed.get("answer", "")
                refs = proposed.get("refs", [])

            # Dispatch the actual report_completion
            try:
                completion = ReportCompletion(
                    tool="report_completion",
                    answer=answer,
                    refs=refs,
                    code="completed",
                    completed_steps_laconic=[
                        f"Hybrid: {controller_calls} controller calls, "
                        f"{len(trace.steps)} executor steps"
                    ],
                )
                dispatcher(completion)
            except Exception:
                pass  # completion dispatch may fail on local vaults

            trace.steps.append(StepRecord(
                tool_name="report_completion",
                tool_input={"answer": answer[:200], "refs": refs},
                output="completed",
                elapsed=0,
            ))
            completed = True

        elif ctrl.action == "correct":
            messages.append({
                "role": "user",
                "content": f"[CONTROLLER]: CORRECTION — {ctrl.instruction}",
            })
            proposed = None

        else:  # continue
            messages.append({
                "role": "user",
                "content": f"[CONTROLLER]: {ctrl.instruction}",
            })
            proposed = None

    # --- Finalize ---
    if not completed:
        print(f"\n  {CLI_RED}Max steps ({max_steps}) reached without completion{CLI_CLR}")
        trace.error = "max_steps_reached"

    trace.total_steps = len(trace.steps)
    return trace


def _finalize_completion(
    dispatcher: Dispatcher,
    ctrl: ControllerResult,
    trace: TaskTrace,
) -> None:
    """Handle controller completing from initial call (no executor needed)."""
    answer = ctrl.answer
    refs = ctrl.refs or []
    try:
        completion = ReportCompletion(
            tool="report_completion",
            answer=answer,
            refs=refs,
            code="completed",
            completed_steps_laconic=["Controller completed from warmup context"],
        )
        dispatcher(completion)
    except Exception:
        pass

    trace.steps.append(StepRecord(
        tool_name="report_completion",
        tool_input={"answer": answer[:200], "refs": refs},
        output="completed",
        elapsed=0,
    ))
    print(f"  {CLI_GREEN}Controller completed immediately: {answer[:80]}{CLI_CLR}")
