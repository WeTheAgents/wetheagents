# BitGN Sandbox Agent

Agent for the BitGN Sandbox benchmark. Explores an Obsidian Vault via gRPC tools, solves tasks, defends against prompt injection.

## Running

```bash
cd domains/bitgn
uv sync
cp .env.example .env  # fill in API keys
uv run python src/main.py              # full benchmark
uv run python src/main.py t01          # single task
uv run python src/main.py --provider openai  # switch provider
```

## Architecture

- `src/main.py` -- entry point, connects to BitGN API, runs benchmark loop
- `src/agent.py` -- core agent loop (provider-agnostic)
- `src/models.py` -- Pydantic models for tools and agent steps
- `src/tools.py` -- dispatch Pydantic tool models to gRPC calls
- `src/prompts.py` -- system prompt with injection defense
- `src/defense.py` -- content sanitization, injection pattern detection
- `src/providers/` -- swappable LLM backends (anthropic, openai)
