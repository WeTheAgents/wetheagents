# Session 11 Status Report — Home Underdog Dead End + Portfolio Correlation

Date: 2026-03-20

## 1. Home Underdog: Comprehensive Dead End

Tested home underdog (away team = favorite, ~40% of games) with walk-forward model edge. Two strategies:

### 1a. Home +1.5 Run Line
- Universe: 5,453 games with real `home_run_line_odds` (no estimation needed)
- Baseline: 54.6% cover, avg odds 1.72, **ROI -6.3%**
- With edge > 0.05: 1,900 bets, 58.3% cover, but odds 1.61 → breakeven 62.1% → **ROI -6.2%**
- Best single filter (streak_away <= 0): 60.8% cover, odds 1.61, **ROI -2.4%** (still negative)
- No positive-ROI combos generated — section 3 returned empty

### 1b. Home ML (moneyline win)
- Universe: 7,824 games
- Baseline: 43.9% WR, avg odds 2.18, **ROI -4.9%**
- With edge > 0.05: 2,915 bets, 47.8% WR, odds 1.99, **ROI -4.9%**
- Closest to breakeven: wp_home_at_home >= 0.55 → 50.3% WR, **ROI -0.1%** (not profitable)

### Why it fails
Bookmakers correctly price home field advantage into run line odds. Home +1.5 odds average 1.61-1.72 (vs ~1.87 for away +1.5). The breakeven cover rate at these odds (58-62%) is too high to reach with available features.

**Conclusion: home underdog is a dead end. Do not revisit.**

## 2. Portfolio Correlation: S3-dual + RL +1.5

Analyzed combining the two profitable away underdog strategies.

### Strategy recap
- **S3-dual (Away ML)**: edge < -0.05, rpi/elo filters, dual-regime. 54 bets/season, +6.9% ROI, Sharpe 0.426
- **RL-1H (Away +1.5)**: edge > 0.10, first half only. 91 bets/season, +11.8% ROI, Sharpe 1.233
- **RL-FIP (Away +1.5)**: FIP > 0.5 + edge > 0.10. 56 bets/season, +12.5% ROI, Sharpe 1.031

### Key finding: ZERO overlap
Strategies use opposite edge directions (< -0.05 vs > 0.10) — they **never bet on the same game**. Overlap = 0 out of 1,812 bets.

### Correlation metrics

| Level | S3 vs RL-1H | S3 vs RL-FIP |
|-------|-------------|--------------|
| Daily (both active) | 0.234 | 0.116 |
| Daily (all dates) | 0.035 | 0.020 |
| Monthly | 0.093 | -0.025 |
| Season | 0.162 | 0.158 |

Monthly correlation with RL-FIP is effectively zero (-0.025) — ideal for diversification.

### Combined portfolio results

| Portfolio | Bets/season | ROI | Sharpe | MaxDD | Folds+ |
|-----------|-------------|-----|--------|-------|--------|
| S3-dual only | 54 | +6.9% | 0.426 | 28.4% | 9/15 |
| RL-1H only | 91 | +11.8% | 1.233 | 35.8% | 6/11 |
| **S3 + RL-1H** | **121** | **+9.6%** | **1.012** | 45.4% | 9/15 |
| RL-FIP only | 56 | +12.5% | 1.031 | 25.5% | 8/11 |
| **S3 + RL-FIP** | **95** | **+9.3%** | **0.842** | 37.9% | 9/15 |

### Diversification quality
- Months both strategies lose: only 4/33 (12%)
- Hedging works: S3's worst months often offset by RL gains (and vice versa)
- Combined Sharpe (1.012) is close to theoretical uncorrelated maximum (1.305)
- MaxDD increases in combo due to S3's early seasons (2010-2013) without RL data

### Best allocation
- S3=$75, RL=$100 → Sharpe 1.075, ROI +10.0% (slight edge over equal allocation)
- Rationale: RL-1H has higher Sharpe, deserves slightly more capital

### Per-season trajectory (S3 + RL-1H combined)
Strong acceleration in recent seasons:
- 2019: +$1,956 (15.6% ROI)
- 2022: +$2,275 (45.5% ROI)
- 2023: +$3,923 (38.5% ROI)
- 2024: +$6,072 (44.0% ROI)
- 2025: +$5,030 (48.8% ROI)

## 3. Dead Ends Updated

| Approach | Why it fails |
|----------|-------------|
| Favorite flat ML | Vig eats 4-5%, WR 56-60% = exactly breakeven |
| Favorite RL -1.5 | Cover rate 43%, breakeven ~50% at RL odds |
| Favorite series dogon | WR 80.5%, breakeven 82.7%, gap -2.2pp |
| **Home underdog +1.5** | **Odds too low (1.61-1.72), breakeven 58-62% unreachable** |
| **Home underdog ML** | **WR peaks at 50.3%, breakeven ~50.5%, no margin** |

## 4. Final Strategy Portfolio

### Production strategies (2 confirmed)
1. **S3-dual (Away ML)**: edge < -0.05 + rpi/elo dual-regime → ~54 bets/season, +6.9% ROI
2. **RL-1H (Away +1.5)**: edge > 0.10 + first half → ~91 bets/season, +11.8% ROI

### Portfolio characteristics
- Total: ~120 bets/season (~2.5/week during season)
- Zero overlap, near-zero monthly correlation
- Combined ROI: +9.6%, Sharpe: 1.012
- Both strategies bet exclusively on **away underdogs**, one ML and one RL

## 5. Scripts Created

- `scripts/rl_home_analysis.py` — home underdog backtest (confirmed dead end)
- `scripts/portfolio_away_underdog.py` — portfolio correlation analysis
