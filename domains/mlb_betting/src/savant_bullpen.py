"""Statcast bullpen features from Baseball Savant pitcher game logs.

Computes two categories of bullpen metrics per team per game:
1. **Fatigue** (3-day rolling): whiff%, barrel rate, hard hit%, exit velo
   — plus delta vs season-to-date average (leading fatigue indicator)
2. **Quality** (season-to-date + 15-game rolling): xwOBA, barrel rate
   — luck-adjusted bullpen quality for mismatch detection

All metrics are strictly ENTERING-game (anti-leakage).
Relievers are identified from Statcast data directly (min_inning > 1).

Output: data/processed/savant/savant_bullpen_features.parquet
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

SAVANT_DIR = Path(__file__).parent.parent / "data" / "processed" / "savant"
OUTPUT_DIR = SAVANT_DIR
SEASONS = [2015, 2016, 2017, 2018, 2019, 2021, 2022, 2023, 2024, 2025]


def load_reliever_games(seasons: list[int] | None = None) -> pd.DataFrame:
    """Load Savant pitcher-game data and filter to relievers only."""
    seasons = seasons or SEASONS
    frames = []
    for year in seasons:
        path = SAVANT_DIR / f"pitcher_games_{year}.parquet"
        if not path.exists():
            logger.warning("Missing Savant data for %d — skipping", year)
            continue
        df = pd.read_parquet(path)
        frames.append(df)

    if not frames:
        raise FileNotFoundError("No Savant pitcher-game parquets found")

    all_pg = pd.concat(frames, ignore_index=True)
    logger.info("Loaded %d pitcher-game rows across %d seasons", len(all_pg), len(frames))

    # Keep relievers only (did not pitch in inning 1).
    relievers = all_pg[~all_pg["is_starter"]].copy()
    logger.info("Relievers: %d rows (%d starters excluded)", len(relievers), len(all_pg) - len(relievers))

    # Ensure game_date is datetime.
    relievers["game_date"] = pd.to_datetime(relievers["game_date"])
    return relievers


def _aggregate_team_game(relievers: pd.DataFrame) -> pd.DataFrame:
    """Aggregate reliever Statcast metrics to team-game level, weighted by batted balls."""
    df = relievers.copy()

    # For rate stats, we need IP-weighted or BB-weighted aggregation.
    # Barrel/hard-hit/xwoba are per batted ball — weight by batted_balls.
    # Whiff is per swing — weight by swings.
    grp = df.groupby(["pitcher_team", "season", "game_date", "game_pk"], sort=False)

    agg = grp.agg(
        bp_sc_pitches=("total_pitches", "sum"),
        bp_sc_swings=("swings", "sum"),
        bp_sc_whiffs=("whiffs", "sum"),
        bp_sc_batted=("batted_balls", "sum"),
        bp_sc_hard_hits=("hard_hits", "sum"),
        bp_sc_barrels=("barrels", "sum"),
        # For exit velo: need sum of (exit_velo * batted_balls) / total batted_balls.
        # Approximate via weighted sum from pre-aggregated pitcher data.
        bp_sc_ev_weighted=("avg_exit_velo", lambda x: np.nansum(
            x * df.loc[x.index, "batted_balls"]
        )),
        bp_sc_ev_denom=("batted_balls", "sum"),
        # xwoba weighted by batted balls similarly
        bp_sc_xwoba_weighted=("xwoba", lambda x: np.nansum(
            x * df.loc[x.index, "batted_balls"]
        )),
        bp_sc_n_relievers=("pitcher", "nunique"),
    ).reset_index()

    # Compute rates.
    agg["bp_sc_whiff_pct"] = agg["bp_sc_whiffs"] / agg["bp_sc_swings"].replace(0, np.nan)
    agg["bp_sc_hard_hit_pct"] = agg["bp_sc_hard_hits"] / agg["bp_sc_batted"].replace(0, np.nan)
    agg["bp_sc_barrel_pct"] = agg["bp_sc_barrels"] / agg["bp_sc_batted"].replace(0, np.nan)
    agg["bp_sc_avg_exit_velo"] = agg["bp_sc_ev_weighted"] / agg["bp_sc_ev_denom"].replace(0, np.nan)
    agg["bp_sc_xwoba"] = agg["bp_sc_xwoba_weighted"] / agg["bp_sc_ev_denom"].replace(0, np.nan)

    # Drop intermediate columns.
    agg = agg.drop(columns=["bp_sc_ev_weighted", "bp_sc_ev_denom", "bp_sc_xwoba_weighted"])

    # Rename for consistency.
    agg = agg.rename(columns={"pitcher_team": "team"})
    return agg


def _compute_fatigue_features(
    team_game: pd.DataFrame,
    *,
    fatigue_days: int = 3,
) -> pd.DataFrame:
    """Compute 3-day rolling Statcast bullpen metrics + delta vs season average.

    All metrics are entering-game: only prior games are used.
    """
    df = team_game.sort_values(["team", "season", "game_date"]).reset_index(drop=True)

    results = []
    for (team, season), grp in df.groupby(["team", "season"], sort=False):
        grp = grp.sort_values("game_date").reset_index(drop=True)
        n = len(grp)

        # Arrays for accumulation.
        dates = grp["game_date"].values
        whiffs = grp["bp_sc_whiffs"].values.astype(float)
        swings = grp["bp_sc_swings"].values.astype(float)
        barrels = grp["bp_sc_barrels"].values.astype(float)
        hard_hits = grp["bp_sc_hard_hits"].values.astype(float)
        batted = grp["bp_sc_batted"].values.astype(float)
        xwoba_game = grp["bp_sc_xwoba"].values.astype(float)
        ev_game = grp["bp_sc_avg_exit_velo"].values.astype(float)

        # Running season totals for STD.
        cum_whiffs = np.cumsum(whiffs)
        cum_swings = np.cumsum(swings)
        cum_barrels = np.cumsum(barrels)
        cum_hard_hits = np.cumsum(hard_hits)
        cum_batted = np.cumsum(batted)

        for i in range(n):
            row = {
                "team": team,
                "season": season,
                "game_date": dates[i],
            }

            if i == 0:
                # No prior data — all NaN.
                for col in [
                    "bp_sc_whiff_3d", "bp_sc_barrel_3d", "bp_sc_hard_hit_3d",
                    "bp_sc_exit_velo_3d", "bp_sc_xwoba_3d",
                    "bp_sc_whiff_delta_3d", "bp_sc_barrel_delta_3d",
                    "bp_sc_xwoba_std", "bp_sc_barrel_std",
                    "bp_sc_xwoba_15g", "bp_sc_barrel_15g",
                ]:
                    row[col] = np.nan
                results.append(row)
                continue

            game_date = pd.Timestamp(dates[i])
            cutoff = game_date - pd.Timedelta(days=fatigue_days)

            # 3-day window: games in [cutoff, game_date) — strictly before current game.
            mask_3d = np.array([
                pd.Timestamp(dates[j]) >= cutoff and j < i
                for j in range(n)
            ])

            if mask_3d.any():
                w3 = whiffs[mask_3d].sum()
                s3 = swings[mask_3d].sum()
                row["bp_sc_whiff_3d"] = w3 / s3 if s3 > 0 else np.nan

                b3 = barrels[mask_3d].sum()
                bb3 = batted[mask_3d].sum()
                row["bp_sc_barrel_3d"] = b3 / bb3 if bb3 > 0 else np.nan

                hh3 = hard_hits[mask_3d].sum()
                row["bp_sc_hard_hit_3d"] = hh3 / bb3 if bb3 > 0 else np.nan

                # Exit velo: simple mean of game-level averages (weighted would be better
                # but game-level avg is already batted-ball weighted within the game).
                ev_vals = ev_game[mask_3d]
                ev_valid = ev_vals[~np.isnan(ev_vals)]
                row["bp_sc_exit_velo_3d"] = ev_valid.mean() if len(ev_valid) > 0 else np.nan

                xw_vals = xwoba_game[mask_3d]
                xw_valid = xw_vals[~np.isnan(xw_vals)]
                row["bp_sc_xwoba_3d"] = xw_valid.mean() if len(xw_valid) > 0 else np.nan
            else:
                row["bp_sc_whiff_3d"] = np.nan
                row["bp_sc_barrel_3d"] = np.nan
                row["bp_sc_hard_hit_3d"] = np.nan
                row["bp_sc_exit_velo_3d"] = np.nan
                row["bp_sc_xwoba_3d"] = np.nan

            # Season-to-date (entering game) — use cumulative sums up to i-1.
            std_swings = cum_swings[i - 1]
            std_batted = cum_batted[i - 1]
            std_whiff = cum_whiffs[i - 1] / std_swings if std_swings > 0 else np.nan
            std_barrel = cum_barrels[i - 1] / std_batted if std_batted > 0 else np.nan

            xw_slice = xwoba_game[:i]
            xw_valid = xw_slice[~np.isnan(xw_slice)]
            row["bp_sc_xwoba_std"] = xw_valid.mean() if len(xw_valid) > 0 else np.nan
            row["bp_sc_barrel_std"] = std_barrel

            # 15-game rolling.
            start_15 = max(0, i - 15)
            b15 = barrels[start_15:i].sum()
            bb15 = batted[start_15:i].sum()
            row["bp_sc_barrel_15g"] = b15 / bb15 if bb15 > 0 else np.nan
            xw_15_slice = xwoba_game[start_15:i]
            xw_15_valid = xw_15_slice[~np.isnan(xw_15_slice)]
            row["bp_sc_xwoba_15g"] = xw_15_valid.mean() if len(xw_15_valid) > 0 else np.nan

            # Delta = 3-day metric minus season-to-date.
            whiff_3d = row.get("bp_sc_whiff_3d")
            barrel_3d = row.get("bp_sc_barrel_3d")
            row["bp_sc_whiff_delta_3d"] = (
                whiff_3d - std_whiff
                if whiff_3d is not None and not np.isnan(whiff_3d)
                   and std_whiff is not None and not np.isnan(std_whiff)
                else np.nan
            )
            row["bp_sc_barrel_delta_3d"] = (
                barrel_3d - std_barrel
                if barrel_3d is not None and not np.isnan(barrel_3d)
                   and std_barrel is not None and not np.isnan(std_barrel)
                else np.nan
            )

            results.append(row)

    return pd.DataFrame(results)


def build_savant_bullpen_features(
    seasons: list[int] | None = None,
    *,
    fatigue_days: int = 3,
) -> pd.DataFrame:
    """Build all Savant-based bullpen features.

    Returns DataFrame with columns:
    - team, season, game_date (keys)
    - bp_sc_whiff_3d, bp_sc_barrel_3d, bp_sc_hard_hit_3d, bp_sc_exit_velo_3d, bp_sc_xwoba_3d
    - bp_sc_whiff_delta_3d, bp_sc_barrel_delta_3d
    - bp_sc_xwoba_std, bp_sc_barrel_std
    - bp_sc_xwoba_15g, bp_sc_barrel_15g
    """
    relievers = load_reliever_games(seasons)
    team_game = _aggregate_team_game(relievers)
    logger.info("Team-game aggregates: %d rows", len(team_game))

    # Dedup doubleheaders: keep first game per team-date.
    before = len(team_game)
    team_game = team_game.sort_values(["team", "game_date", "game_pk"])
    team_game = team_game.drop_duplicates(subset=["team", "season", "game_date"], keep="first")
    dropped = before - len(team_game)
    if dropped:
        logger.info("Deduped %d doubleheader rows", dropped)

    features = _compute_fatigue_features(team_game, fatigue_days=fatigue_days)
    logger.info("Savant bullpen features: %d rows", len(features))
    return features


def save_savant_bullpen_features(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> Path:
    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "savant_bullpen_features.parquet"
    df.to_parquet(out_path, index=False)
    logger.info("Saved %s", out_path)
    return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    features = build_savant_bullpen_features()
    save_savant_bullpen_features(features)
    print(f"\nShape: {features.shape}")
    print(f"Columns: {list(features.columns)}")
    print(f"\nSample:\n{features.dropna().head(10).to_string()}")
