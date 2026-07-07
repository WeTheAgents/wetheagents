# ML Stage 1 — Labels Rebuild (2026-07-07)

Stage 1 of the cheap-wings ML plan: replace the broken `ml_panel.realized_in_bracket`
labels with a canonical settlement-label table. Builder: `scripts/build_labels.py` →
`data/processed/labels.parquet` (+ `labels_meta.json`, `reports/labels_report.html`).

## Design (and what the data forced us to change)

Planned: market-implied winner (unique bracket, last candle ≥ 0.90) gated by "history
must extend ≥6h past local day end" to catch late reversals. **The gate turned out to be
inverted in practice** — full-archive diagnosis:

- Candles are trades. Most markets go quiet before local midnight (median last candle
  ≈ 45h *before* day end across all events incl. never-active far-dates); only ~34% of
  events ever print a ≥0.90 last candle.
- Raw-winner vs METAR agreement by trading lifetime: ≤ −12h: 98.8% (n=163), −12..−6h:
  92.3%, −6..−3h: 95.2%, −3..0h: 89.3%, 0..+6h: 93.6% (n=1075), **>+6h: 50.0% (n=40)**.
- So early-dying markets lock *correctly*; the only toxic bucket is markets still
  trading >6h past day end — the resolution-dispute signature.

Final rule: no minimum-history gate; `labeled_disputed` quarantine for >6h-past-day-end
events (47); `too_recent` guard = day_end + 12h must precede the download tip (an
intraday ≥0.90 print can still reverse while the day is running). Disputed days are NOT
blindly given the METAR label: agreement is checked against the raw market winner, so a
disputed day whose winner disagrees with METAR becomes a `conflict` (quarantined), while
one that agrees is kept — this moved 20 rows from silent-METAR into conflict (80→100).
The METAR label is also gated on `day_end ≤ hist_max_ts` so a still-climbing current day
can't freeze a partial running max as a "final" label.

Layered final label (`winner_bracket_final`, `label_source`):
market where trusted → METAR rounded-native max (`metar_day_table.parquet`, corrected
stations, PR #929) as fallback → conflicts quarantined.

## Numbers (archive 2026-03-09 .. 2026-07-06, ~4670 events, 42 cities)

(Event count drifts up as the live main-checkout gains future markets with no candles
yet — those land as `no_history` and are never trainable. Snapshot below from the
2026-07-07 build.)

| metric | value |
|---|---|
| market label trusted | 1546 (33%) |
| market label disputed (quarantine) | 47 |
| no price history (future/bracket-only day) | 44 |
| recent partial day, METAR not settled yet (quarantine) | 27 |
| METAR label available | 4097 |
| both present → agreement | **94.1%** (1280/1360) |
| conflicts (quarantine) | 80 (1.7%) |
| **train_ok** (final label, minus taipei/jakarta) | **4096 city-days, 40 cities** |
| train_ok by source | market 1436 / metar 2660 |

A **METAR recency gate** (added after codex P1): a day's METAR max is only trusted once
the local day is fully elapsed as of the freshest data timestamp (`day_end ≤ hist_max_ts`),
so a still-climbing current day cannot freeze a partial running max as a "final" label.
`day_end` is the next **local** midnight (not +24h) so DST-transition days are exact.

**Old-label breakage reproduced:** the old panel had 1321 events; **129 had zero
matching bracket** (the observed max landed in no bracket at all — pure rounding
breakage) and 1192 had a unique old winner. On the 1109 of those comparable to a new
final label, the old `realized_in_bracket` disagrees on **759 (68.4%)** — matching the
2026-07-03 finding (643/924 = 69.6%). Root cause (unchanged): raw `temp_max_native`
compared to bracket bounds without native-unit rounding + ERA5 obs for intl cities.

## Flags for later

- **shenzhen: 24 of the 80 conflicts** — systematic, same region as Hong Kong's known
  negative WU−METAR basis (session 10). Candidate for resolution-station audit or
  exclusion before intl (v2) training. taipei (17 conflicts) already excluded.
- Isolated huge conflicts (market vs METAR 3–8 brackets apart: amsterdam 2026-06-26,
  buenos-aires 2026-06-11) look like station mismatches, not rounding noise —
  quarantine handles them; audit only if the pattern grows.
- v1 (US NBM cities) is clean: ≤2 conflicts per US city.
- METAR gaps (`no_metar_day`): taipei 52, sao-paulo 20, SF/austin/atlanta/seattle ~18
  each — collection gaps; market label covers part of them.

## Usage contract for downstream stages

Train/eval joins on `labels.parquet` filtered to `train_ok == True`; never read
`realized_in_bracket` from `ml_panel.parquet`. `label_source` is kept per row so the
model ladder can run a robustness pass on market-labeled rows only.
