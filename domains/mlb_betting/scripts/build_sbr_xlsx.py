"""Build xlsx files for 2022-2025 from SBR odds + Retrosheet CSVs.

SBR source: ArnavSaraogi/mlb-odds-scraper (MIT license).
Retrosheet source: retrosheets/YYYYcsvs.zip → teamstats.csv (inning scores + starters).

Output: data/raw/odds/mlb-odds-{year}.xlsx matching sports-statistics.com format.

Usage:
    python scripts/build_sbr_xlsx.py
"""

import csv
import json
import logging
import sys
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SBR_JSON = ROOT / "data" / "raw" / "sbr_odds_full.json"
RETROSHEETS_DIR = ROOT / "retrosheets"
OUTPUT_DIR = ROOT / "data" / "raw" / "odds"

# SBR shortName → our pipeline team code
SBR_TO_PIPELINE = {
    "WAS": "WAS",  # Retrosheet uses WAS too (2022+)
    "TB": "TAM",
    "CHW": "CWS",
    "SD": "SDG",
    "SF": "SFO",
    "CHC": "CUB",
    "KC": "KAN",
    "AZ": "ARI",   # Rebranded 2024
    "ATH": "OAK",  # Rebranded 2024 (Sacramento Athletics)
}

# Retrosheet team code → our pipeline team code
# (for matching teamstats.csv rows to SBR data)
RS_TO_PIPELINE = {
    "NYA": "NYY", "NYN": "NYM",
    "CHA": "CWS", "CHN": "CUB",
    "ANA": "LAA", "LAN": "LAD",
    "TBA": "TAM", "KCA": "KAN",
    "SFN": "SFO", "SDN": "SDG",
    "SLN": "STL", "FLO": "MIA",
    "WAS": "WAS",
}

SPORTSBOOK_PRIORITY = ["draftkings", "fanduel", "bet365", "caesars", "betmgm", "bet_rivers_ny"]

SEASONS = [2022, 2023, 2024, 2025]


def _pick_odds(
    books: list[dict],
    line_type: str = "currentLine",
    *,
    required_keys: tuple[str, ...] = ("homeOdds",),
) -> dict | None:
    """Pick odds from the highest-priority available sportsbook."""
    book_map = {b["sportsbook"]: b for b in books}
    for name in SPORTSBOOK_PRIORITY:
        if name in book_map:
            line = book_map[name].get(line_type)
            if line and all(line.get(key) is not None for key in required_keys):
                return line
    # Fallback: any book with data
    for b in books:
        line = b.get(line_type)
        if line and all(line.get(key) is not None for key in required_keys):
            return line
    return None


def parse_sbr(data: dict, season: int) -> pd.DataFrame:
    """Parse SBR JSON for a single season into a game-level DataFrame."""
    rows = []
    for date_str, games in data.items():
        if not date_str.startswith(str(season)):
            continue

        dt = pd.Timestamp(date_str)
        # Exclude September (operator instruction)
        if dt.month >= 9:
            continue

        for game in games:
            gv = game["gameView"]

            # Only regular season
            if gv.get("gameType", "R") != "R":
                continue

            away_short = gv["awayTeam"]["shortName"]
            home_short = gv["homeTeam"]["shortName"]

            # Skip All-Star
            if away_short in ("AL", "NL") or home_short in ("AL", "NL"):
                continue

            # Map to our pipeline codes
            away = SBR_TO_PIPELINE.get(away_short, away_short)
            home = SBR_TO_PIPELINE.get(home_short, home_short)

            away_score = gv.get("awayTeamScore")
            home_score = gv.get("homeTeamScore")

            # Skip incomplete games
            status = gv.get("gameStatusText", "")
            if "Postponed" in status or "Cancelled" in status or "Suspended" in status:
                continue
            if away_score is None or home_score is None:
                continue

            # --- Moneyline ---
            ml_books = game.get("odds", {}).get("moneyline", [])
            close_ml = _pick_odds(ml_books, "currentLine")
            open_ml = _pick_odds(ml_books, "openingLine")

            home_close_ml = close_ml["homeOdds"] if close_ml else np.nan
            away_close_ml = close_ml["awayOdds"] if close_ml else np.nan
            home_open_ml = open_ml["homeOdds"] if open_ml else np.nan
            away_open_ml = open_ml["awayOdds"] if open_ml else np.nan

            # --- Point spread (run line) ---
            ps_books = game.get("odds", {}).get("pointspread", [])
            close_ps = _pick_odds(ps_books, "currentLine")

            if close_ps:
                home_rl = close_ps.get("homeSpread", np.nan)
                home_rl_odds = close_ps.get("homeOdds", np.nan)
                away_rl = close_ps.get("awaySpread", np.nan)
                away_rl_odds = close_ps.get("awayOdds", np.nan)
            else:
                home_rl = away_rl = home_rl_odds = away_rl_odds = np.nan

            # --- Totals (O/U) ---
            total_books = (
                game.get("odds", {}).get("totals")
                or game.get("odds", {}).get("total")
                or []
            )
            close_ou_line = _pick_odds(
                total_books,
                "currentLine",
                required_keys=("total",),
            )
            open_ou_line = _pick_odds(
                total_books,
                "openingLine",
                required_keys=("total",),
            )

            close_ou = close_ou_line.get("total", np.nan) if close_ou_line else np.nan
            open_ou = open_ou_line.get("total", np.nan) if open_ou_line else np.nan
            close_ou_under_odds = (
                close_ou_line.get("underOdds", np.nan) if close_ou_line else np.nan
            )
            open_ou_under_odds = (
                open_ou_line.get("underOdds", np.nan) if open_ou_line else np.nan
            )
            close_ou_over_odds = (
                close_ou_line.get("overOdds", np.nan) if close_ou_line else np.nan
            )
            open_ou_over_odds = (
                open_ou_line.get("overOdds", np.nan) if open_ou_line else np.nan
            )

            rows.append({
                "date": dt,
                "month": dt.month,
                "day": dt.day,
                "away_team": away,
                "home_team": home,
                "away_score": int(away_score),
                "home_score": int(home_score),
                "home_close_ml": home_close_ml,
                "away_close_ml": away_close_ml,
                "home_open_ml": home_open_ml,
                "away_open_ml": away_open_ml,
                "home_rl": home_rl,
                "home_rl_odds": home_rl_odds,
                "away_rl": away_rl,
                "away_rl_odds": away_rl_odds,
                "open_ou": open_ou,
                "close_ou": close_ou,
                "open_ou_under_odds": open_ou_under_odds,
                "close_ou_under_odds": close_ou_under_odds,
                "open_ou_over_odds": open_ou_over_odds,
                "close_ou_over_odds": close_ou_over_odds,
                "venue": gv.get("venueName", ""),
                "status": status,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values(["date", "home_team"]).reset_index(drop=True)
    logger.info(f"  SBR {season}: {len(df)} games (Apr-Aug, regular season)")
    return df


def load_retrosheet_teamstats(season: int) -> pd.DataFrame:
    """Load inning scores + starter IDs from Retrosheet teamstats.csv."""
    zip_path = RETROSHEETS_DIR / f"{season}csvs.zip"
    if not zip_path.exists():
        logger.warning(f"  Retrosheet zip missing: {zip_path}")
        return pd.DataFrame()

    member = f"{season}teamstats.csv"
    with ZipFile(zip_path) as z:
        if member not in z.namelist():
            logger.warning(f"  {member} not in {zip_path}")
            return pd.DataFrame()
        with z.open(member) as f:
            reader = csv.DictReader(TextIOWrapper(f, encoding="utf-8", errors="replace"))
            rows = list(reader)

    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        # Only regular season
        if r.get("gametype", "regular") != "regular":
            continue

        team_rs = r["team"]
        team = RS_TO_PIPELINE.get(team_rs, team_rs)

        # Parse date
        date_raw = r.get("date", "")
        try:
            dt = pd.Timestamp(date_raw[:4] + "-" + date_raw[4:6] + "-" + date_raw[6:8])
        except (ValueError, IndexError):
            continue

        # Skip September
        if dt.month >= 9:
            continue

        # Inning scores
        inns = []
        for i in range(1, 10):
            v = r.get(f"inn{i}", "0")
            inns.append(int(v) if v and v.strip().isdigit() else 0)

        # Final score
        final = int(r.get("b_r", 0))

        # Starting pitcher (position 1 = pitcher)
        pitcher_id = r.get("start_f1", "")

        # Home/visitor
        vh = r.get("vishome", "").lower()

        records.append({
            "gid": r["gid"],
            "date": dt,
            "team": team,
            "vh": "H" if vh == "h" else "V",
            "final": final,
            "pitcher": pitcher_id,
            **{f"inn_{i}": inns[i - 1] for i in range(1, 10)},
            "game_num": int(r.get("number", 0)),
        })

    df = pd.DataFrame(records)
    logger.info(f"  Retrosheet {season}: {len(df)} team-game rows ({len(df)//2} games)")
    return df


def merge_and_format(sbr: pd.DataFrame, rs: pd.DataFrame, season: int) -> pd.DataFrame:
    """Merge SBR odds + Retrosheet innings → xlsx-format rows (2 per game: V then H)."""
    if rs.empty:
        logger.warning(f"  No Retrosheet data for {season}, using SBR scores with zero innings")
        return _format_from_sbr_only(sbr, season)

    # Pivot Retrosheet: one row per side
    rs_away = rs[rs["vh"] == "V"].copy()
    rs_home = rs[rs["vh"] == "H"].copy()

    # Map Retrosheet teams for merge
    rs_away = rs_away.rename(columns={"team": "away_team_rs"})
    rs_home = rs_home.rename(columns={"team": "home_team_rs"})

    # Get home team from gid for matching
    rs_home["gid_date"] = rs_home["date"]
    rs_away["gid_date"] = rs_away["date"]

    # Build game-level Retrosheet
    # Use gid to pair home/away
    rs_game = rs_home.merge(
        rs_away[["gid", "away_team_rs", "pitcher", "final"] +
                [f"inn_{i}" for i in range(1, 10)]],
        on="gid",
        suffixes=("_home", "_away"),
        how="inner",
    )

    # Match with SBR by (date, home_team, away_team)
    rs_game["home_team_match"] = rs_game["home_team_rs"]
    rs_game["away_team_match"] = rs_game["away_team_rs"]

    merged = sbr.merge(
        rs_game,
        left_on=["date", "home_team", "away_team"],
        right_on=["date", "home_team_match", "away_team_match"],
        how="left",
    )

    matched = merged["gid"].notna().sum()
    total = len(merged)
    logger.info(f"  Merge {season}: {matched}/{total} matched ({matched/total*100:.1f}%)")

    # For unmatched games, zero out innings
    for side in ["home", "away"]:
        for i in range(1, 10):
            col = f"inn_{i}_{side}"
            if col in merged.columns:
                merged[col] = merged[col].fillna(0).astype(int)

    # Build xlsx rows (visitor then home for each game)
    xlsx_rows = []
    rot = 900  # starting rotation number

    for _, g in merged.iterrows():
        date_mmdd = g["month"] * 100 + g["day"]

        # Visitor row
        v_row = {
            "date": date_mmdd,
            "rot": rot,
            "vh": "V",
            "team": g["away_team"],
            "pitcher": g.get("pitcher_away", "UNKNOWN-R"),
        }
        for i in range(1, 10):
            v_row[f"inn_{i}"] = int(g.get(f"inn_{i}_away", 0))
        v_row["final"] = g["away_score"]
        v_row["open_ml"] = g["away_open_ml"]
        v_row["close_ml"] = g["away_close_ml"]
        v_row["run_line"] = g["away_rl"]
        v_row["run_line_odds"] = g["away_rl_odds"]
        v_row["open_ou"] = g["open_ou"]
        v_row["open_ou_odds"] = g.get("open_ou_under_odds", np.nan)
        v_row["close_ou"] = g["close_ou"]
        v_row["close_ou_odds"] = g.get("close_ou_under_odds", np.nan)
        xlsx_rows.append(v_row)

        # Home row
        h_row = {
            "date": date_mmdd,
            "rot": rot + 1,
            "vh": "H",
            "team": g["home_team"],
            "pitcher": g.get("pitcher_home", "UNKNOWN-R"),
        }
        for i in range(1, 10):
            h_row[f"inn_{i}"] = int(g.get(f"inn_{i}_home", 0))
        h_row["final"] = g["home_score"]
        h_row["open_ml"] = g["home_open_ml"]
        h_row["close_ml"] = g["home_close_ml"]
        h_row["run_line"] = g["home_rl"]
        h_row["run_line_odds"] = g["home_rl_odds"]
        h_row["open_ou"] = g["open_ou"]
        h_row["open_ou_odds"] = g.get("open_ou_over_odds", np.nan)
        h_row["close_ou"] = g["close_ou"]
        h_row["close_ou_odds"] = g.get("close_ou_over_odds", np.nan)
        xlsx_rows.append(h_row)

        rot += 2

    result = pd.DataFrame(xlsx_rows)
    return result


def _format_from_sbr_only(sbr: pd.DataFrame, season: int) -> pd.DataFrame:
    """Fallback: format from SBR data only (no inning scores)."""
    xlsx_rows = []
    rot = 900
    for _, g in sbr.iterrows():
        date_mmdd = g["month"] * 100 + g["day"]
        for vh, team, score, ml_c, ml_o, rl, rl_odds in [
            ("V", g["away_team"], g["away_score"],
             g["away_close_ml"], g["away_open_ml"], g["away_rl"], g["away_rl_odds"]),
            ("H", g["home_team"], g["home_score"],
             g["home_close_ml"], g["home_open_ml"], g["home_rl"], g["home_rl_odds"]),
        ]:
            row = {
                "date": date_mmdd,
                "rot": rot,
                "vh": vh,
                "team": team,
                "pitcher": "UNKNOWN-R",
            }
            for i in range(1, 10):
                row[f"inn_{i}"] = 0
            row["final"] = score
            row["open_ml"] = ml_o
            row["close_ml"] = ml_c
            row["run_line"] = rl
            row["run_line_odds"] = rl_odds
            row["open_ou"] = g["open_ou"]
            row["open_ou_odds"] = (
                g.get("open_ou_under_odds", np.nan)
                if vh == "V"
                else g.get("open_ou_over_odds", np.nan)
            )
            row["close_ou"] = g["close_ou"]
            row["close_ou_odds"] = (
                g.get("close_ou_under_odds", np.nan)
                if vh == "V"
                else g.get("close_ou_over_odds", np.nan)
            )
            xlsx_rows.append(row)
            rot += 1

    return pd.DataFrame(xlsx_rows)


def main() -> None:
    logger.info("Loading SBR odds dataset...")
    with open(SBR_JSON) as f:
        sbr_data = json.load(f)
    logger.info(f"  {len(sbr_data)} dates in SBR dataset")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for season in SEASONS:
        logger.info(f"\n=== Season {season} ===")

        sbr = parse_sbr(sbr_data, season)
        if sbr.empty:
            logger.warning(f"  No SBR data for {season}, skipping")
            continue

        rs = load_retrosheet_teamstats(season)
        xlsx = merge_and_format(sbr, rs, season)

        outpath = OUTPUT_DIR / f"mlb-odds-{season}.xlsx"
        xlsx.to_excel(outpath, index=False)
        n_games = len(xlsx) // 2
        logger.info(f"  Wrote {outpath.name}: {n_games} games, {len(xlsx)} rows")

    # Summary
    logger.info("\n=== Summary ===")
    for season in SEASONS:
        p = OUTPUT_DIR / f"mlb-odds-{season}.xlsx"
        if p.exists():
            df = pd.read_excel(p)
            logger.info(f"  {season}: {len(df)//2} games")
        else:
            logger.info(f"  {season}: MISSING")


if __name__ == "__main__":
    main()
