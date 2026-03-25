# Session 14 Handoff — Feature Pipeline + CF Zone Breakthrough

## What Was Done

### Feature Pipeline Completion
`build_all_features()` now produces 171 features (was 123). Added:

**From stash (restored):**
- `calc_first_inning_rate(log)` — rolling 1st-inning scoring rate
- `calc_league_relative(log)` — offense/defense as ratio to league average
- `calc_late_game_metrics(log)` — hold_rate, close_game_wp, deficit_recovery_rate
- Inning data extraction in `build_team_game_log()` (scored_in_1st, score_after_6, margins)

**New merges in `build_all_features()`:**
- Pitcher hand from Retrosheet allplayers.csv (15/15 for 2024, 33852/48300 overall)
- Bullpen FIP + workload (moved from `build_spec_features()`, idempotent guard added)
- Batting lineup vs-hand splits (top3_obp_vs_rhp/lhp, effective OBP matchup-aware)

**Coinflip zone fix:**
- `add_derived_odds()` now adds `odds_spread` + `is_coinflip` columns (was in stash, never applied)
- CF games now correctly route to `CF_pickem` zone instead of SKIP

### Pitcher Card Redesign
Removed WR/RA oscillators from pitcher section. Now shows: FIP (with momentum), K/BB, K9, IP/start, pitcher hand (RHP/LHP), batting vs-hand matchup. Added `_diff_or_compute()` for self-sufficient diff calculation.

### Full-Day Calibration Results

| Day | Zones | Bets | Accuracy | P&L | ROI |
|-----|-------|------|----------|-----|-----|
| 2024-06-12 | 5 RL, 5 S3 | 7/10 | 4/7 (57%) | +$272 | +41.9% |
| 2024-08-27 | 5 RL, 3 S3 | 4/8 | 2/4 (50%) | +$32 | +9.3% |
| 2024-07-04 | 7 CF, 3 S3, 1 RL | 5/11 | 4/5 (80%) | +$174 | +43.4% |
| **Total** | | **16/29** | **10/16 (63%)** | **+$478** | **+35.3%** |

**CF Zone breakthrough:** 3/7 bets, 2/3 wins, P&L +$78. Previously 6/6 PASS (zero signal). Value expert now uses offense_vs_league, hold_rate, batting splits to find real edges in pick'em games.

**PASS accuracy:** June 12 PASS pool 0/3 dog wins (perfect filter). Aug 27 PASS pool 3/4 dog wins (too conservative).

## Data Coverage Gaps
- Bullpen FIP/workload: Retrosheet events only built through 2021, NaN for 2022+
- Batting lineup splits: available 2010-2025 (good)
- Pitcher hand: available 2010-2025 via allplayers.csv (good)
- Late-game metrics: NaN for 2004-2009 (no real inning data)

## Files Modified This Session

| File | Changes |
|------|---------|
| `src/features.py` | +3 calc functions, build_all_features pipeline (bullpen/batting/hand merges), build_spec_features idempotent |
| `src/data_loader.py` | odds_spread + is_coinflip in add_derived_odds() |
| `src/feature_card.py` | Pitcher card redesign: FIP/K-BB/K9/IP, hand, matchup, _diff_or_compute() |

## Next Session: Over/Under Expert System

### Goal
Apply the same DuelEngine expert architecture (Momentum + Value genomes → Arbiter) to Over/Under (totals) betting. Currently the system only handles moneyline and run line in S3/RL/CF zones. O/U is a separate market with its own dynamics.

### What Exists
- `close_ou` column in game data (O/U line from closing odds)
- `scripts/run_ou_backtest.py` — regime-split model predicting total runs, bets OVER when prediction > line
- `src/market_builder.py` — F5 over/under using half of game O/U as proxy
- `src/model.py` — OU_REGIMES = ["T0", "T_OVER2", "T_OVER1", "T_UNDER"]
- O/U line shown in feature card context section (low/normal/high-scoring label)

### Key Design Questions
1. **Zone logic for O/U**: Does O/U need zones like S3/RL/CF? Or is it a single zone with its own filter (e.g., only bet when model edge > X)?
2. **Card design**: O/U card needs different framing — not dog/fav but over/under. Key signals: combined RPG, bullpen FIP, pitcher FIP (both), ballpark factor, weather (not available), close_ou line vs historical average
3. **Expert genomes**: Reuse momentum_v1/value_v1 with O/U prompts? Or create dedicated O/U genomes?
4. **Arbitration**: Same 2-expert duel or different? O/U might need different confidence thresholds
5. **Standard odds**: -110/-110 (1.909 decimal, 52.38% breakeven) — fixed in backtest, real lines vary

### Implementation Steps
1. Build O/U feature card section (or separate card) — combined RPG, combined FIP, O/U line, deviation from average
2. Create O/U expert prompts (system prompt framing: "totals evaluator")
3. Wire O/U zone into `run_fullday_calibration.py` — game can be both ML bet AND O/U bet (independent markets)
4. Create O/U-specific output schema: OVER/UNDER/PASS
5. Run calibration on same 3 test days (June 12, July 4, Aug 27)

### Calibration Baseline
From `run_ou_backtest.py` — the regime-split model already has results. Compare expert system accuracy vs pure model to measure expert value-add on totals.
