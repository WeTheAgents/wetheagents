# Spec — City Timing Study (directions: deeper train data + per-city entry hours)

## Outcome summary

Two operator questions:
1. Can we extend the study deeper than June 15 (e.g., May CLOB data)?
2. Should entry times be tuned per city instead of global 15:00 / 17:00?

Findings that shape this spec (probed live 2026-07-03):
- CLOB API no longer serves April–May price history (retention); our own parquet has
  those weeks but candles END before local day end (past_end ≈ 0–5% for weeks 14–22)
  → market-truth winners are unrecoverable for May. **Documented as a negative result.**
- BUT the rise label needs no market at all: rise = native-rounded daily max >
  native-rounded 15:00 running max — pure METAR. Hourly METAR exists Mar 9 – Jul 2
  for all 45 stations → ~4–5k city-days of training labels (4× the market-label set).

## Deliverables

`scripts/run_city_timing_study.py` + `reports/city_timing_report.html` (Russian).
Research only; no live-runner changes.

## Requirements

**R1 — METAR-only day table.** Per (city, local_date): rounded native running max at
each local hour 10–21, daily max, `settle_hour` (earliest hour whose running max
equals the daily max, native), `rise15` label. Days with ≥ 12 obs.

**R2 — Label validation.** On June+ events where both exist, agreement between
METAR-only rise15 and the market-label rise (target ≥ 85%; report the confusion).

**R3 — Direction 1 (deeper train).** Refit city_rate and persistence on METAR-only
labels Mar 9 – Jun 15; rebuild the day-ahead flag (same thresholds as strategy-3
study); evaluate on the SAME market test (> Jun 15): P(rise|flag) separation and
L1/L2 portfolio ROI vs the strategy-3 baseline flag.

**R4 — Direction 2 (per-city entry hour).** From METAR train only (≤ Jun 15):
h*(city) = earliest local hour h with P(settle_hour ≤ h) ≥ 0.65 (fallback 16:00 when
n < 15). No price data used in fitting. Evaluate OOS (> Jun 15) with checkpoint
prices: portfolio A@h*(city) vs A@15:00 vs the flag-ensemble (A@15 clean / A@17
flagged), all with 1¢ slippage, YES ≤ 0.85. Also report h* vs peak-hour climatology
and the combined variant (per-city hour + flag skip/shift).

**R5 — Report** with explicit verdicts: what May extension is/isn't possible;
whether METAR-refit flag beats the old one; whether per-city hours beat global;
recommended production config (per-city table).

## Acceptance

- [ ] R2 agreement measured and ≥ 80% (else investigate before conclusions).
- [ ] All fits use data ≤ Jun 15 only; test strictly > Jun 15.
- [ ] Negative result (May) documented in report.
- [ ] Report sent.
