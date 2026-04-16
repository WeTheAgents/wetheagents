"""Validate that 2022-2025 data gaps are fixed end-to-end (Session 37).

Before the Session 37 fix, the standard load pipeline

    load_all_seasons → apply_data_filters → add_derived_odds
                     → build_all_features → add_derived_for_strategies

produced a frame where, for 2022-2025:

    * ``home_run_line`` / ``away_run_line`` were 100% NaN
    * ``fav_power_rate_diff`` was 100% NaN

Any strategy that filters on ``home_run_line ∈ {-1.5, +1.5}`` silently dropped
2022-2025 entirely, so pick counts that *looked* like "all 11 seasons" were
really 2014-2021 only.

This script re-runs the full pipeline and reports per-season:

    1. Coverage of ``home_run_line`` / ``away_run_line`` / ``fav_power_rate_diff``.
    2. Count of rows that would qualify for the ``fav_rl`` strategy
       (standard regime = Sess 25 filter, i.e. fav_implied ∈ [0.62,0.75) &
       fav_starter_fip_diff ≤ -0.2 & fav_power_rate_diff ≥ 0).
    3. Count of "reverse RL" rows — the mirror image where the dog is on
       +1.5 and the strategy expects a populated away_run_line/away_run_line_odds.

The goal is simply to confirm that 2022-2025 pick counts are non-zero and in
the expected order of magnitude after the data-gap fix.

Usage:
    python scripts/validate_reverse_rl.py
    python scripts/validate_reverse_rl.py --no-features  # odds/run_line only
"""

from __future__ import annotations

import argparse
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Ensure the project root is on sys.path so ``src.*`` imports resolve when
# the script is invoked from outside the domain directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.data_loader import (  # noqa: E402
    add_derived_odds,
    apply_data_filters,
    load_all_seasons,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


SEASONS_OF_INTEREST = [2021, 2022, 2023, 2024, 2025]
STANDARD_REGIME_SEASONS = list(range(2014, 2026))
STANDARD_REGIME_SEASONS.remove(2020)  # COVID


# ── Fav-RL (Sess 25) standard-regime filter ────────────────────────────────
FAV_RL_IMPL_MIN = 0.62
FAV_RL_IMPL_MAX = 0.75  # exclusive
FAV_RL_FIP_DIFF_MAX = -0.2
FAV_RL_POWER_DIFF_MIN = 0.0


def _section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def _counts_table(
    df: pd.DataFrame,
    cols: list[str],
    season_col: str = "season",
    seasons: list[int] | None = None,
) -> pd.DataFrame:
    """Compute per-season non-null counts for each column in ``cols``."""
    if seasons is None:
        seasons = sorted(df[season_col].dropna().unique().tolist())

    rows: list[dict] = []
    for s in seasons:
        sub = df[df[season_col] == s]
        n = len(sub)
        row = {"season": s, "n_games": n}
        for c in cols:
            if c not in df.columns:
                row[f"{c}_nonnull"] = 0
                row[f"{c}_pct"] = 0.0
                continue
            nn = int(sub[c].notna().sum())
            row[f"{c}_nonnull"] = nn
            row[f"{c}_pct"] = 100.0 * nn / n if n > 0 else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def _print_counts_table(tbl: pd.DataFrame, cols: list[str]) -> None:
    header = f"  {'Season':>6}  {'N':>6}"
    for c in cols:
        header += f"  {c[:24]:>24}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for _, r in tbl.iterrows():
        line = f"  {int(r['season']):>6}  {int(r['n_games']):>6}"
        for c in cols:
            nn = int(r[f"{c}_nonnull"])
            pct = float(r[f"{c}_pct"])
            line += f"  {nn:>6}/{int(r['n_games']):<6} ({pct:5.1f}%)"
        print(line)


def _fav_rl_mask(df: pd.DataFrame) -> pd.Series:
    """Standard-regime Sess 25 fav_rl filter (no run_line gate)."""
    required = [
        "fav_implied_prob",
        "fav_starter_fip_diff",
        "fav_power_rate_diff",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("fav_rl_mask: missing columns %s; all-False", missing)
        return pd.Series(False, index=df.index)

    return (
        (df["fav_implied_prob"] >= FAV_RL_IMPL_MIN)
        & (df["fav_implied_prob"] < FAV_RL_IMPL_MAX)
        & (df["fav_starter_fip_diff"] <= FAV_RL_FIP_DIFF_MAX)
        & (df["fav_power_rate_diff"] >= FAV_RL_POWER_DIFF_MIN)
    )


def _fav_rl_mask_with_odds_gate(df: pd.DataFrame) -> pd.Series:
    """fav_rl + a run_line gate (i.e. require live -1.5 odds on the fav side).

    Any backtest that compares its picks against the actual RL market must
    additionally filter to rows where the fav has an entry at -1.5 with
    usable odds.  This helper makes the difference explicit.
    """
    base = _fav_rl_mask(df)
    if not base.any():
        return base
    if "home_run_line_odds" not in df.columns or "away_run_line_odds" not in df.columns:
        return pd.Series(False, index=df.index)
    fav_is_home = df.get("fav_is_home", pd.Series(False, index=df.index)).fillna(False)
    home_rl_ok = df["home_run_line"].fillna(0) == -1.5
    away_rl_ok = df["away_run_line"].fillna(0) == -1.5
    home_odds_ok = df["home_run_line_odds"].notna() & (df["home_run_line_odds"] != 0)
    away_odds_ok = df["away_run_line_odds"].notna() & (df["away_run_line_odds"] != 0)
    return base & np.where(
        fav_is_home, home_rl_ok & home_odds_ok, away_rl_ok & away_odds_ok
    )


def _reverse_rl_mask(df: pd.DataFrame) -> pd.Series:
    """Reverse-RL = dog +1.5, with real away_run_line_odds present.

    This is the mirror of fav_rl for sanity-checking: the strategy expects the
    underdog to be on +1.5, so we require the xlsx carries the +1.5 value with
    non-NaN odds on the dog's side.
    """
    if "home_run_line" not in df.columns:
        return pd.Series(False, index=df.index)
    fav_is_home = df.get("fav_is_home", pd.Series(False, index=df.index)).fillna(False)
    # Dog spread = opposite side's +1.5.
    home_dog_plus = (~fav_is_home) & (df["home_run_line"] == 1.5)
    away_dog_plus = (fav_is_home) & (df["away_run_line"] == 1.5)
    home_dog_odds = df.get("home_run_line_odds", pd.Series(np.nan, index=df.index)).notna()
    away_dog_odds = df.get("away_run_line_odds", pd.Series(np.nan, index=df.index)).notna()
    return (home_dog_plus & home_dog_odds) | (away_dog_plus & away_dog_odds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-features",
        action="store_true",
        help="Skip build_all_features (faster — only checks raw run_line)",
    )
    parser.add_argument(
        "--no-enrichment",
        action="store_true",
        help="Run with enrich_innings=False and enrich_run_line=False (pre-fix)",
    )
    args = parser.parse_args()

    logger.info("Loading all seasons (enrichment=%s)…", not args.no_enrichment)
    games = load_all_seasons(
        enrich_innings=not args.no_enrichment,
        enrich_run_line=not args.no_enrichment,
    )
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    _section("CHECK 1 — run_line coverage per season (after load)")
    rl_cols = [
        "home_run_line",
        "home_run_line_odds",
        "away_run_line",
        "away_run_line_odds",
    ]
    tbl = _counts_table(games, rl_cols, seasons=STANDARD_REGIME_SEASONS)
    for _, r in tbl.iterrows():
        line = f"  {int(r['season']):>4} | N={int(r['n_games']):>5}  "
        for c in rl_cols:
            line += f"{c:<22}={r[f'{c}_nonnull']:>5} ({r[f'{c}_pct']:5.1f}%)  "
        print(line)

    # Coverage summary specifically for the problem seasons.
    problem = tbl[tbl["season"].isin([2022, 2023, 2024, 2025])]
    total_problem = problem["n_games"].sum()
    total_rl = problem["home_run_line_nonnull"].sum()
    print()
    print(
        f"  2022-2025 summary: "
        f"home_run_line={total_rl}/{total_problem} rows "
        f"({100.0 * total_rl / max(total_problem, 1):5.1f}%)"
    )

    if args.no_features:
        _section("SKIP CHECK 2 (--no-features)")
        return 0

    # Expensive: build features (this takes ~3 minutes in a full pipeline).
    logger.info("Building features (~3 min)…")
    from src.features import build_all_features
    from src.strategies.base import add_derived_for_strategies

    enriched = build_all_features(games)
    enriched = add_derived_for_strategies(enriched)

    _section("CHECK 2 — fav_power_rate_diff coverage per season")
    pr_cols = ["power_rate_home", "power_rate_away", "fav_power_rate_diff"]
    tbl2 = _counts_table(enriched, pr_cols, seasons=STANDARD_REGIME_SEASONS)
    for _, r in tbl2.iterrows():
        line = f"  {int(r['season']):>4} | N={int(r['n_games']):>5}  "
        for c in pr_cols:
            line += f"{c:<22}={r[f'{c}_nonnull']:>5} ({r[f'{c}_pct']:5.1f}%)  "
        print(line)

    _section("CHECK 3 — fav_rl (standard regime) picks per season")
    mask = _fav_rl_mask(enriched)
    mask_gated = _fav_rl_mask_with_odds_gate(enriched)
    per_season = []
    for s in STANDARD_REGIME_SEASONS:
        sub = enriched[enriched["season"] == s]
        n = len(sub)
        n_base = int(mask[enriched["season"] == s].sum())
        n_gated = int(mask_gated[enriched["season"] == s].sum())
        per_season.append(
            {"season": s, "n_games": n, "fav_rl": n_base, "fav_rl_rl15_gated": n_gated}
        )
        print(
            f"  {s:>4} | N={n:>5}  "
            f"fav_rl (power+fip only) = {n_base:>5}  |  "
            f"+ RL -1.5 odds gate = {n_gated:>5}"
        )
    totals = pd.DataFrame(per_season).sum(numeric_only=True)
    print(
        f"  ---- total: fav_rl={int(totals['fav_rl']):>5}  "
        f"rl15-gated={int(totals['fav_rl_rl15_gated']):>5}"
    )

    _section("CHECK 4 — reverse-RL (dog +1.5) rows per season")
    rev_mask = _reverse_rl_mask(enriched)
    for s in STANDARD_REGIME_SEASONS:
        sub_mask = rev_mask & (enriched["season"] == s)
        n = int((enriched["season"] == s).sum())
        print(f"  {s:>4} | N={n:>5}  dog-plus-15 with odds = {int(sub_mask.sum()):>5}")

    _section("VERDICT")
    problem_with_picks = [
        s for s in [2022, 2023, 2024, 2025]
        if any(r["season"] == s and r["fav_rl"] > 0 for r in per_season)
    ]
    problem_rl_gated = [
        s for s in [2022, 2023, 2024, 2025]
        if any(r["season"] == s and r["fav_rl_rl15_gated"] > 0 for r in per_season)
    ]
    print(f"  Seasons 2022-2025 with fav_rl picks (unrestricted): {problem_with_picks}")
    print(f"  Seasons 2022-2025 with fav_rl picks (RL-15 gated):  {problem_rl_gated}")

    if set(problem_with_picks) != {2022, 2023, 2024, 2025}:
        print()
        print("  WARN: not every 2022-2025 season has fav_rl picks.")
        print("        Either the filter is genuinely empty, or power_rate is still NaN.")
        print("        Re-check CHECK 2 coverage before believing the backtest.")
        return 1

    print("  PASS: 2022-2025 are represented in the standard-regime fav_rl filter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
