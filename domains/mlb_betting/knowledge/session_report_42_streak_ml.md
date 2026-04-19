# Session 42 -- Streak ML Momentum

**Date**: 2026-04-18
**Scope**: ML-only streak continuation, market-pricing, and narrow edge search.
**Headline verdict**: **no validated streak ml champion**.

## TL;DR

- Main slice `2015-2025`: after `W3+`, team WR = **53.2%**; after `L3+`, team WR = **46.6%**.
- Pricing check: `W3+` back ROI = **-2.60%**. `L3+` fade ROI = **-2.85%**, but fade actual-minus-implied = **-1.46pp**.
- Candidate scan: 20496 eligible combos, 139 shortlisted, 89 discovery gate passers, 0 validated survivors.

## Best candidate

- `fade_cold | L3+ | opp_flat | Jun-Jul`
- Discovery ROI: **+10.67%** on N=471
- Frozen 2024 ROI: **-4.09%** on N=59
- Live 2025 ROI: **+23.94%** on N=65

## Reasons not to promote

- hot teams win a bit more often, but backing them remains negative after price
- fading cold teams is directionally better than backing them, but still not enough to clear vig
- no discovery candidate survives frozen 2024 and live-forward 2025 checks

## Top discovery rows by thesis

### back_hot
- `back_hot | W2+ | [0.45,0.55) | <.500 | opp_cold | Apr-May` -> N=93, ROI=+25.60%, actual-minus-implied=+12.90pp, gate=PASS
- `back_hot | W2+ | away | [0.35,0.45) | opp_cold | Aug-Sep` -> N=202, ROI=+23.00%, actual-minus-implied=+9.18pp, gate=PASS
- `back_hot | W2+ | underdog | away | [0.35,0.45) | opp_cold | Aug-Sep` -> N=202, ROI=+23.00%, actual-minus-implied=+9.18pp, gate=PASS
### fade_hot
- `fade_hot | W6+ | home | [0.65,0.75) | opp_cold` -> N=66, ROI=+41.77%, actual-minus-implied=+13.37pp, gate=PASS
- `fade_hot | W6+ | home | [0.65,0.75) | >=.500 | opp_cold` -> N=66, ROI=+41.77%, actual-minus-implied=+13.37pp, gate=PASS
- `fade_hot | W6+ | favorite | home | [0.65,0.75) | opp_cold` -> N=66, ROI=+41.77%, actual-minus-implied=+13.37pp, gate=PASS
### back_cold
- `back_cold | L4+ | underdog | away | [0.45,0.55) | Apr-May` -> N=97, ROI=+24.40%, actual-minus-implied=+11.59pp, gate=PASS
- `back_cold | L4+ | underdog | away | [0.45,0.55) | <.500 | Apr-May` -> N=97, ROI=+24.40%, actual-minus-implied=+11.59pp, gate=PASS
- `back_cold | L6+ | home | Aug-Sep` -> N=119, ROI=+21.75%, actual-minus-implied=+9.60pp, gate=PASS
### fade_cold
- `fade_cold | L3+ | away | [0.65,0.75)` -> N=60, ROI=+45.53%, actual-minus-implied=+16.26pp, gate=PASS
- `fade_cold | L3+ | favorite | away | [0.65,0.75)` -> N=60, ROI=+45.53%, actual-minus-implied=+16.26pp, gate=PASS
- `fade_cold | L4+ | [0.55,0.65) | opp_flat | Jun-Jul` -> N=57, ROI=+31.04%, actual-minus-implied=+13.04pp, gate=PASS
