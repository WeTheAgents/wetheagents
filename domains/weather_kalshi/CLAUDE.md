# Claude Code Instructions -- weather-kalshi

## Project Overview

Weather prediction market backtesting for temperature contracts on **Polymarket** (pivoted from Kalshi in Session 4). Goal: find edge via calibrated probabilistic forecasting vs market-implied probabilities.

**Current Phase: NBM-enhanced live edge detection.**
1. GFS MOS forecasts + observed temperatures from IEM Archive (22 years)
2. **NBM QMD percentiles** from NOAA (P1-P99, ~10 models, pre-calibrated) — primary sigma source
3. GEFS ensemble spread from Open-Meteo (30 members) — fallback sigma source
4. NBMForecaster: empirical CDF from percentiles (no Gaussian assumption)
5. Compare model bracket probabilities vs Polymarket market prices
6. Live edge detection pipeline with 3-tier data source priority

## Data

- **Forecasts**: IEM MOS Archive (mesonet.agron.iastate.edu) -- GFS model, Dec 2003-present
- **Observations**: IEM daily max/min temps
- **Market prices**: Polymarket Gamma API (bracket prices, event metadata)
- **Stations** (Polymarket resolution):
  - KLGA (NYC LaGuardia) -- resolves via wunderground.com/history/daily/KLGA
  - KORD (Chicago O'Hare) -- resolves via wunderground.com/history/daily/KORD
  - KMIA (Miami International) -- resolves via wunderground.com/history/daily/KMIA
- **Also tracked** (Kalshi): KNYC (Central Park), KMDW (Midway)
- **Key numbers**: ~8,000 forecast-obs pairs per station, 22 years
- **NBM QMD**: NOAA NOMADS GRIB2 files (byte-range download, cfgrib parsing)
  Cache in `data/raw/nbm/`. Rolling ~2 days on NOMADS; extended archive on AWS S3.
- **Storage**: raw in data/raw/ (gitignored), processed parquet in data/processed/

## Running Analysis

```bash
# Download historical IEM data
python scripts/download_iem_data.py --station KLGA --fast
python scripts/download_iem_data.py --station KORD --fast

# Download Polymarket weather data (needs VPN for DNS)
python -m scripts.download_polymarket_data --all --last 7

# Run forecaster evaluation (historical walk-forward)
python -m scripts.run_forecaster_eval --station KLGA

# Run ensemble comparison (live sigma vs historical)
python -m scripts.run_ensemble_eval --live-only
python -m scripts.run_ensemble_eval --station KLGA

# Run NBM discovery (validate GRIB2 access, inspect fields)
python scripts/nbm_discovery.py

# Run live edge detection vs Polymarket (NBM + ensemble + historical)
python -m scripts.run_live_edge --cached --station KLGA
python -m scripts.run_live_edge --threshold 0.08
```

## Architecture

- `src/stations.py` -- station registry (ICAO, IEM IDs, Polymarket slug, Kalshi ticker)
- `src/iem_client.py` -- IEM API client (MOS forecasts + daily observations)
- `src/data_loader.py` -- parse MOS n_x into forecast-obs pairs, walk-forward safe
- `src/forecaster.py` -- 6 forecasters: Naive, Bias, EMOS, CRPSigma, EnsembleForecaster, **NBMForecaster** (current best)
- `src/nbm_client.py` -- NBM QMD client (GRIB2 byte-range fetch, cfgrib, P1-P99 percentiles)
- `src/openmeteo_client.py` -- Open-Meteo Ensemble API client (GEFS 30 members, fallback)
- `src/scoring.py` -- CRPS (Gaussian + empirical), PIT, coverage, sharpness
- `src/bracket_builder.py` -- Gaussian/Student-t/empirical CDF for bracket probabilities
- `src/bias_analysis.py` -- bias profiles (mean, std, RMSE by station/month/season)
- `src/polymarket_client.py` -- Polymarket Gamma + CLOB API client
- `src/kalshi_client.py` -- Kalshi S3 market data (legacy, kept for reference)

## Important Data Quirks

1. **MOS n_x field**: alternates MAX/MIN temperatures at 12h intervals.
   - ftime hour=00Z: MAX temperature (calendar_day = ftime.date() - 1)
   - ftime hour=12Z: MIN temperature (calendar_day = ftime.date())

2. **IEM station IDs**: MOS uses 4-char ICAO (KLGA), obs API uses 3-char (LGA).

3. **Polymarket brackets**: 11 per city (9 inner 2F-wide + 2 tails), vs Kalshi's 6.
   Event slug: `highest-temperature-in-{city}-on-{month}-{day}-{year}`
   Cities: nyc, chicago, miami

4. **DNS blocking**: gamma-api.polymarket.com resolves to 127.0.0.1 without VPN.

5. **Market-implied sigma** (~0.7-0.85F) is 3-7x tighter than model sigma (2-5F).
   Market uses day-of multi-model info; model uses historical average.

6. **Ensemble spread** (Open-Meteo): no historical archive. Data accumulates locally
   via `save_ensemble_snapshot()`. Cache in `data/raw/openmeteo/`.

## Key Findings (Session 7 — NBM Integration)

- **NBM sigma dramatically tighter than GEFS**: 0.47-1.4F vs 0.5-8F (ensemble spread)
- NBM uses empirical CDF (PchipInterpolator from P1-P99) — no Gaussian assumption
- fxx mapping from 12Z cycle: fxx=18 (today), fxx=42 (tomorrow), fxx=66 (day+2), fxx=90 (day+3)
- QMD product on NOMADS (not core); herbie doesn't support it, so direct HTTP + cfgrib
- Byte-range requests: ~1.5MB per percentile field × 9 = ~14MB per date (vs 200MB+ full file)
- 3-tier priority: NBM > ensemble > historical — graceful degradation

## NBM Data Details

- **Product**: blend.t{cycle}z.qmd.f{fxx:03d}.co.grib2 on NOMADS
- **Index fields**: `:TMP:2 m above ground:*hour max fcst:{N}% level`
- **Grid**: CONUS (2345×1597), one file covers all 3 Polymarket stations
- **Units**: Kelvin → Fahrenheit conversion required
- **Archive**: NOMADS rolling ~2 days; AWS S3 `s3://noaa-nbm-grib2-pds/` for extended
- **Dependency**: cfgrib (pip) for GRIB2 parsing; herbie-data in pyproject.toml but QMD uses direct HTTP

## Status

Session 7 complete. See `knowledge/handoff_session6_nbm.md` for pre-session research.
Next: accumulate NBM data (30+ days), calibrate ensemble cal_factor, compare NBM vs GEFS edge accuracy.
