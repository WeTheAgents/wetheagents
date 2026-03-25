# Phase 1 — CatBoost Poisson Goals Model Report

## Configuration
- Train: [2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020], Val: [2021], Test: [2022, 2023]
- Features: 29
- CatBoost iterations: 500

## Goals Prediction

| Set | MAE | Naive MAE | Improvement | Poisson LL | Naive LL |
|---|---|---|---|---|---|
| Val | 0.907 | 0.967 | 6.2% | -1.4785 | -1.5071 |
| Test | 0.938 | 1.034 | 9.3% | -1.5032 | -1.5558 |

## Match Outcome (RPS)

| Set | Model RPS | Pinnacle RPS | Improvement |
|---|---|---|---|
| Val | 0.1438 | 0.1375 | -4.6% |
| Test | 0.1361 | 0.1282 | -6.2% |

## Top Features

| Feature | Importance |
|---|---|
| is_home | 15.5 |
| is_big3 | 11.8 |
| opp_ppg_cum | 7.6 |
| own_gf_pg_cum | 6.6 |
| opp_ga_pg_cum | 4.6 |
| own_goal_diff_cum | 4.2 |
| opp_sss_r10 | 4.0 |
| opp_ga_pg_r5 | 3.3 |
| opp_sss_cum | 3.2 |
| own_ga_pg_r5 | 3.1 |