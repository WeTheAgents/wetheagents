# Codex Handoff — Slow-Horizon (T-1/T-2) Pattern Hunt

**Mission:** find an exploitable, *executable* edge at the slow horizons (T-1 =
tomorrow, T-2 = day-after) of Polymarket daily-high temperature markets. This is
newly possible because we now collect order-book depth at those horizons — the one
thing that blocked every prior slow-horizon study. You are doing exploratory data
analysis; propose and test hypotheses, report honestly (including negatives).

This is a research brief, not a spec. Be adversarial with your own findings, use
walk-forward + date-clustered bootstrap, and run `codex review` on any script that
produces a number we might act on.

## What is already ruled out — do NOT re-litigate

- **US T-0 morning wings: NO-GO (triple-confirmed).** The market is better
  calibrated than NBM in every zone (hot wings: market 2.2% / NBM 7.6% / realized
  1.9%); the model ladder found no edge (`knowledge/handoff_ml_stage4_ladder.md`).
- **Structural edges at their tested horizons: NO-GO** — favorite-longshot (net
  −9%), WU−METAR resolution basis (tiny, market already prices the source),
  cross-city forecast-error teleconnection (no OOS skill). See
  `knowledge/handoff_session10_11_verdicts.md`.
- **Intraday passive bids: NO-GO** (adverse selection). `[[weather-passive-antidote]]`.

**The common thread:** every slow-horizon idea died partly on *"we cannot prove
executability — no order-book depth data exists at T-1/T-2."* That data now exists.
So the open question is narrow and concrete: **at a horizon where the market has
NOT yet locked (T-1/T-2), is there a wing mispricing that (a) predicts resolution
and (b) can actually be filled at a price that survives the spread?**

## The new asset — `data/paper/book_sweeps.parquet`

Windows task `book-sweeps` runs `python -m scripts.paper_dayof --sweep` 3×/day
(09:00/14:30/21:00 local), appending one row per (city, horizon, bracket). Live
since 2026-07-08; ~800 book snapshots/day across 41 cities.

Schema (key columns): `ts_utc` (sweep time), `city_slug`, `market_date` (the
resolution date — LOCAL), `days_ahead` (0=T-0, 1=T-1, 2=T-2), `bracket_index`,
`question` (parse bounds with `scripts.build_ml_panel.parse_bracket` — **note
bracket_index is NOT temperature-ordered**), `role`
(curmax/above/favorite/wing), `best_bid`, `best_ask`, `spread`, `mid`,
`bid_depth_shares`, `ask_depth_shares`, `yes24_avg`/`yes24_complete` and
`no24_avg`/`no24_complete` (VWAP + fill-completeness for a $24 marketable order —
**this is your executability signal**), `run_max_native`/`n_obs` (T-0 only).

Track one bracket over time with the key `(city_slug, market_date,
bracket_index)` across distinct `ts_utc` — up to 6 observations per bracket
already, spanning T-2 → T-1 → T-0.

**Preliminary facts (2 days, directional only — accumulating):**
- **Slow-horizon books are LIQUID, more than T-0.** Two-sided book fraction: T-0
  55%, **T-1 95%, T-2 100%**; median ask depth: T-0 26k, **T-1 66k**, T-2 32k
  shares; median 2-sided spread ~1¢ at all horizons. This reverses the prior
  blocker — depth at T-1/T-2 is real.
- **Prices move a lot T-1 → T-0.** Of 430 brackets seen at both, 47% move ≥2¢;
  cheap wings (T-1 mid ≤15¢) drift +0.3¢ on average (they do NOT simply decay to
  0 — some run up). A predictable component of that move would be tradeable.

## Reusable data + tooling (all committed / on main)

- `data/processed/labels.parquet` — **settlement truth** per (slug, target_date):
  `winner_bracket_final` (the resolving bracket INDEX), `train_ok`, `label_source`,
  `metar_day_max_nat`. Covers all 40 traded cities. This is your `y`.
- `data/raw/nbm_backfill/nbm_dayof.parquet` — clean US NBM day-of percentiles
  (P5–P95 only for the operative period; median |err| 1.6°F). For a T-1 prior you'd
  need `fetch_nbm_s3(..., days_ahead=1)` (fxx=42) via `src/nbm_client.py`.
- `scripts/build_exceedance_dataset.py` — template: turns labels+prices+NBM into a
  per-strike exceedance dataset. **Reuse its correctness handling** (temp_rank
  sorting, strike−0.5 rounded threshold, per-strike stale flag, sum∈[0.9,1.1]
  drop). A T-1 variant = change decision_time and the prior column.
- `scripts/run_wing_ladder.py` — template: walk-forward ladder with market-as-
  baseline offset, incremental-CI gatekeeping, date-clustered + ISO-week bootstrap,
  per-city two-stage sweet-spot test. `src/scoring.py` has log_loss/brier/
  reliability_table.

## Hypotheses to test (ranked; pick where the data is richest)

1. **Executability first (precondition).** Using `yes24_avg`/`yes24_complete` and
   depth: at T-1/T-2, what does it *actually cost* to buy a cheap wing (ask VWAP vs
   mid), and does the fill complete? Bucket by market price and horizon. If cheap
   wings can't be filled without giving up >their edge, everything else is moot.
2. **Price-drift predictability.** Does the T-2→T-1→T-0 price path predict
   resolution beyond the current price? E.g. do wings that *gain* depth/price early
   resolve YES more often than the market implies? Build the per-bracket time series
   and regress resolution on drift features. (Preliminary +0.3¢ cheap-wing drift is
   the hook.)
3. **Is the market less efficient at T-1 than T-0?** Build a T-1 exceedance dataset
   (decision at T-1 evening, prior = the T-1 market and/or the prior-day NBM run),
   re-run the ladder. The T-0 finding was "market ≥ NBM"; test whether that holds
   one day out or whether the market hasn't fully priced yet.
4. **Depth/volume as an information signal.** Does early one-sided depth or a
   widening/tightening spread at T-2/T-1 carry information about the eventual
   winner bracket?
5. **Re-test the session-8–11 signals WITH depth.** The calibrated-tails-at-T-2
   signal (realized 10.2% vs market 5.1%, n=59) was non-executable then. Re-check
   it against real book depth now.

## Guardrails (hard-won on this pipeline)

- **Only ~2 days of book data so far.** Treat everything as directional until
  ~2–3 weeks accumulate. Do not over-fit to a handful of dates.
- **Honest-negative discipline:** walk-forward (never fit on the future),
  date-clustered bootstrap (cities correlate within a day — heat domes), sequential
  gatekeeping, freeze any threshold before the final test block. A borderline CI is
  a NO. The pipeline's value has been *disproving* edges cleanly.
- **Known traps:** `bracket_index` is not temperature-ordered (sort by parsed lower
  bound); US brackets are 1°F with gaps (round in native units); `abnormal_features`
  `city_rate` leaks (recompute in-fold); market candles are trades (stale for thin
  wings — the sweep's live books are better for slow horizons).
- Run inputs from the MAIN checkout `.../weather_kalshi/data` (worktree `data/` is
  empty). `codex review --uncommitted -c 'reasoning.effort="very_high"'` before any PR.

## ⚠ Data-flow dependency (operator action)

The sweep enumerates markets from `all_cities_markets.parquet`, refreshed by
`scripts/collect_all_cities.py` (gamma-api → **needs VPN**, currently **run
manually/by codex, NOT scheduled**). Last refresh 2026-07-09. **If market
collection lapses, T-1/T-2 coverage starves within ~2 days** (future markets stop
landing). Keep collecting daily, or the accumulation stalls.

Related: `[[weather-ml-pipeline]]` `[[weather-structural-edges]]`
`[[weather-dayof-pipeline]]`.
