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

# MLB league-average runs per game, used as Bayesian prior for early-season estimates
MLB_AVG_RPG_PRIOR = 4.5


# ── Team Game Log Builder ────────────────────────────────────────────────


def build_team_game_log(games: pd.DataFrame) -> pd.DataFrame:
    """Build a team-level game log from game-level data.

    Each row = one team's perspective on one game.
    2 rows per game (home team + away team).
    """
    # 1st-inning scoring (NaN for games without real inning data)
    has_inn1 = "home_inn_1" in games.columns and "away_inn_1" in games.columns
    if has_inn1:
        # Detect fake inning data: all 9 innings sum to 0 (2004-2009 seasons)
        inn_cols = [f"away_inn_{i}" for i in range(1, 10) if f"away_inn_{i}" in games.columns]
        inn_cols += [f"home_inn_{i}" for i in range(1, 10) if f"home_inn_{i}" in games.columns]
        inn_total = games[inn_cols].sum(axis=1)
        has_real_inn = (inn_total > 0).values
        home_scored_1st = np.where(has_real_inn, (games["home_inn_1"] > 0).astype(float).values, np.nan)
        away_scored_1st = np.where(has_real_inn, (games["away_inn_1"] > 0).astype(float).values, np.nan)

        # Score after 5 innings (for late-game metrics — captures starter's job)
        home_inn_1_5 = [f"home_inn_{i}" for i in range(1, 6) if f"home_inn_{i}" in games.columns]
        away_inn_1_5 = [f"away_inn_{i}" for i in range(1, 6) if f"away_inn_{i}" in games.columns]
        if len(home_inn_1_5) == 5 and len(away_inn_1_5) == 5:
            home_score_5 = games[home_inn_1_5].sum(axis=1).values.astype(float)
            away_score_5 = games[away_inn_1_5].sum(axis=1).values.astype(float)
            # NaN for fake inning data
            home_score_5 = np.where(has_real_inn, home_score_5, np.nan)
            away_score_5 = np.where(has_real_inn, away_score_5, np.nan)
        else:
            home_score_5 = np.full(len(games), np.nan)
            away_score_5 = np.full(len(games), np.nan)

        # Per-inning run counts for offensive power metric
        home_inn_cols = [f"home_inn_{i}" for i in range(1, 10) if f"home_inn_{i}" in games.columns]
        away_inn_cols = [f"away_inn_{i}" for i in range(1, 10) if f"away_inn_{i}" in games.columns]
        home_scoring_inns = np.where(has_real_inn, (games[home_inn_cols] > 0).sum(axis=1).values, np.nan)
        home_multi_run_inns = np.where(has_real_inn, (games[home_inn_cols] >= 2).sum(axis=1).values, np.nan)
        away_scoring_inns = np.where(has_real_inn, (games[away_inn_cols] > 0).sum(axis=1).values, np.nan)
        away_multi_run_inns = np.where(has_real_inn, (games[away_inn_cols] >= 2).sum(axis=1).values, np.nan)
    else:
        home_scored_1st = np.full(len(games), np.nan)
        away_scored_1st = np.full(len(games), np.nan)
        home_score_5 = np.full(len(games), np.nan)
        away_score_5 = np.full(len(games), np.nan)
        home_scoring_inns = np.full(len(games), np.nan)
        home_multi_run_inns = np.full(len(games), np.nan)
        away_scoring_inns = np.full(len(games), np.nan)
        away_multi_run_inns = np.full(len(games), np.nan)

    # Derived late-game columns (from team perspective)
    home_margin = (games["home_final"] - games["away_final"]).values.astype(float)
    away_margin = (games["away_final"] - games["home_final"]).values.astype(float)

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
            "scored_in_1st": home_scored_1st,
            "score_after_5": home_score_5,
            "opp_score_after_5": away_score_5,
            "leading_after_5": np.where(
                np.isnan(home_score_5), np.nan,
                (home_score_5 > away_score_5).astype(float),
            ),
            "trailing_after_5": np.where(
                np.isnan(home_score_5), np.nan,
                (home_score_5 < away_score_5).astype(float),
            ),
            "close_game": np.where(
                np.isnan(home_score_5), np.nan,
                (np.abs(home_margin) <= 2).astype(float),
            ),
            "margin": home_margin,
            "scoring_innings": home_scoring_inns,
            "multi_run_innings": home_multi_run_inns,
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
            "scored_in_1st": away_scored_1st,
            "score_after_5": away_score_5,
            "opp_score_after_5": home_score_5,
            "leading_after_5": np.where(
                np.isnan(away_score_5), np.nan,
                (away_score_5 > home_score_5).astype(float),
            ),
            "trailing_after_5": np.where(
                np.isnan(away_score_5), np.nan,
                (away_score_5 < home_score_5).astype(float),
            ),
            "close_game": np.where(
                np.isnan(away_score_5), np.nan,
                (np.abs(away_margin) <= 2).astype(float),
            ),
            "margin": away_margin,
            "scoring_innings": away_scoring_inns,
            "multi_run_innings": away_multi_run_inns,
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
                rpg = MLB_AVG_RPG_PRIOR
                rapg = MLB_AVG_RPG_PRIOR
            else:
                rpg = rs[:i].mean()
                rapg = ra[:i].mean()

            rpg_last10 = rs[max(0, i - 10) : i].mean() if i > 0 else MLB_AVG_RPG_PRIOR
            rapg_last10 = ra[max(0, i - 10) : i].mean() if i > 0 else MLB_AVG_RPG_PRIOR

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


# ── First-Inning Scoring Rate ────────────────────────────────────────────


def calc_first_inning_rate(log: pd.DataFrame, window: int = 25) -> pd.DataFrame:
    """Rolling rate of games where the team scored in the 1st inning.

    Returns DataFrame with:
    - fi_score_rate: entering-game 1st-inning scoring rate (full season)
    - fi_score_rate_last: rate over last `window` games
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        scored = grp["scored_in_1st"].values
        n = len(grp)

        for i in range(n):
            past = scored[:i]
            valid = past[~np.isnan(past)]

            if len(valid) >= 5:
                fi_rate = valid.mean()
            else:
                fi_rate = np.nan

            recent = scored[max(0, i - window) : i]
            valid_recent = recent[~np.isnan(recent)]
            if len(valid_recent) >= 5:
                fi_rate_last = valid_recent.mean()
            else:
                fi_rate_last = np.nan

            results.append(
                {
                    "team": team,
                    "season": season,
                    "date": grp.iloc[i]["date"],
                    "fi_score_rate": fi_rate,
                    "fi_score_rate_last": fi_rate_last,
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
    # NOTE: wp_lookup is keyed by (team, season, date) where date is the team's
    # own game date.  When looking up an opponent's WP we use the *current* team's
    # game date, but the opponent may not have played on that exact date.  This
    # causes ~50% of opponent WP lookups to miss and silently fall back to 0.5.
    # Fixing this requires keying by game-number instead of date — tracked as a
    # known limitation (see status_report_session10 for impact analysis).
    fallback_count = 0
    total_lookups = 0

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
                    total_lookups += 1
                    opp_wp = wp_lookup.get((opp, season, date))
                    if opp_wp is None:
                        opp_wp = 0.5
                        fallback_count += 1
                    opp_wps.append(opp_wp)
                owp = np.mean(opp_wps) if opp_wps else 0.5

                # OOWP: for each opponent, get THEIR opponents' WPs
                oo_wps = []
                for opp in opps:
                    opp_opps = opponents_lookup.get((opp, season, date), [])
                    for oo in opp_opps:
                        total_lookups += 1
                        oo_wp = wp_lookup.get((oo, season, date))
                        if oo_wp is None:
                            oo_wp = 0.5
                            fallback_count += 1
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

    fallback_pct = (fallback_count / total_lookups * 100) if total_lookups > 0 else 0
    logger.info(
        f"Computed RPI for {len(results)} team-game entries "
        f"(WP fallback rate: {fallback_count}/{total_lookups} = {fallback_pct:.1f}%)"
    )
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
                rpg = MLB_AVG_RPG_PRIOR
                rapg = MLB_AVG_RPG_PRIOR
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


# ── League-Relative Offense/Defense ───────────────────────────────────────


def calc_league_relative(log: pd.DataFrame) -> pd.DataFrame:
    """Offense/defense as ratio to league-wide cumulative average.

    For each team-game, computes:
    - offense_vs_league: team RPG / league RPG (>1.0 = above average)
    - defense_vs_league: team RAPG / league RAPG (<1.0 = above average defense)

    Uses season-cumulative averages (same window as existing rpg/rapg).
    """
    results = []

    for season, season_grp in log.groupby("season"):
        season_grp = season_grp.sort_values("date").reset_index(drop=True)

        # Build cumulative league averages by date
        dates = np.sort(season_grp["date"].unique())

        # Pre-compute league cumulative RPG/RAPG at each date
        league_cum_rpg = {}
        league_cum_rapg = {}
        all_rs = season_grp["runs_scored"].values
        all_ra = season_grp["runs_allowed"].values
        all_dates = season_grp["date"].values

        for d in dates:
            prior_mask = all_dates < d
            if prior_mask.sum() == 0:
                league_cum_rpg[d] = 4.5  # MLB prior
                league_cum_rapg[d] = 4.5
            else:
                league_cum_rpg[d] = all_rs[prior_mask].mean()
                league_cum_rapg[d] = all_ra[prior_mask].mean()

        # Compute per-team ratios
        for (team, _), grp in season_grp.groupby(["team", "season"]):
            grp = grp.sort_values("date").reset_index(drop=True)
            rs = grp["runs_scored"].values
            ra = grp["runs_allowed"].values

            for i in range(len(grp)):
                d = grp.iloc[i]["date"]
                league_rpg = league_cum_rpg[d]
                league_rapg = league_cum_rapg[d]

                if i == 0:
                    team_rpg = 4.5
                    team_rapg = 4.5
                else:
                    team_rpg = rs[:i].mean()
                    team_rapg = ra[:i].mean()

                off_ratio = team_rpg / league_rpg if league_rpg > 0 else 1.0
                def_ratio = team_rapg / league_rapg if league_rapg > 0 else 1.0

                results.append({
                    "team": team,
                    "season": season,
                    "date": d,
                    "offense_vs_league": off_ratio,
                    "defense_vs_league": def_ratio,
                })

    return pd.DataFrame(results)


# ── Late-Game Metrics (Hold Rate, Close-Game WP, Deficit Recovery) ──────


def calc_late_game_metrics(
    log: pd.DataFrame,
    window: int = 30,
    min_qualifying: int = 5,
) -> pd.DataFrame:
    """Compute rolling late-game performance metrics.

    Requires inning-by-inning columns in the log:
    - score_after_5, opp_score_after_5 (team's and opponent's runs in inn 1-5)
    - leading_after_5, trailing_after_5 (booleans)
    - close_game (abs margin <= 2)
    - won (game outcome)

    Returns DataFrame with:
    - hold_rate: win% when leading after 5 (last `window` games)
    - close_game_wp: win% in 1-2 run games (last `window` games)
    - deficit_recovery_rate: win% when trailing after 5 (last `window` games)

    NaN for seasons without real inning data (2004-2009).
    NaN if fewer than `min_qualifying` situations in window.
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        leading = grp["leading_after_5"].values
        trailing = grp["trailing_after_5"].values
        close = grp["close_game"].values
        won = grp["won"].values

        for i in range(n):
            start = max(0, i - window)
            # Only look at games BEFORE current game
            window_slice = slice(start, i)

            # Hold rate
            lead_mask = leading[window_slice]
            won_slice = won[window_slice]
            if len(lead_mask) == 0 or np.isnan(lead_mask).all() or lead_mask.sum() == 0:
                hold = np.nan
            else:
                lead_idx = ~np.isnan(lead_mask) & (lead_mask == 1.0)
                if lead_idx.sum() < min_qualifying:
                    hold = np.nan
                else:
                    hold = won_slice[lead_idx].mean()

            # Close-game WP
            close_mask = close[window_slice]
            if len(close_mask) == 0 or np.isnan(close_mask).all() or close_mask.sum() == 0:
                close_wp = np.nan
            else:
                close_idx = ~np.isnan(close_mask) & (close_mask == 1.0)
                if close_idx.sum() < min_qualifying:
                    close_wp = np.nan
                else:
                    close_wp = won_slice[close_idx].mean()

            # Deficit recovery rate
            trail_mask = trailing[window_slice]
            if len(trail_mask) == 0 or np.isnan(trail_mask).all() or trail_mask.sum() == 0:
                recovery = np.nan
            else:
                trail_idx = ~np.isnan(trail_mask) & (trail_mask == 1.0)
                if trail_idx.sum() < min_qualifying:
                    recovery = np.nan
                else:
                    recovery = won_slice[trail_idx].mean()

            results.append({
                "team": team,
                "season": season,
                "date": grp.iloc[i]["date"],
                "hold_rate": hold,
                "close_game_wp": close_wp,
                "deficit_recovery_rate": recovery,
            })

    return pd.DataFrame(results)


# ── Offensive Power (Multi-Run Inning Rate) ──────────────────────────────


def calc_inning_power(
    log: pd.DataFrame,
    window: int = 30,
    min_qualifying: int = 5,
) -> pd.DataFrame:
    """Rolling offensive power: fraction of scoring innings with 2+ runs.

    High power_rate = team capitalizes on baserunners (big innings).
    Low power_rate = team nibbles with single runs.

    Requires scoring_innings and multi_run_innings columns in the log
    (computed from per-inning run counts in build_team_game_log).

    Returns NaN if fewer than `min_qualifying` total scoring innings in window.
    """
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        n = len(grp)

        scoring = grp["scoring_innings"].values
        multi = grp["multi_run_innings"].values

        for i in range(n):
            start = max(0, i - window)
            window_slice = slice(start, i)

            s_window = scoring[window_slice]
            m_window = multi[window_slice]

            # Skip if no real inning data
            valid = ~np.isnan(s_window)
            if valid.sum() == 0:
                power = np.nan
            else:
                total_scoring = s_window[valid].sum()
                total_multi = m_window[valid].sum()
                if total_scoring < min_qualifying:
                    power = np.nan
                else:
                    power = total_multi / total_scoring

            results.append({
                "team": team,
                "season": season,
                "date": grp.iloc[i]["date"],
                "power_rate": power,
            })

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

    logger.info("Computing 1st-inning scoring rate...")
    fi_rate_df = calc_first_inning_rate(log)

    logger.info("Computing league-relative offense/defense...")
    league_rel_df = calc_league_relative(log)

    logger.info("Computing late-game metrics (hold rate, close-game WP, recovery)...")
    late_game_df = calc_late_game_metrics(log)

    logger.info("Computing offensive power (multi-run inning rate)...")
    power_df = calc_inning_power(log)

    logger.info("Computing RPI (this may take a while)...")
    rpi_df = calc_rolling_rpi(log)

    # Merge all feature DataFrames
    features = wp_df.merge(
        streak_df, on=["team", "season", "date"], how="left"
    ).merge(
        runs_df, on=["team", "season", "date"], how="left"
    ).merge(
        fi_rate_df, on=["team", "season", "date"], how="left"
    ).merge(
        pyth_df, on=["team", "season", "date"], how="left"
    ).merge(
        rpi_df[["team", "season", "date", "rpi", "owp_component"]],
        on=["team", "season", "date"],
        how="left",
    ).merge(
        league_rel_df, on=["team", "season", "date"], how="left",
    ).merge(
        late_game_df, on=["team", "season", "date"], how="left",
    ).merge(
        power_df, on=["team", "season", "date"], how="left",
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
            "fi_score_rate": "fi_score_rate_home",
            "fi_score_rate_last": "fi_score_rate_last_home",
            "pyth_wp": "pyth_wp_home",
            "rpi": "rpi_home",
            "owp_component": "sos_home",
            "offense_vs_league": "offense_vs_league_home",
            "defense_vs_league": "defense_vs_league_home",
            "hold_rate": "hold_rate_home",
            "close_game_wp": "close_game_wp_home",
            "deficit_recovery_rate": "deficit_recovery_rate_home",
            "power_rate": "power_rate_home",
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
            "fi_score_rate": "fi_score_rate_away",
            "fi_score_rate_last": "fi_score_rate_last_away",
            "pyth_wp": "pyth_wp_away",
            "rpi": "rpi_away",
            "owp_component": "sos_away",
            "offense_vs_league": "offense_vs_league_away",
            "defense_vs_league": "defense_vs_league_away",
            "hold_rate": "hold_rate_away",
            "close_game_wp": "close_game_wp_away",
            "deficit_recovery_rate": "deficit_recovery_rate_away",
            "power_rate": "power_rate_away",
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
    enriched["fi_score_rate_diff"] = (
        enriched["fi_score_rate_home"] - enriched["fi_score_rate_away"]
    )
    enriched["rpi_min"] = enriched[["rpi_home", "rpi_away"]].min(axis=1)
    enriched["rpi_max"] = enriched[["rpi_home", "rpi_away"]].max(axis=1)
    enriched["games_played_min"] = enriched[
        ["games_played_home", "games_played_away"]
    ].min(axis=1)

    # League-relative and late-game diffs
    enriched["offense_vs_league_diff"] = (
        enriched["offense_vs_league_home"] - enriched["offense_vs_league_away"]
    )
    enriched["defense_vs_league_diff"] = (
        enriched["defense_vs_league_home"] - enriched["defense_vs_league_away"]
    )
    enriched["hold_rate_diff"] = (
        enriched["hold_rate_home"] - enriched["hold_rate_away"]
    )
    enriched["close_game_wp_diff"] = (
        enriched["close_game_wp_home"] - enriched["close_game_wp_away"]
    )
    enriched["deficit_recovery_diff"] = (
        enriched["deficit_recovery_rate_home"] - enriched["deficit_recovery_rate_away"]
    )
    enriched["power_rate_diff"] = (
        enriched["power_rate_home"] - enriched["power_rate_away"]
    )

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

        from src.data_loader import (
            PROCESSED_DIR,
            _map_team_code_to_retrosheet,
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

        # ── Pitcher hand from Retrosheet allplayers ──────────────────────
        if "home_starter_id" in enriched.columns:
            try:
                from src.retrosheet_batters import load_season_players

                logger.info("Merging pitcher hand from Retrosheet allplayers...")
                hand_lookup = {}
                for year in enriched["season"].unique():
                    players = load_season_players(int(year))
                    if players is not None:
                        hand_df = players.drop_duplicates(subset=["id"])[["id", "throw"]]
                        for _, r in hand_df.iterrows():
                            hand_lookup[(r["id"], int(year))] = r["throw"]

                if hand_lookup:
                    for id_col, hand_col in [
                        ("home_starter_id", "home_sp_hand"),
                        ("away_starter_id", "away_sp_hand"),
                    ]:
                        enriched[hand_col] = enriched.apply(
                            lambda r, _id=id_col, _hc=hand_col: hand_lookup.get(
                                (r.get(_id), int(r["season"])),
                                r.get(_hc),
                            ),
                            axis=1,
                        )
                    n_hand = enriched["home_sp_hand"].notna().sum()
                    logger.info(f"Pitcher hand filled: {n_hand}/{len(enriched)} games")
            except ImportError:
                logger.warning("retrosheet_batters not available, skipping pitcher hand")

        # ── Bullpen features (FIP, workload) ─────────────────────────────
        bp_path = PROCESSED_DIR / "retrosheet" / "bullpen_features.parquet"
        if bp_path.exists():
            logger.info("Merging bullpen features (FIP, workload)...")
            bp = pd.read_parquet(bp_path)
            bp["date"] = pd.to_datetime(bp["date"]).dt.normalize()
            enriched["date"] = pd.to_datetime(enriched["date"]).dt.normalize()

            for side, team_col in [("home", "home_team"), ("away", "away_team")]:
                enriched[f"_bp_{side}_team"] = enriched.apply(
                    lambda r, _tc=team_col: _map_team_code_to_retrosheet(r[_tc], r["season"]),
                    axis=1,
                )
                bp_cols_to_merge = ["team", "date"]
                bp_rename = {"team": f"_bp_{side}_team"}
                for bc in ["bp_fip_short", "bp_fip_7g", "bp_fip_long", "bp_ip_3d"]:
                    if bc in bp.columns:
                        bp_cols_to_merge.append(bc)
                        bp_rename[bc] = f"{bc}_{side}"
                side_bp = bp[bp_cols_to_merge].rename(columns=bp_rename)
                side_bp = side_bp.drop_duplicates(
                    subset=[f"_bp_{side}_team", "date"], keep="first"
                )
                enriched = enriched.merge(side_bp, on=[f"_bp_{side}_team", "date"], how="left")
                enriched = enriched.drop(columns=[f"_bp_{side}_team"])

            if "bp_fip_short_home" in enriched.columns:
                enriched["bullpen_fip_diff"] = enriched["bp_fip_short_home"] - enriched["bp_fip_short_away"]
            if "bp_ip_3d_home" in enriched.columns:
                enriched["bullpen_workload_3d_diff"] = enriched["bp_ip_3d_home"] - enriched["bp_ip_3d_away"]
        else:
            logger.warning(f"Bullpen features not found at {bp_path}")

        # ── Batting lineup vs-hand features ──────────────────────────────
        lineup_path = PROCESSED_DIR / "retrosheet" / "game_lineup_features.parquet"
        if lineup_path.exists():
            logger.info("Merging batting lineup vs-hand features...")
            lineup = pd.read_parquet(lineup_path)
            lineup["date"] = pd.to_datetime(lineup["date"]).dt.normalize()
            enriched["date"] = pd.to_datetime(enriched["date"]).dt.normalize()

            for side, team_col in [("home", "home_team"), ("away", "away_team")]:
                enriched[f"_lu_{side}_team"] = enriched.apply(
                    lambda r, _tc=team_col: _map_team_code_to_retrosheet(r[_tc], r["season"]),
                    axis=1,
                )
                lu_cols = [c for c in lineup.columns if c.startswith("top3_") or c == "n_batters"]
                lu_rename = {"team": f"_lu_{side}_team"}
                for c in lu_cols:
                    lu_rename[c] = f"{c}_{side}"
                side_lu = lineup[["team", "date"] + lu_cols].rename(columns=lu_rename)
                side_lu = side_lu.drop_duplicates(subset=[f"_lu_{side}_team", "date"], keep="first")
                enriched = enriched.merge(side_lu, on=[f"_lu_{side}_team", "date"], how="left")
                enriched = enriched.drop(columns=[f"_lu_{side}_team"])

            # Effective OBP (matchup-aware: lineup OBP vs opposing pitcher's hand)
            if all(
                c in enriched.columns
                for c in [
                    "away_sp_hand", "home_sp_hand",
                    "top3_obp_vs_rhp_home", "top3_obp_vs_lhp_home",
                    "top3_obp_vs_rhp_away", "top3_obp_vs_lhp_away",
                ]
            ):
                enriched["effective_obp_home"] = np.where(
                    enriched["away_sp_hand"] == "R",
                    enriched["top3_obp_vs_rhp_home"],
                    enriched["top3_obp_vs_lhp_home"],
                )
                enriched["effective_obp_away"] = np.where(
                    enriched["home_sp_hand"] == "R",
                    enriched["top3_obp_vs_rhp_away"],
                    enriched["top3_obp_vs_lhp_away"],
                )
        else:
            logger.warning(f"Lineup features not found at {lineup_path}")

    # effective_obp_diff (must be after lineup + pitcher hand merge)
    if "effective_obp_home" in enriched.columns and "effective_obp_away" in enriched.columns:
        enriched["effective_obp_diff"] = (
            enriched["effective_obp_home"] - enriched["effective_obp_away"]
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
    # Session 18: late-game + matchup features
    "close_game_wp_diff",   # win% in 1-2 run games (tight game capability)
    "hold_rate_diff",       # win% when leading after 5 innings (closing strength)
    "effective_obp_diff",   # OBP top-3 batters vs opposing pitcher's hand
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

    from src.data_loader import (
        PROCESSED_DIR,
        _map_team_code_to_retrosheet,
        add_derived_odds,
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

    # ── Bullpen diffs (skip if already merged by build_all_features) ─────
    if "bp_fip_short_home" not in df.columns:
        bp_path = PROCESSED_DIR / "retrosheet" / "bullpen_features.parquet"
        if bp_path.exists():
            bp = pd.read_parquet(bp_path)
            bp["date"] = pd.to_datetime(bp["date"]).dt.normalize()
            df["date"] = pd.to_datetime(df["date"]).dt.normalize()

            for side, team_col in [("home", "home_team"), ("away", "away_team")]:
                df[f"_bp_{side}_team"] = df.apply(
                    lambda r, _tc=team_col: _map_team_code_to_retrosheet(r[_tc], r["season"]),
                    axis=1,
                )
                bp_cols_to_merge = ["team", "date"]
                bp_rename = {"team": f"_bp_{side}_team"}
                for bc in ["bp_fip_short", "bp_ip_3d"]:
                    if bc in bp.columns:
                        bp_cols_to_merge.append(bc)
                        bp_rename[bc] = f"{bc}_{side}"
                side_bp = bp[bp_cols_to_merge].rename(columns=bp_rename)
                side_bp = side_bp.drop_duplicates(
                    subset=[f"_bp_{side}_team", "date"], keep="first"
                )
                df = df.merge(side_bp, on=[f"_bp_{side}_team", "date"], how="left")
                df = df.drop(columns=[f"_bp_{side}_team"])
        else:
            logger.warning(f"Bullpen features not found at {bp_path}. Using NaN.")

    if "bullpen_fip_diff" not in df.columns:
        if "bp_fip_short_home" in df.columns:
            df["bullpen_fip_diff"] = df["bp_fip_short_home"] - df["bp_fip_short_away"]
        else:
            df["bullpen_fip_diff"] = np.nan
    if "bullpen_workload_3d_diff" not in df.columns:
        if "bp_ip_3d_home" in df.columns:
            df["bullpen_workload_3d_diff"] = df["bp_ip_3d_home"] - df["bp_ip_3d_away"]
        else:
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


# ── Over/Under Features ──────────────────────────────────────────────────

OU_FEATURES = [
    # Combined scoring environment (sums — O/U is about total runs)
    "combined_rpg",               # rpg_home + rpg_away (season cumulative)
    "combined_rapg",              # rapg_home + rapg_away
    "combined_rpg_last10",        # rpg_last10_home + rpg_last10_away
    "combined_rapg_last10",       # rapg_last10_home + rapg_last10_away
    # Starting pitching (combined quality)
    "sp_ra_combined_short",       # home_sp_ra_short + away_sp_ra_short
    "sp_ra_combined_long",        # home_sp_ra_long + away_sp_ra_long
    "sp_quality_floor",           # max(home_sp_ra_long, away_sp_ra_long) — worst starter
    "sp_fip_combined",            # home_sp_fip_short + away_sp_fip_short
    "sp_whip_combined",           # home_sp_whip_short + away_sp_whip_short
    "sp_kbb_combined",            # home_sp_kbb_short + away_sp_kbb_short (higher=better)
    "sp_ip_per_start_combined",   # home_sp_ip_per_start_short + away_sp_ip_per_start_short
    # Bullpen
    "bullpen_fip_combined",       # bp_fip_short_home + bp_fip_short_away
    "bullpen_fip_7g_combined",    # bp_fip_7g_home + bp_fip_7g_away (7-game rolling)
    "bp_fip_osc_combined",        # (7g - season) home + (7g - season) away; positive = deteriorating
    "bullpen_ip_3d_combined",     # bp_ip_3d_home + bp_ip_3d_away (workload proxy)
    # League-relative
    "offense_vs_league_combined",   # offense_vs_league_home + offense_vs_league_away
    "defense_vs_league_combined",   # defense_vs_league_home + defense_vs_league_away
    # Team quality
    "pyth_wp_combined",           # pyth_wp_home + pyth_wp_away
    # 1st inning scoring tendency
    "fi_score_rate_combined",     # fi_score_rate_home + fi_score_rate_away
    # Market line (for classifier — NOT for regression target)
    "close_ou",
    # Relative to line
    "rpg_vs_line",                # combined_rpg - close_ou
    "rpg_last10_vs_line",         # combined_rpg_last10 - close_ou
    # Session 18: tested hold_rate/power_rate/effective_obp_combined — all degraded
    # AUC and ROI. Reverted. See A/B analysis in session 18.
]

# --- V2: Interaction features (session 19 experiment) ---
# V1 (OU_FEATURES) remains production default. V2 is experimental.
# Insight: combined sums destroy matchup info. Interactions capture
# "weak bullpen × strong opponent offense" signals that sums miss.
OU_FEATURES_V2 = [
    # Tier 1: Core matchup interactions
    "matchup_rpg_x_sp_ra",          # (rpg_home*away_sp_ra + rpg_away*home_sp_ra) / 2
    "matchup_rpg10_x_sp_ra",        # recent form RPG × opposing starter RA
    "matchup_rpg_x_bp_fip",         # offense × opposing bullpen FIP (7g rolling)
    "matchup_offense_x_defense",    # league-relative offense × league-relative defense
    "home_offense_x_away_sp",       # rpg_home × away_sp_fip (asymmetric)
    "away_offense_x_home_sp",       # rpg_away × home_sp_fip (asymmetric)
    "home_rpg_x_away_bp_workload",  # offense × tired opposing bullpen
    "away_rpg_x_home_bp_workload",  # mirror
    # Tier 2: Pitching quality interactions
    "sp_quality_gap",               # abs(home_sp_ra_long - away_sp_ra_long)
    "max_offense_x_worst_sp",       # max(rpg_home, rpg_away) × sp_quality_floor
    "effective_obp_x_sp_fip",       # handedness-matched OBP × opposing FIP
    "bp_fip_osc_x_rpg",            # deteriorating bullpen × opponent offense
    # Tier 3: Environment context (retained from V1)
    "combined_rpg",
    "combined_rpg_last10",
    "sp_quality_floor",
    "sp_ip_per_start_combined",
    "pyth_wp_combined",
    "fi_score_rate_combined",
    "close_ou",
    "rpg_vs_line",
]

# --- V3: Hybrid = V1 combined + top 4 V2 interactions ---
# Keep all V1 combined features, add only the highest-importance interactions.
OU_FEATURES_V3 = OU_FEATURES + [
    "bp_fip_osc_x_rpg",        # deteriorating bullpen × opponent offense (12.2% imp)
    "matchup_rpg_x_bp_fip",    # offense × opposing bullpen FIP (10.6% imp)
    "sp_quality_gap",           # abs starter mismatch (5.6% imp)
    "effective_obp_x_sp_fip",  # handedness-matched OBP × opposing FIP (4.2% imp)
]

# --- NRFI: 1st-inning specific features (Set A) ---
# SUM composites — NRFI = "both pitchers suppress", symmetric signal.
# All columns produced by build_yrfi_features().
NRFI_FEATURES_A = [
    "sp_fi_ra_combined",           # pitcher 1st-inn RA (5-start window)
    "sp_fi_ra_combined_long",      # pitcher 1st-inn RA (15-start window)
    "sp_fi_momentum_combined",     # 1st-inn form oscillator (short - long)
    "fi_score_rate_combined",      # team 1st-inn scoring tendency (season)
    "fi_score_rate_last_combined", # team 1st-inn rate (last 25 games)
    "top3_babip_inn1_combined",    # batter contact quality in 1st inning
    "sp_babip_inn1_combined",      # pitcher hit-allowing quality in 1st
    "effective_obp_combined",      # handedness-matched lineup OBP
    "starter_fip_combined",        # combined starter FIP
    "starter_kbb_combined",        # combined K/BB ratio (higher = better pitching)
    "starter_whip_combined",       # combined WHIP
    "close_ou",                    # market context (drives NRFI pricing)
    "combined_rpg",                # total scoring environment
]


def build_ou_features(
    games: pd.DataFrame | None = None,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build feature set for Over/Under prediction.

    Combined (sum) features rather than diffs — O/U is about total scoring
    environment, not which team wins.

    Args:
        games: Raw game-level DataFrame. If None, loads all seasons.
        enriched: Pre-computed enriched DataFrame from build_all_features().
            If provided, skips the full pipeline and just computes O/U features.

    Returns:
        DataFrame with OU_FEATURES columns, targets (total_runs, under_hit),
        and metadata (season, date, teams, close_ou).
    """
    if enriched is None:
        from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons

        if games is None:
            logger.info("Loading all seasons for O/U features...")
            games = load_all_seasons()
        games = apply_data_filters(games)
        games = add_derived_odds(games)
        logger.info("Building all features for O/U...")
        enriched = build_all_features(games)

    df = enriched.copy()

    # ── Targets ───────────────────────────────────────────────────────────
    df["total_runs"] = df["home_final"] + df["away_final"]
    df["under_hit"] = (df["total_runs"] < df["close_ou"]).astype(int)
    df["over_hit"] = (df["total_runs"] > df["close_ou"]).astype(int)
    df["is_push"] = df["total_runs"] == df["close_ou"]

    # ── Combined scoring features ─────────────────────────────────────────
    df["combined_rpg"] = df["rpg_home"] + df["rpg_away"]
    df["combined_rapg"] = df["rapg_home"] + df["rapg_away"]

    if "rpg_last10_home" in df.columns:
        df["combined_rpg_last10"] = df["rpg_last10_home"] + df["rpg_last10_away"]
    if "rapg_last10_home" in df.columns:
        df["combined_rapg_last10"] = df["rapg_last10_home"] + df["rapg_last10_away"]

    # ── Combined pitcher features ─────────────────────────────────────────
    _safe_sum(df, "sp_ra_combined_short", "home_sp_ra_short", "away_sp_ra_short")
    _safe_sum(df, "sp_ra_combined_long", "home_sp_ra_long", "away_sp_ra_long")
    # sp_quality_floor already computed by pitcher_features.py
    _safe_sum(df, "sp_fip_combined", "home_sp_fip_short", "away_sp_fip_short")
    _safe_sum(df, "sp_whip_combined", "home_sp_whip_short", "away_sp_whip_short")
    _safe_sum(df, "sp_kbb_combined", "home_sp_kbb_short", "away_sp_kbb_short")
    _safe_sum(df, "sp_ip_per_start_combined", "home_sp_ip_per_start_short", "away_sp_ip_per_start_short")

    # ── Combined bullpen features ─────────────────────────────────────────
    _safe_sum(df, "bullpen_fip_combined", "bp_fip_short_home", "bp_fip_short_away")
    _safe_sum(df, "bullpen_fip_7g_combined", "bp_fip_7g_home", "bp_fip_7g_away")
    _safe_sum(df, "bullpen_ip_3d_combined", "bp_ip_3d_home", "bp_ip_3d_away")

    # ── Bullpen FIP oscillator (7g minus season; positive = deteriorating) ──
    if all(c in df.columns for c in ["bp_fip_7g_home", "bp_fip_long_home",
                                      "bp_fip_7g_away", "bp_fip_long_away"]):
        bp_osc_home = df["bp_fip_7g_home"] - df["bp_fip_long_home"]
        bp_osc_away = df["bp_fip_7g_away"] - df["bp_fip_long_away"]
        df["bp_fip_osc_combined"] = bp_osc_home + bp_osc_away
    else:
        df["bp_fip_osc_combined"] = np.nan

    # ── League-relative combined ──────────────────────────────────────────
    _safe_sum(df, "offense_vs_league_combined", "offense_vs_league_home", "offense_vs_league_away")
    _safe_sum(df, "defense_vs_league_combined", "defense_vs_league_home", "defense_vs_league_away")

    # ── Team quality combined ─────────────────────────────────────────────
    _safe_sum(df, "pyth_wp_combined", "pyth_wp_home", "pyth_wp_away")

    # ── 1st inning scoring tendency ───────────────────────────────────────
    _safe_sum(df, "fi_score_rate_combined", "fi_score_rate_home", "fi_score_rate_away")

    # ── Relative to line ──────────────────────────────────────────────────
    if "combined_rpg" in df.columns and "close_ou" in df.columns:
        df["rpg_vs_line"] = df["combined_rpg"] - df["close_ou"]
    if "combined_rpg_last10" in df.columns and "close_ou" in df.columns:
        df["rpg_last10_vs_line"] = df["combined_rpg_last10"] - df["close_ou"]

    # ── Session 18: late-game + matchup combined features ────────────────
    _safe_sum(df, "hold_rate_combined", "hold_rate_home", "hold_rate_away")
    _safe_sum(df, "power_rate_combined", "power_rate_home", "power_rate_away")
    _safe_sum(df, "effective_obp_combined", "effective_obp_home", "effective_obp_away")

    # ── O/U regime labels (for regression model) ──────────────────────────
    margin = df["total_runs"] - df["close_ou"]
    df["ou_regime"] = np.where(
        margin >= 2, "T_OVER2",
        np.where(margin >= 1, "T_OVER1",
                 np.where(margin < 0, "T_UNDER", "T0")),
    )

    # ── O/U filters ──────────────────────────────────────────────────────
    n_before = len(df)
    mask = pd.Series(True, index=df.index)

    # Exclude Colorado (extreme park factor)
    if "involves_col" in df.columns:
        mask &= ~df["involves_col"]

    # Exclude missing O/U line
    mask &= df["close_ou"].notna()

    df = df[mask].copy()
    logger.info(
        f"O/U features: {n_before} -> {len(df)} games "
        f"(excluded {n_before - len(df)})"
    )

    # ── Feature availability report ───────────────────────────────────────
    available = [f for f in OU_FEATURES if f in df.columns and df[f].notna().mean() > 0.3]
    missing = [f for f in OU_FEATURES if f not in available]
    if missing:
        logger.warning(f"O/U features with low coverage: {missing}")
    logger.info(
        f"O/U features available: {len(available)}/{len(OU_FEATURES)} | "
        f"Pushes: {df['is_push'].sum()} | "
        f"Under rate: {df.loc[~df['is_push'], 'under_hit'].mean() * 100:.1f}%"
    )

    return df


def build_ou_features_v3(
    games: pd.DataFrame | None = None,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build V3 hybrid feature set: V1 combined + top 4 V2 interactions.

    Starts from build_ou_features() output, adds only:
    - bp_fip_osc_x_rpg, matchup_rpg_x_bp_fip, sp_quality_gap, effective_obp_x_sp_fip
    """
    df = build_ou_features(games, enriched=enriched)

    # ── bp_fip_osc_x_rpg: deteriorating bullpen × opponent offense ──
    if all(c in df.columns for c in ["bp_fip_7g_home", "bp_fip_long_home",
                                      "bp_fip_7g_away", "bp_fip_long_away"]):
        bp_osc_home = df["bp_fip_7g_home"] - df["bp_fip_long_home"]
        bp_osc_away = df["bp_fip_7g_away"] - df["bp_fip_long_away"]
        df["bp_fip_osc_x_rpg"] = (bp_osc_home * df["rpg_away"] + bp_osc_away * df["rpg_home"]) / 2
    else:
        df["bp_fip_osc_x_rpg"] = np.nan

    # ── matchup_rpg_x_bp_fip: offense × opposing bullpen FIP ──
    _safe_cross_sum(df, "matchup_rpg_x_bp_fip",
                    "rpg_home", "bp_fip_7g_away",
                    "rpg_away", "bp_fip_7g_home")

    # ── sp_quality_gap: absolute starter mismatch ──
    if "home_sp_ra_long" in df.columns and "away_sp_ra_long" in df.columns:
        df["sp_quality_gap"] = (df["home_sp_ra_long"] - df["away_sp_ra_long"]).abs()
    else:
        df["sp_quality_gap"] = np.nan

    # ── effective_obp_x_sp_fip: handedness-matched OBP × opposing FIP ──
    _safe_cross_sum(df, "effective_obp_x_sp_fip",
                    "effective_obp_home", "away_sp_fip_short",
                    "effective_obp_away", "home_sp_fip_short")

    # ── Report ──
    available = [f for f in OU_FEATURES_V3 if f in df.columns and df[f].notna().mean() > 0.3]
    missing = [f for f in OU_FEATURES_V3 if f not in available]
    if missing:
        logger.warning(f"O/U V3 features with low coverage: {missing}")
    logger.info(f"O/U V3 features available: {len(available)}/{len(OU_FEATURES_V3)}")

    return df


# --- OVER-dedicated: asymmetric offensive + directional interactions ---
# Designed for predicting over_hit (target: when does scoring explode?).
# Key difference from V3: individual team metrics instead of combined sums,
# directional interactions instead of averaged cross-sums, pitching-quality
# sums dropped (those are UNDER signal generators).
OU_FEATURES_OVER = [
    # Tier 1: Offensive firepower (individual, NOT sums)
    "power_rate_home",              # fraction of scoring innings with 2+ runs
    "power_rate_away",
    "effective_obp_home",           # handedness-matched OBP vs opposing starter
    "effective_obp_away",
    "rpg_home",                     # runs per game (season rolling)
    "rpg_away",
    # Tier 2: Pitching vulnerability (individual oscillators)
    "sp_quality_floor",             # max(home_sp_ra_long, away_sp_ra_long) — worst starter
    "bp_fip_osc_home",              # bp_fip_7g - bp_fip_long (positive = deteriorating)
    "bp_fip_osc_away",
    "bp_ip_3d_home",                # recent bullpen workload (raw, individual)
    "bp_ip_3d_away",
    # Tier 3: Directional interactions (one strong matchup → OVER)
    "home_offense_x_away_bp_fatigue",   # rpg_home * bp_fip_osc_away
    "away_offense_x_home_bp_fatigue",   # rpg_away * bp_fip_osc_home
    "effective_obp_x_sp_ra_home",       # effective_obp_home * away_sp_ra_long
    "effective_obp_x_sp_ra_away",       # effective_obp_away * home_sp_ra_long
    "power_rate_max_x_sp_floor",        # max(power_rate_h, power_rate_a) * sp_quality_floor
    # Tier 4: Environment context (combined, proven features)
    "combined_rpg",                 # total scoring environment
    "rpg_vs_line",                  # combined_rpg - close_ou (market inefficiency)
    "fi_score_rate_combined",       # early scoring tendency
    "offense_vs_league_combined",   # league-relative offense
    "sp_quality_gap",               # abs(home_sp_ra_long - away_sp_ra_long)
    "wrc_plus_combined",            # wrc_plus_home + wrc_plus_away (FanGraphs Y-1)
]

# Minimal OVER: Tiers 1 + 3 only (pure asymmetric, no context features)
OU_FEATURES_OVER_MINIMAL = [f for f in OU_FEATURES_OVER
                            if f not in {"combined_rpg", "rpg_vs_line",
                                         "fi_score_rate_combined",
                                         "offense_vs_league_combined",
                                         "sp_quality_gap", "wrc_plus_combined",
                                         "sp_quality_floor", "bp_fip_osc_home",
                                         "bp_fip_osc_away", "bp_ip_3d_home",
                                         "bp_ip_3d_away"}]


def build_ou_features_over(
    games: pd.DataFrame | None = None,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build OVER-dedicated feature set: asymmetric offense + directional interactions.

    Starts from build_ou_features() base (data, targets, filters), then adds:
    - Individual bullpen oscillators (not combined)
    - Directional offense x pitching vulnerability interactions
    - FanGraphs wRC+ (Y-1 anti-leakage)
    """
    df = build_ou_features(games, enriched=enriched)

    # ── Individual bullpen FIP oscillators ──────────────────────────────────
    if all(c in df.columns for c in ["bp_fip_7g_home", "bp_fip_long_home"]):
        df["bp_fip_osc_home"] = df["bp_fip_7g_home"] - df["bp_fip_long_home"]
    else:
        df["bp_fip_osc_home"] = np.nan

    if all(c in df.columns for c in ["bp_fip_7g_away", "bp_fip_long_away"]):
        df["bp_fip_osc_away"] = df["bp_fip_7g_away"] - df["bp_fip_long_away"]
    else:
        df["bp_fip_osc_away"] = np.nan

    # ── Directional interactions ────────────────────────────────────────────
    # home offense × away bullpen fatigue
    if "rpg_home" in df.columns and "bp_fip_osc_away" in df.columns:
        df["home_offense_x_away_bp_fatigue"] = df["rpg_home"] * df["bp_fip_osc_away"]
    else:
        df["home_offense_x_away_bp_fatigue"] = np.nan

    # away offense × home bullpen fatigue
    if "rpg_away" in df.columns and "bp_fip_osc_home" in df.columns:
        df["away_offense_x_home_bp_fatigue"] = df["rpg_away"] * df["bp_fip_osc_home"]
    else:
        df["away_offense_x_home_bp_fatigue"] = np.nan

    # effective OBP × opposing starter RA (lineup gets on base vs vulnerable pitcher)
    if "effective_obp_home" in df.columns and "away_sp_ra_long" in df.columns:
        df["effective_obp_x_sp_ra_home"] = df["effective_obp_home"] * df["away_sp_ra_long"]
    else:
        df["effective_obp_x_sp_ra_home"] = np.nan

    if "effective_obp_away" in df.columns and "home_sp_ra_long" in df.columns:
        df["effective_obp_x_sp_ra_away"] = df["effective_obp_away"] * df["home_sp_ra_long"]
    else:
        df["effective_obp_x_sp_ra_away"] = np.nan

    # max(power_rate) × worst starter RA (explosive offense vs weakest pitcher)
    if all(c in df.columns for c in ["power_rate_home", "power_rate_away", "sp_quality_floor"]):
        power_max = df[["power_rate_home", "power_rate_away"]].max(axis=1)
        df["power_rate_max_x_sp_floor"] = power_max * df["sp_quality_floor"]
    else:
        df["power_rate_max_x_sp_floor"] = np.nan

    # ── sp_quality_gap (already computed by V3 builder, but ensure exists) ──
    if "sp_quality_gap" not in df.columns:
        if "home_sp_ra_long" in df.columns and "away_sp_ra_long" in df.columns:
            df["sp_quality_gap"] = (df["home_sp_ra_long"] - df["away_sp_ra_long"]).abs()
        else:
            df["sp_quality_gap"] = np.nan

    # ── FanGraphs wRC+ (Y-1 anti-leakage) ──────────────────────────────────
    if "wrc_plus_home" not in df.columns:
        from src.data_loader import PROCESSED_DIR, _map_team_code_to_retrosheet
        fg_path = PROCESSED_DIR / "fangraphs" / "team_batting_season.parquet"
        if fg_path.exists():
            fg = pd.read_parquet(fg_path)
            fg = fg.rename(columns={"season": "stat_season"})
            fg["season"] = fg["stat_season"] + 1  # Y-1 anti-leakage
            for side, team_col in [("home", "home_team"), ("away", "away_team")]:
                df[f"_fg_{side}_team"] = df.apply(
                    lambda r, _tc=team_col: _map_team_code_to_retrosheet(r[_tc], r["season"]),
                    axis=1,
                )
                side_fg = fg.rename(columns={
                    "team": f"_fg_{side}_team",
                    "wrc_plus": f"wrc_plus_{side}",
                })[["season", f"_fg_{side}_team", f"wrc_plus_{side}"]]
                df = df.merge(side_fg, on=["season", f"_fg_{side}_team"], how="left")
                df = df.drop(columns=[f"_fg_{side}_team"])
        else:
            logger.warning(f"FanGraphs data not found at {fg_path}. wrc_plus will be NaN.")
            df["wrc_plus_home"] = np.nan
            df["wrc_plus_away"] = np.nan

    _safe_sum(df, "wrc_plus_combined", "wrc_plus_home", "wrc_plus_away")

    # ── Report ──────────────────────────────────────────────────────────────
    available = [f for f in OU_FEATURES_OVER if f in df.columns and df[f].notna().mean() > 0.3]
    missing = [f for f in OU_FEATURES_OVER if f not in available]
    if missing:
        logger.warning(f"OVER features with low coverage: {missing}")
    logger.info(f"OVER features available: {len(available)}/{len(OU_FEATURES_OVER)}")

    return df


def build_ou_features_v2(
    games: pd.DataFrame | None = None,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build V2 feature set for Over/Under prediction with INTERACTION features.

    V2 replaces most combined sums with matchup interactions:
    offense × opposing pitching, bullpen vulnerability × opponent strength, etc.
    Retains 8 environmental context features from V1.

    V1 (build_ou_features) remains production default. This is experimental.

    Args:
        games: Raw game-level DataFrame. If None, loads all seasons.
        enriched: Pre-computed enriched DataFrame from build_all_features().

    Returns:
        DataFrame with OU_FEATURES_V2 columns, targets (total_runs, under_hit),
        and metadata (season, date, teams, close_ou).
    """
    if enriched is None:
        from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons

        if games is None:
            logger.info("Loading all seasons for O/U V2 features...")
            games = load_all_seasons()
        games = apply_data_filters(games)
        games = add_derived_odds(games)
        logger.info("Building all features for O/U V2...")
        enriched = build_all_features(games)

    df = enriched.copy()

    # ── Targets (same as V1) ───────────────────────────────────────────────
    df["total_runs"] = df["home_final"] + df["away_final"]
    df["under_hit"] = (df["total_runs"] < df["close_ou"]).astype(int)
    df["over_hit"] = (df["total_runs"] > df["close_ou"]).astype(int)
    df["is_push"] = df["total_runs"] == df["close_ou"]

    # ── Tier 1: Core matchup interactions ──────────────────────────────────

    # Offense vs opposing starter (symmetric, averaged)
    _safe_cross_sum(df, "matchup_rpg_x_sp_ra",
                    "rpg_home", "away_sp_ra_short",
                    "rpg_away", "home_sp_ra_short")

    # Recent form offense vs opposing starter
    if "rpg_last10_home" in df.columns:
        _safe_cross_sum(df, "matchup_rpg10_x_sp_ra",
                        "rpg_last10_home", "away_sp_ra_short",
                        "rpg_last10_away", "home_sp_ra_short")
    else:
        df["matchup_rpg10_x_sp_ra"] = np.nan

    # Offense vs opposing bullpen (7-game rolling FIP)
    _safe_cross_sum(df, "matchup_rpg_x_bp_fip",
                    "rpg_home", "bp_fip_7g_away",
                    "rpg_away", "bp_fip_7g_home")

    # League-relative matchup: offense_vs_league × defense_vs_league
    _safe_cross_sum(df, "matchup_offense_x_defense",
                    "offense_vs_league_home", "defense_vs_league_away",
                    "offense_vs_league_away", "defense_vs_league_home")

    # Asymmetric: home bats vs away starter FIP
    _safe_product(df, "home_offense_x_away_sp", "rpg_home", "away_sp_fip_short")

    # Asymmetric: away bats vs home starter FIP
    _safe_product(df, "away_offense_x_home_sp", "rpg_away", "home_sp_fip_short")

    # Offense vs tired opposing bullpen (3-day workload)
    _safe_product(df, "home_rpg_x_away_bp_workload", "rpg_home", "bp_ip_3d_away")
    _safe_product(df, "away_rpg_x_home_bp_workload", "rpg_away", "bp_ip_3d_home")

    # ── Tier 2: Pitching quality interactions ──────────────────────────────

    # Starter mismatch: absolute gap in long-term RA
    if "home_sp_ra_long" in df.columns and "away_sp_ra_long" in df.columns:
        df["sp_quality_gap"] = (df["home_sp_ra_long"] - df["away_sp_ra_long"]).abs()
    else:
        df["sp_quality_gap"] = np.nan

    # Best offense × worst starter
    if "sp_quality_floor" in df.columns:
        max_rpg = df[["rpg_home", "rpg_away"]].max(axis=1)
        df["max_offense_x_worst_sp"] = max_rpg * df["sp_quality_floor"]
    else:
        df["max_offense_x_worst_sp"] = np.nan

    # Handedness-matched OBP × opposing FIP
    _safe_cross_sum(df, "effective_obp_x_sp_fip",
                    "effective_obp_home", "away_sp_fip_short",
                    "effective_obp_away", "home_sp_fip_short")

    # Deteriorating bullpen × opponent offense
    if all(c in df.columns for c in ["bp_fip_7g_home", "bp_fip_long_home",
                                      "bp_fip_7g_away", "bp_fip_long_away"]):
        bp_osc_home = df["bp_fip_7g_home"] - df["bp_fip_long_home"]
        bp_osc_away = df["bp_fip_7g_away"] - df["bp_fip_long_away"]
        df["bp_fip_osc_x_rpg"] = (bp_osc_home * df["rpg_away"] + bp_osc_away * df["rpg_home"]) / 2
    else:
        df["bp_fip_osc_x_rpg"] = np.nan

    # ── Tier 3: Retained environment context from V1 ──────────────────────

    df["combined_rpg"] = df["rpg_home"] + df["rpg_away"]
    if "rpg_last10_home" in df.columns:
        df["combined_rpg_last10"] = df["rpg_last10_home"] + df["rpg_last10_away"]

    # sp_quality_floor already computed by pitcher_features.py
    _safe_sum(df, "sp_ip_per_start_combined", "home_sp_ip_per_start_short", "away_sp_ip_per_start_short")
    _safe_sum(df, "pyth_wp_combined", "pyth_wp_home", "pyth_wp_away")
    _safe_sum(df, "fi_score_rate_combined", "fi_score_rate_home", "fi_score_rate_away")

    # Relative to line
    if "combined_rpg" in df.columns and "close_ou" in df.columns:
        df["rpg_vs_line"] = df["combined_rpg"] - df["close_ou"]

    # ── O/U regime labels (same as V1) ─────────────────────────────────────
    margin = df["total_runs"] - df["close_ou"]
    df["ou_regime"] = np.where(
        margin >= 2, "T_OVER2",
        np.where(margin >= 1, "T_OVER1",
                 np.where(margin < 0, "T_UNDER", "T0")),
    )

    # ── O/U filters (same as V1) ──────────────────────────────────────────
    n_before = len(df)
    mask = pd.Series(True, index=df.index)
    if "involves_col" in df.columns:
        mask &= ~df["involves_col"]
    mask &= df["close_ou"].notna()

    df = df[mask].copy()
    logger.info(
        f"O/U V2 features: {n_before} -> {len(df)} games "
        f"(excluded {n_before - len(df)})"
    )

    # ── Feature availability report ────────────────────────────────────────
    available = [f for f in OU_FEATURES_V2 if f in df.columns and df[f].notna().mean() > 0.3]
    missing = [f for f in OU_FEATURES_V2 if f not in available]
    if missing:
        logger.warning(f"O/U V2 features with low coverage: {missing}")
    logger.info(
        f"O/U V2 features available: {len(available)}/{len(OU_FEATURES_V2)} | "
        f"Pushes: {df['is_push'].sum()} | "
        f"Under rate: {df.loc[~df['is_push'], 'under_hit'].mean() * 100:.1f}%"
    )

    return df


def build_yrfi_features(
    games: pd.DataFrame | None = None,
    *,
    enriched: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build YRFI feature set: lineup + BABIP + pitcher SUM composites.

    Adds 1st-inning BABIP features (from retrosheet parquets) and
    pitcher/team SUM composites needed for YRFI filter strategies.

    Args:
        games: Raw game-level DataFrame. If None, loads all seasons.
        enriched: Pre-computed enriched DataFrame from build_all_features().

    Returns:
        DataFrame with YRFI composite columns, target (yrfi), and metadata.
        Only includes games with real inning-by-inning data.
    """
    from src.data_loader import (
        PROCESSED_DIR,
        _map_team_code_to_retrosheet,
    )

    if enriched is None:
        from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons

        if games is None:
            games = load_all_seasons()
        games = apply_data_filters(games)
        games = add_derived_odds(games)
        enriched = build_all_features(games)

    df = enriched.copy()

    # Filter to real inning data (exclude seasons with fake zeros)
    inn_cols_away = [f"away_inn_{i}" for i in range(1, 10) if f"away_inn_{i}" in df.columns]
    inn_cols_home = [f"home_inn_{i}" for i in range(1, 10) if f"home_inn_{i}" in df.columns]
    if inn_cols_away and inn_cols_home:
        away_inn_sum = df[inn_cols_away].sum(axis=1)
        home_inn_sum = df[inn_cols_home].sum(axis=1)
        has_inning_data = (away_inn_sum + home_inn_sum) > 0
        df = df[has_inning_data].copy()

    # YRFI target
    if "away_inn_1" in df.columns and "home_inn_1" in df.columns:
        df["inn1_runs"] = df["away_inn_1"] + df["home_inn_1"]
        df["yrfi"] = (df["inn1_runs"] > 0).astype(int)

    # ── Merge 1st-inning BABIP ─────────────────────────────────────────
    babip_path = PROCESSED_DIR / "retrosheet" / "first_inning_babip.parquet"
    if babip_path.exists():
        babip = pd.read_parquet(babip_path)
        babip["date"] = pd.to_datetime(babip["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_bb_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]),
                axis=1,
            )
            bb_rename = {
                "team": f"_bb_{side}_team",
                "top3_babip_inn1": f"top3_babip_inn1_{side}",
                "sp_babip_inn1": f"sp_babip_inn1_{side}",
            }
            side_bb = babip[
                ["team", "date", "top3_babip_inn1", "sp_babip_inn1"]
            ].rename(columns=bb_rename)
            side_bb = side_bb.drop_duplicates(
                subset=[f"_bb_{side}_team", "date"], keep="first"
            )
            df = df.merge(side_bb, on=[f"_bb_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_bb_{side}_team"])

        _safe_sum(df, "top3_babip_inn1_combined", "top3_babip_inn1_home", "top3_babip_inn1_away")
        _safe_sum(df, "sp_babip_inn1_combined", "sp_babip_inn1_home", "sp_babip_inn1_away")
    else:
        logger.warning(f"BABIP features not found at {babip_path}")

    # ── Pitcher SUM composites ─────────────────────────────────────────
    _safe_sum(df, "sp_fi_ra_combined", "home_sp_fi_ra_short", "away_sp_fi_ra_short")
    _safe_sum(df, "sp_fi_ra_combined_long", "home_sp_fi_ra_long", "away_sp_fi_ra_long")
    _safe_sum(df, "sp_fi_momentum_combined", "home_sp_fi_momentum", "away_sp_fi_momentum")
    _safe_sum(df, "sp_ra_momentum_combined", "home_sp_ra_momentum", "away_sp_ra_momentum")
    _safe_sum(df, "starter_fip_combined", "home_sp_fip_short", "away_sp_fip_short")
    _safe_sum(df, "starter_whip_combined", "home_sp_whip_short", "away_sp_whip_short")
    _safe_sum(df, "starter_kbb_combined", "home_sp_kbb_short", "away_sp_kbb_short")

    # ── Team SUM composites ────────────────────────────────────────────
    _safe_sum(df, "combined_rpg", "rpg_home", "rpg_away")
    _safe_sum(df, "combined_rpg_last10", "rpg_last10_home", "rpg_last10_away")
    _safe_sum(df, "combined_rapg", "rapg_home", "rapg_away")
    _safe_sum(df, "fi_score_rate_combined", "fi_score_rate_home", "fi_score_rate_away")
    _safe_sum(df, "fi_score_rate_last_combined", "fi_score_rate_last_home", "fi_score_rate_last_away")

    # ── Effective OBP (handedness-matched lineup OBP) ──────────────────
    if all(
        c in df.columns
        for c in [
            "away_sp_hand", "home_sp_hand",
            "top3_obp_vs_rhp_home", "top3_obp_vs_lhp_home",
            "top3_obp_vs_rhp_away", "top3_obp_vs_lhp_away",
        ]
    ):
        df["effective_obp_home"] = np.where(
            df["away_sp_hand"] == "R",
            df["top3_obp_vs_rhp_home"],
            df["top3_obp_vs_lhp_home"],
        )
        df["effective_obp_away"] = np.where(
            df["home_sp_hand"] == "R",
            df["top3_obp_vs_rhp_away"],
            df["top3_obp_vs_lhp_away"],
        )
        _safe_sum(df, "effective_obp_combined", "effective_obp_home", "effective_obp_away")

    n_yrfi = len(df)
    n_babip = df["top3_babip_inn1_home"].notna().sum() if "top3_babip_inn1_home" in df.columns else 0
    logger.info(
        f"YRFI features: {n_yrfi} games with inning data, "
        f"BABIP coverage: {n_babip}/{n_yrfi}"
    )
    return df


def _safe_sum(df: pd.DataFrame, target: str, col_a: str, col_b: str) -> None:
    """Sum two columns into target, producing NaN if either is missing."""
    if col_a in df.columns and col_b in df.columns:
        df[target] = df[col_a] + df[col_b]
    else:
        df[target] = np.nan


def _safe_product(df: pd.DataFrame, target: str, col_a: str, col_b: str) -> None:
    """Multiply two columns into target, producing NaN if either is missing."""
    if col_a in df.columns and col_b in df.columns:
        df[target] = df[col_a] * df[col_b]
    else:
        df[target] = np.nan


def _safe_cross_sum(
    df: pd.DataFrame,
    target: str,
    off_home: str,
    def_away: str,
    off_away: str,
    def_home: str,
) -> None:
    """Compute (off_home * def_away + off_away * def_home) / 2.

    Symmetric interaction: captures both sides of the matchup and averages.
    Produces NaN if any required column is missing.
    """
    cols = [off_home, def_away, off_away, def_home]
    if all(c in df.columns for c in cols):
        df[target] = (df[off_home] * df[def_away] + df[off_away] * df[def_home]) / 2
    else:
        df[target] = np.nan
