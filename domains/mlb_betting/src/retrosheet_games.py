"""Retrosheet gamelogs (GL) → game-level master table.

We use Retrosheet gamelog files (glYYYY.txt) because they contain:
- date, home/away teams, game number (doubleheaders)
- final score (home/away runs)
- linescore strings by inning (visitor/home)

This allows building an inning-level game dataset WITHOUT play-by-play.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RETROSHEETS_DIR = Path(__file__).parent.parent / "retrosheets"


@dataclass(frozen=True)
class GamelogSources:
    """Where to read Retrosheet gamelog files from."""

    gl2010_19_zip: Path = RETROSHEETS_DIR / "gl2010_19.zip"
    gl2020_25_zip: Path = RETROSHEETS_DIR / "gl2020_25.zip"


def _parse_linescore_to_innings(linescore: str, innings: int = 9) -> tuple[list[int], int]:
    """Parse Retrosheet linescore string into inning runs.

    Retrosheet linescore examples:
    - visitor: "020300200"
    - home:    "01001331x"   (x = did not bat; treat as 0)
    - extra innings may add more digits after the 9th.

    Returns:
        (first_n_innings_runs, total_runs_from_linescore_digits)
    """
    if not isinstance(linescore, str):
        return [0] * innings, 0

    # Keep only inning symbols; treat non-digits (e.g. 'x') as 0 for inning vector,
    # but they do not contribute to digit-based totals.
    chars = list(linescore.strip().strip('"'))

    inning_runs: list[int] = []
    digit_total = 0
    for c in chars:
        if c.isdigit():
            v = int(c)
            digit_total += v
            if len(inning_runs) < innings:
                inning_runs.append(v)
        else:
            if len(inning_runs) < innings:
                inning_runs.append(0)

    # Pad if shorter than requested innings.
    if len(inning_runs) < innings:
        inning_runs.extend([0] * (innings - len(inning_runs)))

    return inning_runs[:innings], digit_total


def _iter_gl_rows_from_zip(zip_path: Path, member: str) -> list[list[str]]:
    with ZipFile(zip_path) as z, z.open(member) as f:
        reader = csv.reader(TextIOWrapper(f, encoding="utf-8", errors="replace"))
        return list(reader)


def load_retrosheet_gamelogs(
    seasons: list[int],
    *,
    sources: GamelogSources = GamelogSources(),
) -> pd.DataFrame:
    """Load Retrosheet gamelog rows for selected seasons into a compact DataFrame.

    Uses the downloaded zip archives:
    - gl2010_19.zip (gl2010.txt..gl2019.txt)
    - gl2020_25.zip (gl2020.txt..gl2025.txt)
    """
    parts: list[pd.DataFrame] = []

    for season in seasons:
        if 2010 <= season <= 2019:
            zip_path = sources.gl2010_19_zip
        else:
            zip_path = sources.gl2020_25_zip

        member = f"gl{season}.txt"
        if not zip_path.exists():
            raise FileNotFoundError(f"Missing gamelog zip: {zip_path}")

        rows = _iter_gl_rows_from_zip(zip_path, member)
        if not rows:
            logger.warning(f"Empty gamelog file: {member} in {zip_path}")
            continue

        # GL fields are 161-wide. We only need specific positions (1-based -> 0-based):
        #  1 date (YYYYMMDD) -> idx 0
        #  2 game_num (0/1/2) -> idx 1
        #  4 away_team -> idx 3
        #  7 home_team -> idx 6
        # 10 away_runs -> idx 9
        # 11 home_runs -> idx 10
        # 20 away_linescore -> idx 19
        # 21 home_linescore -> idx 20
        data = []
        for r in rows:
            if len(r) < 21:
                continue
            date_raw = r[0].strip().strip('"')
            game_num = r[1].strip().strip('"')
            away_team = r[3].strip().strip('"')
            home_team = r[6].strip().strip('"')
            away_runs = r[9].strip().strip('"')
            home_runs = r[10].strip().strip('"')
            away_ls = r[19].strip().strip('"')
            home_ls = r[20].strip().strip('"')
            data.append(
                {
                    "season": season,
                    "date_raw": date_raw,
                    "game_num": int(game_num) if game_num.isdigit() else 0,
                    "away_team": away_team,
                    "home_team": home_team,
                    "away_final": pd.to_numeric(away_runs, errors="coerce"),
                    "home_final": pd.to_numeric(home_runs, errors="coerce"),
                    "away_linescore": away_ls,
                    "home_linescore": home_ls,
                }
            )

        df = pd.DataFrame(data)
        if df.empty:
            continue

        df["date"] = pd.to_datetime(df["date_raw"], format="%Y%m%d", errors="coerce")
        # Retrosheet GID format: HOMEYYYYMMDDN (N = game number)
        df["gid"] = df["home_team"] + df["date_raw"] + df["game_num"].astype(str)
        df["matchup_key"] = df.apply(
            lambda x: "_".join(sorted([str(x["away_team"]), str(x["home_team"])])),
            axis=1,
        )

        # Inning runs
        away_inns, away_ls_total = zip(
            *df["away_linescore"].apply(lambda s: _parse_linescore_to_innings(s, 9))
        )
        home_inns, home_ls_total = zip(
            *df["home_linescore"].apply(lambda s: _parse_linescore_to_innings(s, 9))
        )
        away_inns = np.array(list(away_inns), dtype=int)
        home_inns = np.array(list(home_inns), dtype=int)

        for i in range(1, 10):
            df[f"away_inn_{i}"] = away_inns[:, i - 1]
            df[f"home_inn_{i}"] = home_inns[:, i - 1]

        df["away_innings_sum"] = away_inns.sum(axis=1)
        df["home_innings_sum"] = home_inns.sum(axis=1)
        df["away_linescore_total"] = np.array(list(away_ls_total), dtype=int)
        df["home_linescore_total"] = np.array(list(home_ls_total), dtype=int)
        df["home_win"] = (df["home_final"] > df["away_final"]).astype(int)
        df["total_runs"] = df["home_final"] + df["away_final"]
        df["is_extra_innings"] = (
            (df["away_linescore_total"] != df["away_final"])
            | (df["home_linescore_total"] != df["home_final"])
        )

        parts.append(df)

    if not parts:
        raise ValueError("No gamelog data loaded for requested seasons.")

    games = pd.concat(parts, ignore_index=True)
    games = games.dropna(subset=["date", "home_team", "away_team", "home_final", "away_final"]).copy()
    games["home_final"] = pd.to_numeric(games["home_final"], errors="coerce").astype(int)
    games["away_final"] = pd.to_numeric(games["away_final"], errors="coerce").astype(int)
    games = games.sort_values(["season", "date", "game_num", "home_team", "away_team"]).reset_index(
        drop=True
    )

    logger.info(f"Loaded Retrosheet gamelogs: {len(games)} games ({games['season'].nunique()} seasons)")
    return games


def drop_doubleheaders(df: pd.DataFrame) -> pd.DataFrame:
    """Drop all games that are part of a doubleheader (matchup repeats on same date)."""
    g = df.copy()
    counts = g.groupby(["date", "matchup_key"]).size().reset_index(name="n_games")
    dh = counts[counts["n_games"] > 1][["date", "matchup_key"]]
    if dh.empty:
        return g
    m = g.merge(dh, on=["date", "matchup_key"], how="left", indicator=True)
    out = m[m["_merge"] == "left_only"].drop(columns=["_merge"])
    return out.reset_index(drop=True)

