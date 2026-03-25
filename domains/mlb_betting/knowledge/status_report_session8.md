# Session 8 Status Report — Duplicate Fix + Dual-Regime S3 + September Discovery

Date: 2026-03-19 (second session of the day)

## 1. Duplicate Root Cause — FIXED

**Source**: `bullpen_features.parquet` had 613 doubleheader duplicate rows on (team, date). Internal merge (quality × close_game × workload) on (team, season, date) produced up to 8x fan-out per DH date. When merged to games in `build_spec_features()` for home + away sides, compounded to 64x.

**Fix**: Dedup `team_game_bp` after aggregation in `bullpen_features.py:330`, keeping game-1 entering state. Safety dedup + integrity check in `features.py:694`. Bandaid in `analyze_divergence.py` replaced with assertion.

**Result**: `build_spec_features()` → 17,814 rows (was ~230K with dupes), 0 duplicates.

**Post-dedup correction**: S3 bets 868 → 521 (without Sep), ROI +9.9% → +5.9%. Max loss streak 19 → 9.

## 2. September Discovery

September was filtered out based on "tanking teams" assumption. Analysis showed the opposite:

| Month | Bets | WR | ROI | MaxL |
|-------|------|-----|-----|------|
| May | 132 | 40.2% | -4.3% | 6 |
| Jun | 147 | 40.1% | -4.1% | 7 |
| Jul | 103 | 47.6% | +13.7% | 9 |
| Aug | 113 | 47.8% | +16.4% | 6 |
| **Sep** | **66** | **50.0%** | **+22.2%** | **4** |
| Oct | 17 | 58.8% | +43.2% | 4 |

**Why**: Tanking teams are HOME, which is exactly where S3 bets against. Tanking *helps* the away underdog edge. September filter removed from `build_spec_features()`.

## 3. May-June Key Found

May-June S3 base: 279 bets, -4.2% ROI. Wins vs losses profile showed:
- Elo diff: wins 5.9 vs losses 11.9 (tight matchups win)
- RPI diff: wins -0.020 vs losses -0.017 (need stronger RPI edge)
- Starter FIP diff: significant signal
- Home BP 3d: tired bullpen helps

**Key filter**: `rpi_diff <= -0.01 + elo_diff <= 15` on top of S3 base.
May-June with this filter: 123 bets, WR 52.0%, ROI +23.0%, MaxL 4.

## 4. Dual-Regime S3 (Final Configuration)

Split at All-Star break (~Jul 15):
- **1H (pre-ASG)**: S3 + rpi<=-0.01 + elo<=15
- **2H (post-ASG)**: S3 base (edge<-0.05, rpi<=0, elo<=30)

| Regime | Bets | B/Season | WR | ROI | Sharpe | Kelly/2 | MaxL | MaxDD | Seasons+ |
|--------|------|----------|-----|-----|--------|---------|------|-------|----------|
| S3 base everywhere | 584 | 65 | 44.2% | +6.3% | 0.424 | 2.2% | 6 | 23.5% | 7/9 |
| 1H strict only | 149 | 17 | 49.7% | +17.6% | 0.601 | 6.4% | 5 | 6.9% | 6/9 |
| 2H base only | 249 | 28 | 48.6% | +18.0% | 0.777 | 6.1% | 6 | 10.7% | 8/9 |
| **COMBINED** | **398** | **44** | **49.0%** | **+17.9%** | **0.983** | **6.2%** | **6** | **15.6%** | **8/9** |

Monthly: May +20%, Jun +25%, Jul +3%, Aug +16%, Sep +22%, Oct +43%.
PnL: $0 → +$7,112 on flat $100 bets over 9 seasons.
Only losing season: 2010 (-4.7%).

## 5. Open Questions

1. **Volume**: 44 bets/season may be too thin for Polymarket. Need additional systems (favorite-side, RL).
2. **July transition**: Jul +3% ROI — the ASG cutoff zone is weak. Could extend strict to full July.
3. **S1/S4 correlation**: If uncorrelated with S3, portfolio of systems increases volume.
4. **Favorite-side**: Was -2% ROI overall, but may have pockets with correct filters (similar to how MJ S3 was -4% before the key was found).

## Files Modified/Created

| File | Change |
|------|--------|
| `src/bullpen_features.py` | Dedup DH rows after aggregation |
| `src/features.py` | Safety dedup + integrity check; September filter removed |
| `scripts/analyze_divergence.py` | Bandaid → assertion |
| `scripts/loss_streak_analysis.py` | NEW — S3 streak anatomy + sub-filter search |
| `scripts/mayjune_dive.py` | NEW — May-June deep dive |
| `scripts/dual_regime_s3.py` | NEW — dual-regime backtest |
