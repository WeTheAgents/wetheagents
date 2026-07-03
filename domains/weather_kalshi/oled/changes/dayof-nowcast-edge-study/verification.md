# Verification — Day-of Nowcast Edge Study

Date: 2026-07-03

## Acceptance criteria status

- [x] Script runs end-to-end: `python -m scripts.run_dayof_nowcast_study` (rebuild, ~2 min)
      then `python -m scripts.build_dayof_nowcast_report` → `reports/dayof_nowcast_report.html`
- [x] All headline numbers produced by `analyze()`; no hand-edited figures in HTML
- [x] Basis-error rate reported per buffer: 2.96% (0°F), 0.55% (1°F), 0.20% (2°F)
- [x] Exclusion counters reported in report §1: 4457 total events → 1122 used
      (409 no obs, 2917 history not past day end — April–May candle retention gap, 9 no unique winner)
- [x] 3 events spot-checked manually (below)
- [x] Verdict explicit: dead-bracket latency NO-GO; current-max-at-15:00 main candidate
      (+27% slip ROI, n=513, June+); WU basis = separate exploitable signal

## Manual spot checks

1. **NYC 2026-06-25 (KLGA)** — METAR daily max 84.0°F; market winner bracket 84–85°F.
   Exact match. ✓
2. **London 2026-06-20 (EGLL)** — METAR daily max 77.0°F = 25.0°C; market winner 26°C.
   Resolution read 1°C ABOVE METAR — live confirmation of the WU>METAR basis. ✓
3. **Dallas 2026-06-26 (KDFW)** — METAR daily max 97.0°F; market winner 94–95°F (2–3°F BELOW).
   Too large for rounding/WU basis → likely resolution station mismatch (Polymarket Dallas
   probably resolves via a different airport than KDFW). **Finding**: audit
   `data/static/icao_map.json` primaries against Polymarket resolution pages.
   Recorded in report §8. This inflates the measured basis-error rate slightly,
   i.e. the true WU-vs-METAR error with correct stations is ≤ reported 0.55%.

## Methodology fixes made during the study

- Panel `realized_in_bracket` labels NOT used (shown broken 2026-07-03); market-implied
  winner (unique last candle ≥ 0.90, history past local day end) used instead.
- Bracket assignment rounds running max in native units (°F US / °C INTL) because US
  brackets have 1°F gaps (83–84 / 85–86) and resolution uses whole degrees. Without this
  fix the US winner-match rate at 19:00 was 61%; with it — 85%.

## Known limitations (stated in report §8)

Candles ≈ midpoint (not executable prices), no order-book depth, 10-min granularity,
April–May coverage gap, single daily HRRR run, station-mismatch audit pending.
