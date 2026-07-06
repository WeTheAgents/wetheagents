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

## ⚠ Known issue for ML data prep — legacy-station joinability

Six cities changed resolution station (2026-07-06). Historical data collected BEFORE the change is
keyed by the OLD ICAO, and `scripts/build_ml_panel.py` maps station→slug via `ICAO_TO_SLUG` (derived
from the current `STATIONS` registry, which no longer contains the old codes). So when rebuilding the
ML panel, **pre-change forecast/snapshot rows for these cities will orphan and their historical forecast
features will drop** unless a legacy-alias map is added.

METAR is NOT affected: the corrected stations were backfilled for the full history (2026-03-01..), so
`metar_day_table` rebuilt on the corrected `icao_map` is complete. The gap is only the point-in-time
FORECAST snapshots (which cannot be re-fetched for the corrected coordinates).

Old → new station map to wire into `build_ml_panel` (add these as `ICAO_TO_SLUG` aliases when building
the panel, so historical rows still join):

| slug | old ICAO | new (resolution) ICAO |
|------|----------|------------------------|
| houston | KIAH | KHOU |
| dallas | KDFW | KDAL |
| denver | KDEN | KBKF |
| london | EGLL | EGLC |
| moscow | UUEE | UUWW |
| jakarta | WIII | WIHH |

Note the historical forecasts for these cities are for the OLD airport (wrong coords, ~30 km off);
going forward both forecast and obs use the corrected station. Decide in the ML chat whether to keep
the old-airport forecast history (continuity) or start the clean series at the correction date.

## Provenance

- Resolution stations were audited 2026-07-06 against Polymarket market rules (gamma-api market
  descriptions) for all 42 traded cities; see the audit corrections in `README_stations.md` and the
  session-10/11 handoff. `dc`, `phoenix`, `dubai` are in the configs but not traded on Polymarket.
