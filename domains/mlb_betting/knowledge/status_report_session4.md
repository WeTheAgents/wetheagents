# Session 4 Status Report

> Previous: pitcher proxy features, train/test validation (series dogon +5.21% ROI OOS).
> This session: exhaustive testing of alternative markets (RL, F5, full-game ML), CatBoost planning.

---

## 1. What We Have (data + features recap)

### 1.1 Raw Data

| Parameter | Value |
|-----------|-------|
| Source | sports-statistics.com xlsx |
| Seasons | 2010-2019, 2021 (2020 excluded — COVID) |
| Raw games | 27,109 |
| After hard filters | 26,420 (removed: missing odds/pitcher, double-headers) |
| After betting filters | ~20,500 (removed: Colorado, September, extreme lines >300) |

Each game has: 9 inning scores per side, final scores, opening/closing ML odds, run line + odds, over/under + odds, pitcher codes for both starters.

### 1.2 Feature Pipeline

**Entry point:** `build_all_features(games, include_pitcher=True)` in `src/features.py`

Adds 67 features per game (35 team + 32 pitcher). All features use only data available BEFORE that game (no look-ahead). Computation time ~3 min for full dataset.

### 1.3 Team Features (35) — `src/features.py`

| Group | Features | Key Columns | Notes |
|-------|----------|-------------|-------|
| Win % | 10 | `wp_home`, `wp_away`, `wp_last10_*`, `wp_last20_*` | Cumulative + rolling window |
| Streak | 3 | `streak_home`, `streak_away`, `streak_diff` | Signed: +N = win streak, -N = loss |
| Runs per game | 8 | `rpg_home/away`, `rapg_home/away`, `*_last10` | Offense + defense production |
| RPI | 6 | `rpi_home`, `rpi_away`, `rpi_diff`, `sos_*` | 0.25×WP + 0.50×OWP + 0.25×OOWP |
| Differentials | 5 | `wp_diff`, `wp_last10_diff`, `rpg_diff`, `rapg_diff` | home - away |
| Meta | 3 | `games_played_home/away`, `games_played_min` | For early-season filter |

**RPI** — ключевая фича. Объединяет силу команды и силу расписания в одном числе. RPI diff >= 0.03 — порог для серии догон.

### 1.4 Pitcher Features (32) — `src/pitcher_features.py`

**Подход:** proxy-метрики из результатов матчей (не реальные WHIP/K/BB, т.к. их нет в данных).

**Per-pitcher (9 × 2 стороны = 18 columns):**

| Feature | Short (5) | Long (15) | Momentum | Что измеряет |
|---------|-----------|-----------|----------|-------------|
| Win Rate | `sp_wr_short` | `sp_wr_long` | `sp_wr_momentum` | Как часто команда побеждает со стартером |
| Runs Allowed | `sp_ra_short` | `sp_ra_long` | `sp_ra_momentum` | Сколько ранов пропускает (proxy ERA) |
| 1st Inn RA | `sp_fi_ra_short` | `sp_fi_ra_long` | `sp_fi_momentum` | Ранй в 1-м иннинге (для YRFI) |

Плюс `sp_hand` (R/L/None) и `sp_starts_total`.

**Composites (14 columns):**

| Feature | Column | Формула | Сила сигнала |
|---------|--------|---------|-------------|
| WR Long Diff | `sp_wr_long_diff` | home_sp - away_sp | **10.1pp spread, generalizes** |
| RA Long Diff | `sp_ra_long_diff` | home_sp - away_sp | **16.4pp spread, but doesn't generalize** |
| WR Short Diff | `sp_wr_short_diff` | home_sp - away_sp | Fair |
| WR Momentum Diff | `sp_wr_momentum_diff` | home - away | Weak (2.7pp) |
| 1st Inn RA Combined | `sp_fi_ra_combined` | (home + away) / 2 | Untested (for YRFI) |
| Quality Floor | `sp_quality_floor` | max(home_ra, away_ra) | Fair |
| Starts Diff | `sp_starts_diff` | home - away | Noise |

**Критически важно:**
- Группировка по (pitcher, team) — иначе ASANCHEZ-R (2 разных человека) ломает merge
- min_sample=3 стартов — до этого features = NaN
- Coverage: 89.8% игр с home_sp, 81.5% с обоими

### 1.5 Derived Odds (5 columns) — `src/data_loader.py`

| Column | Source | Example |
|--------|--------|---------|
| `home_decimal_odds` | home_close_ml → decimal | 1.91 |
| `away_decimal_odds` | away_close_ml → decimal | 1.91 |
| `home_implied_prob` | home_close_ml → probability | 0.524 |
| `away_implied_prob` | away_close_ml → probability | 0.476 |
| `home_is_favorite` | home_implied_prob > 0.5 | True |

### 1.6 Market Features — `src/market_builder.py`

| Market | Key Column | How Computed |
|--------|-----------|-------------|
| YRFI | `yrfi` | away_inn_1 + home_inn_1 > 0 |
| F5 Winner | `f5_winner` | Compare sum(inn_1..5) per side; 'home'/'away'/'push' |
| F5 Total | `f5_total` | Total runs in first 5 innings |
| Run Line Cover | `home_rl_cover` | home_margin >= 2 |
| Race to 3 | `race_to_3` | Inning-by-inning cumulative tracking |

---

## 2. What Was Tested This Session

### 2.1 Run Line Flat Bet (`scripts/run_runline_with_pitcher.py`)

**Идея:** Фаворит -1.5 (выигрывает 2+), Андердог +1.5 (проигрывает ≤1 или побеждает).

**Unified datasets:**
- All favorites -1.5: 10,936 bets (7,105 home fav + 3,831 away fav)
- All underdogs +1.5: 10,936 bets (3,831 home dog + 7,105 away dog)
- Away-side RL odds estimated via vig: away_imp = TOTAL_VIG(1.045) - home_rl_imp

**Результаты:**

| Config | N | Cover% | Avg Odds | ROI |
|--------|---|--------|----------|-----|
| Fav -1.5 baseline | 10,936 | 42.3% | 2.304 | **-4.25%** |
| Fav -1.5: RPI>=0.03 + RA<=0 + WR>=0.10 | 1,051 | 47.9% | 2.027 | **-5.43%** |
| Dog +1.5 baseline | 10,936 | 57.7% | 1.681 | **-4.37%** |
| Dog +1.5: RPI>=0.02 + WR>=0.10 | 309 | 63.1% | 1.537 | **-3.00%** |

**Train/Test:**

| Config | TRAIN ROI | TEST ROI | TEST N |
|--------|-----------|----------|--------|
| Fav -1.5: RPI>=0.03 + WR>=0.10 | -13.90% | -0.52% | 704 |
| Dog +1.5: RPI>=0.02 + WR>=0.10 | -8.25% | **+5.61%** | 117 |

**Вывод:** Единственный TEST+ конфиг (Dog +1.5 +5.61%) — всего 117 ставок при минусовом TRAIN. **Не надёжно.** Букмекер точно калибрует RL odds.

### 2.2 F5 Moneyline Flat Bet (`scripts/run_f5_moneyline.py`)

**Идея:** Ставим на фаворита выиграть первые 5 иннингов. Odds = full-game decimal - 0.10 (поправка на push/ничью).

**Ключевая проблема:** Push rate = 14.8%. Ничья после 5 иннингов в каждой ~7-й игре. Bet loses on push.

**Результаты — катастрофические:**

| Config | N | WR | Avg Odds | ROI |
|--------|---|-----|----------|-----|
| Fav F5 baseline | 17,608 | 48.2% | 1.613 | **-23.1%** |
| Fav F5: RPI>=0.02 + WR>=0.20 | 1,846 | 52.8% | 1.502 | **-21.3%** |
| Dog F5 baseline | 17,608 | 37.0% | 2.209 | **-19.8%** |

**Train/Test:** Все конфиги -19% до -25% на обоих сплитах. Robustness grid: **все 16 ячеек отрицательные** на TRAIN и TEST.

**Вывод:** F5 ML с нашим подходом к odds абсолютно не работает. При odds ~1.50 нужен WR >67% для breakeven. С push rate 14.8% фактический WR 48-54% — дыра в 13-19pp.

### 2.3 Full-Game Moneyline Flat Bet (`scripts/run_moneyline_flat.py`)

**Идея:** Обычная ставка на победителя матча. Реальные closing odds с обеих сторон.

**Результаты — самые интересные из трёх:**

| Config | N | WR | Avg Odds | ROI |
|--------|---|-----|----------|-----|
| Fav ML baseline | 17,608 | 57.0% | 1.713 | **-3.26%** |
| Fav ML: RPI>=0.03 + RA<=0 + WR>=0.10 | 1,565 | 63.5% | 1.585 | **-0.22%** |
| Fav ML: RPI>=0.05 | 933 | 63.7% | 1.588 | **+0.19%** |
| Dog ML: RPI>=0.02 | 2,004 | 53.3% | 2.115 | **+12.44%** |
| Dog ML: imp [0.45, 0.50) | 6,061 | 47.6% | 2.115 | **+0.64%** |

**Train/Test:**

| Config | TRAIN ROI | TEST ROI | TEST N |
|--------|-----------|----------|--------|
| Fav ML: RPI>=0.03 + WR>=0.10 | -2.87% | **+3.10%** | 697 |
| Fav ML: RPI>=0.04 + WR>=0.10 | -4.99% | **+3.71%** | 431 |
| Fav ML: RPI>=0.05 + WR>=0.10 | -5.51% | **+4.00%** | 256 |
| Dog ML: RPI>=0.02 + WR>=0.10 | -8.03% | **+12.89%** | 133 |

**Robustness grid Fav ML (RPI × SP_WR):**
- TRAIN: хаос — 8 из 16 ячеек в плюсе, нет монотонного тренда
- TEST: тоже хаос — 8 из 16 в плюсе

**Вывод:** ML flat ближе всего к breakeven. TEST показывает +3-4% ROI, но:
- TRAIN отрицательный для ВСЕХ конфигов — edge не подтверждён двусторонне
- Grid хаотичен (ср. с series dogon: 16/16 ячеек в плюсе)
- Вероятно TEST+ = structural shift 2018+ (shorter odds, different market)

---

## 3. Summary Table — All Strategies Tested

| Strategy | Market | Best Overall ROI | TRAIN | TEST | Verdict |
|----------|--------|-----------------|-------|------|---------|
| **Series Dogon + pitcher** | ML (martingale) | **+3.07%** | **+1.75%** | **+5.21%** | **WORKS** |
| RL Fav -1.5 | Run Line | -5.43% | -13.90% | -0.52% | Not viable |
| RL Dog +1.5 | Run Line | -3.00% | -8.25% | +5.61% (117) | Unreliable |
| F5 ML Fav | First 5 | -21.3% | -24% | -21% | Catastrophic |
| F5 ML Dog | First 5 | -19.8% | -19% | -23% | Catastrophic |
| Full ML Fav | Moneyline | -0.22% | -2.87% | +3.10% (697) | Near breakeven |
| Full ML Dog | Moneyline | +12.44%* | -8.03% | +12.89% (133) | Unreliable |

*Full ML Dog +12.44% only for RPI>=0.02 filter (2,004 bets full sample — but doesn't survive train/test).

**Единственная стратегия с двусторонней (TRAIN+TEST) прибылью: Series Dogon + pitcher features.**

---

## 4. Scripts Inventory (updated)

```
scripts/
├── run_series_backtest.py          # Baseline series dogon (no filters)
├── run_series_with_features.py     # Series dogon + RPI/WP/streak filters
├── run_series_with_pitcher.py      # Series dogon + pitcher proxy layer
├── run_series_deep_analysis.py     # Granular: WR by game#, drawdown, streaks
├── run_train_test_validation.py    # Train/test split (champion config)
├── run_streak_analysis.py          # Win/loss streak patterns
├── run_runline_analysis.py         # RL baselines (RPI only)
├── run_runline_real_odds.py        # RL with actual data odds
├── run_runline_with_pitcher.py     # RL + pitcher features (fav -1.5, dog +1.5)
├── run_f5_moneyline.py             # F5 ML flat bet (odds - 0.10 discount)
└── run_moneyline_flat.py           # Full-game ML flat bet (fav + dog)
```

---

## 5. What Remains

| # | Task | Priority | Status |
|---|------|----------|--------|
| 1 | YRFI with first inning RA | Medium | Not started |
| 2 | **CatBoost ML with 67 features** | **High** | **Planning** |
| 3 | pybaseball pitcher data upgrade | Low | Deferred |
| 4 | `src/rules.py` expert rules | Low | Deferred |
| 5 | LLM estimator | Low | Deferred |
