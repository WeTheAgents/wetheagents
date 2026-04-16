"""Probabilistic temperature forecasters for weather prediction markets.

Hierarchy:
  NaiveForecaster    — mu = raw forecast, sigma = historical std (market baseline)
  BiasForecaster     — mu = forecast - walk-forward monthly bias, sigma = historical std
  EMOSForecaster     — mu = a + b*forecast (linear), sigma = CRPS-optimized per group
  CRPSigmaForecaster — mu = raw forecast, sigma = CRPS-optimized per (station, month)
  EnsembleForecaster — mu = raw forecast, sigma = day-specific from ensemble spread

All forecasters follow the same interface:
  .fit(train_df)         — learn parameters from historical forecast-obs pairs
  .predict(...)          — single-day prediction -> CalibratedForecast
  .predict_day(...)      — day-specific prediction with optional context (ensemble etc.)
  .predict_batch(df)     — batch prediction -> DataFrame with mu, sigma columns
  .predict_batch_day(df) — batch prediction with per-row context columns

The Forecaster knows NOTHING about brackets, markets, or betting.
It only answers: "what distribution describes tomorrow's temperature?"
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import optimize

from .scoring import crps_gaussian

logger = logging.getLogger(__name__)

# Minimum sigma floor (0.5F — tighter is unrealistic for day-ahead temp)
MIN_SIGMA = 0.5

# Minimum samples to fit a (station, month) group
MIN_SAMPLES = 30


@dataclass(frozen=True)
class CalibratedForecast:
    """A probabilistic temperature forecast.

    Downstream consumers (bracket builder, betting engine) use mu and sigma
    to compute bracket probabilities.  The distribution field controls which
    CDF is used: Gaussian (default), Student-t, or empirical percentiles.
    """

    mu: float
    sigma: float
    method: str
    station: str = ""
    month: int = 0
    distribution: str = "gaussian"  # "gaussian" | "student_t" | "empirical"
    df_param: float | None = None  # degrees of freedom for student_t
    percentiles: dict[int, float] | None = None  # raw percentiles for empirical


class Forecaster(ABC):
    """Abstract base class for temperature forecasters."""

    name: str

    @abstractmethod
    def fit(self, train_df: pd.DataFrame) -> None:
        """Learn parameters from historical forecast-observation pairs.

        train_df must have columns: station, forecast_high, observed_high,
        error_high, month, year. Walk-forward responsibility is on the caller.
        """

    @abstractmethod
    def predict(
        self,
        forecast_temp: float,
        station: str,
        month: int,
    ) -> CalibratedForecast:
        """Produce a calibrated Gaussian forecast for a single day."""

    def predict_day(
        self,
        forecast_temp: float,
        station: str,
        month: int,
        forecast_date: date | None = None,
        context: dict | None = None,
    ) -> CalibratedForecast:
        """Day-specific prediction with optional context.

        Context may contain day-specific data like ensemble_spread,
        nbm_percentiles, etc.  Default: falls back to predict().
        Subclasses override this for day-specific sigma.
        """
        return self.predict(forecast_temp, station, month)

    def predict_batch(self, test_df: pd.DataFrame) -> pd.DataFrame:
        """Batch prediction. Returns copy with pred_mu, pred_sigma columns."""
        mus = np.empty(len(test_df))
        sigmas = np.empty(len(test_df))
        for i, (_, row) in enumerate(test_df.iterrows()):
            fc = self.predict(
                forecast_temp=row["forecast_high"],
                station=row["station"],
                month=int(row["month"]),
            )
            mus[i] = fc.mu
            sigmas[i] = fc.sigma
        result = test_df.copy()
        result["pred_mu"] = mus
        result["pred_sigma"] = sigmas
        result["pred_method"] = self.name
        return result

    def predict_batch_day(self, test_df: pd.DataFrame) -> pd.DataFrame:
        """Batch prediction with per-row context from DataFrame columns.

        If test_df has an 'ensemble_spread' column, it is passed as context.
        Falls back to predict_batch() if no context columns are present.
        """
        context_cols = {"ensemble_spread", "ensemble_mean"}
        nbm_pctl_cols = {f"nbm_p{p}" for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]}
        all_context_cols = context_cols | nbm_pctl_cols
        has_context = bool(all_context_cols & set(test_df.columns))

        if not has_context:
            return self.predict_batch(test_df)

        mus = np.empty(len(test_df))
        sigmas = np.empty(len(test_df))
        for i, (_, row) in enumerate(test_df.iterrows()):
            ctx = {}
            for col in context_cols:
                if col in row.index and pd.notna(row[col]):
                    ctx[col] = float(row[col])

            # Build nbm_percentiles from individual columns
            nbm_pctls = {}
            for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
                col = f"nbm_p{p}"
                if col in row.index and pd.notna(row[col]):
                    nbm_pctls[p] = float(row[col])
            if nbm_pctls:
                ctx["nbm_percentiles"] = nbm_pctls

            forecast_date = None
            if "date" in row.index:
                d = row["date"]
                if isinstance(d, str):
                    forecast_date = date.fromisoformat(d)
                elif hasattr(d, "date"):
                    forecast_date = d.date()

            fc = self.predict_day(
                forecast_temp=row["forecast_high"],
                station=row["station"],
                month=int(row["month"]),
                forecast_date=forecast_date,
                context=ctx if ctx else None,
            )
            mus[i] = fc.mu
            sigmas[i] = fc.sigma
        result = test_df.copy()
        result["pred_mu"] = mus
        result["pred_sigma"] = sigmas
        result["pred_method"] = self.name
        return result


class NaiveForecaster(Forecaster):
    """Baseline: mu = raw forecast, sigma = historical std per (station, month).

    Approximates what the market uses. No bias correction.
    """

    name = "Naive"

    def __init__(self) -> None:
        self._sigma: dict[tuple[str, int], float] = {}
        self._global_sigma: float = 3.5

    def fit(self, train_df: pd.DataFrame) -> None:
        grouped = train_df.groupby(["station", "month"])["error_high"]
        for (station, month), errors in grouped:
            if len(errors) >= MIN_SAMPLES:
                self._sigma[(station, int(month))] = max(errors.std(), MIN_SIGMA)
        self._global_sigma = max(train_df["error_high"].std(), MIN_SIGMA)

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        sigma = self._sigma.get((station, month), self._global_sigma)
        return CalibratedForecast(
            mu=forecast_temp, sigma=sigma, method=self.name,
            station=station, month=month,
        )


class BiasForecaster(Forecaster):
    """Phase 1: mu = forecast - monthly mean bias, sigma = historical std.

    Proven insufficient by Session 2 — included as reference point.
    """

    name = "Bias"

    def __init__(self) -> None:
        self._params: dict[tuple[str, int], tuple[float, float]] = {}
        self._global_bias: float = 0.0
        self._global_sigma: float = 3.5

    def fit(self, train_df: pd.DataFrame) -> None:
        grouped = train_df.groupby(["station", "month"])["error_high"]
        for (station, month), errors in grouped:
            if len(errors) >= MIN_SAMPLES:
                self._params[(station, int(month))] = (
                    errors.mean(),
                    max(errors.std(), MIN_SIGMA),
                )
        self._global_bias = train_df["error_high"].mean()
        self._global_sigma = max(train_df["error_high"].std(), MIN_SIGMA)

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        bias, sigma = self._params.get(
            (station, month),
            (self._global_bias, self._global_sigma),
        )
        return CalibratedForecast(
            mu=forecast_temp - bias, sigma=sigma, method=self.name,
            station=station, month=month,
        )


class EMOSForecaster(Forecaster):
    """EMOS without ensemble spread.

    mu = a + b * forecast  (OLS linear regression)
    sigma = CRPS-optimized per (station, month) group

    Since we lack ensemble spread S^2, we optimize sigma directly:
      sigma* = argmin_sigma mean(CRPS(obs, a + b*forecast, sigma))
    using scipy.optimize.minimize_scalar with bounded method.
    """

    name = "EMOS"

    def __init__(self, sigma_bounds: tuple[float, float] = (0.5, 15.0)) -> None:
        self._sigma_bounds = sigma_bounds
        # {(station, month): (a, b, sigma)}
        self._params: dict[tuple[str, int], tuple[float, float, float]] = {}
        self._global_params: tuple[float, float, float] = (0.0, 1.0, 3.5)

    def fit(self, train_df: pd.DataFrame) -> None:
        grouped = train_df.groupby(["station", "month"])
        for (station, month), group in grouped:
            if len(group) < MIN_SAMPLES:
                continue
            params = self._fit_group(group)
            if params is not None:
                self._params[(station, int(month))] = params

        global_params = self._fit_group(train_df)
        if global_params is not None:
            self._global_params = global_params

    def _fit_group(
        self, group_df: pd.DataFrame
    ) -> tuple[float, float, float] | None:
        """Fit (a, b, sigma) for one group.

        Step 1: OLS observed = a + b * forecast
        Step 2: Optimize sigma via CRPS on training residuals
        """
        forecasts = group_df["forecast_high"].values.astype(float)
        observed = group_df["observed_high"].values.astype(float)

        mask = np.isfinite(forecasts) & np.isfinite(observed)
        if mask.sum() < MIN_SAMPLES:
            return None

        f = forecasts[mask]
        o = observed[mask]

        # Step 1: OLS  observed = b * forecast + a
        try:
            b, a = np.polyfit(f, o, 1)
        except (np.linalg.LinAlgError, ValueError):
            return None

        mu_train = a + b * f

        # Step 2: optimize sigma to minimize mean CRPS
        def objective(sigma: float) -> float:
            sigma_arr = np.full_like(o, sigma)
            return crps_gaussian(o, mu_train, sigma_arr).mean()

        result = optimize.minimize_scalar(
            objective,
            bounds=self._sigma_bounds,
            method="bounded",
        )

        if result.success:
            sigma = max(result.x, MIN_SIGMA)
        else:
            sigma = max(float(np.std(o - mu_train)), MIN_SIGMA)

        return (float(a), float(b), sigma)

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        a, b, sigma = self._params.get(
            (station, month),
            self._global_params,
        )
        mu = a + b * forecast_temp
        return CalibratedForecast(
            mu=mu, sigma=sigma, method=self.name,
            station=station, month=month,
        )


class CRPSigmaForecaster(Forecaster):
    """Sigma-only calibration: mu = raw forecast, sigma = CRPS-optimized.

    Isolates the sigma calibration effect from mu correction.
    Hypothesis: the market's mu (raw forecast) is already optimal;
    only the uncertainty estimate needs tuning.
    """

    name = "CRPSigma"

    def __init__(self, sigma_bounds: tuple[float, float] = (0.5, 15.0)) -> None:
        self._sigma_bounds = sigma_bounds
        self._sigma: dict[tuple[str, int], float] = {}
        self._global_sigma: float = 3.5

    def fit(self, train_df: pd.DataFrame) -> None:
        grouped = train_df.groupby(["station", "month"])
        for (station, month), group in grouped:
            if len(group) < MIN_SAMPLES:
                continue
            sigma = self._fit_sigma(group)
            if sigma is not None:
                self._sigma[(station, int(month))] = sigma

        global_sigma = self._fit_sigma(train_df)
        if global_sigma is not None:
            self._global_sigma = global_sigma

    def _fit_sigma(self, group_df: pd.DataFrame) -> float | None:
        """Find sigma* = argmin mean(CRPS(obs, forecast, sigma))."""
        forecasts = group_df["forecast_high"].values.astype(float)
        observed = group_df["observed_high"].values.astype(float)

        mask = np.isfinite(forecasts) & np.isfinite(observed)
        if mask.sum() < MIN_SAMPLES:
            return None

        f = forecasts[mask]
        o = observed[mask]

        def objective(sigma: float) -> float:
            return crps_gaussian(o, f, np.full_like(o, sigma)).mean()

        result = optimize.minimize_scalar(
            objective,
            bounds=self._sigma_bounds,
            method="bounded",
        )

        if result.success:
            return max(result.x, MIN_SIGMA)
        return max(float(np.std(o - f)), MIN_SIGMA)

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        sigma = self._sigma.get((station, month), self._global_sigma)
        return CalibratedForecast(
            mu=forecast_temp, sigma=sigma, method=self.name,
            station=station, month=month,
        )


class EnsembleForecaster(Forecaster):
    """Day-specific sigma from ensemble spread.

    Uses the ensemble standard deviation (from GEFS, ECMWF, etc.) as a
    day-specific proxy for forecast uncertainty.  A calibration factor
    maps raw spread to optimal sigma:
        sigma = ensemble_spread * cal_factor

    On .fit():
      - If train_df has 'ensemble_spread' column, calibrate cal_factor
        by minimizing CRPS on (forecast, obs, spread * factor) triples.
      - Otherwise, learn CRPSigma-style fallback sigma per (station, month).

    On .predict_day():
      - If context has 'ensemble_spread', use day-specific sigma.
      - Otherwise, use historical fallback sigma.
    """

    name = "Ensemble"

    def __init__(
        self,
        sigma_bounds: tuple[float, float] = (0.5, 15.0),
        cal_factor_bounds: tuple[float, float] = (0.5, 3.0),
        default_cal_factor: float = 1.0,
    ) -> None:
        self._sigma_bounds = sigma_bounds
        self._cal_factor_bounds = cal_factor_bounds
        self._cal_factor: float = default_cal_factor
        self._fallback_sigma: dict[tuple[str, int], float] = {}
        self._global_sigma: float = 3.5
        self._has_ensemble_cal: bool = False

    def fit(self, train_df: pd.DataFrame) -> None:
        # Always learn fallback sigma (CRPSigma-style)
        self._fit_fallback(train_df)

        # If ensemble spread is available, calibrate the factor
        if "ensemble_spread" in train_df.columns:
            self._fit_cal_factor(train_df)

    def _fit_fallback(self, train_df: pd.DataFrame) -> None:
        """Learn historical sigma per (station, month) as fallback."""
        grouped = train_df.groupby(["station", "month"])
        for (station, month), group in grouped:
            if len(group) < MIN_SAMPLES:
                continue
            forecasts = group["forecast_high"].values.astype(float)
            observed = group["observed_high"].values.astype(float)
            mask = np.isfinite(forecasts) & np.isfinite(observed)
            if mask.sum() < MIN_SAMPLES:
                continue

            f, o = forecasts[mask], observed[mask]

            def objective(sigma: float) -> float:
                return crps_gaussian(o, f, np.full_like(o, sigma)).mean()

            result = optimize.minimize_scalar(
                objective, bounds=self._sigma_bounds, method="bounded",
            )
            if result.success:
                self._fallback_sigma[(station, int(month))] = max(result.x, MIN_SIGMA)

        # Global fallback
        f_all = train_df["forecast_high"].values.astype(float)
        o_all = train_df["observed_high"].values.astype(float)
        mask = np.isfinite(f_all) & np.isfinite(o_all)
        if mask.sum() >= MIN_SAMPLES:

            def obj_global(sigma: float) -> float:
                return crps_gaussian(
                    o_all[mask], f_all[mask], np.full(mask.sum(), sigma)
                ).mean()

            result = optimize.minimize_scalar(
                obj_global, bounds=self._sigma_bounds, method="bounded",
            )
            if result.success:
                self._global_sigma = max(result.x, MIN_SIGMA)

    def _fit_cal_factor(self, train_df: pd.DataFrame) -> None:
        """Calibrate spread-to-sigma mapping: sigma = spread * factor."""
        df = train_df.dropna(subset=["ensemble_spread", "forecast_high", "observed_high"])
        if len(df) < MIN_SAMPLES:
            logger.info("Not enough ensemble data for calibration, using default factor")
            return

        spreads = df["ensemble_spread"].values.astype(float)
        forecasts = df["forecast_high"].values.astype(float)
        observed = df["observed_high"].values.astype(float)

        def objective(factor: float) -> float:
            sigmas = np.maximum(spreads * factor, MIN_SIGMA)
            return crps_gaussian(observed, forecasts, sigmas).mean()

        result = optimize.minimize_scalar(
            objective, bounds=self._cal_factor_bounds, method="bounded",
        )
        if result.success:
            self._cal_factor = float(result.x)
            self._has_ensemble_cal = True
            logger.info(f"Ensemble cal_factor calibrated: {self._cal_factor:.3f}")
        else:
            logger.warning("Ensemble cal_factor optimization failed, using default")

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        sigma = self._fallback_sigma.get((station, month), self._global_sigma)
        return CalibratedForecast(
            mu=forecast_temp, sigma=sigma, method=self.name,
            station=station, month=month,
        )

    def predict_day(
        self,
        forecast_temp: float,
        station: str,
        month: int,
        forecast_date: date | None = None,
        context: dict | None = None,
    ) -> CalibratedForecast:
        if context and "ensemble_spread" in context:
            raw_spread = context["ensemble_spread"]
            sigma = max(raw_spread * self._cal_factor, MIN_SIGMA)
        else:
            sigma = self._fallback_sigma.get((station, month), self._global_sigma)
        return CalibratedForecast(
            mu=forecast_temp, sigma=sigma, method=self.name,
            station=station, month=month,
        )


class NBMForecaster(Forecaster):
    """Day-specific sigma and empirical CDF from NBM percentiles.

    When NBM percentiles are available (via context dict), uses:
      - mu = P50 (NBM median, pre-calibrated by NOAA)
      - sigma = (P90-P10) / 2.56
      - distribution = "empirical" with full percentile dict
        → bracket_builder uses PchipInterpolator CDF (no parametric assumption)

    Fallback (no NBM data): CRPSigma-style historical sigma per (station, month).

    Advantages over EnsembleForecaster:
      - Pre-calibrated by NOAA (no cal_factor needed)
      - Empirical CDF captures non-Gaussian shape (asymmetric tails)
      - 200+ effective ensemble members vs GEFS's 30
    """

    name = "NBM"

    def __init__(self, sigma_bounds: tuple[float, float] = (0.5, 15.0)) -> None:
        self._sigma_bounds = sigma_bounds
        self._fallback_sigma: dict[tuple[str, int], float] = {}
        self._global_sigma: float = 3.5

    def fit(self, train_df: pd.DataFrame) -> None:
        """Learn fallback sigma from historical data (CRPSigma-style)."""
        grouped = train_df.groupby(["station", "month"])
        for (station, month), group in grouped:
            if len(group) < MIN_SAMPLES:
                continue
            forecasts = group["forecast_high"].values.astype(float)
            observed = group["observed_high"].values.astype(float)
            mask = np.isfinite(forecasts) & np.isfinite(observed)
            if mask.sum() < MIN_SAMPLES:
                continue

            f, o = forecasts[mask], observed[mask]

            def objective(sigma: float) -> float:
                return crps_gaussian(o, f, np.full_like(o, sigma)).mean()

            result = optimize.minimize_scalar(
                objective, bounds=self._sigma_bounds, method="bounded",
            )
            if result.success:
                self._fallback_sigma[(station, int(month))] = max(result.x, MIN_SIGMA)

        # Global fallback
        f_all = train_df["forecast_high"].values.astype(float)
        o_all = train_df["observed_high"].values.astype(float)
        mask = np.isfinite(f_all) & np.isfinite(o_all)
        if mask.sum() >= MIN_SAMPLES:

            def obj_global(sigma: float) -> float:
                return crps_gaussian(
                    o_all[mask], f_all[mask], np.full(mask.sum(), sigma)
                ).mean()

            result = optimize.minimize_scalar(
                obj_global, bounds=self._sigma_bounds, method="bounded",
            )
            if result.success:
                self._global_sigma = max(result.x, MIN_SIGMA)

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        """Fallback prediction (no NBM context)."""
        sigma = self._fallback_sigma.get((station, month), self._global_sigma)
        return CalibratedForecast(
            mu=forecast_temp, sigma=sigma, method=self.name,
            station=station, month=month,
        )

    def predict_day(
        self,
        forecast_temp: float,
        station: str,
        month: int,
        forecast_date: date | None = None,
        context: dict | None = None,
    ) -> CalibratedForecast:
        """Day-specific prediction using NBM percentiles when available."""
        if context and "nbm_percentiles" in context:
            pctls = context["nbm_percentiles"]
            mu = pctls.get(50, forecast_temp)
            if 90 in pctls and 10 in pctls:
                sigma = max((pctls[90] - pctls[10]) / 2.56, MIN_SIGMA)
            else:
                sigma = self._fallback_sigma.get((station, month), self._global_sigma)
            return CalibratedForecast(
                mu=mu, sigma=sigma, method=self.name,
                station=station, month=month,
                distribution="empirical",
                percentiles=pctls,
            )
        return self.predict(forecast_temp, station, month)


class MultiModelForecaster(Forecaster):
    """Day-specific empirical CDF from pooled multi-model ensemble members.

    International equivalent of NBMForecaster.  Instead of NOAA NBM
    percentiles (CONUS-only), uses ~179 members from 6 global models
    (ECMWF IFS, GEFS, ICON, GEM, UKMO, BOM) fetched via Open-Meteo.

    When multi-model members are available (via context dict), uses:
      - mu = P50 of pooled members
      - sigma = (P90-P10) / 2.56
      - distribution = "empirical" with computed percentile dict
        -> bracket_builder uses PchipInterpolator CDF

    Fallback (no live data): historical sigma per (city, month)
    learned from Open-Meteo Archive observations.
    """

    name = "MultiModel"

    def __init__(self, sigma_bounds: tuple[float, float] = (0.5, 15.0)) -> None:
        self._sigma_bounds = sigma_bounds
        self._fallback_sigma: dict[tuple[str, int], float] = {}
        self._global_sigma: float = 3.5

    def fit(self, train_df: pd.DataFrame) -> None:
        """Learn fallback sigma from historical obs (CRPSigma-style).

        train_df must have: station (city slug), forecast_high, observed_high,
        month.  For international cities, forecast_high = ensemble mean and
        observed_high = ERA5 daily max from Open-Meteo Archive.
        """
        grouped = train_df.groupby(["station", "month"])
        for (station, month), group in grouped:
            if len(group) < MIN_SAMPLES:
                continue
            forecasts = group["forecast_high"].values.astype(float)
            observed = group["observed_high"].values.astype(float)
            mask = np.isfinite(forecasts) & np.isfinite(observed)
            if mask.sum() < MIN_SAMPLES:
                continue

            f, o = forecasts[mask], observed[mask]

            def objective(sigma: float) -> float:
                return crps_gaussian(o, f, np.full_like(o, sigma)).mean()

            result = optimize.minimize_scalar(
                objective, bounds=self._sigma_bounds, method="bounded",
            )
            if result.success:
                self._fallback_sigma[(station, int(month))] = max(result.x, MIN_SIGMA)

        # Global fallback
        f_all = train_df["forecast_high"].values.astype(float)
        o_all = train_df["observed_high"].values.astype(float)
        mask = np.isfinite(f_all) & np.isfinite(o_all)
        if mask.sum() >= MIN_SAMPLES:

            def obj_global(sigma: float) -> float:
                return crps_gaussian(
                    o_all[mask], f_all[mask], np.full(mask.sum(), sigma)
                ).mean()

            result = optimize.minimize_scalar(
                obj_global, bounds=self._sigma_bounds, method="bounded",
            )
            if result.success:
                self._global_sigma = max(result.x, MIN_SIGMA)

    def predict(
        self, forecast_temp: float, station: str, month: int
    ) -> CalibratedForecast:
        """Fallback prediction (no multi-model context)."""
        sigma = self._fallback_sigma.get((station, month), self._global_sigma)
        return CalibratedForecast(
            mu=forecast_temp, sigma=sigma, method=self.name,
            station=station, month=month,
        )

    def predict_day(
        self,
        forecast_temp: float,
        station: str,
        month: int,
        forecast_date: date | None = None,
        context: dict | None = None,
    ) -> CalibratedForecast:
        """Day-specific prediction using pooled multi-model members."""
        if context and "multimodel_members" in context:
            members = np.array(context["multimodel_members"])
            if len(members) >= 3:
                pctls = {
                    p: float(np.percentile(members, p))
                    for p in [1, 5, 10, 25, 50, 75, 90, 95, 99]
                }
                mu = pctls[50]
                sigma = max((pctls[90] - pctls[10]) / 2.56, MIN_SIGMA)
                return CalibratedForecast(
                    mu=mu, sigma=sigma, method=self.name,
                    station=station, month=month,
                    distribution="empirical",
                    percentiles=pctls,
                )
        return self.predict(forecast_temp, station, month)
