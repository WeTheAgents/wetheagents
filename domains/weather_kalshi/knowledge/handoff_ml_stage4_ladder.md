# ML Stage 4 — Wing Ladder Verdict: NO-GO on US T-0 wings (2026-07-07)

One full run of the model ladder (`scripts/run_wing_ladder.py`) on the stage-3
exceedance dataset, per the operator's decision ("one run, then expand scope to
T-1 + intl"). Walk-forward: 9 weekly test blocks (2026-W20..W28), expanding train,
per-fold isotonic / validation-tail early stopping. Headline metric: Δlog-loss vs
the market on fresh wing rows (positive = beats market), date-clustered bootstrap CI.

## Results (headline: 2286 fresh wing rows, 29 test dates)

| rung | Δlog-loss | CI (date-clustered) | verdict |
|---|---|---|---|
| r1 NBM param + isotonic | **−0.0441** | [−0.054, −0.034] | **FAIL — decisively worse than market** |
| r2 offset-GLM (market + correction) | +0.0019 | [−0.003, +0.006] | zero (exploratory; gate closed) |
| r3 CatBoost (baseline=market) | −0.0004 | [−0.006, +0.004] | zero (exploratory; gate closed) |

(Gate semantics: a rung passes only if it beats the PREVIOUS rung's headline
log-loss with a positive date-clustered CI; the first test week is clipped to
TEST_START so no pre-cutoff days leak into out-of-sample — both per codex review.)

The gate closed at rung 1: even after in-fold isotonic calibration, an NBM-based
probability is far worse than the market price. The market-anchored rungs (2, 3)
converge to the market itself — exactly what the offset design predicts when
there is no residual signal: the learned correction shrinks to zero.

## Exploratory pockets (all below deployability)

- Sweet-spot cities (Δ>0 in both early AND late test halves): r2 → atlanta
  (+0.008), houston (+0.007), denver, miami, austin, dallas (all ≤ +0.008);
  r3 → houston, seattle, miami. Effect sizes are tiny (≤0.008 log-loss units),
  city-level CIs would be enormous, and the r2/r3 sets don't even agree on which
  cities — the signature of noise, not signal.
- Threshold scan (best rungs @ |model−market| ≥ 5¢): n=45–59 rows over 21 dates,
  EV-proxy **+2.2–4.6¢ per unit at ZERO spread**. Real wing spreads are ≥2–3¢
  plus adverse selection → consumed. Larger thresholds: n=13–23, same story.

## Conclusion

**No deployable edge on US T-0 morning wings.** This is now a triple-confirmed
honest negative: (1) sessions 8–11 structural studies, (2) the stage-3 calibration
table (market better than NBM in every zone), (3) this ladder. The v1 question is
answered definitively with disciplined methodology (walk-forward, gatekeeping,
cluster bootstrap, frozen protocol) — not a data or tooling failure.

Stage 5 (economic gates / paper runner) is **moot for v1** — there is no model to
gate. It remains the template if v2 finds a signal.

## What v2 (T-1 + intl) needs — per operator direction

1. **T-1/T-2 book depth**: collection live since PR #932 (`paper_dayof --sweep`,
   all brackets × horizons, days_ahead tagged). ~2–3 weeks of accumulation gives
   the executability picture that killed every previous slow-horizon study.
2. **Intl prior**: no NBM outside CONUS → the physics prior is the multimodel
   ensemble (`multimodel_members_json` in snapshots — requires the snapshot
   harmonization + ICAO relabel deferred from stage 3a).
3. **Intl decision time**: their local morning ≈ 00–08 UTC; the natural anchor is
   the previous day's forecast run (a true T-1 horizon), which is exactly where
   the fresh book data will tell us if fills exist.
4. Labels already cover all 40 cities (stage 1); the exceedance builder
   generalizes once a per-city prior column is provided.

Related: [[weather-ml-pipeline]] [[weather-ml-stage3-dataset]]
[[weather-structural-edges]].
