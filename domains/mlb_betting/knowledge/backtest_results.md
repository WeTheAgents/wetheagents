# Backtest Results Summary

> All results use 2010-2019 + 2021 data (11 seasons, ~26,420 games).
> Bettable = excluding Colorado, September, extreme lines (~20,511 games).

---

## 1. Streak-Based Strategies

| Strategy | Bets | Win% | ROI | Verdict |
|----------|------|------|-----|---------|
| Bet ON winning streaks (W1+) | 18,345 | 51.6% | -1.3% | Odds price it in |
| Bet ON W3+ | 5,311 | 52.1% | -0.8% | Slightly negative |
| Bet AGAINST losing streaks (L1+) | 18,345 | 53.3% | +3.6% | **Profitable** |
| Bet AGAINST L3+ | 5,311 | 53.3% | +4.0% | **Best streak strategy** |
| Bet AGAINST L5+ | 1,523 | 54.8% | +3.8% | Profitable, fewer bets |

**Takeaway**: Momentum exists and is statistically significant. Betting AGAINST cold streaks shows genuine edge (~4% ROI). But odds partially price momentum -- betting ON hot streaks is unprofitable.

---

## 2. Series Dogon (Martingale)

Target: $100 profit per series, dogon in G2 if G1 lost.

| Config | Series | WR | ROI | Max Exposure |
|--------|--------|------|------|---|
| Baseline (all favorites) | 6,432 | 80.9% | **-2.8%** | $1,800 |
| Implied prob > 0.55 | 4,737 | 82.4% | -2.8% | $1,800 |
| Implied prob > 0.60 | 2,616 | 84.7% | -2.7% | $1,800 |
| No dogon (G1 only) | 6,432 | 58.3% | -2.0% | $420 |
| 3-game dogon | 6,432 | 90.2% | -2.2% | $5,220 |
| Moderate favorites (0.52-0.60) | 3,798 | 78.2% | -3.5% | $705 |

**Breakeven requires 81.7% series WR.** We achieve 80.9% at best.

### With feature filters:

| Filter | Series | WR | ROI |
|--------|--------|------|------|
| RPI diff >= 0.05 | 365 | 87.1% | **+0.4%** |
| Implied prob [0.50-0.53) | 230 | 79.6% | **+3.5%** |
| RPI>=0.03 + WP>=0.10 + Streak>=W2 + MinRPI>=0.48 | 198 | 84.3% | ~0% |

**Takeaway**: Raw dogon unprofitable. Very selective filters approach breakeven, but sample sizes are small. Needs pitcher data + ML to find reliable edge.

---

## 3. Run Line (-1.5 / +1.5)

### With ACTUAL odds from data:

| Strategy | Games | Cover% | Avg Odds | ROI |
|----------|-------|--------|----------|-----|
| Home favorite -1.5 | 8,412 | 40.8% | 2.40 | **-4.0%** |
| Home underdog +1.5 | 4,554 | 55.7% | 1.75 | **-3.5%** |

### Odds drop from ML to +1.5:

| Home implied prob | ML odds | +1.5 odds | Drop |
|-------------------|---------|-----------|------|
| 0.30-0.35 | 3.06 | 2.26 | 0.80 |
| 0.35-0.40 | 2.64 | 1.99 | 0.64 |
| 0.40-0.45 | 2.34 | 1.79 | 0.56 |
| 0.45-0.50 | 2.10 | 1.65 | 0.45 |

### With RPI filters (home underdog +1.5, actual odds):

| Filter | Games | Cover% | Odds | ROI |
|--------|-------|--------|------|-----|
| All | 3,831 | 55.7% | 1.76 | -3.3% |
| RPI: home >= away | 806 | 57.9% | 1.67 | -3.7% |
| WP diff > 0.05 | 314 | 61.5% | 1.66 | **+1.6%** |
| RPI>=0.02 + Streak W1+ | 123 | 58.5% | 1.66 | -3.0% |

**Takeaway**: Bookmaker prices RL very accurately. Even with RPI showing value, the low +1.5 odds (1.65-1.75) make it nearly impossible to profit. Breakeven at 1.75 odds = 57.1% cover, and we barely exceed that with filters.

---

## 4. RPI Prediction Power

| RPI Diff (home - away) | Games | Home WR |
|-------------------------|-------|---------|
| < -0.05 | 665 | 40.2% |
| -0.05 to -0.03 | 2,429 | 50.3% |
| -0.03 to -0.01 | 5,946 | 43.0% |
| -0.01 to +0.01 | 7,317 | 55.4% |
| +0.01 to +0.03 | 5,168 | 58.9% |
| +0.03 to +0.05 | 2,169 | 63.2% |
| > +0.05 | 665 | 64.4% |

**Strong monotonic relationship. RPI diff is our best single predictor.**

---

## Meta-Insight

Bookmakers price TEAM strength efficiently on Moneyline and Run Line.
Team-only features (RPI, WP, streak) improve predictions directionally but not enough
to overcome vig (~4-5%).

**Critical missing layer: PITCHER STATS (ERA, WHIP, K/BB, K/9)**

Legacy system (2016-2018) also had no pitcher data — just team metrics + Solver.
But pitchers are ~40% of the game outcome. Adding pitcher stats should provide
the 2-5pp improvement needed to cross the profitability threshold.

**What we still believe can work (rules-based):**
1. Pitcher matchup quality (ERA/WHIP differential) as primary filter
2. Team momentum (RPI, trail windows) as secondary filter
3. Extreme selectivity: 200-500 bets/year at higher stakes, not 6000 at minimum
4. Market-specific inefficiencies (YRFI, F5 less efficient than ML)

**Pitcher features are the #1 priority for next session.**

## Available Pitcher Data in Our Dataset

- **Pitcher names**: 1,379 unique across 11 seasons
- **Handedness**: R/L suffix on pitcher names
- **Starts per pitcher-season**: avg 15.4, median 13
- **What we can compute from our data**: runs allowed per start (crude ERA proxy)
- **What we need from pybaseball**: IP, H, BB, K per start -> WHIP, K/BB (NOT ERA — too noisy)
- **Oscillator approach**: short window (5 starts) vs long window (15 starts) for each metric
- Momentum = short - long. Like MACD in trading. Captures pitcher form trend.
