# mlb-betting

Standalone MLB betting research and live-operations repository.

The active production path is intentionally narrow:

- rules-based live strategies
- promoted CatBoost models
- fail-closed daily capture, health checks, and runtime contracts

Genome-based LLM experiments remain in the repo as archive material, but they
are not part of the current production contract.

## Quick Start

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -U pip
pip install -e ".[dev]"
```

Local operator setup:

```bash
cp .env.example .env
```

`data/fetch_2026/state.json` and `data/fetch_2026/pitcher_cache.json` are
local-only runtime files. If they are missing, the repo seeds them from the
committed `*.example.json` files on first use.

## Active Operations

Canonical scheduled runner:

```bash
python scripts/mlb_daily_capture.py
```

Strict health/runtime checks:

```bash
python scripts/check_2026_pipeline.py --strict-freshness
python scripts/check_live_runtime_contract.py --date YYYY-MM-DD
python scripts/generate_picks_2026.py --date YYYY-MM-DD --dry-run --no-poly
```

Manual recovery:

```bash
python scripts/fetch_daily_2026.py --phase pregame --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --phase pitchers --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --phase postgame-full --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --phase savant --date YYYY-MM-DD
python scripts/fetch_daily_2026.py --backfill-savant YYYY-MM-DD YYYY-MM-DD
```

Runbook: `knowledge/live_ops_runbook.md`

## Repository Layout

- `src/` — core feature, model, strategy, and live-runtime code
- `scripts/` — operational runners and research scripts
- `tests/` — regression and runtime-contract coverage
- `knowledge/` — session docs, reports, and working memory
- `site/` — static research/archive pages
- `genomes/`, `src/llm_*` — legacy LLM research archive

## Archive Note

The genome-based expert system is retained for reproducibility and historical
research only. New production work should assume the repo lives independently
of WeTheAgents domain routing and independently of genome evolution workflows.
