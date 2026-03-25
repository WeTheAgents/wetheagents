# Phase 0 — SSS Signal Validation Report

## Dataset
- Matches: 1073
- Seasons: [np.int64(2021), np.int64(2022), np.int64(2023)]
- Teams: 25

## SSS Coverage

|   season |   matches | sss_cum_coverage   | sss_r10_coverage   |
|---------:|----------:|:-------------------|:-------------------|
|     2021 |       380 | 360/380 (95%)      | 360/380 (95%)      |
|     2022 |       313 | 294/313 (94%)      | 294/313 (94%)      |
|     2023 |       380 | 360/380 (95%)      | 360/380 (95%)      |

## Cumulative SSS — Team-Level Bucket Analysis

|   bucket |   n |   mean_sss |   implied_win% |   actual_win% |   delta_win% |   implied_ppg |   actual_ppg |   delta_ppg |
|---------:|----:|-----------:|---------------:|--------------:|-------------:|--------------:|-------------:|------------:|
|        0 | 406 |     0.528  |           37.1 |          34.7 |         -2.3 |         1.362 |        1.271 |      -0.091 |
|        1 | 405 |     0.6226 |           35.9 |          35.8 |         -0.1 |         1.331 |        1.316 |      -0.015 |
|        2 | 406 |     0.6824 |           38.8 |          41.9 |          3.1 |         1.414 |        1.498 |       0.084 |
|        3 | 405 |     0.7576 |           38.4 |          42.5 |          4.1 |         1.402 |        1.509 |       0.107 |
|        4 | 406 |     0.8968 |           37   |          35   |         -2   |         1.362 |        1.31  |      -0.052 |

## Cumulative SSS — Differential Analysis (Home - Away)

|   bucket |   n |   mean_sss_diff |   implied_home_win% |   actual_home_win% |   delta% |
|---------:|----:|----------------:|--------------------:|-------------------:|---------:|
|        0 | 203 |         -0.1675 |                46   |               49.3 |      3.2 |
|        1 | 202 |         -0.0464 |                44.7 |               46.5 |      1.8 |
|        2 | 203 |          0.0226 |                43.9 |               41.4 |     -2.5 |
|        3 | 202 |          0.091  |                43.3 |               45.5 |      2.2 |
|        4 | 203 |          0.2178 |                43.3 |               50.2 |      6.9 |

## Rolling-10 SSS — Team-Level Bucket Analysis

|   bucket |   n |   mean_sss |   implied_win% |   actual_win% |   delta_win% |   implied_ppg |   actual_ppg |   delta_ppg |
|---------:|----:|-----------:|---------------:|--------------:|-------------:|--------------:|-------------:|------------:|
|        0 | 406 |     0.5451 |           36.7 |          35.5 |         -1.2 |         1.351 |        1.296 |      -0.056 |
|        1 | 405 |     0.6431 |           36.7 |          37.5 |          0.9 |         1.354 |        1.37  |       0.016 |
|        2 | 406 |     0.6995 |           38.7 |          40.6 |          2   |         1.41  |        1.461 |       0.051 |
|        3 | 405 |     0.7695 |           38.2 |          41   |          2.8 |         1.395 |        1.462 |       0.067 |
|        4 | 406 |     0.8992 |           36.9 |          35.2 |         -1.7 |         1.36  |        1.315 |      -0.045 |

## Rolling-10 SSS — Differential Analysis (Home - Away)

|   bucket |   n |   mean_sss_diff |   implied_home_win% |   actual_home_win% |   delta% |
|---------:|----:|----------------:|--------------------:|-------------------:|---------:|
|        0 | 203 |         -0.166  |                46.2 |               50.2 |      4.1 |
|        1 | 202 |         -0.0478 |                45.3 |               49.5 |      4.2 |
|        2 | 203 |          0.0199 |                43.1 |               39.4 |     -3.6 |
|        3 | 202 |          0.0861 |                43.3 |               43.1 |     -0.3 |
|        4 | 203 |          0.2203 |                43.3 |               50.7 |      7.4 |

## Interpretation

- **delta_win% < 0 in low SSS buckets**: teams with weakened squads underperform their odds → signal exists
- **delta_win% > 0 in high SSS buckets**: teams with full-strength squads outperform their odds → signal exists
- **Spearman p < 0.05**: statistically significant monotonic relationship
- **Spearman p < 0.10**: worth investigating further
- **Spearman p > 0.10**: no signal detected