# ML Stage 2 — NBM Day-of Archive Repair (2026-07-07)

The exceedance model's z-score is z = (strike − nbm_median)/nbm_sigma, so a wrong
NBM archive silently poisons everything downstream. It was wrong. This stage found
and fixed the cause, and rebuilt a clean day-of archive.

## The bug was NOT what the plan assumed

The plan (from adversarial review) blamed **fallback timing**: snapshots taken
~11:15 UTC before the 12Z cycle publishes, falling back to yesterday's run without
shifting fxx. That is real but **secondary**. Fetching the *same-day* 12Z fxx=18
directly from S3 still reproduced the wrong ~67°F for NYC 2026-07-03 (realized
100–101°F). Two GRIB-extraction bugs in `src/nbm_client.py` were the real cause:

1. **Wrong field.** At a MaxT fxx the QMD file carries *two* TMP records per
   percentile: the instantaneous `"{fxx} hour fcst"` (temperature AT the valid
   time — 06Z, i.e. overnight for fxx=18) and the windowed `"0-{fxx} hour max
   fcst"` (the daytime maximum). `_find_percentile_ranges` matched on percentile
   only and grabbed the first = the **instantaneous overnight temp**.
2. **Wrong grid cell.** NBM CONUS is a Lambert-conformal grid; latitude/longitude
   are 2D/curvilinear. The old code searched `lats[:,0]` and `lons[0,:]`
   independently, which for KLGA landed in the **Atlantic off Maine** (71°F)
   instead of LaGuardia (102.6°F). Fixed with a true 2D nearest-neighbour
   (`_nearest_grid_cell`).

Both compounded to the ~16–19°F day-of error. **The live NBM path had therefore
never been correct** — every prior "NBM edge" number (e.g. CLAUDE.md's "NBM sigma
0.47–1.4F") was computed on garbage. The fxx mapping itself ({0:18,1:42,2:66,3:90})
was fine.

## Fixes (src/nbm_client.py)

- `_find_percentile_ranges(..., field_marker="max fcst")` — select the windowed
  MaxT field, skip the instantaneous one.
- `_nearest_grid_cell(lats, lons, lat, lon)` — 2D nearest neighbour; cached per
  station across percentiles in `_download_and_extract`.
- Fallback loop in `fetch_nbm_batch` now shifts fxx by +24h per day back (so a
  stale run still targets the right calendar day) — the secondary fix.
- New `fetch_nbm_s3(...)` + `_build_qmd_url(..., source="s3")` — deterministic
  historical fetch from `noaa-nbm-grib2-pds.s3.amazonaws.com`; shared tail
  `_forecasts_from_idx`.

## Validation

`fetch_nbm_s3` day-of `nbm_median` vs realized METAR max (`metar_day_table`):
**median |err| 1.7°F, mean 2.3°F** (was 16.5°F broken; ensemble baseline 2.3°F).
KLGA 2026-07-03: 102.6°F vs realized 100–101°F. One outlier: KORD 2026-07-03
9.6°F (Chicago; possible lake-effect microclimate or genuine miss).

## Backfill

`scripts/backfill_nbm_dayof.py` → `data/raw/nbm_backfill/nbm_dayof.parquet`
(one row per slug × target_date × days_ahead; 11 US NBM cities; each date's own
12Z fxx=18 = the morning-of forecast). Idempotent (skip existing / `--refetch`),
flushes every 10 dates, self-validates by month. Full run 2026-03-09..now.

**Percentile caveat:** the QMD MaxT product exposes only **P5–P95** (7 levels:
5,10,25,50,75,90,95), not P1/P99 (those exist only on the instantaneous field we
correctly drop). Extreme wings (<P5 / >P95) rely on P90/P95 spacing + Pchip
extrapolation — a real limit for the very cheapest wings; revisit in Stage 3/4.
Consumer fix: `build_ml_panel.py::model_prob_in_bracket` used to require all nine
percentiles and would have silently dropped every corrected NBM row — now it uses
whatever percentiles are present (requiring core P10/P50/P90) and adds synthetic P1/P99
tail anchors (`_add_tail_anchors`, linear extrapolation of the outer segments) so finite
wing brackets beyond P5/P95 get monotone mass instead of collapsing to 0. This is an
approximate patch for the legacy edge proxy; the exceedance pipeline (Stage 3) will use
`bracket_builder`'s Pchip CDF, which handles the tail directly.

## Downstream contract

Stage 3 exceedance dataset MUST read NBM from `nbm_backfill/nbm_dayof.parquet`,
NOT from `snapshot_*.parquet` `nbm_*` columns (still broken for history). Going
forward the live `daily_snapshot` NBM is fixed too; run it ≥13:45 UTC for the
freshest 12Z cycle. Related: [[weather-ml-pipeline]] [[weather-ml-stage1-labels]].
