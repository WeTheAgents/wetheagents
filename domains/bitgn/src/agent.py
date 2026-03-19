"""Core agent loop for BitGN sandbox — provider-agnostic, backend-agnostic."""

import json
import sys

# Fix Windows cp1251 encoding errors
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(errors="replace")
import time

from src.compressor import compress_history
from src.config import DEFAULT_CONFIG, AgentConfig
from src.enrichment import AgentContext, enriched_dispatcher
from src.models import ReportCompletion
from src.prompts import build_system_prompt
from src.providers.anthropic_provider import AnthropicProvider
from src.tools import Dispatcher
from src.trace import StepRecord, TaskTrace, truncate_output
from src.warmup import warmup_vault
from src.watchdog import Watchdog

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_BLUE = "\x1B[34m"
CLI_CLR = "\x1B[0m"

MAX_STEPS = 35
FORCE_ANSWER_AT = 25


def _prepare_agent(
    dispatcher: Dispatcher,
    task_text: str,
    system_prompt_override: str | None,
    config: AgentConfig,
) -> tuple[str, Dispatcher, AgentContext]:
    """Common setup for both Anthropic and OpenAI agent loops.

    Returns (system_prompt, dispatcher, agent_context).
    """
    ctx = AgentContext(max_steps=MAX_STEPS)
    warmup_context = None

    # Warmup: pre-load vault outline + AGENTS.MD
    if config.warmup:
        warmup_text, trust_chain = warmup_vault(
            dispatcher, read_agents_md=config.warmup_read_agents_md
        )
        warmup_context = warmup_text
        ctx.trust_chain = trust_chain
        print(f"  {CLI_BLUE}Warmup: outline + {len(trust_chain)} trust chain files{CLI_CLR}")

    # Build system prompt
    if system_prompt_override:
        system_prompt = system_prompt_override
        # If warmup context available but using custom prompt, append it
        if warmup_context and "{warmup_context}" not in system_prompt:
            system_prompt += f"\n\n{warmup_context}"
    else:
        system_prompt = build_system_prompt(
            task_text, warmup_context=warmup_context
        )

    # Enrichment: wrap dispatcher with step budget, defense, trust hints
    if config.enrichment:
        dispatcher = enriched_dispatcher(dispatcher, ctx, config)

    return system_prompt, dispatcher, ctx


def run_agent_anthropic(
    provider: AnthropicProvider,
    dispatcher: Dispatcher,
    task_text: str,
    system_prompt_override: str | None = None,
    config: AgentConfig | None = None,
) -> TaskTrace:
    """Run agent loop using Anthropic's native tool_use protocol."""
    config = config or DEFAULT_CONFIG

    watchdog = (
        Watchdog(
            model=config.watchdog_model,
            gate_model=config.watchdog_gate_model,
            check_every=config.watchdog_check_every,
            min_step=config.watchdog_min_step,
        )
        if config.watchdog
        else None
    )

    system_prompt, dispatcher, ctx = _prepare_agent(
        dispatcher, task_text, system_prompt_override, config
    )
    trace = TaskTrace(task_id="", instruction=task_text)

    messages = [{"role": "user", "content": task_text}]

    from src.models import (
        DeleteTool,
        ListTool,
        OutlineTool,
        ReadTool,
        SearchTool,
        WriteTool,
    )

    TOOL_MODELS = {
        "outline": OutlineTool,
        "read": ReadTool,
        "list": ListTool,
        "search": SearchTool,
        "write": WriteTool,
        "delete": DeleteTool,
    }

    gate_retries = 0  # pre-final gate retry counter

    for i in range(MAX_STEPS):
        ctx.step = i + 1
        step_name = f"step_{i + 1}"
        print(f"\n{step_name}... ", end="", flush=True)

        # History compression
        call_messages = messages
        if config.compress_history and len(messages) > config.compress_threshold:
            call_messages = compress_history(messages, keep_last=config.compress_keep_last)

        started = time.time()
        resp = provider.raw_call(
            call_messages, system_prompt,
            cache_aware=config.cache_aware_prompt,
        )
        elapsed = time.time() - started

        # Append assistant response to history (preserves tool_use blocks)
        messages.append({"role": "assistant", "content": resp.content})

        # Collect ALL tool_use blocks (model may return multiple)
        tool_calls = []
        text_parts = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        thinking = " ".join(text_parts)[:100] if text_parts else ""
        print(f"{thinking} ({elapsed:.1f}s)")

        if not tool_calls:
            print(f"  {CLI_RED}No tool call in response{CLI_CLR}")
            messages.append({
                "role": "user",
                "content": "You must call a tool. If you have the answer, use report_completion. If not, continue exploring.",
            })
            continue

        # Process ALL tool calls and collect results
        tool_results = []
        completed = False

        for tool_call in tool_calls:
            tool_name = tool_call.name
            tool_input = tool_call.input
            if "tool" not in tool_input:
                tool_input["tool"] = tool_name

            print(f"  -> {tool_name}: {_summarize_input(tool_input)}")

            step_started = time.time()

            # Handle report_completion — pre-final gate runs first
            if tool_name == "report_completion":
                # Gate: reject and redirect if watchdog finds a problem
                if watchdog is not None and gate_retries < config.watchdog_gate_retries:
                    gate_correction = watchdog.check_final(task_text, trace.steps, tool_input)
                    if gate_correction:
                        gate_retries += 1
                        print(f"  {CLI_RED}[GATE] {gate_correction}{CLI_CLR}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "content": (
                                f"[REDTEAM]: {gate_correction} "
                                "Correct the issue and resubmit."
                            ),
                        })
                        break  # don't accept completion; re-enter outer loop

                # Gate passed (or disabled/exhausted) — process normally
                completion = ReportCompletion.model_validate(tool_input)
                result_text = dispatcher(completion)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_call.id,
                    "content": result_text,
                })
                trace.steps.append(StepRecord(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    output=truncate_output(result_text),
                    elapsed=time.time() - step_started,
                ))
                print(f"\n{CLI_GREEN}Agent {completion.code}{CLI_CLR}. Summary:")
                for s in completion.completed_steps_laconic:
                    print(f"  - {s}")
                print(f"\n{CLI_BLUE}ANSWER: {completion.answer}{CLI_CLR}")
                if completion.refs:
                    for ref in completion.refs:
                        print(f"  - {CLI_BLUE}{ref}{CLI_CLR}")
                completed = True
                break  # stop executing further tool calls after completion

            model_cls = TOOL_MODELS.get(tool_name)
            if model_cls is None:
                result_text = f"Unknown tool: {tool_name}"
            else:
                tool_obj = model_cls.model_validate(tool_input)
                result_text = dispatcher(tool_obj)

            step_elapsed = time.time() - step_started

            truncated = result_text[:200] + "..." if len(result_text) > 200 else result_text
            print(f"  {CLI_GREEN}OUT{CLI_CLR}: {truncated}")

            trace.steps.append(StepRecord(
                tool_name=tool_name,
                tool_input=tool_input,
                output=truncate_output(result_text),
                elapsed=step_elapsed,
            ))

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": result_text,
            })

        # Append ALL tool results in a single user message
        messages.append({"role": "user", "content": tool_results})

        if completed:
            trace.total_steps = len(trace.steps)
            return trace

        # Watchdog: Haiku checks for stuck/looping behavior every N executed steps
        if watchdog is not None and watchdog.should_check(len(trace.steps)):
            correction = watchdog.check(task_text, trace.steps)
            if correction:
                print(f"  {CLI_RED}[WATCHDOG] {correction}{CLI_CLR}")
                messages.append({"role": "user", "content": f"[WATCHDOG]: {correction}"})

        # Budget warning (only if enrichment not active — enrichment handles this)
        if not config.enrichment and i == FORCE_ANSWER_AT - 1:
            messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM: You have only 5 steps remaining. "
                    "Submit your answer NOW using report_completion, "
                    "even if incomplete. Do not waste remaining steps exploring.]"
                ),
            })

    print(f"\n{CLI_RED}Max steps reached without completion{CLI_CLR}")
    trace.total_steps = len(trace.steps)
    trace.error = "Max steps reached without completion"
    return trace


def run_agent_openai(
    provider,
    dispatcher: Dispatcher,
    task_text: str,
    system_prompt_override: str | None = None,
    config: AgentConfig | None = None,
) -> TaskTrace:
    """Run agent loop using OpenAI native function calling (tools API)."""
    config = config or DEFAULT_CONFIG

    watchdog = (
        Watchdog(
            model=config.watchdog_model,
            gate_model=config.watchdog_gate_model,
            check_every=config.watchdog_check_every,
            min_step=config.watchdog_min_step,
        )
        if config.watchdog
        else None
    )

    system_prompt, dispatcher, ctx = _prepare_agent(
        dispatcher, task_text, system_prompt_override, config
    )
    trace = TaskTrace(task_id="", instruction=task_text)

    from src.models import (
        DeleteTool,
        ListTool,
        OutlineTool,
        ReadTool,
        SearchTool,
        WriteTool,
    )

    TOOL_MODELS = {
        "outline": OutlineTool,
        "read": ReadTool,
        "list": ListTool,
        "search": SearchTool,
        "write": WriteTool,
        "delete": DeleteTool,
    }

    # Messages list (without system — raw_call prepends it)
    messages = [{"role": "user", "content": task_text}]

    gate_retries = 0  # pre-final gate retry counter

    for i in range(MAX_STEPS):
        ctx.step = i + 1
        step_name = f"step_{i + 1}"
        print(f"\n{step_name}... ", end="", flush=True)

        # History compression
        call_messages = messages
        if config.compress_history and len(messages) > config.compress_threshold:
            call_messages = compress_history(messages, keep_last=config.compress_keep_last)

        started = time.time()
        resp = provider.raw_call(
            call_messages, system_prompt,
            cache_aware=config.cache_aware_prompt,
        )
        elapsed = time.time() - started

        choice = resp.choices[0]
        msg = choice.message

        # Print thinking text
        thinking = (msg.content or "")[:100]
        print(f"{thinking} ({elapsed:.1f}s)")

        # Append assistant message to history (preserves tool_calls)
        assistant_msg = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "type": "function",
                    "id": tc.id,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_msg)

        if not msg.tool_calls:
            print(f"  {CLI_RED}No tool call in response{CLI_CLR}")
            messages.append({
                "role": "user",
                "content": "You must call a tool. If you have the answer, use report_completion. If not, continue exploring.",
            })
            continue

        # Process ALL tool calls
        completed = False

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            tool_input = json.loads(tc.function.arguments)
            if "tool" not in tool_input:
                tool_input["tool"] = tool_name

            print(f"  -> {tool_name}: {_summarize_input(tool_input)}")

            step_started = time.time()

            # Handle report_completion — pre-final gate runs first
            if tool_name == "report_completion":
                # Gate: reject and redirect if watchdog finds a problem
                if watchdog is not None and gate_retries < config.watchdog_gate_retries:
                    gate_correction = watchdog.check_final(task_text, trace.steps, tool_input)
                    if gate_correction:
                        gate_retries += 1
                        print(f"  {CLI_RED}[GATE] {gate_correction}{CLI_CLR}")
                        messages.append({
                            "role": "tool",
                            "content": (
                                f"[REDTEAM]: {gate_correction} "
                                "Correct the issue and resubmit."
                            ),
                            "tool_call_id": tc.id,
                        })
                        break  # don't accept completion; re-enter outer loop

                # Gate passed (or disabled/exhausted) — process normally
                completion = ReportCompletion.model_validate(tool_input)
                result_text = dispatcher(completion)
                messages.append({"role": "tool", "content": result_text, "tool_call_id": tc.id})
                trace.steps.append(StepRecord(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    output=truncate_output(result_text),
                    elapsed=time.time() - step_started,
                ))
                print(f"\n{CLI_GREEN}Agent {completion.code}{CLI_CLR}. Summary:")
                for s in completion.completed_steps_laconic:
                    print(f"  - {s}")
                print(f"\n{CLI_BLUE}ANSWER: {completion.answer}{CLI_CLR}")
                if completion.refs:
                    for ref in completion.refs:
                        print(f"  - {CLI_BLUE}{ref}{CLI_CLR}")
                completed = True
                break  # stop executing further tool calls after completion

            model_cls = TOOL_MODELS.get(tool_name)
            if model_cls is None:
                result_text = f"Unknown tool: {tool_name}"
            else:
                tool_obj = model_cls.model_validate(tool_input)
                result_text = dispatcher(tool_obj)

            step_elapsed = time.time() - step_started

            truncated = result_text[:200] + "..." if len(result_text) > 200 else result_text
            print(f"  {CLI_GREEN}OUT{CLI_CLR}: {truncated}")

            trace.steps.append(StepRecord(
                tool_name=tool_name,
                tool_input=tool_input,
                output=truncate_output(result_text),
                elapsed=step_elapsed,
            ))

            # OpenAI format: each tool result is a separate message
            messages.append({"role": "tool", "content": result_text, "tool_call_id": tc.id})

        if completed:
            trace.total_steps = len(trace.steps)
            return trace

        # Watchdog: Haiku checks for stuck/looping behavior every N executed steps
        if watchdog is not None and watchdog.should_check(len(trace.steps)):
            correction = watchdog.check(task_text, trace.steps)
            if correction:
                print(f"  {CLI_RED}[WATCHDOG] {correction}{CLI_CLR}")
                messages.append({"role": "user", "content": f"[WATCHDOG]: {correction}"})

        # Budget warning (only if enrichment not active)
        if not config.enrichment and i == FORCE_ANSWER_AT - 1:
            messages.append({
                "role": "user",
                "content": (
                    "[SYSTEM: You have only 5 steps remaining. "
                    "Submit your answer NOW using report_completion.]"
                ),
            })

    print(f"\n{CLI_RED}Max steps reached without completion{CLI_CLR}")
    trace.total_steps = len(trace.steps)
    trace.error = "Max steps reached without completion"
    return trace


def _summarize_input(tool_input: dict) -> str:
    """Brief summary of tool input for logging."""
    parts = []
    for k, v in tool_input.items():
        if k == "tool":
            continue
        if isinstance(v, str) and len(v) > 50:
            v = v[:50] + "..."
        parts.append(f"{k}={v}")
    return ", ".join(parts)
