"""Squad Stability Score (SSS) computation for Turkish Super Lig.

Computes weighted SSS using player impact scores derived from
intra-team share of goals and assists (transfermarkt data).

Two variants:
  1. Cumulative (season-to-date): uses all prior matches in the season
  2. Rolling-10: uses only the last 10 matches

Data leakage prevention:
  - All metrics computed using ONLY data before the current match
  - Player/team accumulators updated AFTER SSS is recorded
  - Season boundaries reset all accumulators
  - First match of each season -> SSS = NaN

Impact score (Variant A — intra-team share):
  impact_i = max(
      player_goals / team_goals,
      player_assists / team_assists,
  )
  Guards: 0/0 -> 0, all team totals zero -> equal weights (1.0)

SSS_w = Σ(impact_i × MinPct_i) / Σ(impact_i) for starters

Usage:
    from src.features import build_sss_features

    enriched = build_sss_features(games)
    # Adds: sss_cum_home, sss_cum_away, sss_cum_diff,
    #        sss_r10_home, sss_r10_away, sss_r10_diff
"""

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

ROLLING_WINDOW = 10

# Stats used for impact score calculation (transfermarkt data: goals + assists)
# Minutes-share is always included as a baseline dimension so that players
# with 0 goals/assists (most defenders) still get non-zero impact.
IMPACT_STATS = ["goals", "assists"]


# ---------------------------------------------------------------------------
# Accumulators for leakage-free computation
# ---------------------------------------------------------------------------

@dataclass
class PlayerAccum:
    """Per-player running totals within a season."""
    minutes: float = 0.0
    goals: float = 0.0
    assists: float = 0.0


@dataclass
class TeamAccum:
    """Per-team running totals within a season."""
    matches_played: int = 0
    total_goals: float = 0.0
    total_assists: float = 0.0
    total_minutes: float = 0.0
    players: dict[str, PlayerAccum] = field(default_factory=dict)

    # Rolling window: store per-match snapshots for rolling-N computation
    match_snapshots: list[dict] = field(default_factory=list)

    def get_player(self, name: str) -> PlayerAccum:
        if name not in self.players:
            self.players[name] = PlayerAccum()
        return self.players[name]


@dataclass
class MatchSnapshot:
    """Per-match player stats, stored for rolling window computation."""
    player_stats: dict[str, dict]  # player_name -> {minutes, xg, xa, tackles, interceptions}
    team_totals: dict  # {xg, xa, tackles, interceptions}


# ---------------------------------------------------------------------------
# Core SSS computation
# ---------------------------------------------------------------------------

def compute_impact(
    player_accum: PlayerAccum,
    team_accum: TeamAccum,
) -> float:
    """Compute impact score for a single player.

    impact = max(minutes_share, goals_share, assists_share).
    Minutes-share is ALWAYS included as baseline so that defenders with
    0 goals/assists still get non-zero impact proportional to their playing time.
    If no team data exists, returns 1.0 (equal weight fallback).
    """
    ratios = []

    # Always include minutes-share as baseline
    if team_accum.total_minutes > 0:
        ratios.append(player_accum.minutes / team_accum.total_minutes)

    # Add goals/assists share (when team has any)
    for stat in IMPACT_STATS:
        player_val = getattr(player_accum, stat, 0.0)
        team_attr = f"total_{stat}"
        team_val = getattr(team_accum, team_attr, 0.0)

        if team_val > 0:
            ratios.append(player_val / team_val)

    if not ratios:
        return 1.0  # equal weight fallback (no team data yet)

    return max(ratios)


def compute_sss_for_lineup(
    lineup: list[dict],
    team_accum: TeamAccum,
) -> float | None:
    """Compute weighted SSS for a given lineup using pre-match accumulators.

    Args:
        lineup: list of player dicts from match data
            Each dict has: {player, is_starter, minutes, xg, xa, tackles, interceptions}
        team_accum: team's running totals (all data BEFORE this match)

    Returns:
        Weighted SSS or None if insufficient data
    """
    if team_accum.matches_played == 0:
        return None  # no prior data

    starters = [p for p in lineup if p.get("is_starter", False)]
    if not starters:
        return None

    max_possible_minutes = 90.0 * team_accum.matches_played

    numerator = 0.0
    denominator = 0.0

    for player_info in starters:
        # Use player_id as key (more reliable than name for accumulator lookups)
        name = str(player_info.get("player_id", player_info.get("player_name", "")))
        player_accum = team_accum.get_player(name)

        # MinPct: fraction of possible minutes this player has played
        min_pct = player_accum.minutes / max_possible_minutes if max_possible_minutes > 0 else 0.0

        # Impact: intra-team share (max across stats)
        impact = compute_impact(player_accum, team_accum)

        numerator += impact * min_pct
        denominator += impact

    if denominator == 0:
        return None

    return numerator / denominator


def compute_sss_rolling(
    lineup: list[dict],
    team_accum: TeamAccum,
    window: int = ROLLING_WINDOW,
) -> float | None:
    """Compute rolling-window SSS using only the last N matches.

    Uses match_snapshots stored in team_accum to rebuild
    player/team stats from the rolling window only.
    """
    snapshots = team_accum.match_snapshots
    if len(snapshots) == 0:
        return None

    # Use at most the last `window` snapshots
    recent = snapshots[-window:]

    # Rebuild player and team totals from rolling window
    rolling_team = TeamAccum(matches_played=len(recent))
    for snap in recent:
        rolling_team.total_minutes += snap.team_totals.get("minutes", 0.0)
        for stat in IMPACT_STATS:
            team_attr = f"total_{stat}"
            setattr(
                rolling_team, team_attr,
                getattr(rolling_team, team_attr) + snap.team_totals.get(stat, 0.0),
            )
        for player_name, pstats in snap.player_stats.items():
            p = rolling_team.get_player(player_name)
            p.minutes += pstats.get("minutes", 0.0)
            for stat in IMPACT_STATS:
                setattr(p, stat, getattr(p, stat) + pstats.get(stat, 0.0))

    return compute_sss_for_lineup(lineup, rolling_team)


# ---------------------------------------------------------------------------
# Update accumulators after a match (called AFTER SSS is recorded)
# ---------------------------------------------------------------------------

def update_accumulators(
    team_accum: TeamAccum,
    lineup: list[dict],
) -> None:
    """Update team and player accumulators with data from a completed match.

    Called AFTER SSS has been computed for this match to prevent leakage.
    """
    match_player_stats = {}
    match_team_totals = {stat: 0.0 for stat in IMPACT_STATS}
    match_total_minutes = 0.0

    for player_info in lineup:
        name = str(player_info.get("player_id", player_info.get("player_name", "")))
        minutes = float(player_info.get("minutes", 0) or 0)
        player_accum = team_accum.get_player(name)
        player_accum.minutes += minutes
        match_total_minutes += minutes

        player_match = {"minutes": minutes}

        for stat in IMPACT_STATS:
            val = float(player_info.get(stat, 0) or 0)
            setattr(player_accum, stat, getattr(player_accum, stat) + val)
            match_team_totals[stat] += val
            player_match[stat] = val

        match_player_stats[name] = player_match

    # Update team totals
    team_accum.matches_played += 1
    team_accum.total_minutes += match_total_minutes
    for stat in IMPACT_STATS:
        team_attr = f"total_{stat}"
        setattr(
            team_accum, team_attr,
            getattr(team_accum, team_attr) + match_team_totals[stat],
        )

    # Store snapshot for rolling window (include minutes in team_totals)
    match_team_totals["minutes"] = match_total_minutes
    team_accum.match_snapshots.append(MatchSnapshot(
        player_stats=match_player_stats,
        team_totals=match_team_totals,
    ))


# ---------------------------------------------------------------------------
# Build SSS features for all matches
# ---------------------------------------------------------------------------

def _compute_team_sss(
    games: pd.DataFrame,
    team_col: str,
    lineup_col: str,
) -> pd.DataFrame:
    """Compute SSS for one side (home or away) across all matches.

    Args:
        games: match DataFrame sorted by date
        team_col: column with canonical team code ("home_team" or "away_team")
        lineup_col: column with lineup list ("home_lineup" or "away_lineup")

    Returns:
        DataFrame with columns: _idx, sss_cum, sss_r10
    """
    results = []
    team_accums: dict[tuple[int, str], TeamAccum] = {}  # (season, team) -> accum

    for idx, row in games.iterrows():
        team = row[team_col]
        season = row["season"]
        key = (season, team)

        # Get or create accumulator
        if key not in team_accums:
            team_accums[key] = TeamAccum()
        accum = team_accums[key]

        lineup = row.get(lineup_col)

        if lineup is not None and isinstance(lineup, list) and len(lineup) > 0:
            # Compute SSS BEFORE updating accumulators
            sss_cum = compute_sss_for_lineup(lineup, accum)
            sss_r10 = compute_sss_rolling(lineup, accum)

            # Update accumulators AFTER computing SSS
            update_accumulators(accum, lineup)
        else:
            sss_cum = None
            sss_r10 = None

        results.append({
            "_idx": idx,
            "sss_cum": sss_cum,
            "sss_r10": sss_r10,
        })

    return pd.DataFrame(results)


def build_sss_features(games: pd.DataFrame) -> pd.DataFrame:
    """Build SSS features for all matches.

    Adds 6 columns to games:
      sss_cum_home, sss_cum_away, sss_cum_diff
      sss_r10_home, sss_r10_away, sss_r10_diff

    Args:
        games: match DataFrame from data_loader (must be sorted by date)

    Returns:
        games with SSS columns added
    """
    games = games.sort_values("date").reset_index(drop=True)

    # Check if lineup data exists
    if "home_lineup" not in games.columns or "away_lineup" not in games.columns:
        logger.warning("No lineup columns — cannot compute SSS. Adding NaN columns.")
        for col in ["sss_cum_home", "sss_cum_away", "sss_cum_diff",
                     "sss_r10_home", "sss_r10_away", "sss_r10_diff"]:
            games[col] = np.nan
        return games

    has_data = games["has_lineup_data"].sum() if "has_lineup_data" in games.columns else 0
    logger.info(f"Computing SSS for {has_data}/{len(games)} matches with lineup data")

    # Compute home SSS
    home_sss = _compute_team_sss(games, "home_team", "home_lineup")
    games["sss_cum_home"] = home_sss["sss_cum"].values
    games["sss_r10_home"] = home_sss["sss_r10"].values

    # Compute away SSS
    away_sss = _compute_team_sss(games, "away_team", "away_lineup")
    games["sss_cum_away"] = away_sss["sss_cum"].values
    games["sss_r10_away"] = away_sss["sss_r10"].values

    # Diffs
    games["sss_cum_diff"] = games["sss_cum_home"] - games["sss_cum_away"]
    games["sss_r10_diff"] = games["sss_r10_home"] - games["sss_r10_away"]

    # Coverage stats
    cum_coverage = games["sss_cum_home"].notna().mean()
    r10_coverage = games["sss_r10_home"].notna().mean()
    logger.info(
        f"SSS coverage — cumulative: {cum_coverage:.1%}, rolling-10: {r10_coverage:.1%}"
    )

    return games


# ---------------------------------------------------------------------------
# Form, congestion, market, context features
# ---------------------------------------------------------------------------

BIG_3 = {"GS", "FB", "BJK"}
FORM_WINDOW = 5


def _build_team_game_log(games: pd.DataFrame) -> pd.DataFrame:
    """Convert match-level → team-level (2 rows per match).

    Each row: team, date, season, goals_scored, goals_conceded, result_points,
              opponent, is_home.
    """
    rows = []
    for _, g in games.iterrows():
        rows.append({
            "date": g["date"], "season": g["season"],
            "team": g["home_team"], "opponent": g["away_team"],
            "goals_scored": g["home_goals"], "goals_conceded": g["away_goals"],
            "points": 3 if g["result"] == "H" else (1 if g["result"] == "D" else 0),
            "is_home": True,
        })
        rows.append({
            "date": g["date"], "season": g["season"],
            "team": g["away_team"], "opponent": g["home_team"],
            "goals_scored": g["away_goals"], "goals_conceded": g["home_goals"],
            "points": 3 if g["result"] == "A" else (1 if g["result"] == "D" else 0),
            "is_home": False,
        })
    log = pd.DataFrame(rows).sort_values(["team", "season", "date"]).reset_index(drop=True)
    return log


def _calc_form_features(log: pd.DataFrame) -> pd.DataFrame:
    """Compute per-team rolling form features. All look-back only (no leakage)."""
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        cum_points = 0.0
        cum_gf = 0.0
        cum_ga = 0.0
        streak = 0
        recent_points: list[int] = []
        recent_gf: list[float] = []
        recent_ga: list[float] = []

        for i in range(len(grp)):
            n_played = i  # matches played BEFORE this one

            if n_played == 0:
                ppg_cum = np.nan
                ppg_r5 = np.nan
                goal_diff_cum = np.nan
                gf_pg_cum = np.nan
                ga_pg_cum = np.nan
                gf_pg_r5 = np.nan
                ga_pg_r5 = np.nan
                feat_streak = 0
            else:
                ppg_cum = cum_points / n_played
                ppg_r5 = np.mean(recent_points[-FORM_WINDOW:]) if recent_points else np.nan
                goal_diff_cum = (cum_gf - cum_ga) / n_played
                gf_pg_cum = cum_gf / n_played
                ga_pg_cum = cum_ga / n_played
                gf_pg_r5 = np.mean(recent_gf[-FORM_WINDOW:]) if recent_gf else np.nan
                ga_pg_r5 = np.mean(recent_ga[-FORM_WINDOW:]) if recent_ga else np.nan
                feat_streak = streak

            results.append({
                "team": team, "date": grp.iloc[i]["date"], "season": season,
                "ppg_cum": ppg_cum,
                "ppg_r5": ppg_r5,
                "goal_diff_cum": goal_diff_cum,
                "gf_pg_cum": gf_pg_cum,
                "ga_pg_cum": ga_pg_cum,
                "gf_pg_r5": gf_pg_r5,
                "ga_pg_r5": ga_pg_r5,
                "streak": feat_streak,
            })

            # Update accumulators AFTER recording features
            pts = grp.iloc[i]["points"]
            gf = grp.iloc[i]["goals_scored"]
            ga = grp.iloc[i]["goals_conceded"]
            cum_points += pts
            cum_gf += gf
            cum_ga += ga
            recent_points.append(pts)
            recent_gf.append(gf)
            recent_ga.append(ga)

            # Streak: positive = consecutive wins, negative = consecutive losses
            if pts == 3:
                streak = streak + 1 if streak > 0 else 1
            elif pts == 0:
                streak = streak - 1 if streak < 0 else -1
            else:
                streak = 0

    return pd.DataFrame(results)


def _calc_congestion_features(log: pd.DataFrame) -> pd.DataFrame:
    """Compute days_rest and match_density_14d per team."""
    results = []

    for (team, season), grp in log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)
        dates = grp["date"].tolist()

        for i in range(len(grp)):
            if i == 0:
                days_rest = np.nan
            else:
                days_rest = (dates[i] - dates[i - 1]).days

            # Match density: matches in last 14 days (before this match)
            cutoff = dates[i] - pd.Timedelta(days=14)
            density = sum(1 for d in dates[:i] if d >= cutoff)

            results.append({
                "team": team, "date": dates[i], "season": season,
                "days_rest": days_rest,
                "match_density_14d": density,
            })

    return pd.DataFrame(results)


def build_form_congestion_features(games: pd.DataFrame) -> pd.DataFrame:
    """Add form + congestion features to match-level DataFrame.

    Adds columns:
      ppg_cum_home/away, ppg_r5_home/away, goal_diff_cum_home/away,
      streak_home/away, days_rest_home/away, match_density_14d_home/away,
      + diffs for each pair
    """
    log = _build_team_game_log(games)
    form = _calc_form_features(log)
    cong = _calc_congestion_features(log)

    # Merge form + congestion per team
    team_feats = form.merge(cong, on=["team", "date", "season"])

    FORM_CONG_FEATURES = [
        "ppg_cum", "ppg_r5", "goal_diff_cum", "streak",
        "gf_pg_cum", "ga_pg_cum", "gf_pg_r5", "ga_pg_r5",
        "days_rest", "match_density_14d",
    ]

    # Merge home side
    home = team_feats.rename(columns={c: f"{c}_home" for c in FORM_CONG_FEATURES})
    home = home.rename(columns={"team": "home_team", "date": "date", "season": "season"})
    merge_cols = ["home_team", "date", "season"] + [f"{c}_home" for c in FORM_CONG_FEATURES]
    games = games.merge(home[merge_cols], on=["home_team", "date", "season"], how="left")

    # Merge away side
    away = team_feats.rename(columns={c: f"{c}_away" for c in FORM_CONG_FEATURES})
    away = away.rename(columns={"team": "away_team", "date": "date", "season": "season"})
    merge_cols = ["away_team", "date", "season"] + [f"{c}_away" for c in FORM_CONG_FEATURES]
    games = games.merge(away[merge_cols], on=["away_team", "date", "season"], how="left")

    # Diffs
    for feat in FORM_CONG_FEATURES:
        games[f"{feat}_diff"] = games[f"{feat}_home"] - games[f"{feat}_away"]

    return games


def build_context_features(games: pd.DataFrame) -> pd.DataFrame:
    """Add market and context features.

    Adds: matchday (normalized), is_big3_home, is_big3_away.
    Overround is already added by data_loader.add_derived_odds().
    """
    # Matchday: normalized season progress (0→1)
    for season, grp in games.groupby("season"):
        idx = grp.index
        dates = grp["date"]
        min_date = dates.min()
        max_date = dates.max()
        span = (max_date - min_date).days
        if span > 0:
            games.loc[idx, "matchday"] = (dates - min_date).dt.days / span
        else:
            games.loc[idx, "matchday"] = 0.5

    # Big-3 flags
    games["is_big3_home"] = games["home_team"].isin(BIG_3).astype(int)
    games["is_big3_away"] = games["away_team"].isin(BIG_3).astype(int)

    return games


# ---------------------------------------------------------------------------
# Combined feature builder
# ---------------------------------------------------------------------------

# Feature lists for model input (team-level, mirrored)
TEAM_FEATURES = [
    "sss_cum", "sss_r10",
    "ppg_cum", "ppg_r5", "goal_diff_cum", "streak",
    "gf_pg_cum", "gf_pg_r5",   # goals scored per game (attack strength)
    "ga_pg_cum", "ga_pg_r5",   # goals conceded per game (defensive weakness)
    "days_rest", "match_density_14d",
]

MATCH_FEATURES = [
    "overround", "matchday", "is_big3",
]


def build_all_features(games: pd.DataFrame) -> pd.DataFrame:
    """Build all features: SSS + form + congestion + context.

    Returns games with all feature columns added.
    """
    logger.info("Building all features...")

    # SSS (existing)
    games = build_sss_features(games)

    # Form + congestion
    games = build_form_congestion_features(games)

    # Context
    games = build_context_features(games)

    # Coverage report
    feature_cols = (
        [f"{f}_home" for f in TEAM_FEATURES]
        + [f"{f}_away" for f in TEAM_FEATURES]
        + ["overround", "matchday"]
    )
    available = [c for c in feature_cols if c in games.columns]
    coverage = {c: f"{games[c].notna().mean():.0%}" for c in available}
    logger.info(f"Feature coverage: {coverage}")

    return games


def build_team_level_dataset(games: pd.DataFrame) -> pd.DataFrame:
    """Convert match-level features to team-level (2 rows per match).

    For model training: each row = one team's features + goals_scored target.
    Own features + opponent features + match context.

    Returns DataFrame with columns:
      team, opponent, date, season, is_home, goals_scored (target),
      own_sss_cum, own_sss_r10, own_ppg_cum, ...,
      opp_sss_cum, opp_sss_r10, opp_ppg_cum, ...,
      overround, matchday, is_big3
    """
    rows = []
    for _, g in games.iterrows():
        # Home team row
        home_row = {
            "date": g["date"], "season": g["season"],
            "team": g["home_team"], "opponent": g["away_team"],
            "is_home": 1,
            "goals_scored": g["home_goals"],
        }
        for feat in TEAM_FEATURES:
            home_row[f"own_{feat}"] = g.get(f"{feat}_home")
            home_row[f"opp_{feat}"] = g.get(f"{feat}_away")
        home_row["overround"] = g.get("overround")
        home_row["matchday"] = g.get("matchday")
        home_row["is_big3"] = g.get("is_big3_home", 0)
        home_row["opp_is_big3"] = g.get("is_big3_away", 0)
        # Result points for weighting (3=win, 1=draw, 0=loss)
        r = g.get("result")
        home_row["result_points"] = 3 if r == "H" else (1 if r == "D" else 0)
        # Line movement (from team perspective)
        home_row["line_move_own"] = g.get("line_move_home")
        home_row["line_move_opp"] = g.get("line_move_away")
        rows.append(home_row)

        # Away team row (mirrored)
        away_row = {
            "date": g["date"], "season": g["season"],
            "team": g["away_team"], "opponent": g["home_team"],
            "is_home": 0,
            "goals_scored": g["away_goals"],
        }
        for feat in TEAM_FEATURES:
            away_row[f"own_{feat}"] = g.get(f"{feat}_away")
            away_row[f"opp_{feat}"] = g.get(f"{feat}_home")
        away_row["overround"] = g.get("overround")
        away_row["matchday"] = g.get("matchday")
        away_row["is_big3"] = g.get("is_big3_away", 0)
        away_row["opp_is_big3"] = g.get("is_big3_home", 0)
        # Result points for weighting
        away_row["result_points"] = 3 if r == "A" else (1 if r == "D" else 0)
        # Line movement (mirrored perspective)
        away_row["line_move_own"] = g.get("line_move_away")
        away_row["line_move_opp"] = g.get("line_move_home")
        rows.append(away_row)

    return pd.DataFrame(rows)


# Feature columns for model training
MODEL_FEATURES = (
    [f"own_{f}" for f in TEAM_FEATURES]
    + [f"opp_{f}" for f in TEAM_FEATURES]
    + ["is_home", "overround", "matchday", "is_big3", "opp_is_big3"]
)


# ---------------------------------------------------------------------------
# Diagnostic utilities
# ---------------------------------------------------------------------------

def sss_coverage_report(games: pd.DataFrame) -> pd.DataFrame:
    """Report SSS coverage by season."""
    rows = []
    for season, grp in games.groupby("season"):
        n = len(grp)
        cum_ok = grp["sss_cum_home"].notna().sum() if "sss_cum_home" in grp.columns else 0
        r10_ok = grp["sss_r10_home"].notna().sum() if "sss_r10_home" in grp.columns else 0
        rows.append({
            "season": season,
            "matches": n,
            "sss_cum_coverage": f"{cum_ok}/{n} ({100*cum_ok/n:.0f}%)" if n > 0 else "N/A",
            "sss_r10_coverage": f"{r10_ok}/{n} ({100*r10_ok/n:.0f}%)" if n > 0 else "N/A",
        })
    return pd.DataFrame(rows)
