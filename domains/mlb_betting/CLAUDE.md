# Claude Code Instructions -- mlb-betting

## Project Overview

MLB baseball betting backtest system. Goal: find profitable strategies for Polymarket MLB markets starting April 2026.

**Three approaches tested in parallel:**
1. **Rules-based** -- expert criteria from legacy system (RPI, pitcher stats, form)
2. **LLM estimator** -- GPT-4o-mini via OpenAI Batch API generates fair odds per game
3. **CatBoost ML** -- gradient boosting on 35+ features

## Data

- **Sources**: 21 seasons (2004-2019, 2021-2025; 2020 excluded for COVID)
  - sports-statistics.com xlsx: 2010-2019, 2021 (original)
  - SportsDatabase.com SDQL API: 2004-2009 (moneyline, OU, scores, starters)
  - ArnavSaraogi JSON + SDQL merge: 2022-2025 (multi-book ML, run line, starters)
- **Download**: `python data/download.py` (original) + `python data/download_historical.py` (new seasons)
- **Load**: `from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds`
- **Key numbers**: ~50,700 raw games -> ~49,700 filtered -> ~38,000 bettable
- **Note**: SDQL/JSON seasons (2004-2009, 2022-2025) lack inning-by-inning scores; run line data only available for 2014+ (original) and 2022-2025 (JSON)

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
    & ~games["is_extreme_line"]  # Skip extreme favorites (>300)
]
# Note: September is now INCLUDED (validated profitable across 5 seasons)
```

## Season Ramp-Up Protocol

Feature coverage depends on games played in the current season:

| Period | Team features | Pitcher features | Action |
|--------|--------------|-----------------|--------|
| **W1 (Apr 1-7)** | 100% (Elo carries over) | 0% | **No bets.** Collect data, shadow-run LLM experts |
| **W2 (Apr 8-14)** | 100% | ~8% | **Start betting:** LLM-MULTI on team features only, ¼ Kelly |
| **W3 (Apr 15-21)** | 100% | ~60% | **Full portfolio, ¼ Kelly.** First genome review (Sunday) |
| **W4+ (Apr 22+)** | 100% | ~70%+ | **Full portfolio, ½ Kelly.** Weekly genome updates (Sundays) |

Genome evolution: experts review weekly results after Sunday series end, update anti-patterns and weights.

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

### Production-Ready Strategies

**1. Fav -1.5 Run Line** (Session 25: `knowledge/session_report_25.md`)
- Filter: impl 62-75% + starter_fip_diff <= -0.2 + power_rate_diff >= 0
- ~137 games/season, 49.8% cover, +19.6% ROI (TRAIN), +15.0% ROI (TEST 2025)
- Optional LLM layer (Analyst + Momentum, gpt-5.4) for refinement

**2. Away +1.5 Bullpen Day** (Session 26: `knowledge/session_report_26.md`)
- Filter: edge>0.05 + home_is_bullpen_day + away_has_starter
- ~24 games/season, Dog ML 74.2% win rate at 2.20 odds = **+63.9% ROI**
- RL +1.5: 83.7% cover = +31.2% ROI
- **11/11 seasons profitable** (2014-2025), validated on 2024-2025
- Tier 2 (bullpen fatigue gap): +35 games/season at ~69% cover

**3. Away +1.5 Pitcher Advantage** (Session 27: `knowledge/session_report_27.md`)
- Filter: away_sp_fip_short<=3.5 + starter_depth_diff<=-1.0 + bp_ip_3d_home>=8
- ~8 games/season, 79.0% cover, **+24.7% ROI** (TRAIN +29.2%, TEST +21.0%)
- Starter-only variant (no BP filter): 135 games, 71.9% cover, +12.3% ROI
- Complements Tier 1 (bullpen day) and Tier 2 (fatigue gap)

### Research — Dead Ends

**Statcast Bullpen xwOBA Mismatch** (Session 28: `knowledge/session_report_28.md`)
- 10 seasons Savant pitch-by-pitch data (2015-2025), aggregated to team bullpen per game
- Tested: xwOBA mismatch, barrel rate mismatch, 3-day fatigue delta, combinations
- **Result: break-even** — 53% WR, -0.2% ROI on 960 games (10 seasons, threshold >=0.05)
- CatBoost feature importance: 1.74% combined (negligible)
- **Why**: market already prices Statcast (public since 2015); managers compensate fatigue
- **Infrastructure retained**: `data/fetch_savant_gamelogs.py`, `src/savant_bullpen.py`, 30 Savant columns in pipeline

### Earlier Work
- Series dogon with pitcher proxy features: +5.21% ROI (TEST)
- 67 features total (35 team + 32 pitcher) + 30 Savant bullpen columns (2015+)
- Walk-forward CatBoost + Ridge ensemble (4 biased regime models)
