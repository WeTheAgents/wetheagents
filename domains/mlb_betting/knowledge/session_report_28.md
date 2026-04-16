# Session 28: Statcast Bullpen Features from Baseball Savant

**Date**: 2026-04-03
**Objective**: Explore Baseball Savant Statcast metrics for bullpen quality/fatigue detection.
**Hypothesis**: Bullpen xwOBA mismatch + fatigue signals provide high-volume betting edge.
**Result**: NEGATIVE — signal is too weak for standalone or ML use.

---

## What We Built

### Infrastructure
1. **`data/fetch_savant_gamelogs.py`** — Downloads pitch-by-pitch Statcast data via pybaseball, aggregates to pitcher-game level. 10 seasons cached (2015-2025, excl. 2020). ~750K pitches/season.
2. **`src/savant_bullpen.py`** — Filters to relievers (min_inning > 1), aggregates team-level bullpen Statcast metrics, computes rolling features (3-day fatigue + season-to-date quality + 15-game rolling).
3. **`data/processed/savant/`** — 10 parquet files (pitcher_games), 1 ID bridge, 1 bullpen features file.
4. **Integration in `src/features.py`** — 30 Savant columns auto-merged, 4 diff features added to SPEC_FEATURES.

### Features Computed (per team per game, entering-game anti-leak)
- **Fatigue (3-day)**: bp_sc_whiff_3d, bp_sc_barrel_3d, bp_sc_hard_hit_3d, bp_sc_exit_velo_3d, bp_sc_xwoba_3d
- **Fatigue delta**: bp_sc_whiff_delta_3d (3d vs STD), bp_sc_barrel_delta_3d
- **Quality**: bp_sc_xwoba_std, bp_sc_barrel_std (season-to-date), bp_sc_xwoba_15g, bp_sc_barrel_15g (15-game)
- **Mismatch diffs**: home minus away for each metric

---

## Standalone Signal Scan (10 seasons, 2015-2025)

### xwOBA Season-to-Date Mismatch (best standalone signal)
Bet AWAY moneyline when home bullpen xwOBA is higher (worse).

| Threshold | Games/season | Win Rate | ROI | Profitable seasons |
|-----------|-------------|----------|------|-------------------|
| >= 0.03 | 238 | 53.0% | **-0.8%** | 4/10 |
| >= 0.04 | 148 | 53.1% | **-1.0%** | 5/10 |
| >= 0.05 | 96 | 53.1% | **-0.2%** | 6/10 |

### Per-Season Detail (threshold >= 0.05)
| Season | N | WR | ROI |
|--------|---|------|------|
| 2015 | 44 | 52.3% | +8.2% |
| 2016 | 73 | 57.5% | +15.2% |
| 2017 | 45 | 60.0% | +19.3% |
| 2018 | 54 | 57.4% | +7.1% |
| 2019 | 86 | 53.5% | -9.6% |
| 2021 | 88 | 43.2% | **-16.1%** |
| 2022 | 219 | 51.1% | -5.8% |
| 2023 | 158 | 56.3% | +0.8% |
| 2024 | 111 | 54.1% | +7.2% |
| 2025 | 82 | 51.2% | -3.4% |

**Pattern**: Strong 2015-2018 (pre-analytics boom), degraded 2019+. Market adapted.

### Other Signals Tested
- **15-game rolling xwOBA mismatch**: Negative ROI across all thresholds
- **Barrel rate mismatch**: Near break-even
- **Fatigue (barrel_delta_3d) alone**: **Strongly negative** (-5% to -13%)
  - Interpretation: managers compensate (next starter goes deeper) and/or market already prices workload
- **Combined (xwOBA + fatigue)**: Looked strong on 2024 alone (59.5% WR), collapsed on multi-season validation

---

## ML Integration (CatBoost)

Added 4 Savant diff features to the 21-feature SPEC_FEATURES:
- bp_sc_xwoba_std_diff, bp_sc_barrel_std_diff, bp_sc_whiff_delta_3d_diff, bp_sc_barrel_delta_3d_diff

**Feature importance in CatBoost** (train 2004-2023, test 2024-2025):
- elo_diff: 41.2% (dominant)
- Savant features combined: **1.74%** (negligible)
  - bp_sc_xwoba_std_diff: 0.71% (rank 14/25)
  - bp_sc_barrel_std_diff: 0.44% (rank 16)
  - bp_sc_whiff_delta_3d_diff: 0.37% (rank 18)
  - bp_sc_barrel_delta_3d_diff: 0.22% (rank 21)

Test RMSE with Savant features: 0.1004 (vs naive baseline 0.1177).

---

## Why Bullpen Statcast Failed as a Signal

1. **Market efficiency**: Bookmakers already incorporate bullpen state. Savant data is public since 2015 — sharp bettors and models have been using it for years.
2. **Manager adaptation**: Fatigue signals are compensated by managers (deeper starts after heavy bullpen use). The barrel_delta "fatigue" signal is actually *anti-predictive* (-13% ROI).
3. **Noise at game level**: Per-game Statcast metrics for relievers are noisy (2-6 batted balls per reliever per game). Season aggregates smooth this but lose recency.
4. **Temporal decay**: Signal was profitable 2015-2018 when Statcast was new, degraded as market absorbed the information.

---

## What Remains Valuable

1. **10 seasons of Statcast data** cached and ready (pitch-by-pitch aggregated to pitcher-game)
2. **Savant infrastructure** in the pipeline — can be extended to starter Statcast metrics
3. **Reliever identification** from Statcast data (no Retrosheet dependency) — useful for 2026 live
4. **Negative result documentation** — saves future effort by eliminating a plausible-but-empty avenue

---

## Recommended Next Steps

1. **Remove Savant features from SPEC_FEATURES** (negligible contribution, adds noise)
2. **Explore starter Statcast metrics** as next research direction — starter quality has higher per-game signal-to-noise ratio and may be less priced-in
3. **Use Savant data for 2026 live bullpen-day detection** (identify relievers without Retrosheet dependency)
