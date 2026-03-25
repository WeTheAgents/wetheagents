# Session 8 Handoff — Wing Backtest + 26-City Expansion

## What was done

### 1. Expanded from 3 to 26 cities
- Probed Polymarket Gamma API for all temperature markets
- Found 26 cities: 11 US (NBM available) + 15 international
- Registry: `data/static/polymarket_cities.json`
- US: nyc, chicago, miami, los-angeles, houston, dallas, denver, seattle, atlanta, san-francisco, austin
- International: hong-kong, taipei, tel-aviv, london, tokyo, seoul, singapore, paris, toronto, sao-paulo, buenos-aires, shanghai, beijing, madrid, warsaw

### 2. Key insight: resolution from price history
- No external weather API needed for backtesting
- At resolution, winning bracket goes to 100%, all others to 0%
- Last candle in price history reveals observed temperature
- 195 of 196 past events successfully resolved this way

### 3. Wing buying backtest (195 events, 490 trades at T-48h)

**Baseline (blind wing buying):** 4.1% hit rate, -21.8% ROI

**Best single filters:**
| Filter | Trades | Hit Rate | ROI |
|--------|--------|----------|-----|
| entropy >= 2.8 | 63 | 7.9% | +21.4% |
| price 3-6¢ | 73 | 5.5% | +26.5% |
| max_prob <= 0.3 | 265 | 5.3% | -0.6% |

**Oracle test (perfect directional signal):**
| Strategy | Trades | Hit Rate | ROI |
|----------|--------|----------|-----|
| Oracle only | 247 | 8.1% | **+41.7%** |
| Oracle + entropy ≥ 2.5 | 146 | 9.6% | **+90.3%** |
| Oracle + entropy ≥ 2.8 | 33 | 15.2% | **+110%** |
| Oracle + price 3-6¢ | 33 | 12.1% | **+170%** |

**Conclusion:** With a perfect directional signal, wing strategy is highly profitable.
The key question is whether NBM can provide that directional signal.

### 4. Miss analysis
- Mean miss: +0.18 brackets, std: 1.80
- |miss| >= 2 brackets: 22.4% of events
- |miss| >= 3 brackets: 11.5% (wings hit territory)
- |miss| >= 4 brackets: 5.2%

### 5. Auto-collection setup
- Script: `scripts/collect_all_cities.py` — gap-filling, 26 cities
- Scheduled task: `polymarket-weather-collect` — daily at ~09:23
- Data: `data/raw/polymarket/all_cities_markets.parquet` (3925 rows)
- History: `data/raw/polymarket/all_cities_price_history.parquet` (1M+ candles)

### 6. Feature ideas identified (not yet tested with NBM)
1. |NBM - consensus| threshold (directional signal strength)
2. NBM percentile spread P90-P10 (model uncertainty)
3. Price velocity (wing price movement over 12/24h)
4. Market entropy (probability concentration)
5. Wing asymmetry (left vs right tail pricing)
6. Tail ratio (inner/outer wing price ratio)
7. Cross-city correlation (weather system propagation)
8. NBM direction × market drift agreement (confirmation signal)

## Next steps
1. **Accumulate NBM data** — daily snapshots via `daily_snapshot.py` (needs 2-4 weeks)
2. **Test NBM as directional signal** — does |NBM_median - market_consensus| predict miss direction?
3. **Amplitude filter** — can NBM P90-P10 spread predict large misses (>= 3 brackets)?
4. **Cross-city weather correlation** — do Asian city misses predict European city misses 12h later?
5. **Execution layer** — Polymarket CLOB API for order placement (only after signal is validated)

## Data locations
- `data/processed/wing_backtest_raw.parquet` — 951 wing trades with features
- `data/processed/wing_backtest_enriched.parquet` — with price velocity added
- `data/raw/polymarket/all_cities_markets.parquet` — 26 cities bracket data
- `data/raw/polymarket/all_cities_price_history.parquet` — CLOB candles
