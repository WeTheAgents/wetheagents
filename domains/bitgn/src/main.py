"""Entry point for BitGN Sandbox benchmark runner."""

import os
import sys
import textwrap

# Ensure project root is on sys.path (needed for package=false flat layout)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"), override=True)

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    EvalPolicy,
    GetBenchmarkRequest,
    StartPlaygroundRequest,
    StatusRequest,
)
from connectrpc.errors import ConnectError

from src.config import DEFAULT_CONFIG, AgentConfig
from src.prompts import build_system_prompt
from src.tools import bitgn_dispatcher
from src.trace import BenchmarkTrace, TaskTrace

BITGN_URL = os.getenv("BENCHMARK_HOST", "https://api.bitgn.com")

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"


def create_provider(name: str):
    """Factory for LLM providers."""
    if name == "anthropic":
        from src.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    elif name == "openai":
        from src.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()
    else:
        raise ValueError(f"Unknown provider: {name}. Use 'anthropic' or 'openai'.")


def run_benchmark(
    provider_name: str,
    prompt_template: str | None = None,
    task_filter: list[str] | None = None,
    prompt_version: str = "default",
    config: AgentConfig | None = None,
) -> BenchmarkTrace:
    """Run the full benchmark and return a structured trace.

    Args:
        provider_name: 'anthropic' or 'openai'
        prompt_template: Custom system prompt template (with {task_text} placeholder).
                        If None, uses the default tuned prompt.
        task_filter: Optional list of task_ids to run (e.g. ['t01', 't02']).
        prompt_version: Label for this prompt version (e.g. 'gen_003').
        config: Optional AgentConfig for feature flags.

    Returns:
        BenchmarkTrace with all task traces, scores, and metadata.
    """
    config = config or DEFAULT_CONFIG
    provider = create_provider(provider_name)
    prompt_text = prompt_template or ""

    trace = BenchmarkTrace(
        provider=provider.provider_name(),
        prompt_version=prompt_version,
        prompt_text=prompt_text,
    )

    try:
        client = HarnessServiceClientSync(BITGN_URL)
        status = client.status(StatusRequest())
        print(f"Connected to BitGN: {status}")

        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id="bitgn/sandbox"))
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks."
        )

        for t in res.tasks:
            if task_filter and t.task_id not in task_filter:
                continue

            print("=" * 60)
            print(f"TASK: {t.task_id}")

            trial = client.start_playground(
                StartPlaygroundRequest(
                    benchmark_id="bitgn/sandbox",
                    task_id=t.task_id,
                )
            )

            print(f"Instruction: {trial.instruction}\n")

            # Build system prompt for this task
            system_prompt = build_system_prompt(trial.instruction, prompt_template)

            try:
                # Create gRPC dispatcher for this trial's VM
                from bitgn.vm.mini_connect import MiniRuntimeClientSync
                vm = MiniRuntimeClientSync(trial.harness_url)
                dispatcher = bitgn_dispatcher(vm)

                if provider_name == "anthropic":
                    from src.agent import run_agent_anthropic
                    task_trace = run_agent_anthropic(
                        provider, dispatcher, trial.instruction,
                        system_prompt_override=system_prompt,
                        config=config,
                    )
                else:
                    from src.agent import run_agent_openai
                    task_trace = run_agent_openai(
                        provider, dispatcher, trial.instruction,
                        system_prompt_override=system_prompt,
                        config=config,
                    )
            except Exception as e:
                print(f"{CLI_RED}Agent error: {e}{CLI_CLR}")
                import traceback
                traceback.print_exc()
                task_trace = TaskTrace(
                    task_id=t.task_id,
                    instruction=trial.instruction,
                    error=str(e),
                )

            result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))

            # Fill in score info from BitGN API
            task_trace.task_id = t.task_id
            if result.score >= 0:
                task_trace.score = result.score
                task_trace.score_detail = list(result.score_detail)

                style = CLI_GREEN if result.score == 1 else CLI_RED
                explain = textwrap.indent("\n".join(result.score_detail), "  ")
                print(f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}")

            trace.traces.append(task_trace)

    except ConnectError as e:
        print(f"{CLI_RED}{e.code}: {e.message}{CLI_CLR}")
    except KeyboardInterrupt:
        print(f"\n{CLI_RED}Interrupted{CLI_CLR}")

    trace.finalize()
    return trace


def print_summary(trace: BenchmarkTrace) -> None:
    """Print score summary to stdout."""
    if not trace.traces:
        return

    print("\n" + "=" * 60)
    print("RESULTS:")
    for t in trace.traces:
        style = CLI_GREEN if t.score == 1 else CLI_RED
        print(f"  {t.task_id}: {style}{t.score:0.2f}{CLI_CLR}")

    style = CLI_GREEN if trace.total_score >= 0.64 else CLI_RED
    pct = trace.total_score * 100.0
    print(f"\n  FINAL: {style}{pct:0.2f}%{CLI_CLR}")


def _parse_config_from_args(args: list[str]) -> tuple[list[str], AgentConfig]:
    """Extract --feature flags from args, return (remaining_args, config)."""
    config = AgentConfig()
    remaining = []
    i = 0
    while i < len(args):
        if args[i] == "--warmup":
            config.warmup = True
            config.enrichment = True  # warmup implies enrichment
            i += 1
        elif args[i] == "--compress":
            config.compress_history = True
            i += 1
        elif args[i] == "--enrich":
            config.enrichment = True
            i += 1
        elif args[i] == "--defense" and i + 1 < len(args):
            config.defense_mode = args[i + 1]
            config.enrichment = True  # defense requires enrichment
            i += 2
        elif args[i] == "--validate":
            config.step_validator = True
            config.enrichment = True  # validator lives in enrichment layer
            i += 1
        elif args[i] == "--cache":
            config.cache_aware_prompt = True
            i += 1
        elif args[i] == "--watchdog":
            config.watchdog = True
            i += 1
        elif args[i] == "--all-features":
            config.warmup = True
            config.compress_history = True
            config.enrichment = True
            config.step_validator = True
            config.defense_mode = "soft_block"
            config.cache_aware_prompt = True
            # watchdog NOT included: it makes live Anthropic API calls (has cost)
            i += 1
        else:
            remaining.append(args[i])
            i += 1
    return remaining, config


def main() -> None:
    # Parse args: task filter, provider, and feature flags
    task_filter = []
    provider_name = os.getenv("LLM_PROVIDER", "anthropic")

    args = sys.argv[1:]
    args, config = _parse_config_from_args(args)

    i = 0
    while i < len(args):
        if args[i] == "--provider" and i + 1 < len(args):
            provider_name = args[i + 1]
            i += 2
        elif args[i].startswith("--provider="):
            provider_name = args[i].split("=", 1)[1]
            i += 1
        else:
            task_filter.append(args[i])
            i += 1

    print(f"Provider: {provider_name}")
    if config.warmup:
        print("Features: warmup=ON")
    if config.compress_history:
        print("Features: compression=ON")
    if config.enrichment:
        print(f"Features: enrichment=ON, defense={config.defense_mode}")
    if config.step_validator:
        print("Features: step_validator=ON")
    if config.watchdog:
        print(
            f"Features: watchdog=ON "
            f"(model={config.watchdog_model}, "
            f"every={config.watchdog_check_every} steps, "
            f"from step {config.watchdog_min_step})"
        )

    trace = run_benchmark(
        provider_name=provider_name,
        task_filter=task_filter if task_filter else None,
        config=config,
    )

    print_summary(trace)


if __name__ == "__main__":
    main()
