"""Common types + helpers shared across strategies.

The ``Pick`` dataclass is the unit each strategy returns. The
``add_derived_for_strategies`` helper computes the fav-oriented diff
columns that several strategies need but ``build_all_features`` does
not produce on its own (those normally live inside ``build_spec_features``,
which we cannot use in production because it drops April).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Pick:
    """A single betting recommendation.

    ``historical_p`` is the cover/win rate from the source session report.
    The picks generator shrinks it (see plans/§11.1 #14) before computing
    Kelly so we don't over-bet a sample-mean estimate.
    """

    pick_id: str
    date: date
    away: str
    home: str
    market: str          # "ML_dog" | "RL_+1.5" | "RL_-1.5"
    side: str            # "away" | "home"
    tier: str
    historical_p: float
    ref_odds_espn: float | None
    reason: str
    feature_snapshot: dict[str, Any]
    also_qualified: list[str] = field(default_factory=list)

    @classmethod
    def make(
        cls,
        *,
        target_date: date,
        away: str,
        home: str,
        market: str,
        side: str,
        tier: str,
        historical_p: float,
        ref_odds_espn: float | None,
        reason: str,
        feature_snapshot: dict[str, Any],
    ) -> "Pick":
        # Stable id so a re-run on the same day produces the same pick_id.
        raw = f"{target_date}|{away}|{home}|{market}|{side}|{tier}"
        pid = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
        return cls(
            pick_id=pid,
            date=target_date,
            away=away,
            home=home,
            market=market,
            side=side,
            tier=tier,
            historical_p=historical_p,
            ref_odds_espn=ref_odds_espn,
            reason=reason,
            feature_snapshot=feature_snapshot,
        )


def add_derived_for_strategies(df: pd.DataFrame) -> pd.DataFrame:
    """Add fav-oriented diff columns + workload gap that strategies expect.

    These columns are normally added inside ``build_spec_features`` (which
    drops April and so can't be used for live picks). We replicate the
    parts we need on the unfiltered ``build_all_features`` output.

    Adds (only if the underlying source columns exist):
      - fav_implied_prob          (max of home/away implied prob)
      - fav_is_home               (bool — True iff home is the favorite)
      - fav_starter_fip_diff      (signed so negative = fav has better SP)
      - fav_power_rate_diff       (signed so positive = fav more explosive)
      - bp_workload_gap           (= bp_ip_3d_home - bp_ip_3d_away)
      - starter_depth_diff_short  (= home_sp_ip_per_start_short - away_..., per Decision §9.1)
      - starter_depth_diff        (LONG window — kept for parity with backtest)

    Idempotent: re-running on a frame that already has these columns is a
    no-op (we always recompute, never rely on prior values).
    """
    df = df.copy()

    # Implied prob: derived from close_ml via add_derived_odds(). Both should
    # be present after the standard load_all_seasons → add_derived_odds chain.
    if "home_implied_prob" in df.columns and "away_implied_prob" in df.columns:
        # In a 2-way market the two implieds usually sum to slightly more
        # than 1.0 (vig). The fav is the side with the higher implied.
        df["fav_implied_prob"] = np.maximum(
            df["home_implied_prob"], df["away_implied_prob"]
        )
        df["fav_is_home"] = df["home_implied_prob"] >= df["away_implied_prob"]
    else:
        df["fav_implied_prob"] = np.nan
        df["fav_is_home"] = pd.NA

    # Sign-flip helper: positive when (home - away) is in the fav's favor.
    if "fav_is_home" in df.columns:
        flip = np.where(df["fav_is_home"].fillna(False), 1.0, -1.0)
    else:
        flip = np.ones(len(df))

    # Starter FIP diff (short window — what Sess 25 uses for live filter).
    if "home_sp_fip_short" in df.columns and "away_sp_fip_short" in df.columns:
        raw = df["home_sp_fip_short"] - df["away_sp_fip_short"]
        df["fav_starter_fip_diff"] = raw * flip

    # Power rate diff (Sess 25 attack-quality filter).
    if "power_rate_home" in df.columns and "power_rate_away" in df.columns:
        raw_pr = df["power_rate_home"] - df["power_rate_away"]
        df["fav_power_rate_diff"] = raw_pr * flip

    # Bullpen workload gap (Tier 2 trigger).
    if "bp_ip_3d_home" in df.columns and "bp_ip_3d_away" in df.columns:
        df["bp_workload_gap"] = df["bp_ip_3d_home"] - df["bp_ip_3d_away"]

    # Starter depth diff. Decision §9.1: use SHORT window in production
    # (long window won't be valid until ~mid-June). The long-window column
    # is also added for parity with the Sess 27 backtest scripts.
    if (
        "home_sp_ip_per_start_short" in df.columns
        and "away_sp_ip_per_start_short" in df.columns
    ):
        df["starter_depth_diff_short"] = (
            df["home_sp_ip_per_start_short"] - df["away_sp_ip_per_start_short"]
        )
    if (
        "home_sp_ip_per_start_long" in df.columns
        and "away_sp_ip_per_start_long" in df.columns
    ):
        df["starter_depth_diff"] = (
            df["home_sp_ip_per_start_long"] - df["away_sp_ip_per_start_long"]
        )

    return df


def feature_snapshot(row: pd.Series, columns: list[str]) -> dict[str, Any]:
    """Extract a JSON-friendly snapshot of feature values for a single game."""
    out: dict[str, Any] = {}
    for col in columns:
        if col not in row.index:
            continue
        val = row[col]
        if pd.isna(val):
            out[col] = None
        elif isinstance(val, (np.integer, np.floating, np.bool_)):
            out[col] = val.item()
        elif isinstance(val, (int, float, bool, str)):
            out[col] = val
        else:
            out[col] = str(val)
    return out
