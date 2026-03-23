# Session 16 Status Report — OVER System + Feature Card Overhaul

Date: 2026-03-23

## What Was Done

### 1. OVER Pipeline Built (symmetric to UNDER)
- `run_over()` + `_arbitrate_over()` in `DuelEngine` (mirrored UNDER, direction flipped)
- `analyze_over()` + `_build_system_prompt_over()` in `LLMExpert`
- 2 OVER expert genomes: `OffenseFirst` (offensive momentum), `FatigueExploit` (bullpen fatigue)
- `OUFeatureCard.from_row_over()` and `OUAnalystCard.from_row_over()`
- `run_over_calibration_batch.py` batch script

### 2. Season Isolation Fix
- Discovered rolling features (RPG, RAPG, pitcher stats) leaked across seasons
- Fixed `features.py`, `bullpen_features.py`, `pitcher_features.py`: all rolling resets at season boundary
- Verified: April games start with NaN/default, no prior-season carryover
- Both UNDER and OVER pipelines validated post-fix

### 3. Feature Card Overhaul (3 iterations)

**Iteration 1 — OVER Signal Summary (failed):**
Added `_over_signal_summary()` with 5 aggregated OVER indicators to analyst card.
Biased analyst toward OVER — predicted 10+ totals on games that went UNDER.
Experts rubber-stamped inflated analyst totals, no filtering value.

**Iteration 2 — Neutral restructuring:**
Removed directional summary. Distributed data into neutral sections.
Updated analyst prompt: predict SCENARIO first, total = mathematical consequence.
OVER improved from 3W-6L to 3W-0L at P(o)>=0.55. UNDER stable.

**Iteration 3 — League context enrichment (final):**
- K/BB thresholds recalibrated: 1.6 = "poor command" (was "average"). Avg=2.5, elite=3.5+
- OBP vs hand: data-driven p25/p75 (.326/.352)
- Bullpen oscillator: `+ = deteriorating, - = improving` explained inline
- BP workload: lg avg ~9.5 IP/3d documented
- Hold rate: changed to "after 5 innings" (lg avg 0.82, was 0.86 full-game). Moved to Bullpen section
- Power rate: new metric, share of scoring innings with 2+ runs (lg avg 0.465)
- Fatigue composite: oscillator + workload combined in Bullpen section
- All labels: `[lg avg X.XX]` context appended

### 4. Final Calibration Results (5 dates)

**UNDER** (3 dates: 2024-04-06, 2024-04-23, 2024-06-28):
| Threshold | Bets | Record | P&L | ROI |
|-----------|------|--------|-----|-----|
| P(u)>=0.55 | 3 | 3W-0L | +$227 | +75.8% |
| P(u)>=0.52 | 11 | 10W-1L | +$809 | +73.5% |

**OVER** (5 dates: + 2025-04-04, 2025-06-14):
| Threshold | Bets | Record | P&L | ROI |
|-----------|------|--------|-----|-----|
| P(o)>=0.55 | 3 | 3W-0L | +$273 | +90.9% |
| P(o)>=0.52 | 7 | 4W-3L | +$64 | +9.1% |

### 5. Key Findings

**OVER selectivity:**
- P(o)>=0.55: extremely selective (3/13 bet, 100% accuracy)
- P(o)>=0.52: conservative (7/27 bet, 57% accuracy)
- 2025-06-14: 0 bets from 9 eligible — correctly filtered poor setups
- Missed: MIA@ATL (10), CLE@LAA (14), SEA@SFO (19) at 0.52 threshold

**CWS@MIN deep-dive** (2024-04-23, actual=11):
- Analyst had no offensive context data → predicted 6.5 total → both experts said UNDER
- After signal summary: caught CWS@MIN but biased all other games
- After neutral restructured card: properly caught via offensive + bullpen data

## Files Modified
- `src/feature_card.py` — OUAnalystCard, OUFeatureCard, 15+ label functions, new sections
- `src/llm_expert.py` — `analyze_over()`, `_build_system_prompt_over()`, analyst scenario prompt
- `src/llm_duel.py` — `run_over()`, `_arbitrate_over()`
- `src/features.py` — season isolation
- `src/bullpen_features.py` — season isolation, hold_rate_after_5, power_rate
- `src/pitcher_features.py` — season isolation
- `genomes/ou_over_offense_v1.yaml` — OffenseFirst genome
- `genomes/ou_over_fatigue_v1.yaml` — FatigueExploit genome
- `scripts/run_over_calibration_batch.py` — batch OVER calibration script
