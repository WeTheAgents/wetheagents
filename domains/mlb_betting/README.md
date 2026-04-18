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
    & ~games["is_extreme_line"]     # skip favorites > 300
]
# September now INCLUDED (validated profitable across 5 seasons)
```

## Scripts

See `scripts/` and `knowledge/status_report_session3.md`.

## Operational Memory

Use these docs as the current working memory for MLB research:

- `knowledge/layered_basket_selection_method.md` -- canonical basket-promotion workflow
- `knowledge/bullpen_day_chat_watchlist_2026.md` -- chat-first bullpen-day rotation watchlist for the 2026 season

Current bullpen-day workflow is intentionally chat-first until a stricter model is promoted.
