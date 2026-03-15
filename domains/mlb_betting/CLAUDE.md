# Claude Code Instructions -- mlb-betting

## Project Overview

MLB baseball betting backtest system. Goal: find profitable strategies for Polymarket MLB markets starting April 2026.

**Three approaches tested in parallel:**
1. **Rules-based** -- expert criteria from legacy system (RPI, pitcher stats, form)
2. **LLM estimator** -- GPT-4o-mini via OpenAI Batch API generates fair odds per game
3. **CatBoost ML** -- gradient boosting on 35+ features

## Data

- **Source**: sports-statistics.com xlsx (2010-2019, 2021; 2020 excluded for COVID)
- **Download**: `python data/download.py` (downloads to data/raw/odds/)
- **Load**: `from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds`
- **Key numbers**: 27,109 raw games -> 26,420 filtered -> 20,511 bettable

## Running Analysis

```bash
# Feature computation (~3 min)
python -c "from src.features import build_all_features; from src.data_loader import *; g=load_all_seasons(); g=apply_data_filters(g); g=add_derived_odds(g); e=build_all_features(g)"

# Series dogon backtest
python scripts/run_series_backtest.py

# Series with RPI/WP/streak filters
python scripts/run_series_with_features.py

# Run Line analysis (real odds)
python scripts/run_runline_real_odds.py

# Streak analysis
python scripts/run_streak_analysis.py
```

## Key Filters (ALWAYS apply)

```python
from src.data_loader import apply_data_filters, add_derived_odds
games = apply_data_filters(games)  # Hard: remove 2020, missing odds/pitcher, double-headers
games = add_derived_odds(games)    # Add decimal odds, implied probs

# Betting filters (apply before selecting bets):
bettable = games[
    ~games["involves_col"]       # Never bet on Colorado games
    & ~games["is_september"]     # Skip September tanking
    & ~games["is_extreme_line"]  # Skip extreme favorites (>300)
]
```

## Architecture Notes

- `src/data_loader.py` -- data loading, pairing home/away, filters
- `src/market_builder.py` -- construct YRFI, F5, Race to X from inning scores
- `src/features.py` -- rolling RPI, WP, streaks, RPG + pitcher integration (67 features total)
- `src/pitcher_features.py` -- pitcher proxy oscillators (WR, RA, 1st inn, short/long/momentum)
- `src/series.py` -- series identification, dogon engine, backtest runner
- `scripts/` -- standalone analysis scripts (no Jupyter needed)
- `knowledge/` -- research docs, legacy feature catalog, status reports
- `notebooks/` -- exploratory analysis (00-02 complete)

## Important Data Quirk

`home_run_line` column contains MIXED data:
- Values -1.5 and 1.5 = actual Run Line (spread)
- Values 5.5+ = Over/Under total (misclassified in raw data)
- Filter by `home_run_line.isin([-1.5, 1.5])` for actual RL analysis

## Status

See `knowledge/status_report_session3.md` for detailed status with results.

Current findings: pitcher proxy features + team RPI = profitable series dogon.
- Best config: RPI>=0.03 + WP>=0.05 + SP_RA<=0 + SP_WR>=0.10
- Out-of-sample validated: +5.21% ROI on TEST (2018-2021), +1.75% on TRAIN (2010-2017)
- 67 features total (35 team + 32 pitcher)
Next steps: Run Line, YRFI, flat ML betting with pitcher features.
