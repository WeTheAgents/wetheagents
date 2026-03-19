"""Feature engineering for MLB betting.

Computes rolling features for each team as of each game date:
- Rolling RPI (Rating Percentage Index): team strength metric
- W/L record + home/away splits
- Winning/losing streak (signed)
- Runs per game (offense + defense)
- Recent form (last 10, last 20)
- Pitcher proxy features (win rate, runs allowed, 1st inning oscillators)

All features are computed using only data available BEFORE the game (no look-ahead).
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Team Game Log Builder ────────────────────────────────────────────────


def build_team_game_log(games: pd.DataFrame) -> pd.DataFrame:
    """Build a team-level game log from game-level data.

    Each row = one team's perspective on one game.
    2 rows per game (home team + away team).
    """
    home = pd.DataFrame(
        {
            "season": games["season"].values,
            "date": games["date"].values,
            "team": games["home_team"].values,
            "opponent": games["away_team"].values,
            "is_home": True,
            "won": games["home_win"].astype(bool).values,
            "runs_scored": games["home_final"].values,
            "runs_allowed": games["away_final"].values,
            "close_ml": games["home_close_ml"].values,
        }
    )
    away = pd.DataFrame(
        {
            "season": games["season"].values,
            "date": games["date"].values,
            "team": games["away_team"].values,
            "opponent": games["home_team"].values,
            "is_home": False,
            "won": (~games["home_win"].astype(bool)).values,
            "runs_scored": games["away_final"].values,
            "runs_allowed": games["home_final"].values,
            "close_ml": games["away_close_ml"].values,
        }
    )
    log = pd.concat([home, away], ignore_index=True)
    log = log.dropna(subset=["runs_scored", "runs_allowed"])
    log = log.sort_values(["team", "season", "date"]).reset_index(drop=True)

    logger.info(f"Team game log: {len(log)} rows, {log['team'].nunique()} teams")
    return log


# ── Win Percentage ───────────────────────────────────────────────────────


def calc_rolling_wp(log: pd.DataFrame) -> pd.DataFrame:
    """Calculate rolling win percentage for each team-season.

    Returns DataFrame with columns:
    - wp: overall win percentage entering this game
    - wp_home: win pct in home games only
    - wp_away: win pct in away games only
    - wp_last10: win pct over last 10 games
    - wp_last20: win pct over last 20 games
    - games_played: number of games played so far
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        # Arrays for cumulative stats
        wins_cum = np.zeros(n)
        games_cum = np.zeros(n)
        wins_home_cum = np.zeros(n)
        games_home_cum = np.zeros(n)
        wins_away_cum = np.zeros(n)
        games_away_cum = np.zeros(n)

        won = grp["won"].values
        is_home = grp["is_home"].values

        for i in range(n):
            # Stats ENTERING this game (before it's played)
            if i == 0:
                wins_cum[i] = 0
                games_cum[i] = 0
                wins_home_cum[i] = 0
                games_home_cum[i] = 0
                wins_away_cum[i] = 0
                games_away_cum[i] = 0
            else:
                wins_cum[i] = wins_cum[i - 1] + (1 if won[i - 1] else 0)
                games_cum[i] = games_cum[i - 1] + 1

                if is_home[i - 1]:
                    wins_home_cum[i] = wins_home_cum[i - 1] + (1 if won[i - 1] else 0)
                    games_home_cum[i] = games_home_cum[i - 1] + 1
                    wins_away_cum[i] = wins_away_cum[i - 1]
                    games_away_cum[i] = games_away_cum[i - 1]
                else:
                    wins_away_cum[i] = wins_away_cum[i - 1] + (1 if won[i - 1] else 0)
                    games_away_cum[i] = games_away_cum[i - 1] + 1
                    wins_home_cum[i] = wins_home_cum[i - 1]
                    games_home_cum[i] = games_home_cum[i - 1]

        # Rolling last N
        wp_last3 = np.full(n, np.nan)
        wp_last6 = np.full(n, np.nan)
        wp_last10 = np.full(n, np.nan)
        wp_last20 = np.full(n, np.nan)
        for i in range(n):
            if i >= 3:
                wp_last3[i] = won[i - 3 : i].mean()
            if i >= 6:
                wp_last6[i] = won[i - 6 : i].mean()
            if i >= 10:
                wp_last10[i] = won[i - 10 : i].mean()
            if i >= 20:
                wp_last20[i] = won[i - 20 : i].mean()

        for i in range(n):
            gp = int(games_cum[i])
            results.append(
                {
                    "team": team,
                    "season": season,
                    "date": grp.iloc[i]["date"],
                    "games_played": gp,
                    "wp": wins_cum[i] / gp if gp > 0 else 0.5,
                    "wp_home": (
                        wins_home_cum[i] / games_home_cum[i]
                        if games_home_cum[i] > 0
                        else 0.5
                    ),
                    "wp_away": (
                        wins_away_cum[i] / games_away_cum[i]
                        if games_away_cum[i] > 0
                        else 0.5
                    ),
                    "wp_last3": wp_last3[i],
                    "wp_last6": wp_last6[i],
                    "wp_last10": wp_last10[i],
                    "wp_last20": wp_last20[i],
                }
            )

    return pd.DataFrame(results)


# ── Streak ───────────────────────────────────────────────────────────────


def calc_streaks(log: pd.DataFrame) -> pd.DataFrame:
    """Calculate winning/losing streak entering each game.

    Returns DataFrame with:
    - signed_streak: positive = winning streak, negative = losing streak
      e.g. +3 = won last 3, -5 = lost last 5
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        won = grp["won"].values
        n = len(grp)

        streaks = np.zeros(n, dtype=int)
        current_streak = 0
        current_type = "none"

        for i in range(n):
            # Record streak ENTERING this game
            if current_type == "W":
                streaks[i] = current_streak
            elif current_type == "L":
                streaks[i] = -current_streak
            else:
                streaks[i] = 0

            # Update streak after this game
            if won[i]:
                if current_type == "W":
                    current_streak += 1
                else:
                    current_streak = 1
                    current_type = "W"
            else:
                if current_type == "L":
                    current_streak += 1
                else:
                    current_streak = 1
                    current_type = "L"

        for i in range(n):
            results.append(
                {
                    "team": team,
                    "season": season,
                    "date": grp.iloc[i]["date"],
                    "signed_streak": streaks[i],
                }
            )

    return pd.DataFrame(results)


# ── Runs Per Game ────────────────────────────────────────────────────────


def calc_rolling_runs(log: pd.DataFrame) -> pd.DataFrame:
    """Calculate rolling runs scored/allowed per game.

    Returns DataFrame with:
    - rpg: runs per game (scored)
    - rapg: runs allowed per game
    - rpg_last10: runs per game over last 10
    - rapg_last10: runs allowed per game over last 10
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        rs = grp["runs_scored"].values
        ra = grp["runs_allowed"].values
        n = len(grp)

        for i in range(n):
            if i == 0:
                rpg = 4.5  # MLB average prior
                rapg = 4.5
            else:
                rpg = rs[:i].mean()
                rapg = ra[:i].mean()

            rpg_last10 = rs[max(0, i - 10) : i].mean() if i > 0 else 4.5
            rapg_last10 = ra[max(0, i - 10) : i].mean() if i > 0 else 4.5

            results.append(
                {
                    "team": team,
                    "season": season,
                    "date": grp.iloc[i]["date"],
                    "rpg": rpg,
                    "rapg": rapg,
                    "rpg_last10": rpg_last10,
                    "rapg_last10": rapg_last10,
                }
            )

    return pd.DataFrame(results)


# ── RPI (Rating Percentage Index) ────────────────────────────────────────


def calc_rolling_rpi(log: pd.DataFrame) -> pd.DataFrame:
    """Calculate rolling RPI for each team on each date.

    RPI = 0.25 * WP + 0.50 * OWP + 0.25 * OOWP

    Where:
    - WP = team's win percentage
    - OWP = average win percentage of team's opponents
    - OOWP = average win percentage of team's opponents' opponents

    This is computed incrementally: for each game, we use only data
    from games played BEFORE that date.
    """
    results = []

    # First pass: build cumulative WP for each team-season-date
    # We need a fast lookup: team+season+date -> wp_at_that_point
    wp_lookup: dict[tuple, float] = {}
    opponents_lookup: dict[tuple, list[str]] = {}

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        won = grp["won"].values
        n = len(grp)

        # Build list of opponents faced up to each game
        opponents_so_far: list[str] = []

        for i in range(n):
            date = grp.iloc[i]["date"]
            gp = i  # games played before this game

            if gp == 0:
                wp = 0.5  # prior
            else:
                wp = won[:i].mean()

            wp_lookup[(team, season, date)] = wp
            opponents_lookup[(team, season, date)] = list(opponents_so_far)
            opponents_so_far.append(grp.iloc[i]["opponent"])

    # Second pass: compute OWP and OOWP
    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        for i in range(n):
            date = grp.iloc[i]["date"]
            wp = wp_lookup.get((team, season, date), 0.5)

            # OWP: average WP of opponents we've faced
            opps = opponents_lookup.get((team, season, date), [])
            if not opps:
                owp = 0.5
                oowp = 0.5
            else:
                # Each opponent's WP at the time we played them
                opp_wps = []
                for opp in opps:
                    opp_wp = wp_lookup.get((opp, season, date), 0.5)
                    opp_wps.append(opp_wp)
                owp = np.mean(opp_wps) if opp_wps else 0.5

                # OOWP: for each opponent, get THEIR opponents' WPs
                oo_wps = []
                for opp in opps:
                    opp_opps = opponents_lookup.get((opp, season, date), [])
                    for oo in opp_opps:
                        oo_wp = wp_lookup.get((oo, season, date), 0.5)
                        oo_wps.append(oo_wp)
                oowp = np.mean(oo_wps) if oo_wps else 0.5

            rpi = 0.25 * wp + 0.50 * owp + 0.25 * oowp

            results.append(
                {
                    "team": team,
                    "season": season,
                    "date": date,
                    "rpi": rpi,
                    "wp_component": wp,
                    "owp_component": owp,
                    "oowp_component": oowp,
                }
            )

    logger.info(f"Computed RPI for {len(results)} team-game entries")
    return pd.DataFrame(results)


# ── Pythagorean Win Percentage ────────────────────────────────────────────


def calc_pythagorean_wp(log: pd.DataFrame) -> pd.DataFrame:
    """Calculate Pythagorean win percentage from cumulative RPG/RAPG.

    Formula: pyth_wp = rpg^1.83 / (rpg^1.83 + rapg^1.83)
    Uses only data available BEFORE the game (entering-game cumulative RPG/RAPG).
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        rs = grp["runs_scored"].values
        ra = grp["runs_allowed"].values
        n = len(grp)

        for i in range(n):
            if i == 0:
                rpg = 4.5  # MLB average prior
                rapg = 4.5
            else:
                rpg = rs[:i].mean()
                rapg = ra[:i].mean()

            pyth_wp = rpg**1.83 / (rpg**1.83 + rapg**1.83) if (rpg + rapg) > 0 else 0.5

            results.append(
                {
                    "team": team,
                    "season": season,
                    "date": grp.iloc[i]["date"],
                    "pyth_wp": pyth_wp,
                }
            )

    return pd.DataFrame(results)


# ── Master Feature Builder ───────────────────────────────────────────────


def build_all_features(
    games: pd.DataFrame,
    include_pitcher: bool = True,
    include_retrosheet: bool = True,
) -> pd.DataFrame:
    """Build all rolling features and merge back to game-level data.

    Returns the original games DataFrame with added feature columns:
    - For home team: rpi_home, wp_home, streak_home, rpg_home, etc.
    - For away team: rpi_away, wp_away, streak_away, rpg_away, etc.
    - Synthetic: rpi_diff, wp_diff, streak_diff, etc.
    - Pitcher proxy: home_sp_*, away_sp_*, sp_* (if include_pitcher=True)
    - Retrosheet entering features: WHIP, K/BB, K9, BB9, HR9, IP (if include_retrosheet=True)
    - Pythagorean win%: pyth_wp_home, pyth_wp_away, pyth_wp_diff
    """
    logger.info("Building team game log...")
    log = build_team_game_log(games)

    logger.info("Computing win percentages...")
    wp_df = calc_rolling_wp(log)

    logger.info("Computing streaks...")
    streak_df = calc_streaks(log)

    logger.info("Computing runs per game...")
    runs_df = calc_rolling_runs(log)

    logger.info("Computing Pythagorean win%...")
    pyth_df = calc_pythagorean_wp(log)

    logger.info("Computing RPI (this may take a while)...")
    rpi_df = calc_rolling_rpi(log)

    # Merge all feature DataFrames
    features = wp_df.merge(
        streak_df, on=["team", "season", "date"], how="left"
    ).merge(
        runs_df, on=["team", "season", "date"], how="left"
    ).merge(
        pyth_df, on=["team", "season", "date"], how="left"
    ).merge(
        rpi_df[["team", "season", "date", "rpi", "owp_component"]],
        on=["team", "season", "date"],
        how="left",
    )

    # Merge features for HOME team
    home_features = features.rename(
        columns={
            "wp": "wp_home",
            "wp_home": "wp_home_at_home",
            "wp_away": "wp_home_on_road",
            "wp_last3": "wp_last3_home",
            "wp_last6": "wp_last6_home",
            "wp_last10": "wp_last10_home",
            "wp_last20": "wp_last20_home",
            "games_played": "games_played_home",
            "signed_streak": "streak_home",
            "rpg": "rpg_home",
            "rapg": "rapg_home",
            "rpg_last10": "rpg_last10_home",
            "rapg_last10": "rapg_last10_home",
            "pyth_wp": "pyth_wp_home",
            "rpi": "rpi_home",
            "owp_component": "sos_home",
        }
    )
    home_features = home_features.rename(columns={"team": "home_team"})
    home_features = home_features.drop(columns=["season"], errors="ignore")

    # Merge features for AWAY team
    away_features = features.rename(
        columns={
            "wp": "wp_away",
            "wp_home": "wp_away_at_home",
            "wp_away": "wp_away_on_road",
            "wp_last3": "wp_last3_away",
            "wp_last6": "wp_last6_away",
            "wp_last10": "wp_last10_away",
            "wp_last20": "wp_last20_away",
            "games_played": "games_played_away",
            "signed_streak": "streak_away",
            "rpg": "rpg_away",
            "rapg": "rapg_away",
            "rpg_last10": "rpg_last10_away",
            "rapg_last10": "rapg_last10_away",
            "pyth_wp": "pyth_wp_away",
            "rpi": "rpi_away",
            "owp_component": "sos_away",
        }
    )
    away_features = away_features.rename(columns={"team": "away_team"})
    away_features = away_features.drop(columns=["season"], errors="ignore")

    # Merge to games
    enriched = games.merge(
        home_features, on=["home_team", "date"], how="left"
    ).merge(
        away_features, on=["away_team", "date"], how="left"
    )

    # Synthetic features (diffs)
    enriched["rpi_diff"] = enriched["rpi_home"] - enriched["rpi_away"]
    enriched["wp_diff"] = enriched["wp_home"] - enriched["wp_away"]
    enriched["wp_last3_diff"] = enriched["wp_last3_home"] - enriched["wp_last3_away"]
    enriched["wp_last6_diff"] = enriched["wp_last6_home"] - enriched["wp_last6_away"]
    enriched["wp_last10_diff"] = enriched["wp_last10_home"] - enriched["wp_last10_away"]
    enriched["streak_diff"] = enriched["streak_home"] - enriched["streak_away"]
    enriched["rpg_diff"] = enriched["rpg_home"] - enriched["rpg_away"]
    enriched["rapg_diff"] = enriched["rapg_home"] - enriched["rapg_away"]
    enriched["pyth_wp_diff"] = enriched["pyth_wp_home"] - enriched["pyth_wp_away"]
    enriched["rpi_min"] = enriched[["rpi_home", "rpi_away"]].min(axis=1)
    enriched["rpi_max"] = enriched[["rpi_home", "rpi_away"]].max(axis=1)
    enriched["games_played_min"] = enriched[
        ["games_played_home", "games_played_away"]
    ].min(axis=1)

    # Pitcher proxy features
    if include_pitcher:
        from src.pitcher_features import (
            build_pitcher_start_log,
            calc_pitcher_rolling_features,
            merge_pitcher_features_to_games,
        )

        logger.info("Building pitcher start log...")
        pitcher_log = build_pitcher_start_log(games)

        logger.info("Computing pitcher rolling features...")
        pitcher_features = calc_pitcher_rolling_features(pitcher_log)

        logger.info("Merging pitcher features to games...")
        enriched = merge_pitcher_features_to_games(enriched, pitcher_features)

    # Retrosheet entering features (WHIP, K/BB, K9, BB9, HR9, IP)
    if include_retrosheet:
        from pathlib import Path

        from src.data_loader import (
            PROCESSED_DIR,
            merge_retrosheet_pitchers,
            merge_retrosheet_starter_entering_features,
        )

        bridge_path = PROCESSED_DIR / "pitchers" / "game_id_bridge.parquet"
        entering_path = PROCESSED_DIR / "pitchers" / "starter_entering_features.parquet"

        if bridge_path.exists() and entering_path.exists():
            logger.info("Merging Retrosheet starter IDs...")
            enriched = merge_retrosheet_pitchers(enriched, bridge_path=bridge_path)

            logger.info("Merging Retrosheet entering features (WHIP, K/BB, K9, etc.)...")
            enriched = merge_retrosheet_starter_entering_features(
                enriched, entering_path=entering_path
            )
        else:
            missing = []
            if not bridge_path.exists():
                missing.append(str(bridge_path))
            if not entering_path.exists():
                missing.append(str(entering_path))
            logger.warning(
                f"Retrosheet parquets not found: {missing}. "
                "Run scripts/build_retrosheet_pitchers.py first. "
                "Skipping Retrosheet entering features."
            )

    n_features = len([c for c in enriched.columns if c not in games.columns])
    logger.info(f"Added {n_features} features to {len(enriched)} games")

    return enriched


# ── Spec Feature Columns ────────────────────────────────────────────────

SPEC_FEATURES = [
    "starter_fip_diff",
    "starter_whip_diff",
    "starter_kbb_diff",
    "starter_recent_ip_diff",
    "team_wrc_plus_diff",
    "team_obp_diff",
    "pyth_wp_diff",
    "bullpen_fip_diff",
    "bullpen_workload_3d_diff",
    "wp_last3_diff",
    "wp_last6_diff",
    "wp_last10_diff",
    "elo_diff",
    "home_advantage",
]


def build_spec_features(
    games: pd.DataFrame | None = None,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the 14-feature matrix from mlb_feature_spec.md.

    Either pass raw `games` (will call build_all_features internally)
    or pass pre-enriched `enriched` DataFrame from build_all_features().

    Returns DataFrame with:
    - 14 spec feature columns (SPEC_FEATURES)
    - regime label: 'M2' (fav won 2+), 'M3' (fav won 1), 'M4' (fav lost)
    - target: closing_decimal_odds_favorite
    - metadata: season, date, home_team, away_team, home_win, etc.
    """
    from pathlib import Path

    from src.data_loader import (
        PROCESSED_DIR,
        _map_team_code_to_retrosheet,
        add_derived_odds,
        american_to_decimal,
        apply_data_filters,
        load_all_seasons,
    )
    from src.elo import compute_elo

    # Step 0: Load and enrich games if needed
    if enriched is None:
        if games is None:
            logger.info("Loading all seasons...")
            games = load_all_seasons()
            games = apply_data_filters(games)
            games = add_derived_odds(games)
        logger.info("Building all features (team + pitcher + Retrosheet)...")
        enriched = build_all_features(games)

    df = enriched.copy()

    # ── Starter pitcher diffs (from Retrosheet entering features) ────────
    # These columns are merged by build_all_features() with home_sp_ / away_sp_ prefixes
    for col, home_col, away_col in [
        ("starter_fip_diff", "home_sp_fip_short", "away_sp_fip_short"),
        ("starter_whip_diff", "home_sp_whip_short", "away_sp_whip_short"),
        ("starter_kbb_diff", "home_sp_kbb_short", "away_sp_kbb_short"),
        ("starter_recent_ip_diff", "home_sp_ip_per_start_short", "away_sp_ip_per_start_short"),
    ]:
        if home_col in df.columns and away_col in df.columns:
            df[col] = df[home_col] - df[away_col]
        else:
            logger.warning(f"Missing columns for {col}: {home_col} / {away_col}")
            df[col] = np.nan

    # ── FanGraphs team offense (wRC+, OBP) with Y-1 anti-leakage ────────
    fg_path = PROCESSED_DIR / "fangraphs" / "team_batting_season.parquet"
    if fg_path.exists():
        fg = pd.read_parquet(fg_path)
        # Anti-leakage: season Y stats → used for season Y+1 games
        fg = fg.rename(columns={"season": "stat_season"})
        fg["season"] = fg["stat_season"] + 1
        # Map team codes to match our games
        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_fg_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]), axis=1
            )
            side_fg = fg.rename(columns={
                "team": f"_fg_{side}_team",
                "wrc_plus": f"wrc_plus_{side}",
                "obp": f"obp_{side}",
            })[["season", f"_fg_{side}_team", f"wrc_plus_{side}", f"obp_{side}"]]
            df = df.merge(side_fg, on=["season", f"_fg_{side}_team"], how="left")
            df = df.drop(columns=[f"_fg_{side}_team"])

        df["team_wrc_plus_diff"] = df["wrc_plus_home"] - df["wrc_plus_away"]
        df["team_obp_diff"] = df["obp_home"] - df["obp_away"]
    else:
        logger.warning(f"FanGraphs data not found at {fg_path}. Using NaN for wRC+/OBP diffs.")
        df["team_wrc_plus_diff"] = np.nan
        df["team_obp_diff"] = np.nan

    # ── Bullpen diffs ────────────────────────────────────────────────────
    bp_path = PROCESSED_DIR / "retrosheet" / "bullpen_features.parquet"
    if bp_path.exists():
        bp = pd.read_parquet(bp_path)
        bp["date"] = pd.to_datetime(bp["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_bp_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]), axis=1
            )
            bp_cols_to_merge = ["team", "date"]
            bp_rename = {"team": f"_bp_{side}_team"}
            for bc in ["bp_fip_short", "bp_ip_3d"]:
                if bc in bp.columns:
                    bp_cols_to_merge.append(bc)
                    bp_rename[bc] = f"{bc}_{side}"
            side_bp = bp[bp_cols_to_merge].rename(columns=bp_rename)
            # Safety: ensure unique (team, date) keys to prevent fan-out
            side_bp = side_bp.drop_duplicates(
                subset=[f"_bp_{side}_team", "date"], keep="first"
            )
            df = df.merge(side_bp, on=[f"_bp_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_bp_{side}_team"])

        if "bp_fip_short_home" in df.columns:
            df["bullpen_fip_diff"] = df["bp_fip_short_home"] - df["bp_fip_short_away"]
        else:
            df["bullpen_fip_diff"] = np.nan

        if "bp_ip_3d_home" in df.columns:
            df["bullpen_workload_3d_diff"] = df["bp_ip_3d_home"] - df["bp_ip_3d_away"]
        else:
            df["bullpen_workload_3d_diff"] = np.nan
    else:
        logger.warning(f"Bullpen features not found at {bp_path}. Using NaN.")
        df["bullpen_fip_diff"] = np.nan
        df["bullpen_workload_3d_diff"] = np.nan

    # ── Elo ──────────────────────────────────────────────────────────────
    logger.info("Computing Elo ratings...")
    elo_df = compute_elo(df)
    df = df.merge(
        elo_df[["season", "date", "home_team", "away_team", "elo_diff"]],
        on=["season", "date", "home_team", "away_team"],
        how="left",
    )

    # ── Home advantage (constant) ────────────────────────────────────────
    df["home_advantage"] = 1

    # ── Existing diffs (already computed by build_all_features) ──────────
    # pyth_wp_diff, wp_last3_diff, wp_last6_diff, wp_last10_diff — already present

    # ── Integrity check: no duplicate games ──────────────────────────────
    dup_count = df.duplicated(subset=["season", "date", "home_team", "away_team"]).sum()
    if dup_count > 0:
        logger.error(f"Duplicate games detected: {dup_count} rows. Deduplicating as safety net.")
        df = df.drop_duplicates(
            subset=["season", "date", "home_team", "away_team"], keep="first"
        )

    # ── Spec filters ─────────────────────────────────────────────────────
    n_before = len(df)
    mask = pd.Series(True, index=df.index)

    # Colorado
    if "involves_col" in df.columns:
        mask &= ~df["involves_col"]
    # April (early season)
    if "month" in df.columns:
        mask &= df["month"] != 4
    # September: kept in dataset — away underdog edge is strongest in Sep
    # (WR 50%, ROI +22%, MaxL 4). Tanking home teams boost dog value.
    # Extra innings
    if "is_extra_innings" in df.columns:
        mask &= ~df["is_extra_innings"]
    # Extreme lines (>200 or pick'em zone)
    if "home_close_ml" in df.columns:
        home_abs = df["home_close_ml"].abs()
        away_abs = df["away_close_ml"].abs()
        fav_ml = pd.concat([home_abs, away_abs], axis=1).max(axis=1)
        mask &= fav_ml > 105  # not pick'em
        mask &= fav_ml <= 200  # not extreme

    df = df[mask].copy()
    logger.info(f"Spec filters: {n_before} -> {len(df)} games")

    # ── Regime labels (by outcome) ───────────────────────────────────────
    # Determine which team is the favorite (lower implied odds = higher probability)
    df["fav_is_home"] = df["home_implied_prob"] > df["away_implied_prob"]
    df["fav_final"] = np.where(df["fav_is_home"], df["home_final"], df["away_final"])
    df["dog_final"] = np.where(df["fav_is_home"], df["away_final"], df["home_final"])
    df["fav_margin"] = df["fav_final"] - df["dog_final"]

    df["regime"] = np.where(
        df["fav_margin"] >= 2, "M2",
        np.where(df["fav_margin"] == 1, "M3", "M4"),
    )

    # ── Target: closing decimal odds of favorite ─────────────────────────
    df["closing_decimal_odds_favorite"] = np.where(
        df["fav_is_home"],
        df["home_decimal_odds"],
        df["away_decimal_odds"],
    )

    # ── Final feature check ──────────────────────────────────────────────
    available = [f for f in SPEC_FEATURES if f in df.columns and df[f].notna().any()]
    missing = [f for f in SPEC_FEATURES if f not in available]
    if missing:
        logger.warning(f"Spec features with no data: {missing}")
    logger.info(f"Spec features available: {len(available)}/{len(SPEC_FEATURES)}")

    return df
