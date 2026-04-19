"""Runtime bundle helpers for the live UNDER totals strategy."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier

from src.features import OU_FEATURES

BASE_DIR = Path(__file__).resolve().parent.parent
PICKS_DIR = BASE_DIR / "picks"

UNDER_TRAIN_SEASONS = [2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024]
UNDER_VAL_SEASONS = [2025]
UNDER_LIVE_SEASONS = [2026]

UNDER_BASE_THRESHOLD = 0.53
UNDER_POWER_THRESHOLD = 0.55
UNDER_FALLBACK_DECIMAL = 1.909

UNDER_MODEL_PATH = PICKS_DIR / "under_totals_model.cbm"
UNDER_METADATA_PATH = PICKS_DIR / "under_totals_model.json"
UNDER_SUMMARY_PATH = PICKS_DIR / "under_totals_summary.json"

UNDER_MODIFIER_QUANTILES = {
    "q60": 0.60,
    "q70": 0.70,
    "q75": 0.75,
    "q80": 0.80,
}


@dataclass
class UnderLiveBundle:
    cb_model: CatBoostClassifier
    features: list[str]
    train_medians: np.ndarray
    ensemble_weight_catboost: float
    lr_coefficients: np.ndarray | None
    lr_intercept: float | None
    train_seasons: list[int]
    val_seasons: list[int]
    live_seasons: list[int]
    thresholds: dict[str, float]
    fallback_ref_odds: float
    summary_metrics: dict[str, Any]
    modifier: dict[str, Any]
    metadata_path: Path
    model_path: Path


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -35.0, 35.0)))


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Not JSON serializable: {type(value)!r}")


def _manual_lr_proba(X: np.ndarray, coefficients: np.ndarray, intercept: float) -> np.ndarray:
    return _sigmoid(X @ coefficients + intercept)


def predict_under_bundle_proba(
    frame: pd.DataFrame,
    bundle: UnderLiveBundle,
) -> np.ndarray:
    """Score a feature frame with a persisted UNDER live bundle."""
    X = frame.reindex(columns=bundle.features).to_numpy(dtype=float, copy=True)
    if X.ndim != 2:
        raise ValueError("Expected 2D feature matrix for UNDER live scoring")

    train_medians = np.asarray(bundle.train_medians, dtype=float)
    if train_medians.shape[0] != X.shape[1]:
        raise ValueError(
            f"Median vector length {train_medians.shape[0]} does not match "
            f"feature count {X.shape[1]}"
        )

    nan_mask = np.isnan(X)
    if nan_mask.any():
        X[nan_mask] = np.take(train_medians, np.where(nan_mask)[1])

    cb_proba = bundle.cb_model.predict_proba(X)[:, 1]
    if bundle.lr_coefficients is not None and bundle.lr_intercept is not None:
        lr_proba = _manual_lr_proba(X, bundle.lr_coefficients, bundle.lr_intercept)
        proba = (
            bundle.ensemble_weight_catboost * cb_proba
            + (1.0 - bundle.ensemble_weight_catboost) * lr_proba
        )
    else:
        proba = cb_proba
    return np.clip(proba, 0.0, 1.0)


def save_under_live_bundle(
    *,
    cb_model: CatBoostClassifier,
    features: list[str],
    train_medians: np.ndarray,
    ensemble_weight_catboost: float,
    lr_coefficients: np.ndarray | None,
    lr_intercept: float | None,
    train_seasons: list[int],
    val_seasons: list[int],
    live_seasons: list[int],
    thresholds: dict[str, float],
    summary_metrics: dict[str, Any],
    modifier: dict[str, Any],
    model_path: Path = UNDER_MODEL_PATH,
    metadata_path: Path = UNDER_METADATA_PATH,
) -> tuple[Path, Path]:
    """Persist the CatBoost model plus JSON metadata for live UNDER scoring."""
    model_path.parent.mkdir(parents=True, exist_ok=True)
    cb_model.save_model(str(model_path))

    metadata = {
        "bundle": "under_totals_live",
        "model_type": "catboost_plus_logistic_ensemble",
        "features": list(features),
        "features_requested": list(OU_FEATURES),
        "train_medians": np.asarray(train_medians, dtype=float).tolist(),
        "ensemble_weight_catboost": float(ensemble_weight_catboost),
        "lr_coefficients": (
            np.asarray(lr_coefficients, dtype=float).tolist()
            if lr_coefficients is not None
            else None
        ),
        "lr_intercept": float(lr_intercept) if lr_intercept is not None else None,
        "train_seasons": list(train_seasons),
        "val_seasons": list(val_seasons),
        "live_seasons": list(live_seasons),
        "thresholds": dict(thresholds),
        "fallback_ref_odds": UNDER_FALLBACK_DECIMAL,
        "summary_metrics": summary_metrics,
        "modifier": modifier,
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return model_path, metadata_path


@lru_cache(maxsize=1)
def load_under_live_bundle(
    model_path: Path = UNDER_MODEL_PATH,
    metadata_path: Path = UNDER_METADATA_PATH,
) -> UnderLiveBundle:
    """Load the persisted UNDER live bundle from disk."""
    if not model_path.exists():
        raise FileNotFoundError(
            f"UNDER model bundle missing: {model_path}. "
            "Run scripts/export_under_live_bundle.py first."
        )
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"UNDER metadata bundle missing: {metadata_path}. "
            "Run scripts/export_under_live_bundle.py first."
        )

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    cb_model = CatBoostClassifier()
    cb_model.load_model(str(model_path))

    lr_coefficients_raw = metadata.get("lr_coefficients")
    lr_coefficients = (
        np.asarray(lr_coefficients_raw, dtype=float)
        if lr_coefficients_raw is not None
        else None
    )
    if lr_coefficients is not None and lr_coefficients.ndim != 1:
        lr_coefficients = lr_coefficients.reshape(-1)

    return UnderLiveBundle(
        cb_model=cb_model,
        features=list(metadata.get("features", [])),
        train_medians=np.asarray(metadata.get("train_medians", []), dtype=float),
        ensemble_weight_catboost=float(metadata.get("ensemble_weight_catboost", 1.0)),
        lr_coefficients=lr_coefficients,
        lr_intercept=(
            float(metadata["lr_intercept"])
            if metadata.get("lr_intercept") is not None
            else None
        ),
        train_seasons=list(metadata.get("train_seasons", [])),
        val_seasons=list(metadata.get("val_seasons", [])),
        live_seasons=list(metadata.get("live_seasons", [])),
        thresholds=dict(metadata.get("thresholds", {})),
        fallback_ref_odds=float(metadata.get("fallback_ref_odds", UNDER_FALLBACK_DECIMAL)),
        summary_metrics=dict(metadata.get("summary_metrics", {})),
        modifier=dict(metadata.get("modifier", {})),
        metadata_path=metadata_path,
        model_path=model_path,
    )
