# Repeat-Series Signal Analysis (ML/RL)

Generated: 2026-04-20 09:58 UTC

## Bottom Line

- After a first win, next-game repeats look **no evidence of strengthening**: 127 transitions, 60.6% success, 28.2% ROI versus pooled repeat baseline 62.6% / 30.0%.
- After a first loss, the practical read is **treat cautiously**: 84 transitions, 65.5% success, 32.6% ROI.
- After prior wins, the market did not meaningfully shorten the repeated team; team ML implied prob moved -0.003 and signal odds moved -0.051.
- Rule impact: No rule change yet. Keep repeat-series context as a note, not a staking override.

## Sample

- Raw signal rows: 1218
- Team-level signal rows: 931
- Next-game repeat transitions: 211
- G1→G2 transitions: 92
- G2→G3 transitions: 100

## Performance

| Slice | n | Success | ROI | Avg Odds | Wilson CI | ROI CI |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Repeat baseline | 211 | 62.6% | 30.0% | 2.05 | 55.9% to 68.8% | 15.6% to 43.3% |
| After first win | 127 | 60.6% | 28.2% | 2.07 | 51.9% to 68.7% | 9.9% to 47.4% |
| After first loss | 84 | 65.5% | 32.6% | 2.03 | 54.8% to 74.8% | 9.4% to 54.5% |
| G1→G2 | 92 | 62.0% | 33.2% | 2.07 | 51.7% to 71.2% | 12.4% to 54.3% |
| G2→G3 | 100 | 64.0% | 26.5% | 2.04 | 54.2% to 72.7% | 6.2% to 46.9% |
| Same-strategy repeat | 100 | 60.0% | 23.4% | 2.07 | 50.2% to 69.1% | 2.5% to 43.2% |
| ML-only | 48 | 52.1% | 22.1% | 2.36 | 38.3% to 65.5% | -10.5% to 54.9% |
| RL-only | 112 | 67.0% | 33.9% | 1.92 | 57.8% to 75.0% | 15.2% to 53.3% |
| Single-support | 181 | 61.9% | 26.6% | 2.05 | 54.6% to 68.6% | 11.1% to 42.3% |
| Multi-support | 30 | 66.7% | 48.7% | 2.05 | 48.8% to 80.8% | 15.7% to 79.1% |
| Original first signal baseline | 211 | 60.2% | 26.9% | 2.10 | 53.5% to 66.6% | 12.4% to 41.8% |

## Mechanism

### After First Win

| Feature delta (second minus first) | Mean | Median |
| --- | ---: | ---: |
| Team ML implied prob | -0.003 | 0.000 |
| Signal odds | -0.051 | 0.000 |
| Diff wp_last10 | 0.071 | 0.100 |
| Diff rpg_last10 | 0.374 | 0.300 |
| Diff rapg_last10 | -0.359 | -0.300 |
| Diff bp_ip_3d | -1.247 | -1.000 |
| Diff bp_fip_short | -0.129 | -0.205 |
| Diff sp_fip_short | -0.055 | 0.069 |
| Diff sp_ip_per_start_short | 0.050 | -0.067 |

### After First Loss

| Feature delta (second minus first) | Mean | Median |
| --- | ---: | ---: |
| Team ML implied prob | -0.001 | 0.005 |
| Signal odds | -0.037 | -0.040 |
| Diff wp_last10 | -0.095 | -0.100 |
| Diff rpg_last10 | -0.386 | -0.250 |
| Diff rapg_last10 | 0.391 | 0.400 |
| Diff bp_ip_3d | -0.583 | -0.667 |
| Diff bp_fip_short | 0.356 | 0.372 |
| Diff sp_fip_short | 0.071 | 0.083 |
| Diff sp_ip_per_start_short | -0.246 | -0.367 |

## Robustness

Regularized logistic regression on 211 transitions gives `prior_win` coef -0.230 (odds ratio 0.795).
