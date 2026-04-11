"""Entry point for BitGN benchmark runner (sandbox + PAC1)."""

import json
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
    StartRunRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
)
from connectrpc.errors import ConnectError

from src.config import DEFAULT_CONFIG, AgentConfig
from src.prompts import build_system_prompt
from src.tools import bitgn_dispatcher
from src.trace import BenchmarkTrace, TaskTrace, build_answers_digest, build_failure_digest, save_trace

BITGN_URL = os.getenv("BENCHMARK_HOST", "https://api.bitgn.com")
BITGN_API_KEY = os.getenv("BITGN_API_KEY", "")

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"


def _start_leaderboard_run(client: HarnessServiceClientSync, *, run_name: str, benchmark_id: str, leaderboard_api_key: str):
    """Start a leaderboard run across old/new API shapes."""
    request_kwargs = {
        "name": run_name,
        "benchmark_id": benchmark_id,
    }
    if "api_key" in StartRunRequest.DESCRIPTOR.fields_by_name:
        request_kwargs["api_key"] = leaderboard_api_key
        return client.start_run(StartRunRequest(**request_kwargs))

    request = StartRunRequest(**request_kwargs)
    header_variants = []
    if leaderboard_api_key:
        header_variants = [
            {"x-api-key": leaderboard_api_key},
            {"X-Api-Key": leaderboard_api_key},
            {"authorization": f"Bearer {leaderboard_api_key}"},
            {"Authorization": f"Bearer {leaderboard_api_key}"},
        ]

    last_error = None
    for headers in header_variants or [None]:
        try:
            return client.start_run(request, headers=headers)
        except ConnectError as exc:
            last_error = exc
            message = str(exc).lower()
            if "api key" not in message and "auth" not in message:
                raise

    if last_error is not None:
        raise last_error
    return client.start_run(request)


def _is_pcm(benchmark_id: str) -> bool:
    """Check if benchmark uses the PCM runtime."""
    return "pac1" in benchmark_id


def create_provider(name: str, benchmark_id: str = "bitgn/sandbox"):
    """Factory for LLM providers with runtime-appropriate tool definitions."""
    if _is_pcm(benchmark_id):
        from src.tool_defs import pcm_anthropic_tools, pcm_openai_tools
        anthropic_tools = pcm_anthropic_tools()
        openai_tools = pcm_openai_tools()
    else:
        anthropic_tools = None  # use provider defaults
        openai_tools = None

    if name == "anthropic":
        from src.providers.anthropic_provider import AnthropicProvider
        return AnthropicProvider(tools=anthropic_tools)
    elif name == "openai":
        from src.providers.openai_provider import OpenAIProvider
        return OpenAIProvider(tools=openai_tools)
    elif name == "responses":
        from src.providers.responses_provider import ResponsesProvider
        return ResponsesProvider()
    else:
        raise ValueError(f"Unknown provider: {name}. Use 'anthropic', 'openai', or 'responses'.")


def run_benchmark(
    provider_name: str,
    prompt_template: str | None = None,
    task_filter: list[str] | None = None,
    prompt_version: str = "default",
    config: AgentConfig | None = None,
    benchmark_id: str = "bitgn/sandbox",
    run_name: str = "WEA v1",
    leaderboard_api_key: str = "",
) -> BenchmarkTrace:
    """Run the full benchmark and return a structured trace.

    Args:
        provider_name: 'anthropic' or 'openai'
        prompt_template: Custom system prompt template (with {task_text} placeholder).
                        If None, uses the default tuned prompt.
        task_filter: Optional list of task_ids to run (e.g. ['t01', 't02']).
        prompt_version: Label for this prompt version (e.g. 'gen_003').
        config: Optional AgentConfig for feature flags.
        benchmark_id: Benchmark to run ('bitgn/sandbox' or 'bitgn/pac1-dev').
        run_name: Display name for this run on the leaderboard (used when BITGN_API_KEY is set).

    Returns:
        BenchmarkTrace with all task traces, scores, and metadata.
    """
    config = config or DEFAULT_CONFIG
    provider = create_provider(provider_name, benchmark_id)
    prompt_text = prompt_template or ""
    pcm = _is_pcm(benchmark_id)

    # PCM runtime: auto-enable warmup when router is active (needs vault outline)
    if pcm and config.router and not config.warmup:
        config.warmup = True

    # Get runtime-specific tool_models and completion class
    if pcm:
        from src.pcm_models import PcmReportCompletion
        from src.tool_defs import pcm_tool_models
        tool_models = pcm_tool_models()
        completion_cls = PcmReportCompletion
    else:
        tool_models = None
        completion_cls = None

    trace = BenchmarkTrace(
        provider=provider.provider_name(),
        prompt_version=prompt_version,
        prompt_text=prompt_text,
    )

    try:
        client = HarnessServiceClientSync(BITGN_URL)
        status = client.status(StatusRequest())
        print(f"Connected to BitGN: {status}")

        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=benchmark_id))
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks."
        )

        def _run_trial(trial_id_or_task_id, *, leaderboard_trial_id: str | None = None):
            """Run a single trial and return its TaskTrace. Used by both flows."""
            nonlocal trial
            if leaderboard_trial_id is not None:
                trial = client.start_trial(StartTrialRequest(trial_id=leaderboard_trial_id))
                task_id = trial.task_id
            else:
                trial = client.start_playground(
                    StartPlaygroundRequest(
                        benchmark_id=benchmark_id,
                        task_id=trial_id_or_task_id,
                    )
                )
                task_id = trial_id_or_task_id

            print("=" * 60)
            print(f"TASK: {task_id}")
            print(f"Instruction: {trial.instruction}\n")

            system_prompt = build_system_prompt(trial.instruction, prompt_template)

            try:
                if pcm:
                    from bitgn.vm.pcm_connect import PcmRuntimeClientSync
                    from src.pcm_tools import pcm_dispatcher
                    vm = PcmRuntimeClientSync(trial.harness_url)
                    dispatcher = pcm_dispatcher(vm)
                else:
                    from bitgn.vm.mini_connect import MiniRuntimeClientSync
                    vm = MiniRuntimeClientSync(trial.harness_url)
                    dispatcher = bitgn_dispatcher(vm)

                from src.agent import run_agent
                task_trace = run_agent(
                    provider=provider,
                    provider_name=provider_name,
                    dispatcher=dispatcher,
                    task_text=trial.instruction,
                    system_prompt_override=system_prompt,
                    config=config,
                    tool_models=tool_models,
                    completion_cls=completion_cls,
                )
            except Exception as e:
                print(f"{CLI_RED}Agent error: {e}{CLI_CLR}")
                import traceback
                traceback.print_exc()
                task_trace = TaskTrace(
                    task_id=task_id,
                    instruction=trial.instruction,
                    error=str(e),
                )

            result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
            task_trace.task_id = task_id
            if result.score >= 0:
                task_trace.score = result.score
                task_trace.score_detail = list(result.score_detail)
                style = CLI_GREEN if result.score == 1 else CLI_RED
                explain = textwrap.indent("\n".join(result.score_detail), "  ")
                print(f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}")

            return task_trace

        trial = None  # will be set inside _run_trial

        if leaderboard_api_key:
            # Leaderboard flow: start_run → start_trial per slot → submit_run
            run = _start_leaderboard_run(
                client,
                run_name=run_name,
                benchmark_id=benchmark_id,
                leaderboard_api_key=leaderboard_api_key,
            )
            print(f"Leaderboard run started: {run.run_id}")
            try:
                for lid in run.trial_ids:
                    # Peek at task_id without consuming the trial slot
                    peek = client.start_trial(StartTrialRequest(trial_id=lid))
                    if task_filter and peek.task_id not in task_filter:
                        continue
                    # Re-use the already-started trial (trial object is set inside)
                    trial = peek
                    task_id = trial.task_id
                    print("=" * 60)
                    print(f"TASK: {task_id}")
                    print(f"Instruction: {trial.instruction}\n")
                    system_prompt = build_system_prompt(trial.instruction, prompt_template)
                    try:
                        if pcm:
                            from bitgn.vm.pcm_connect import PcmRuntimeClientSync
                            from src.pcm_tools import pcm_dispatcher
                            vm = PcmRuntimeClientSync(trial.harness_url)
                            dispatcher = pcm_dispatcher(vm)
                        else:
                            from bitgn.vm.mini_connect import MiniRuntimeClientSync
                            vm = MiniRuntimeClientSync(trial.harness_url)
                            dispatcher = bitgn_dispatcher(vm)
                        from src.agent import run_agent
                        task_trace = run_agent(
                            provider=provider,
                            provider_name=provider_name,
                            dispatcher=dispatcher,
                            task_text=trial.instruction,
                            system_prompt_override=system_prompt,
                            config=config,
                            tool_models=tool_models,
                            completion_cls=completion_cls,
                        )
                    except Exception as e:
                        print(f"{CLI_RED}Agent error: {e}{CLI_CLR}")
                        import traceback
                        traceback.print_exc()
                        task_trace = TaskTrace(
                            task_id=task_id,
                            instruction=trial.instruction,
                            error=str(e),
                        )
                    result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
                    task_trace.task_id = task_id
                    if result.score >= 0:
                        task_trace.score = result.score
                        task_trace.score_detail = list(result.score_detail)
                        style = CLI_GREEN if result.score == 1 else CLI_RED
                        explain = textwrap.indent("\n".join(result.score_detail), "  ")
                        print(f"\n{style}Score: {result.score:0.2f}\n{explain}\n{CLI_CLR}")
                    trace.traces.append(task_trace)
            finally:
                client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))
                print(f"Run submitted: {run.run_id}")
        else:
            # Playground flow (no leaderboard): start_playground per task
            for t in res.tasks:
                if task_filter and t.task_id not in task_filter:
                    continue
                task_trace = _run_trial(t.task_id)
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


def print_multi_run_summary(all_traces: list[BenchmarkTrace]) -> None:
    """Print aggregated stats across multiple benchmark runs."""
    from collections import Counter

    n_runs = len(all_traces)
    scores = [t.total_score for t in all_traces]
    avg = sum(scores) / n_runs
    lo, hi = min(scores), max(scores)

    # Per-task pass rate
    task_passes: Counter[str] = Counter()
    task_total: Counter[str] = Counter()
    for trace in all_traces:
        for t in trace.traces:
            task_total[t.task_id] += 1
            if t.score >= 1.0:
                task_passes[t.task_id] += 1

    print("\n" + "=" * 60)
    print(f"MULTI-RUN SUMMARY ({n_runs} runs)")
    print(f"  Avg: {avg * 100:.1f}%  Min: {lo * 100:.1f}%  Max: {hi * 100:.1f}%")
    print(f"  Scores: {', '.join(f'{s*100:.0f}%' for s in scores)}")
    print()

    # Sort by pass rate (worst first)
    all_tasks = sorted(task_total.keys(), key=lambda tid: (int(tid[1:]) if tid[1:].isdigit() else 0))
    for tid in all_tasks:
        total = task_total[tid]
        passed = task_passes[tid]
        rate = passed / total
        if rate == 1.0:
            style = CLI_GREEN
        elif rate == 0.0:
            style = CLI_RED
        else:
            style = "\x1B[33m"  # yellow
        bar = "█" * passed + "░" * (total - passed)
        print(f"  {tid}: {style}{bar} {passed}/{total} ({rate*100:.0f}%){CLI_CLR}")

    # Highlight unstable and hard tasks
    flaky = [tid for tid in all_tasks if 0 < task_passes[tid] < task_total[tid]]
    never = [tid for tid in all_tasks if task_passes[tid] == 0]
    if flaky:
        print(f"\n  Flaky (vault-dependent): {', '.join(flaky)}")
    if never:
        print(f"  Never passed: {', '.join(never)}")


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
        elif args[i] == "--planner-model" and i + 1 < len(args):
            config.planner_model = args[i + 1]
            i += 2
        elif args[i] == "--executor-fixed-model" and i + 1 < len(args):
            config.executor_fixed_model = args[i + 1]
            i += 2
        elif args[i] == "--disable-executor-tier-routing":
            config.disable_executor_tier_routing = True
            i += 1
        elif args[i] == "--watchdog-model" and i + 1 < len(args):
            config.watchdog_model = args[i + 1]
            i += 2
        elif args[i] == "--watchdog-gate-model" and i + 1 < len(args):
            config.watchdog_gate_model = args[i + 1]
            i += 2
        elif args[i] == "--watchdog-deterministic-first":
            config.watchdog_deterministic_first = True
            i += 1
        elif args[i] == "--router":
            config.router = True
            config.enrichment = True
            i += 1
        elif args[i] == "--complex-model" and i + 1 < len(args):
            config.complex_model = args[i + 1]
            config.router = True  # model routing requires router
            config.enrichment = True
            i += 2
        elif args[i] == "--genome":
            config.use_genome = True
            config.warmup = True  # genome mode requires warmup (planner needs vault context)
            config.enrichment = True
            config.defense_mode = "soft_block"  # hard blocks data entirely; soft_block shows with warning
            config.step_validator = True
            i += 1
        elif args[i] == "--hybrid":
            config.hybrid = True
            config.warmup = True
            config.enrichment = True
            config.defense_mode = "soft_block"
            config.step_validator = True
            i += 1
        elif args[i] == "--phase-length" and i + 1 < len(args):
            config.hybrid_phase_length = int(args[i + 1])
            i += 2
        elif args[i] == "--executor-model" and i + 1 < len(args):
            config.hybrid_executor_model = args[i + 1]
            i += 2
        elif args[i] == "--controller-model" and i + 1 < len(args):
            config.hybrid_controller_model = args[i + 1]
            i += 2
        elif args[i] == "--dual":
            config.use_genome = True
            config.dual_executor = True
            config.planner_loop = True
            config.warmup = True
            config.enrichment = True
            config.defense_mode = "soft_block"
            config.step_validator = True
            i += 1
        elif args[i] == "--planner-loop":
            config.use_genome = True
            config.planner_loop = True
            config.warmup = True
            config.enrichment = True
            config.defense_mode = "soft_block"
            config.step_validator = True
            i += 1
        elif args[i] == "--planner54-executor41":
            config.use_genome = True
            config.planner_loop = True
            config.warmup = True
            config.enrichment = True
            config.defense_mode = "soft_block"
            config.step_validator = True
            config.watchdog = True
            config.planner_model = "gpt-5.4"
            config.executor_fixed_model = "gpt-4.1"
            config.disable_executor_tier_routing = True
            config.watchdog_model = "gpt-5.4-mini"
            config.watchdog_gate_model = "gpt-5.4-mini"
            config.watchdog_deterministic_first = True
            i += 1
        elif args[i] == "--replan-every" and i + 1 < len(args):
            config.planner_replan_every = int(args[i + 1])
            i += 2
        elif args[i] == "--replan-from-step" and i + 1 < len(args):
            config.planner_replan_min_step = int(args[i + 1])
            i += 2
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
    # Parse args: task filter, provider, benchmark, and feature flags
    task_filter = []
    provider_name = os.getenv("LLM_PROVIDER", "anthropic")
    benchmark_id = os.getenv("BENCHMARK_ID", "bitgn/sandbox")
    run_name = "WEA v1"
    leaderboard_api_key = BITGN_API_KEY

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
        elif args[i] == "--benchmark" and i + 1 < len(args):
            benchmark_id = args[i + 1]
            i += 2
        elif args[i].startswith("--benchmark="):
            benchmark_id = args[i].split("=", 1)[1]
            i += 1
        elif args[i] == "--run-name" and i + 1 < len(args):
            run_name = args[i + 1]
            i += 2
        elif args[i] == "--no-submit":
            leaderboard_api_key = ""
            i += 1
        else:
            task_filter.append(args[i])
            i += 1

    print(f"Provider: {provider_name}")
    print(f"Benchmark: {benchmark_id}")
    if config.warmup:
        print("Features: warmup=ON")
    if config.compress_history:
        print("Features: compression=ON")
    if config.enrichment:
        print(f"Features: enrichment=ON, defense={config.defense_mode}")
    if config.step_validator:
        print("Features: step_validator=ON")
    if config.router:
        print(f"Features: router=ON (model={config.router_model})")
    if config.complex_model:
        print(f"Features: complex_model={config.complex_model}")
    if config.watchdog:
        print(
            f"Features: watchdog=ON "
            f"(model={config.watchdog_model}, gate={config.watchdog_gate_model}, "
            f"mode={'deterministic-first' if config.watchdog_deterministic_first else 'llm-midstream'}, "
            f"every={config.watchdog_check_every} steps, "
            f"from step {config.watchdog_min_step})"
        )
    if config.planner_loop:
        print(
            f"Features: planner_loop=ON "
            f"(replan_every={config.planner_replan_every}, "
            f"from_step={config.planner_replan_min_step}, "
            f"max_escalations={config.max_escalations})"
        )
    if config.hybrid:
        print(
            f"Features: hybrid=ON "
            f"(controller={config.hybrid_controller_model}, "
            f"executor={config.hybrid_executor_model}, "
            f"phase_length={config.hybrid_phase_length}, "
            f"max_steps={config.hybrid_max_steps})"
        )
    if config.dual_executor:
        print("Features: dual_executor=ON")
    if config.disable_executor_tier_routing:
        print(
            f"Features: executor_fixed_model={config.executor_fixed_model} "
            f"(tier_routing=OFF, planner_model={config.planner_model})"
        )

    if leaderboard_api_key:
        print(f"Leaderboard: ON (run_name={run_name!r})")
    else:
        print("Leaderboard: OFF (set BITGN_API_KEY to enable)")

    trace = run_benchmark(
        provider_name=provider_name,
        task_filter=task_filter if task_filter else None,
        config=config,
        benchmark_id=benchmark_id,
        run_name=run_name,
        leaderboard_api_key=leaderboard_api_key,
    )

    print_summary(trace)

    timestamp = trace.timestamp.replace(":", "").replace("-", "")
    safe_name = run_name.replace(" ", "-")
    logs_dir = os.path.join(_PROJECT_ROOT, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    trace_path = os.path.join(logs_dir, f"{safe_name}-{timestamp}-trace.json")
    save_trace(trace_path, trace)
    print(f"Saved trace: {trace_path}")
    answers_path = os.path.join(logs_dir, f"{safe_name}-{timestamp}-answers.json")
    with open(answers_path, "w", encoding="utf-8") as f:
        json.dump(build_answers_digest(trace), f, indent=2, ensure_ascii=False)
    print(f"Saved answers digest: {answers_path}")
    if trace.failed_tasks:
        failure_path = os.path.join(logs_dir, f"{safe_name}-{timestamp}-failures.json")
        with open(failure_path, "w", encoding="utf-8") as f:
            json.dump(build_failure_digest(trace), f, indent=2, ensure_ascii=False)
        print(f"Saved failure digest: {failure_path}")


if __name__ == "__main__":
    main()
