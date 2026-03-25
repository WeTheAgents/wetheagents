# Weather Kalshi -- Session 3 Handoff

## TL;DR

**Separated temperature forecasting from betting strategy.** Built a clean Forecaster module with 4 implementations and proper scoring (CRPS, PIT). Key finding: **CRPSigma** (keep raw forecast mu, CRPS-optimize sigma only) is the best forecaster -- beats Naive consistently across 18/19 test years, confirming Session 2's conclusion that the problem is uncertainty calibration, not bias.

## Architecture Change: Analyst/Strategist Split

Inspired by MLB domain's Analyst/Expert separation. The Forecaster:
- Takes raw GFS MOS forecast
- Outputs calibrated Gaussian distribution (mu, sigma)
- Knows NOTHING about brackets, markets, or betting
- Evaluated with proper scoring rules (CRPS, PIT, coverage)

Betting logic (bracket probabilities, edge detection, Kelly sizing) stays in existing modules and will consume Forecaster output in a future session.

## What Was Built

### New Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/scoring.py` | ~120 | CRPS, PIT, reliability bins, coverage, sharpness |
| `src/forecaster.py` | ~230 | 4 forecasters: Naive, Bias, EMOS, CRPSigma |
| `scripts/run_forecaster_eval.py` | ~350 | Walk-forward evaluation with comparison tables |

### Forecaster Hierarchy

| Forecaster | mu | sigma | Rationale |
|---|---|---|---|
| **Naive** | raw forecast | historical std per (station, month) | Market baseline |
| **Bias** | forecast - monthly mean bias | historical std | Phase 1 approach (proven insufficient) |
| **EMOS** | a + b*forecast (OLS) | CRPS-optimized per group | Full EMOS without ensemble spread |
| **CRPSigma** | raw forecast (= Naive) | CRPS-optimized per group | **Winner**: isolates sigma calibration |

### Scoring Module

- `crps_gaussian()` -- closed-form CRPS for Gaussian (Gneiting & Raftery 2007)
- `pit_values()` -- Probability Integral Transform for calibration assessment
- `reliability_bins()` -- PIT histogram + chi-squared uniformity test
- `coverage_probability()` -- prediction interval coverage at any level
- `sharpness()` -- mean sigma (smaller = better, given calibration)

## Key Results

### Comparison Table (20,803 test days, 2007-2025, walk-forward)

| Forecaster | CRPS | vs Naive | PIT chi2 | Cov90% | Sharpness |
|---|---|---|---|---|---|
| Naive | 2.027 | baseline | 2749 | 91.1% | 3.72 |
| **CRPSigma** | **2.023** | **-0.2%** | 2290 | 89.2% | **3.51** |
| EMOS | 2.033 | +0.3% | **103** | 88.3% | 3.43 |
| Bias | 2.041 | +0.7% | 322 | 90.8% | 3.72 |

### Per-Station CRPS (CRPSigma vs Naive)

| Station | Naive | CRPSigma | Improvement |
|---|---|---|---|
| KNYC | 2.274 | 2.268 | -0.2% |
| KMDW | 2.634 | 2.632 | -0.1% |
| KMIA | 1.173 | 1.168 | -0.4% |

### Year-by-Year Stability (CRPSigma vs Naive)

CRPSigma beats Naive in **18 of 19 years** (2007-2025). Only exception: 2014 (+0.0%). Improvement range: -0.1% to -0.6%. Recent 5yr average: -0.3%.

By contrast, EMOS is volatile: +5.0% (2012), +3.4% (2018), but -2.4% (2021), -2.3% (2025).

## Analysis

### Why CRPSigma Wins

1. **Session 2 was right**: GFS bias is 0.26F against sigma 3.65F (SNR=0.07). Correcting mu adds noise without reducing CRPS.
2. **CRPS directly optimizes sigma**: simple std() overestimates sigma for most (station, month) groups. CRPS minimization finds tighter sigma (3.51 vs 3.72 = 5.6% sharper).
3. **Stability**: since mu is unchanged, the only parameter is sigma per group -- less overfitting than EMOS's 3 parameters (a, b, sigma).

### Why EMOS Has Best PIT But Worst CRPS

EMOS's OLS correction (mu = a + b*forecast) produces non-integer mu values, which breaks the integer discreteness artifact in PIT histograms. This makes PIT look much better (chi2=103 vs 2749) but doesn't improve prediction quality -- it just smooths a measurement artifact.

The OLS mu correction is fragile: some years b deviates far from 1.0, introducing more error than the sigma optimization saves.

### The PIT Spike Problem

All forecasters with mu = integer forecast show a massive PIT spike at [0.5-0.6] (3757-3901 vs expected 2080). This is because forecast and observed temperatures are both rounded to integer F. When forecast = observed, PIT = Phi(0) = 0.5 exactly. This is a data discreteness artifact, not a model deficiency.

## What This Means for Phase 2 (Betting Strategy)

The Forecaster's CalibratedForecast(mu, sigma) connects to existing bracket_builder.py without modification:

```python
from src.forecaster import CRPSigmaForecaster
from src.bracket_builder import build_brackets, forecast_to_bracket_probs

forecaster = CRPSigmaForecaster()
forecaster.fit(train_df)
fc = forecaster.predict(forecast_high, station, month)

effective_bias = forecast_high - fc.mu  # = 0 for CRPSigma
probs = forecast_to_bracket_probs(forecast_high, effective_bias, fc.sigma, brackets)
```

The key insight for betting: CRPSigma gives **tighter sigma** than the market (Naive), which means it assigns more probability to the center bracket and less to the tails. This creates NO edge on tail brackets and YES edge on center brackets -- the opposite of Phase 1's NO-biased strategy.

## Next Steps (Phase 2 Recommendations)

### Near-term (improve Forecaster)
1. **Regime-dependent sigma** -- CRPSigma uses one sigma per (station, month). Adding weather-regime features (|forecast - climatology|, recent error volatility) could make sigma adaptive per day.
2. **Non-Gaussian distribution** -- PIT shows the error distribution is leptokurtic (pointy). Student-t or Laplace might improve tail probabilities.
3. **Recent-window sigma** -- instead of all prior years, CRPS-optimize sigma on rolling 3-5 year window. Already tested via `--rolling-window 5` flag.

### Medium-term (build Strategist)
4. **Real Kalshi prices** -- the favorite-longshot bias (YES loses 75-88%) is a market microstructure effect. Need actual bracket prices from Kalshi API.
5. **Center-bracket YES strategy** -- CRPSigma's tighter sigma implies the market overprices tail brackets. This suggests a YES strategy on center brackets, not NO on tails.
6. **Multi-station portfolio** -- KMIA has the strongest CRPSigma improvement (-0.4%). Focus live pilot there.

### Stretch
7. **Multi-model ensemble** -- GFS alone has structural limitations. Adding NAM/ECMWF would provide real ensemble spread for classic EMOS.
8. **LLM debate layer** -- for Segment C bust scenarios where mechanical models fail.

## Files Summary

| File | Change |
|------|--------|
| `src/scoring.py` | NEW: CRPS, PIT, coverage, sharpness scoring |
| `src/forecaster.py` | NEW: Naive, Bias, EMOS, CRPSigma forecasters |
| `scripts/run_forecaster_eval.py` | NEW: walk-forward evaluation pipeline |

## Kalshi Market Data Integration

### Data Access Discovery

Kalshi API is geo-blocked (US only, returns 403 from non-US IPs). But discovered **public S3 bucket** with daily market reports:
```
https://kalshi-public-docs.s3.amazonaws.com/reporting/market_data_{DATE}.json
```
No auth required. One JSON per day with ALL Kalshi markets (100-700MB). Filter to weather = ~162 rows per day per 20 cities.

### Ticker Format (learned from real data)

```
KXHIGHNY-26MAR23-B54.5   (inner bracket, boundary at 54.5F)
KXHIGHNY-26MAR23-T54     (tail bracket, <= 54F)
```
- 6 brackets per city per day: 4 inner (B, 2F wide) + 2 tails (T)
- Kalshi report_tickers: KXHIGHNY (NYC), KXHIGHCHI (Chicago!), KXHIGHMIA (Miami)
- Note: Chicago is `KXHIGHCHI` not `KXHIGHCG` as in our stations.json

### Data Limitation

S3 reports provide daily **high/low prices** (day range), not last_price or closing price. For finalized markets, this shows 0/99 (settlement). For active markets, shows the trading day's range.

This means: we can see market structure and price ranges, but **cannot do precise edge calculation** without last_price data. For that, we'd need either Kalshi API access (US IP) or the candlestick endpoint.

### Market Structure Observations (7-day sample, March 2026)

- NYC, Chicago, Miami all actively traded: 2K-16K contracts/bracket/day
- Tail brackets often more liquid than inner brackets
- Real bracket centers match GFS MOS forecasts closely
- Sum of mid prices (high+low)/2 > 100c because highs and lows are at different times

### Files Added

| File | Purpose |
|------|---------|
| `src/kalshi_client.py` | S3 market data client (no auth), parses weather markets from daily reports |
| `scripts/download_kalshi_data.py` | CLI to download date range of weather market data |
| `scripts/run_edge_analysis.py` | Compare CRPSigma model vs Kalshi prices (limited by high/low data) |

### Next Steps for Real Edge Analysis

1. **Get Kalshi API access** (US IP via VPN or cloud instance) for last_price / candlestick data
2. **Or use jon-becker/prediction-market-analysis dataset** (36GB, has last_price field)
3. **Or download 6+ months of S3 reports** and use active-market high/low from day-before-settlement as price proxy

## Commands

```bash
# Run full evaluation (all stations, all prior years training)
python scripts/run_forecaster_eval.py

# Single station
python scripts/run_forecaster_eval.py --station KMIA

# Rolling 5-year training window
python scripts/run_forecaster_eval.py --rolling-window 5

# Download Kalshi market data (last 7 days)
python scripts/download_kalshi_data.py --last 7

# Run edge analysis
python scripts/run_edge_analysis.py
```
