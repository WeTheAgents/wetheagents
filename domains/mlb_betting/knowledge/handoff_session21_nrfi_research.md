# Handoff Session 20 -> Session 21: NRFI Binary Classifier Research

## Session 20 Summary

**OVER ML is dead.** Three architectures tested (UNDER inversion, V3 baseline on over_hit, dedicated OVER features with asymmetric offense), all at AUC ~0.50, all negative ROI. OVER dropped from portfolio. See `knowledge/handoff_session20_over_dedicated.md`.

**UNDER model confirmed dominant:** P(u)>=0.55 → 68.4% hit, +30.6% ROI, 13/15 seasons.

---

## Session 21 Goal: NRFI Binary Classifier

### The Question

We predict UNDER (full game under O/U line) with 68% hit rate at the high-confidence tail. Can we predict NRFI (No Runs First Inning — 1st inning total = 0) with similar accuracy?

**Intuition**: Both UNDER and NRFI are "pitching suppresses scoring" bets. The same signals (strong starters, low offense, good K/BB ratio) should work for both. If anything, NRFI should be EASIER because:
- 1st inning is the most predictable (starters at full strength, no bullpen variance)
- The base rate is favorable: ~56-59% of games have NRFI (depending on line)
- Market breakeven is lower: ~54% at 1.85 odds vs 52.4% at -110

### What Exists vs What's Missing

**Exists:**
- `build_yrfi_features()` in `src/features.py:1857` — full 1st-inning feature set
- `sp_fi_ra_short/long` — pitcher's 1st-inning runs allowed (5/15-start rolling)
- `sp_fi_momentum` — 1st-inning form oscillator
- `top3_babip_inn1_combined` — batter 1st-inning BABIP
- `fi_score_rate_combined` — team 1st-inning scoring tendency
- YRFI CatBoost 3-class model (`scripts/run_yrfi_catboost.py`) — predicts P(0), P(1), P(2+)
- Rule-based NRFI filters (`scripts/run_nrfi_backtest.py`, `scripts/run_nrfi_research.py`)
- Market odds calibration from close_ou (NRFI odds: 1.61-2.36 range)

**Missing (the experiment):**
- **Binary NRFI classifier** (like the UNDER model) — trained on `nrfi_hit` target with walk-forward
- Profitability map: P(nrfi) by bins, cumulative thresholds
- Calibration curve: actual NRFI rate vs predicted P(nrfi) — does the model discriminate?
- Direct comparison: NRFI at P(nrfi)>=0.55 vs UNDER at P(under)>=0.55

### Research Plan

#### Step 1: Build NRFI feature set

Two candidate sets to A/B test:

**Set A: 1st-Inning Specific (from build_yrfi_features)**
- `sp_fi_ra_combined` — combined 1st-inning RA (short window)
- `sp_fi_ra_combined_long` — combined 1st-inning RA (long window)
- `sp_fi_momentum_combined` — 1st-inning form oscillator
- `fi_score_rate_combined` — team 1st-inning scoring tendency
- `fi_score_rate_last_combined` — recent 25-game 1st-inning rate
- `top3_babip_inn1_combined` — batter contact quality in 1st inning
- `sp_babip_inn1_combined` — pitcher hit-allowing quality in 1st
- `effective_obp_home/away` — handedness-matched OBP (1st AB matchup)
- `starter_fip_combined` — combined starter FIP
- `starter_kbb_combined` — combined K/BB ratio
- `starter_whip_combined` — combined WHIP
- close_ou bucket or rpg_vs_line (market context)

**Set B: UNDER-derived (reuse UNDER model features on NRFI target)**
- Same 21 V3 features from the UNDER model, but target = nrfi_hit
- Tests whether full-game features also predict 1st-inning outcomes
- If this works, it means the signal is the same (pitching quality → NRFI)

**Set C: Hybrid** — best of A + best of B based on feature importance

#### Step 2: Walk-forward binary classifier

Reuse `run_walk_forward_under()` infrastructure:
- Target: `nrfi_hit = (inn1_runs == 0).astype(int)` — 1 if no runs in 1st inning
- Exclude: games without inning data (2004-2009 have fake zeros, only 2010-2025 valid)
- Walk-forward: same expanding/sliding window as UNDER model
- Metrics: AUC, Brier, calibration curve

#### Step 3: Profitability map

- Fine bins: P(nrfi) from 0.50 to 0.70 in 0.01 steps
- Cumulative thresholds: P(nrfi) >= X for each cutoff
- Market-adjusted odds (from close_ou calibration table, not fixed 1.85)
- Per-season breakdown for each threshold
- Symmetry comparison: NRFI tail vs YRFI tail (like we did for UNDER vs OVER)

#### Step 4: Decision gate

1. If P(nrfi)>=0.60 shows >60% hit AND >0% adj_roi AND >=7/15 seasons → production tier
2. If P(nrfi)>=0.65 shows >65% hit AND >0% adj_roi → high-conf only tier
3. If nothing works → NRFI ML is also dead (use rule-based filters from existing NRFI research)

### Key Hypotheses

**H1 (Optimistic)**: NRFI should be MORE predictable than UNDER because:
- Only ~18 plate appearances (top of lineup), less randomness than full game
- Starters are at peak (no fatigue, no bullpen involved)
- 1st-inning-specific features (sp_fi_ra, babip_inn1) capture exactly the right signal
- Higher base rate (~57%) means less edge needed to be profitable

**H2 (Pessimistic)**: NRFI could fail because:
- Small sample per game (one inning = 6 outs) → high variance per bet
- Market may already price NRFI correctly using pitcher-quality signals
- Correlation between our features and 1st-inning outcome may be low (0.046 close_ou→YRFI)
- The 0.046 correlation is for close_ou specifically; 1st-inning-specific features should correlate higher

**H3 (Key test)**: Set B (UNDER features on NRFI target) works → proves same signal drives both markets. Set A works better → proves 1st-inning features add discriminative power.

### Key Data Notes

- **Valid inning data**: 2010-2025 only (2004-2009 have fake zeros from SDQL/JSON sources)
- **NRFI base rate**: ~56-59% of games (scoreless 1st inning), varies by close_ou
- **NRFI odds calibration** (from run_nrfi_research.py):
  - close_ou 6.5 → odds 1.61 (breakeven 62.1%) — cheap, hard to beat
  - close_ou 8.25 → odds 1.91 (breakeven 52.4%) — sweet spot
  - close_ou 11.0 → odds 2.36 (breakeven 42.4%) — expensive, easier to beat
- **Push rule**: no push in NRFI — either runs score (YRFI) or they don't (NRFI)

### Key Files

| File | Purpose |
|------|---------|
| `src/features.py:build_yrfi_features()` | 1st-inning feature builder (line 1857) |
| `src/features.py:OU_FEATURES_V3` | UNDER model features (for Set B) |
| `src/pitcher_features.py` | sp_fi_ra, sp_fi_momentum computation |
| `src/model.py:run_walk_forward_under()` | Walk-forward infrastructure (reuse) |
| `src/market_builder.py:add_yrfi_market()` | 1st-inning target construction |
| `scripts/run_nrfi_research.py` | NRFI odds calibration table |
| `scripts/run_nrfi_backtest.py` | Rule-based NRFI filters |
| `scripts/run_yrfi_catboost.py` | YRFI 3-class model (reference) |
| `data/processed/retrosheet/first_inning_babip.parquet` | 1st-inning BABIP data |

### What NOT to Do

- Don't use 2004-2009 games for NRFI/YRFI (fake inning zeros)
- Don't assume fixed 1.85 odds — use market-adjusted odds from close_ou calibration
- Don't compare raw hit rates without adjusting for odds/breakeven differences
- Don't forget: UNDER breakeven is 52.4% at -110; NRFI breakeven varies by game (52-62%)
