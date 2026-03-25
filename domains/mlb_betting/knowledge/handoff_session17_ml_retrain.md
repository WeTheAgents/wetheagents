# Session 17: ML Model Retraining with New Features

## Context

Session 16 added powerful new features (hold_rate_after_5, power_rate, effective_obp, close_game_wp, deficit_recovery_rate) that are currently used ONLY in LLM feature cards. The two CatBoost walk-forward models (SPEC 14 features, UNDER 22 features) don't include them yet. This session adds the best candidates and measures impact.

## Current Models

### SPEC (Moneyline probability) — 14 features
- Location: `src/features.py` lines 1081-1096 (SPEC_FEATURES list)
- Training: `src/model.py` → `run_walk_forward()`, 14 folds, 4 regime splits (M0/M2/M3/M4)
- Format: diff (home - away)

### UNDER (O/U classifier) — 22 features
- Location: `src/features.py` lines 1297-1328 (OU_FEATURES list)
- Training: `src/model.py` → `run_walk_forward_under()`, 14 folds
- Format: combined (home + away sums)

## Candidate Features to Add

### For SPEC model (diff format):
1. `close_game_wp_diff` — win% in 1-2 run games (who wins tight games)
2. `hold_rate_diff` — win% when leading after 5 innings (who closes out)
3. `effective_obp_diff` — OBP of batters vs opposing pitcher's hand (matchup-aware)

### For UNDER model (combined format):
1. `hold_rate_combined` — combined hold rate (high = games stay decided = under)
2. `power_rate_combined` — combined multi-run inning rate (high = explosive = over)
3. `effective_obp_combined` — combined matchup OBP (high = more baserunners = over)

### For YRFI (new model):
- Currently NO walk-forward model, only static filters (babip_inn1 > 0.7 + fip > 8.4)
- CatBoost on first-inning features could replace/enhance static filters

## Critical Check: Feature Coverage

New features require inning-by-inning data. Coverage by source:
- xlsx 2010-2019, 2021: FULL inning data ✓
- SDQL 2004-2009: NO inning data (inn_1..inn_9 = 0)
- SDQL 2022-2025: NO inning data (inn_1..inn_9 = 0)

**Impact:** hold_rate, power_rate, deficit_recovery may be NaN for 2004-2009 and 2022-2025.
Need to verify: are these features computed from team game log (which uses final scores only) or from inning scores?
- If from final scores only → available for all seasons
- If from inning scores → only 2010-2021

## Plan

1. **Verify coverage** — check which new features have data for which seasons
2. **Add to SPEC** — append 3 candidates to SPEC_FEATURES, rebuild, run walk-forward
3. **Add to UNDER** — append 3 candidates to OU_FEATURES, rebuild, run walk-forward
4. **Compare** — old vs new ROI on dress rehearsal months (Sep 2019, Jun 2024, Apr 2025, Sep 2025)
5. **YRFI model** — if time permits, build walk-forward CatBoost for first-inning prediction
6. **Decide** — keep expanded model if ROI improves or stays flat; revert if overfitting detected

## Data Available for Validation

Dress rehearsal results from session 16-17 (all with LLM):
| Month | Bets | ROI | Sharpe |
|-------|------|-----|--------|
| Sep 2019 | ~150 | +2.9% | 0.46 |
| Sep 2021 | 261 | +6.6% | 1.18 |
| Sep 2023 | 204 | +10.8% | 1.62 |
| Apr 2024 | 221 | +0.8% | 0.07 |
| Jun 2024 | ~200 | +17.8% | 1.89 |
| Sep 2024 | 259 | +6.0% | 1.03 |
| Apr 2025 | ~180 | -10.8% | -0.87 |
| Sep 2025 | 275 | +11.9% | 2.07 |

## Key Files
- `src/features.py` — SPEC_FEATURES (line 1081), OU_FEATURES (line 1297), build functions
- `src/model.py` — walk-forward training (line 609+), under classifier (line 747+)
- `scripts/run_model_training.py` — training orchestration
- `scripts/run_dress_rehearsal.py` — full system backtest
