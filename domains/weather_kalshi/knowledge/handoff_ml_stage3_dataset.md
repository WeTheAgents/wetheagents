# ML Stage 3 — Exceedance Dataset (2026-07-07)

Builder: `scripts/build_exceedance_dataset.py` → `data/processed/exceedance_dataset.parquet`
(+ `_meta.json`, `reports/exceedance_dataset_report.html`). One row = one strike (a
bracket lower bound) for one US city-day.

## What it is

- **Scope**: 11 US NBM cities, decision_time = 14:00 UTC. 8990 rows, 905 city-days,
  111 dates (2026-03-11..07-06). Dropped: 241 city-days (decision-time prices don't sum
  to [0.9,1.1]) + 6 (a bracket had no candle before decision — prices incomplete).
  (An initial version had a None→NaN bug that mis-sorted the bottom tail and corrupted
  temp_rank/targets — caught by codex, fixed; the market-vs-NBM finding below held.)
- **Target** `y = 1[realized max ≥ strike]`, derived from `winner_bracket_final` in
  labels.parquet. **Critical:** `bracket_index` is NOT temperature-ordered (nyc idx1 =
  54-55°F, idx8 = 46-47°F), so brackets are sorted by lower bound into a `temp_rank`
  and `y = 1[winner_temp_rank ≥ strike_rank]`. Using the raw index would scramble the
  target. Works for market- and metar-labeled rows alike (no exact temp needed).
- **Baseline** `market_p_exceed`: cumulative decision-time bracket price at/above the
  strike, normalized, clipped [0.005,0.995]. Monotone-in-strike on 100% of city-days.
- **NBM features (P5-P95 only)**: `z = (strike−nbm_median)/nbm_sigma`; two exceedance
  estimates — `nbm_exceed_param` (Gaussian survival of z) and `nbm_exceed_emp`
  (`_build_empirical_cdf`, tail extrapolated). p1/p99 deliberately NOT read (they vanish
  Jun-Jul → walk-forward leak).
- **Other**: warming (nbm_median − prev-day realized max), log_nbm_sigma, month, doy
  sin/cos, `is_wing` (min(p,1−p) ≤ 0.15), `wing_side` (hot/cold/mid), `stale`,
  `candle_age_h`, `label_source`. city_rate NOT written (in-fold in Stage 4).
- Anti-leak assert: every market candle used is ≤ decision_time.

## Two findings that change expectations for Stage 4

**1. Staleness is inherent — the fresh sample is thin.** Only **~39% of rows (45 distinct
dates, 362 city-days)** have all contributing quotes within 3h of decision_time. Freshness does
NOT improve at a later hour (14:00 UTC 33% > 18:00 30% > 20:00 28%) — US weather markets
trade mostly the evening before, then go quiet. So **14:00 UTC is the best decision_time**
(the earlier Explore suggestion to move to 18:00 was wrong), and the honest headline
sample is ~42 date-clusters. Stage 4 should report fresh-only (headline) AND all-rows
(larger, stale-price robustness) — the dataset carries the `stale` flag.

**2. The market beats NBM on calibration in EVERY zone (fresh rows).** This is the big one:

| wing side | n | market_p_exceed | nbm_param | realized y |
|---|---|---|---|---|
| hot (cheap YES) | 1436 | 0.022 | **0.076** | 0.019 |
| cold (cheap NO) | 1564 | 0.981 | 0.963 | 0.984 |
| mid | 548 | 0.504 | 0.636 | 0.506 |

(Exceedance probs use the strike−0.5 rounded-max threshold consistently.)

The market's exceedance curve is near-perfectly calibrated; **NBM over-disperses** (fat
tails: says 5.6% hot-tail exceedance when reality is 1.3%; market says 2.2%). So a model
using NBM to *level-correct* the market is dragged toward worse calibration. **NBM can
only add value via conditional discrimination** — identifying WHICH specific days the
market is wrong — not a level shift. In aggregate there is no edge; the strategy rests
entirely on a local/conditional sweet spot surviving Stage 4's gatekeeping. This lowers
the prior substantially (consistent with sessions 8-11: the market is efficient) but does
not rule out a niche. Isotonic (rung 1) will fix NBM's level; the real test is whether
calibrated-NBM discriminates beyond the already-excellent market.

## Contract for Stage 4

Train/eval on `exceedance_dataset.parquet`. Headline metric = Δlog-loss vs
`market_p_exceed` on wing rows (`is_wing==1`), **fresh rows only**, date-clustered
bootstrap over the ~42 fresh dates → expect WIDE CIs; go only on a confident, not
borderline, edge. Report per-city (LA's NBM is worst). Related: [[weather-ml-pipeline]]
[[weather-ml-stage2-nbm]] [[weather-ml-stage1-labels]].
