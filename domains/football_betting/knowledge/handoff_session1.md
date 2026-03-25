# Football Betting — Session 1 Handoff

## What was done

### Phase 0: SSS Signal Validation
- Built football betting domain from scratch on Turkish Super Lig
- **Data sources**: football-data.co.uk (Pinnacle closing odds) + transfermarkt-datasets (lineups, minutes, goals, assists)
- **Weighted SSS**: `impact = max(minutes_share, goals_share, assists_share)`, two variants (cumulative + rolling-10)
- **Signal confirmed**: strong-lineup teams outperform implied odds by +5% at SSS differential > 0.15 (N=276 matches)
- Signal strongest in 0.15-0.20 contrast zone, weaker at extremes (market already prices obvious rotation)

### Phase 1: CatBoost Poisson Goals Model
- Predicts **goals per team** (not match outcome) — each match = 2 rows, model predicts λ (expected goals)
- From λ_home, λ_away → derive P(H/D/A), O/U, AH via Poisson convolution (`src/markets.py`)
- **29 features**: SSS (cum + r10), form (ppg, streak), attack/defense balance (gf_pg, ga_pg), congestion (days_rest, density), context (home, big3, matchday, overround)
- **12 seasons** (2012-2023), 3919 matches, 40 clubs mapped
- Walk-forward: train 2012-2020, val 2021, test 2022-2023

### Results (current baseline)
| Metric | Value |
|---|---|
| Goals MAE improvement vs naive | **+9.3%** |
| Poisson LL improvement | **+0.053** |
| Match RPS vs Pinnacle | **-6.2%** (worse) |
| Top features | is_home (15.5%), is_big3 (11.8%), opp_ppg_cum (7.6%), own_gf_pg_cum (6.6%), opp_ga_pg_cum (4.6%) |

## What's next: Phase 2 — Bias-Trained Ensemble

The model predicts goals better than naive (+9.3% MAE) but derives match probabilities worse than Pinnacle (-6.2% RPS). Independent Poisson assumption loses information (doesn't model correlation between teams' goals).

### Plan for bias-trained models

Train **multiple intentionally biased CatBoost models**, each specialized for a regime:

1. **Squad Disruption Model**: train only on matches where SSS_diff > 0.15 (one team significantly rotated). Uses only SSS + congestion features. Learns when lineup weakness matters most.

2. **Home Fortress Model**: train with overweighted home wins. Learns what makes home advantage especially strong in Turkish mid-table matches.

3. **Congestion Model**: train on matches where days_rest ≤ 3 for at least one team. Learns fatigue effects.

4. **Market Correction Model**: if opening odds are available (some seasons have them in the CSVs), train on matches with significant line movement. Learns where sharp money spotted mispricing.

### Implementation approach

Each biased model produces its own λ prediction. Ensemble combines via:
- **Meta-learner** (logistic regression or ridge) trained on validation set
- Input = all biased model λ predictions + baseline model λ
- Output = final λ_home, λ_away
- Isotonic calibration on top

### Key files

| File | Purpose |
|---|---|
| `src/data_loader.py` | Load + join odds + transfermarkt, 40 club IDs mapped |
| `src/features.py` | 29 features, `build_all_features()` + `build_team_level_dataset()` |
| `src/model.py` | CatBoost Poisson, walk-forward, RPS evaluation |
| `src/markets.py` | Poisson convolution: λ → P(H/D/A), O/U, AH |
| `scripts/run_model_training.py` | End-to-end pipeline |
| `scripts/run_sss_signal_test.py` | Phase 0 signal validation |

### Data quirks
- Season 2012 has 0 starter lineups in transfermarkt (appearances exist but no `starting_lineup` type) → SSS = NaN for 2012
- Some early CSVs have trailing NaN rows → handled with `dropna(subset=["home_team_raw"])`
- 2020 season: 420 matches (extended due to COVID), all others ~306-380
- `is_big3` (GS/FB/BJK) is the 2nd most important feature — consider excluding big-3 matches or building a separate model for them

### Open questions
- Should biased models predict λ (goals) or directly predict match probability?
- Bivariate Poisson (models correlation between home/away goals) may help with draw prediction — the biggest gap vs Pinnacle
- Asian Handicap closing odds are available in the CSV (PAHH/PAHA columns) — could be used for AH-specific evaluation
