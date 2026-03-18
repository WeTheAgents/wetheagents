# Claude Code Instructions -- wea-poker

## Overview

Autonomous poker bot for PokerNow.com play-money tournaments. Plays Texas Hold'em NL (single table and MTT). Strategy: preflop lookup tables + Monte Carlo equity postflop.

## Architecture

Three-layer pipeline:
1. **Table Interface** (`src/table/`) — Selenium-based PokerNow automation
2. **Decision Engine** (`src/strategy/`) — preflop lookup + postflop equity + bet sizing
3. **Opponent Tracker** (`src/tracker/`) — per-player VPIP/PFR stats

## Running

```bash
# Install dependencies
uv sync

# Single bot (tournament or cash)
python scripts/run_bot.py --url <pokernow_url> --name "PlayerName"

# Training arena (multiple bots, one table)
python scripts/run_arena.py --url <pokernow_url> --players 5 --hands 200
```

## Key Files

- `src/table/state.py` — GameState, Action, PlayerState dataclasses
- `src/table/connector.py` — PokerNow browser automation
- `src/strategy/engine.py` — top-level `get_action(state) -> Action`
- `src/strategy/preflop.py` — preflop range lookups
- `src/strategy/postflop.py` — Monte Carlo equity + pot odds decisions
- `data/preflop_ranges.json` — TAG ranges by position and stack depth
- `data/push_fold.json` — Nash equilibrium push/fold charts (<20BB)

## Strategy Parameters

Strategy configs in `data/strategies/` control:
- Preflop ranges (VPIP/PFR targets)
- Postflop aggression thresholds
- C-bet and bluff frequencies
- Bet sizing preferences

## Research

Full technical research: `../../research/pokernow_text_markdown.md`
