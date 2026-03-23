# Weather Kalshi

Weather prediction market trading for Kalshi temperature contracts.

## Quick Start

```bash
# Install dependencies
uv sync

# Download historical data (MOS forecasts + observations)
python scripts/download_iem_data.py --station KNYC --years 2004-2025

# Run bias analysis
python scripts/run_bias_backtest.py

# Run NO-strategy backtest
python scripts/run_no_strategy_backtest.py
```

## Architecture

Phase 1: Mechanical bias-correction pipeline (no LLM debate layer).

1. **IEM MOS Archive** -- 20+ years of GFS forecast-observation pairs
2. **Bias Analysis** -- per-station, per-month systematic forecast errors
3. **Bracket Builder** -- convert bias-corrected forecasts to Kalshi bracket probabilities
4. **NO Strategy** -- exploit favorite-longshot bias via NO-biased trading

## Cities (Phase 1)

| Station | City | Daily Volume |
|---------|------|-------------|
| KNYC | New York (Central Park) | ~$144K |
| KMIA | Miami International | ~$99K |
| KMDW | Chicago Midway | ~$57K |
