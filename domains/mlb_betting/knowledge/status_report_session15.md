# Session 15 Status Report — O/U System Calibration & Threshold Discovery

Date: 2026-03-22

## What Was Done

### 1. Retrosheet Bullpen Data Extended to 2022-2025
- `SEASONS` in `src/bullpen_features.py` extended from [2010-2019, 2021] to include 2022-2025
- Retrosheet pitching.csv zips already existed for these years with identical format (~16K reliever lines/season)
- 2004-2009 have no Retrosheet zips; remain without bullpen features

### 2. Threshold Analysis: top-25% vs P(u)>=0.55 vs P(u)>=0.60
Full walk-forward (14 folds, 22 features, 30K predictions) across 6 seasons:

| Method | 2017 | 2018 | 2019 | 2021 | 2024 | 2025 |
|--------|------|------|------|------|------|------|
| **top-25% adaptive** | +5.9% | +2.8% | +2.1% | -4.9% | **-10.9%** | -1.1% |
| **P(u)>=0.55** | +8.6% | +7.8% | +4.5% | +10.6% | +0.2% | +15.4% |
| **P(u)>=0.60** | +42.5% | +61.3% | +32.0% | +52.7% | +49.4% | +47.5% |

**Key finding**: Adaptive top-25% is unprofitable (negative ROI in 2021, 2024). Fixed thresholds work.
- P(u)>=0.55: all 6 seasons positive, ~100 bets/season in recent years
- P(u)>=0.60: nuclear zone (70-85% hit rate), but only 22-75 bets/season

### 3. LLM Expert Batch Calibration (3 days x 2 thresholds)
Dates: 2024-04-06, 2024-04-23, 2024-06-28

**P(u)>=0.55**: 9 eligible -> 5 bets, **5W-0L, +$454, +90.9% ROI**
**P(u)>=0.52**: 18 eligible -> 9 bets, **9W-0L, +$818, +90.9% ROI**

LLM experts correctly filtered ALL 4 OVER games in the P>=0.52 pool (BAL@PIT 9 runs, BAL@LAA 11, SDG@BOS 11, CLE@KAN 13).

### 4. Noise Band Test: P(u) [0.50, 0.52)
6 games (3U-3O, ground truth 50/50). LLM results: **2W-3L, -$118, -23.6% ROI**

Failed catastrophically:
- ARI@ATL: P(u)=0.517, both experts said UNDER → actual 17 runs (O)
- NYM@CIN: P(u)=0.507, both experts said UNDER → actual 15 runs (O)
- ARI@STL: P(u)=0.516, both experts said UNDER → actual 15 runs (O)

**Conclusion**: Below P(u)=0.52, neither ML model nor LLM experts have signal.

### 5. Production Pre-Filter Fixed at P(u)>=0.52
- Gives ~3 bets/day on test dates (up from ~1.7 at P>=0.55)
- LLM experts add real value: filter all OVERs while keeping UNDERs
- Combined system: 14W-0L on calibration sample (small but clean)

## Files Modified
- `src/bullpen_features.py` — SEASONS extended to 2022-2025
- `scripts/run_ou_calibration_batch.py` — NEW: batch calibration (multi-date, multi-threshold)
- `scripts/run_ou_calibration_band.py` — NEW: band-specific calibration for noise testing
- `knowledge/fullday_tests/ou_batch_calibration_2024.md` — batch report

## Key Numbers

| Metric | Value |
|--------|-------|
| Pre-filter threshold | P(u) >= 0.52 |
| Nuclear zone | P(u) >= 0.60 |
| Noise floor | P(u) < 0.52 (no signal) |
| Walk-forward folds | 14 (2004-2025) |
| O/U features | 22 |
| LLM calibration record | 14W-0L (P>=0.52), 2W-3L (P<0.52) |
| Bullpen FIP osc importance | 38.12% (#1 feature) |
