"""Team batting data (wRC+, OBP) computed from Retrosheet boxscore CSVs.

Computes wRC+ from wOBA using standard Sabermetric formulas.
Anti-leakage: each game in season Y uses team batting from season Y-1.

Output: data/processed/fangraphs/team_batting_season.parquet

Note: Originally used pybaseball to pull from FanGraphs, but the FanGraphs
legacy API now returns 403 (Cloudflare protection). Retrosheet teamstats
provide all necessary batting components (PA, AB, H, 2B, 3B, HR, BB, HBP, SF,
IBB) to compute OBP and wRC+ directly.
"""

from __future__ import annotations

import logging
import os
import zipfile
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "data" / "processed" / "fangraphs"

# Retrosheet zips directory — resolve via environment or relative to this file
_RETRO_ENV = os.environ.get("RETROSHEET_DIR")
RETROSHEET_DIR = Path(_RETRO_ENV) if _RETRO_ENV else Path(__file__).parent.parent / "retrosheets"

# Seasons to pull: 2009 (prior for 2010) through 2021
PULL_SEASONS = list(range(2009, 2022))

# Era-average wOBA linear weights (2009-2021).
# Since wRC+ is relative to league average, small year-to-year weight
# variations introduce at most ~1-2 points of error at team level.
WOBA_WEIGHTS = {
    "bb": 0.690,
    "hbp": 0.720,
    "single": 0.880,
    "double": 1.240,
    "triple": 1.560,
    "hr": 2.010,
}
WOBA_SCALE = 1.157  # Average wOBA scale factor (2009-2021 era)


# Retrosheet team codes are already in our format — no mapping needed
# (unlike FanGraphs which uses NYY, LAD, etc.)
# Only exception: Marlins franchise rename
def _normalize_retro_team(team: str, season: int) -> str:
    """Normalize Retrosheet team code for franchise changes."""
    t = team.strip().upper()
    # Marlins: FLO before 2012, MIA from 2012
    if t in {"FLA", "FLO", "MIA"}:
        return "FLO" if season <= 2011 else "MIA"
    return t


def _load_season_teamstats(season: int) -> pd.DataFrame:
    """Load team batting stats from Retrosheet zip for one season."""
    zip_path = RETROSHEET_DIR / f"{season}csvs.zip"
    if not zip_path.exists():
        raise FileNotFoundError(f"Retrosheet zip not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as zf:
        csv_name = f"{season}teamstats.csv"
        if csv_name not in zf.namelist():
            raise FileNotFoundError(f"{csv_name} not found in {zip_path}")
        with zf.open(csv_name) as f:
            df = pd.read_csv(f)

    # Filter to regular season only
    df = df[df["gametype"] == "regular"].copy()
    return df


def _compute_team_batting_season(season: int) -> pd.DataFrame:
    """Compute team-level wRC+ and OBP for one season from Retrosheet data.

    Uses the standard wOBA -> wRC+ formula:
      wOBA = (w_BB*uBB + w_HBP*HBP + w_1B*1B + w_2B*2B + w_3B*3B + w_HR*HR)
             / (AB + BB - IBB + SF + HBP)
      wRC+ = ((wOBA - lgwOBA) / wOBAscale + lgR/PA) / (lgR/PA) * 100
    """
    raw = _load_season_teamstats(season)

    # Aggregate game-level stats to team-season totals
    teams = raw.groupby("team").agg(
        pa=("b_pa", "sum"),
        ab=("b_ab", "sum"),
        r=("b_r", "sum"),
        h=("b_h", "sum"),
        d=("b_d", "sum"),
        t=("b_t", "sum"),
        hr=("b_hr", "sum"),
        bb=("b_w", "sum"),
        hbp=("b_hbp", "sum"),
        sf=("b_sf", "sum"),
        ibb=("b_iw", "sum"),
    ).reset_index()

    # Derived batting components
    teams["singles"] = teams["h"] - teams["d"] - teams["t"] - teams["hr"]
    teams["ubb"] = teams["bb"] - teams["ibb"]

    # OBP = (H + BB + HBP) / (AB + BB + HBP + SF)
    denom_obp = teams["ab"] + teams["bb"] + teams["hbp"] + teams["sf"]
    teams["obp"] = (teams["h"] + teams["bb"] + teams["hbp"]) / denom_obp

    # wOBA
    w = WOBA_WEIGHTS
    denom_woba = teams["ab"] + teams["bb"] - teams["ibb"] + teams["sf"] + teams["hbp"]
    teams["woba"] = (
        w["bb"] * teams["ubb"]
        + w["hbp"] * teams["hbp"]
        + w["single"] * teams["singles"]
        + w["double"] * teams["d"]
        + w["triple"] * teams["t"]
        + w["hr"] * teams["hr"]
    ) / denom_woba

    # League averages (across all teams in this season)
    lg_woba = teams["woba"].mean()
    lg_r = teams["r"].sum()
    lg_pa = teams["pa"].sum()
    lg_rpa = lg_r / lg_pa

    # wRC+ = ((wOBA - lgwOBA) / wOBAscale + lgR/PA) / (lgR/PA) * 100
    teams["wrc_plus"] = (
        ((teams["woba"] - lg_woba) / WOBA_SCALE + lg_rpa) / lg_rpa * 100
    )

    # Build output rows with normalized team codes
    results = []
    for _, row in teams.iterrows():
        team_code = _normalize_retro_team(str(row["team"]), season)
        results.append(
            {
                "team": team_code,
                "season": season,
                "wrc_plus": round(row["wrc_plus"], 1),
                "obp": round(row["obp"], 4),
                "pa_total": int(row["pa"]),
            }
        )

    return pd.DataFrame(results)


def build_team_batting_all_seasons(
    seasons: list[int] | None = None,
    *,
    cache_dir: Path | None = None,
    delay_seconds: float = 2.0,
) -> pd.DataFrame:
    """Compute team batting for all seasons from Retrosheet data.

    Returns DataFrame with columns: team, season, wrc_plus, obp, pa_total
    """
    seasons = seasons or PULL_SEASONS
    all_seasons = []

    for season in seasons:
        logger.info(f"  Computing team batting for {season} from Retrosheet...")
        team_df = _compute_team_batting_season(season)
        all_seasons.append(team_df)

    result = pd.concat(all_seasons, ignore_index=True)
    logger.info(
        f"Team batting: {len(result)} rows, "
        f"seasons {result['season'].min()}-{result['season'].max()}, "
        f"teams per season: {result.groupby('season')['team'].nunique().median():.0f}"
    )
    return result


def validate_team_batting(df: pd.DataFrame) -> dict[str, object]:
    """Run sanity checks on aggregated team batting data."""
    issues = {}
    issues["total_rows"] = len(df)
    issues["seasons"] = sorted(df["season"].unique().tolist())
    issues["teams_per_season"] = df.groupby("season")["team"].nunique().to_dict()

    # wRC+ should center around 100
    wrc_mean = df["wrc_plus"].mean()
    issues["wrc_plus_mean"] = round(wrc_mean, 1)
    issues["wrc_plus_range"] = [round(df["wrc_plus"].min(), 1), round(df["wrc_plus"].max(), 1)]

    # OBP should be in reasonable range
    issues["obp_range"] = [round(df["obp"].min(), 4), round(df["obp"].max(), 4)]

    return issues


def save_team_batting(
    df: pd.DataFrame,
    *,
    output_dir: Path | None = None,
) -> Path:
    """Save aggregated team batting to parquet."""
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "team_batting_season.parquet"
    df.to_parquet(out_path, index=False)
    logger.info(f"Saved team batting to {out_path}")
    return out_path
