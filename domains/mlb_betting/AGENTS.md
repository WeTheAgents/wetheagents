# MLB Betting — Repository Context

`mlb_betting` is a standalone repository for MLB betting research and live operations.

## Active Production Scope

- Rules-based live strategies
- Live data capture and health/runtime checks
- CatBoost-backed models that are already promoted into production

Canonical live command:

```bash
python scripts/mlb_daily_capture.py
```

## Archive Scope

The repository also keeps historical research artifacts:

- `genomes/`
- `src/llm_*`
- legacy calibration/debug scripts for genome-based experiments
- `site/` static research pages

These are archive/reference material. They are not part of the active live path,
CI contract, or operator runbook unless explicitly promoted again.

## Local-Only Files

These stay out of git and are auto-bootstrapped locally when needed:

- `.env`
- `.claude/`
- `data/fetch_2026/state.json`
- `data/fetch_2026/pitcher_cache.json`
- `data/raw/`
- `data/processed/`
- `retrosheets/*.zip`
- generated `picks/` outputs

Committed examples live at:

- `data/fetch_2026/state.example.json`
- `data/fetch_2026/pitcher_cache.example.json`

## Working Rules

- Treat the repository root as the project root. Do not assume a surrounding monorepo.
- Keep production docs and workflows focused on rules/ML/live ops.
- Do not add genome-based research back into the production path without an explicit promotion decision.
- Prefer repo-relative paths or env/config-driven paths over machine-specific absolute paths.
