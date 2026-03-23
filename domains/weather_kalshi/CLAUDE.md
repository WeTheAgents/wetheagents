# Claude Code Instructions -- weather-kalshi

## Project Overview

Weather prediction market backtesting for Kalshi temperature contracts. Goal: find mechanical edge via systematic forecast bias exploitation, starting with NO-biased strategy.

**Phase 1: Mechanical pipeline (no LLM debate layer).**
1. Download GFS MOS forecasts + observed temperatures from IEM Archive
2. Compute per-station, per-month forecast biases
3. Convert bias-corrected forecasts to Kalshi bracket probabilities
4. Backtest NO-biased trading strategy

## Data

- **Source**: IEM MOS Archive (mesonet.agron.iastate.edu) -- public, no API key
  - MOS forecasts: `/api/1/mos.json` (GFS model, Dec 2003-present)
  - Observations: `/api/1/daily.json` (daily max/min temps)
- **Stations**: KNYC (NYC Central Park), KMDW (Chicago Midway), KMIA (Miami Intl)
- **Key numbers**: ~22 years * 365 days * 3 stations = ~24K forecast-obs pairs per station
- **Storage**: raw CSVs in data/raw/ (gitignored), processed parquet in data/processed/

## Running Analysis

```bash
# Download historical data
python scripts/download_iem_data.py --station KNYC

# Run bias analysis
python scripts/run_bias_backtest.py

# Run NO-strategy backtest
python scripts/run_no_strategy_backtest.py
```

## Architecture Notes

- `src/stations.py` -- station metadata registry (ICAO, IEM IDs, timezone, Kalshi ticker)
- `src/iem_client.py` -- IEM API client (MOS forecasts + daily observations)
- `src/data_loader.py` -- parse MOS n_x field into forecast-obs pairs, walk-forward safe
- `src/bias_analysis.py` -- compute bias profiles (mean, std, RMSE by station/month/season)
- `src/bracket_builder.py` -- Gaussian CDF to convert forecasts into bracket probabilities
- `scripts/` -- standalone analysis and download scripts

## Important Data Quirks

1. **MOS n_x field**: alternates MAX/MIN temperatures at 12h intervals.
   - ftime with hour=00Z: MAX temperature for the preceding daytime
   - ftime with hour=12Z: MIN temperature for the preceding nighttime
   - Calendar day of MAX = ftime.date() - 1 day (for US stations)

2. **IEM station IDs**: MOS uses 4-char ICAO (KNYC), obs API uses 3-char (NYC).

3. **DST/LST**: NWS CLI reports in Local Standard Time, not clock time during DST.
   During DST the recording window is 1:00 AM to 12:59 AM local clock time.

4. **Kalshi brackets**: 6 mutually exclusive brackets per city, 2F inner width,
   centered on the forecast. Brackets change daily. Phase 1 uses parametric model.

## Status

Phase 1 in progress. See `knowledge/research_weather_predictions.md` for foundational research.
