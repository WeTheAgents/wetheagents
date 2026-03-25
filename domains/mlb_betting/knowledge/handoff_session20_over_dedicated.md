# Handoff Session 20: OVER Dedicated Model — Negative Result

## TL;DR

**OVER ML pre-filter is NOT viable.** Three model architectures tested, all fail. Signal asymmetry confirmed: the same features that predict UNDER (pitching dominance) have zero predictive power for OVER (scoring explosions). OVER for April 2026 launch should use LLM-only gate or be dropped from portfolio.

---

## Experiments Run

### Experiment 1: Profitability Map (UNDER model inversion)

Used existing UNDER classifier (V3, 21 features, None calibration) and checked the OVER tail: bet OVER when P(under) is low.

**Result: zero signal at every threshold.**

| Threshold | Bets | Hit% | ROI | Seasons+ |
|-----------|------|------|-----|----------|
| P(u)<0.50 | 27,701 | 50.1% | -4.4% | 1/15 |
| P(u)<0.48 | 5,691 | 49.5% | -5.5% | 3/15 |
| P(u)<0.45 | 398 | 49.7% | -5.0% | 7/12 |

Calibration curve: actual OVER rate is ~50% in ALL P(over) bins. No discrimination.

**Script**: `scripts/run_over_profitability_map.py`

### Experiment 2: Dedicated OVER Model (asymmetric offensive features)

Designed `OU_FEATURES_OVER` (22 features) with:
- **Tier 1**: Individual offensive metrics (power_rate, effective_obp, rpg — per team, NOT combined sums)
- **Tier 2**: Individual bullpen vulnerability (bp_fip_osc, bp_ip_3d — per team)
- **Tier 3**: Directional interactions (strong offense x weak opposing bullpen)
- **Tier 4**: Environment context (combined_rpg, rpg_vs_line, wrc_plus_combined)

Three variants tested with walk-forward (14 folds, target=over_hit):

| Variant | Features | AUC | Brier | Std |
|---------|----------|-----|-------|-----|
| A) V3-baseline | 21 (same as UNDER, target flipped) | 0.5110 | 0.2495 | 0.0167 |
| B) OVER-dedicated | 22 (new asymmetric set) | 0.5054 | 0.2499 | 0.0109 |
| C) Minimal-OVER | 11 (Tiers 1+3 only) | 0.5031 | 0.2499 | 0.0164 |

All AUCs are essentially coin-flip (0.50).

**Betting simulation (all negative):**

| Variant | P(over)>=0.52 | P(over)>=0.55 |
|---------|---------------|---------------|
| A | 5,302 bets, 49.8%, -4.9% ROI | 520 bets, 50.8%, -3.1% ROI |
| B | 2,986 bets, 49.7%, -5.2% ROI | 252 bets, 49.2%, -6.1% ROI |
| C | 2,125 bets, 51.5%, -1.7% ROI | 92 bets, 52.2%, -0.4% ROI |

**Calibration (variant B):**
- P(over) [0.55, 0.60): actual 49.0% vs expected 57.5% = **-8.5% gap**
- Model is systematically overconfident on OVER predictions

**Decision Gate: ALL GATES FAILED.**

**Script**: `scripts/run_over_dedicated_model.py`
**Feature list**: `src/features.py:OU_FEATURES_OVER`
**Builder**: `src/features.py:build_ou_features_over()`

---

## Feature Importance (Variant B, last fold)

| Feature | Importance |
|---------|-----------|
| away_offense_x_home_bp_fatigue | 19.09% |
| bp_fip_osc_home | 18.66% |
| bp_ip_3d_home | 12.34% |
| combined_rpg | 8.22% |
| power_rate_away | 6.02% |
| power_rate_home | 5.35% |
| bp_fip_osc_away | 4.73% |
| offense_vs_league_combined | 4.59% |
| effective_obp_away | 4.19% |
| effective_obp_x_sp_ra_away | 3.52% |
| sp_quality_floor | 3.35% |
| rpg_vs_line | 2.64% |
| rpg_home | 2.62% |
| (6 features at 0.00%) | |

**Observations:**
- Directional interaction `away_offense_x_home_bp_fatigue` = top feature (19%) — the design hypothesis was correct in identifying WHAT matters
- But the signal-to-noise ratio is too low to cross the 52.38% breakeven
- Strong home-side bias: home bullpen features dominate, away bullpen features contribute less
- 6/22 features at 0.00% importance = noise

---

## Root Cause Analysis

### Why UNDER works but OVER doesn't

1. **Entropy asymmetry**: UNDER games converge (3-2, 2-1, 4-3 — all "pitching held" patterns). OVER games diverge (12-4 blowout vs 5-4 nailbiter — different mechanisms). Lower entropy = easier to predict.

2. **Feature stability**: Pitching quality (FIP, WHIP, K/BB, RA) is stable start-to-start. Offensive output (runs, hits, HRs) has much higher game-to-game variance. Good pitching consistently suppresses scoring; good offense doesn't consistently produce it.

3. **Market efficiency**: Bookmakers set lines using OVER-biased recreational bettors. The line is already adjusted for "the public likes overs." Finding OVER value requires beating the market + the vig, which requires signal where there may be fundamentally none.

4. **Feature ceiling**: We tested everything available — individual offense, directional interactions, bullpen fatigue x offense, wRC+, power rate. The model finds the right features (bullpen fatigue + opposing offense) but cannot separate signal from noise.

---

## Production Decision

**OVER ML pre-filter is dropped from the portfolio.**

### Options for OVER exposure (if desired)

1. **LLM-only gate** — Run OffenseFirst + FatigueExploit genomes on games where line is 8.5+ and bp_fip_osc > 0.5 on either side. No ML pre-filter. Small volume (~3-5 bets/week), 0.25x base unit. This is session 16 approach (showed 3W-0L at P>=0.55 in tiny sample).

2. **Rules-based heuristic** — bp_fip_osc > 0.5 (either side) AND power_rate_max > 0.35 AND rpg_vs_line > 0.5. Pure rule filter, no model. Then LLM duel for final confirmation.

3. **Skip OVER entirely** — Focus 100% on UNDER (proven +30.6% ROI at P>=0.55) + other strategies (series dogon, run line, YRFI). OVER adds risk without proven edge.

**Recommendation**: Option 3 (skip OVER) for April 2026 launch. Revisit with option 1 (LLM-only) after 1 month of live UNDER data confirms real-time calibration.

---

## Files Changed

| File | Change |
|------|--------|
| `src/features.py` | Added `OU_FEATURES_OVER`, `OU_FEATURES_OVER_MINIMAL`, `build_ou_features_over()` |
| `scripts/run_over_profitability_map.py` | New — UNDER model OVER tail profitability map |
| `scripts/run_over_dedicated_model.py` | Rewritten — 3-variant dedicated OVER experiment |

## Comparison with UNDER (for reference)

| Metric | UNDER (P>=0.55) | OVER best (C, P>=0.55) |
|--------|-----------------|------------------------|
| Bets | 1,402 | 92 |
| Hit rate | 68.4% | 52.2% |
| ROI | +30.6% | -0.4% |
| Seasons+ | 13/15 | 4/8 |
| AUC | 0.5200 | 0.5031 |

The UNDER edge is real and large. The OVER edge does not exist.
