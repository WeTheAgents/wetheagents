# Handoff Session 19 → Session 20: OVER Research

## What Changed This Session

### 1. UNDER Model Overhaul (Production-Ready)

**Platt calibration removed** — replaced with None (raw ensemble probabilities).
- File: `src/model.py:660-679` — Platt block replaced with `calibrator = None`
- Reason: Platt inflated 65% of 0.55+ bets from <0.55 zone (hit 54.8% vs genuine 68.9%)

**Feature set: 22 → 21 (trimmed + V3 interactions)**
- Removed 5 noisy features: `close_ou`, `combined_rpg_last10`, `combined_rapg`, `combined_rapg_last10`, `pyth_wp_combined`
- Added 4 V3 interaction features: `bp_fip_osc_x_rpg`, `matchup_rpg_x_bp_fip`, `sp_quality_gap`, `effective_obp_x_sp_fip`
- Feature list NOT yet updated in `OU_FEATURES` constant — still uses old 22 in `src/features.py:1307`
- V3 features built via `build_ou_features_v3()` in `src/features.py:1512`

**Final A/B results (None calibration, 21 features):**

| Threshold | Bets | Hit% | ROI | P/L |
|-----------|------|------|-----|-----|
| P>=0.52 | 7,221 | 55.6% | +6.1% | +$44,400 |
| P>=0.55 | 1,178 | 70.4% | +34.3% | +$40,464 |

vs OLD (Platt, 22 features): P>=0.52 was -$18,700.

### 2. LLM Expert Expansion Zone — VALIDATED

**Zone A (P 0.51-0.52) pilot: Jun-Sep 2024, 110 games**

| Metric | Baseline (all 110) | LLM-filtered (61 bets) |
|--------|-------------------|----------------------|
| Hit rate | 52.7% | **60.7%** |
| ROI | +0.7% | **+15.0%** |
| P/L | +$73 | **+$918** |

Per-month: Jun +55% ROI, Jul -27%, Aug -5%, Sep +27%. Jul needs genome tuning.

Filtering quality: 54% of OVER games filtered out, 64% of UNDER games kept.

**Script**: `scripts/run_zone_a_pilot.py` — runs LLM duel on Zone A games
**Report**: `knowledge/llm_duel_report_KCR_ARI_20240723.md` — example full duel report

### 3. Production Tiering (Decided)

| Zone | P(under) | Action | Stake |
|------|----------|--------|-------|
| High confidence | >= 0.55 | Auto-bet (no LLM) | 2x |
| Medium confidence | 0.52-0.55 | Auto-bet (no LLM) | 1x |
| Expansion (Zone A) | 0.51-0.52 | LLM duel gate | 0.5x if BET/LEAN |
| Skip | < 0.51 | No bet | 0 |

---

## Next Session Goal: OVER Research

Mirror the UNDER approach for OVER bets. The same model predicts P(under), so P(over) = 1 - P(under) - P(push).

### Proposed OVER Tiering (starting point)

| Zone | P(under) | P(over) approx | Action | Stake |
|------|----------|----------------|--------|-------|
| High confidence OVER | < 0.47 | > 0.53 | Auto-bet by ML scoring | 2x |
| Medium confidence OVER | 0.47-0.49 | 0.51-0.53 | Auto-bet | 1x |
| Expansion OVER | 0.49-0.50 | 0.50-0.51 | LLM expert gate | 0.5x |
| Dead zone | 0.50-0.51 | — | Skip | 0 |

**Note**: P(over) = 1 - P(under) in our model. Pushes (total == line, ~4.7%) are excluded from training and prediction, so model outputs are conditional on not-push.

### Research Steps

1. **Map OVER profitability** — fine-grained ROI by P(under) bins from 0.45 to 0.50
   - Where does OVER become profitable? Is it symmetric with UNDER?
   - Key: the model was trained to predict P(under), not P(over). Signal may be asymmetric.

2. **Check if separate OVER model is needed** — or if low P(under) is sufficient signal
   - Compare: betting OVER when P(under)<0.48 vs training a dedicated OVER classifier

3. **OVER LLM experts exist** — `genomes/ou_over_offense_v1.yaml` + `genomes/ou_over_fatigue_v1.yaml`
   - DuelEngine has `run_over()` method in `src/llm_duel.py`
   - OUFeatureCard has `from_row_over()` classmethod
   - Full infrastructure ready

4. **Pilot OVER expert gate** on expansion zone (P(under) 0.49-0.50)
   - Same approach as UNDER pilot: pick Jun-Sep 2024, run LLM duel, score

### Key Files

| File | Purpose |
|------|---------|
| `src/model.py:591-726` | UnderModelConfig, train_under_model, predict_under_proba (None calibration) |
| `src/features.py:1307-1379` | OU_FEATURES, V2, V3 feature lists |
| `src/features.py:1382-1556` | build_ou_features(), build_ou_features_v3() |
| `src/llm_duel.py:run_over()` | OVER duel engine (symmetric to run_ou) |
| `src/llm_expert.py:analyze_over()` | OVER expert analysis |
| `src/feature_card.py:from_row_over()` | OVER betting card builder |
| `genomes/ou_over_offense_v1.yaml` | OffenseFirst OVER expert |
| `genomes/ou_over_fatigue_v1.yaml` | FatigueExploit OVER expert |
| `scripts/run_zone_a_pilot.py` | UNDER pilot (adapt for OVER) |
| `scripts/run_dress_rehearsal.py` | Full portfolio dry-run |

### Data Notes

- Model trained on `under_hit` target (binary: 1=under, 0=over, pushes excluded)
- P(under) from walk-forward with None calibration, 21 features
- OVER calibration curves from session 19 A/B:
  - [0.45-0.50): 27,939 games, actual=49.9% under → 50.1% over
  - Tail behavior for OVER not yet mapped at fine granularity
- Push rate: ~4.7% (2,235 out of 47,070 games) — excluded from model, P(over) = 1-P(under)
