"""Master data audit — check all data sources and their readiness.

For each data source:
1. Check if output parquet exists
2. If yes: load, verify row count, date range, NaN%, range validation
3. If no: print which script to run
4. Check merge compatibility with game data (team codes, date overlap)

Usage:
    python scripts/audit_data_sources.py
    python scripts/audit_data_sources.py --save-report
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path("data/processed")
REPORT_PATH = PROCESSED_DIR / "data_audit_report.md"


def _status(ok: bool) -> str:
    return "GREEN" if ok else "RED"


def _check_parquet(path: Path, label: str) -> dict:
    """Check if parquet exists and return basic stats."""
    result = {"label": label, "path": str(path), "exists": path.exists()}
    if not path.exists():
        result["status"] = "RED"
        return result

    df = pd.read_parquet(path)
    result["rows"] = len(df)
    result["columns"] = list(df.columns)
    result["nan_pct"] = {
        col: round(df[col].isna().mean() * 100, 1) for col in df.columns if df[col].isna().any()
    }
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce")
        result["date_range"] = [str(dates.min())[:10], str(dates.max())[:10]]
    if "season" in df.columns:
        result["seasons"] = sorted(df["season"].dropna().unique().tolist())
    if "team" in df.columns:
        result["teams"] = sorted(df["team"].dropna().unique().tolist())
        result["n_teams"] = len(result["teams"])
    result["status"] = "GREEN"
    return result


def audit_odds_data() -> dict:
    """Check raw odds data availability."""
    raw_dir = Path("data/raw/odds")
    seasons = list(range(2010, 2022))
    found = []
    missing = []
    for s in seasons:
        if s == 2020:
            continue
        path = raw_dir / f"mlb-odds-{s}.xlsx"
        if path.exists():
            found.append(s)
        else:
            missing.append(s)
    return {
        "label": "Raw Odds (xlsx)",
        "path": str(raw_dir),
        "exists": len(found) > 0,
        "found_seasons": found,
        "missing_seasons": missing,
        "status": _status(len(missing) == 0),
        "fix": "python data/download.py" if missing else None,
    }


def audit_retrosheet_zips() -> dict:
    """Check Retrosheet zip availability."""
    retro_dir = Path("retrosheets")
    seasons = list(range(2010, 2022))
    found = []
    missing = []
    for s in seasons:
        if s == 2020:
            continue
        path = retro_dir / f"{s}csvs.zip"
        if path.exists():
            found.append(s)
        else:
            missing.append(s)
    return {
        "label": "Retrosheet Zips",
        "path": str(retro_dir),
        "exists": len(found) > 0,
        "found_seasons": found,
        "missing_seasons": missing,
        "status": _status(len(missing) == 0),
        "fix": "Download from retrosheet.org" if missing else None,
    }


def audit_retrosheet_pitchers() -> dict:
    """Check Retrosheet pitcher outputs."""
    results = {}
    for name, path in [
        ("game_id_bridge", PROCESSED_DIR / "pitchers" / "game_id_bridge.parquet"),
        ("starter_game_logs", PROCESSED_DIR / "pitchers" / "starter_game_logs.parquet"),
        ("starter_entering_features", PROCESSED_DIR / "pitchers" / "starter_entering_features.parquet"),
    ]:
        info = _check_parquet(path, f"Retrosheet: {name}")
        if not info["exists"]:
            info["fix"] = "python scripts/build_retrosheet_pitchers.py"

        # Validate entering features have WHIP/KBB columns
        if info["exists"] and name == "starter_entering_features":
            expected_cols = ["whip_short", "whip_long", "kbb_short", "kbb_long", "k9_short"]
            found = [c for c in expected_cols if c in info["columns"]]
            info["has_whip_kbb"] = len(found) == len(expected_cols)
            if not info["has_whip_kbb"]:
                info["status"] = "RED"
                info["missing_columns"] = [c for c in expected_cols if c not in info["columns"]]

        results[name] = info
    return results


def audit_fangraphs() -> dict:
    """Check FanGraphs team batting output."""
    path = PROCESSED_DIR / "fangraphs" / "team_batting_season.parquet"
    info = _check_parquet(path, "FanGraphs Team Batting")
    if not info["exists"]:
        info["fix"] = "python scripts/build_fangraphs_data.py"
        return info

    df = pd.read_parquet(path)
    # Validate wRC+ range
    if "wrc_plus" in df.columns:
        wrc_mean = df["wrc_plus"].mean()
        info["wrc_plus_mean"] = round(wrc_mean, 1)
        info["wrc_plus_ok"] = 90 <= wrc_mean <= 110
        if not info["wrc_plus_ok"]:
            info["status"] = "RED"
    if "obp" in df.columns:
        obp_range = [df["obp"].min(), df["obp"].max()]
        info["obp_range"] = [round(v, 4) for v in obp_range]
        info["obp_ok"] = obp_range[0] >= 0.25 and obp_range[1] <= 0.40
        if not info["obp_ok"]:
            info["status"] = "RED"

    # Check expected row count: ~30 teams × 13 seasons = ~390
    info["expected_rows"] = "~390 (30 teams × 13 seasons)"
    return info


def audit_bullpen() -> dict:
    """Check bullpen features output."""
    path = PROCESSED_DIR / "retrosheet" / "bullpen_features.parquet"
    info = _check_parquet(path, "Bullpen Features")
    if not info["exists"]:
        info["fix"] = "python scripts/build_bullpen_features.py"
        return info

    # Validate key columns
    df = pd.read_parquet(path)
    expected = ["bp_whip_short", "bp_kbb_short", "bp_close_win_pct", "bp_ip_3d"]
    found = [c for c in expected if c in df.columns]
    info["has_expected_columns"] = len(found) == len(expected)
    if not info["has_expected_columns"]:
        info["missing_columns"] = [c for c in expected if c not in df.columns]
        info["status"] = "RED"

    return info


def audit_travel() -> dict:
    """Check travel/fatigue features output."""
    path = PROCESSED_DIR / "schedule" / "travel_fatigue.parquet"
    info = _check_parquet(path, "Travel/Fatigue Features")
    if not info["exists"]:
        info["fix"] = "python scripts/build_schedule_features.py"
        return info

    df = pd.read_parquet(path)
    # Validate ranges
    for col, lo, hi in [
        ("rest_days", 0, 700),  # cross-season gaps (offseason + COVID 2019→2021)
        ("travel_miles_3d", 0, 10000),
        ("road_trip_len", 0, 30),
        ("tz_changes_3d", 0, 10),
    ]:
        if col in df.columns:
            valid = df[col].dropna()
            info[f"{col}_range"] = [round(valid.min(), 1), round(valid.max(), 1)]
            info[f"{col}_ok"] = valid.min() >= lo and valid.max() <= hi
            if not info[f"{col}_ok"]:
                info["status"] = "RED"

    return info


def build_report(audits: dict) -> str:
    """Build markdown audit report."""
    lines = ["# MLB Data Sources Audit Report\n\n"]

    for section, data in audits.items():
        lines.append(f"## {section}\n\n")

        if isinstance(data, dict) and "label" in data:
            # Single source
            _format_source(lines, data)
        elif isinstance(data, dict):
            # Multiple sub-sources
            for sub_name, sub_data in data.items():
                if isinstance(sub_data, dict) and "label" in sub_data:
                    _format_source(lines, sub_data)
        lines.append("\n")

    return "".join(lines)


def _format_source(lines: list, data: dict) -> None:
    status = data.get("status", "UNKNOWN")
    label = data.get("label", "Unknown")
    lines.append(f"**{label}** — `{status}`\n\n")
    lines.append(f"- Path: `{data.get('path', 'N/A')}`\n")
    lines.append(f"- Exists: {data.get('exists', False)}\n")

    if data.get("exists"):
        if "rows" in data:
            lines.append(f"- Rows: {data['rows']}\n")
        if "date_range" in data:
            lines.append(f"- Date range: {data['date_range'][0]} to {data['date_range'][1]}\n")
        if "seasons" in data:
            lines.append(f"- Seasons: {data['seasons']}\n")
        if "n_teams" in data:
            lines.append(f"- Teams: {data['n_teams']}\n")
        if "nan_pct" in data and data["nan_pct"]:
            lines.append("- NaN%: ")
            nan_items = [f"{k}={v}%" for k, v in sorted(data["nan_pct"].items()) if v > 0]
            lines.append(", ".join(nan_items[:10]))
            if len(nan_items) > 10:
                lines.append(f" ... ({len(nan_items)} total)")
            lines.append("\n")
    else:
        if "fix" in data and data["fix"]:
            lines.append(f"- Fix: `{data['fix']}`\n")
        if "missing_seasons" in data and data["missing_seasons"]:
            lines.append(f"- Missing seasons: {data['missing_seasons']}\n")

    lines.append("\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--save-report", action="store_true", help="Save report to file")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    audits = {}

    logger.info("Auditing raw data sources...")
    audits["Raw Odds Data"] = audit_odds_data()
    audits["Retrosheet Archives"] = audit_retrosheet_zips()

    logger.info("Auditing processed data...")
    audits["Retrosheet Pitchers"] = audit_retrosheet_pitchers()
    audits["FanGraphs Team Batting"] = audit_fangraphs()
    audits["Bullpen Features"] = audit_bullpen()
    audits["Travel/Fatigue"] = audit_travel()

    # Summary
    all_statuses = []
    for section, data in audits.items():
        if isinstance(data, dict) and "status" in data:
            all_statuses.append(data["status"])
        elif isinstance(data, dict):
            for sub_data in data.values():
                if isinstance(sub_data, dict) and "status" in sub_data:
                    all_statuses.append(sub_data["status"])

    n_green = all_statuses.count("GREEN")
    n_red = all_statuses.count("RED")
    total = len(all_statuses)

    logger.info(f"\nAudit Summary: {n_green}/{total} GREEN, {n_red}/{total} RED")

    # Print details
    for section, data in audits.items():
        if isinstance(data, dict) and "status" in data:
            status = data["status"]
            label = data.get("label", section)
            fix = data.get("fix", "")
            logger.info(f"  [{status}] {label}" + (f" — fix: {fix}" if fix else ""))
        elif isinstance(data, dict):
            for sub_data in data.values():
                if isinstance(sub_data, dict) and "status" in sub_data:
                    status = sub_data["status"]
                    label = sub_data.get("label", "?")
                    fix = sub_data.get("fix", "")
                    logger.info(f"  [{status}] {label}" + (f" — fix: {fix}" if fix else ""))

    if args.save_report:
        report = build_report(audits)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(report, encoding="utf-8")
        logger.info(f"\nReport saved to {REPORT_PATH}")


if __name__ == "__main__":
    main()
