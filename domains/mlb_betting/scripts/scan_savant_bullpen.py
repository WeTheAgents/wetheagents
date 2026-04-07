"""Quick signal scan: Statcast bullpen quality mismatch + fatigue.

Merges Savant bullpen features with odds data and looks for
high-volume profitable signals.

Usage:
    python scripts/scan_savant_bullpen.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.fetch_2026.team_mapping import ESPN_TO_CODE
from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons

# Explicit mapping: our canonical odds code → Savant/Statcast code.
# Savant uses MLB-style abbreviations; our odds data uses sports-statistics.com codes.
CODE_TO_SAVANT = {
    "ARI": "AZ",   "ATL": "ATL",  "BAL": "BAL",  "BOS": "BOS",
    "CHC": "CHC",  "CHW": "CWS",  "CIN": "CIN",  "CLE": "CLE",
    "COL": "COL",  "DET": "DET",  "HOU": "HOU",  "KCR": "KC",
    "LAA": "LAA",  "LAD": "LAD",  "MIA": "MIA",  "MIL": "MIL",
    "MIN": "MIN",  "NYM": "NYM",  "NYY": "NYY",  "OAK": "ATH",
    "PHI": "PHI",  "PIT": "PIT",  "SDP": "SD",   "SEA": "SEA",
    "SFG": "SF",   "STL": "STL",  "TBR": "TB",   "TEX": "TEX",
    "TOR": "TOR",  "WSN": "WSH",
}


def load_savant_features() -> pd.DataFrame:
    """Load Savant bullpen features for all available seasons."""
    savant_dir = Path(__file__).parent.parent / "data" / "processed" / "savant"
    path = savant_dir / "savant_bullpen_features.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Run savant_bullpen.py first: {path}")
    return pd.read_parquet(path)


def merge_savant_to_games(games: pd.DataFrame, savant: pd.DataFrame) -> pd.DataFrame:
    """Merge Savant bullpen features to games for both home and away teams."""
    g = games.copy()

    # Map our team codes to Savant codes.
    g["home_savant"] = g["home_team"].map(CODE_TO_SAVANT)
    g["away_savant"] = g["away_team"].map(CODE_TO_SAVANT)

    # Merge home bullpen features.
    home_feats = savant.copy()
    home_cols = {c: f"home_{c}" for c in home_feats.columns if c.startswith("bp_sc_")}
    home_feats = home_feats.rename(columns=home_cols)
    home_feats = home_feats.rename(columns={"team": "home_savant", "game_date": "date"})

    g = g.merge(
        home_feats.drop(columns=["season"], errors="ignore"),
        on=["home_savant", "date"],
        how="left",
    )

    # Merge away bullpen features.
    away_feats = savant.copy()
    away_cols = {c: f"away_{c}" for c in away_feats.columns if c.startswith("bp_sc_")}
    away_feats = away_feats.rename(columns=away_cols)
    away_feats = away_feats.rename(columns={"team": "away_savant", "game_date": "date"})

    g = g.merge(
        away_feats.drop(columns=["season"], errors="ignore"),
        on=["away_savant", "date"],
        how="left",
    )

    # Compute mismatch features (home minus away).
    g["bp_sc_xwoba_diff"] = g["home_bp_sc_xwoba_std"] - g["away_bp_sc_xwoba_std"]
    g["bp_sc_barrel_diff"] = g["home_bp_sc_barrel_std"] - g["away_bp_sc_barrel_std"]
    g["bp_sc_xwoba_15g_diff"] = g["home_bp_sc_xwoba_15g"] - g["away_bp_sc_xwoba_15g"]
    g["bp_sc_fatigue_diff"] = (
        g["home_bp_sc_barrel_delta_3d"] - g["away_bp_sc_barrel_delta_3d"]
    )

    return g


def scan_signal(
    games: pd.DataFrame,
    feature: str,
    *,
    thresholds: list[float],
    bet_side: str = "away",
    bet_type: str = "ml",
    min_games: int = 50,
) -> pd.DataFrame:
    """Scan a feature across thresholds for profitability.

    bet_side: "away" or "home" — which side to bet on when signal triggers.
    bet_type: "ml" (moneyline) or "rl" (run line +1.5).
    """
    results = []
    for threshold in thresholds:
        if bet_side == "away":
            # Positive diff = home bullpen worse → bet away
            mask = games[feature] >= threshold
        else:
            mask = games[feature] <= -threshold

        subset = games[mask].dropna(subset=[feature])
        n = len(subset)
        if n < min_games:
            continue

        if bet_type == "ml":
            # Away wins.
            wins = (subset["away_final"] > subset["home_final"]).sum()
            odds_col = "away_decimal_odds"
        else:
            # Run line +1.5 for away: away_final + 1.5 > home_final
            wins = ((subset["away_final"] + 1.5) > subset["home_final"]).sum()
            odds_col = None  # No RL odds in our data for this

        win_rate = wins / n if n > 0 else 0

        # ROI calculation (using actual ML odds).
        if odds_col and odds_col in subset.columns:
            # Flat-bet ROI: bet 1 unit on each game.
            profit = subset.apply(
                lambda r: (r[odds_col] - 1) if r["away_final"] > r["home_final"] else -1,
                axis=1,
            ).sum()
            roi = profit / n
        else:
            roi = np.nan

        per_season = n / subset["season"].nunique() if subset["season"].nunique() > 0 else n

        results.append({
            "feature": feature,
            "threshold": threshold,
            "bet_side": bet_side,
            "bet_type": bet_type,
            "games": n,
            "games_per_season": round(per_season, 1),
            "wins": wins,
            "win_rate": round(win_rate, 4),
            "roi": round(roi, 4) if not np.isnan(roi) else np.nan,
        })

    return pd.DataFrame(results)


def main() -> None:
    print("Loading games...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    # Filter to bettable games.
    bettable = games[~games["involves_col"] & ~games["is_extreme_line"]].copy()

    # Load and merge Savant features.
    print("Loading Savant bullpen features...")
    savant = load_savant_features()
    available_seasons = sorted(savant["season"].unique())
    print(f"Available seasons: {available_seasons}")

    # Filter games to Savant seasons.
    bettable = bettable[bettable["season"].isin(available_seasons)]
    print(f"Games in Savant seasons: {len(bettable)}")

    merged = merge_savant_to_games(bettable, savant)

    # Check merge coverage.
    has_both = merged["home_bp_sc_xwoba_std"].notna() & merged["away_bp_sc_xwoba_std"].notna()
    print(f"Games with both home+away Savant features: {has_both.sum()} / {len(merged)} = {100*has_both.mean():.1f}%")

    merged = merged[has_both].copy()

    print(f"\n{'='*80}")
    print("SIGNAL SCAN: Statcast Bullpen Quality Mismatch")
    print(f"{'='*80}")

    # -------------------------------------------------------------------
    # Signal 1: xwOBA mismatch (STD) — bet against worse bullpen
    # -------------------------------------------------------------------
    print("\n--- xwOBA STD Mismatch (bet AWAY when home BP worse) ---")
    xwoba_thresholds = [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]
    result_xwoba = scan_signal(merged, "bp_sc_xwoba_diff", thresholds=xwoba_thresholds, bet_side="away")
    if len(result_xwoba):
        print(result_xwoba.to_string(index=False))

    print("\n--- xwOBA STD Mismatch (bet HOME when away BP worse) ---")
    result_xwoba_home = scan_signal(merged, "bp_sc_xwoba_diff", thresholds=xwoba_thresholds, bet_side="home")
    if len(result_xwoba_home):
        print(result_xwoba_home.to_string(index=False))

    # -------------------------------------------------------------------
    # Signal 2: xwOBA 15-game rolling mismatch
    # -------------------------------------------------------------------
    print("\n--- xwOBA 15g Rolling Mismatch (bet AWAY when home BP worse) ---")
    result_xwoba15 = scan_signal(merged, "bp_sc_xwoba_15g_diff", thresholds=xwoba_thresholds, bet_side="away")
    if len(result_xwoba15):
        print(result_xwoba15.to_string(index=False))

    # -------------------------------------------------------------------
    # Signal 3: Barrel rate mismatch
    # -------------------------------------------------------------------
    print("\n--- Barrel Rate STD Mismatch (bet AWAY when home BP worse) ---")
    barrel_thresholds = [0.003, 0.005, 0.008, 0.01, 0.015, 0.02]
    result_barrel = scan_signal(merged, "bp_sc_barrel_diff", thresholds=barrel_thresholds, bet_side="away")
    if len(result_barrel):
        print(result_barrel.to_string(index=False))

    # -------------------------------------------------------------------
    # Signal 4: Fatigue mismatch (barrel delta diff)
    # -------------------------------------------------------------------
    print("\n--- Fatigue Mismatch (bet AWAY when home BP more fatigued) ---")
    fatigue_thresholds = [0.01, 0.015, 0.02, 0.03, 0.04, 0.05]
    result_fatigue = scan_signal(merged, "bp_sc_fatigue_diff", thresholds=fatigue_thresholds, bet_side="away")
    if len(result_fatigue):
        print(result_fatigue.to_string(index=False))

    # -------------------------------------------------------------------
    # Signal 5: Combined — quality mismatch + fatigue on same side
    # -------------------------------------------------------------------
    print(f"\n{'='*80}")
    print("COMBINED SIGNALS")
    print(f"{'='*80}")

    for xwoba_thresh in [0.01, 0.02, 0.03]:
        for fatigue_thresh in [0.01, 0.02]:
            mask = (merged["bp_sc_xwoba_diff"] >= xwoba_thresh) & (merged["bp_sc_fatigue_diff"] >= fatigue_thresh)
            subset = merged[mask].dropna(subset=["bp_sc_xwoba_diff", "bp_sc_fatigue_diff"])
            n = len(subset)
            if n < 20:
                continue
            wins = (subset["away_final"] > subset["home_final"]).sum()
            wr = wins / n

            if "away_decimal_odds" in subset.columns:
                profit = subset.apply(
                    lambda r: (r["away_decimal_odds"] - 1) if r["away_final"] > r["home_final"] else -1,
                    axis=1,
                ).sum()
                roi = profit / n
            else:
                roi = np.nan

            per_season = n / subset["season"].nunique() if subset["season"].nunique() > 0 else n
            print(f"  xwOBA>={xwoba_thresh} + fatigue>={fatigue_thresh}: "
                  f"n={n} ({per_season:.0f}/season), WR={wr:.3f}, ROI={roi:+.3f}")


if __name__ == "__main__":
    main()
