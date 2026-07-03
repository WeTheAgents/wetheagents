# Verification — City Timing Study

Date: 2026-07-03

## Acceptance criteria (spec.md)

- [x] R2 label agreement: METAR-only rise15 vs market rise = **88.7%** (n=1079 overlap;
      confusion: 5% market-rise-only, 6% metar-rise-only — WU basis noise, symmetric).
- [x] Leak discipline: h* quantiles and METAR city_rate/persistence fitted on
      city-days ≤ 2026-06-15 only; all portfolio numbers from market data > 2026-06-15.
- [x] Negative result documented: CLOB API returns EMPTY for April–May tokens
      (live probe, madrid 2026-05-10, intervals max/1w/1d); our own candles for
      weeks 14–22 end before local day end (past_end 0–5%) → winners unrecoverable.
- [x] Report reports/city_timing_report.html built and sent.

## Key numbers (OOS test, slippage 1¢)

- METAR day table: 4654 city-days, 45 cities (3927 train) — ~7× the market-label set.
- METAR-refit flag: P(rise|flag)=51% vs 24%; A clean +66.5% (n=165), A flagged −0.8%,
  L2b@17:00 flagged **+47.1%** (n=112) — L2b improved vs old flag (+19.8%).
- Timing: h*₅₀ clean +65.2% (n=210) ≈ fixed-15 clean +66.5% (n=165) → same per-trade
  ROI, +27% coverage. h*₆₅ all-days +17.6% — too late, edge decays with certainty.
- Recommended v2 ensemble: A@h*₅₀ clean (+65%, n=210) + A@17:00 flagged (+47%, n=112).

## Addendum — Flag v2 on local-only deep data (operator pushback: "не бери API")

Operator was right to push: local stores DO cover the training needs for April–May:
- `data/raw/snapshots/*.parquet` (80 daily files since Mar 25): day-ahead ensemble
  forecasts (days_ahead 0–6, 139-member multimodel) → true forecast-warming feature.
  Older snapshots also carry `pm_bracket_*_price` (morning market prices, spring).
- Candles cover D−1 20:00 local for ~100% of events in ALL weeks (sparse May candles
  sit in early market life) → evening market features computable for May.
- `data/raw/observed/obs_*.parquet`: daily max/min per city since Mar 9 (openmeteo).
What remains truly absent everywhere: April–May RESOLUTION prices (decision-hour
candles + winners) — P&L simulation stays June+-only.

Flag v2 (`scripts/run_flag_v2_study.py`, `reports/flag_v2_report.html`):
train Mar 25–Jun 15 (3239 city-days), thresholds tuned on a train slice disjoint
from the city-rate fit; test untouched. Tuned rule: city_rate≥0.5 OR fc_warm≥3°
OR (lag1 AND entropy≥q75). OOS: P(rise|flag)=53% vs 30%, flag rate 25%.
A kept n=239 ROI +44%; **L2b@17:00 n=71, win 66%, ROI +71%** (vs +47% for v1).
Comparable total P&L to v1 with a cleaner methodological base and a stronger L2b leg.

## Notes

- Q=0.5 vs 0.65 comparison was a 2-point scan, not exhaustive tuning; thresholds
  chosen on economic logic (median settle), both reported.
- Seasonal recompute of h* required outside summer.
