# Features & Approaches from Legacy System (D:\bblxls, 2016-2018)

> Source: 61 xlsx files from manual baseball betting analysis.
> Approach: Excel Solver to optimize thresholds for linear scoring formulas.
> Key insight: selectivity > prediction accuracy. We don't predict every game — we wait for outlier signals.

---

## System Architecture (2 independent systems)

### System 1: Moneyline / Series Bets (System3 V1-V4)
**Goal:** Predict game winner for ML bets and series dogon strategy.
**Files:** `System3*.xlsx`, `2017 series fight.xlsx`, `2018 series fight.xlsx`, `Runlines NEW V*.xlsx`

### System 2: Totals / 1st Inning (V6-V7, 1st BABIP/LESS/MORE)
**Goal:** Project run scoring for O/U and YRFI bets.
**Files:** `V6-2016*.xlsx`, `V7-2016*.xlsx`, `1st BABIP*.xlsx`, `1st LESS*.xlsx`, `1st MORE*.xlsx`, `3inn.xlsx`, `5innigs*.xlsx`, `7inn*.xlsx`

---

## Feature Categories

### A. Team Strength Metrics

#### A1. RPI (Rating Percentage Index) ★★★
**Formula:** `RPI = 0.25 × WP + 0.50 × OWP + 0.25 × OOWP`
- WP = team win percentage
- OWP = opponents' average win percentage (strength of schedule)
- OOWP = opponents' opponents' average win percentage

**Legacy usage:** End-of-season RPI from ESPN (static, 1 value per team).
**Our approach:** Rolling daily RPI calculated from game results. No look-ahead.

**Key Solver parameters from legacy:**
- `MinRPIoBet = 0.480` — don't bet on teams with RPI < 0.48
- `RPIdiffAway = 0.029-0.041` — min RPI advantage for away bet
- `PRIdiffHome = 0.011-0.014` — min RPI advantage for home bet (lower threshold — home advantage built in)

**Derived features:**
- `rpi_home`, `rpi_away` (raw)
- `rpi_diff = rpi_home - rpi_away` (synthetic)
- `rpi_min = min(rpi_home, rpi_away)` — quality floor filter
- `rpi_max` — quality ceiling

#### A2. Win-Loss Record ★★
**Legacy:** `MinWLAdvAway = 0.223`, `MinWLAdvHome = 0.024`
- W/L percentage overall
- W/L home/away splits
- Recent form (last 10, last 20 games)

**Derived features:**
- `wl_pct_home`, `wl_pct_away`
- `wl_pct_home_at_home`, `wl_pct_away_on_road` (home/away splits)
- `wl_diff = wl_pct_home - wl_pct_away`
- `wl_last10_home`, `wl_last10_away` (recent form)
- `wl_last10_diff`

#### A3. Streak / Momentum ★★
**Legacy:** `ShortWinsTrail = 7-14`, `LongWinsTrail = 10-22`
**Our streak analysis confirmed:** momentum exists (W3+ → 52.1%, L3+ → 46.8%, both significant)

**Derived features:**
- `streak_home`, `streak_away` (signed: +3 = W3, -3 = L3)
- `streak_diff`
- `streak_abs_max = max(|streak_home|, |streak_away|)`

---

### B. Pitching Metrics

#### B1. Starter Quality ★★★
**Legacy:** ERA, WHIP, K/BB, K/9 from season stats.

**Features (per starter):**
- `era_home_sp`, `era_away_sp` — earned run average
- `whip_home_sp`, `whip_away_sp` — walks + hits per inning
- `kbb_home_sp`, `kbb_away_sp` — strikeout to walk ratio
- `k9_home_sp`, `k9_away_sp` — strikeouts per 9 innings

**Composite (from V6/V7):**
- `whip_combined = (whip_home_sp + whip_away_sp) / 2` (CoWHIP in legacy)
- `kbb_combined` (CoKBB)
- `whip_diff = whip_away_sp - whip_home_sp` (positive = home advantage)

#### B2. First Inning Pitching ★★ (for YRFI)
**Legacy:** `Pit1st-16/17` sheets — ERA specifically for 1st inning.

**Features:**
- `era_1st_inn_home_sp`, `era_1st_inn_away_sp`
- `era_1st_inn_combined`

#### B3. Reliever / Bullpen Quality ★
**Legacy:** `7inn-15-16.xlsx` has `Relieve-15/16/17` sheets.

**Features:**
- `bullpen_era_home`, `bullpen_era_away`
- `bullpen_whip_home`, `bullpen_whip_away`

---

### C. Batting / Offense Metrics

#### C1. Overall Batting ★★
**Legacy V6/V7:** OBP, SLG, OPS, AVG, Runs per Game, Runs/Hits ratio.

**Features (per team):**
- `obp_home`, `obp_away` — on-base percentage
- `slg_home`, `slg_away` — slugging percentage
- `ops_home`, `ops_away` — OBP + SLG
- `avg_home`, `avg_away` — batting average
- `rpg_home`, `rpg_away` — runs per game

**Composites:**
- `obp_combined = (obp_home + obp_away) / 2` (CoOBP)
- `ops_combined` (CoOPS)
- `run_hit_ratio_combined` (CoRUN/HIT Ratio)
- `rpg_combined` (CoRunsPerGame)

#### C2. BABIP (Batting Average on Balls in Play) ★★
**Legacy:** Central metric in 1st inning analysis. Entire file series named after it.

**Features:**
- `babip_home`, `babip_away` — team BABIP
- `babip_vs_sp_home`, `babip_vs_sp_away` — team BABIP against opposing SP

#### C3. Batted Ball Profile ★
**Legacy:** `5innigs-15-16.xlsx` has Gb%, Fb%, Ld% (ground ball, fly ball, line drive).

**Features:**
- `gb_pct_home`, `gb_pct_away` — ground ball percentage
- `fb_pct_home`, `fb_pct_away` — fly ball percentage
- `ld_pct_home`, `ld_pct_away` — line drive percentage

---

### D. Park & Context Factors

#### D1. Park Factor ★★
**Legacy:** `FieldFactor` in V6/V7, `ParkFactorEff` in 1st inning files.

**Features:**
- `park_factor` — park run factor (Coors ~1.3, Petco ~0.85)
- `park_factor_hr` — park HR factor

#### D2. League Penalty ★
**Legacy:** `NLPenalty = 0.91158` — NL teams scored ~9% less (pitcher batting).
**Note:** DH rule unified in 2022. NL penalty NO LONGER APPLIES for 2022+ data.
For our 2010-2021 backtest, this is relevant.

**Feature:**
- `both_nl` — boolean, both teams in NL (for 2010-2021 data only)
- `league_penalty` — 0.91 if both NL, 1.0 otherwise

#### D3. Day of Week ★
**Legacy:** `DoW` column in System3. Weekend vs weekday patterns.

**Feature:**
- `day_of_week` — categorical (Mon-Sun)
- `is_weekend` — boolean

#### D4. Season Phase ★
**Legacy:** `GamesOffset = 20` — don't bet until 20 games into season.

**Feature:**
- `games_played_home`, `games_played_away` — how far into season
- `is_early_season` — < 20 games played
- `month` — April through October

---

### E. Head-to-Head & Series Context

#### E1. Series Position ★★★ (for Series Fight strategy)
**Legacy:** `# in ser` column, `Series#` — game number within the series.

**Features:**
- `game_in_series` — 1, 2, 3, or 4
- `series_score_home` — home team's wins in current series (0-0, 1-0, etc.)
- `series_score_away`
- `series_leader` — who's ahead in the series

#### E2. H2H Season Record ★
**Legacy:** tracked in System3 sheets.

**Features:**
- `h2h_home_wins`, `h2h_away_wins` — season H2H record
- `h2h_diff`

---

### F. Scoring Projections (Composites)

#### F1. ProjectedScore (from V7) ★★
**Formula (reconstructed):**
```
ProjectedScore = CoWHIP × WhipAffect
               × CoRunsPerGame × HiRunsPerGameAffect
               × FieldFactor × NLPenalty
```

**Solver-optimized weights (V7):**
- `WhipAffect = 28.025`
- `HiRunsPerGameAffect = 0.145`

**V6 had more factors:**
- `WhipAffect = 4.739`
- `OPSAffect = 2.828`
- `OBPAffect = 4.264`
- `RUNHITAffect = 2.372`
- `HiRunsPerGameAffect = 2.069`
- `KBBAffect = 4.010`

#### F2. RunMore / RunLess (1st Inning) ★★
**For YRFI/NRFI prediction:**
```
Score = PitchAffect × pitcher_metric
      + AttackAffect × batting_metric
      + HomeRunAffect × hr_metric
      + ParkFactorEff × park_factor
```

**Legacy WinStake values:** 0.77 (RunMore), 0.53 (RunLess) — edge was small.

---

## Key Design Principles from Legacy

### 1. Selectivity Over Volume ★★★
> "We analyze up to 15 nightly games but only bet on 1-3 with maximum signal divergence."

Trade-off: 1000 small bets vs 200 large bets. The system's edge IS selectivity.

### 2. Threshold-Based Filtering ★★
Legacy used hard thresholds (MinRPIoBet, MinWLAdvAway).
New approach: CatBoost learns optimal thresholds, but we still enforce minimum quality floor.

### 3. Don't Predict Winners — Find Value ★★★
We're not trying to beat 53% win rate on every game. We're finding the 5-10% of games where our scoring system shows maximum divergence from the line.

### 4. GamesOffset = 20 ★
Don't bet in first 20 games of season — insufficient sample size for team/pitcher stats.

### 5. NL Penalty (historical only) ★
NL teams scored ~9% less due to pitcher batting. Removed in 2022 (universal DH).

---

## Feature Priority for Implementation

### Tier 1 — Team Dynamics (proven in legacy + computed from our data) ✅ DONE
- Rolling RPI (daily, per team) — **implemented in features.py**
- W/L record + splits (overall, home/away, last 10/20) — **implemented**
- Streak (signed, entering game) — **implemented**
- Runs per game (team, rolling + last 10) — **implemented**
- Strength of schedule (OWP component from RPI) — **implemented**
- Home/away flag — built into data_loader

**Note**: Legacy system (2016-2018) used ONLY team-level metrics, no pitcher data.
The Solver still found edge through selectivity. Tier 1 is the foundation layer.

**Implementation**: `src/features.py` → `build_all_features()` → 35 features per game.

**Backtest status**: RPI is a strong predictor (64% WR at extremes), but team-level
features alone are NOT enough to overcome bookmaker vig on ML, RL, or series dogon.
Breakeven series WR = 81.7%, best achieved = 87.1% with very tight filters (365 series).

### Tier 1.5 — Momentum / Trail (from legacy, partially implemented)
- `ShortWinsTrail = 7-14` — short momentum window ⚠️ **only simple streak implemented**
- `LongWinsTrail = 10-22` — long momentum window ⚠️ **wp_last10/last20 are close but not exact**
- These are attempts to capture **team momentum** as a separate signal from raw WP
- TODO: implement variable-window trails (7/10/14/22) as separate features
- TODO: add **rolling run differential** (better proxy than separate RPG/RAPG)

### Tier 2 — Pitcher Layer (IMPLEMENTED as proxy, see pitcher_features.py)
**Source**: pybaseball game logs (IP, H, R, ER, BB, K, HR, pitches, GB%, FB%)

#### Core metrics: WHIP and K/BB (NOT ERA)
ERA is noisy and depends on defense/luck. WHIP and K/BB are more process-driven:
- **WHIP** = (Walks + Hits) / IP — measures how many baserunners pitcher allows
- **K/BB** = Strikeouts / Walks — measures pitcher's command and dominance

#### Oscillator approach (like trading indicators)
Each metric computed at TWO rolling windows — short and long:
- **Short window** (3-5 starts) = current form / momentum
- **Long window** (12-15 starts) = true level / baseline

The **cross** (short vs long) reveals trend:
- Short WHIP < Long WHIP → pitcher improving / in form
- Short WHIP > Long WHIP → pitcher degrading / fatiguing
- Difference (short - long) = **momentum oscillator**

Per-starter features:
- `whip_short_sp` — WHIP rolling 5 starts ★★★
- `whip_long_sp` — WHIP rolling 15 starts ★★★
- `whip_momentum_sp` — (whip_short - whip_long) ★★★ oscillator signal
- `kbb_short_sp` — K/BB rolling 5 starts ★★★
- `kbb_long_sp` — K/BB rolling 15 starts ★★★
- `kbb_momentum_sp` — (kbb_short - kbb_long) ★★★ oscillator signal
- `k9_sp` — K per 9 innings (long window) ★★
- `ip_avg_sp` — average innings per start (durability proxy) ★
- `hand_sp` — R/L (already have in data: pitcher name suffix) ★

#### Derived / composite features
- `whip_combined = (whip_long_home_sp + whip_long_away_sp) / 2` ★★
- `whip_diff = whip_long_away_sp - whip_long_home_sp` ★★ (positive = home advantage)
- `kbb_combined` ★★
- `kbb_diff` ★★
- `pitcher_momentum_diff = momentum_home - momentum_away` ★★★
  (positive = home pitcher trending better)
- `pitcher_matchup_quality = whip_diff × kbb_ratio` ★★

#### Per-team batting vs pitcher hand
- `ops_vs_rhp`, `ops_vs_lhp` — batting splits vs R/L pitchers ★★
- `babip_vs_rhp`, `babip_vs_lhp` ★

**Data availability**: pybaseball provides per-start game logs for all MLB pitchers.
Already have pitcher names in our data (1,379 unique across 11 seasons).

**Window lengths to test**: short = {3, 5}, long = {10, 12, 15}. Start with 5/15.

**Estimated impact**: pitcher stats should add ~3-5pp to prediction accuracy.
This could be enough to make series dogon and other strategies profitable.

**STATUS (Session 3):** Implemented as PROXY features (rolling WR, RA, 1st inn RA).
Real WHIP/K/BB require pybaseball. Proxy approach works: +3.07% ROI at 545 series.
Best filter: SP WR long diff >= 0.10 combined with RPI >= 0.03.

### Tier 3 — Park + Context (need external data)
- Park factor (Coors ~1.3, Petco ~0.85) — from pybaseball or manual table
- 1st inning ERA (for YRFI) — from pybaseball game logs
- Bullpen ERA/WHIP — from pybaseball
- Batted ball profile (Gb%, Fb%, Ld%) — from pybaseball
- Day of week patterns — already in our data
- NL penalty (0.91 for 2010-2021 only) — easy to add

### Tier 4 — Live Only (not for backtest)
- Twitter/X sentiment (Grok API)
- Lineup data (daily lineups not in historical data)
- Weather
- Umpire tendencies

---

## Approaches to Test

| # | Approach | Data Needed | Files |
|---|----------|-------------|-------|
| 1 | **Series Fight (dogon)** | RPI, W/L, series position | `series.py` |
| 2 | **LLM Fair Odds** | All Tier 1+2 features | `llm_estimator.py` |
| 3 | **CatBoost ML** | All features (raw + synthetic) | `ml_model.py` |
| 4 | **YRFI Rules** | 1st inn ERA, BABIP, park factor | `rules.py` |
| 5 | **F5 Rules** | Starter stats, team batting | `rules.py` |
| 6 | **O/U ProjectedScore** | V7 formula features | `rules.py` |
| 7 | **Run Line** | RPI diff, starter quality | `rules.py` |

**Priority: Series Fight FIRST** — simplest to implement, highest conviction from legacy experience.
