# Session 30 Handoff — UNDER LLM Gate Experiment

## What was done

### 1. UNDER validation (complete)
- Validated UNDER strategy on 2021-2025: P>=0.53 threshold, +10.6% ROI, 5/5 seasons profitable
- Fixed `build_ou_features()` bug: missing `enrich_innings_from_retrosheet()` call
- P>=0.55 ROI improved from +30.8% to +37.2% after fix
- Session report: `knowledge/session_report_30.md`

### 2. LLM Gate v1 (complete, FAILED)
- Script: `scripts/run_under_gate_experiment.py`
- 3 calls/game: Analyst + UNDER Expert (Gatekeeper) + Devil's Advocate
- Model: gpt-5.4-mini, 719/720 games in zone [0.52-0.53)
- Checkpoint: `picks/_under_gate_experiment.json`
- **Result: Expert is inverted** — Expert=UNDER 45.9% (worse than base 46.4%)
- **DA=UNDER is the only signal above breakeven**: 58 games, 53.4%
- Root cause: UNDER-bias in prompt + O/U line in card = anchoring

### 3. LLM Gate v2 (IN PROGRESS — card rebuilt, needs re-run)
- Script: `scripts/run_under_gate_experiment_v2.py`
- 1 call/game: neutral Scorer (no UNDER/OVER bias)
- Model: gpt-5.4 (full, not mini)
- Genome: `genomes/ou_scorer_v1.yaml`
- **First run with line in card** → scorer anchored on line (mean gap = 0.12, useless)
- Results saved: `picks/_under_gate_experiment_v2_with_line.json`

### Card rebuild (DONE, not yet tested)
- New method: `OUFeatureCard.from_row_blind()` in `src/feature_card.py`
- **O/U line removed** from all sections (was in 4+ places)
- **League averages** added to every metric for calibration
- **Added**: SP WHIP, SP 1st-inn RA rate, Savant BP xwOBA (season + 3-day), 
  Pyth W%, batting vs pitcher hand (OBP + K% vs RHP/LHP)
- **Removed**: hold_rate duplicate, "RPG vs line" comparisons
- Sample card: `picks/_sample_card.txt` (1813 chars)

### Genome update (DONE)
- Removed "The line is information" principle from `ou_scorer_v1.yaml`
- Removed "Don't anchor on O/U line" anti-pattern (no line to anchor on now)
- Removed "MLB averages ~8.5-9.0" from output schema (use card lg avgs instead)

## What to do next

### Immediate: Re-run v2 with blind card
```bash
cd D:/GitHub/wetheagents/domains/mlb_betting
python scripts/run_under_gate_experiment_v2.py --model gpt-5.4
```
- Old checkpoint already renamed to `_v2_with_line.json`, script will start fresh
- DA data auto-loaded from v1 checkpoint (`picks/_under_gate_experiment.json`)
- ~720 games × gpt-5.4 ≈ $5-7, ~30 min
- Watch for: predicted_total distribution (should NOT cluster near 8.5-9.0)
- Watch for: probable_delta variance (v1 was stuck at 1.8)

### After results
1. Run `--report-only` to see strategy grid
2. Key strategies to watch:
   - Simple gap: scorer predicted < actual_line (we have line in data, just not in card)
   - Gap + delta: gap >= X, delta <= Y
   - **Scorer + DA combo**: gap >= 0.5 AND DA=UNDER (from v1)
3. If any strategy beats 52.38% breakeven on 50+ games → promising
4. If still no edge → zone [0.52-0.53) is dead, focus on P>=0.53 auto-bet

### If edge found
1. Re-run winning config on zone [0.51-0.52) (~1300 games)
2. Wire into production: `src/strategies/` + `scripts/generate_picks_2026.py`
3. Update CLAUDE.md Production-Ready Strategies

## Key files

| File | Purpose |
|------|---------|
| `scripts/run_under_gate_experiment_v2.py` | v2 experiment (blind scorer) |
| `scripts/run_under_gate_experiment.py` | v1 experiment (has DA data) |
| `picks/_under_gate_experiment.json` | v1 results (DA data source) |
| `picks/_under_gate_experiment_v2_with_line.json` | v2 first run (anchored, discard) |
| `genomes/ou_scorer_v1.yaml` | Neutral scorer genome |
| `src/feature_card.py` → `from_row_blind()` | Blind card builder |
| `src/llm_expert.py` → `analyze_ou_scoring()` | Scorer LLM method |
| `knowledge/session_report_30.md` | Full session report |

## Key insight
LLMs anchor on any number they see. The O/U line was in the card 4+ times.
The scorer predicted total = line ± 0.3 (useless). Remove the line entirely,
give league averages for calibration, and let the LLM build its own estimate
from matchup data. This is the hypothesis being tested in the re-run.

## Session 31 A/B — league-avg banner test (2026-04-15)

Two runs on same 20 games in zone [0.52-0.53), model=gpt-5.4:
- **Run A** (no banner): `picks/_under_gate_experiment_v2_runA_nobanner.json`
- **Run B** (banner "avg total ~8.87"): `picks/_under_gate_experiment_v2_runB_banner.json`
- Banner gated by env `OU_BLIND_LG_BANNER=1` in `src/feature_card.py:from_row_blind`

Results:
| metric | Run A | Run B | Δ |
|---|---|---|---|
| mean predicted_total | 8.49 | 8.83 | **+0.34 toward 8.87** |
| median | 8.40 | 8.75 | +0.35 |
| stdev | 0.94 | 1.07 | wider (not narrower!) |
| mean gap (line − pred) | +0.59 | +0.24 | collapsed −0.35 |
| reasoning mentions "league" | 7/20 | **17/20** | 2.4× |
| games shifted UP | — | **17/20** | (2 flat, 1 down) |

**Verdict: banner anchors the LLM.** Explicit "league avg = 8.87" pulls predictions toward 8.87
(not narrower distribution — just center-shifted). Strategies that relied on `gap >= 0.5` lose
games because the gap itself shrinks by ~0.35.

**Conclusion: do NOT add a top-level league-avg-runs banner.** Per-metric `[lg avg X]` tags
inside sections are fine (they contextualise individual features), but a summary line with
the combined total is an anchor.

Next step: proceed with Run A design on full 720-game scope.

## Session 31 — Analysis framework for full run (IMPORTANT)

Profitability must NOT be judged only by expert's own UNDER/OVER verdict (we don't ask
for one — scorer returns `predicted_total` + `probable_delta` only). We have rich
second-order signals. Evaluate ALL of these:

### Primary deviation signals
1. **gap_to_line** = `ou_line - predicted_total`
   - strategy: bet UNDER when gap ≥ threshold (line is higher than our estimate)
   - grid already in report (`STRATEGY 1`)
2. **gap_to_lg_avg** = `LG_RPG_COMBINED (8.87) - predicted_total`
   - strategy: bet UNDER when scorer projects below league avg (pitcher-friendly env)
   - independent of line → tests whether LLM-detected low-scoring envs are real
3. **line_vs_lg_avg** = `ou_line - 8.87`
   - pure market signal (no LLM): does market bias matter in this zone?
   - serves as baseline — if (1) and (2) beat this, LLM adds value

### Composite signals
4. **conservative_ceiling** = `predicted_total + probable_delta` vs line
   - strategy: even LLM's upper bound is below line (already `STRATEGY 3`)
5. **agreement**: sign(gap_to_line) == sign(gap_to_lg_avg)
   - both LLM and market agree game should go under → stronger signal
6. **disagreement**: gap_to_line < 0 but gap_to_lg_avg > 0 (or vice versa)
   - line is above lg avg but LLM says above-avg scoring → don't bet

### Calibration checks
7. Correlation(predicted_total, total_runs): does LLM estimate track reality?
8. Calibration by bucket: slice by predicted_total bins → is predicted UNDER rate close to actual UNDER rate?
9. Residual std: std(total_runs - predicted_total) — LLM accuracy vs naive mean-8.87

### Combo with existing signals
10. **predicted_total + p_under**: does LLM add info on top of CatBoost model?
    - strategy: p_under in [0.52-0.53) AND gap_to_line ≥ 0.5
11. **predicted_total + DA verdict** (from v1 checkpoint):
    - DA=UNDER + gap_to_line ≥ 0.5 (already `STRATEGY 4`)
12. **probable_delta as confidence**: low delta = high confidence → bet only when delta ≤ threshold

### Per-season / per-bucket slices
13. Break down by season (2021-2025) — check for regime shift
14. By ou_line bucket (7.5, 8.0, 8.5, 9.0, 9.5, 10.0+) — market mispricing may concentrate
15. By month — weather/season-of-season effects

### How to evaluate
- Breakeven for UNDER @ 1.909 odds: **52.38%** hit rate
- Statistical significance: need ≥100 games for any single-signal claim (2σ at 52% vs 48% ≈ 100 bets)
- Cross-validation: split 2021-2023 (tune) / 2024-2025 (holdout)
- Report threshold: any strategy with N≥50, hit_rate>53%, ROI>+3% is promising

### Files already carry all needed data
`picks/_under_gate_experiment_v2.json` records per-game:
`scorer_total`, `scorer_delta`, `ou_line`, `p_under`, `total_runs`, `under_hit`, `season`.
DA verdict joined from v1 checkpoint at report time.
All 15 analyses above can be added to `generate_report()` post-hoc — no need to re-run LLM.

## Session 31 — Full run results (718 games, 2026-04-15)

Analysis script: `scripts/analyze_under_gate_v2.py` (all 15 signals, post-hoc).
Checkpoint: `picks/_under_gate_experiment_v2.json`. Cost: $5.76.

### Headline metrics
- Base under% in zone: **46.4%** (breakeven 52.38%)
- `predicted_total` mean = 8.55, `ou_line` mean = 9.03, `LG_AVG` = 8.87

### CALIBRATION IS BROKEN (signals 7-9)
- **Correlation(pred, actual) = +0.087** — essentially noise
- **MAE(pred) = 3.83, MAE(naive 8.87) = 3.78** — LLM is WORSE than constant
- Systematic bias: when LLM says 7.2, actual mean = 9.5; when LLM says 9.9, actual mean = 10.3.
  LLM compresses predictions toward 7.5-9.5 but reality is 9.4-10.6. Underpredicts ~1-2 runs.
- **Implication: the scorer's `predicted_total` carries no real information about the outcome.**
  Any apparent edge is noise riding on a broken signal.

### Best single-signal strategies (all with tiny N or regime-dependent)
| Strategy | N | Under% | ROI | Verdict |
|---|---|---|---|---|
| gap_to_line ≥ 2.0 | 32 | 56.2% | +7.4% | TRAIN=29/+11.9%, HOLDOUT N=3 — untestable |
| gap_to_line ≥ 2.5 | 10 | 60.0% | +14.5% | too small |
| ceil_gap ≥ 0.5 | 21 | 66.7% | +27.3% | TRAIN=19/+30%, HOLDOUT N=2 — untestable |
| DA=UNDER + gap≥0.5 | 48 | 54.2% | +3.4% | TRAIN 43/55.8%/+6.5%, HOLDOUT 5/40%/-24% |

### Second-order signals
- `gap_to_lg` ≥ 1.5: N=56, 53.6%, +2.3% (marginal)
- `line_vs_lg` (pure market, no LLM): **all buckets negative** — no market mispricing edge
- Agreement signals: no combo beats single signal
- `probable_delta` as confidence: **no monotonic pattern**, delta ≤ 1.5 actually has 16.7% hit (N=6)
- Sub-zone `p_under` [0.524-0.527): N=201, 50.2%, -4.1% — nothing

### Regime shift (CRITICAL)
| season | gap≥1 N | hit | ROI |
|---|---|---|---|
| 2021 | 63 | 54.0% | +3.0% |
| 2022 | 34 | 52.9% | +1.1% |
| 2023 | 57 | 42.1% | -19.6% |
| 2024 | 14 | 50.0% | -4.5% |
| 2025 | 5 | 0% | -100% |

TRAIN (2021-2023) → HOLDOUT (2024-2025) collapse confirms: any edge in 2021-2022 did not survive.

### Month pattern (interesting but small N)
- May, gap≥1.0: 18 games, 67% hit, +27% ROI
- August: -27% ROI (global) — avoid?
- October: 24 games, 42% hit, -20% — sample too small

### Conclusion
**Zone [0.52-0.53) is dead.** The LLM scorer does not predict total runs (correlation 0.087,
worse than naive mean). Strategies that looked profitable (gap≥2.0, ceil_gap≥0.5) are
either too small (N<35) or do not replicate on 2024-2025 holdout. DA=UNDER combo
also collapses on holdout. No promising signal survives scrutiny.

### Recommendations for next session
1. **Abandon this zone.** Go back to P≥0.53 auto-bet (validated +10.6% ROI).
2. If LLM gate is to survive, the scorer needs a fundamentally different approach —
   the current card + prompt produces noise. Options:
   - give LLM `p_under` explicitly and ask "why might this be wrong?"
   - fine-tune on historical `predicted_total` vs `total_runs` pairs
   - try a different model (not gpt-5.4) — but costly, unclear it helps calibration
3. Use the data we have: 718 games × 4 LLM features (total, delta, factors, reasoning)
   is a dataset. Train a meta-model on it? Likely won't help given corr=0.087, but
   easy to try.
