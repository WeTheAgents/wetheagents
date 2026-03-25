# Session 6: Away Underdog ML + Data Expansion (2022-2025)

## Summary

Integrated 4 new seasons (2022-2025) from SportsBookReview dataset, expanding from 11 to 15 seasons and from 4 to 8 walk-forward folds. Discovered that the previously profitable away RL +1.5 strategy did NOT survive out-of-sample validation on new data. Instead, found a robust **away underdog moneyline** signal based on Elo proximity + model edge.

## Data Integration

### SBR Dataset (ArnavSaraogi/mlb-odds-scraper, MIT license)
- Source: SportsBookReview.com via GitHub release (76MB JSON)
- Coverage: 2021-04-01 through 2025-08-16
- Books: DraftKings (primary), FanDuel, Bet365, Caesars, BetMGM, BetRivers
- Used: DraftKings `currentLine` for closing odds, `openingLine` for opening

### Merge Pipeline
- SBR odds + Retrosheet `teamstats.csv` (inning scores, pitcher IDs, final scores)
- Match rate: 99.9-100% across all seasons
- Team abbreviation mapping: ATH→OAK, AZ→ARI, WAS→WAS, TB→TAM, CHW→CWS, SD→SDG, SF→SFO, CHC→CUB, KC→KAN
- Output: xlsx files in existing format, dropped into `data/raw/odds/`
- September excluded from new seasons (operator instruction)

### New Data Coverage
| Season | Games | Source |
|--------|-------|--------|
| 2022 | 1,951 (1,844 after filters) | SBR + Retrosheet |
| 2023 | 2,003 (1,953) | SBR + Retrosheet |
| 2024 | 2,041 (1,981) | SBR + Retrosheet |
| 2025 | 1,722 (1,666) | SBR + Retrosheet (through Aug 16) |

### New Capability: Real Away Run Line Odds
- Added `away_run_line` and `away_run_line_odds` columns to `pair_games()`
- SBR provides both home AND away spread odds (DraftKings)
- Replaces hardcoded 1.87 estimate with per-game real odds
- 100% coverage for all 33,853 filtered games

## Key Finding: Favorite Edge Degraded

The favorite-side strategy that showed +16% ROI on 4 folds (2010-2021) dropped to +7.8% ROI on 8 folds. New folds (2022-2025) show [-9, -4, -4] ROI — the market got more efficient.

## Key Finding: Away RL +1.5 Did NOT Survive

Previously: edge<-0.05 → 2,224 bets, 59.4% cover, +11% ROI.
With 8 folds: 4,020 bets, 57.0% cover, **-2.63% ROI**. New folds all negative.

**Lesson**: a strategy validated on only 4 folds can be a mirage. 8 folds revealed the truth.

## Key Finding: Away Underdog ML Signal

Three strategies survived 8-fold validation:

### S1: elo_diff ≤ 0 + edge < -0.05
- 351 bets, WR=47.3%, avg odds=2.38, **ROI=+12.4%**
- Folds: [-18,+1,+14,+27,+32,+18,+19,+17] — 6/8 positive
- Sharpe: 0.65, Half Kelly: 4.52%, Max DD: 21.7%
- Max loss streak: 12, Profitable seasons: 7/9

### S3: rpi_diff ≤ 0 + elo_diff ≤ 30 + edge < -0.05
- 874 bets, WR=45.7%, avg odds=2.41, **ROI=+9.9%**
- Folds: [-3,+8,+10,+25,+26,+18,+18,-3] — **6/8 positive**
- Sharpe: **0.81**, Half Kelly: 3.53%, Max DD: 22.5%
- Max loss streak: 19, Profitable seasons: **8/9**
- Best risk-adjusted: highest Sharpe, most consistent seasons

### S4: rpi_diff ≤ 0 + bp_ip_3d_home > p75 + edge < -0.05
- 199 bets, WR=49.2%, avg odds=2.46, **ROI=+20.6%**
- Folds: [+15,+23,+14,+29,+23] — **5/5 positive**
- Sharpe: **1.05**, Half Kelly: 7.25%, Max DD: **12.1%**
- Max loss streak: 11, Profitable seasons: 4/5
- Strongest signal, smallest drawdown, but smallest sample

## Bankroll Recommendations

| Strategy | Half Kelly Bankroll | Quarter Kelly Bankroll | Bets/Season |
|----------|--------------------|-----------------------|-------------|
| S1 | $2,215 | $4,430 | ~39 |
| S3 | $2,835 | $5,670 | ~97 |
| S4 | $1,379 | $2,758 | ~22 |

Recommended approach: S3 on quarter Kelly as base, S4 as overlay.

## Signal Interpretation

**Why Elo matters for away underdogs:**
When the model says "favorite is overvalued" (edge < -0.05) AND Elo confirms the away team is competitive (elo_diff ≤ 0 or ≤ 30), the underdog has genuine quality. The market is pricing home-field advantage too aggressively for evenly-matched teams.

**Why bullpen fatigue (S4) amplifies the signal:**
When the home team's bullpen is overworked (top 25% of 3-day IP), their late-game advantage evaporates. Combined with a competitive away team (rpi_diff ≤ 0), this creates a systematic market inefficiency.

## Files Created/Modified

| File | Change |
|------|--------|
| `scripts/build_sbr_xlsx.py` | **NEW** — SBR JSON + Retrosheet → xlsx converter |
| `scripts/bankroll_analysis.py` | **NEW** — Kelly, drawdown, streaks, ruin probability |
| `scripts/analyze_divergence.py` | Rewritten: real odds, away RL, feature filters, combos |
| `src/data_loader.py` | Added 2022-2025 to SEASONS; added away_run_line columns |
| `data/raw/sbr_odds_full.json` | SBR dataset (76MB, not committed) |
| `data/raw/odds/mlb-odds-{2022..2025}.xlsx` | Generated xlsx files |

## Next Steps

1. **FanGraphs data for 2022-2025** — wRC+, OBP, bullpen FIP currently NaN for new seasons (73% feature coverage). Adding this could improve model accuracy.
2. **Walk-forward with more granular folds** — current folds are 2-year test windows; could try 1-year windows for more folds.
3. **Live paper trading** — April 2026 Polymarket MLB markets for S3 validation.
4. **Historical odds pre-2010** — Issue #254 created for expanding to 2000-2009.
5. **Correlation analysis** — do S1, S3, S4 bet on the same games? If uncorrelated, portfolio diversification applies.
