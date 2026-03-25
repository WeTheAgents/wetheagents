# Weather Prediction Markets -- Session 4 Handoff

## TL;DR

**Pivoted from Kalshi to Polymarket.** Built full Polymarket API integration (market discovery, bracket parsing, price history). Key finding: **the market is 3-7x more confident than our CRPSigma model** — market-implied sigma is 0.7-0.85F vs model's 2-5F. This completely reframes the edge question: the market uses day-of multi-model information, not historical averages. Our historical-sigma model cannot compete on point forecasts. The edge, if any, lies in **tail mispricing** — does the market's extreme confidence create systematically underpriced tail brackets?

## Why Polymarket (Pivot from Kalshi)

Kalshi requires a US phone number for registration. Polymarket:
- Account already exists, API keys available
- No geo-blocking for API (but need VPN for DNS resolution)
- Same 2F bracket structure, similar volume ($200-330K/day per city)
- Better data: `outcomePrices` gives exact implied probabilities (vs Kalshi's high/low range)

## Architecture: New Code

| File | Lines | Purpose |
|------|-------|---------|
| `src/polymarket_client.py` | ~280 | Gamma API + CLOB API client |
| `scripts/download_polymarket_data.py` | ~90 | CLI for fetching weather market data |
| `data/static/stations.json` | updated | Added KLGA, KORD with Polymarket fields |
| `src/stations.py` | updated | Station dataclass extended, POLYMARKET_STATIONS |
| `src/bracket_builder.py` | updated | `brackets_from_polymarket()`, `align_model_to_market_brackets()` |

## Key Discoveries

### 1. Resolution Stations Differ

| City | Kalshi | Polymarket | Same? |
|------|--------|------------|-------|
| NYC | KNYC (Central Park) | **KLGA (LaGuardia)** | No |
| Chicago | KMDW (Midway) | **KORD (O'Hare)** | No |
| Miami | KMIA | KMIA | Yes |

Both KLGA and KORD have 22 years of GFS MOS data (8032-8035 forecast-obs pairs). CRPSigma works on both.

### 2. Bracket Structure: 11 vs 6

Polymarket uses **11 brackets** (9 inner 2F-wide + 2 tails) vs Kalshi's 6.
More brackets = finer resolution. Our Gaussian CDF math works unchanged — the `forecast_to_bracket_probs()` function accepts arbitrary bracket counts.

### 3. The Sigma Gap — The Crucial Finding

Market-implied sigma vs model sigma (March 24, 2026):

| Station | CRPSigma sigma | Market implied sigma | Ratio |
|---------|---------------|---------------------|-------|
| KORD | 5.34F | 0.73F | 7.3x |
| KLGA | 5.02F | 0.85F | 5.9x |
| KMIA | 1.92F | 0.68F | 2.8x |

**Why:** CRPSigma calibrates sigma on historical "average March" day-ahead error (all years). The market uses day-of information from multiple weather models, ensemble spread, current conditions. Day-of forecasts have much lower uncertainty than "average day-ahead for this month."

### 4. CRPSigma Performance on New Stations

| Station | CRPS (Naive) | CRPS (CRPSigma) | Improvement | Best Forecaster |
|---------|-------------|-----------------|-------------|-----------------|
| KLGA | 2.337 | 2.331 | -0.2% | EMOS/Bias (-0.6%) |
| KORD | 2.562 | 2.558 | -0.2% | CRPSigma (-0.2%) |
| KMIA | 1.173 | 1.168 | -0.4% | CRPSigma (-0.4%) |

**KLGA anomaly**: Bias/EMOS beat CRPSigma here. KLGA has stronger cold bias (-0.52F) than KNYC (-0.26F), making mean correction worthwhile. This station may benefit from a combined approach (bias + sigma calibration).

### 5. Polymarket Data Snapshot (Mar 18-24, 2026)

- 21 events, 231 bracket rows, 3 cities
- Total 7-day volume: **$1.68M**
- NYC highest volume ($80K-330K/day), Miami ($5-213K), Chicago ($0-163K)
- Settled markets (Mar 18-22) resolve to 1.0/0.0 — no pre-settlement price history retained
- Active markets (Mar 23-24) have live price feeds via CLOB `/prices-history`

## Analysis: Where Is The Edge?

### What Doesn't Work

**Historical-sigma model vs day-of market prices:** Our model spreads probability 3-7x wider than the market. On center brackets, the edge is massively negative (-28pp for KORD center, -23pp for KLGA center). We cannot profitably buy YES on center brackets.

### What Might Work: Tail Strategy

If the market's implied sigma of 0.7F is overconfident, tail brackets are systematically underpriced. Consider:
- KORD [42-43] bracket: model=5.0%, market=0.4% → 12.5x underpriced by market
- KLGA [≤37] bracket: model=7.0%, market=0.15% → 46.7x underpriced by market

**But:** if the market's day-of sigma is correct (which it likely is for most days), tail bets lose consistently. The question is whether the market is **always** well-calibrated or **occasionally** overconfident — and whether we can detect those occasions.

### The Real Edge Opportunity

The model's advantage isn't in the day-of point forecast. It's in knowing **when the market might be overconfident**:

1. **Regime detection** — some weather patterns (frontal passages, lake effect, tropical transitions) have inherently higher forecast uncertainty. If the market doesn't adjust sigma for these, tails are underpriced on those specific days.

2. **Calibration of calibration** — collect Polymarket price data over weeks/months and measure how often the center bracket actually wins. If it wins less than the market implies (e.g., center at 40% but wins only 30%), that's systematic overconfidence.

3. **Lead-time decay** — markets price based on the latest forecast, but how quickly does market confidence adjust when forecasts flip? During rapid forecast changes, the market may lag.

## Polymarket API Reference

### Gamma API (market discovery)
```
Base: https://gamma-api.polymarket.com
GET /events?slug={slug}  → event with nested markets
GET /markets  → search/filter markets
Rate: 300 req/10s (markets), 500 req/10s (events)
No auth needed
```

### CLOB API (prices)
```
Base: https://clob.polymarket.com
GET /prices-history?market={token_id}&interval={1h|6h|1d}  → [{t, p}]
Rate: 1000 req/10s
No auth for reads
```

### Event Slug Pattern
```
highest-temperature-in-{city}-on-{month}-{day}-{year}
Cities: nyc, chicago, miami
Months: lowercase full English (march, april, ...)
```

### DNS Note
`gamma-api.polymarket.com` resolves to 127.0.0.1 without VPN (blocked in hosts/DNS). Need VPN for API access.

## Commands

```bash
# Download Polymarket weather data
python -m scripts.download_polymarket_data --all --last 7
python -m scripts.download_polymarket_data --city chicago --last 30

# Download IEM data for new stations
python scripts/download_iem_data.py --station KLGA --fast
python scripts/download_iem_data.py --station KORD --fast

# Run forecaster evaluation on new stations
python -m scripts.run_forecaster_eval --station KLGA
python -m scripts.run_forecaster_eval --station KORD
```

## Next Steps (Session 5 Recommendations)

### Priority 1: Calibration-of-market study
Collect 30+ days of Polymarket pre-settlement prices and settlement outcomes. Compute:
- Empirical win rate of center bracket vs market-implied probability
- Reliability diagram: is 40% market price = 40% actual frequency?
- If market is overconfident (center wins < market implies), quantify the tail edge

### Priority 2: Day-of sigma model
Replace historical CRPSigma with a **day-of sigma estimator**:
- Input: latest GFS ensemble spread, ECMWF spread, recent forecast volatility
- Output: day-specific sigma that competes with market's implied 0.7-0.85F
- This is the "Forecaster v2" — not just historical calibration but live uncertainty estimation

### Priority 3: Automated data collection
Set up daily cron to:
- Fetch Polymarket prices at T-24h, T-12h, T-6h, T-1h before settlement
- Record settlement outcomes
- Build the calibration dataset for Priority 1

### Priority 4: EMOS for KLGA
KLGA shows stronger bias (-0.52F) and EMOS/Bias outperform CRPSigma. Consider a station-specific strategy: EMOS for KLGA, CRPSigma for KORD/KMIA.

## Files Summary

| File | Change |
|------|--------|
| `src/polymarket_client.py` | NEW: Polymarket Gamma + CLOB API client |
| `src/stations.py` | UPDATED: KLGA, KORD, Polymarket fields |
| `src/bracket_builder.py` | UPDATED: Polymarket bracket conversion |
| `data/static/stations.json` | UPDATED: 5 stations (was 3) |
| `scripts/download_polymarket_data.py` | NEW: CLI for Polymarket data |
| `data/raw/polymarket/` | NEW: Downloaded market data |
| `data/raw/mos/KLGA_GFS_all.csv` | NEW: 22yr MOS data for LaGuardia |
| `data/raw/mos/KORD_GFS_all.csv` | NEW: 22yr MOS data for O'Hare |
| `data/processed/forecast_obs_KLGA.parquet` | NEW: 8032 pairs |
| `data/processed/forecast_obs_KORD.parquet` | NEW: 8035 pairs |
