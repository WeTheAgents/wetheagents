# Weather Kalshi — Data Manifest

Where the domain's data lives after the 2026-07-06 consolidation. **The single canonical copy of all
live data is the main repo checkout** (`.../wetheagents/domains/weather_kalshi/data`). Other clones and
worktrees have either empty (gitignored) or redundant `data/` — do not treat them as sources of truth.

All `data/` paths below are **gitignored** (`data/raw/`, `data/processed/`, `data/paper/`) — they are
local, not committed. Only static config (`data/static/`) is in git.

## data/static/ (committed)

- `stations_canonical.json` — **single source of truth** for per-city station identity (resolution
  source + station, obs ICAO + fallbacks, coords, timezone, unit, US/Kalshi fields). Edit this, then
  run `python -m scripts.gen_station_configs` to regenerate the three legacy files below. A test
  (`tests/test_station_configs.py`) guards drift.
- `icao_map.json`, `polymarket_cities.json`, `stations.json` — **generated** from the canonical.
- `README_stations.md` — how to edit/regenerate.

## data/raw/ (gitignored — live collected feeds)

- `metar/metar_{ICAO}.parquet` — hourly METAR, keyed by resolution ICAO. The six corrected stations
  are backfilled from IEM ASOS (2026-03-01..): KHOU, EGLC, KDAL, KBKF, WIHH, UUWW.
- `taf/taf_{ICAO}.parquet`, `hrrr/hrrr_{ICAO}.parquet` (US only), `nbm/{cycle}/{fxx}/...` (US grid).
- `observed/obs_{slug}.parquet` — daily max/min per city (Open-Meteo archive), keyed by slug.
- `snapshots/snapshot_{date}.parquet` — daily forecast snapshots (NBM/ensemble), from 2026-03-25.
- `polymarket/all_cities_markets.parquet` (market metadata), `all_cities_price_history.parquet`
  (10-min candles).

## data/processed/ (gitignored — derived)

- `metar_day_table.parquet` — daily METAR highs by (slug, local hour). **Rebuild after any station-map
  change** so it reflects the corrected stations.
- `ml_panel.parquet` — ML training panel (slug × target_date × bracket).
- study checkpoints / feature parquets from prior research.

## data/paper/ (gitignored — paper-trading ledgers)

- `paper_trades.jsonl`, `paper_runs.jsonl`, `book_sweeps.parquet` — the live **day-of** scalp paper
  runner (scheduled task `dayof-paper-trade`).
- `passive/` — the **passive-bid** experiment ledger, consolidated 2026-07-06 from the
  `wetheagents-codex-paper-passive-bids` worktree: `paper_trades.jsonl` (27 settled),
  `paper_order_snapshots.jsonl`, `paper_runs.jsonl`. Kept separate from the day-of ledger.

## ML data-prep contract (operator decisions, 2026-07-06)

Completeness verified 2026-07-06 (window 2026-03-01..07-06): METAR complete for 41/42 cities
(~112–128 days; the six corrected stations backfilled to full history); observed complete;
forecast snapshots 25 Mar–6 Jul; prices mostly 97–119 days. `metar_day_table` has been rebuilt on the
corrected stations. Decisions for the ML pipeline:

1. **Exclude `taipei`** — only 65 days of METAR (RCTP from 27 Apr) and its resolution is the Taiwan CWA
   city station 46692, not the RCTP airport proxy. Drop it from training and evaluation.
2. **Keep `jakarta` but do NOT train on it** — only 49 days of price history (from 3 Apr). Usable for
   context, not as a training city.
3. **Harmonize the forecast snapshots to the new schema; do NOT keep legacy ICAO aliases** — early
   snapshots are keyed `slug`+`icao`, later ones `station`+`pm_bracket_*`. Unify to one schema and
   **relabel historical rows of the six corrected cities from the old station code to the new resolution
   ICAO** (KIAH→KHOU, KDFW→KDAL, KDEN→KBKF, EGLL→EGLC, UUEE→UUWW, WIII→WIHH) so each city is one
   continuous series under its correct station. The pre-change forecasts are for the old-airport
   coordinates (~30 km off) — accepted; observations/resolution are correct via the backfill.

## Provenance

- Resolution stations were audited 2026-07-06 against Polymarket market rules (gamma-api market
  descriptions) for all 42 traded cities; see the audit corrections in `README_stations.md` and the
  session-10/11 handoff. `dc`, `phoenix`, `dubai` are in the configs but not traded on Polymarket.
