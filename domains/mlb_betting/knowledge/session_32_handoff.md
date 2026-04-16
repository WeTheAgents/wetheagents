# Session 32 Handoff — OVER Hypothesis Post-2021

## Why this session exists

Session 31 killed UNDER in zone [0.52-0.53) (see `session_30_handoff.md`). But the same
checkpoint revealed the **mirror image**: 53.6% base OVER rate on 718 games, with several
filters showing +7-11% ROI. Operator's long-standing hypothesis — "OVER is a product of
1-2 outlier innings, killed by that in earlier epochs" — was tested directly via an
outlier-stress test and **confirmed**: dropping the top 10% of total_runs collapses every
OVER edge. Yet the raw edge exists, concentrated in 2023-2025.

Goal of session 32: **decide whether a 2021+ OVER strategy is real (structural regime shift)
or a small-sample mirage concentrated in 107 holdout games.**

## What we already know (session 31 OVER post-hoc)

Script: `scripts/analyze_over_gate_v2.py` (no LLM calls, pure post-hoc on existing checkpoint).
Data: `picks/_under_gate_experiment_v2.json` — 718 games, 2021-2025, zone [0.52-0.53).

### Signal summary (UNDER@1.909, breakeven 52.38%)
| Signal | N | Over% | ROI |
|---|---|---|---|
| ALL (baseline) | 718 | 53.6% | +2.3% |
| `gap_over_lg >= 0.3` (pred > 8.87+0.3) | 174 | 58.0% | +10.8% |
| `gap_over_lg >= 0.5` | 129 | 58.1% | +11.0% |
| `DA=OVER` (v1 checkpoint verdict) | **304** | 56.2% | **+7.4%** |
| Agreement (gap_line>0 & gap_lg>0) | 162 | 57.4% | +9.6% |
| `line_below_lg >= 0.5` (pure market) | 59 | 59.3% | +13.2% |
| August (all games) | 155 | 61.9% | **+18.2%** |

### TRAIN / HOLDOUT inversion (critical)
| | 2021-2023 TRAIN | 2024-2025 HOLDOUT |
|---|---|---|
| ALL | 611 / 52.7% / +0.6% | **107 / 58.9% / +12.4%** |
| gap_over_line >= 0.3 | 104 / 50.0% / -4.6% | 23 / 65.2% / +24.5% |
| DA=OVER | 256 / 55.1% / +5.1% | 48 / 62.5% / +19.3% |
| low line (≤ 8.5) | 231 / 50.2% / -4.1% | 56 / 60.7% / +15.9% |

Pattern is **opposite** to UNDER's collapse: UNDER worked in 2021-2022, died in 2023+.
OVER was break-even in 2021-2022 but accelerates through 2023, 2024, 2025.

### Outlier stress test (operator's hypothesis confirmed)
Sort games by total_runs desc, drop top N%, recompute:

| Strategy | 0% | 5% | 10% | 15% | 20% |
|---|---|---|---|---|---|
| ALL | 53.6% / +2% | 51.2% / -2% | 48.5% / -7% | 45.5% / -13% | 42.1% / -20% |
| DA=OVER | 56.2% / +7% | 54.0% / +3% | 51.5% / -2% | 48.6% / -7% | 45.5% / -13% |

Every signal crashes at 10% trim. Edge is outlier-driven, not structural.
This does NOT disqualify the strategy — mispriced outliers are a real pattern — but it
means variance will be high and drawdowns deep.

### Calibration
- `corr(predicted, actual) = +0.087` (noise)
- `mean(actual - pred) = +1.40` runs — LLM systematically underpredicts
- pred mean 8.55, line mean 9.03, **actual mean 9.95**

LLM is bad at pointing to OVER games specifically, but its systematic underprediction
is itself a weak signal that the underlying population scores above the line.

## What to do in session 32

### Step 1 — widen the CatBoost zone (no LLM required)
Run the same analysis on **adjacent p_under buckets without gpt-5.4 scoring**:
- [0.45-0.50): strong OVER lean from CatBoost
- [0.50-0.52): grey zone just below what we tested
- [0.47-0.52) combined: ~1500 games (rough estimate) in 2021-2025

Use just the market signal `line_below_lg` + season + month + DA-style simple heuristics.
If edge replicates on larger sample → structural regime shift confirmed.

Code path: reuse `walk_forward_splits` + `predict_under_proba` in
`scripts/run_under_gate_experiment_v2.py:build_predictions`; add a new filter band and
skip the LLM call loop entirely. Write `scripts/scan_over_zones.py`.

### Step 2 — pre-2021 sanity check
Question: was the 2021-2023 break-even OVER rate genuinely different from 2004-2019?
- Run `line_vs_lg` + base over-rate per season on full dataset 2004-2019
- If pre-2021 over-rate in the grey zone is <50%, the regime shift is real
- If pre-2021 over-rate is ~53-54% too, the 2023+ acceleration is small-sample noise

Load path: `src.data_loader.load_all_seasons()` + `build_ou_features()`. Already filters
pushes. No LLM needed.

### Step 3 — dissect the August effect
155 games, 61.9% over, +18.2% ROI in month 8 is the single strongest cell in the grid.
Hypotheses to test against the feature data:
- Bullpen depletion (late-season workload accumulates): check `bp_ip_3d`, `bp_ip_season` distributions
- Pitcher fatigue (starters in innings 4-5 of August vs April): check `sp_ip_short`
- Weather / ballpark (August heat → ball carries): not in features, may be untestable here
- Lineup call-ups (September expansion rosters — but that's month 9): check
- Simple selection effect: is August *always* the highest-scoring month? Check total_runs
  distribution by month on full 2004-2025 (not just grey zone) to see baseline

If the effect replicates at the full-dataset level, we have a structural reason. If it's
only in the grey zone for 2021-2025, it's probably regime + small sample.

### Step 4 — decision framework
Go/no-go criteria for promoting OVER to production:
- **GO**: edge replicates on ≥2000 games across 2021-2025 with a clear mechanism (August,
  line_below_lg, DA=OVER or a clean LLM signal) AND hit rate ≥ 54% survives 10% outlier trim
  on ≥1000 games
- **NO-GO**: edge degrades materially on wider zone, or outlier-stress kills it even on
  larger sample. In that case document the "OVER variance trap" and move on.
- **MORE DATA NEEDED**: something in between → queue an LLM scoring run on zone [0.47-0.52)
  (~1500 games × ~$0.008 = ~$12) to add LLM features for the promising filters.

## Key files

| File | Purpose |
|------|---------|
| `scripts/analyze_over_gate_v2.py` | Session 31 OVER analyzer (post-hoc) — reference implementation |
| `scripts/analyze_under_gate_v2.py` | Sibling UNDER analyzer — template |
| `picks/_under_gate_experiment_v2.json` | 718 LLM-scored games, zone [0.52-0.53) |
| `picks/_under_gate_experiment.json` | v1 checkpoint with DA verdicts |
| `src/data_loader.py` | `load_all_seasons`, `apply_data_filters`, `add_derived_odds` |
| `src/features.py` | `build_all_features`, `build_ou_features`, `OU_FEATURES` |
| `src/model.py` | `train_under_model`, `predict_under_proba`, `walk_forward_splits` |
| `scripts/run_under_gate_experiment_v2.py` | Walk-forward predictions pipeline (lines 82-123) |
| `knowledge/session_30_handoff.md` | Full session 30-31 history + 15-signal analysis framework |

## Constraints

- 2020 excluded (COVID)
- Pushes excluded upstream
- OVER odds assumed 1.909; upgrade to actual `close_over_odds` if available in the merged data (check `ou` dataframe columns after `build_ou_features`)
- No LLM calls in step 1-3; reserve budget for step 4 if needed

## Operator's constant reminder
OVER is historically a variance trap — every previous investigation (sessions 16, 20) killed it.
The hypothesis we're testing is NOT "OVER is a good bet". It is: **"did something change in
2023 that made the grey-zone OVER a real edge"**. If the answer is no, we stop. The bar for
"yes" is structural mechanism + wide-sample replication + outlier-stress survival.
