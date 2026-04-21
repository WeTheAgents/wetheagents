# Claude Code Instructions -- mlb-betting

## Project Positioning

`mlb_betting` is now a standalone repository. Treat the repository root as the
project root and do not assume any surrounding WEA domain machinery.

## Active Production Surface

Use these paths and commands for live/operator work:

```bash
python scripts/mlb_daily_capture.py
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

The live system is fail-closed. Treat these as hard blockers:

- stale Savant outputs
- dropped live games between overlay and enriched frame
- missing production strategy source / registry drift
- failed post-run health or runtime checks

## Runtime Data Rules

These stay local-only and must not be committed:

- `.env`
- `.claude/`
- `data/fetch_2026/state.json`
- `data/fetch_2026/pitcher_cache.json`
- `data/raw/`
- `data/processed/`
- `retrosheets/*.zip`
- generated `picks/` outputs

Committed seeds/examples:

- `data/fetch_2026/state.example.json`
- `data/fetch_2026/pitcher_cache.example.json`

The repo auto-materializes `state.json` and `pitcher_cache.json` from those
examples when they are missing.

## Data / Feature Notes

- Historical seasons: 2004-2019, 2021-2025; 2020 excluded
- `apply_data_filters()` removes missing odds/pitcher rows, doubleheaders, and extreme cases
- Never bet Colorado games
- September is currently allowed
- `home_run_line` in raw data is mixed RL/total and must be filtered carefully

## Archive / Legacy Research

These are retained for reproducibility and historical context, not as active
production surfaces:

- `genomes/`
- `src/llm_expert.py`, `src/llm_duel.py`, `src/llm_evolution.py`
- genome-heavy calibration/debug scripts
- `site/`

If you touch those paths, keep them repo-relative and archive-safe. Do not
route new production work through genome-based experts unless there is an
explicit promotion decision.
