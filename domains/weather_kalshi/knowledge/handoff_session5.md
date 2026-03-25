# Session 5 Handoff — EnsembleForecaster v1

## What Was Built

Replaced static monthly sigma (2-5F) with day-specific sigma from GEFS ensemble spread (0.5-4.5F). This closes the 3-7x gap between our model and Polymarket's market-implied confidence.

### New Files
- `src/openmeteo_client.py` — Open-Meteo Ensemble API client (GEFS 30 members, live + cache)
- `scripts/run_ensemble_eval.py` — Walk-forward eval + live sigma comparison
- `scripts/run_live_edge.py` — Operational edge detection vs Polymarket bracket prices

### Modified Files
- `src/forecaster.py` — Added `predict_day()` to ABC, `CalibratedForecast` extended with distribution/percentiles fields, new `EnsembleForecaster` class
- `src/bracket_builder.py` — Added Student-t and empirical CDF distribution support
- `src/scoring.py` — Added `crps_empirical()` for ensemble-based scoring
- `src/stations.py` — Added `lat`, `lon` fields to Station dataclass
- `data/static/stations.json` — Added lat/lon coordinates for all 5 stations

### Key Architecture Decisions
1. `predict_day(forecast_temp, station, month, date, context)` — day-specific predictions with optional ensemble context; existing forecasters inherit fallback to `predict()`
2. `predict_batch_day(test_df)` — auto-extracts context from DataFrame columns (ensemble_spread, ensemble_mean)
3. `EnsembleForecaster.fit()` — learns CRPSigma-style fallback sigma AND (optionally) calibrates spread-to-sigma factor when ensemble_spread column is present
4. `bracket_builder` now accepts `distribution="gaussian"|"student_t"|"empirical"` — pluggable CDF for bracket probability computation

## Key Results

### Sigma Improvement (live data, 2026-03-24)

| Station | Day-1 Ensemble Spread | Historical Sigma | Ratio |
|---------|----------------------|------------------|-------|
| KLGA | 0.5-1.5F | 5.0F | 3-10x tighter |
| KORD | 0.6-2.1F | 5.3F | 3-9x tighter |
| KMIA | 0.4-0.7F | 1.9F | 3-4x tighter |

### Bracket Probability Impact (KMIA Mar 24, forecast=80F)
- Historical sigma (1.9F): 40% in peak bracket
- Ensemble sigma (0.65F): **86%** in peak bracket
- This matches market-level confidence

### Spread vs Lead Time Pattern
- Day 1-2: spread 0.5-2F (very competitive with market)
- Day 3-4: spread 1.5-4F (still 2-3x tighter than historical)
- Day 6-7: spread 4-8F (converges to historical — less edge)

## What's NOT Done

### Calibration Factor
- Currently `cal_factor = 1.0` (raw ensemble spread = sigma)
- No historical ensemble data available for calibration (Open-Meteo doesn't archive it)
- Need to accumulate 30+ days of live data via `save_ensemble_snapshot()`, then calibrate
- Expected optimal factor: 1.0-1.3 (ensembles tend slightly underdispersive)

### Historical Backtesting
- Walk-forward eval shows Ensemble = CRPSigma without live data (expected — same fallback)
- True CRPS improvement unmeasurable until we accumulate ensemble history
- Workaround: run daily cron to cache ensemble data, then backtest after 30+ days

### Future Phases (from plan)
1. **NBM percentiles** (`src/nbm_client.py`) — NOMADS text bulletins or Herbie GRIB2 for flow-dependent percentiles
2. **XGBoostLSS** (`src/ml_forecaster.py`) — ML post-processing with features: ensemble_spread, recent_errors, forecast_anomaly, wind/cloud
3. **METAR real-time tracking** — intraday temperature monitoring for late-day updates
4. **Automated latency arbitrage** — detect model updates, trade before market adjusts

## Running the System

```bash
# Live sigma comparison (no VPN needed)
python -m scripts.run_ensemble_eval --live-only

# Live edge vs Polymarket (needs VPN for API, or --cached for saved data)
python -m scripts.run_live_edge --cached --station KLGA
python -m scripts.run_live_edge --threshold 0.08

# Accumulate ensemble data (run daily to build history)
python -c "from src.openmeteo_client import fetch_ensemble_forecast_sync, save_ensemble_snapshot; from src.stations import get_station, POLYMARKET_STATIONS; [save_ensemble_snapshot(fetch_ensemble_forecast_sync(get_station(s).lat, get_station(s).lon, station=s, forecast_days=7), s) for s in POLYMARKET_STATIONS]"
```

## Data State
- Ensemble cache: `data/raw/openmeteo/ensemble_{KLGA,KORD,KMIA}.parquet` — 11 days each
- Market cache: `data/raw/polymarket/polymarket_weather.parquet` — from Session 4
