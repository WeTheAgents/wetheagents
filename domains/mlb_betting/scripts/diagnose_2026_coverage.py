"""Diagnose 2026 live strategy coverage.

For a given target date (or the last N fully-merged days), report:
  1. Feature coverage (% non-null) for every field the 5 strategies read.
  2. Filter cascade: at which stage each strategy drops rows.
  3. Top 5 "near-miss" rows per strategy (one filter short).

Pure READ-ONLY — no file writes unless --out is passed.

Usage:
    python scripts/diagnose_2026_coverage.py --date 2026-04-14
    python scripts/diagnose_2026_coverage.py --last 3   # last 3 merged days
    python scripts/diagnose_2026_coverage.py --date 2026-04-14 --out picks/diagnose.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.WARNING,  # keep the stdout table clean
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd


# The fields every strategy reads. Covers Tier1/2/3, fav_rl, and the new
# OVER strategy.
COVERAGE_FIELDS = [
    # Tier1
    "home_is_bullpen_no_starter",
    "away_is_bullpen_no_starter",
    "fav_is_home",
    # Tier2 / Tier3
    "bp_ip_3d_home",
    "bp_ip_3d_away",
    "bp_workload_gap",
    "away_sp_fip_short",
    "home_sp_fip_short",
    "starter_depth_diff_short",
    # fav_rl
    "fav_implied_prob",
    "fav_starter_fip_diff",
    "fav_power_rate_diff",
    # OVER (new)
    "combined_rpg",
    "close_ou",
    "rpg_vs_line",
    "bullpen_fip_7g_combined",
    "bp_fip_7g_home",
    "bp_fip_7g_away",
    "sp_fip_floor_short",
    "effective_obp_home",
    "effective_obp_away",
    "insufficient_starter_history",
    "starter_feature_source_missing",
    "insufficient_lineup_history",
    "lineup_feature_source_missing",
]


def build_enriched(target: date) -> pd.DataFrame:
    """Same pipeline as generate_picks_2026.py, restricted to recent seasons."""
    from src.data_loader import (
        add_derived_odds,
        apply_data_filters,
        load_all_seasons,
    )
    from src.features import build_all_features
    from src.strategies import add_derived_for_strategies

    games = load_all_seasons()
    should_overlay = target >= date.today()
    if not should_overlay and len(games):
        should_overlay = not (games["date"].dt.date == target).any()

    # Inject pregame overlay for today/future so the diagnostic sees the
    # same frame as the live picks generator. Also do this for fixture dates
    # that have no completed rows in the historical frame but still have a
    # saved pregame snapshot.
    if should_overlay:
        try:
            from src.live_pregame import load_pregame_overlay
            overlay = load_pregame_overlay(target)
            if not overlay.empty:
                mask = games["date"].dt.date == target if len(games) else None
                if mask is not None and mask.any():
                    games = games.loc[~mask].copy()
                games = pd.concat([games, overlay], ignore_index=True, sort=False)
        except Exception as exc:
            logger.warning("Pregame overlay failed: %s", exc)
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    games = games[games["season"].isin([2024, 2025, 2026])]
    enriched = build_all_features(games)
    if should_overlay:
        try:
            from src.live_feature_forward import forward_project_features
            enriched = forward_project_features(enriched, target)
        except Exception as exc:
            logger.warning("Forward-projection failed: %s", exc)
    enriched = add_derived_for_strategies(enriched)

    # Derived OVER fields (may not exist in base features).
    if "combined_rpg" not in enriched.columns:
        if "rpg_home" in enriched.columns and "rpg_away" in enriched.columns:
            enriched["combined_rpg"] = enriched["rpg_home"] + enriched["rpg_away"]
    if "bullpen_fip_7g_combined" not in enriched.columns:
        if "bp_fip_7g_home" in enriched.columns and "bp_fip_7g_away" in enriched.columns:
            enriched["bullpen_fip_7g_combined"] = (
                enriched["bp_fip_7g_home"] + enriched["bp_fip_7g_away"]
            )
    if "sp_fip_floor_short" not in enriched.columns:
        if "home_sp_fip_short" in enriched.columns and "away_sp_fip_short" in enriched.columns:
            enriched["sp_fip_floor_short"] = enriched[
                ["home_sp_fip_short", "away_sp_fip_short"]
            ].max(axis=1, skipna=False)
    if "rpg_vs_line" not in enriched.columns:
        if "combined_rpg" in enriched.columns and "close_ou" in enriched.columns:
            enriched["rpg_vs_line"] = enriched["combined_rpg"] - enriched["close_ou"]

    return enriched


def slice_day(enriched: pd.DataFrame, target: date) -> pd.DataFrame:
    """Return rows whose date equals target (handles Timestamp vs date)."""
    if enriched.empty:
        return enriched
    first = enriched["date"].iloc[0]
    if hasattr(first, "date"):
        return enriched[enriched["date"].dt.date == target]
    return enriched[enriched["date"] == target]


def coverage_pct(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns:
        return -1.0
    if len(df) == 0:
        return 0.0
    return 100.0 * df[col].notna().mean()


def cascade_tier1(df: pd.DataFrame) -> list[tuple[str, int]]:
    if df.empty:
        return [("start", 0)]
    steps = [("start", len(df))]
    if "home_is_bullpen_no_starter" not in df.columns:
        steps.append(("MISSING home_is_bullpen_no_starter", 0))
        return steps
    s = df[df["home_is_bullpen_no_starter"] == True]
    steps.append(("home_is_bullpen_no_starter", len(s)))
    s = s[s["away_is_bullpen_no_starter"] != True]
    steps.append(("& away_has_starter", len(s)))
    return steps


def cascade_tier2(df: pd.DataFrame) -> list[tuple[str, int]]:
    if df.empty:
        return [("start", 0)]
    steps = [("start", len(df))]
    for col in ["bp_ip_3d_home", "bp_ip_3d_away", "bp_workload_gap", "fav_is_home",
                "home_is_bullpen_no_starter", "away_is_bullpen_no_starter"]:
        if col not in df.columns:
            steps.append((f"MISSING {col}", 0))
            return steps
    s = df[df["fav_is_home"].fillna(False) == True]
    steps.append(("fav_is_home", len(s)))
    s = s[(s["home_is_bullpen_no_starter"] != True) & (s["away_is_bullpen_no_starter"] != True)]
    steps.append(("& both have starter", len(s)))
    s = s[s["bp_workload_gap"] >= 3.0]
    steps.append(("& bp_workload_gap>=3.0", len(s)))
    s = s[s["bp_ip_3d_away"] <= 7.0]
    steps.append(("& bp_ip_3d_away<=7.0", len(s)))
    return steps


def cascade_tier3(df: pd.DataFrame) -> list[tuple[str, int]]:
    if df.empty:
        return [("start", 0)]
    steps = [("start", len(df))]
    for col in ["away_sp_fip_short", "starter_depth_diff_short", "bp_ip_3d_home",
                "fav_is_home", "home_is_bullpen_no_starter", "away_is_bullpen_no_starter"]:
        if col not in df.columns:
            steps.append((f"MISSING {col}", 0))
            return steps
    s = df[df["fav_is_home"].fillna(False) == True]
    steps.append(("fav_is_home", len(s)))
    s = s[(s["home_is_bullpen_no_starter"] != True) & (s["away_is_bullpen_no_starter"] != True)]
    steps.append(("& both have starter", len(s)))
    s = s[s["away_sp_fip_short"] <= 3.5]
    steps.append(("& away_sp_fip_short<=3.5", len(s)))
    s = s[s["starter_depth_diff_short"] <= -1.0]
    steps.append(("& depth_diff_short<=-1.0", len(s)))
    s = s[s["bp_ip_3d_home"] >= 8.0]
    steps.append(("& bp_ip_3d_home>=8.0", len(s)))
    return steps


def cascade_fav_rl(df: pd.DataFrame) -> list[tuple[str, int]]:
    if df.empty:
        return [("start", 0)]
    steps = [("start", len(df))]
    for col in ["fav_implied_prob", "fav_starter_fip_diff", "fav_power_rate_diff"]:
        if col not in df.columns:
            steps.append((f"MISSING {col}", 0))
            return steps
    s = df[df["fav_implied_prob"] >= 0.62]
    steps.append(("fav_implied_prob>=0.62", len(s)))
    s = s[s["fav_implied_prob"] < 0.75]
    steps.append(("& fav_implied_prob<0.75", len(s)))
    s = s[s["fav_starter_fip_diff"] <= -0.2]
    steps.append(("& fav_starter_fip_diff<=-0.2", len(s)))
    s = s[s["fav_power_rate_diff"] >= 0]
    steps.append(("& fav_power_rate_diff>=0", len(s)))
    return steps


def cascade_over(df: pd.DataFrame) -> list[tuple[str, int]]:
    if df.empty:
        return [("start", 0)]
    steps = [("start", len(df))]
    for col in ["rpg_vs_line", "bullpen_fip_7g_combined", "sp_fip_floor_short"]:
        if col not in df.columns:
            steps.append((f"MISSING {col}", 0))
            return steps
    s = df[df["rpg_vs_line"] >= 2.0]
    steps.append(("rpg_vs_line>=2.0", len(s)))
    s = s[s["bullpen_fip_7g_combined"] >= 7.5]
    steps.append(("& bullpen_fip_7g_combined>=7.5", len(s)))
    s = s[s["sp_fip_floor_short"] >= 4.5]
    steps.append(("& sp_fip_floor_short>=4.5", len(s)))
    # Power split
    s_power_fip = s[s["bullpen_fip_7g_combined"] >= 10.0]
    s_power_line = s[s["close_ou"] <= 8.0] if "close_ou" in s.columns else s.iloc[:0]
    steps.append(("  power FIP>=10", len(s_power_fip)))
    steps.append(("  power line<=8.0", len(s_power_line)))
    return steps


CASCADES = [
    ("tier1_bullpen_day", cascade_tier1),
    ("tier2_fatigue_gap", cascade_tier2),
    ("tier3_pitcher_advantage", cascade_tier3),
    ("fav_rl", cascade_fav_rl),
    ("over_bullpen_mismatch", cascade_over),
]


def report_day(enriched: pd.DataFrame, target: date) -> dict:
    day = slice_day(enriched, target)
    print(f"\n{'=' * 90}")
    print(f"  DATE: {target}  |  games: {len(day)}")
    print(f"{'=' * 90}")

    if day.empty:
        print("  (no games for this date in the enriched frame)")
        return {"date": target.isoformat(), "games": 0}

    print(f"\n  FEATURE COVERAGE (% non-null among {len(day)} games)")
    print(f"  {'field':<34} {'coverage':>10}")
    print("  " + "-" * 48)
    cov_report = {}
    for col in COVERAGE_FIELDS:
        pct = coverage_pct(day, col)
        cov_report[col] = pct
        if pct < 0:
            print(f"  {col:<34} {'MISSING':>10}")
        else:
            flag = ""
            if pct < 50:
                flag = "  <-- LOW"
            elif pct == 0.0:
                flag = "  <-- ZERO"
            print(f"  {col:<34} {pct:>9.1f}%{flag}")

    print(f"\n  STRATEGY FILTER CASCADES")
    cascade_report = {}
    for tier_name, fn in CASCADES:
        steps = fn(day)
        print(f"\n  [{tier_name}]")
        for label, n in steps:
            print(f"    {label:<38} {n:>4}")
        cascade_report[tier_name] = steps

    return {
        "date": target.isoformat(),
        "games": len(day),
        "coverage": cov_report,
        "cascades": {k: [(lbl, n) for lbl, n in v] for k, v in cascade_report.items()},
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", type=str, default=None,
                   help="Target date YYYY-MM-DD (default: 2026-04-14 fallback)")
    p.add_argument("--last", type=int, default=None,
                   help="Analyse the last N fully-merged days (overrides --date)")
    p.add_argument("--out", type=str, default=None,
                   help="Optional: write JSON report to this path")
    args = p.parse_args()

    # Determine target dates.
    if args.last:
        # Read last postgame date from state.json.
        state_path = (
            Path(__file__).resolve().parent.parent
            / "data" / "fetch_2026" / "state.json"
        )
        if state_path.exists():
            state = json.loads(state_path.read_text())
            last = date.fromisoformat(state["last_postgame_date"])
        else:
            last = date.today() - timedelta(days=1)
        targets = [last - timedelta(days=i) for i in range(args.last - 1, -1, -1)]
    else:
        if args.date:
            targets = [date.fromisoformat(args.date)]
        else:
            targets = [date(2026, 4, 14)]

    print("Building enriched frame (this takes ~30s)...")
    enriched = build_enriched(targets[0])
    print(f"Enriched rows: {len(enriched)}, cols: {len(enriched.columns)}")

    reports = []
    for t in targets:
        reports.append(report_day(enriched, t))

    if args.out:
        Path(args.out).write_text(json.dumps(reports, indent=2, default=str))
        print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
