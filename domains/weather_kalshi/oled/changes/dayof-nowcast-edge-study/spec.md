# Spec — Day-of Nowcast Edge Study (METAR running max vs Polymarket intraday)

## Outcome summary

**Question:** Does the Polymarket daily-high-temperature market lag freely observable
intraday information — specifically the METAR running maximum, which sets a hard floor
on the day's high — leaving exploitable mispricing in "dead" brackets?

**Decision this enables:** go / no-go on building a live day-of trading loop
(the strongest of the 4 approaches identified in the 2026-07-03 data review).

**Deliverable:**
1. `scripts/run_dayof_nowcast_study.py` — reproducible analysis pipeline
2. `reports/dayof_nowcast_report.html` — self-contained interactive report (Plotly inline)
3. Intermediate artifacts in `data/processed/dayof_study_*.parquet`

This is research, not a production behavior change → no separate outcome.md.

## Data inputs (all already collected, read-only)

| Source | File | Granularity |
|---|---|---|
| Market prices | `data/raw/polymarket/all_cities_price_history.parquet` | 10-min candles, UTC, 8.66M rows |
| Bracket metadata | `data/raw/polymarket/all_cities_markets.parquet` | 48,880 brackets, bounds parsed from `question` via `build_ml_panel.parse_bracket` |
| Observations | `data/raw/metar/metar_{ICAO}.parquet` | hourly METAR, 45 stations, 2026-03-09 → 2026-07-02 |
| City → station | `data/static/icao_map.json` (primary ICAO), `data/static/polymarket_cities.json` (timezone, unit) | |
| HRRR (secondary) | `data/raw/hrrr/hrrr_{ICAO}.parquet` | 1 run/day only → descoped to a descriptive sidebar |

## Requirements

**R1 — Ground truth.** Event outcome = market-implied winner: the unique bracket whose
last candle price ≥ 0.90. Events without a unique winner are excluded (count reported).
Rationale: panel `realized_in_bracket` labels were shown broken on 2026-07-03
(643/924 disagreements with market resolution); market truth is the reliable label.

**R2 — Dead bracket definition.** At local time *t* on target date, running max
M(t) = max METAR `temp_f` over obs with local timestamp in [00:00, t].
Bracket with upper bound U (°F-converted) is **dead** when M(t) ≥ U + buffer.
Buffer ∈ {0, 1, 2}°F computed for all three (basis risk: resolution source is
Weather Underground, which reads ≥ METAR by 1–2 brackets in INTL cities).
Top open-ended brackets are never dead under this rule.

**R3 — Mispricing measurement.** At local checkpoints 10:00–21:00 hourly:
count of dead brackets still priced ≥ {1¢, 2¢, 5¢} (YES side); aggregate EV of
buying NO at last candle ≤ checkpoint (candle must be ≤ 2h stale, else skip).
**Safety metric:** rate at which a METAR-dead bracket nevertheless *won* the market
(basis error) — reported per buffer, must be in the report headline.

**R4 — Latency event study.** For each bracket-death event (first hourly METAR ob
crossing U + buffer): YES price at death, decay at +10m/+30m/+1h/+2h/+3h,
time until price ≤ 1¢. Median + quartiles, split US vs INTL.

**R5 — Strategy backtest.** Rule: at checkpoint h ∈ {12:00, 15:00, 18:00} local,
buy NO on every dead bracket (buffer = 1) with YES ≥ 2¢; entry = candle price,
hold to resolution. Report: trade count, hit rate, ROI per $1, total P&L,
per-city and per-ISO-week breakdown, worst 10 trades. Slippage scenario:
entry price +1¢ against us. Both gross and slippage-adjusted ROI reported.

**R6 — Report.** Self-contained HTML (Plotly bundled inline, no CDN), opens locally.
Sections: TL;DR verdict → data & method (with the "why market truth" explanation) →
floor-signal calibration (R3) → latency (R4) → strategy P&L (R5) → risks
(WU/METAR basis, candle=midpoint caveat, liquidity unknown, 10-min granularity) →
next steps. Report prose in Russian (operator-facing research artifact);
code and comments in English.

## Acceptance criteria

- [ ] Script runs end-to-end from repo root: `python -m scripts.run_dayof_nowcast_study`
- [ ] Every headline number in the HTML is produced by the script (no hand-edited figures)
- [ ] Basis-error rate (dead-but-won) reported for each buffer
- [ ] Excluded-event counts reported (no silent drops)
- [ ] 3 events spot-checked manually (candles vs METAR vs winner) and documented in verification.md
- [ ] Verdict states edge size after slippage, or its absence, explicitly
