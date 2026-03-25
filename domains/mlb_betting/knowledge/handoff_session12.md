# Session 12 Handoff — LLM Expert Duel: Offense & Bullpen Enhancement

## What was done

### 1. New features in `src/features.py`
- **`calc_league_relative(log)`** — computes `offense_vs_league` and `defense_vs_league` as ratios of team cumulative RPG/RAPG to league cumulative average. Season-scoped, no look-ahead. Values >1.0 = above average.
- **`calc_late_game_metrics(log, window=30, min_qualifying=5)`** — rolling 30-game window for:
  - `hold_rate`: win% when leading after 6 innings
  - `close_game_wp`: win% in 1-2 run margin games
  - `deficit_recovery_rate`: win% when trailing after 6 innings
  - All NaN for 2004-2009 (fake inning data)

### 2. Modified `build_team_game_log()` in `src/features.py`
Added columns derived from inning-by-inning data: `score_after_6`, `opp_score_after_6`, `leading_after_6`, `trailing_after_6`, `close_game`, `margin`. All NaN when `has_real_inn = False` (2004-2009 seasons where all 9 innings sum to 0).

### 3. Modified `build_all_features()` in `src/features.py`
- Calls `calc_league_relative()` and `calc_late_game_metrics()` after existing feature computation
- Merges results into the feature chain
- Renames to `*_home` / `*_away` suffixes
- Computes 5 new diff columns: `offense_vs_league_diff`, `defense_vs_league_diff`, `hold_rate_diff`, `close_game_wp_diff`, `deficit_recovery_diff`

### 4. New card sections in `src/feature_card.py`
- **`_offense_context(row)`** — renders "Offense & Defense vs League" with contextual labels (STRONG >110%, ABOVE AVG 105-110%, AVERAGE 95-105%, BELOW AVG <95%). Includes caution flag when both lineups elite.
- **`_bullpen_management(row)`** — renders "Bullpen & Late Game" with hold rate, close-game W%, deficit recovery. Labels: hold (ELITE/STRONG/AVERAGE/WEAK), close-game WP (STRONG/AVERAGE/WEAK), recovery (GOOD/AVERAGE/LOW).
- Neutral variants: `_neutral_offense_context()`, `_neutral_bullpen_management()` for AnalystCard.
- Label helpers: `_label_offense()`, `_label_defense()`, `_label_hold()`, `_label_close_wp()`, `_label_recovery()`.

### 5. Genome updates
- **`genomes/analyst_v1.yaml`**: +2 principles (#6 hold rate shapes late-game narrative, #7 offense vs league > raw RPG)
- **`genomes/momentum_v1.yaml`**: +2 principles (#6 both STRONG offense = pitcher quality matters less, #7 ELITE hold rate = dog needs early advantage)
- **`genomes/value_v1.yaml`**: +2 principles (#6 FIP less reliable vs STRONG offense, #7 close-game W% + hold rate reveal bullpen quality)

### 6. Expert prompt update in `src/llm_expert.py`
Added variance awareness sentence to Context section: "Remember: a single 3-run homer or defensive collapse can decide any game. Your edge is over 100+ games, not any single outcome."

## Bug fixed during session
- `calc_league_relative()` had `dates.sort()` on a `DatetimeArray` which doesn't have in-place sort. Fixed to `np.sort(dates)`.

## What remains — dry-run failed, fix needed

The `--dry-run` run of `scripts/run_6game_calibration.py` crashed on the `dates.sort()` bug (now fixed). **The dry-run has NOT been re-run yet.**

### Immediate next steps:
1. **Re-run dry-run**: `python scripts/run_6game_calibration.py --dry-run` — verify new card sections render correctly with real data
2. **Review card output** — check that offense_vs_league, hold_rate, close_game_wp, deficit_recovery_rate populate for 2024 games (they should — real inning data available)
3. **Run full calibration** — `python scripts/run_6game_calibration.py` (requires OPENAI_API_KEY in `.env`) — compare new verdicts with previous results in `knowledge/calibration_6game_report.md`

### Operator decisions from this session:
- **BAL@LAD is NOT a system error** — Burnes was great (5 IP, 1 ER), loss due to 3 defensive errors + 3-run HR. This is game variance, not a signal failure.
- **Rejected**: late-game RA metric (Ichiro-on-the-mound precedent in lost games) and run differential in innings 7-9
- **Approved**: hold rate, close-game W%, deficit recovery rate, offense/defense vs league average

### Files modified:
- `src/features.py` — new functions + build_team_game_log + build_all_features integration
- `src/feature_card.py` — 4 new section builders + 5 label helpers
- `src/llm_expert.py` — 1 sentence added to Context
- `genomes/analyst_v1.yaml` — +2 principles
- `genomes/momentum_v1.yaml` — +2 principles
- `genomes/value_v1.yaml` — +2 principles

### Previous session context:
- 6 hand-picked calibration games from 2024 expansion zone defined in `scripts/run_6game_calibration.py`
- Previous calibration results saved in `knowledge/calibration_6game_report.md`
- Expansion zone parquets: `_tmp_s3_exp.parquet`, `_tmp_rl_exp.parquet`
