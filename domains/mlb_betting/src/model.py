"""Regime-split model training: CatBoost + Ridge → 50/50 ensemble.

Four models trained on different outcome regimes:
- M0: all games (baseline)
- M2: favorite won by 2+ runs (dominant)
- M3: favorite won by exactly 1 run (tight)
- M4: favorite lost (upset)

Target: closing decimal odds of favorite (regression).
Validation: walk-forward (train N seasons, validate 1, test remaining).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier, CatBoostRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegressionCV, RidgeCV
from sklearn.metrics import (
    brier_score_loss,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    roc_auc_score,
)

logger = logging.getLogger(__name__)

REGIMES = ["M0", "M2", "M3", "M4"]
OU_REGIMES = ["T0", "T_OVER2", "T_OVER1", "T_UNDER"]
YRFI_REGIMES = ["Y0", "Y_NRFI", "Y_1RUN", "Y_2PLUS"]


@dataclass
class ModelConfig:
    catboost_params: dict = field(default_factory=lambda: {
        "depth": 4,
        "learning_rate": 0.05,
        "iterations": 300,
        "l2_leaf_reg": 5,
        "min_data_in_leaf": 20,
        "loss_function": "RMSE",
        "verbose": 0,
        "random_seed": 42,
    })
    ridge_alphas: list[float] = field(default_factory=lambda: [0.1, 1.0, 10.0, 100.0])
    ensemble_weight_catboost: float = 0.5


# YRFI regime-split config: deeper trees, more iterations, stronger regularization
YRFI_REG_CONFIG = ModelConfig(
    catboost_params={
        "depth": 5,
        "learning_rate": 0.04,
        "iterations": 400,
        "l2_leaf_reg": 7,
        "min_data_in_leaf": 25,
        "loss_function": "RMSE",
        "verbose": 0,
        "random_seed": 42,
    },
    ridge_alphas=[0.1, 1.0, 10.0, 100.0],
    ensemble_weight_catboost=0.5,
)


@dataclass
class FoldResult:
    fold_name: str
    regime: str
    train_seasons: list[int]
    val_seasons: list[int]
    test_seasons: list[int]
    n_train: int
    n_val: int
    n_test: int
    val_rmse: float
    val_mae: float
    test_rmse: float
    test_mae: float
    test_predictions: pd.DataFrame | None = None


def _get_regime_mask(df: pd.DataFrame, regime: str) -> pd.Series:
    if regime in ("M0", "T0", "Y0"):
        return pd.Series(True, index=df.index)
    return df["regime"] == regime


def walk_forward_splits(
    seasons: list[int],
    *,
    min_train: int = 5,
    max_train: int | None = None,
    val_size: int = 1,
    test_size: int = 2,
) -> list[tuple[list[int], list[int], list[int]]]:
    """Generate walk-forward train/val/test season splits.

    Each fold: train on first N seasons, validate on next 1, test on next 2.
    Slides forward by 1 season each step.

    max_train: if set, use sliding window (last N seasons) instead of expanding.
    """
    seasons = sorted(seasons)
    folds = []
    for i in range(min_train, len(seasons) - val_size - test_size + 1):
        if max_train is not None:
            train = seasons[max(0, i - max_train):i]
        else:
            train = seasons[:i]
        val = seasons[i : i + val_size]
        test = seasons[i + val_size : i + val_size + test_size]
        folds.append((train, val, test))
    return folds


def train_regime_model(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    regime: str,
    train_seasons: list[int],
    val_seasons: list[int],
    *,
    cfg: ModelConfig = ModelConfig(),
) -> tuple[CatBoostRegressor, RidgeCV, IsotonicRegression | None, dict]:
    """Train CatBoost + Ridge on a single regime, return models + metrics."""
    regime_mask = _get_regime_mask(df, regime)

    train_mask = df["season"].isin(train_seasons) & regime_mask
    val_mask = df["season"].isin(val_seasons) & regime_mask

    X_train = df.loc[train_mask, features].values
    y_train = df.loc[train_mask, target].values
    X_val = df.loc[val_mask, features].values
    y_val = df.loc[val_mask, target].values

    if len(X_train) < 50:
        logger.warning(f"Regime {regime}: only {len(X_train)} training samples, skipping")
        return None, None, None, {"n_train": len(X_train), "skipped": True}

    # Handle NaN: fill with column medians from training set.
    # If entire column is NaN (feature unavailable for early seasons), fill with 0.
    train_medians = np.nanmedian(X_train, axis=0)
    train_medians = np.where(np.isnan(train_medians), 0.0, train_medians)
    for col_idx in range(X_train.shape[1]):
        mask = np.isnan(X_train[:, col_idx])
        X_train[mask, col_idx] = train_medians[col_idx]
        if len(X_val) > 0:
            mask_v = np.isnan(X_val[:, col_idx])
            X_val[mask_v, col_idx] = train_medians[col_idx]

    # CatBoost
    cb = CatBoostRegressor(**cfg.catboost_params)
    cb.fit(X_train, y_train, eval_set=(X_val, y_val) if len(X_val) > 0 else None)

    # Ridge
    ridge = RidgeCV(alphas=cfg.ridge_alphas)
    ridge.fit(X_train, y_train)

    # Calibration (isotonic on validation fold)
    calibrator = None
    if len(X_val) >= 10:
        cb_val_pred = cb.predict(X_val)
        ridge_val_pred = ridge.predict(X_val)
        ensemble_val = cfg.ensemble_weight_catboost * cb_val_pred + (1 - cfg.ensemble_weight_catboost) * ridge_val_pred
        try:
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(ensemble_val, y_val)
        except Exception:
            calibrator = None

    metrics = {
        "n_train": len(X_train),
        "n_val": len(X_val),
        "skipped": False,
        "ridge_alpha": float(ridge.alpha_),
        "train_medians": train_medians,
    }

    if len(X_val) > 0:
        cb_pred = cb.predict(X_val)
        ridge_pred = ridge.predict(X_val)
        ens_pred = cfg.ensemble_weight_catboost * cb_pred + (1 - cfg.ensemble_weight_catboost) * ridge_pred
        if calibrator is not None:
            ens_pred = calibrator.predict(ens_pred)
        metrics["val_rmse"] = float(np.sqrt(mean_squared_error(y_val, ens_pred)))
        metrics["val_mae"] = float(mean_absolute_error(y_val, ens_pred))
    else:
        metrics["val_rmse"] = float("nan")
        metrics["val_mae"] = float("nan")

    return cb, ridge, calibrator, metrics


def predict_ensemble(
    X: np.ndarray,
    cb: CatBoostRegressor,
    ridge: RidgeCV,
    calibrator: IsotonicRegression | None,
    train_medians: np.ndarray,
    *,
    cfg: ModelConfig = ModelConfig(),
) -> np.ndarray:
    """Generate ensemble predictions, handling NaN via training medians."""
    X = X.copy()
    for col_idx in range(X.shape[1]):
        mask = np.isnan(X[:, col_idx])
        X[mask, col_idx] = train_medians[col_idx]

    cb_pred = cb.predict(X)
    ridge_pred = ridge.predict(X)
    ens = cfg.ensemble_weight_catboost * cb_pred + (1 - cfg.ensemble_weight_catboost) * ridge_pred
    if calibrator is not None:
        ens = calibrator.predict(ens)
    return ens


def run_walk_forward(
    df: pd.DataFrame,
    features: list[str],
    target: str = "closing_decimal_odds_favorite",
    *,
    cfg: ModelConfig = ModelConfig(),
    min_train: int = 5,
    regimes: list[str] | None = None,
) -> list[FoldResult]:
    """Run walk-forward validation for all regimes across all folds.

    Returns list of FoldResult with metrics and test predictions.
    """
    regimes = regimes or REGIMES
    seasons = sorted(df["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=min_train)

    results = []
    for train_s, val_s, test_s in folds:
        fold_name = f"train_{train_s[0]}-{train_s[-1]}_val_{val_s[0]}_test_{test_s[0]}-{test_s[-1]}"
        logger.info(f"\n{'='*60}")
        logger.info(f"Fold: {fold_name}")

        for regime in regimes:
            logger.info(f"  Regime {regime}...")
            cb, ridge, cal, metrics = train_regime_model(
                df, features, target, regime, train_s, val_s, cfg=cfg,
            )

            if metrics.get("skipped"):
                logger.warning(f"  Regime {regime}: skipped (too few samples)")
                results.append(FoldResult(
                    fold_name=fold_name, regime=regime,
                    train_seasons=train_s, val_seasons=val_s, test_seasons=test_s,
                    n_train=metrics["n_train"], n_val=0, n_test=0,
                    val_rmse=float("nan"), val_mae=float("nan"),
                    test_rmse=float("nan"), test_mae=float("nan"),
                ))
                continue

            # Test evaluation: predict ALL test games (not regime-filtered)
            test_mask = df["season"].isin(test_s)
            X_test = df.loc[test_mask, features].values
            y_test = df.loc[test_mask, target].values

            test_pred = predict_ensemble(
                X_test, cb, ridge, cal, metrics["train_medians"], cfg=cfg,
            )
            test_rmse = float(np.sqrt(mean_squared_error(y_test, test_pred)))
            test_mae = float(mean_absolute_error(y_test, test_pred))

            # Build predictions DataFrame for divergence analysis
            pred_df = df.loc[test_mask, ["season", "date", "home_team", "away_team",
                                         "regime", target]].copy()
            pred_df[f"pred_{regime}"] = test_pred

            logger.info(
                f"  {regime}: train={metrics['n_train']}, val={metrics['n_val']}, "
                f"test={len(X_test)} | val_RMSE={metrics['val_rmse']:.4f}, "
                f"test_RMSE={test_rmse:.4f}"
            )

            results.append(FoldResult(
                fold_name=fold_name, regime=regime,
                train_seasons=train_s, val_seasons=val_s, test_seasons=test_s,
                n_train=metrics["n_train"], n_val=metrics["n_val"], n_test=len(X_test),
                val_rmse=metrics["val_rmse"], val_mae=metrics["val_mae"],
                test_rmse=test_rmse, test_mae=test_mae,
                test_predictions=pred_df,
            ))

    return results


def compute_divergence(fold_results: list[FoldResult]) -> pd.DataFrame:
    """Compute inter-model divergence from walk-forward results.

    For each test game, collects predictions from all 4 regime models
    and computes divergence metrics.
    """
    # Group results by fold
    fold_groups: dict[str, list[FoldResult]] = {}
    for r in fold_results:
        if r.test_predictions is not None:
            fold_groups.setdefault(r.fold_name, []).append(r)

    all_divs = []
    for fold_name, fold_rs in fold_groups.items():
        # All regime models predict the same test games (same index),
        # so just assign columns by index rather than merging.
        base = None
        for r in fold_rs:
            preds = r.test_predictions
            pred_col = [c for c in preds.columns if c.startswith("pred_")][0]
            if base is None:
                base = preds.copy().reset_index(drop=True)
            else:
                base[pred_col] = preds[pred_col].values

        if base is None:
            continue

        pred_cols = [c for c in base.columns if c.startswith("pred_")]
        if len(pred_cols) < 2:
            continue

        pred_matrix = base[pred_cols].values
        base["div_range"] = np.nanmax(pred_matrix, axis=1) - np.nanmin(pred_matrix, axis=1)
        base["div_std"] = np.nanstd(pred_matrix, axis=1)
        base["fold"] = fold_name
        all_divs.append(base)

    if not all_divs:
        return pd.DataFrame()
    return pd.concat(all_divs, ignore_index=True)


# ── YRFI Classification ─────────────────────────────────────────────────


@dataclass
class YRFIModelConfig:
    catboost_params: dict = field(default_factory=lambda: {
        "loss_function": "Logloss",
        "depth": 5,
        "learning_rate": 0.03,
        "iterations": 500,
        "l2_leaf_reg": 8,
        "min_data_in_leaf": 30,
        "verbose": 0,
        "random_seed": 42,
        "auto_class_weights": "Balanced",
        "early_stopping_rounds": 50,
    })
    ensemble_weight_catboost: float = 0.7


def _impute_nan(X: np.ndarray, medians: np.ndarray) -> np.ndarray:
    """Replace NaN with column medians (in-place on copy)."""
    X = X.copy()
    for col in range(X.shape[1]):
        mask = np.isnan(X[:, col])
        X[mask, col] = medians[col]
    return X


def train_yrfi_model(
    df: pd.DataFrame,
    features: list[str],
    train_seasons: list[int],
    val_seasons: list[int],
    *,
    cfg: YRFIModelConfig = YRFIModelConfig(),
) -> tuple[CatBoostClassifier, LogisticRegressionCV | None, IsotonicRegression | None, dict]:
    """Train YRFI binary classifier (CatBoost + LogisticRegression ensemble).

    Returns (catboost_model, logistic_model, calibrator, metrics_dict).
    """
    train_mask = df["season"].isin(train_seasons)
    val_mask = df["season"].isin(val_seasons)

    X_train = df.loc[train_mask, features].values.astype(float)
    y_train = df.loc[train_mask, "yrfi"].values.astype(int)
    X_val = df.loc[val_mask, features].values.astype(float)
    y_val = df.loc[val_mask, "yrfi"].values.astype(int)

    logger.info(f"YRFI train: {len(X_train)} games, YRFI rate={y_train.mean()*100:.1f}%")
    logger.info(f"YRFI val:   {len(X_val)} games, YRFI rate={y_val.mean()*100:.1f}%")

    # NaN imputation from training medians
    train_medians = np.nanmedian(X_train, axis=0)
    train_medians = np.where(np.isnan(train_medians), 0.0, train_medians)
    X_train = _impute_nan(X_train, train_medians)
    X_val = _impute_nan(X_val, train_medians)

    # CatBoost classifier
    cb = CatBoostClassifier(**cfg.catboost_params)
    cb.fit(X_train, y_train, eval_set=(X_val, y_val) if len(X_val) > 0 else None)

    # Logistic regression (secondary model)
    lr_model = None
    try:
        lr_model = LogisticRegressionCV(
            Cs=[0.01, 0.1, 1.0, 10.0],
            cv=5,
            max_iter=1000,
            random_state=42,
        )
        lr_model.fit(X_train, y_train)
    except Exception as e:
        logger.warning(f"LogisticRegression failed: {e}")

    # Calibration on validation fold
    calibrator = None
    if len(X_val) >= 50:
        cb_proba_val = cb.predict_proba(X_val)[:, 1]
        if lr_model is not None:
            lr_proba_val = lr_model.predict_proba(X_val)[:, 1]
            ensemble_val = (
                cfg.ensemble_weight_catboost * cb_proba_val
                + (1 - cfg.ensemble_weight_catboost) * lr_proba_val
            )
        else:
            ensemble_val = cb_proba_val
        try:
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(ensemble_val, y_val)
        except Exception:
            calibrator = None

    # Metrics
    metrics = {
        "n_train": len(X_train),
        "n_val": len(X_val),
        "train_medians": train_medians,
        "train_yrfi_rate": float(y_train.mean()),
    }

    if len(X_val) > 0:
        proba_val = predict_yrfi_proba(X_val, cb, lr_model, calibrator, train_medians, cfg=cfg)
        metrics["val_auc"] = float(roc_auc_score(y_val, proba_val))
        metrics["val_brier"] = float(brier_score_loss(y_val, proba_val))
        metrics["val_logloss"] = float(log_loss(y_val, np.clip(proba_val, 1e-7, 1 - 1e-7)))
        logger.info(
            f"VAL: AUC={metrics['val_auc']:.4f}, "
            f"Brier={metrics['val_brier']:.4f}, "
            f"LogLoss={metrics['val_logloss']:.4f}"
        )

    return cb, lr_model, calibrator, metrics


def predict_yrfi_proba(
    X: np.ndarray,
    cb: CatBoostClassifier,
    lr_model: LogisticRegressionCV | None,
    calibrator: IsotonicRegression | None,
    train_medians: np.ndarray,
    *,
    cfg: YRFIModelConfig = YRFIModelConfig(),
) -> np.ndarray:
    """Generate YRFI probability predictions (0-1)."""
    X = _impute_nan(X, train_medians)

    cb_proba = cb.predict_proba(X)[:, 1]
    if lr_model is not None:
        lr_proba = lr_model.predict_proba(X)[:, 1]
        proba = cfg.ensemble_weight_catboost * cb_proba + (1 - cfg.ensemble_weight_catboost) * lr_proba
    else:
        proba = cb_proba

    if calibrator is not None:
        proba = calibrator.predict(proba)

    return np.clip(proba, 0.0, 1.0)


# ── YRFI Multiclass (0 runs / 1 run / 2+ runs) ───────────────────────

YRFI_CLASSES = {0: "NRFI", 1: "1RUN", 2: "2PLUS"}


@dataclass
class YRFIMultiConfig:
    catboost_params: dict = field(default_factory=lambda: {
        "loss_function": "MultiClass",
        "classes_count": 3,
        "depth": 5,
        "learning_rate": 0.03,
        "iterations": 500,
        "l2_leaf_reg": 8,
        "min_data_in_leaf": 30,
        "verbose": 0,
        "random_seed": 42,
        "early_stopping_rounds": 50,
    })


def train_yrfi_multiclass(
    df: pd.DataFrame,
    features: list[str],
    train_seasons: list[int],
    val_seasons: list[int],
    *,
    cfg: YRFIMultiConfig = YRFIMultiConfig(),
) -> tuple[CatBoostClassifier, IsotonicRegression | None, dict]:
    """Train YRFI 3-class CatBoost: 0 runs / 1 run / 2+ runs.

    Target column: 'fi_class' (0, 1, 2).
    Returns (model, yrfi_calibrator, metrics_dict).
    Calibrator maps raw P(YRFI) = P(1) + P(2) to calibrated probability.
    """
    train_mask = df["season"].isin(train_seasons)
    val_mask = df["season"].isin(val_seasons)

    X_train = df.loc[train_mask, features].values.astype(float)
    y_train = df.loc[train_mask, "fi_class"].values.astype(int)
    X_val = df.loc[val_mask, features].values.astype(float)
    y_val = df.loc[val_mask, "fi_class"].values.astype(int)

    # NaN imputation
    train_medians = np.nanmedian(X_train, axis=0)
    train_medians = np.where(np.isnan(train_medians), 0.0, train_medians)
    X_train = _impute_nan(X_train, train_medians)
    X_val = _impute_nan(X_val, train_medians)

    cb = CatBoostClassifier(**cfg.catboost_params)
    cb.fit(X_train, y_train, eval_set=(X_val, y_val) if len(X_val) > 0 else None)

    metrics = {
        "n_train": len(X_train),
        "n_val": len(X_val),
        "train_medians": train_medians,
    }

    # Class distribution
    for c in range(3):
        metrics[f"train_class{c}_rate"] = float((y_train == c).mean())

    calibrator = None
    if len(X_val) > 0:
        proba_val = predict_yrfi_multiclass(X_val, cb, train_medians)
        # Per-class AUC (one-vs-rest)
        for c in range(3):
            y_bin = (y_val == c).astype(int)
            if y_bin.sum() > 0 and y_bin.sum() < len(y_bin):
                metrics[f"val_auc_class{c}"] = float(roc_auc_score(y_bin, proba_val[:, c]))
        # Overall multiclass log loss
        metrics["val_logloss"] = float(
            log_loss(y_val, np.clip(proba_val, 1e-7, 1 - 1e-7))
        )
        # YRFI binary: P(YRFI) = P(class1) + P(class2)
        p_yrfi_raw = proba_val[:, 1] + proba_val[:, 2]
        y_yrfi = (y_val > 0).astype(int)
        metrics["val_auc_yrfi_raw"] = float(roc_auc_score(y_yrfi, p_yrfi_raw))

        # Isotonic calibration on P(YRFI)
        try:
            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(p_yrfi_raw, y_yrfi)
            p_yrfi_cal = calibrator.predict(p_yrfi_raw)
            metrics["val_auc_yrfi"] = float(roc_auc_score(y_yrfi, p_yrfi_cal))
            metrics["val_brier_yrfi"] = float(brier_score_loss(y_yrfi, p_yrfi_cal))
        except Exception:
            calibrator = None
            metrics["val_auc_yrfi"] = metrics["val_auc_yrfi_raw"]
            metrics["val_brier_yrfi"] = float(brier_score_loss(y_yrfi, p_yrfi_raw))

    return cb, calibrator, metrics


def predict_yrfi_multiclass(
    X: np.ndarray,
    cb: CatBoostClassifier,
    train_medians: np.ndarray,
) -> np.ndarray:
    """Predict 3-class probabilities: [P(0 runs), P(1 run), P(2+ runs)].

    Returns ndarray of shape (n_games, 3).
    """
    X = _impute_nan(X, train_medians)
    return cb.predict_proba(X)


# ── Under/Over Binary Classification ─────────────────────────────────────


@dataclass
class UnderModelConfig:
    catboost_params: dict = field(default_factory=lambda: {
        "loss_function": "Logloss",
        "depth": 5,
        "learning_rate": 0.03,
        "iterations": 500,
        "l2_leaf_reg": 8,
        "min_data_in_leaf": 30,
        "verbose": 0,
        "random_seed": 42,
        "auto_class_weights": "Balanced",
        "early_stopping_rounds": 50,
    })
    ensemble_weight_catboost: float = 0.7
    max_train_seasons: int | None = 8


def train_under_model(
    df: pd.DataFrame,
    features: list[str],
    train_seasons: list[int],
    val_seasons: list[int],
    *,
    cfg: UnderModelConfig = UnderModelConfig(),
) -> tuple[CatBoostClassifier, LogisticRegressionCV | None, object | None, dict]:
    """Train UNDER binary classifier (CatBoost + LogisticRegression ensemble).

    Target: under_hit (1 = total_runs < close_ou, 0 = over).
    Pushes (total_runs == close_ou) are excluded from train and val.

    Returns (catboost_model, logistic_model, calibrator, metrics_dict).
    """
    push_mask = df["is_push"] if "is_push" in df.columns else pd.Series(False, index=df.index)

    train_mask = df["season"].isin(train_seasons) & ~push_mask
    val_mask = df["season"].isin(val_seasons) & ~push_mask

    X_train = df.loc[train_mask, features].values.astype(float)
    y_train = df.loc[train_mask, "under_hit"].values.astype(int)
    X_val = df.loc[val_mask, features].values.astype(float)
    y_val = df.loc[val_mask, "under_hit"].values.astype(int)

    logger.info(f"Under train: {len(X_train)} games, under_rate={y_train.mean()*100:.1f}%")
    logger.info(f"Under val:   {len(X_val)} games, under_rate={y_val.mean()*100:.1f}%")

    # NaN imputation from training medians
    train_medians = np.nanmedian(X_train, axis=0)
    train_medians = np.where(np.isnan(train_medians), 0.0, train_medians)
    X_train = _impute_nan(X_train, train_medians)
    X_val = _impute_nan(X_val, train_medians)

    # CatBoost classifier
    cb = CatBoostClassifier(**cfg.catboost_params)
    cb.fit(X_train, y_train, eval_set=(X_val, y_val) if len(X_val) > 0 else None)

    # Logistic regression (secondary model)
    lr_model = None
    try:
        lr_model = LogisticRegressionCV(
            Cs=[0.01, 0.1, 1.0, 10.0],
            cv=5,
            max_iter=1000,
            random_state=42,
        )
        lr_model.fit(X_train, y_train)
    except Exception as e:
        logger.warning(f"LogisticRegression failed: {e}")

    # Platt calibration on validation fold (sigmoid, 2 params — preserves
    # continuous discrimination unlike isotonic step-function)
    calibrator = None
    if len(X_val) >= 50:
        cb_proba_val = cb.predict_proba(X_val)[:, 1]
        if lr_model is not None:
            lr_proba_val = lr_model.predict_proba(X_val)[:, 1]
            ensemble_val = (
                cfg.ensemble_weight_catboost * cb_proba_val
                + (1 - cfg.ensemble_weight_catboost) * lr_proba_val
            )
        else:
            ensemble_val = cb_proba_val
        try:
            platt = LogisticRegressionCV(Cs=[1e10], cv=3, solver="lbfgs",
                                         max_iter=1000, random_state=42)
            platt.fit(ensemble_val.reshape(-1, 1), y_val)
            calibrator = platt
        except Exception:
            calibrator = None

    # Metrics
    metrics = {
        "n_train": len(X_train),
        "n_val": len(X_val),
        "train_medians": train_medians,
        "train_under_rate": float(y_train.mean()),
    }

    if len(X_val) > 0:
        proba_val = predict_under_proba(X_val, cb, lr_model, calibrator, train_medians, cfg=cfg)
        metrics["val_auc"] = float(roc_auc_score(y_val, proba_val))
        metrics["val_brier"] = float(brier_score_loss(y_val, proba_val))
        metrics["val_logloss"] = float(log_loss(y_val, np.clip(proba_val, 1e-7, 1 - 1e-7)))
        logger.info(
            f"Under VAL: AUC={metrics['val_auc']:.4f}, "
            f"Brier={metrics['val_brier']:.4f}, "
            f"LogLoss={metrics['val_logloss']:.4f}"
        )

    return cb, lr_model, calibrator, metrics


def predict_under_proba(
    X: np.ndarray,
    cb: CatBoostClassifier,
    lr_model: LogisticRegressionCV | None,
    calibrator: object | None,
    train_medians: np.ndarray,
    *,
    cfg: UnderModelConfig = UnderModelConfig(),
) -> np.ndarray:
    """Generate calibrated P(under) predictions (0-1)."""
    X = _impute_nan(X, train_medians)

    cb_proba = cb.predict_proba(X)[:, 1]
    if lr_model is not None:
        lr_proba = lr_model.predict_proba(X)[:, 1]
        proba = cfg.ensemble_weight_catboost * cb_proba + (1 - cfg.ensemble_weight_catboost) * lr_proba
    else:
        proba = cb_proba

    if calibrator is not None:
        proba = calibrator.predict_proba(proba.reshape(-1, 1))[:, 1]

    return np.clip(proba, 0.0, 1.0)


@dataclass
class UnderFoldResult:
    """Result of a single walk-forward fold for the under classifier."""

    fold_name: str
    train_seasons: list[int]
    val_seasons: list[int]
    test_seasons: list[int]
    n_train: int
    n_val: int
    n_test: int
    val_auc: float
    val_brier: float
    test_auc: float
    test_brier: float
    test_predictions: pd.DataFrame | None = None
    p_under_threshold: float = 0.0


def run_walk_forward_under(
    df: pd.DataFrame,
    features: list[str],
    *,
    cfg: UnderModelConfig = UnderModelConfig(),
    min_train: int = 5,
) -> list[UnderFoldResult]:
    """Walk-forward binary classification for P(under).

    Uses sliding or expanding training window depending on cfg.max_train_seasons.
    Returns list of UnderFoldResult with test predictions containing p_under.
    """
    seasons = sorted(df["season"].unique().tolist())
    folds = walk_forward_splits(seasons, min_train=min_train,
                                max_train=cfg.max_train_seasons)

    if not folds:
        logger.warning("No walk-forward folds generated for under classifier")
        return []

    logger.info(f"Under walk-forward: {len(folds)} folds, {len(features)} features")
    results = []

    for i, (train_s, val_s, test_s) in enumerate(folds):
        fold_name = f"fold_{i}_{val_s[0]}_{test_s[0]}-{test_s[-1]}"
        logger.info(f"  {fold_name}: train={train_s[0]}-{train_s[-1]}, "
                     f"val={val_s}, test={test_s}")

        # Train
        cb, lr_model, calibrator, metrics = train_under_model(
            df, features, train_s, val_s, cfg=cfg,
        )
        train_medians = metrics["train_medians"]

        # Predict on test fold (exclude pushes)
        push_mask = df["is_push"] if "is_push" in df.columns else pd.Series(False, index=df.index)
        test_mask = df["season"].isin(test_s) & ~push_mask
        n_test = int(test_mask.sum())

        if n_test < 10:
            logger.warning(f"  {fold_name}: only {n_test} test games, skipping")
            continue

        X_test = df.loc[test_mask, features].values.astype(float)
        y_test = df.loc[test_mask, "under_hit"].values.astype(int)
        p_under = predict_under_proba(X_test, cb, lr_model, calibrator, train_medians, cfg=cfg)

        # Test metrics
        test_auc = float(roc_auc_score(y_test, p_under))
        test_brier = float(brier_score_loss(y_test, p_under))
        logger.info(f"  {fold_name}: test AUC={test_auc:.4f}, Brier={test_brier:.4f}")

        # Build predictions DataFrame
        meta_cols = ["season", "date", "home_team", "away_team", "close_ou",
                     "total_runs", "under_hit"]
        preds_df = df.loc[test_mask, meta_cols].copy()
        preds_df["p_under"] = p_under

        # Adaptive threshold: top 25% of predictions in this fold
        threshold_75 = float(np.percentile(p_under, 75))

        results.append(UnderFoldResult(
            fold_name=fold_name,
            train_seasons=train_s,
            val_seasons=val_s,
            test_seasons=test_s,
            n_train=metrics["n_train"],
            n_val=metrics["n_val"],
            n_test=n_test,
            val_auc=metrics.get("val_auc", 0.0),
            val_brier=metrics.get("val_brier", 0.0),
            test_auc=test_auc,
            test_brier=test_brier,
            test_predictions=preds_df,
            p_under_threshold=threshold_75,
        ))

    logger.info(f"Under walk-forward complete: {len(results)} folds")
    return results
