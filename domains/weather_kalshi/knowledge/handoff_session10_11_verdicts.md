# Session 10–11 Handoff — Structural & Cross-City Edges (all NO-GO)

Follows the session-9 pivot (intraday is dead; compete where inefficiency persists structurally).
Four structural bets were tested on real data. **All four are NO-GO.** This handoff records the
verdicts and the one real correctness fix that fell out of the work.

## Verdicts

### 1. Resolution-basis edge (WU vs METAR) — NO-GO
Polymarket resolves ~24 cities via Weather Underground (whole-degree), and Taipei/Tel-Aviv via NOAA
weather.gov (see `knowledge/Resolving Polymarket weather contracts across 26 cities_markdown.md`).
- Same-station WU−METAR basis is statistically real but economically tiny: pooled n=594, mean
  0.409 half-brackets (~0.2 bracket), p=0.0002, σ=2.68 (huge relative to the mean). Below the
  ~half-bracket bar needed to move a US 1°F bracket reliably.
- **Killer:** on days where WU and METAR disagree (n=153) the market favorite tracks WU 34.6% vs
  METAR 15.0% — the market already anchors to the resolution source, so knowing the basis adds nothing.
- Per-city exceptions worth noting (not pursued): Hong Kong VHHH basis ≈ −1.5 half-brackets
  (WU below METAR, p=0.04), Paris +0.63 (p=0.005), Dallas −0.25 (p=0.04).

### 2. Favorite-longshot — NO-GO
- Back-favorite (price ≥ 0.20): gross +1.3% → **net −9.2%** after spread, −12.1% stressed. The
  earlier "+18% ROI buying the favorite" was a midpoint artifact; the spread eats it.
- Cheap-wing NO-fade: net +1.2% / +0.5% stressed — thinly positive, not executable without
  horizon-matched depth. Median favorite capital lockup 59.5h.

### 3. Calibrated tails at T-2/T-3 — NO-GO (non-executable)
- Weak in-sample signal (model-market edge ≥ 10c rule: realized 10.2% vs market 5.1%, n=59) but
  **no T-2 order-book depth data exists** (only 107 same-day book sweeps, median spread 3c). Cannot
  demonstrate executability.

### 4. Cross-city forecast-error teleconnection — NO-GO
Idea: an upstream city's forecast error today leads a downstream city's forecast error tomorrow
(trading the model's spatially-coherent regime bias, orthogonal to the forecast the market prices).
Panel: 1857 city-days, 45 cities, 2026-04-29..2026-07-02.
- **Timing gate killed all lag-1 pairs** (min margin −1 to −2h): a city's daily high finalizes late
  in the day, after the downstream (often eastern) market has already priced the next day — using it
  would leak future information. Only lag-2 survives cleanly.
- On clean lag-2 links, **0 survived out-of-sample** — no residual skill beyond each city's own
  forecast (best: denver→dallas lag 2, test_n=13, worse than baseline). The NWP forecast already
  absorbs the propagation, as expected.
- Regime-tail variant: OOS Brier improvement ≈ 0 across all 7 configs. No joint-tail underpricing.
- Also constrained by only ~2 months of forecast history → tiny per-pair samples.

## Cross-cutting conclusion
Every bet failed for the same reason: **the market is efficient, it already prices the resolution
source, and on our horizon spread ≥ edge.** The recurring hard blocker for the slow-horizon ideas is
**no order-book depth data at T-2/day-ahead** — executability of any slow-horizon signal cannot be
proven with same-day book sweeps alone. The intraday + structural + cross-city space is, on current
evidence, exhausted at our horizon.

## Station-map bug — identified and specified, NOT yet applied

The audit found that two cities have been tracking the WRONG resolution stations for the whole
project (they affect every study's Houston/London data):
- **Houston**: we use `KIAH` (Bush); Polymarket resolves on **`KHOU`** (Hobby).
- **London**: we use `EGLL` (Heathrow); Polymarket resolves on **`EGLC`** (London City).
- **Taipei / Tel-Aviv**: resolve via **NOAA weather.gov**, not WU (exclude from any WU-basis work).
- **São Paulo**: `SBGR` unconfirmed (do NOT switch to SBMT without market-rule evidence).
- **19 cities** are absent from the resolution research and remain unaudited.

**Why it is not applied here.** A `codex review` showed the station identity is duplicated across
several places, so an `icao_map.json`-only change is inconsistent (forecast would use the old airport
while observations/resolution use the new one). A correct fix must change, together:
- `data/static/icao_map.json` — slug → primary/fallback ICAO (METAR path).
- `data/static/stations.json` — the US station entry is keyed by ICAO (`KIAH`) with its own
  lat/lon, `iem_station_id`, `wunderground_id`; re-key/update to `KHOU`.
- `src/stations.py` — `POLYMARKET_STATIONS` hardcodes `"KIAH"`.
- `data/static/polymarket_cities.json` — Houston/London lat/lon (forecast coords: KHOU ≈ 29.645,
  −95.279; EGLC ≈ 51.505, +0.055) used by `daily_snapshot.fetch_intl_ensemble()`.
- Then re-grep for any remaining hardcoded `KIAH`/`EGLL` references.

This coordinated change is only worth doing if the weather theme continues (it is 4/4 NO-GO). METAR for
the corrected stations was already backfilled locally (IEM ASOS: KHOU 3640 obs, EGLC 6090 obs, in the
gitignored `data/raw/metar/`), so the data is ready if/when the fix is applied.

Study scripts/reports for the four NO-GO bets are intentionally not committed (research-only; numbers
preserved in this doc).
