"""Phase 0: Does Squad Stability Score predict outcomes in Brazilian Serie A?

Produces two analyses:
1. SSS bucket analysis (per-team): bin matches by team SSS, compare
   implied win% from odds vs actual win%, look for delta.
2. SSS differential analysis (game-level): bin by (SSS_home - SSS_away),
   compare implied home win% vs actual home win%.

If delta for low SSS is consistently negative -> signal confirmed.

Output:
  - Console tables
  - CSV export to knowledge/sss_signal_results.csv
  - Markdown report to knowledge/phase0_signal_report.md

Usage:
    python scripts/run_sss_signal_test.py
"""

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_sss_features, sss_coverage_report

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"
N_BUCKETS = 5


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def team_level_view(games: pd.DataFrame) -> pd.DataFrame:
    """Convert game-level to team-level (2 rows per match, like MLB pattern).

    Each row represents one team's performance in one match:
      team, date, season, sss_cum, sss_r10, implied_win, actual_win,
      implied_ppg, actual_ppg
    """
    rows = []

    for _, g in games.iterrows():
        # Home team
        rows.append({
            "date": g["date"],
            "season": g["season"],
            "team": g["home_team"],
            "side": "home",
            "sss_cum": g.get("sss_cum_home"),
            "sss_r10": g.get("sss_r10_home"),
            "implied_win": g["home_implied"],
            "actual_win": 1.0 if g["result"] == "H" else 0.0,
            "implied_ppg": g["home_implied_ppg"],
            "actual_ppg": 3.0 if g["result"] == "H" else (1.0 if g["result"] == "D" else 0.0),
        })

        # Away team
        rows.append({
            "date": g["date"],
            "season": g["season"],
            "team": g["away_team"],
            "side": "away",
            "sss_cum": g.get("sss_cum_away"),
            "sss_r10": g.get("sss_r10_away"),
            "implied_win": g["away_implied"],
            "actual_win": 1.0 if g["result"] == "A" else 0.0,
            "implied_ppg": g["away_implied_ppg"],
            "actual_ppg": 3.0 if g["result"] == "A" else (1.0 if g["result"] == "D" else 0.0),
        })

    return pd.DataFrame(rows)


def bucket_analysis(
    df: pd.DataFrame,
    sss_col: str,
    label: str,
) -> pd.DataFrame:
    """Bin by SSS and compare implied vs actual outcomes.

    Returns summary table with one row per bucket.
    """
    # Drop NaN SSS
    valid = df.dropna(subset=[sss_col])
    if len(valid) < N_BUCKETS * 10:
        logger.warning(f"Only {len(valid)} valid rows for {label} — too few for {N_BUCKETS} buckets")
        return pd.DataFrame()

    # Equal-frequency binning
    valid = valid.copy()
    valid["bucket"] = pd.qcut(valid[sss_col], N_BUCKETS, labels=False, duplicates="drop")

    rows = []
    for bucket_id, grp in valid.groupby("bucket"):
        n = len(grp)
        mean_sss = grp[sss_col].mean()

        implied_win = grp["implied_win"].mean()
        actual_win = grp["actual_win"].mean()
        delta_win = actual_win - implied_win

        implied_ppg = grp["implied_ppg"].mean()
        actual_ppg = grp["actual_ppg"].mean()
        delta_ppg = actual_ppg - implied_ppg

        rows.append({
            "bucket": int(bucket_id),
            "n": n,
            "mean_sss": round(mean_sss, 4),
            "implied_win%": round(implied_win * 100, 1),
            "actual_win%": round(actual_win * 100, 1),
            "delta_win%": round(delta_win * 100, 1),
            "implied_ppg": round(implied_ppg, 3),
            "actual_ppg": round(actual_ppg, 3),
            "delta_ppg": round(delta_ppg, 3),
        })

    result = pd.DataFrame(rows)

    # Statistical tests
    spearman_r, spearman_p = stats.spearmanr(result["bucket"], result["delta_win%"])

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  N = {len(valid)} | Spearman r = {spearman_r:.3f}, p = {spearman_p:.4f}")
    print(f"{'='*70}")
    print(result.to_string(index=False))
    print()

    return result


def differential_analysis(games: pd.DataFrame, sss_col_suffix: str, label: str) -> pd.DataFrame:
    """Bin by SSS differential and compare implied vs actual home win%.

    Args:
        games: match-level DataFrame with SSS columns
        sss_col_suffix: "cum" or "r10"
        label: description for printing
    """
    diff_col = f"sss_{sss_col_suffix}_diff"
    valid = games.dropna(subset=[diff_col])

    if len(valid) < N_BUCKETS * 10:
        logger.warning(f"Only {len(valid)} valid rows for {label} — too few")
        return pd.DataFrame()

    valid = valid.copy()
    valid["bucket"] = pd.qcut(valid[diff_col], N_BUCKETS, labels=False, duplicates="drop")

    rows = []
    for bucket_id, grp in valid.groupby("bucket"):
        n = len(grp)
        mean_diff = grp[diff_col].mean()

        implied_home = grp["home_implied"].mean()
        actual_home = grp["home_win"].astype(float).mean()
        delta = actual_home - implied_home

        rows.append({
            "bucket": int(bucket_id),
            "n": n,
            "mean_sss_diff": round(mean_diff, 4),
            "implied_home_win%": round(implied_home * 100, 1),
            "actual_home_win%": round(actual_home * 100, 1),
            "delta%": round(delta * 100, 1),
        })

    result = pd.DataFrame(rows)

    spearman_r, spearman_p = stats.spearmanr(result["bucket"], result["delta%"])

    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  N = {len(valid)} | Spearman r = {spearman_r:.3f}, p = {spearman_p:.4f}")
    print(f"{'='*70}")
    print(result.to_string(index=False))
    print()

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    games: pd.DataFrame,
    team_results: dict[str, pd.DataFrame],
    diff_results: dict[str, pd.DataFrame],
    coverage: pd.DataFrame,
) -> str:
    """Generate markdown report."""
    lines = [
        "# Phase 0 — SSS Signal Validation Report",
        "",
        "## Dataset",
        f"- Matches: {len(games)}",
        f"- Seasons: {sorted(games['season'].unique())}",
        f"- Teams: {games['home_team'].nunique()}",
        "",
        "## SSS Coverage",
        "",
        coverage.to_markdown(index=False),
        "",
    ]

    for variant in ["cumulative", "rolling-10"]:
        key = "cum" if "cum" in variant else "r10"

        lines.append(f"## {variant.title()} SSS — Team-Level Bucket Analysis")
        lines.append("")
        if key in team_results and len(team_results[key]) > 0:
            lines.append(team_results[key].to_markdown(index=False))
        else:
            lines.append("*Insufficient data*")
        lines.append("")

        lines.append(f"## {variant.title()} SSS — Differential Analysis (Home - Away)")
        lines.append("")
        if key in diff_results and len(diff_results[key]) > 0:
            lines.append(diff_results[key].to_markdown(index=False))
        else:
            lines.append("*Insufficient data*")
        lines.append("")

    # Interpretation guide
    lines.extend([
        "## Interpretation",
        "",
        "- **delta_win% < 0 in low SSS buckets**: teams with weakened squads "
        "underperform their odds → signal exists",
        "- **delta_win% > 0 in high SSS buckets**: teams with full-strength squads "
        "outperform their odds → signal exists",
        "- **Spearman p < 0.05**: statistically significant monotonic relationship",
        "- **Spearman p < 0.10**: worth investigating further",
        "- **Spearman p > 0.10**: no signal detected",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("  Phase 0: SSS Signal Validation — Turkish Super Lig")
    print("=" * 70)
    print()

    # Step 1: Load data
    print("Step 1: Loading data...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    print(f"  Loaded {len(games)} matches\n")

    # Step 2: Compute SSS features
    print("Step 2: Computing SSS features...")
    games = build_sss_features(games)

    # Coverage report
    coverage = sss_coverage_report(games)
    print("\n  SSS Coverage:")
    print(coverage.to_string(index=False))
    print()

    # Step 3: Team-level bucket analysis
    print("Step 3: Running team-level bucket analysis...")
    team_df = team_level_view(games)

    team_results = {}
    for variant, col in [("cum", "sss_cum"), ("r10", "sss_r10")]:
        label = f"Team-Level SSS Buckets ({variant})"
        team_results[variant] = bucket_analysis(team_df, col, label)

    # Step 4: Differential analysis
    print("Step 4: Running SSS differential analysis...")
    diff_results = {}
    for variant in ["cum", "r10"]:
        label = f"SSS Differential Home-Away ({variant})"
        diff_results[variant] = differential_analysis(games, variant, label)

    # Step 5: Generate report
    print("Step 5: Generating report...")
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

    report = generate_report(games, team_results, diff_results, coverage)
    report_path = KNOWLEDGE_DIR / "phase0_signal_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  Report saved to {report_path}")

    # Save raw results as CSV
    for key, df in team_results.items():
        if len(df) > 0:
            csv_path = KNOWLEDGE_DIR / f"sss_team_buckets_{key}.csv"
            df.to_csv(csv_path, index=False)
    for key, df in diff_results.items():
        if len(df) > 0:
            csv_path = KNOWLEDGE_DIR / f"sss_diff_buckets_{key}.csv"
            df.to_csv(csv_path, index=False)

    print("\nDone!")


if __name__ == "__main__":
    main()
