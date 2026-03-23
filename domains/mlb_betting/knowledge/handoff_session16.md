# Session 16 Handoff — Strategy Combinations & OVER Genome Tuning

## What's Done

### UNDER System (production-ready)
- 2-stage: CatBoost+LR walk-forward ensemble → LLM expert duel (PitchingFirst + ScoringContext)
- P(u)>=0.52 threshold: 10W-1L, +73.5% ROI across 3 test dates
- Season-isolated features, enriched neutral analyst card with league context

### OVER System (alpha — needs genome work)
- Same 2-stage architecture, P(over) = 1 - P(under)
- P(o)>=0.55: 3W-0L +90.9% — but only 3 bets from 13 eligible
- P(o)>=0.52: 4W-3L +9.1% — experts too conservative, miss profitable games
- Expert genomes (OffenseFirst, FatigueExploit) need tuning for recall

### Feature Card (v3 — shared by both systems)
Neutral analyst card with 7 sections, league averages, qualitative labels.
Analyst prompt: "describe probable match scenario, total follows from scenario."
New metrics: hold_rate_after_5, power_rate, fatigue composite.

## Next Session: Strategy Combinations

### 1. Combined UNDER + OVER Daily Run
Both systems share the same data pipeline. Natural extension:
- Load data once, compute P(under) for all games
- Split: P(u)>=0.52 → UNDER pipeline, P(o)>=0.52 → OVER pipeline
- Non-overlapping by definition (same game can't be in both)
- Combined daily output: list of UNDER bets + OVER bets

**Key question**: should they share the analyst call? Currently yes (`from_row` = `from_row_over`).
The analyst is neutral — same scenario feeds both expert teams. This is correct.

### 2. OVER Genome Tuning
Current problem: experts pass on too many games. At P(o)>=0.52, only 26% bet rate (7/27).
Missed profitable games: MIA@ATL (10 runs), CLE@LAA (14 runs), SEA@SFO (19 runs).

Root cause analysis from game dumps:
- Analyst predicts neutral/low total → experts inherit pessimism
- Both experts default to UNDER when card lacks strong OVER signal
- Anti-patterns ("don't override elite pitching") are too aggressive — filter good bets

Possible approaches:
1. **Soften anti-patterns** — remove "one elite starter suppresses everything"
2. **Add OVER-specific principles** — e.g., "when combined RPG exceeds line by 1+, default to OVER not PASS"
3. **Recalibrate confidence modifiers** — boost for high-conviction setups
4. **Test 3rd genome** — maybe a "Contrarian" that exploits low-total analyst predictions

### 3. Expanded Test Set
Current: 5 dates (3 original + 2 new). Need 10-15 dates for significance.
Selection criteria: mix of seasons (2022-2025), months (Apr-Sep), diverse slate sizes.
Run both systems simultaneously on expanded set for proper statistical test.

### 4. Noise Band Analysis for OVER
Did this for UNDER in Session 15: P(u) in [0.50, 0.52) was unprofitable (noise).
Need same test for OVER: P(o) in [0.50, 0.52) — do experts have any edge there?
Probably not (UNDER experts couldn't), but verify.

## Files to Know

| File | Purpose |
|------|---------|
| `scripts/run_over_calibration_batch.py` | OVER batch calibration (5 dates) |
| `scripts/run_ou_calibration_batch.py` | UNDER batch calibration (3 dates) |
| `src/feature_card.py` | All card builders (AnalystCard, FeatureCard, OUAnalystCard, OUFeatureCard) |
| `src/llm_expert.py` | LLMExpert (analyze, analyze_ou, analyze_over) + LLMAnalyst |
| `src/llm_duel.py` | DuelEngine (run, run_ou, run_over) + arbitration |
| `genomes/ou_over_offense_v1.yaml` | OffenseFirst genome |
| `genomes/ou_over_fatigue_v1.yaml` | FatigueExploit genome |
| `genomes/ou_analyst_v1.yaml` | Shared OU analyst genome |
| `knowledge/debug_card_stl_mil.md` | Example full card + expert responses |

## Validated Numbers

| System | Threshold | Dates | Bets | Record | ROI |
|--------|-----------|-------|------|--------|-----|
| UNDER | P(u)>=0.55 | 3 | 3 | 3W-0L | +75.8% |
| UNDER | P(u)>=0.52 | 3 | 11 | 10W-1L | +73.5% |
| OVER | P(o)>=0.55 | 5 | 3 | 3W-0L | +90.9% |
| OVER | P(o)>=0.52 | 5 | 7 | 4W-3L | +9.1% |
| Combined | 0.52 | 5* | 18 | 14W-4L | +48.5% |

*UNDER only on 3 of 5 dates; OVER on all 5.
