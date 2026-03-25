# Phase 2 — Bias-Trained Ensemble Report

## Configuration
- Train: [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020]
- Val: [2021]
- Test: [2022, 2023]
- Baseline features: 29
- Biased models trained: 4

## Tuning Results
- Meta-learner alpha (home): 26.366508987303554
- Meta-learner alpha (away): 12.742749857031322
- Bivariate Poisson ρ: 0.220

## Biased Model Training

| Model | Training Rows | Features |
|---|---|---|
| squad_disruption | 1332 | 9 |
| home_fortress | 5692 | 29 |
| congestion | 188 | 12 |
| market_correction | 2965 | 31 |

## Goals Prediction (Test Set)

| Model | MAE | vs Naive |
|---|---|---|
| Baseline | 0.938 | 9.3% |
| **Ensemble** | **0.955** | **7.6%** |

## Match Outcome RPS (Test Set)

| Model | RPS | Pinnacle | vs Pinnacle |
|---|---|---|---|
| Baseline | 0.1361 | 0.1282 | -6.2% |
| Ensemble (independent) | 0.1372 | 0.1282 | -7.1% |
| **Ensemble (bivariate rho=0.22)** | **0.1367** | 0.1282 | **-6.6%** |

## Meta-Learner Coefficients

| Model | Home coef | Away coef |
|---|---|---|
| baseline | +0.084 | +0.398 |
| congestion | +0.158 | +0.207 |
| home_fortress | +0.104 | +0.320 |
| market_correction | +0.276 | +0.358 |
| squad_disruption | +0.028 | -0.006 |
| *intercept* | +0.603 | -0.339 |