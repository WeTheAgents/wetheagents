# Handoff: Session 25 — Favorite -1.5 Run Line

## Context

Session 24: CF rebuild (kill Momentum genome, design Devil's Advocate).
Session 25: Pivot to **Favorite -1.5 Run Line** — first serious look with full feature stack.

## Why this direction

Session 11 marked "Favorite RL -1.5" as a dead end:
> "Cover rate 43%, breakeven ~50% at RL odds"

That verdict was premature — it was tested **without pitcher features and without walk-forward model edge**.
Today's away +1.5 analysis confirmed that real RL odds (avg 1.57) make the +1.5 direction nearly impossible to beat.
The -1.5 direction has completely different economics:

| Direction | Avg Odds | Breakeven | Baseline Cover | Gap |
|-----------|----------|-----------|----------------|-----|
| Away +1.5 (real odds) | 1.57 | **63.7%** | 60.2% | -3.5pp |
| **Fav -1.5** | **~2.40** | **41.7%** | **40.8%** | **-0.9pp** |

The favorite -1.5 is **4x closer to breakeven** than away +1.5. A single strong filter adding +2pp cover
rate (e.g. RPI diff + pitcher quality) would make it profitable.

Core hypothesis: when a favorite is structurally dominant (run-scoring offense, quality SP, weak opponent),
they win by 2+ at a rate exceeding the 41.7% breakeven at ~2.40 decimal odds.

## What's known from run_runline_with_pitcher.py

Part 2 of that script tested fav -1.5 with RPI + pitcher filters (vig-estimated odds, train 2010-2017):

| Filter | N | Cover% | ROI |
|--------|---|--------|-----|
| Baseline (all fav -1.5) | ~8,400 | 40.8% | -4.0% |
| RPI >= 0.03 + SP_WR >= 0.10 | ~900 | ? | ? (TRAIN only) |
| RPI >= 0.04 + SP_WR >= 0.10 | ~600 | ? | ? (TRAIN only) |

These results were printed but not saved. The script needs to be re-run or a dedicated analysis built.

## What makes fav -1.5 different from fav ML

Fav ML: team wins the game (margins irrelevant).
Fav -1.5: team wins by 2+ runs. This requires a different feature emphasis:

- **Offense volume** (RPG, runs_vs_league) — run-scoring environments
- **SP dominance** (FIP, RA, WHIP) — hold opponent to 0-1 runs through 6
- **Bullpen closing** (hold_rate, bp_fip) — don't blow a 2-run lead
- **NOT close-game WP** — teams that win close games (1-run) actively hurt fav -1.5 cover
- **Run line implied prob band** — very strong favorites (>70% implied) may have lower RL cover (regression)

## Analysis plan

### Step 1: Build `scripts/rl_fav_analysis.py`

Universe: all games where home OR away team is a -1.5 RL favorite (i.e., `home_run_line == -1.5` OR
`away_run_line == -1.5`). Use real odds where available, vig-estimate where not.

Cover condition: favorite wins by 2+ (`|margin| >= 2`).

Structure parallel to `rl_away_analysis.py`:
- Section 1: Baseline + edge bands + monthly splits
- Section 2: Single filters (see candidates below)
- Section 3: 2-way combos on top singles
- Section 4: Walk-forward model integration (build_spec_features)
- Section 5: Train/Test split (TRAIN 2010-2017, TEST 2018-2019/2021)

### Step 2: Feature candidates

**Primary (expect positive signal):**
```
rpi_diff >= 0.02 / 0.03 / 0.04 / 0.05   (fav stronger schedule-adjusted)
sp_wr_long_diff >= 0.10 / 0.15 / 0.20   (fav pitcher better W/R)
sp_ra_long_diff <= 0.0 / -0.5 / -1.0    (fav pitcher allows fewer runs)
starter_fip_diff <= -0.3 / -0.5         (fav pitcher better FIP)
offense_vs_league_fav >= 1.05           (fav offense above average)
rpg_fav >= league_avg + 0.3             (fav scoring more)
```

**Secondary (refine):**
```
bp_ip_3d_dog > median                   (dog bullpen tired = fav covers)
hold_rate_fav >= 0.75                   (fav closes out leads)
sp_ra_momentum_diff < 0                 (fav pitcher improving, dog worsening)
starter_whip_diff < -0.10               (fav pitcher less leaky)
close_game_wp_fav < 0.55               (fav wins BIG, not just close — inverse!)
```

**Edge direction (walk-forward model):**
```
edge_consensus < -0.05                  (fav underpriced on ML = might dominate)
edge_consensus < -0.10                  (stronger underpricing signal)
```

Note: inverted edge logic vs away +1.5. For fav -1.5, we want the favorite to be
UNDERpriced on ML (edge < 0) — the market thinks the fav is better than the line shows.

**Bands to avoid:**
```
implied_prob_fav > 0.72                 (extreme favorites — already priced, regression to mean)
is_colorado                             (coors field inflates scores both ways)
```

### Step 3: Implied probability sweet spot

Strong favorites (-200 to -250 on ML, implied ~67-71%) may have the best -1.5 cover rate:
- Too weak (-120 = 55% implied): not dominant enough to cover by 2
- Too strong (-350+ = 78%+ implied): already fully priced, line compensates

Test in bands: [0.55-0.60], [0.60-0.65], [0.65-0.70], [0.70-0.75], [0.75+]

### Step 4: Run environment interaction

High-run games → more variance → higher chance of 2+ run margins.
Test: `rpg_fav + rapg_dog >= 9.0` (combined expected run environment).

## Data notes

- `home_run_line == -1.5`: home team is favorite. Real `home_run_line_odds` available for 2014+.
- `home_run_line == 1.5`: away team is favorite. Fav RL odds must be vig-estimated.
- For unified fav -1.5 dataset: flip signs on all diffs when away is the favorite (same pattern
  as `run_runline_with_pitcher.py` lines 162-170).
- `run_runline_with_pitcher.py` already has this flip logic — reuse it.

## Key questions for Session 25

1. What's the actual cover rate by implied probability band? Is the sweet spot at 60-70%?
2. Does RPI + SP combo push cover rate above 42%? What's the minimum profitable filter?
3. Is the effect stronger in 1H or 2H? (Pitcher coverage is 0% in week 1, 70%+ by week 3)
4. Can walk-forward model edge direction (fav underpriced) add signal on top of rule-based filters?
5. Is fav -1.5 correlated with S3-dual or RL +1.5? Could become a third uncorrelated leg.

## Starting point code

`scripts/run_runline_with_pitcher.py` Part 2 has the basics — unified fav -1.5 dataset with flip logic.
Extend it with walk-forward model, Section 4 train/test split, and implied prob bands.

Alternatively: copy `rl_away_analysis.py` and invert the logic (cover = margin >= 2 instead of <= 1,
universe = fav instead of dog, edge direction = negative not positive).

## Context: what NOT to do

- Do NOT revisit away +1.5 with real odds — baseline -6.7%, only wp_last3 signal (+4.1%, 36 bets/season).
  Not enough edge, too few bets. Real odds are 1.57 avg = brutal vig.
- Do NOT test home +1.5 or home ML — confirmed dead end in session 11.
- Do NOT expect walk-forward edge alone to save the direction — rule-based filters must work first.

## If fav -1.5 fails

Next candidates in order of priority:
1. **Half-inning RL** (F5 or 7-inning lines) — only SP matters, bullpen noise eliminated
2. **wp_last3_away + edge > 0.15** combo (from today's run): 48 bets/season, +11.9% ROI on 7 seasons.
   Small sample, but worth a deeper multi-season validation.
3. **UNDER via fav dominance** — strong favorites in low-run environments → UNDER.
   Cross-strategy signal: same features, different market.
