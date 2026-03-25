"""Bullpen Fatigue Hypothesis: does a team allow more runs the day after
a "bullpen day" (no pitcher reaches 4.0 IP)?

Compares runs allowed vs expected (from closing O/U line) for:
- Fatigue group: next-day games after a bullpen day
- Control group: next-day games after a normal start

Usage:
    python scripts/run_bullpen_fatigue_analysis.py
"""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd
from scipy import stats

from src.data_loader import (
    load_all_seasons,
    apply_data_filters,
    add_derived_odds,
    merge_retrosheet_pitchers,
)


def load_games():
    """Load games with retrosheet bullpen flags merged."""
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    games = merge_retrosheet_pitchers(games)
    return games


def build_team_log(games: pd.DataFrame) -> pd.DataFrame:
    """Convert game-level rows into team-level rows (2 per game)."""
    rows = []
    for _, g in games.iterrows():
        common = dict(
            date=g["date"],
            season=g["season"],
            close_ou=g.get("close_ou"),
        )
        # Normalized implied probabilities (remove vig)
        h_ip = g.get("home_implied_prob", np.nan)
        a_ip = g.get("away_implied_prob", np.nan)
        total_ip = h_ip + a_ip if pd.notna(h_ip) and pd.notna(a_ip) else np.nan
        h_norm = h_ip / total_ip if pd.notna(total_ip) and total_ip > 0 else np.nan
        a_norm = a_ip / total_ip if pd.notna(total_ip) and total_ip > 0 else np.nan

        # Home perspective
        rows.append({
            **common,
            "team": g["home_team"],
            "opponent": g["away_team"],
            "is_home": True,
            "runs_scored": g["home_final"],
            "runs_allowed": g["away_final"],
            "was_bullpen_day": bool(g.get("home_is_bullpen_no_starter", False)),
            "team_implied_norm": h_norm,
            "opp_implied_norm": a_norm,
        })
        # Away perspective
        rows.append({
            **common,
            "team": g["away_team"],
            "opponent": g["home_team"],
            "is_home": False,
            "runs_scored": g["away_final"],
            "runs_allowed": g["home_final"],
            "was_bullpen_day": bool(g.get("away_is_bullpen_no_starter", False)),
            "team_implied_norm": a_norm,
            "opp_implied_norm": h_norm,
        })

    tl = pd.DataFrame(rows)
    tl["date"] = pd.to_datetime(tl["date"])
    return tl


def find_next_day_pairs(team_log: pd.DataFrame):
    """For each team-season, pair consecutive games that are 1 day apart.

    Returns (fatigue_df, control_df) where each row describes the NEXT game
    after a bullpen day (fatigue) or normal game (control).
    """
    fatigue, control = [], []

    for (team, season), grp in team_log.groupby(["team", "season"]):
        grp = grp.sort_values("date").reset_index(drop=True)

        for i in range(1, len(grp)):
            prev = grp.iloc[i - 1]
            curr = grp.iloc[i]

            day_gap = (curr["date"] - prev["date"]).days
            if day_gap != 1:
                continue

            ou = curr["close_ou"]
            if pd.isna(ou) or ou <= 0:
                continue

            ra = curr["runs_allowed"]
            if pd.isna(ra):
                continue

            expected_simple = ou / 2.0
            opp_norm = curr["opp_implied_norm"]
            expected_ml = ou * opp_norm if pd.notna(opp_norm) else np.nan

            row = dict(
                team=team,
                season=season,
                bp_day_date=prev["date"],
                next_date=curr["date"],
                opponent=curr["opponent"],
                is_home=curr["is_home"],
                runs_allowed=ra,
                runs_scored=curr["runs_scored"],
                close_ou=ou,
                expected_ra_simple=expected_simple,
                expected_ra_ml=expected_ml,
                delta_simple=ra - expected_simple,
                delta_ml=ra - expected_ml if pd.notna(expected_ml) else np.nan,
                total_runs=ra + curr["runs_scored"],
                went_over=ra + curr["runs_scored"] > ou,
            )

            if prev["was_bullpen_day"]:
                fatigue.append(row)
            else:
                control.append(row)

    return pd.DataFrame(fatigue), pd.DataFrame(control)


def print_examples(fat: pd.DataFrame, n: int = 10):
    """Print n concrete examples from the fatigue group."""
    print(f"\n{'=' * 80}")
    print(f"  10 EXAMPLE GAMES: Next Day After Bullpen Day")
    print(f"{'=' * 80}\n")

    # Pick varied examples: top 5 by delta, bottom 3, 2 random
    fat_sorted = fat.sort_values("delta_simple", ascending=False)
    top = fat_sorted.head(5)
    bot = fat_sorted.tail(3)
    mid = fat_sorted.iloc[len(fat_sorted) // 4 : len(fat_sorted) // 4 + 2]
    sample = pd.concat([top, mid, bot]).head(n)

    header = (
        f"{'#':>2} | {'Team':<4} | {'BP Day':<10} | {'Next Day':<10} | "
        f"{'vs':<4} | {'H/A':>3} | {'RA':>3} | {'Exp':>5} | "
        f"{'Delta':>6} | {'OU':>5} | {'Total':>5} | {'O/U':>4}"
    )
    print(header)
    print("-" * len(header))

    for idx, (_, r) in enumerate(sample.iterrows(), 1):
        bp_date = r["bp_day_date"].strftime("%Y-%m-%d") if hasattr(r["bp_day_date"], "strftime") else str(r["bp_day_date"])
        nx_date = r["next_date"].strftime("%Y-%m-%d") if hasattr(r["next_date"], "strftime") else str(r["next_date"])
        ha = "H" if r["is_home"] else "A"
        ou_result = "OVER" if r["went_over"] else "UNDR"
        total = int(r["total_runs"])
        print(
            f"{idx:>2} | {r['team']:<4} | {bp_date} | {nx_date} | "
            f"{r['opponent']:<4} | {ha:>3} | {int(r['runs_allowed']):>3} | "
            f"{r['expected_ra_simple']:>5.1f} | {r['delta_simple']:>+6.1f} | "
            f"{r['close_ou']:>5.1f} | {total:>5} | {ou_result:>4}"
        )


def print_aggregate(fat: pd.DataFrame, ctrl: pd.DataFrame):
    """Print aggregate comparison: fatigue vs control."""
    print(f"\n{'=' * 80}")
    print(f"  AGGREGATE RESULTS")
    print(f"{'=' * 80}\n")

    n_f, n_c = len(fat), len(ctrl)
    ra_f, ra_c = fat["runs_allowed"].mean(), ctrl["runs_allowed"].mean()
    d_f, d_c = fat["delta_simple"].mean(), ctrl["delta_simple"].mean()
    sd_f, sd_c = fat["delta_simple"].std(), ctrl["delta_simple"].std()

    t_stat, p_val = stats.ttest_ind(
        fat["delta_simple"].dropna(),
        ctrl["delta_simple"].dropna(),
        equal_var=False,
    )

    over_f = fat["went_over"].mean() * 100
    over_c = ctrl["went_over"].mean() * 100

    print(f"{'':>26} | {'Fatigue':>12} | {'Control':>12} | {'Diff':>10}")
    print(f"{'-' * 26}-+-{'-' * 12}-+-{'-' * 12}-+-{'-' * 10}")
    print(f"{'N games':>26} | {n_f:>12,} | {n_c:>12,} |")
    print(f"{'Mean runs allowed':>26} | {ra_f:>12.3f} | {ra_c:>12.3f} | {ra_f - ra_c:>+10.3f}")
    print(f"{'Mean delta (RA - OU/2)':>26} | {d_f:>12.3f} | {d_c:>12.3f} | {d_f - d_c:>+10.3f}")
    print(f"{'Std dev delta':>26} | {sd_f:>12.3f} | {sd_c:>12.3f} |")
    print(f"{'Over rate':>26} | {over_f:>11.1f}% | {over_c:>11.1f}% | {over_f - over_c:>+9.1f}%")
    print()
    print(f"  Welch t-test: t = {t_stat:.3f}, p = {p_val:.4f}")
    sig = "YES (p < 0.05)" if p_val < 0.05 else "NO (p >= 0.05)"
    print(f"  Statistically significant: {sig}")

    # ML-weighted method
    fat_ml = fat["delta_ml"].dropna()
    ctrl_ml = ctrl["delta_ml"].dropna()
    if len(fat_ml) > 0 and len(ctrl_ml) > 0:
        t2, p2 = stats.ttest_ind(fat_ml, ctrl_ml, equal_var=False)
        print(f"\n  ML-weighted method: fatigue delta = {fat_ml.mean():+.3f}, "
              f"control delta = {ctrl_ml.mean():+.3f}, t = {t2:.3f}, p = {p2:.4f}")


def print_seasonal(fat: pd.DataFrame):
    """Print per-season breakdown of fatigue group."""
    print(f"\n{'=' * 80}")
    print(f"  PER-SEASON BREAKDOWN (Fatigue Group)")
    print(f"{'=' * 80}\n")

    print(f"{'Season':>6} | {'N':>5} | {'Mean RA':>8} | {'Mean Delta':>10} | {'Over%':>6}")
    print(f"{'-' * 6}-+-{'-' * 5}-+-{'-' * 8}-+-{'-' * 10}-+-{'-' * 6}")

    for season, grp in fat.groupby("season"):
        n = len(grp)
        ra = grp["runs_allowed"].mean()
        d = grp["delta_simple"].mean()
        ov = grp["went_over"].mean() * 100
        print(f"{int(season):>6} | {n:>5} | {ra:>8.2f} | {d:>+10.3f} | {ov:>5.1f}%")


def main():
    print("=" * 80)
    print("  BULLPEN FATIGUE ANALYSIS")
    print("  Does a team allow more runs the day after a bullpen day?")
    print("=" * 80)

    print("\nLoading data...")
    games = load_games()
    n_total = len(games)

    bp_home = games["home_is_bullpen_no_starter"].sum() if "home_is_bullpen_no_starter" in games.columns else 0
    bp_away = games["away_is_bullpen_no_starter"].sum() if "away_is_bullpen_no_starter" in games.columns else 0
    print(f"  Games loaded: {n_total:,}")
    print(f"  Bullpen days (home): {bp_home:,}")
    print(f"  Bullpen days (away): {bp_away:,}")

    print("\nBuilding team-level game log...")
    tl = build_team_log(games)
    bp_total = tl["was_bullpen_day"].sum()
    print(f"  Team-game rows: {len(tl):,}")
    print(f"  Total bullpen day instances: {bp_total:,}")

    print("\nFinding next-day game pairs...")
    fat, ctrl = find_next_day_pairs(tl)
    print(f"  Fatigue group (day after BP day): {len(fat):,}")
    print(f"  Control group (day after normal): {len(ctrl):,}")

    if len(fat) == 0:
        print("\n  No fatigue games found. Check retrosheet data.")
        return

    print_examples(fat)
    print_aggregate(fat, ctrl)
    print_seasonal(fat)


if __name__ == "__main__":
    main()
