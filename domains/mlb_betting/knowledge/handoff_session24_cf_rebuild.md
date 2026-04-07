# Handoff: Session 24 — CF Expert Rebuild

## What happened

Full CF calibration on 168 games (Jun/Aug/Sep 2024, GPT-5.4). Result: **KILL** — 40.5% accuracy, -22.1% ROI.

## The critical finding

| Configuration | Bets | Accuracy | Verdict |
|---|---|---|---|
| Both agree (current duel) | 74 | 40.5% | KILL — worse than random |
| Structure solo (PASSed by duel) | 27 | 55.6% | PROFITABLE — above breakeven |
| Momentum solo (PASSed by duel) | 15 | 33.3% | TOXIC — actively anti-predictive |

**Momentum is poisoning Structure.** When both agree, it selects the WORST subset of Structure's picks — ones where Momentum's flawed logic also fires.

## Root causes

### 1. Away bias (80% of bets on away)
Both experts systematically overvalue away teams. In CF zone the market already prices in team quality — "better" team ≠ "underpriced" team. Experts see higher RPI/WP away and bet that side, but the line already reflects it.

### 2. Confidence miscalibration
All 74 bets landed in High confidence (0.65+). Within that:
- 0.65-0.75: 10 bets, **20% acc** (worst)
- 0.75-0.85: 59 bets, **46% acc** (best, still losing)
- 0.85-1.00: 5 bets, **20% acc** (worst)

Extreme confidence = extreme error. Experts are most wrong when most sure.

### 3. Zero expert diversity
74 consensus bets, 0 disagreements on side. Structure and Momentum give identical picks when both bet. The genomes are too similar — both react to the same signals the same way.

### 4. Monthly pattern
- Jun: 33% (30 bets) — worst
- Aug: 38% (24 bets) — bad
- Sep: 55% (20 bets) — only profitable month

September has better feature coverage and playoff races create real mispricings. June/August have more noise.

## What to rebuild

### Option A: Kill Momentum, upgrade Structure (recommended)
- Structure solo is 55.6% — already profitable
- Replace Momentum with a **Devil's Advocate** genome: its job is to find reasons NOT to bet, not to find a different bet
- Duel becomes: Structure proposes → Advocate challenges → BET only if Structure survives scrutiny
- This filters OUT the bad bets instead of doubling down on them

### Option B: Fundamentally different second expert
- Keep Structure as anchor
- New expert: **CF-Contrarian** — specifically looks for cases where the "obvious" side is a trap
- Focus: regression-to-mean, schedule fatigue, travel, bullpen depletion
- Disagreement becomes signal, not noise

### Option C: Single expert + confidence threshold
- Drop duel entirely for CF zone
- Structure alone with confidence > 0.65 → BET
- Simple, but gives up the filtering value of a second opinion

## Files to change

| File | What |
|---|---|
| `genomes/cf_momentum_v1.yaml` | DELETE or replace with new genome |
| `genomes/cf_advocate_v1.yaml` | NEW — Devil's Advocate genome (if Option A) |
| `src/llm_expert.py` | Maybe: new `_OUTPUT_SCHEMA_CF_ADVOCATE` with CHALLENGE/CONCEDE actions |
| `src/llm_duel.py` | Rewrite `_arbitrate_cf()` for propose→challenge model |
| `src/feature_card.py` | No changes needed |

## Anti-patterns for new genomes

Based on failure analysis:
1. **"Better team = better bet" is WRONG in CF** — the line already prices team quality
2. **Away bias kills** — add explicit: "In pick'em, home team has 3-5% edge not in the stats. Default should be slight home lean, not away."
3. **High confidence on small diffs is miscalibrated** — RPI diff of 0.01 in CF ≠ 0.65 confidence. New genome needs: "In CF zone, confidence 0.60 = maximum without extreme confluence"
4. **Momentum signals are noise in CF** — last-10 WP, streaks etc. don't predict CF outcomes. Structure (RPI, Pythagorean, pitcher FIP) has real signal.

## Calibration infrastructure ready

```bash
# Same script, just change genomes and re-run
PYTHONIOENCODING=utf-8 python scripts/run_cf_calibration.py \
  --season 2024 --months 6,8,9 --model gpt-5.4 \
  --save picks/cf_calibration_v2.json
```

Results JSON from this session: `picks/cf_calibration_2024_jun_aug_sep.json`

## Key numbers to beat

- Breakeven: ~52.4% at avg odds 1.92
- Structure solo baseline: 55.6% on 27 bets (small sample but signal)
- Target: >53% on >40 bets (statistically meaningful)
- PASS rate target: 50-70% (CF is dangerous, not betting = profit)
