# Tasks — Day-of Nowcast Edge Study

- [x] T1. Data prep: load candles + markets (parse brackets via `build_ml_panel.parse_bracket`),
      METAR per station, `icao_map.json` + `polymarket_cities.json`; derive market-truth
      winners (unique last-price ≥ 0.90); convert candle timestamps to city-local time.
- [x] T2. Dead-bracket engine: per (city, target_date) compute hourly METAR running max
      in local time; per bracket compute death time for buffers {0,1,2}°F.
- [x] T3. Checkpoint mispricing tables (R3) + basis-error safety metric.
- [x] T4. Latency event study (R4): price decay curves after bracket death.
- [x] T5. Strategy backtest (R5): 12/15/18 local entries + positional strategies
      (current-max bracket buy, above-bracket NO) with native-unit rounding fix,
      gross + slippage ROI, per-week/price-band breakdowns.
- [x] T6. HRRR sidebar: descoped to limitation note (1 run/day in cache).
- [x] T7. Build interactive HTML report (Plotly inline, Russian prose) —
      `reports/dayof_nowcast_report.html`.
- [x] T8. Verify: acceptance checklist + 3 manual spot-checks → verification.md
      (finding: Dallas resolution-station mismatch — icao_map audit needed).
