# Session 22 — NRFI Binary Classifier: Hypothesis Killed

**Date**: 2026-03-25
**Goal**: Build binary NRFI classifier via UNDER model architecture, A/B/C feature comparison
**Verdict**: NRFI ML is DEAD. All three feature sets failed decision gates.

## What Was Built

- `src/features.py`: `NRFI_FEATURES_A` constant (13 1st-inning features)
- `src/model.py`: `NRFIModelConfig`, `NRFIFoldResult`, `train_nrfi_model()`, `run_walk_forward_nrfi()`
- `src/market_builder.py`: `estimate_nrfi_odds()` moved from scripts (8-point calibration curve)
- `scripts/run_nrfi_model.py`: 10-step A/B/C experiment with market-adjusted ROI

## Experiment Results

### Walk-Forward AUC (barely above coin flip)

| Set | Features | Mean AUC | Mean Brier |
|-----|----------|----------|------------|
| A (1st-inning) | 13 | 0.5258 | 0.2492 |
| B (UNDER V3) | 6/26 | 0.5200 | 0.2493 |
| C (hybrid) | 12 | 0.5187 | 0.2494 |

### Profitability Map (best rows only)

| Set | Threshold | Bets | Hit% | Avg Odds | Adj ROI | Seasons |
|-----|-----------|------|------|----------|---------|---------|
| B | P>=0.55 | 92 | 59.8% | 1.69 | +0.5% | 2/3 |
| B | P>=0.56 | 44 | 61.4% | 1.67 | +2.7% | 2/3 |
| C | P>=0.55 | 122 | 61.5% | 1.72 | +5.6% | 3/5 |

Marginal signal at extreme thresholds, but too few bets and seasons.

### Decision Gates: ALL FAILED

- Gate 1 (Production: P>=0.60, >60% hit, >0% ROI, >=7/15 seasons): **FAIL** — model never generates P>=0.60
- Gate 2 (High-Conf: P>=0.65, >65% hit, >0% ROI): **FAIL** — model max prediction ~0.58

## Why It Failed

### 1. Base rate myth busted
Session 21 estimated NRFI base rate ~57%. Actual after filters: **49.2%** (range 46.3%–53.3% across seasons). Below breakeven of 52.8% at average odds 1.904. The "starters at peak, only 18 PA" argument doesn't hold — first innings are close to 50/50.

### 2. 18 plate appearances = noise
First-inning outcomes are dominated by randomness. Unlike full-game O/U (where 70+ PA smooth variance), 18 PA per half-inning means a single walk or bloop single flips the outcome. ML can't find stable signal in this noise — AUC 0.52 is the ceiling.

### 3. Set B was crippled (but still best)
Only 6/26 UNDER V3 features available in YRFI DataFrame. `build_yrfi_features()` doesn't compute bullpen FIP, sp_ra_combined, pitcher interaction features. Even crippled, Set B matched Set A — suggesting full-game features carry as much 1st-inning signal as 1st-inning-specific features.

### 4. Feature importance dominated by close_ou
close_ou accounts for 22% (Set A), 43% (Set B), and the model is essentially learning "low O/U games → NRFI" which the market already prices. No edge beyond what's in the line.

## Key Learnings

1. **NRFI is not inverse YRFI for ML purposes.** YRFI benefits from asymmetric signal ("one weak pitcher + one strong lineup = runs"). NRFI needs symmetric signal ("both pitchers suppress") which is harder to detect with 18 PA.

2. **Base rate assumptions must be validated before building.** The 57% estimate was from unconditional stats; after betting filters, reality is 49%.

3. **Market-adjusted ROI matters more than hit rate.** Even Set C's 61.5% hit at P>=0.55 only yields +5.6% ROI because odds at that threshold average 1.72 (breakeven 58.1%).

4. **Rule-based NRFI filters (from session 20) remain the only viable NRFI approach.** Pitcher-specific thresholds can identify extreme matchups the ML misses because they don't rely on aggregate signal.

## What Stays vs What's Dead

| Component | Status |
|-----------|--------|
| NRFI ML classifier | **DEAD** — do not revisit |
| `estimate_nrfi_odds()` in market_builder | **KEEP** — useful for rule-based NRFI |
| `NRFI_FEATURES_A` constant | KEEP — documents the feature set for reference |
| `run_nrfi_model.py` script | KEEP — documents the negative result |
| Rule-based NRFI from session 20 | **ALIVE** — pitcher-specific filters still viable |
| YRFI ML (CatBoost multiclass) | **ALIVE** — separate market, different signal |

## Next Steps

- Focus on proven markets: UNDER (30.6% ROI), Moneyline, YRFI
- Rule-based NRFI can remain as a secondary market with pitcher-specific filters
- Do NOT attempt to "fix" NRFI ML — the signal ceiling is structural (18 PA noise)
