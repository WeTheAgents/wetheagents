# Session 7 Status Report — Away Underdog Deep Dive + SBR Integration

Date: 2026-03-19

## Critical Bug Found & Fixed

**88.5% duplicate rows in analysis dataset.** `build_spec_features()` produces duplicate game entries (doubleheader ambiguity + Retrosheet merge fan-out). One game (SDG@STL 2016-07-20) appeared 200+ times.

**Impact**: All previous session 6 ROI numbers were inflated by duplicates. Favorite-side ROI dropped from +17% to ~-2% after dedup.

**Fix**: Added `drop_duplicates(subset=[season, date, home_team, away_team, fold])` in `build_analysis_df()` within `scripts/analyze_divergence.py`.

**Root cause**: `build_spec_features()` itself outputs dupes. Needs investigation — likely in the Retrosheet merge step or bullpen features join. The dedup in the analysis script is a bandaid; the real fix should be in `src/features.py`.

## Corrected Results (Post-Dedup)

### Favorite-side: NOT profitable
Previous claim of +17% ROI was artifact of duplicates. Real ROI is ~-2%.

### Away Underdog ML: Profitable strategies confirmed

| Strategy | Bets | WR | Avg Odds | ROI | Sharpe | Kelly | Max Lstreak | Max DD% | Folds |
|----------|------|-----|----------|-----|--------|-------|-------------|---------|-------|
| S1: elo≤0 + edge<-0.05 | 351 | 47.3% | 2.38 | +12.4% | 0.65 | 9.0% | 12 | 21.7% | 7/9 seasons profitable |
| S3: rpi≤0 + elo≤30 + edge<-0.05 | 874 | 45.7% | 2.41 | +9.9% | 0.81 | 7.1% | 19 | 22.5% | 8/9 seasons profitable |
| S4: rpi≤0 + home_bp>p75 + edge<-0.05 | 179 | 50.3% | 2.46 | +22.3% | — | — | — | — | 5/5 folds positive |

### Away Underdog RL +1.5: Promising with filters

Best combos on edge<-0.05:
- `elo_diff≤0 + home_bp_3d>med`: 126 bets, 73% cover, +21% ROI, 5/5 folds positive
- `home_bp_3d>p75 + away_rpg>=med`: 278 bets, 65% cover, +10% ROI, 5/5 folds positive
- `elo_diff≤0 + rpi_diff≤0.05`: 343 bets, 66% cover, +8% ROI

## Data Expansion: SBR Integration (In Progress)

**Source**: ArnavSaraogi/mlb-odds-scraper (GitHub, MIT license)
- 76MB JSON, 2021-2025, SportsBookReview data
- 6 sportsbooks: DraftKings, FanDuel, Bet365, Caesars, BetMGM, BetRivers
- Moneyline (open + close), Run Line (BOTH sides!), O/U totals
- Already downloaded to `data/raw/sbr_odds_full.json`

**Team mapping needed**: WAS→WSN, TB→TBR, CHW→CWS, SD→SDP, SF→SFG

**Key value**: Away RL odds for BOTH sides (currently only home side in our data). This eliminates the 1.87 fixed estimate for away +1.5 odds.

**Plan**: `scripts/build_sbr_xlsx.py` converts SBR JSON + Retrosheet inning scores → xlsx files matching our existing format. Detailed plan in `.claude/plans/`.

**Issue #254**: Created for expanding further to 2000-2009 (separate task, 100 WEA).

## Open Questions

1. **S3 loss streak of 19**: Needs anatomy analysis. Are there common factors (day of week, stadium, odds band)? Additional filters could reduce max DD without destroying ROI, enabling higher Kelly fraction.

2. **Favorite-side signal**: With clean data, fav bets show ~-2% ROI. The model may still be useful as a FILTER (not a bet signal) — i.e., the model's edge correlates with dog win probability even if fav flat bets lose.

3. **Duplicate root cause**: Should be fixed at source in `build_spec_features()`, not just bandaided in analysis script.

## Files Modified This Session

| File | Change |
|------|--------|
| `scripts/analyze_divergence.py` | Complete rewrite: real odds, away dog focus, RL+ML analysis, dedup fix, combo search |
| `scripts/bankroll_analysis.py` | Bankroll metrics for S1/S3/S4 (Kelly, Sharpe, drawdown, ruin probability) |
| `data/raw/sbr_odds_full.json` | Downloaded SBR dataset (76MB) |

## Next Session Priorities

1. **Build SBR xlsx converter** — plan is ready in `.claude/plans/`, script is `scripts/build_sbr_xlsx.py`
2. **Update `data_loader.py`** — add SEASONS 2022-2025, add `away_run_line_odds` to `pair_games()`
3. **Rebuild retrosheet + rerun analysis** — expect 6-7 folds instead of 4, validate S1/S3/S4 on fresh data
4. **S3 loss streak anatomy** — find filterable patterns in the 19-game losing streak
5. **Fix duplicate root cause** — investigate `build_spec_features()` duplication source
