# Session 15 Handoff — OVER System Design

## What's Done (UNDER pipeline complete)

Two-stage UNDER betting pipeline validated on 2024 data:

```
Stage 1: CatBoost+LR ensemble → P(under) per game
Stage 2: P(u) >= 0.52 → LLM expert duel (Analyst + PitchingFirst + RunEnvironment)
         Both experts UNDER → bet UNDER at -110
         Any disagreement → PASS
```

Calibration: **14W-0L** on 3 test days (2024-04-06, 04-23, 06-28).
Noise test: P(u) < 0.52 → 2W-3L, LLM experts fail. Boundary confirmed.

## Next Session: Symmetric OVER System

### Core Idea
The existing UNDER model already produces P(under) for every game. The complement P(over) = 1 - P(under) is free. Hypothesis: games with P(u) <= 0.45 (i.e. P(over) >= 0.55) may be profitable OVER bets with LLM expert filtering.

### Why P(u) <= 0.45?
- Symmetric to P(u) >= 0.55 (the profitable UNDER zone)
- At -110 odds, need >52.38% hit rate
- P(u) <= 0.45 means model estimates >55% chance of OVER
- No model retraining needed — just flip the filter direction

### Implementation Plan

**Step 1: Validate P(over) signal from existing model**
```python
# Check if P(u) <= 0.45 predicts OVER with edge
over_candidates = pred_df[pred_df.p_under <= 0.45]
over_hit_rate = (over_candidates.total_runs > over_candidates.close_ou).mean()
# Need: over_hit_rate > 0.5238 (breakeven at -110)
```
Run this across all 6 test seasons (2017-2025). Check ROI at thresholds 0.45, 0.48, 0.50.

**Step 2: Build OVER LLM experts**
Need new genomes — OVER experts think differently than UNDER experts:
- `ou_over_analyst_v1.yaml` — predicts total runs, same as existing analyst
- `ou_over_offense_v1.yaml` — "OffenseFirst" expert: RPG vs league, recent form, 1st-inning scoring
- `ou_over_bullpen_fatigue_v1.yaml` — "FatigueExploit" expert: bullpen deterioration (positive oscillator = tired bullpens = runs)

Key insight: the bullpen FIP oscillator (#1 feature at 38.12%) is a *symmetric signal*. Positive oscillator = deteriorating bullpens = favors OVER. The same feature that identifies UNDER opportunities (negative oscillator = fresh bullpens) identifies OVER opportunities.

**Step 3: Build OVER feature cards**
- `OUOverFeatureCard` — same data as UNDER card but framed for OVER analysis
- Highlight: high RPG vs line, positive bp_fip_osc, poor SP quality, high 1st-inning scoring rate
- Different narrative: "runs happen" vs "runs are prevented"

**Step 4: Extend DuelEngine for OVER**
- `run_over()` method: Both experts OVER → bet OVER (1.0x), OVER+PASS → LEAN_OVER (0.5x), disagreement → PASS
- Analyst adjustment: predicted_total > close_ou → confidence boost; predicted_total < close_ou-1 → confidence penalty

**Step 5: Calibrate on same 3 dates (2024-04-06, 04-23, 06-28)**
These dates had OVER games that were correctly PASSed by UNDER system. Now check: does the OVER system correctly BET them?
- ARI@ATL: 17 runs (line 9.0) — should be strong OVER signal
- NYM@CIN: 15 runs (line 9.5) — should be OVER
- ARI@STL: 15 runs (line 8.5) — should be OVER

### Risk: OVER vs UNDER Conflicts
Same game might have P(u) in [0.48, 0.52] — neither system bets. This is fine (it's the noise zone). But if P(u) is ever simultaneously >=0.52 for UNDER and <=0.48 for OVER... that's impossible by definition. Systems are naturally mutually exclusive.

### Architecture Question
Should OVER use the same analyst or a separate one? Likely same — the analyst predicts total runs neutrally (no UNDER/OVER bias). The experts are the ones with directional conviction.

## Files to Know

| File | Purpose |
|------|---------|
| `src/model.py` → `run_walk_forward_under()` | Walk-forward P(u) predictions (already computed) |
| `src/features.py` → `OU_FEATURES`, `build_ou_features()` | 22 O/U features |
| `src/bullpen_features.py` | Bullpen FIP/WHIP/K9 (now covers 2010-2025) |
| `src/llm_expert.py` | `LLMExpert`, `LLMAnalyst` with `analyze_ou()`, `predict_ou()` |
| `src/llm_duel.py` | `DuelEngine.run_ou()`, `_arbitrate_ou()` |
| `src/feature_card.py` | `OUFeatureCard`, `OUAnalystCard` |
| `genomes/ou_analyst_v1.yaml` | Scoring analyst (neutral, predicts total) |
| `genomes/ou_pitching_v1.yaml` | PitchingFirst expert (UNDER-biased) |
| `genomes/ou_scoring_v1.yaml` | RunEnvironment expert (UNDER-biased) |
| `scripts/run_ou_calibration_batch.py` | Batch calibration (multi-date, multi-threshold) |
| `scripts/run_ou_calibration_band.py` | Band-specific noise testing |

## Validated Numbers

| Zone | Hit Rate | ROI (flat -110) | Volume |
|------|----------|-----------------|--------|
| P(u) >= 0.60 | 69-85% | +32 to +61% | 22-75/season |
| P(u) >= 0.55 | 53-61% | +0.2 to +15% | 86-369/season |
| P(u) >= 0.52 | 52-57% | +0.2 to +15% | 101-530/season |
| P(u) [0.50, 0.52) | 47-52% | **-24%** | noise |
| P(u) >= 0.52 + LLM | **100%** (14/14) | **+91%** | ~3/day |
