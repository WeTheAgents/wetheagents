# Spec — dayof-paper-trading

Outcome: see outcome.md (v0.1). This spec defines observable behavior.

## Components

1. `src/clob_book.py` — CLOB order-book client + fill simulation
2. `scripts/paper_dayof.py` — runner with modes `--trade`, `--settle`, `--sweep`
3. `scripts/build_paper_report.py` — HTML report → `reports/paper_trading_report.html`
4. Windows scheduled task `dayof-paper-trade` — every 15 min, runs `--trade --settle`

## Behavior requirements

**B1. Order book (`fetch_order_book`)**: GET `{CLOB_BASE}/book?token_id=...`.
Returns bids/asks normalized to floats, best-first. Empty/missing sides allowed.

**B2. Fill simulation (`walk_fill`)**: given a book side and a target stake in $,
walk levels best-first, return (avg_price, shares_filled, stake_filled, levels_used).
Partial fill when depth runs out. Pure function, unit-tested.

**B3. `--trade` mode** (each run):
- Load today's + tomorrow's markets from `data/raw/polymarket/all_cities_markets.parquet`
  (collected daily); cities from `polymarket_cities.json` with a primary ICAO in `icao_map.json`.
- For each city, compute local now. Strategy windows:
  - **A (curmax-buy)**: local time in [15:00, 15:15) → buy YES $100 on the bracket
    containing the rounded native-unit running max, skip if best ask > 0.85 or book empty.
  - **B (above-NO)**: local time in [16:30, 16:45) → buy NO $100 on the bracket above
    the current-max bracket, only if YES last/bid in [0.02, 0.50]. NO fill = walk YES
    bid side; NO price = 1 − VWAP(bids walked).
- Running max: live AWC METAR (`fetch_metar_bulk`, hours=20), obs filtered to the
  city's local calendar day, native-unit rounding as in the study
  (round °F for US, round °C for INTL).
- Dedup: at most one trade per (strategy, city, market_date) — checked against ledger.
- Every considered city leaves a run-trace row (traded / skipped+reason).
- Ledger: append JSONL `data/paper/paper_trades.jsonl`; traces `data/paper/paper_runs.jsonl`;
  full book snapshot embedded in the trade row.

**B4. `--settle` mode**: for open trades whose city-local day ended ≥ 3h ago, fetch
price history for the traded YES token; last price ≥ 0.90 → bracket won,
≤ 0.10 → lost, else leave open. P&L: strategy A wins pay (1−fill)/fill per $;
strategy B (NO) wins pay fill_no→(1−fill_no) economics; recorded per trade.
Settlement updates the trade row (rewrite JSONL atomically).

**B5. `--sweep` mode** (executability study, run ad-hoc): for every city with a market
today, regardless of window: fetch METAR + books for the current-max bracket, the one
above, and the market favorite; record best bid/ask, spread, depth at best,
simulated $100 fill slippage vs mid. Output `data/paper/book_sweeps.parquet` (append).

**B6. Report**: `build_paper_report.py` renders self-contained HTML (Plotly inline,
Russian prose): executability snapshot (spreads/depth/slippage vs the study's 1¢
assumption), paper P&L to date per strategy (once settles exist), run health
(traces, gaps), and a "how it works" section. Must render meaningfully on day 0
(sweep only, no settled trades yet).

**B7. Scheduling**: Windows `schtasks` task `dayof-paper-trade`, every 15 minutes,
absolute python path, Start-In = domain dir, output appended to `logs/paper_dayof.log`.
Removal documented in report (`schtasks /delete /tn dayof-paper-trade`).

**B8. Failure behavior**: any network error → log to run-trace, exit 0 (no retries
inside a run; next run in 15 min is the retry). No exceptions may kill settlement
of other trades.

## Acceptance criteria

- [ ] Unit tests for `walk_fill` (full fill, partial, empty book) pass.
- [ ] `--sweep` produces a non-empty parquet against live CLOB.
- [ ] `--trade` executes for at least one city live (Asia afternoon at build time)
      and writes a ledger row with embedded book.
- [ ] Dedup verified: second `--trade` run within the window does not duplicate.
- [ ] Scheduled task registered and visible in `schtasks /query`.
- [ ] Report builds and is sent to operator; renders with 0 settled trades.
