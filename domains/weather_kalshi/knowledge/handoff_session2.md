# Weather Kalshi — Session 2 Handoff

## TL;DR

**The mechanical cold bias strategy is NOT viable for live trading in 2026.** The GFS cold bias is real and was historically profitable (2007-2011), but has been progressively corrected by NCEP model upgrades. Recent years (2020-2025) generate too few trades with inconsistent returns. Phase 1's core hypothesis — that systematic forecast bias creates exploitable bracket mispricing — is refuted at the bracket level.

## What Was Done

### Data Pipeline (async, 5x faster)
- Added `download_obs_bulk_async()` to `src/iem_client.py` — 5 concurrent requests via httpx.AsyncClient
- 3 stations x 22 years of obs downloaded in **13 minutes** (vs ~6 hours with sync code)
- MOS bulk CSVs: ~685K lines per station (Dec 2003 - Mar 2026)
- Observations: ~8,114 days per station (2004-2026)
- Forecast-obs pairs: ~8,030 per station (2004-2025, 2026 rejected at 95% quality threshold)

### Analysis Completed
- Bias backtest: 3 stations × 22 years × 12 months
- NO-strategy backtest: 3 edge thresholds (5%, 8%, 10%)
- Walk-forward discipline: all results use prior-year-only bias training

## Key Findings

### 1. Cold Bias: Real But Weak

| Station | 22yr Mean Bias | MAE | P(too high) | Cold Years |
|---------|---------------|-----|-------------|------------|
| KNYC | -0.26F | 3.15F | 43.6% | 14/22 (64%) |
| KMDW | -0.28F | 3.64F | 44.3% | 13/22 (59%) |
| KMIA | -0.10F | 1.57F | 34.4% | 13/22 (59%) |

Session 1's KNYC 2024 bias was -1.39F — **5x stronger** than the 22-year average. 2024 was an anomalously strong cold-bias year, not representative.

### 2. Bias Correction Adds ZERO Value at Bracket Level

| Station | Naive Hit Rate | Corrected Hit Rate | Brier (Naive) | Brier (Corrected) |
|---------|---------------|-------------------|---------------|-------------------|
| KNYC | 21.4% | 21.0% (-0.4%) | 0.6786 | 0.6787 |
| KMDW | 22.9% | 22.5% (-0.5%) | 0.6774 | 0.6765 |
| KMIA | 40.6% | 39.9% (-0.7%) | 0.5492 | 0.5509 |

Bias correction actually makes bracket prediction *worse*. The ~0.3F mean bias is drowned out by ~3-4F standard deviation.

### 3. Trading Edge is Evaporating

**NO-strategy at 5% edge threshold:**

| Period | Trades/yr | Win Rate | ROI | Verdict |
|--------|-----------|----------|-----|---------|
| 2007-2011 | 524 | 83.4% | +6.6% | Strong edge |
| 2012-2013 | 334 | 74.6% | -5.2% | Edge failure |
| 2014-2016 | 238 | 84.7% | +9.6% | Recovery |
| 2017-2019 | 207 | 72.2% | -4.2% | Edge failure |
| 2020-2025 | 75 | 80.2% | +6.3% | Few trades, inconsistent |

**By threshold (all years):**

| Min Edge | Trades | Win Rate | ROI | Sharpe | Last Trade Year |
|----------|--------|----------|-----|--------|----------------|
| 5% | 5,073 | 80.7% | 3.7% | 1.64 | 2025 |
| 8% | 1,095 | 82.6% | 8.8% | 3.06 | 2019 |
| 10% | 406 | 81.5% | 10.8% | 3.66 | 2012 |

Higher threshold = better ROI but edge disappears sooner. At 8%+ there are ZERO trades in 2020-2025.

### 4. Station Comparison

- **KMIA (Miami)**: Best station. Lowest error (MAE 1.57F), most consistent cold bias (P(too high) 27-42% all months), highest ROI at every threshold. GFS handles tropical convection poorly.
- **KMDW (Chicago)**: Middle. Highest MAE (3.64F), decent trade count. Best months: Feb, Apr, Jun.
- **KNYC (NYC)**: Weakest. Walk-forward direction hit rates are best (Apr 79%, Nov 82%) but ROI is lowest.

### 5. Month Analysis

| Month | Win Rate | ROI | Assessment |
|-------|----------|-----|-----------|
| Jul | 84.1% | +6.3% | Best month |
| Feb | 81.9% | +8.8% | Strong |
| Dec | 88.6% | +9.6% | Strong but few trades |
| Jun | 83.0% | +5.1% | Solid |
| Apr | 78.3% | +4.3% | High volume, moderate |
| Sep | 65.0% | -19.9% | **DEATH TRAP — skip** |
| Nov | 71.2% | -3.6% | Unprofitable |

### 6. Why The Edge Is Disappearing

1. **GFS model upgrades**: NCEP has progressively improved the GFS model. Resolution increased from ~35km (2007) to ~13km (2024). Each upgrade reduces systematic bias.
2. **Walk-forward training dilution**: As more years of data accumulate, recent low-bias years dilute the training signal, generating fewer trades.
3. **Structural**: A 0.26F bias against a 3.65F standard deviation of error is a signal-to-noise ratio of 0.07. This is too weak for bracket-level trading (bracket width = 2F).

## Verdict on Phase 1 Hypothesis

**REFUTED.** The mechanical cold bias creates *directional* signal (forecast too low ~57% of the time) but NOT *bracket-level* signal. The 2F bracket width absorbs the ~0.3F bias without changing which bracket the observation falls in. This is why bias correction makes bracket prediction worse, not better.

## What Could Work (Phase 2 Pivot)

The raw forecast error is 3-4F — that's 1.5-2 brackets of uncertainty. This means Kalshi bracket markets are fundamentally about **quantifying uncertainty**, not correcting bias. Phase 2 should pivot:

1. **EMOS calibration** — fit σ (spread) not just μ (bias). CRPS minimization over rolling window. This directly addresses the uncertainty quantification problem.
2. **Real Kalshi market prices** — the favorite-longshot bias (Chris Dodds: YES trades lose 75-88%) is a market microstructure effect, separate from forecast bias. Get actual bracket prices via Kalshi API.
3. **Regime classifier** — GFS errors are NOT iid. Certain weather patterns (frontal passages, tropical systems, temperature inversions) create predictable error clusters. ERA5 reanalysis + k-means could identify these.
4. **Multi-model ensemble** — GFS alone is suboptimal. NAM, ECMWF, HRRR each have different error profiles. Ensemble improves calibration.
5. **High-convidence seasonal filter** — trade only Jul-Aug at KMIA (93%+ win rate historically) as a narrow pilot.

## Files Modified

| File | Change |
|------|--------|
| `src/iem_client.py` | Added `download_obs_bulk_async()`, `download_obs_year_async()`, `_fetch_obs_day()` |
| `scripts/download_iem_data.py` | Added `--fast` flag for async obs download |

## Data State

- `data/raw/mos/`: `{ICAO}_GFS_all.csv` (3 files, ~50MB each)
- `data/raw/obs/`: `{station}_obs_all.parquet` + per-year parquets (23 files per station)
- `data/processed/`: `forecast_obs_{ICAO}.parquet` (3 files, ~8K rows each)

All data is gitignored. Re-download with `python scripts/download_iem_data.py --fast`.
