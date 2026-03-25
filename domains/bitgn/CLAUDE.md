# BitGN Agent

Agent for BitGN benchmarks (Sandbox + PAC1). Explores vaults via gRPC tools, solves tasks, defends against prompt injection.

## Running

```bash
cd domains/bitgn
uv sync
cp .env.example .env  # fill in API keys

# Sandbox benchmark (mini runtime — default)
uv run python src/main.py              # full benchmark
uv run python src/main.py t01          # single task
uv run python src/main.py --provider openai  # switch provider

# PAC1 benchmark (PCM runtime)
uv run python src/main.py --benchmark bitgn/pac1-dev
uv run python src/main.py --benchmark bitgn/pac1-dev t01
```

## Architecture

- `src/main.py` -- entry point, connects to BitGN API, selects runtime (mini/PCM)
- `src/agent.py` -- core agent loop (provider-agnostic, runtime-agnostic)
- `src/models.py` -- Pydantic models for mini runtime tools
- `src/pcm_models.py` -- Pydantic models for PCM runtime tools (PAC1)
- `src/tools.py` -- dispatch mini tool models to gRPC calls
- `src/pcm_tools.py` -- dispatch PCM tool models to gRPC calls
- `src/tool_defs.py` -- tool definition builders for both runtimes
- `src/prompts.py` -- system prompt with injection defense
- `src/defense.py` -- content sanitization, injection pattern detection
- `src/providers/` -- swappable LLM backends (anthropic, openai)

## Runtimes

| Runtime | Benchmark | Tools |
|---------|-----------|-------|
| Mini | `bitgn/sandbox` | outline, read, list, search, write, delete |
| PCM | `bitgn/pac1-dev` | tree, find, search, list, read, context, write, delete, mkdir, move |
