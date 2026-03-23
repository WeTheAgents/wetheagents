# Weather Kalshi — Session 1 Handoff

## What Was Done

Created the `weather_kalshi` domain from scratch — complete Phase 1 scaffold with verified data pipeline.

### Files Created (20 files, 2677 lines)

**Core library (`src/`):**
- `stations.py` — Registry of 3 Kalshi resolution stations (KNYC, KMDW, KMIA) with IEM identifiers, timezones, NWS offices
- `iem_client.py` — IEM API client: bulk MOS CSV download + per-day obs JSON. Rate-limited (1s), idempotent (skip existing files)
- `data_loader.py` — Parses MOS `n_x` field into daily forecast-obs pairs. Key logic: ftime 00Z = MAX for (ftime.date()-1), ftime 12Z = MIN for ftime.date()
- `bias_analysis.py` — Computes bias profiles by station×month/season/year. Walk-forward stability test with 0.5°F minimum significance threshold
- `bracket_builder.py` — Gaussian CDF converts bias-corrected forecasts to 6-bracket Kalshi probabilities. Unified `resolve_bracket()` for consistent CDF/resolution boundaries

**Scripts (`scripts/`):**
- `download_iem_data.py` — CLI wrapper for bulk download (all stations or single)
- `download_single_year.py` — Quick single-year download for testing
- `smoke_test.py` — 6 end-to-end tests (API connectivity, n_x parsing, bias math, bracket CDF, bulk endpoints)
- `run_bias_backtest.py` — Historical bias analysis report with walk-forward bracket accuracy test
- `run_no_strategy_backtest.py` — NO-biased trading P&L simulation with Kelly sizing, Sharpe, drawdown

**Infrastructure:**
- `pyproject.toml`, `CLAUDE.md`, `README.md`, `.gitignore`, `.env.example`, `stations.json`
- `ledger/domains.json` updated with `weather_kalshi` entry (invariant PASS)

### Key Technical Decisions

1. **IEM MOS Archive as primary data source** — eliminates data engineering. GFS MOS available Dec 2003-present
2. **Bulk CSV for MOS** (`cgi-bin/request/mos.py` with year1/month1/.../format=csv) — fast, one request per station
3. **Per-day JSON for obs** (`api/1/daily.json`) — bulk CSV endpoint doesn't return temperature for Central Park (NYC). ~3 min per year at 0.5s rate limit
4. **n_x parsing**: ftime hour=0 → MAX (calendar day = ftime.date()-1), ftime hour=12 → MIN (calendar day = ftime.date())
5. **Bracket model**: 6 brackets, 4 inner (2°F width) + 2 tails, centered on even-rounded forecast. +0.5 continuity correction for Gaussian CDF
6. **No agents assigned** — Phase 1 is operator + Agent0 only

### Code Review Findings (all fixed)

1. CDF/resolution boundary mismatch → unified `resolve_bracket()` with +0.5 boundaries
2. Bias stability test noise at zero → minimum 0.5°F threshold
3. Quality filter: wrong denominator + no leap year handling → fixed with `calendar.isleap()`
4. Bulk MOS download: no error handling → added try/except with clear error message
5. Bracket centering: comment said "even" but `round()` rounds to nearest int → fixed to `round(x/2)*2`

## First Results (KNYC 2024, 366 days)

| Metric | Value | Trading Implication |
|--------|-------|-------------------|
| GFS bias (high) | **-1.39°F (COLD)** | Forecast systematically underestimates |
| P(forecast too high) | **29.2%** | Actual temp exceeds forecast 71% of days |
| MAE | 2.85°F | ~1.5 brackets of error |
| Std error | 3.65°F | Width of predictive distribution |
| Best month | October: P(high)=16.1% | 84% of days forecast too low |
| Worst month | December: P(high)=48.4% | Near-neutral, skip |

**Monthly breakdown:**
```
Jan: bias=-0.74F, MAE=3.45F, P(high)=45.2%
Feb: bias=-0.93F, MAE=2.86F, P(high)=34.5%
Mar: bias=-1.59F, MAE=3.27F, P(high)=29.0%
Apr: bias=-2.40F, MAE=4.33F, P(high)=30.0%
May: bias=-1.26F, MAE=2.87F, P(high)=35.5%
Jun: bias=-0.87F, MAE=2.13F, P(high)=30.0%
Jul: bias=-2.03F, MAE=2.87F, P(high)=22.6%
Aug: bias=-1.52F, MAE=2.35F, P(high)=22.6%
Sep: bias=-1.33F, MAE=2.07F, P(high)=23.3%
Oct: bias=-1.94F, MAE=2.32F, P(high)=16.1%  ** strongest
Nov: bias=-2.43F, MAE=3.23F, P(high)=13.3%  ** strongest
Dec: bias=+0.32F, MAE=2.45F, P(high)=48.4%  -- skip
```

**Key insight**: GFS cold bias confirmed (aligns with NCEP Office Note 520). Trading signal = NO on lower brackets (market overprices probability that temp will be below forecast). October-November are the strongest months.

## What Needs To Be Done Next (Session 2)

### Priority 1: Download 20 years of data
```bash
cd domains/weather_kalshi

# MOS forecasts (bulk CSV — fast, ~20 sec per station)
python scripts/download_iem_data.py --mos-only --no-pairs

# Observations (per-day JSON — ~1 hour per station × 20 years)
# Run for each station separately, expect ~60-80 min each
python scripts/download_single_year.py  # modify YEAR range for 2004-2023
```

**Important**: The obs download is slow (per-day JSON API). Consider:
- Download years in parallel (multiple terminal sessions)
- Or write an async httpx version for 5-10x speedup
- Each year file is idempotent (skip if exists), so safe to interrupt/resume

### Priority 2: Run full bias backtest
```bash
python scripts/run_bias_backtest.py --station KNYC
```

Key questions to answer:
1. Is the cold bias stable across 20 years? (Need 18+/20 years with same direction)
2. Does walk-forward stability test show >70% direction hit rate?
3. Which station-months have P(too high) > 58% or < 42%?
4. Does bias-corrected bracket prediction improve Brier score vs naive?

### Priority 3: Run NO-strategy backtest
```bash
python scripts/run_no_strategy_backtest.py --station KNYC
python scripts/run_no_strategy_backtest.py --station KNYC --min-edge 0.05
```

Key metrics to evaluate:
- Win rate (target: >60%)
- ROI after fees (target: >5%)
- Sharpe ratio (target: >0.5)
- Max drawdown
- Per-year profitability (target: >70% of years profitable)

### Priority 4: Repeat for KMDW and KMIA
Same pipeline, different stations. Compare bias patterns across cities.

### Priority 5 (if results are positive): Plan Phase 2
- EMOS calibration (Gaussian with fitted variance, CRPS minimization)
- Regime classifier (ERA5 500mb PCA + k-means)
- Consider adding more stations (Austin, LA — next highest volume)

## Known Limitations

1. **Single year only** — 2024 results could be anomalous. 20-year validation is critical
2. **No real market prices** — backtest uses naive forecast as market price proxy. Real Kalshi prices may differ
3. **Bracket model is parametric** — actual Kalshi brackets vary daily. Phase 2 should use real bracket data via Kalshi API
4. **Obs download is slow** — ~1 hour per station-year via per-day JSON. Could be 10x faster with async httpx or finding a working bulk endpoint

## File Locations

- Domain: `domains/weather_kalshi/`
- Ledger registration: `ledger/domains.json` (key: `weather_kalshi`)
- Downloaded data (gitignored): `domains/weather_kalshi/data/raw/` and `data/processed/`
- Research doc: `domains/weather_kalshi/knowledge/research_weather_predictions.md`
- Commit: `0cba608` on main
