# Session 23 Handoff — Moneyline Coinflip Zone: LLM Expert Improvement

## Context

NRFI ML is dead (session 22). UNDER pipeline is mature (+30.6% ROI). The next frontier is **moneyline coinflip games** — where the market says "50/50" but structural features + LLM experts can find edge.

## What Exists Today

### Coinflip Zone Definition
- `src/data_loader.py:352`: `is_coinflip = odds_spread <= 0.04` (implied prob gap <= 4%)
- Volume: ~2-15% of games per season depending on market
- Home win rate in CF: ~52% (slight home advantage)
- CF games have odds near -110/-110 or -105/-115 — breakeven ~52.4%

### LLM Expert Architecture (fully operational)
- `src/llm_expert.py`: `LLMExpert` (betting) + `LLMAnalyst` (neutral prediction)
- `src/llm_duel.py`: `DuelEngine.run()` — Analyst → 2 Experts → Consensus
- `src/llm_evolution.py`: `EvolutionEngine` — weekly genome evolution from resolved picks
- `src/feature_card.py`: `FeatureCard`, `AnalystCard` — structured data for LLM input
- Provider: GPT-4o-mini via OpenAI Batch API

### CF-Specific Schema Already Exists
`llm_expert.py:121-139` (`_OUTPUT_SCHEMA_CF`):
```
action: "BET" | "PASS"
side: "home" | "away"
confidence: 0.0-1.0
```
Rules: "Most should be PASS. Only bet when one side has clear structural advantages."

### Current Genomes (3)
1. `genomes/momentum_v1.yaml` — trajectory-focused (streaks, pitcher momentum)
2. `genomes/value_v1.yaml` — structural mispricings (RPI, FIP, Pythagorean WP)
3. `genomes/analyst_v1.yaml` — neutral game predictor

### Existing Coinflip Analysis
`scripts/analyze_coinflip.py` — feature sweep + 2-way combos on CF games:
- Tests 13 diff features (rpi_diff, wp_diff, sp_wr_long_diff, elo_diff, etc.)
- Per-percentile thresholds (p25, p50, p75)
- Home and away perspective
- Monthly deep dives (2024-06, 2024-08, 2025-04)

### Expansion Zones (from `run_llm_picks.py`)
Currently LLM experts operate on S3 (away underdog) and RL (run line) zones:
- S3: `edge_consensus < -0.02`, `rpi_diff <= 0.02`, `elo_diff <= 40`
- RL: `edge_consensus > 0.05`
- CF zone (`CF_pickem`): referenced in code but **not wired into daily pick flow**

## The Opportunity

Coinflip games are the largest unexploited zone:
1. **Volume**: 2-15% of games = 50-350 per season. High bet volume = better bankroll compounding.
2. **Market inefficiency**: When the market says "50/50", even a 53-54% hit rate is profitable at near-even odds (~1.90-1.95 decimal).
3. **LLM experts' strength**: CF games have subtle edges (pitcher matchup, recent form, team quality gaps) that are hard to price but easy for LLMs to narrate. The experts already have the CF schema and feature cards.
4. **No model retraining needed**: The regression walk-forward already produces `edge_consensus`. CF games are where `edge_consensus ≈ 0` but features disagree with the line.

## Research Plan

### Phase 1: Quantify the Baseline (rule-based)

Run `scripts/analyze_coinflip.py` across all seasons. Capture:
- Global CF rate and home win rate
- Best single-feature filters (which features predict CF winners?)
- Best 2-way combos
- ROI curves at different feature thresholds
- Per-season stability of the best filters

Key question: **Is there a rule-based CF edge at all?** If blind-home already gives +2-3% ROI, LLM experts just need to not destroy that edge. If blind-home is negative, experts need to find 3-4% alpha.

### Phase 2: CF Feature Card Design

Current `FeatureCard` is built for underdog analysis ("should we bet the dog?"). CF needs a **symmetric card** — both teams presented equally, no dog/fav framing.

Design a `CoinflipFeatureCard`:
- Both teams' stats side by side (not "dog vs fav")
- Pitcher matchup comparison (SP RA, FIP, WHIP, K/BB, 1st-inning)
- Recent form (last 10 WP, streak, RPG trend)
- Structural quality (RPI, Elo, Pythagorean WP)
- Bullpen state (FIP oscillator, recent workload)
- **No odds or edge info** in the card — force the expert to evaluate on fundamentals
- Separate `close_ou` for context (high/low scoring environment)

### Phase 3: CF Genome Pair

Two new CF-specific genomes that think differently:

**`genomes/cf_structure_v1.yaml`** — Structural edge finder:
- Philosophy: "In coinflip games, the market has priced narrative correctly but structure wrong. Look for RPI/Elo/Pythagorean disagreements."
- Principles: RPI diff is primary anchor. Pythagorean WP divergence from actual WP = regression signal. Starting pitcher FIP matters more than ERA in pick'em.

**`genomes/cf_momentum_v1.yaml`** — Form/trajectory reader:
- Philosophy: "Pick'em games are won by the team that's rising. Look for convergent signals: winning streak + improving pitcher + offensive hot streak."
- Principles: Last-10 WP matters more than season WP. Pitcher momentum (short vs long RA) reveals trajectory. Team on 4+ win streak in CF = systematic mispricing.

### Phase 4: CF Duel Engine Extension

Extend `DuelEngine` with `run_cf()` method:
- Analyst predicts winner + confidence (reuse existing analyst)
- Both CF experts analyze the `CoinflipFeatureCard`
- Consensus logic (adapted from ML duel):
  - Both BET same side → STRONG_BET (bet that side, 1.0x stake)
  - Both BET different sides → PASS (conflicting signals)
  - One BET + one PASS → LEAN (0.5x stake) only if BET confidence >= 0.65
  - Both PASS → PASS
- Analyst acts as tiebreaker: if one expert + analyst agree on side → upgrade to LEAN

### Phase 5: Walk-Forward CF Calibration

Unlike UNDER (where we have P(under) from ML), CF relies purely on LLM experts. Calibration approach:

1. Select 50 representative CF games across 5 seasons (10 per season)
   - Mix: 25 home wins, 25 away wins
   - Feature diversity: some with strong RPI signal, some with pitcher edge, some truly random
2. Run the CF duel engine on all 50
3. Score:
   - STRONG_BET accuracy (need >55%)
   - LEAN accuracy (need >52.5%)
   - PASS rate (target: 40-60% of games)
   - ROI at CF odds (~1.90-1.95)
4. If STRONG_BET < 55% → genome evolution or kill CF ML
5. If STRONG_BET > 58% → production-ready

### Phase 6: Wire CF into Daily Pick Flow

If Phase 5 passes, add CF zone to `run_llm_picks.py`:
```python
# In get_expansion_zone():
cf_mask = df["is_coinflip"] & ~df["involves_col"]
cf_games = df[cf_mask].copy()
cf_games["zone"] = "CF_pickem"
expansion = pd.concat([s3_exp, rl_exp, cf_games], ignore_index=True)
```

### Phase 7: Genome Evolution for CF

Weekly evolution cycle (reuse existing `EvolutionEngine`):
- High-confidence losses (>0.65) → anti-pattern extraction
- High-confidence wins (>0.70) → example promotion
- Monthly crossbreed between cf_structure and cf_momentum
- Track: STRONG_BET accuracy, LEAN accuracy, pass rate, ROI

## Key Hypotheses to Test

| # | Hypothesis | Test | Pass Criteria |
|---|-----------|------|---------------|
| H1 | CF games have exploitable feature signal | Rule-based sweep (Phase 1) | Any 2-way combo >54% win rate, >20 bets/season |
| H2 | LLM experts add alpha over rules | Compare LLM picks vs best rule on same games | LLM ROI > rule ROI |
| H3 | Symmetric card > dog-framed card | A/B test same games with both card formats | Symmetric card higher accuracy |
| H4 | CF genomes outperform generic genomes | Test cf_structure+cf_momentum vs momentum+value on CF games | Specialized > generic |
| H5 | STRONG_BET has genuine edge | Walk-forward calibration (Phase 5) | >55% accuracy across 50 games |

## Critical Files

| File | Role |
|------|------|
| `src/data_loader.py:350-352` | `is_coinflip` definition |
| `src/llm_expert.py:121-139` | `_OUTPUT_SCHEMA_CF` (already exists) |
| `src/llm_duel.py:93-156` | `DuelEngine.run()` (extend for CF) |
| `src/feature_card.py` | Add `CoinflipFeatureCard` |
| `scripts/analyze_coinflip.py` | Rule-based baseline (run first) |
| `scripts/run_llm_picks.py:109-140` | `get_expansion_zone()` (wire CF in) |
| `genomes/` | Add cf_structure_v1.yaml, cf_momentum_v1.yaml |

## Features Available for CF Analysis

Diff features (home - away, all in `build_all_features()`):
- `rpi_diff` — strength-of-schedule adjusted record
- `wp_diff`, `wp_last10_diff` — win percentages
- `pyth_wp_diff` — Pythagorean (expected) win%
- `elo_diff` — Elo rating gap
- `streak_diff` — winning streak gap
- `rpg_diff` — runs per game (offense)
- `sp_wr_long_diff` — starter win rate
- `sp_ra_long_diff` — starter runs allowed
- `sp_fi_momentum_diff` — 1st-inning pitcher trend
- `starter_fip_diff`, `starter_whip_diff` — advanced pitcher quality
- `bullpen_fip_diff` — bullpen quality gap

## Expected Timeline

| Phase | Effort | Dependency |
|-------|--------|------------|
| 1. Baseline | 20 min | None — just run existing script |
| 2. Card design | 30 min | Phase 1 results (what features matter) |
| 3. Genomes | 15 min | Phase 2 (card structure informs principles) |
| 4. Duel extension | 30 min | Phase 2-3 |
| 5. Calibration | 40 min | Phase 4 (needs OpenAI API calls) |
| 6. Wire in | 10 min | Phase 5 pass |
| 7. Evolution | 10 min | Phase 6 |

## Risk Factors

1. **CF games may be truly efficient** — the market prices pick'em well. If Phase 1 shows no feature signal at all, skip to Phase 7 (genome evolution on S3/RL instead).
2. **LLM cost** — 50-game calibration = ~100 API calls (analyst + 2 experts per game). At GPT-4o-mini prices, <$1.
3. **Low bet volume per day** — maybe 0-3 CF games pass expert filter. ROI compounding is slow. But combined with UNDER (3-5/day) and S3/RL (1-2/day), total portfolio reaches 6-10 bets/day.
4. **Home bias** — experts may default to "bet home in CF" which is a known ~52% strategy. Genomes must penalize blind-home bias explicitly.
