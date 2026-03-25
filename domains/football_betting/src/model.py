"""CatBoost Poisson model for predicting goals per team.

Architecture:
  - Input: team-level features (own + opponent metrics, home flag, context)
  - Target: goals_scored (count data)
  - Model: CatBoost with Poisson loss → output = λ (expected goals)
  - Validation: walk-forward (2021 train → 2022 val → 2023 test)

From predicted λ_home and λ_away, we derive all market probabilities via
Poisson convolution (see src/markets.py).

Usage:
    from src.model import train_and_evaluate

    results = train_and_evaluate(team_level_df, feature_cols)
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from scipy.stats import poisson as poisson_dist

from src.markets import match_probabilities

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    catboost_params: dict | None = None
    train_seasons: list[int] | None = None
    val_seasons: list[int] | None = None
    test_seasons: list[int] | None = None

    def __post_init__(self):
        if self.catboost_params is None:
            self.catboost_params = {
                "loss_function": "Poisson",
                "depth": 4,
                "learning_rate": 0.05,
                "iterations": 500,
                "l2_leaf_reg": 5,
                "min_data_in_leaf": 20,
                "random_seed": 42,
                "verbose": 0,
            }
        if self.train_seasons is None:
            self.train_seasons = list(range(2012, 2021))  # 2012-2020
        if self.val_seasons is None:
            self.val_seasons = [2021]
        if self.test_seasons is None:
            self.test_seasons = [2022, 2023]


def _split_data(
    df: pd.DataFrame,
    feature_cols: list[str],
    config: ModelConfig,
) -> tuple:
    """Split team-level data into train/val/test by season."""
    train = df[df["season"].isin(config.train_seasons)]
    val = df[df["season"].isin(config.val_seasons)]
    test = df[df["season"].isin(config.test_seasons)]

    # Fill NaN with training medians
    X_train = train[feature_cols].copy()
    y_train = train["goals_scored"].values

    medians = X_train.median()
    X_train = X_train.fillna(medians)
    X_val = val[feature_cols].fillna(medians)
    X_test = test[feature_cols].fillna(medians)

    y_val = val["goals_scored"].values
    y_test = test["goals_scored"].values

    logger.info(
        f"Split: train={len(train)} ({config.train_seasons}), "
        f"val={len(val)} ({config.val_seasons}), "
        f"test={len(test)} ({config.test_seasons})"
    )

    return X_train, y_train, X_val, y_val, X_test, y_test, val, test, medians


def train_catboost_poisson(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    config: ModelConfig,
) -> CatBoostRegressor:
    """Train CatBoost with Poisson loss."""
    model = CatBoostRegressor(**config.catboost_params)
    model.fit(
        X_train, y_train,
        eval_set=(X_val, y_val),
        early_stopping_rounds=50,
    )
    logger.info(f"CatBoost trained: {model.best_iteration_} iterations")
    return model


def evaluate_goals(
    y_true: np.ndarray,
    y_pred_lambda: np.ndarray,
    label: str,
) -> dict:
    """Evaluate goal predictions."""
    mae = np.mean(np.abs(y_true - y_pred_lambda))
    mean_actual = np.mean(y_true)
    naive_mae = np.mean(np.abs(y_true - mean_actual))

    # Poisson log-likelihood
    ll = np.mean(poisson_dist.logpmf(y_true.astype(int), y_pred_lambda))

    # Naive Poisson LL (predict mean for all)
    naive_ll = np.mean(poisson_dist.logpmf(y_true.astype(int), mean_actual))

    logger.info(
        f"{label}: MAE={mae:.3f} (naive={naive_mae:.3f}), "
        f"Poisson LL={ll:.4f} (naive={naive_ll:.4f})"
    )

    return {
        "label": label,
        "mae": mae,
        "naive_mae": naive_mae,
        "mae_improvement": 1 - mae / naive_mae,
        "poisson_ll": ll,
        "naive_poisson_ll": naive_ll,
        "ll_improvement": ll - naive_ll,
        "mean_predicted": np.mean(y_pred_lambda),
        "mean_actual": mean_actual,
    }


def evaluate_match_probabilities(
    games_df: pd.DataFrame,
    lambdas_home: np.ndarray,
    lambdas_away: np.ndarray,
    label: str,
    rho: float = 0.0,
) -> dict:
    """Evaluate derived match probabilities vs actual outcomes and Pinnacle baseline.

    Args:
        games_df: must have: result, home_implied, draw_implied, away_implied.
        lambdas_home: predicted expected goals for home teams.
        lambdas_away: predicted expected goals for away teams.
        label: identifier for logging.
        rho: bivariate Poisson correlation parameter (0 = independent).
    """
    n = len(games_df)
    model_rps = 0.0
    pinnacle_rps = 0.0

    for i in range(n):
        row = games_df.iloc[i]
        probs = match_probabilities(lambdas_home[i], lambdas_away[i], rho)

        # Actual outcome as [H, D, A] vector
        actual = [
            1.0 if row["result"] == "H" else 0.0,
            1.0 if row["result"] == "D" else 0.0,
            1.0 if row["result"] == "A" else 0.0,
        ]

        # Model probabilities
        model_p = [probs["home_win"], probs["draw"], probs["away_win"]]

        # Pinnacle probabilities
        pinnacle_p = [row["home_implied"], row["draw_implied"], row["away_implied"]]

        # RPS (Ranked Probability Score)
        model_rps += _rps(model_p, actual)
        pinnacle_rps += _rps(pinnacle_p, actual)

    model_rps /= n
    pinnacle_rps /= n

    logger.info(
        f"{label}: Model RPS={model_rps:.4f}, Pinnacle RPS={pinnacle_rps:.4f}, "
        f"Improvement={1 - model_rps/pinnacle_rps:.1%}"
    )

    return {
        "label": label,
        "model_rps": model_rps,
        "pinnacle_rps": pinnacle_rps,
        "rps_improvement": 1 - model_rps / pinnacle_rps,
        "n_matches": n,
    }


def _rps(predicted: list[float], actual: list[float]) -> float:
    """Ranked Probability Score for ordered outcomes [H, D, A]."""
    cum_pred = np.cumsum(predicted)
    cum_actual = np.cumsum(actual)
    return np.mean((cum_pred - cum_actual) ** 2)


def train_and_evaluate(
    team_df: pd.DataFrame,
    feature_cols: list[str],
    games: pd.DataFrame,
    config: ModelConfig | None = None,
) -> dict:
    """Full pipeline: split → train → predict → evaluate.

    Args:
        team_df: team-level DataFrame (2 rows per match) with features + goals_scored
        feature_cols: list of feature column names
        games: match-level DataFrame with result, implied probs (for RPS eval)
        config: model configuration

    Returns:
        dict with model, predictions, and evaluation results
    """
    config = config or ModelConfig()

    # Split
    X_train, y_train, X_val, y_val, X_test, y_test, val_df, test_df, medians = \
        _split_data(team_df, feature_cols, config)

    # Train
    model = train_catboost_poisson(X_train, y_train, X_val, y_val, config)

    # Predict (CatBoost Poisson outputs log(λ), need exp)
    pred_val = model.predict(X_val)
    pred_test = model.predict(X_test)

    # CatBoost Poisson: predictions are already λ (not log λ) — verify
    if pred_val.mean() < 0:
        pred_val = np.exp(pred_val)
        pred_test = np.exp(pred_test)

    # Clip to reasonable range
    pred_val = np.clip(pred_val, 0.1, 5.0)
    pred_test = np.clip(pred_test, 0.1, 5.0)

    # Evaluate goals
    val_goals = evaluate_goals(y_val, pred_val, "Validation")
    test_goals = evaluate_goals(y_test, pred_test, "Test")

    # Reconstruct match-level λ for RPS evaluation
    # team_df has 2 rows per match (home then away, in order)
    val_games = games[games["season"].isin(config.val_seasons)].copy()
    test_games = games[games["season"].isin(config.test_seasons)].copy()

    val_home_idx = val_df[val_df["is_home"] == 1].index
    val_away_idx = val_df[val_df["is_home"] == 0].index

    val_home_lambda = pred_val[np.isin(np.arange(len(val_df)), np.where(val_df["is_home"].values == 1)[0])]
    val_away_lambda = pred_val[np.isin(np.arange(len(val_df)), np.where(val_df["is_home"].values == 0)[0])]

    test_home_lambda = pred_test[np.isin(np.arange(len(test_df)), np.where(test_df["is_home"].values == 1)[0])]
    test_away_lambda = pred_test[np.isin(np.arange(len(test_df)), np.where(test_df["is_home"].values == 0)[0])]

    # Match RPS eval
    val_rps = evaluate_match_probabilities(val_games, val_home_lambda, val_away_lambda, "Validation")
    test_rps = evaluate_match_probabilities(test_games, test_home_lambda, test_away_lambda, "Test")

    # Feature importance
    importance = dict(zip(feature_cols, model.feature_importances_))
    top_features = sorted(importance.items(), key=lambda x: -x[1])[:10]

    return {
        "model": model,
        "config": config,
        "medians": medians,
        "val_goals": val_goals,
        "test_goals": test_goals,
        "val_rps": val_rps,
        "test_rps": test_rps,
        "top_features": top_features,
        "predictions": {
            "val_lambda": pred_val,
            "test_lambda": pred_test,
            "test_home_lambda": test_home_lambda,
            "test_away_lambda": test_away_lambda,
        },
    }
