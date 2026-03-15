# CatBoost ML Plan

## 1. Why CatBoost

### 1.1 Что уже попробовали и почему ML — следующий шаг

Rules-based подход (серия догон с ручными фильтрами) работает: +5.21% ROI out-of-sample. Но:

- **Ручные фильтры линейны.** RPI >= 0.03 AND SP_WR >= 0.10 — это прямоугольные отсечки в пространстве фич. Реальная граница прибыльности может быть нелинейной (например: при высоком RPI достаточно среднего SP_WR, а при низком RPI нужен экстремально хороший питчер).

- **67 фич, а используем 4.** Из 67 фич в series dogon задействованы только rpi_diff, wp_diff, sp_ra_long_diff, sp_wr_long_diff. Остальные 63 фичи могут содержать дополнительный сигнал, который невозможно найти ручным перебором.

- **Interactions.** CatBoost автоматически находит взаимодействия: "домашний питчер с RA < 3.0 + away_team на losing streak + implied prob > 0.60" — такие комбинации невозможно перебрать руками.

### 1.2 Почему именно CatBoost, а не XGBoost / LightGBM / нейросеть

| Критерий | CatBoost | Альтернативы |
|----------|----------|-------------|
| NaN handling | Built-in (наши pitcher features ~18% NaN) | XGB/LGB require imputation |
| Categorical features | Native support (`sp_hand` = R/L/None) | Require encoding |
| Overfitting protection | Ordered boosting + built-in regularization | Standard |
| Small datasets | Good (26K games — не big data) | Neural nets need more data |
| Interpretability | Feature importance + SHAP | Similar |
| Speed | Fast on CPU | LGB faster, XGB slower |

Главное: **native NaN handling** — у нас ~18% игр без pitcher features (< 3 стартов), и CatBoost обработает это без костылей.

---

## 2. Task Formulation

### 2.1 Что предсказываем

**Три варианта постановки задачи:**

#### Option A: Binary Classification — "Home Win" (baseline)
- **Target:** `home_win` (0 or 1)
- **Output:** P(home_win) — вероятность победы дома
- **Плюсы:** Прямой target, максимум данных (все 20K+ игр)
- **Минусы:** Предсказание P(home) ≠ "на кого ставить" (нужно сравнить с implied prob)

#### Option B: Binary Classification — "Favorite Wins"
- **Target:** `fav_win` (0 or 1) — фаворит по closing line побеждает
- **Features:** Нормализованные (fav_rpi, fav_sp_wr, etc. — всегда с perspective фаворита)
- **Плюсы:** Прямо отвечает на вопрос "ставить ли на фаворита"
- **Минусы:** Теряем home/away asymmetry

#### Option C: Regression — "Fair Probability"
- **Target:** `home_win` (0 or 1), но оптимизируем LogLoss / Brier Score
- **Output:** calibrated P(home_win)
- **Bet signal:** `edge = P_model(home) - implied_prob(home)`. Если edge > threshold → bet.
- **Плюсы:** Самый правильный подход. Напрямую оцениваем "fair odds" и сравниваем с рынком.
- **Минусы:** Требует хорошую калибровку

**Рекомендация: Option C (regression / calibrated probabilities).** Это позволяет:
1. Ставить на home ИЛИ away, если edge достаточный
2. Sizing пропорционально edge (Kelly criterion)
3. Одна модель для всех рынков (ML, RL, F5 — везде нужна P(home))

### 2.2 Edge Framework

```
P_model = CatBoost prediction (probability that home team wins)
P_market = home_implied_prob (from closing moneyline)

edge_home = P_model - P_market
edge_away = (1 - P_model) - (1 - P_market) = P_market - P_model  [= -edge_home]

if edge_home > THRESHOLD:
    bet HOME at home_decimal_odds
elif edge_away > THRESHOLD (i.e. edge_home < -THRESHOLD):
    bet AWAY at away_decimal_odds
else:
    no bet
```

**THRESHOLD** — ключевой гиперпараметр. Чем выше → меньше ставок, выше ROI, но больше variance. Типичные значения: 0.02-0.08.

---

## 3. Feature Matrix

### 3.1 Полный список фич для модели

67 features, разделённые по категориям. Все числовые, кроме `sp_hand` (categorical).

#### Team Strength (11 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 1 | Home RPI | `rpi_home` | float | 0.3-0.7 | Strongest team metric |
| 2 | Away RPI | `rpi_away` | float | 0.3-0.7 | |
| 3 | RPI Diff | `rpi_diff` | float | -0.3 to +0.3 | Positive = home stronger |
| 4 | Home SOS | `sos_home` | float | 0.4-0.6 | Strength of schedule |
| 5 | Away SOS | `sos_away` | float | 0.4-0.6 | |
| 6 | Home WP | `wp_home` | float | 0.2-0.8 | Cumulative win % |
| 7 | Away WP | `wp_away` | float | 0.2-0.8 | |
| 8 | WP Diff | `wp_diff` | float | -0.5 to +0.5 | |
| 9 | Home WP Last 10 | `wp_last10_home` | float | 0-1 | Recent form |
| 10 | Away WP Last 10 | `wp_last10_away` | float | 0-1 | |
| 11 | WP Last 10 Diff | `wp_last10_diff` | float | -1 to +1 | |

#### Offense/Defense (6 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 12 | Home RPG | `rpg_home` | float | 2-8 | Runs scored per game |
| 13 | Away RPG | `rpg_away` | float | 2-8 | |
| 14 | Home RAPG | `rapg_home` | float | 2-8 | Runs allowed per game |
| 15 | Away RAPG | `rapg_away` | float | 2-8 | |
| 16 | RPG Diff | `rpg_diff` | float | -4 to +4 | Offensive edge |
| 17 | RAPG Diff | `rapg_diff` | float | -4 to +4 | Defensive edge |

#### Streaks (3 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 18 | Home Streak | `streak_home` | int | -10 to +10 | Signed streak |
| 19 | Away Streak | `streak_away` | int | -10 to +10 | |
| 20 | Streak Diff | `streak_diff` | int | -20 to +20 | |

#### Pitcher Win Rate (6 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 21 | Home SP WR Short | `home_sp_wr_short` | float | 0-1 | Last 5 starts |
| 22 | Home SP WR Long | `home_sp_wr_long` | float | 0-1 | Last 15 starts |
| 23 | Away SP WR Short | `away_sp_wr_short` | float | 0-1 | |
| 24 | Away SP WR Long | `away_sp_wr_long` | float | 0-1 | |
| 25 | SP WR Long Diff | `sp_wr_long_diff` | float | -1 to +1 | **Key predictor** |
| 26 | SP WR Short Diff | `sp_wr_short_diff` | float | -1 to +1 | |

#### Pitcher Runs Allowed (6 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 27 | Home SP RA Short | `home_sp_ra_short` | float | 0-10 | Last 5 starts |
| 28 | Home SP RA Long | `home_sp_ra_long` | float | 0-10 | Last 15 starts |
| 29 | Away SP RA Short | `away_sp_ra_short` | float | 0-10 | |
| 30 | Away SP RA Long | `away_sp_ra_long` | float | 0-10 | |
| 31 | SP RA Long Diff | `sp_ra_long_diff` | float | -8 to +8 | **Strongest single signal (16.4pp)** |
| 32 | SP RA Short Diff | `sp_ra_short_diff` | float | -8 to +8 | |

#### Pitcher Momentum (4 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 33 | Home SP WR Momentum | `home_sp_wr_momentum` | float | -1 to +1 | Short - Long |
| 34 | Away SP WR Momentum | `away_sp_wr_momentum` | float | -1 to +1 | |
| 35 | SP WR Momentum Diff | `sp_wr_momentum_diff` | float | -2 to +2 | Weak signal |
| 36 | SP RA Momentum Diff | `sp_ra_momentum_diff` | float | -10 to +10 | Weak signal |

#### Pitcher First Inning (4 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 37 | Home SP FI RA Short | `home_sp_fi_ra_short` | float | 0-4 | 1st inning ERA proxy |
| 38 | Home SP FI RA Long | `home_sp_fi_ra_long` | float | 0-4 | |
| 39 | Away SP FI RA Short | `away_sp_fi_ra_short` | float | 0-4 | |
| 40 | Away SP FI RA Long | `away_sp_fi_ra_long` | float | 0-4 | |

#### Pitcher Meta (6 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 41 | SP FI RA Combined | `sp_fi_ra_combined` | float | 0-4 | Avg 1st inn RA (for YRFI) |
| 42 | SP FI Momentum Diff | `sp_fi_momentum_diff` | float | -4 to +4 | |
| 43 | SP Quality Floor | `sp_quality_floor` | float | 0-10 | Worst RA of the two |
| 44 | SP Starts Diff | `sp_starts_diff` | int | -200 to +200 | Experience delta |
| 45 | Home SP Hand | `home_sp_hand` | cat | R/L/None | Categorical |
| 46 | Away SP Hand | `away_sp_hand` | cat | R/L/None | Categorical |

#### Market / Odds (5 features)
| # | Feature | Column | Type | Range | Notes |
|---|---------|--------|------|-------|-------|
| 47 | Home Implied Prob | `home_implied_prob` | float | 0.2-0.8 | Market's estimate |
| 48 | Away Implied Prob | `away_implied_prob` | float | 0.2-0.8 | |
| 49 | Home Decimal Odds | `home_decimal_odds` | float | 1.1-5.0 | |
| 50 | Away Decimal Odds | `away_decimal_odds` | float | 1.1-5.0 | |
| 51 | Close O/U | `close_ou` | float | 5.5-13.0 | Total line |

#### Context (up to 16 features, optional)
| # | Feature | Column | Type | Notes |
|---|---------|--------|------|-------|
| 52 | Season | `season` | int | 2010-2021, for trend |
| 53 | Month | `month` | int | 4-9 |
| 54 | Games Played Home | `games_played_home` | int | 1-162 |
| 55 | Games Played Away | `games_played_away` | int | 1-162 |
| 56 | Games Played Min | `games_played_min` | int | 1-162 |
| 57-67 | WP splits, WP last20, etc. | various | float | Secondary features |

**Total: 51 core + ~16 secondary = 67 features.**

### 3.2 Какие фичи НЕ включаем (и почему)

| Feature | Reason |
|---------|--------|
| `home_team`, `away_team` | Leakage — team identity меняется (ростер, тренер). Используем только rolling metrics. |
| `home_pitcher`, `away_pitcher` | Leakage — pitcher identity уже captured через rolling features. |
| `date` (raw) | Leakage. Month и games_played достаточно. |
| `matchup_key` | Too sparse (900 unique matchups), overfitting risk |
| `home_win` | Target variable! |
| Future-looking columns | `home_final`, `away_final`, inning scores — outcome data |

### 3.3 NaN Policy

| Feature Group | NaN Rate | CatBoost Handling |
|--------------|----------|-------------------|
| Team features (RPI, WP, etc.) | ~0% after game 20 | `games_played_min >= 20` filter |
| Pitcher short window | ~25% | Native NaN in CatBoost |
| Pitcher long window | ~18% | Native NaN in CatBoost |
| Pitcher hand (2021) | ~69% for 2021 | CatBoost treats None as category |

CatBoost learns optimal NaN splits automatically. Imputation unnecessary.

---

## 4. Experimental Design

### 4.1 Train / Validation / Test Split

Temporal split (no shuffle — time-series data):

```
TRAIN:      2010-2015  (~14,000 games)   — fit model
VALIDATION: 2016-2017  (~4,500 games)    — tune hyperparameters + threshold
TEST:       2018-2019, 2021 (~7,500 games) — final evaluation (touch ONCE)
```

**Почему именно так:**
- Series dogon уже валидирован на 2018-2021 → используем тот же TEST для сравнения
- VALIDATION (2016-2017) для подбора threshold и early stopping — не трогаем TEST до финала
- Минимум 5 сезонов в TRAIN для устойчивости rolling features (RPI, pitcher)
- 2021 в TEST (не VALIDATION) — другая эпоха (post-COVID rules)

**Альтернатива:** Walk-forward (expanding window). Более robust, но сложнее и медленнее.

### 4.2 Метрики

#### Model Quality Metrics
| Metric | What It Measures | Target |
|--------|-----------------|--------|
| **LogLoss** | Calibration of probabilities | < 0.680 (random = 0.693) |
| **Brier Score** | MSE of probabilities | < 0.245 |
| **AUC-ROC** | Discrimination power | > 0.55 (hard problem!) |
| **Calibration plot** | P_predicted vs P_actual | Diagonal line = good |

**Важно:** AUC > 0.55 — это уже хорошо для спортивных ставок. Рынок efficient, даже 0.52-0.53 может быть прибыльным при правильном threshold.

#### Betting Metrics (главные)
| Metric | Formula | Target |
|--------|---------|--------|
| **ROI** | sum(P&L) / sum(stakes) | > 0% |
| **Yield** | ROI, same thing | > 2% desirable |
| **Sharpe** | mean(daily_pnl) / std(daily_pnl) | > 0.5 |
| **Max Drawdown** | Deepest peak-to-trough | < 30% of bankroll |
| **Bet Count** | Number of bets placed | > 500 for stat significance |
| **CLV** | Closing Line Value | P_model - P_closing > 0 |

### 4.3 Backtesting Protocol

```
For each game in TEST set (chronological order):
    1. Compute features using only past data (already done in build_all_features)
    2. Predict P(home_win) with trained model
    3. Calculate edge: edge = P_model - P_market
    4. If |edge| > THRESHOLD:
        - Bet on the side with positive edge
        - Stake = flat (or Kelly-sized)
        - Record outcome + P&L
    5. Aggregate: ROI, Sharpe, drawdown, calibration
```

---

## 5. Hyperparameters & Training Plan

### 5.1 CatBoost Key Hyperparameters

| Parameter | Starting Value | Search Range | Notes |
|-----------|---------------|-------------|-------|
| `iterations` | 1000 | 500-3000 | With early_stopping_rounds |
| `learning_rate` | 0.05 | 0.01-0.1 | Lower = more iterations needed |
| `depth` | 6 | 4-8 | Deeper = more interactions, overfitting risk |
| `l2_leaf_reg` | 5 | 1-10 | Regularization strength |
| `min_data_in_leaf` | 50 | 20-200 | Prevents overfitting to small groups |
| `random_strength` | 1.0 | 0.5-2.0 | Exploration in split selection |
| `bagging_temperature` | 1.0 | 0.5-2.0 | Row sampling randomness |
| `border_count` | 128 | 64-254 | Quantization bins |
| `loss_function` | `Logloss` | — | Binary classification |
| `eval_metric` | `Logloss` | Also track AUC, Brier | |
| `early_stopping_rounds` | 100 | 50-200 | Stop if VALIDATION doesn't improve |
| `cat_features` | [home_sp_hand, away_sp_hand] | — | Categorical columns |

### 5.2 Training Steps

1. **Baseline model** — default CatBoost params, all 67 features → establish floor
2. **Feature selection** — remove low-importance features (< 1% total importance)
3. **Hyperparameter tuning** — Optuna on VALIDATION LogLoss (50-100 trials)
4. **Threshold optimization** — sweep THRESHOLD 0.01-0.10 on VALIDATION ROI
5. **Final evaluation** — best model + threshold on TEST → one-shot, no going back

### 5.3 Anti-Overfitting Measures

| Measure | Implementation |
|---------|---------------|
| Temporal split (no shuffle) | TRAIN < VALID < TEST chronologically |
| Early stopping on VALIDATION | Stop when LogLoss stops improving |
| L2 regularization | `l2_leaf_reg` > 1 |
| Minimum leaf size | `min_data_in_leaf` >= 50 |
| Feature importance filter | Drop noisy features |
| Threshold not on TEST | Optimize on VALIDATION, evaluate once on TEST |
| No team/pitcher identity | Prevents memorizing specific rosters |
| Season not as feature (optional) | Prevents fitting to season-specific patterns |

---

## 6. Expected Outcomes

### 6.1 Realistic Expectations

**Model quality:**
- AUC-ROC: 0.53-0.57 (modest). Sports betting is hard — even Vegas lines have AUC ~0.58
- LogLoss: 0.676-0.685 (slightly better than coin flip / market baseline)
- The model must beat the MARKET (closing line), not a random baseline

**Betting profitability:**
- If model finds 1-3% edge over market → ROI +2-5% on filtered bets
- If model just recombines our known features → ROI ~0% (no improvement over rules)
- If model overfits → TRAIN looks great, TEST is negative

**Bet volume:**
- At THRESHOLD = 0.03: expect ~3000-5000 bets per season
- At THRESHOLD = 0.05: expect ~1000-2000 bets per season
- At THRESHOLD = 0.08: expect ~200-500 bets per season (higher ROI, more variance)

### 6.2 How CatBoost Could Add Value (vs. Rules)

| Scenario | What CatBoost Finds | Expected Impact |
|----------|-------------------|----------------|
| Non-linear interactions | "RPI 0.02 + SP_WR 0.25 = good" but "RPI 0.02 + SP_WR 0.10 = bad" | +1-2% ROI |
| Undervalued features | streak, rpg, rapg, first_inn_ra matter in combinations | +0.5-1% ROI |
| Market inefficiency detection | Spots when market over/under-values home advantage | +1-2% ROI |
| Pitcher NaN signal | "Unknown pitcher" = bullpen game = undervalued dog | +0.5% ROI |
| Optimal threshold per context | Different edge needed for fav vs dog, high vs low odds | +0.5-1% ROI |

### 6.3 How CatBoost Could Fail

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Overfitting to TRAIN | Medium | Early stopping, regularization, temporal split |
| Features are linearly sufficient | High | If so, ML adds nothing over rules (not a failure per se) |
| Market is too efficient | Medium | Focus on edges our rules already found |
| Not enough data | Low-Medium | 14K train games is borderline. Simple model (few features) preferred. |
| Distribution shift 2010→2021 | Medium | Walk-forward, or season-aware features |

---

## 7. Implementation Steps (ordered)

### Step 1: Data Preparation
- Load enriched data with all 67 features
- Apply base filters (no Colorado, September, extreme lines, games_played >= 20)
- Split: TRAIN (2010-2015), VALID (2016-2017), TEST (2018-2019, 2021)
- Define feature list (exclude target, outcome, identity columns)
- Mark categorical features (sp_hand)
- Verify no look-ahead leakage

### Step 2: Baseline Model
- Train CatBoost with defaults on TRAIN
- Evaluate LogLoss, AUC on VALID and TEST
- Plot calibration curve
- Print feature importances (top 20)
- **Checkpoint:** If AUC < 0.52 on VALID → features are too weak, abort ML approach

### Step 3: Feature Analysis
- SHAP values for top 20 features
- Partial Dependence Plots for rpi_diff, sp_wr_long_diff, sp_ra_long_diff
- Interaction analysis: top 5 feature pairs
- Remove features with importance < 1%
- Retrain with reduced feature set

### Step 4: Hyperparameter Tuning
- Optuna (50-100 trials) on VALID LogLoss
- Search: depth, learning_rate, l2_leaf_reg, min_data_in_leaf
- Keep best model

### Step 5: Threshold Optimization
- For THRESHOLD in [0.01, 0.02, ..., 0.10]:
  - Simulate betting on VALID set
  - Record: N_bets, ROI, Sharpe, max_drawdown
- Select THRESHOLD that maximizes ROI with N_bets >= 200/season
- **This is done on VALIDATION only — not TEST**

### Step 6: Final Evaluation (one shot)
- Apply best model + best threshold to TEST set
- Report: ROI, N_bets, Sharpe, drawdown, per-season breakdown
- Compare with series dogon (+5.21% ROI, 194 series on same TEST)
- Plot cumulative P&L curve
- **No going back to tune after seeing TEST results**

### Step 7: Combination Analysis
- Can ML + series dogon coexist? (different bet types, different games)
- ML for flat bets + dogon for series = portfolio approach?
- Correlation between ML signals and dogon filter signals

### Step 8 (optional): Walk-Forward Validation
- Expanding window: train on 2010-Y, predict Y+1
- More robust estimate of live performance
- Slower but gives per-season P&L curve

---

## 8. Dependencies & Tooling

### Python Packages
```
catboost          # Core model
optuna            # Hyperparameter search
shap              # Feature explanation (SHAP values)
scikit-learn      # Calibration, AUC, Brier score
matplotlib        # Plots
```

### File Structure (planned)
```
src/
  ml_model.py           # CatBoost training, prediction, evaluation
  ml_features.py        # Feature matrix builder (from enriched df → X, y)
  ml_backtest.py        # Threshold-based betting simulation

scripts/
  run_catboost_baseline.py    # Step 2
  run_catboost_tune.py        # Steps 3-4
  run_catboost_evaluate.py    # Steps 5-6

knowledge/
  catboost_results.md         # Final report
```

---

## 9. Success Criteria

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| VALID AUC > 0.53 | Minimum | Must beat market slightly |
| VALID LogLoss < 0.685 | Minimum | Better than market baseline |
| TEST ROI > 0% | Required | Profitable out-of-sample |
| TEST ROI > +2% | Target | Practically useful |
| TEST N_bets > 500 | Required | Statistically meaningful |
| TEST ROI > +5.21% (dogon) | Stretch | Beats our best strategy |
| Calibration within 2pp | Required | P_predicted ≈ P_actual |

**Minimum viable outcome:** TEST ROI > 0% with > 500 bets.
**Great outcome:** TEST ROI > 3% with > 1000 bets.
**Home run:** TEST ROI > 5% AND complements (not replaces) series dogon.

---

## 10. Risks & Open Questions

### Open Questions for Discussion

1. **Feature set:** Include `home_implied_prob` as feature or not?
   - PRO: Market line is strong signal, model can learn "when market is wrong"
   - CON: Model might just copy market line → no edge. Also, if we're betting against the line, having it as a feature is circular.
   - **Recommendation:** Include it. CatBoost can learn to use it as baseline and find deviations.

2. **Season as feature?**
   - PRO: Captures era effects (rule changes, DH expansion)
   - CON: Overfitting to specific seasons
   - **Recommendation:** Don't include. Use month + games_played instead.

3. **Flat bet only, or also series dogon with ML filter?**
   - **Recommendation:** Start with flat bet. If profitable, test ML as pre-filter for dogon.

4. **Which odds to use for profit calculation — opening or closing?**
   - **Recommendation:** Closing (more realistic — we'd bet close to game time). Already using closing for all analyses.

5. **Minimum edge threshold — fixed or dynamic?**
   - **Recommendation:** Start with fixed threshold, optimize on VALID. Dynamic threshold (per-odds-bucket) is Step 8+.
