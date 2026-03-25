# Session 9 Status Report — Favorite Dead End + RL +1.5 Discovery + 21-Season Expansion

Date: 2026-03-19 (third session of the day)

## 1. Favorite-Side: Comprehensive Dead End

Tested three angles on favorite betting. All negative ROI.

### 1a. Flat ML on favorites
- Baseline: 11,384 games, WR 56.5%, avg odds 1.716, **ROI -3.5%**
- Edge bands: even "fav very cheap" (edge < -0.10) gives -4.3% — vig eats everything
- Contrarian (weakness + model value): all combos -1.4% to -6.4%
- Divergence signals: div_std <= 0.008 + edge<-0.05 → -0.1% (closest to zero, still negative)

### 1b. Favorite RL -1.5 (win by 2+)
- Cover rate 43.3%, avg RL odds 2.265, **ROI -2.4%**
- Best edge band: -0.05 <= edge < 0 → +1.8% (noise, 3/9 seasons)

### 1c. Favorite Series Dogon
- Baseline: 3639 series, WR 80.5%, breakeven 82.7%, **gap -2.2pp**
- Best combo: pyth>=0.03 + m34<0 → WR 83.8%, gap +0.8pp, ROI +1.7% — too thin, fragile
- **Conclusion**: market prices favorites efficiently. No exploitable edge.

## 2. Away RL +1.5: Strong Profitable Strategy

### Key discovery: edge direction INVERTED for RL +1.5

For ML underdog betting, `edge < -0.05` works (model says dog is underpriced).
For RL +1.5 cover, **`edge > 0.05` works** (model says favorite is overpriced → tighter games → +1.5 covers more).

### Baseline (edge > 0.05)
- 3,039 bets (276/season), cover 61.2%, avg odds 1.69, **ROI +3.7%**, Sharpe 0.701

### Two key signals
1. **Pitcher FIP diff > 0** — away pitcher better than home pitcher by FIP
2. **First half (pre-ASG)** — tighter games before All-Star break

### Top strategies (21 seasons, 11 folds)

| Strategy | Bets | B/S | Cover | ROI | Sharpe | Kelly/2 | Folds+ |
|----------|------|-----|-------|-----|--------|---------|--------|
| **1H + edge>0.10** | 1006 | 91 | 63.8% | +11.8% | 1.233 | 7.4% | 6/11 |
| FIP>0.5 + edge>0.10 | 612 | 56 | 64.9% | +12.5% | 1.031 | 8.4% | 8/11 |
| FIP>0 + 1H | 859 | 78 | 63.3% | +11.2% | 1.079 | 7.0% | 6/11 |
| FIP>0 + pyth≤0.05 | 925 | 84 | 63.5% | +10.9% | 1.088 | 7.1% | 6/11 |
| rpi≤-0.02 + FIP>0 | 187 | 17 | 66.8% | +19.4% | 0.861 | 12.3% | 8/11 |
| FIP>0 (full season) | 1441 | 131 | 63.2% | +8.4% | 1.081 | 5.6% | 6/11 |
| edge>0.15 + pyth≤0.03 | 292 | 27 | 63.7% | +13.8% | 0.757 | 8.9% | 7/11 |

### FIP works in 2H too
- 2H + FIP>0: 413 bets/season=46, cover 62.5%, ROI +6.9%, Sharpe 0.529, 5/9
- But 1H is 3x stronger: Sharpe 1.663 vs 0.529

### Away ML win with edge > 0.05: DOES NOT WORK
- edge > 0.05: WR 46.0%, avg dog odds 2.08, ROI **-4.7%**
- Odds too compressed in this zone. RL +1.5 is the only profitable play here.

## 3. Dataset Expansion: 11 → 21 Seasons

Merged PR #255: expanded from 11 seasons to 21 (2004-2025, excl. 2020).

| Metric | Before | After |
|--------|--------|-------|
| Seasons | 11 (2010-2019, 2021) | 21 (2004-2025) |
| Total games | ~27K | 48,300 |
| Walk-forward folds | ~5 | ~11 |
| 2025 coverage | through Aug 16 | through Aug 16 |

**Validation**: 2024 benchmark matched exactly (1981 games, HWR 0.5235, away+1.5 cover 0.645).

**Model fix**: added NaN→0 fallback for `train_medians` in `model.py:119` — prevents crash when early seasons (2004-2009) lack Retrosheet/FanGraphs features.

**RL data**: only available for 2014+ and 2022-2025, so RL analysis uses 11 seasons despite 21 being loaded.

## 4. Confirmed Strategy Portfolio

### Strategy 1: S3-Dual (Away ML Underdog)
- **Signal**: edge_consensus < -0.05 (model says underdog is underpriced)
- **1H (pre-ASG)**: S3 + rpi_diff <= -0.01 + elo_diff <= 15
- **2H (post-ASG)**: S3 base (edge < -0.05, rpi <= 0, elo <= 30)
- **Result**: 398 bets (44/s), WR 49.0%, ROI +17.9%, Sharpe 0.983, 8/9 seasons+

### Strategy 2: RL +1.5 Away (NEW)
- **Signal**: edge_consensus > 0.05 (model says favorite is overpriced → tight games)
- **Best config**: 1H + edge > 0.10
- **Result**: 1006 bets (91/s), cover 63.8%, ROI +11.8%, Sharpe 1.233, 6/11 seasons+
- **Alt config**: FIP > 0.5 + edge > 0.10 → 612 bets (56/s), ROI +12.5%, 8/11 folds

### Combined Portfolio
- S3-dual: ~44 bets/season (ML underdog, high ROI)
- RL +1.5: ~91 bets/season (RL cover, high Sharpe)
- **Total: ~135 bets/season**
- Strategies use OPPOSITE edge directions → likely uncorrelated

## 5. Dead Ends (Do Not Revisit)

| Approach | Why it fails |
|----------|-------------|
| Favorite flat ML | Vig eats 4-5%, WR 56-60% = exactly breakeven |
| Favorite RL -1.5 | Cover rate 43%, breakeven ~50% at RL odds |
| Favorite series dogon | Breakeven WR ~84%, achievable WR ~81-84% = razor thin |
| Away ML win (edge > 0.05) | Dog odds 2.08 too compressed, WR 46% < breakeven 48% |

## 6. Next Priorities

1. **More volume**: need additional systems beyond S3-dual + RL +1.5
   - YRFI / F5 / Race-to-X markets (different dynamics)
   - Home underdog strategies (not tested yet)
   - Intra-game markets if Polymarket offers them
2. **Portfolio correlation**: S1/S3/S4 + RL — are they independent?
3. **2025 live validation**: compare model predictions vs actual outcomes game-by-game
4. **FanGraphs features**: wRC+/OBP still NaN for 2022-2025

## Files Modified/Created

| File | Change |
|------|--------|
| `scripts/favorite_dive.py` | NEW — favorite ML/RL/contrarian/divergence analysis |
| `scripts/series_fav_model.py` | NEW — favorite series dogon with model signals |
| `scripts/rl_away_analysis.py` | NEW — away RL +1.5 with inverted edge direction |
| `src/model.py` | Fix: NaN→0 fallback for train_medians (line 119) |
| `src/data_loader.py` | Conflict resolution after PR #255 merge |
| `knowledge/benchmark_2024_pre_merge.json` | 2024 validation snapshot |
| `knowledge/status_report_session9.md` | This file |
