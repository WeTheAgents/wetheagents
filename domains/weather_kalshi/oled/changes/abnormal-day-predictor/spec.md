# Spec — Abnormal-Day Predictor (strategy 3: day-ahead risk filter for the scalp system)

## Outcome summary

The scalp system (strategies A/B) loses on "abnormal days": the daily max keeps rising
after the 15:00/16:30 decision windows, so the winner lands ABOVE the bracket we bought
(A) or exactly on the bracket we sold (B). Question: can we know **by the evening
before (D-1) or early morning of D** which city-days are high-risk, with monetizable
probability?

Two monetization levels:
1. **L1 (defensive)**: skip tomorrow's scalp trades in flagged city-days → avoid losses.
2. **L2 (offensive)**: on flagged days, take the opposite side — buy the bracket(s)
   ABOVE the eventual afternoon max (the very thing strategy B normally sells).

Deliverable: `scripts/run_abnormal_day_study.py` + `reports/abnormal_day_report.html`
(Russian prose, Plotly inline) with an explicit verdict per level.
Research only — no changes to the live paper runner.

## Definitions

- **Event** = (city, target_date) with a clean market winner (last candle ≥ 0.90),
  from `data/processed/dayof_study_checkpoints.parquet` (1109 events, Mar–Jul).
- **cur15** = bracket containing the rounded native running max at 15:00 local
  (reuse `assign_positions` from `scripts/build_dayof_nowcast_report.py`).
- **Label `rise` (abnormal day)** = winner_idx > cur15_idx (temp climbed ≥1 bracket
  after 15:00). Magnitude = winner_idx − cur15_idx. Basis-driven losses
  (winner BELOW cur15) are counted separately, not as "abnormal".

## Day-ahead features (all must be knowable before D 15:00 local; source in parens)

- F1 `rise_lag1`, `rise_lag2` — this city rose late yesterday / day before (own labels;
  weather-regime persistence).
- F2 `city_rate` — city's smoothed base rate of late rises (leave-one-out to avoid
  self-leakage; captures chronic late-peakers, e.g. sea-breeze coasts).
- F3 `warming` — market-implied forecast max for D minus realized max on D-1
  (modal bracket of D's market at D-1 evening from candle history; realized from METAR).
  Hypothesis: big warm-ups are advective days that peak late.
- F4 `mkt_entropy` — entropy of D's bracket price distribution at D-1 20:00 local
  (candles). Market's own uncertainty.
- F5 `mkt_upside_mass` — total price mass on brackets above the modal bracket at
  D-1 20:00 (market already leaning "hotter than mode").
- F6 `ens_spread` / `nbm_sigma` — ensemble/NBM uncertainty for D (ml_panel, June+ only).
- F7 `taf_delta` — TAF max for D minus market modal forecast (ml_panel; TAF is issued
  day-ahead).
- F8 `peak_hour_clim` — city's climatological mean daily peak hour from the METAR
  archive (Mar–Jul hourly).

## Analyses

1. Base rates: P(rise), magnitude distribution, by city / US-INTL, June vs all.
2. Univariate lift: P(rise | feature quantile) for F1–F8, with n per bucket.
3. Simple combined score (logistic regression on available-June subset or hand rule
   from top features; NO heavy ML — n≈1000). Out-of-sample discipline: time split
   (train ≤ June 15, test after) for anything fitted.
4. **L1 simulation**: June strategy-A trades (h=15, YES ≤ 0.85) with vs without
   skipping flagged days; report ROI delta, trades kept, and the same for strategy B.
5. **L2 simulation**: on flagged days, buy YES at h=15 on the bracket above cur15
   (and the open-top tail variant); ROI at candle prices with 1¢ slippage.
6. Honest caveats: sample size, single season (summer), candle≈mid, multiple testing.

## Acceptance criteria

- [ ] Labels validated on 3 hand-checked events (rise / no-rise / basis-loss).
- [ ] Every feature verified leak-free (uses only data timestamped before D 15:00 local).
- [ ] L1 verdict: explicit ROI with/without filter on a time-split test set.
- [ ] L2 verdict: explicit ROI of the offensive side, or "not monetizable".
- [ ] Report sent to operator.
