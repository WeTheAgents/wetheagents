# mlb-betting

MLB baseball betting backtest system. Goal: find sustainably profitable strategies for Polymarket MLB markets (launch: April 2026).

## Approaches

- Rules-based -- expert filters (RPI, pitchers, form)
- LLM estimator -- fair odds estimation via OpenAI Batch API
- CatBoost ML -- gradient boosting on 35+ features (67 total)

## Quick Start

```bash
# Install (uv or pip)
python -m venv .venv
# Windows: .\.venv\Scripts\activate
pip install -U pip
pip install -e .
```

Feature computation example:

```bash
python -c "from src.features import build_all_features; from src.data_loader import *; g=load_all_seasons(); g=apply_data_filters(g); g=add_derived_odds(g); e=build_all_features(g)"
```

## Key Betting Filters

Always apply before selecting bets:

```python
from src.data_loader import apply_data_filters, add_derived_odds

games = apply_data_filters(games)  # remove 2020, missing odds/pitcher, double-headers
games = add_derived_odds(games)    # decimal odds, implied probs

bettable = games[
    ~games["involves_col"]          # never bet Colorado games
    & ~games["is_september"]        # skip September tanking
    & ~games["is_extreme_line"]     # skip favorites > 300
]
```

## Scripts

See `scripts/` and `knowledge/status_report_session3.md`.
