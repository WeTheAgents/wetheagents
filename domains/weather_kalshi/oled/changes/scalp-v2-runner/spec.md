# Spec — Scalp v2 runner (per-city rolling h*50 + flag v2)

## Outcome summary

Move the paper runner from fixed windows (A@15:00, B@16:30) to the validated v2
config: **A enters at the city's rolling median settle hour h*50 on clean days and
at 17:00 on flagged days; B unchanged.** Operator decision 2026-07-03 after the
h*50-vs-15:00 decomposition (48 incremental early-city trades at +43% ROI, shared
events slightly better) and requirement: **monthly re-tuning of h*50** — settle
time is seasonal.

## Behavior

**B1 — Rolling config** `data/static/scalp_hours.json`, produced by
`python -m scripts.paper_dayof --retune` from LOCAL data only:
- per city: `h50` (median settle hour, clamped 12–19, from rolling 60-day METAR
  window), `city_rate` (rise15 rate over same window), `n_days`;
- global: `entropy_q75` (bracket-price entropy at D−1 20:00 local over the rolling
  window, from the candle parquet), thresholds `cr_cut=0.5`, `warm_cut=3.0`,
  `generated_at`, `window_days=60`.
- Fallbacks: city with < 15 days → h50=15, city_rate=null.

**B2 — Auto-retune**: on every `--trade` run, if the config is missing or older
than 30 days, retune first (same process, logged). No new scheduled task.

**B3 — Flag v2 at trade time** (per city, local target date, computed inside the
run, cached per day in the ledger row):
`flag = city_rate ≥ cr_cut OR fc_warm ≥ warm_cut OR (lag1 AND entropy ≥ entropy_q75)`
- `fc_warm` = yesterday's snapshot ens forecast for today (days_ahead=1, native)
  − yesterday's realized METAR max (AWC live, 48h back, native rounding);
- `lag1` = yesterday was a rise day (yesterday max > yesterday max-by-15:00, METAR 48h);
- `entropy` from today's market candles ≤ D−1 20:00 local (daily-collected parquet);
- missing components degrade to False for their clause (logged in the row).

**B4 — Windows**:
- A, clean day: [h50, h50+15min) local → buy curmax bracket, ask ≤ 0.85.
- A, flagged day: [17:00, 17:15) local (same bracket rule).
- A run inside the h50-window on a FLAGGED day records `skip_reason=flagged_wait_17`
  and must NOT dedup-block the later 17:00 attempt; mirror-case
  `clean_not_17_window` likewise.
- B: [16:30, 16:45) unchanged.

**B5 — Ledger compatibility**: rows gain `variant` (`h50_clean` / `late17_flagged`),
`h_star`, `flag`, `flag_inputs`. Settlement logic unchanged.

## Acceptance

- [ ] `--retune` produces a sane config (h50 spread 12–17, Madrid late / HK early)
      from local data; runs < 2 min.
- [ ] Unit tests: window selection incl. flagged-wait dedup exception.
- [ ] Live `--trade` run executes with new windows; ledger row carries flag fields.
- [ ] Existing tests still pass; scheduled task needs no change.
