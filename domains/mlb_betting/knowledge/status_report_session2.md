# Session 2 Status Report (Feb 12, 2026)

> Previous session: created repo, data loader, market builder, streak analysis notebook.
> This session: series dogon engine, features.py, deep analysis of series + run line strategies.

---

## What was done

### 1. Data Pipeline Validation
- Downloaded all 11 seasons (2010-2019, 2021) from sports-statistics.com
- Fixed Unicode encoding crash in download.py (Windows cp1251 vs UTF-8)
- Full pipeline test: **27,109 games -> 26,420 after filters -> 20,511 bettable**
- Installed missing deps (scipy, matplotlib, seaborn)

### 2. Streak Analysis (`scripts/run_streak_analysis.py`)
- Standalone validation script (no Jupyter needed)
- **Key findings:**
  - Baseline win rate: 50.0%
  - After W3+: 52.1% (p=0.0003) -- **hot hand confirmed**
  - After L3+: 46.8% (p<0.0001) -- **cold streak confirmed**
  - W7+: 63.2% win rate (228 games)
  - Betting ON winning streaks: **unprofitable** (odds price it in)
  - Betting AGAINST losing streaks: **+3.6-4.0% ROI** on L1-L3+
  - Year-by-year: W3+ > 50% in 10 of 11 seasons (consistent)

### 3. Legacy System Analysis (`knowledge/features_from_legacy.md`)
- Deep scan of 61 xlsx files from D:\bblxls (2016-2018 manual system)
- Documented all features, Solver parameters, design principles
- Key legacy Solver parameters: MinRPIoBet=0.48, RPIdiffAway=0.029-0.041
- Organized into Tier 1-4 priority for implementation
- **Core philosophy preserved**: selectivity > prediction accuracy

### 4. Series Identification + Dogon Engine (`src/series.py`)
- `identify_series()`: groups by (season, matchup_key), splits on >3 day gaps
- **8,414 series** across 11 seasons (~765/year), avg 3.1 games
- Series length: 70% are 3-game, 20% are 4-game, 10% are 2-game
- `run_series_dogon()`: stake calculation for fixed $100 profit target
- `backtest_series_dogon()`: full backtest with filtering (COL, September, etc.)
- Bug fixed: NaN in home_final causing ValueError

### 5. Feature Engineering (`src/features.py`)
- `build_team_game_log()`: 52,838 team-game rows from 26,420 games
- `calc_rolling_wp()`: overall WP, home/away splits, last 10/20 games
- `calc_streaks()`: signed streak entering each game
- `calc_rolling_runs()`: RPG, RAPG, last-10 rolling
- `calc_rolling_rpi()`: **daily rolling RPI** (0.25*WP + 0.50*OWP + 0.25*OOWP)
- `build_all_features()`: 35 features per game, ~173 seconds to compute
- **RPI validated as strong predictor:**
  - RPI diff > +0.05: home WR = 64.4%
  - RPI diff < -0.05: home WR = 40.2% (away WR 59.8%)
  - Monotonic relationship across all buckets

### 6. Series Dogon Deep Analysis (`scripts/run_series_deep_analysis.py`)
- **Breakeven math**: WR needed = 81.7%, actual = 80.9% (gap = -0.8pp)
- **Vig analysis**: favorites win G1 58.3%, odds imply 59.3% (1.1pp vig)
- **G2 degradation**: G2 win rate = 54.2% (vs G1 = 58.3%)
- **Max drawdown**: $60,180 on $10K bankroll (wipe)
- **Worst streak**: 6 consecutive series losses

### 7. Feature-Filtered Series (`scripts/run_series_with_features.py`)
- Tested 20+ filter combinations: RPI, WP, streak, implied prob, quality floor
- **Best results:**
  - RPI diff >= 0.05: 365 series, 87.1% WR, **+0.4% ROI** (barely positive)
  - Implied prob [0.50, 0.53): 230 series, 79.6% WR, **+3.5% ROI**
  - RPI>=0.03 + WP>=0.10 + Streak>=W2 + MinRPI>=0.48: 198 series, 84.3% WR, ~0% ROI

### 8. Run Line Analysis (`scripts/run_runline_real_odds.py`)
- **Critical data insight**: `home_run_line` field contains BOTH run line (-1.5/+1.5) AND O/U totals (7.0-12.0) mixed together
  - -1.5 = home favorite (10,909 games = 41.3%)
  - +1.5 = home underdog (5,839 games = 22.1%)
  - 5.5+ = O/U total (rest)
- **ML to +1.5 odds drop**: avg 0.51 (range 0.45-0.80 depending on matchup)
- **With REAL odds:**
  - Home underdog +1.5: 55.7% cover, 1.75 odds, **-3.5% ROI** (unprofitable)
  - Home favorite -1.5: 40.8% cover, 2.40 odds, **-4.0% ROI** (unprofitable)
  - RPI-filtered +1.5: cover rate improves to 57-59%, but odds too low (1.65-1.67)
  - Only WP diff > 0.05 showed +1.6% ROI (314 games, small sample)

---

## Key Conclusions

### What works
1. **RPI is a powerful predictor** -- monotonic, significant, 64% WR at extremes
2. **Streaks have real momentum** -- W3+ = 52.1%, L3+ = 46.8%, both significant
3. **Feature engineering adds value** -- RPI, WP, streak filters improve series WR from 80.9% to 87.1%
4. **Betting AGAINST losing streaks** shows genuine ROI (+3.6-4.0%)

### What doesn't work YET (with current team-only features)
1. **Raw series dogon**: -2.8% ROI across all configs, vig kills the edge
2. **Run Line +1.5 underdog**: -3.5% ROI with real odds, estimated ROI was inflated
3. **Run Line -1.5 favorite**: -4.0% ROI, consistently negative
4. **Heavy favorite filters**: higher WR but worse ROI (lower odds)

### Key context: pitcher layer NOT YET IMPLEMENTED
- Current features = team-level ONLY (RPI, WP, streak, RPG)
- Legacy system (2016-2018) also had NO pitcher data and still found edge via Solver
- Pitcher accounts for ~40% of game outcome (not 60-70% as commonly believed)
- Pitcher stats (ERA, WHIP, K/BB, K/9) are the biggest missing data layer
- We have pitcher NAMES in data (1,379 unique) but not their performance stats
- pybaseball can provide per-start game logs (IP, H, R, ER, BB, K, HR)
- **Adding pitcher layer is expected to provide the 2-5pp improvement needed for profitability**

### Core insight
**The bookmaker prices TEAM strength accurately.** But:
- Pitcher matchup quality varies enormously game-to-game
- Team metrics + pitcher metrics together may exceed what the line captures
- Legacy system got results from team-only metrics with extreme selectivity
- Pitcher layer should amplify the selectivity signal significantly

---

## What remains from the plan

### HIGHEST PRIORITY: Pitcher Data Layer
| # | Task | Priority | Notes |
|---|------|----------|-------|
| 1 | Pitcher game logs via pybaseball | **CRITICAL** | IP, H, BB, K per start for 1,379 pitchers across 11 seasons |
| 2 | Pitcher oscillator features | **CRITICAL** | WHIP short/long (5/15 starts), K/BB short/long, momentum = short-long. NOT ERA (too noisy). |
| 3 | Add pitcher features to features.py | **CRITICAL** | Per-game: starter WHIP/K/BB at both windows, momentum, matchup composite, hand (R/L) |
| 4 | Momentum trail features (ShortWinsTrail, LongWinsTrail) | HIGH | Variable windows 7/10/14/22 from legacy |
| 5 | Re-test series dogon with pitcher+team features | HIGH | This is the key test: does pitcher layer make dogon profitable? |
| 6 | Re-test run line with pitcher+team features | HIGH | Cover rate needs +2-3pp to become profitable |

### Next steps after pitcher layer
| # | Task | Priority | Notes |
|---|------|----------|-------|
| 6 | `src/rules.py` | MEDIUM | Expert rules for YRFI, F5, O/U with full feature set |
| 7 | `src/llm_estimator.py` + notebook 03 | MEDIUM | OpenAI Batch API, GPT-4o-mini, ~$1-10 for full backtest |
| 8 | `src/ml_model.py` + notebook 09 | MEDIUM | CatBoost on 50+ features (team + pitcher), train 2010-2018, test 2019+2021 |
| 9 | `src/backtester.py` | MEDIUM | Generic backtest engine for any strategy |
| 10 | Notebooks 04-08, 10 | LOW-MED | YRFI, F5, Totals, Run Line, Series, Combined analysis |
| 11 | `src/bankroll.py` + `src/viz.py` | LOW | Kelly, staking, visualizations |

### Partially done
| # | Task | Status | Notes |
|---|------|--------|-------|
| 1 | Feature engineering | ~60% done | Team layer complete (35 features). Missing: pitcher layer, park factors, batting splits |
| 2 | Series dogon strategy | Analysis complete at team level | -2.8% ROI without pitcher data. Breakeven at 81.7% WR, best = 87.1%. Pitcher layer may provide needed +2-5pp |
| 3 | Run Line strategy | Analysis complete at team level | -3.5% to -4% ROI with real odds. Need pitcher data for meaningful filtering |

---

## Decision Points / Forks

### Fork 1 (RESOLVED): Next priority — PITCHER DATA
User decision: rules-based approach is NOT exhausted. Pitcher stats (ERA, WHIP, K/BB, K/9)
are the biggest missing layer. Implement pitcher features BEFORE moving to LLM/CatBoost.

**Action plan:**
1. Pull pitcher game logs via pybaseball (per-start: IP, H, R, ER, BB, K)
2. Compute rolling pitcher features (5-10 start windows)
3. Add to features.py as Tier 2 features
4. Re-run series dogon and run line backtests with pitcher+team features
5. THEN decide if LLM/CatBoost is needed or if rules suffice

### Fork 2: Which markets to focus on?
- **Series dogon**: needs +2-5pp WR improvement. Pitcher data may provide this.
- **YRFI**: needs pitcher-specific 1st inning data. Less efficient market = more edge potential.
- **F5**: purely starter-driven (no bullpen). Pitcher features are KEY here.
- **Moneyline**: most data but bookmaker most accurate. Pitcher matchup is the main differentiator.
- **Run Line**: needs +2-3pp cover improvement. Difficult with low +1.5 odds (1.65-1.75).

### Fork 3: pybaseball data scope
- **Game logs** (per-start): IP, H, R, ER, BB, K, HR, pitches. ~30K starts over 11 seasons.
- **Statcast** (pitch-level): velocity, spin rate, movement. Much more data but overkill for now.
- **Team batting splits** (vs R/L): OPS, BABIP, K% by batter handedness vs pitcher hand.
- **Recommendation**: start with game logs (simplest, most impactful), add Statcast later if needed.

### Fork 4: Momentum implementation
Legacy had ShortWinsTrail (7-14 games) and LongWinsTrail (10-22 games).
Currently we have simple streak (W3, L5 etc) and wp_last10/last20.
Options:
- Simple: keep current streak + last10/last20 (already done)
- Medium: add variable-window WP trails (7/14/22 games)
- Full: add rolling run differential, scoring trend, defensive trend
**Recommendation**: medium — add 7/14/22 trails, low effort, high potential impact.

### Fork 5: 2022+ data gap
- Our data ends at 2021. 2023+ has pitch clock + shift ban (structural regime change).
- pybaseball may have 2022-2025 data too — check availability.
- If available: extend backtest to 2022-2025 for out-of-sample validation.
- If not: backtest on 2010-2021, calibrate adjustments from rule change document.

---

## File Inventory

```
mlb-betting/
├── pyproject.toml              # Dependencies: pandas, catboost, openai, scipy, etc.
├── .gitignore                  # Ignores data/raw, data/processed, *.jsonl, .env
├── .env.example                # Template for API keys
├── data/
│   └── download.py             # Downloads 11 seasons from sports-statistics.com
├── knowledge/
│   ├── features_from_legacy.md # All features from 61 legacy xlsx files
│   ├── mlb_rule_changes_2022_2026.md # Rule changes affecting 2022+ data
│   └── status_report_session2.md # THIS FILE
├── notebooks/
│   ├── 00_streak_analysis.ipynb # Streak momentum analysis (complete)
│   ├── 01_data_exploration.ipynb # Data quality + exploration (complete)
│   └── 02_market_construction.ipynb # YRFI, F5, RL, Race to X (complete)
├── scripts/
│   ├── run_streak_analysis.py    # Standalone streak analysis
│   ├── run_series_backtest.py    # 6-config series dogon backtest
│   ├── run_series_deep_analysis.py # Deep series analysis (vig, math, bankroll)
│   ├── run_series_with_features.py # Series dogon + RPI/WP/streak filters
│   ├── run_runline_analysis.py   # Initial RL analysis (estimated odds)
│   └── run_runline_real_odds.py  # RL analysis with ACTUAL odds + RPI
└── src/
    ├── __init__.py
    ├── data_loader.py            # Load xlsx, pair home/away, apply filters
    ├── market_builder.py         # YRFI, F5, Race to X from inning data
    ├── features.py               # Rolling RPI, WP, streak, RPG (35 features)
    └── series.py                 # Series ID, dogon engine, backtest runner
```

## Data Loaded
- **Source**: sports-statistics.com xlsx files
- **Seasons**: 2010-2019, 2021 (2020 excluded: COVID)
- **Raw games**: 27,109
- **After hard filters**: 26,420 (removed: missing odds, missing pitcher, double-headers)
- **Bettable**: 20,511 (excluded: Colorado, September, extreme lines)
- **Series identified**: 8,414 (avg 3.1 games each)
- **Team-game rows**: 52,838 (2 per game, for feature computation)
