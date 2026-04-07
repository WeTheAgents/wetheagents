# Session 26 Report: Away +1.5 Run Line — Bullpen Day Discovery

## Goal

Find profitable Away +1.5 RL strategy. Tested LLM pipeline (3 versions), then rule-based filters. Discovered structural edge in bullpen days.

---

## LLM Pipeline (Failed — 3 iterations)

### v1: Dual expert + edge_consensus (gpt-4o-mini)
- Architecture: edge>0.05 filter, AnalystCard, 2 experts (RL_TightGame + RL_AwayValue), arbitration
- Result: **-15.4% ROI** on 100 stratified games
- Root cause: experts parroted analyst (90% agreement), analyst biased by edge_consensus on card (81% predicted away wins), LEAN action catastrophic (-43.9% ROI)

### v2: Solo expert + margin gate (gpt-5.4)
- Architecture: neutral Analyst (predict_simple), solo expert (RL_AwayTightGame), no edge on card, analyst margin gate
- Result: **-1.2% ROI** on 200 natural-distribution games (2024)
- Root cause: expert framed as "tight game finder" but 72% of covers = dog wins outright. BET cover 67.5% < PASS cover 72.1% — expert anti-selects

### v3: Strong underdog framing (gpt-5.4)
- Architecture: same as v2 but expert reframed to "find strong underdogs", signed margin gate (dog wins = auto-BET), new feature card with DOG STRENGTH section
- Result: **-1.2% ROI** on 200 games (2024+2025)
- Root cause: pipeline collapsed to `analyst_winner==away -> BET (100%)`, `analyst_winner==home -> PASS (85%)`. Expert adds zero independent judgment

### LLM Conclusion

LLM cannot discriminate RL Away +1.5 covers. The signal (bullpen state, game variance, single-inning blowups) is not in the feature card — it's in lineup decisions announced hours before game time.

---

## Rule-Based Filter Scan

### Architecture

Mirrored `rl_fav_analysis.py` from Session 25: single filters -> 2-way combos -> 3-way combos -> train/test validation.

Universe: edge_consensus > 0.05, fav_is_home=True, 2014+ only (modern game).
4875 games total, 3675 in 2014+, baseline 62.4% cover, avg odds 1.566, **-2.5% ROI**.

### Key Finding: Bullpen Days

The `home_is_bullpen_no_starter` flag (home team uses opener/bullpen day instead of traditional starter) is the strongest single predictor:

```
home=BP, away=starter: 264 games, 83.7% cover, +31.2% ROI, 11/11 seasons
home=starter, away=BP: 351 games, 31.3% cover, -50.8% ROI, 0/11 seasons
both starters:         2999 games, 63.9% cover, -1.2% ROI
```

**Logic**: When the home favorite runs a bullpen day (rest day, injury, tanking rotation spot), the away underdog with a real starter has a massive structural advantage. The home bullpen is exposed from inning 1, with no ace anchoring the game.

### SBR Odds Parser Fix

During calibration, discovered that `awaySpread` in SBR JSON can be -1.5 (away is favorite) or +1.5 (away is underdog). Original parser didn't filter — captured both directions, producing bimodal odds distribution with impossible 2.5+ values for Away +1.5. Fixed to `awaySpread == 1.5` only.

Real Away +1.5 odds (2024 DraftKings): **median 1.625, mean 1.689** (not 1.87 as previously assumed).

---

## Production Strategy: Bullpen Day Dog

### Two products from one signal

| Product | Bet Type | Games/Season | Win/Cover % | Avg Odds | ROI |
|---------|----------|-------------|-------------|----------|-----|
| **Dog ML** | Moneyline (dog wins outright) | ~24 | 74.2% | 2.208 | **+63.9%** |
| **RL +1.5** | Run line (dog covers +1.5) | ~24 | 83.7% | 1.563 | **+31.2%** |

### Per-Season Breakdown (Dog ML)

| Season | Games | Win% | ROI |
|--------|-------|------|-----|
| 2014 | 14 | 78.6% | +73% |
| 2015 | 39 | 71.8% | +59% |
| 2016 | 14 | 78.6% | +75% |
| 2017 | 18 | 72.2% | +60% |
| 2018 | 26 | 69.2% | +54% |
| 2019 | 29 | 79.3% | +77% |
| 2021 | 43 | 74.4% | +65% |
| 2022 | 16 | 93.8% | +107% |
| 2023 | 10 | 60.0% | +33% |
| **2024** | **29** | **72.4%** | **+60%** |
| **2025** | **26** | **65.4%** | **+45%** |

**11/11 seasons profitable.** Worst season: 2023 (+33% ROI on 10 games).

### Post-COVID Validation (2024-2025)

```
2024: 29 games, Dog ML 72.4% win, +60.3% ROI | RL 75.9% cover, +16.2% ROI
2025: 26 games, Dog ML 65.4% win, +45.3% ROI | RL 84.6% cover, +31.2% ROI
```

Odds are real (away_decimal_odds from closing lines) — no fallback needed for ML bets.

### Filters (deterministic, free)

```python
UNIVERSE:   edge_consensus > 0.05 AND fav_is_home == True
FILTER 1:   away_is_bullpen_no_starter == False  (dog has a real starter)
FILTER 2:   home_is_bullpen_no_starter == True   (home running bullpen day)
BET:        Away team moneyline (primary) + Away +1.5 run line (secondary)
```

### Additional Tier 2 Signal

For non-bullpen-day games, bullpen fatigue still matters:

```python
# Tier 2: home BP exhausted, away BP rested (both have starters)
FILTER:  NOT away_bullpen_game AND NOT home_bullpen_game
         AND bp_workload_gap >= 3  (home BP 3+ more IP in last 3 days)
         AND bp_ip_3d_away <= 7    (away BP rested)
```

Tier 2 adds ~35 games/season at ~69% cover (+8% ROI on RL).

### Combined Strategy

```
Tier 1 (bullpen day):     ~24 games/season, 83.7% RL cover, +31.2% ROI
Tier 2 (fatigue gap):     ~35 games/season, ~69% RL cover, +8% ROI
Combined:                 ~59 games/season, ~75% RL cover, +18% ROI
```

---

## Caveats

1. **Volume**: ~24 bullpen-day games/season is thin. Combined with Tier 2 = ~59/season.
2. **Detection**: Bullpen days are announced in lineup cards, typically 1-3 hours before first pitch. Must monitor daily lineups.
3. **Market adjustment**: If books detect the pattern, lines will move. Currently, dog ML odds average 2.20 (implied 45%) despite 74% actual win rate — market hasn't priced this in.
4. **Sample size caveat**: 264 total games across 11 seasons. Per-season N ranges from 10 (2023) to 43 (2021). Effect is consistent but small-N years could be noise.
5. **RL odds uncertainty**: Away +1.5 odds for bullpen-day games may differ from standard games. Fallback 1.60 used for most historical games. Real RL odds needed for precise ROI.

---

## Files Created/Modified

| File | Action | Purpose |
|---|---|---|
| `genomes/rl_away_v3.yaml` | CREATE | Strong underdog genome (v3, unused in production) |
| `genomes/rl_away_tightgame_v2.yaml` | CREATE | Tight-game genome (v2, deprecated) |
| `genomes/rl_away_value_v1.yaml` | CREATE | Counter-narrative genome (v1, deprecated) |
| `scripts/rl_away_filter_scan.py` | CREATE | Full filter scan (6 sections, mirrors rl_fav_analysis.py) |
| `scripts/_bp_scan.py` | CREATE | Bullpen-focused scan (2014+ only) |
| `scripts/run_rl_calibration.py` | MODIFY | v2/v3 calibration, SBR parser fix (awaySpread==1.5), signed margin gate |
| `src/feature_card.py` | MODIFY | RL_away_v2 zone, _rl_matchup_context, dog-win signals, road WP |
| `src/llm_expert.py` | MODIFY | v2/v3 expert prompts (strong underdog framing) |
| `src/llm_duel.py` | MODIFY | _extract_signed_margin, run_rl_away_v2 signed gate |
| `picks/rl_v3_calibration_gpt54.json` | CREATE | v3 calibration results (200 games, 2024+2025) |

---

## Key Lessons

1. **LLM cannot predict game variance.** Three iterations proved that GPT-4o-mini and GPT-5.4 cannot discriminate RL covers. The signal (bullpen composition, last-minute lineup decisions) isn't in historical stats — it's in daily operations.

2. **72% of RL covers = dog wins outright.** Framing the problem as "tight games" was fundamentally wrong. The correct frame: "find underdogs who can win."

3. **Bullpen days are structural mispricing.** When a team announces a bullpen day, the market adjusts the moneyline ~5-10%, but the actual win probability for the opponent with a real starter is ~74%. Market efficiency breaks down on non-standard pitching configurations.

4. **Rule-based beats LLM when the signal is binary.** "Is this a bullpen day?" is a yes/no question. No LLM reasoning needed. The filter is trivially computable from lineup data.

5. **SBR odds parsing matters.** A single missing filter (`awaySpread == 1.5`) produced bimodal odds with impossible 2.5+ values, inflating ROI by 2x. Always validate odds distributions.
