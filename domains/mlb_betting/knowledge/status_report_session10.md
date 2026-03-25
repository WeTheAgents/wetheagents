# Session 10 — Over/Under Totals Strategy

## Goal
Adapt the regime-split CatBoost+Ridge model to O/U totals betting. Find profitable OVER or UNDER strategies using the same architecture as the S3 underdog system.

## Approach

### Model Architecture
- **Target**: `close_ou` (the O/U line, not total_runs) — analogous to predicting `closing_decimal_odds_favorite` in the ML model
- **Regimes**: T0 (all), T_OVER2 (went over by 2+), T_OVER1 (close over), T_UNDER (went under)
- **Features**: 23 total (16 used after ou_line_move exclusion):
  - SUM-based: combined_rpg, combined_rapg, combined_rpg_last10, combined_rapg_last10, sp_ra_combined_short/long, starter_fip_combined, starter_whip_combined, sp_quality_floor
  - Bullpen SUM: bullpen_fip_combined, bullpen_whip_combined, bullpen_k9_combined, bullpen_kbb_combined, bullpen_ip_3d_combined, bullpen_pitchers_3d_combined, bullpen_ip_1d_combined
  - DIFF-based: rpg_diff, rapg_diff, pyth_wp_diff, sp_ra_short_diff, elo_diff
  - Context: home_advantage
- **Edge**: `predicted_line - close_ou`. Positive = OVER signal, Negative = UNDER signal
- **Odds**: Standard -110/-110 (decimal 1.909, breakeven 52.38%)
- **Walk-forward**: Same as ML model (train N seasons, val 1, test 2)

### Key Design Decision
First attempt used `total_runs` as target — failed (RMSE 4.37, worse than naive baseline 4.30). Switched to `close_ou` (the market line) as target — model predicts "fair line" much better (RMSE 0.75, Corr 0.68).

## Results

### OVER: Not Profitable
Even with best filters, OVER never sustainably beats 52.38% breakeven.
- Best single filter: sp_ra>8.0 + edge>1.5 → 139 bets, 56.1% hit, +7.1% ROI (but only 5/11 seasons, high variance)
- Most combos hover 49-51% hit rate → negative ROI after -110 juice

### UNDER: Profitable Signal Found

**Best strategy: `sp_ra_combined < 8.0 + edge < -1.0 + 2nd half (post-ASG)`**

| Metric | Value |
|--------|-------|
| Bets | 251 (23/season) |
| Hit rate | 57.8% |
| ROI | +10.3% |
| Sharpe | 0.520 |
| Kelly half | 5.7% |
| Max loss streak | 6 |
| Max drawdown | 7.5% |
| Profitable seasons | **9/11** |
| PnL (flat $100) | +$2,581 |

**Logic**: Both starting pitchers have LOW combined runs allowed (sp_ra < 8.0 = quality starts), model predicts the line should be lower than market (edge < -1.0), and it's 2nd half of season when these mispricings are exploitable.

### Per-Season Breakdown
| Season | Bets | Hit% | ROI |
|--------|------|------|-----|
| 2010 | 7 | 85.7% | +63.6% |
| 2011 | 18 | 72.2% | +37.9% |
| 2012 | 40 | 55.0% | +5.0% |
| 2013 | 31 | 54.8% | +4.7% |
| 2014 | 30 | 63.3% | +20.9% |
| **2015** | **16** | **31.2%** | **-40.3%** |
| 2016 | 14 | 71.4% | +36.4% |
| 2017 | 47 | 57.4% | +9.7% |
| 2018 | 19 | 52.6% | +0.5% |
| 2019 | 17 | 64.7% | +23.5% |
| **2021** | **12** | **41.7%** | **-20.5%** |

### Bullpen Enhancement
Adding bullpen quality filters improves ROI but reduces volume:
- `+ bp_fip < 7.4`: 135 bets, 59.3% hit, **+13.1% ROI**, 8/11 seasons
- `+ bp_k9 > 17.2`: 130 bets, 59.2% hit, **+13.1% ROI**, 7/11 seasons
- `+ bp_ip_3d < 17.0`: 123 bets, 56.9% hit, +8.6% ROI, 7/11 seasons (lowest MaxDD: 4.7%)

### Monthly Pattern
| Month | Bets | Hit% | ROI | Notes |
|-------|------|------|-----|-------|
| July (1H) | 68 | 64.7% | +23.5% | Best month, ASG transition |
| September | 70 | 62.9% | +20.0% | Post-trade-deadline, stabilized rosters |
| **August** | **108** | **49.1%** | **-6.3%** | Consistently weak across all combos |
| October | 5 | 80.0% | +52.7% | Small sample |

### Regime Distribution (after filters)
- T_OVER2 (total > line+2): 33.1%
- T_OVER1 (total > line by 0-2): 12.9%
- T_UNDER (total <= line): 53.9% — structural UNDER bias after removing Colorado, April, extras

## Data Notes
- 26,605 games after O/U filters (no Colorado, no April, no extras, no extreme lines, close_ou in 5.5-15)
- 839 pushes (total_runs == close_ou) excluded from PnL
- Bullpen features available for ~60% of games (2010-2021 Retrosheet coverage)
- O/U odds unavailable — assumed standard -110/-110

## Files Modified
- `src/features.py` — added `OU_FEATURES` (23 features), `build_ou_features()`, expanded bullpen merge (7 composites)
- `src/model.py` — added `OU_REGIMES`, parameterized `run_walk_forward()` with `regimes` param

## Files Created
- `scripts/run_ou_backtest.py` — full OVER+UNDER backtest with validation

## Next Steps
1. **August exclusion**: August is consistently -6% ROI. Excluding it might boost overall ROI significantly
2. **Portfolio analysis**: Check correlation between UNDER 2H and S3/RL strategies — if uncorrelated, combined Sharpe improves
3. **UNDER as Polymarket strategy**: April 2026 deployment — UNDER bets during 2H with the sp_ra + edge filters
4. **Park factors**: Missing from current features. Could improve model accuracy if added
