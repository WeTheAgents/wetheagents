"""Bias-trained ensemble for football goals prediction.

Architecture:
  - Baseline: standard CatBoost Poisson model (all features, all training data)
  - 4 biased specialist models, each trained on a filtered/reweighted subset:
    1. Squad Disruption: SSS-filtered, SSS+congestion features only
    2. Home Fortress: home rows overweighted, all features
    3. Congestion: fatigue-filtered, form+congestion features only
    4. Market Correction: line-movement filtered, all features + line_move
  - Meta-learner: Ridge regression combines all model λ predictions
  - Separate home/away Ridge models (different base rates ~1.5 vs ~1.1)

Key invariant: filters/weights apply to TRAINING data only.
At inference, every model predicts on ALL matches.

Usage:
    from src.ensemble import train_and_evaluate_ensemble

    results = train_and_evaluate_ensemble(team_df, games)
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from catboost import CatBoostRegressor, Pool
from sklearn.linear_model import Ridge, RidgeCV

from src.features import MODEL_FEATURES
from src.model import (
    ModelConfig,
    evaluate_goals,
    evaluate_match_probabilities,
    train_and_evaluate,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class BiasedModelConfig:
    """Configuration for a single biased specialist model."""

    name: str
    feature_cols: list[str]
    train_filter: Callable[[pd.DataFrame], pd.Series] | None = None
    sample_weight_fn: Callable[[pd.DataFrame], np.ndarray] | None = None
    catboost_overrides: dict = field(default_factory=dict)


@dataclass
class EnsembleConfig:
    """Configuration for the full ensemble."""

    base_model_config: ModelConfig = field(default_factory=ModelConfig)
    biased_configs: list[BiasedModelConfig] = field(default_factory=list)
    meta_alpha: float | None = None  # None = RidgeCV with LOOCV, float = fixed Ridge
    min_train_rows: int = 100
    estimate_rho: bool = True         # estimate bivariate Poisson ρ on validation set
    rho_override: float | None = None  # manual ρ (skips estimation if set)


# ---------------------------------------------------------------------------
# Biased model definitions
# ---------------------------------------------------------------------------

SQUAD_DISRUPTION_FEATURES = [
    "own_sss_cum", "own_sss_r10", "opp_sss_cum", "opp_sss_r10",
    "own_days_rest", "opp_days_rest",
    "own_match_density_14d", "opp_match_density_14d",
    "is_home",
]

CONGESTION_FEATURES = [
    "own_days_rest", "opp_days_rest",
    "own_match_density_14d", "opp_match_density_14d",
    "own_ppg_r5", "opp_ppg_r5",
    "own_gf_pg_r5", "opp_gf_pg_r5",
    "own_ga_pg_r5", "opp_ga_pg_r5",
    "is_home", "matchday",
]

MARKET_CORRECTION_FEATURES = MODEL_FEATURES + ["line_move_own", "line_move_opp"]

# Regularized CatBoost params for thin-data models
_THIN_DATA_OVERRIDES = {"l2_leaf_reg": 10, "iterations": 300}


def _squad_disruption_filter(df: pd.DataFrame) -> pd.Series:
    """Keep rows where SSS differential is large (rotation detected)."""
    sss_diff = (df["own_sss_cum"] - df["opp_sss_cum"]).abs()
    return sss_diff > 0.15


def _home_fortress_weight(df: pd.DataFrame) -> np.ndarray:
    """Weight home rows 2x to amplify home advantage learning."""
    weights = np.ones(len(df))
    weights[df["is_home"].values == 1] = 2.0
    return weights


def _congestion_filter(df: pd.DataFrame) -> pd.Series:
    """Keep rows where at least one team has short rest."""
    own_tired = df["own_days_rest"].fillna(99) <= 3
    opp_tired = df["opp_days_rest"].fillna(99) <= 3
    return own_tired | opp_tired


def _market_correction_filter(df: pd.DataFrame) -> pd.Series:
    """Keep rows with significant line movement (>2pp implied probability shift)."""
    has_data = df["line_move_own"].notna()
    significant = df["line_move_own"].abs() > 0.02
    return has_data & significant


def make_default_biased_configs() -> list[BiasedModelConfig]:
    """Create the 4 biased model configurations."""
    return [
        BiasedModelConfig(
            name="squad_disruption",
            feature_cols=SQUAD_DISRUPTION_FEATURES,
            train_filter=_squad_disruption_filter,
            catboost_overrides=_THIN_DATA_OVERRIDES,
        ),
        BiasedModelConfig(
            name="home_fortress",
            feature_cols=list(MODEL_FEATURES),
            sample_weight_fn=_home_fortress_weight,
        ),
        BiasedModelConfig(
            name="congestion",
            feature_cols=CONGESTION_FEATURES,
            train_filter=_congestion_filter,
            catboost_overrides=_THIN_DATA_OVERRIDES,
        ),
        BiasedModelConfig(
            name="market_correction",
            feature_cols=MARKET_CORRECTION_FEATURES,
            train_filter=_market_correction_filter,
            catboost_overrides=_THIN_DATA_OVERRIDES,
        ),
    ]


def make_default_ensemble_config() -> EnsembleConfig:
    """Create default ensemble configuration."""
    return EnsembleConfig(
        base_model_config=ModelConfig(
            train_seasons=list(range(2012, 2021)),
            val_seasons=[2021],
            test_seasons=[2022, 2023],
        ),
        biased_configs=make_default_biased_configs(),
        meta_alpha=None,  # RidgeCV with LOOCV
        min_train_rows=100,
        estimate_rho=True,
    )


# ---------------------------------------------------------------------------
# Biased model training
# ---------------------------------------------------------------------------

def train_biased_model(
    team_df: pd.DataFrame,
    config: BiasedModelConfig,
    base_config: ModelConfig,
) -> dict | None:
    """Train a single biased CatBoost model.

    Filters/reweights TRAINING data only. Predicts on ALL val/test data.

    Returns dict with model, predictions, and training stats.
    Returns None if filtered training data is too small.
    """
    # Split into train/val/test by season
    train_df = team_df[team_df["season"].isin(base_config.train_seasons)].copy()
    val_df = team_df[team_df["season"].isin(base_config.val_seasons)].copy()
    test_df = team_df[team_df["season"].isin(base_config.test_seasons)].copy()

    # Apply training filter
    if config.train_filter is not None:
        mask = config.train_filter(train_df)
        # Handle NaN in mask (treat as False)
        mask = mask.fillna(False) if hasattr(mask, "fillna") else mask
        train_df = train_df[mask]

    n_train = len(train_df)
    logger.info(f"  [{config.name}] Training rows: {n_train}, features: {len(config.feature_cols)}")

    if n_train < 100:
        logger.warning(f"  [{config.name}] Only {n_train} training rows — SKIPPING")
        return None

    # Prepare features (fill NaN with training medians)
    X_train = train_df[config.feature_cols].copy()
    medians = X_train.median()
    X_train = X_train.fillna(medians)
    y_train = train_df["goals_scored"].values

    X_val = val_df[config.feature_cols].fillna(medians)
    y_val = val_df["goals_scored"].values
    X_test = test_df[config.feature_cols].fillna(medians)
    y_test = test_df["goals_scored"].values

    # Build CatBoost params
    catboost_params = {**base_config.catboost_params}
    catboost_params.update(config.catboost_overrides)

    # Sample weights
    sample_weight = None
    if config.sample_weight_fn is not None:
        sample_weight = config.sample_weight_fn(train_df)

    # Train
    model = CatBoostRegressor(**catboost_params)
    train_pool = Pool(X_train, y_train, weight=sample_weight)
    val_pool = Pool(X_val, y_val)
    model.fit(train_pool, eval_set=val_pool, early_stopping_rounds=50)

    # Predict on ALL val/test
    pred_val = np.clip(model.predict(X_val), 0.1, 5.0)
    pred_test = np.clip(model.predict(X_test), 0.1, 5.0)

    logger.info(
        f"  [{config.name}] Trained ({model.best_iteration_} iters), "
        f"val MAE={np.mean(np.abs(y_val - pred_val)):.3f}"
    )

    return {
        "name": config.name,
        "model": model,
        "medians": medians,
        "n_train": n_train,
        "pred_val": pred_val,
        "pred_test": pred_test,
        "y_val": y_val,
        "y_test": y_test,
    }


# ---------------------------------------------------------------------------
# Meta-learner
# ---------------------------------------------------------------------------

def train_meta_learner(
    model_preds_val: dict[str, np.ndarray],
    y_val: np.ndarray,
    is_home_val: np.ndarray,
    alpha: float | None = None,
) -> tuple[Ridge | RidgeCV, Ridge | RidgeCV, list[str]]:
    """Train Ridge meta-learner: separate models for home and away λ.

    Args:
        model_preds_val: {model_name: val_predictions} for all models (baseline + biased)
        y_val: true goals on validation set
        is_home_val: binary array (1=home, 0=away)
        alpha: Ridge regularization. None = RidgeCV with LOOCV, float = fixed Ridge.

    Returns:
        (ridge_home, ridge_away, model_names) where model_names preserves column order
    """
    model_names = sorted(model_preds_val.keys())
    X = np.column_stack([model_preds_val[name] for name in model_names])

    home_mask = is_home_val == 1
    away_mask = ~home_mask

    if alpha is None:
        alphas = np.logspace(-3, 3, 20)
        ridge_home = RidgeCV(alphas=alphas)
        ridge_away = RidgeCV(alphas=alphas)
    else:
        ridge_home = Ridge(alpha=alpha)
        ridge_away = Ridge(alpha=alpha)

    ridge_home.fit(X[home_mask], y_val[home_mask])
    ridge_away.fit(X[away_mask], y_val[away_mask])

    if alpha is None:
        logger.info(
            f"Meta-learner: RidgeCV selected home_alpha={ridge_home.alpha_:.4f}, "
            f"away_alpha={ridge_away.alpha_:.4f}"
        )
    else:
        logger.info(f"Meta-learner trained (alpha={alpha})")

    for i, name in enumerate(model_names):
        logger.info(
            f"  {name:25s} home_coef={ridge_home.coef_[i]:+.3f}  "
            f"away_coef={ridge_away.coef_[i]:+.3f}"
        )

    return ridge_home, ridge_away, model_names


def predict_ensemble(
    model_preds: dict[str, np.ndarray],
    is_home: np.ndarray,
    ridge_home: Ridge,
    ridge_away: Ridge,
    model_names: list[str],
) -> np.ndarray:
    """Generate ensemble λ predictions using meta-learner."""
    X = np.column_stack([model_preds[name] for name in model_names])

    result = np.zeros(len(is_home))
    home_mask = is_home == 1

    result[home_mask] = ridge_home.predict(X[home_mask])
    result[~home_mask] = ridge_away.predict(X[~home_mask])

    return np.clip(result, 0.1, 5.0)


# ---------------------------------------------------------------------------
# Full ensemble pipeline
# ---------------------------------------------------------------------------

def train_and_evaluate_ensemble(
    team_df: pd.DataFrame,
    games: pd.DataFrame,
    config: EnsembleConfig | None = None,
) -> dict:
    """Full ensemble pipeline: train all models, meta-learn, evaluate.

    Args:
        team_df: team-level DataFrame (2 rows per match) with features + goals_scored
        games: match-level DataFrame with result, implied probs (for RPS eval)
        config: ensemble configuration

    Returns:
        dict with all models, predictions, meta-learner, and evaluation results
    """
    config = config or make_default_ensemble_config()
    base_cfg = config.base_model_config

    # --- Step 1: Train baseline model ---
    logger.info("Training baseline model...")
    baseline_results = train_and_evaluate(team_df, MODEL_FEATURES, games, base_cfg)

    # --- Step 2: Train biased models ---
    biased_results = {}
    for biased_cfg in config.biased_configs:
        result = train_biased_model(team_df, biased_cfg, base_cfg)
        if result is not None:
            biased_results[result["name"]] = result

    if not biased_results:
        logger.warning("No biased models trained — returning baseline only")
        return {"baseline": baseline_results, "biased": {}, "ensemble": None}

    # --- Step 3: Collect predictions ---
    val_df = team_df[team_df["season"].isin(base_cfg.val_seasons)]
    test_df = team_df[team_df["season"].isin(base_cfg.test_seasons)]

    val_preds = {"baseline": baseline_results["predictions"]["val_lambda"]}
    test_preds = {"baseline": baseline_results["predictions"]["test_lambda"]}

    for name, res in biased_results.items():
        val_preds[name] = res["pred_val"]
        test_preds[name] = res["pred_test"]

    y_val = val_df["goals_scored"].values
    y_test = test_df["goals_scored"].values
    is_home_val = val_df["is_home"].values
    is_home_test = test_df["is_home"].values

    # --- Step 4: Train meta-learner ---
    logger.info("Training meta-learner...")
    ridge_home, ridge_away, model_names = train_meta_learner(
        val_preds, y_val, is_home_val, alpha=config.meta_alpha
    )

    # --- Step 5: Generate ensemble predictions ---
    ensemble_val = predict_ensemble(val_preds, is_home_val, ridge_home, ridge_away, model_names)
    ensemble_test = predict_ensemble(test_preds, is_home_test, ridge_home, ridge_away, model_names)

    # --- Step 6: Evaluate ---
    logger.info("Evaluating ensemble...")

    # Goals evaluation
    ensemble_val_goals = evaluate_goals(y_val, ensemble_val, "Ensemble-Val")
    ensemble_test_goals = evaluate_goals(y_test, ensemble_test, "Ensemble-Test")

    # Match RPS evaluation
    val_games = games[games["season"].isin(base_cfg.val_seasons)].copy()
    test_games = games[games["season"].isin(base_cfg.test_seasons)].copy()

    # Reconstruct home/away λ from team-level predictions
    val_home_mask = is_home_val == 1
    val_home_lambda = ensemble_val[val_home_mask]
    val_away_lambda = ensemble_val[~val_home_mask]

    test_home_mask = is_home_test == 1
    test_home_lambda = ensemble_test[test_home_mask]
    test_away_lambda = ensemble_test[~test_home_mask]

    # --- Step 6b: Estimate bivariate Poisson ρ ---
    from src.markets import estimate_rho as _estimate_rho

    rho = 0.0
    rho_info = None

    if config.rho_override is not None:
        rho = config.rho_override
        logger.info(f"Using manual rho override: {rho:.3f}")
    elif config.estimate_rho:
        logger.info("Estimating bivariate Poisson rho on validation set...")
        rho, rho_info = _estimate_rho(val_games, val_home_lambda, val_away_lambda)

    # --- Step 6c: Evaluate with bivariate Poisson ---
    # Independent Poisson (rho=0) for comparison
    ensemble_val_rps_indep = evaluate_match_probabilities(
        val_games, val_home_lambda, val_away_lambda, "Ensemble-Val (indep)"
    )
    ensemble_test_rps_indep = evaluate_match_probabilities(
        test_games, test_home_lambda, test_away_lambda, "Ensemble-Test (indep)"
    )

    # Bivariate Poisson (rho > 0 if estimated)
    ensemble_val_rps = evaluate_match_probabilities(
        val_games, val_home_lambda, val_away_lambda, "Ensemble-Val (biv)", rho
    )
    ensemble_test_rps = evaluate_match_probabilities(
        test_games, test_home_lambda, test_away_lambda, "Ensemble-Test (biv)", rho
    )

    # --- Meta-learner coefficients ---
    meta_coefs = {}
    for i, name in enumerate(model_names):
        meta_coefs[name] = {
            "home_coef": ridge_home.coef_[i],
            "away_coef": ridge_away.coef_[i],
        }

    return {
        "baseline": baseline_results,
        "biased": biased_results,
        "ensemble": {
            "val_goals": ensemble_val_goals,
            "test_goals": ensemble_test_goals,
            "val_rps": ensemble_val_rps,
            "test_rps": ensemble_test_rps,
            "val_rps_independent": ensemble_val_rps_indep,
            "test_rps_independent": ensemble_test_rps_indep,
            "val_lambda": ensemble_val,
            "test_lambda": ensemble_test,
            "meta_coefs": meta_coefs,
            "ridge_home": ridge_home,
            "ridge_away": ridge_away,
            "model_names": model_names,
            "rho": rho,
            "rho_info": rho_info,
            "meta_alpha_home": getattr(ridge_home, "alpha_", config.meta_alpha),
            "meta_alpha_away": getattr(ridge_away, "alpha_", config.meta_alpha),
        },
    }
