"""Series dogon with pitcher proxy features — testing if pitcher layer adds edge.

Key question: does adding pitcher-level proxy metrics (win rate, runs allowed,
first inning ERA, oscillators) improve series dogon ROI beyond team-only features?

Previous best (team only): 87.1% WR, ~+0.4% ROI (365 series, RPI>=0.05).
Target: 85%+ WR with positive ROI at scale (1000+ series).
"""

import sys
import os
import warnings
import logging

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import build_all_features
from src.series import (
    build_backtest_summary,
    identify_series,
    print_backtest_report,
    run_series_dogon,
    select_series_favorite,
    Series,
    SeriesResult,
)

# ── Load and build ALL features (team + pitcher) ────────────────────────
print("Loading data and computing features (team + pitcher, takes ~3 min)...")
games = load_all_seasons()
games = apply_data_filters(games)
games = add_derived_odds(games)
enriched = build_all_features(games, include_pitcher=True)
print(f"Games with features: {len(enriched)}")

# Quick coverage check
pitcher_cols = [c for c in enriched.columns if c.startswith("home_sp_") or c.startswith("away_sp_")]
print(f"Pitcher feature columns: {len(pitcher_cols)}")
n_valid = enriched["home_sp_wr_short"].notna().sum()
print(f"Pitcher data coverage: {n_valid}/{len(enriched)} ({100*n_valid/len(enriched):.1f}%)")

# ── Identify series ──────────────────────────────────────────────────────
all_series = identify_series(enriched)
print(f"Total series: {len(all_series)}")

# ── Feature lookup ───────────────────────────────────────────────────────
feature_cols = [
    # Team features
    "rpi_home", "rpi_away", "rpi_diff", "rpi_min",
    "wp_home", "wp_away", "wp_diff",
    "wp_last10_home", "wp_last10_away", "wp_last10_diff",
    "streak_home", "streak_away", "streak_diff",
    "games_played_min",
    "home_implied_prob", "away_implied_prob",
    # Pitcher features
    "home_sp_wr_short", "home_sp_wr_long", "home_sp_wr_momentum",
    "away_sp_wr_short", "away_sp_wr_long", "away_sp_wr_momentum",
    "home_sp_ra_short", "home_sp_ra_long", "home_sp_ra_momentum",
    "away_sp_ra_short", "away_sp_ra_long", "away_sp_ra_momentum",
    "home_sp_fi_ra_long", "away_sp_fi_ra_long",
    "home_sp_starts", "away_sp_starts",
    "sp_wr_short_diff", "sp_wr_long_diff", "sp_wr_momentum_diff",
    "sp_ra_short_diff", "sp_ra_long_diff", "sp_ra_momentum_diff",
    "sp_fi_ra_combined",
]

enriched_lookup = enriched.set_index(["home_team", "away_team", "date"])


def get_series_features(series: Series) -> dict | None:
    """Get features for game 1 of a series."""
    g1 = series.games[0]
    key = (g1.home_team, g1.away_team, g1.date)
    if key in enriched_lookup.index:
        row = enriched_lookup.loc[key]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        return {col: row.get(col, np.nan) for col in feature_cols}
    return None


# ── Filtered dogon with pitcher features ─────────────────────────────────


def run_filtered_dogon(
    series_list: list[Series],
    # Team filters
    min_rpi_diff: float = 0.0,
    min_rpi_min: float = 0.0,
    min_wp_diff: float = 0.0,
    min_streak_fav: int | None = None,
    min_games_played: int = 20,
    # Pitcher filters
    max_sp_ra_long_diff: float | None = None,    # home_sp_ra - away_sp_ra (lower = home better)
    min_sp_wr_long_diff: float | None = None,    # home_sp_wr - away_sp_wr (higher = home better)
    min_sp_wr_momentum_diff: float | None = None, # momentum oscillator diff
    max_sp_fi_combined: float | None = None,       # first inning RA combined (for NRFI)
    min_sp_starts: int | None = None,              # min starts for both pitchers
    # Bet params
    target_profit: float = 100.0,
    max_games: int = 2,
) -> tuple[list[SeriesResult], pd.DataFrame]:
    """Run dogon with team + pitcher feature-based filtering."""
    results = []
    skipped = {
        "colorado": 0, "september": 0, "no_features": 0,
        "no_favorite": 0, "games_played": 0,
        "rpi_diff": 0, "rpi_min": 0, "wp_diff": 0, "streak": 0,
        "sp_ra_diff": 0, "sp_wr_diff": 0, "sp_momentum": 0,
        "sp_fi": 0, "sp_starts": 0, "no_pitcher_data": 0,
    }

    for series in series_list:
        if "COL" in (series.home_team, series.away_team):
            skipped["colorado"] += 1
            continue
        if series.games and pd.Timestamp(series.games[0].date).month == 9:
            skipped["september"] += 1
            continue

        feats = get_series_features(series)
        if feats is None:
            skipped["no_features"] += 1
            continue

        if feats.get("games_played_min", 0) < min_games_played:
            skipped["games_played"] += 1
            continue

        pick = select_series_favorite(series, method="game1_odds")
        if pick is None:
            skipped["no_favorite"] += 1
            continue

        favorite, underdog = pick

        # Determine favorite's perspective for features
        g1 = series.games[0]
        fav_is_home = favorite == g1.home_team

        if fav_is_home:
            rpi_diff = feats.get("rpi_diff", 0)
            fav_rpi = feats.get("rpi_home", 0.5)
            dog_rpi = feats.get("rpi_away", 0.5)
            fav_wp = feats.get("wp_home", 0.5)
            dog_wp = feats.get("wp_away", 0.5)
            fav_streak = feats.get("streak_home", 0)
            # Pitcher diffs are already home-away, favorable for home
            sp_ra_diff = feats.get("sp_ra_long_diff", np.nan)
            sp_wr_diff = feats.get("sp_wr_long_diff", np.nan)
            sp_mom_diff = feats.get("sp_wr_momentum_diff", np.nan)
        else:
            rpi_diff = -(feats.get("rpi_diff", 0))
            fav_rpi = feats.get("rpi_away", 0.5)
            dog_rpi = feats.get("rpi_home", 0.5)
            fav_wp = feats.get("wp_away", 0.5)
            dog_wp = feats.get("wp_home", 0.5)
            fav_streak = feats.get("streak_away", 0)
            # Flip pitcher diffs: away fav means negative is good
            sp_ra_diff = -(feats.get("sp_ra_long_diff", np.nan))
            sp_wr_diff = -(feats.get("sp_wr_long_diff", np.nan))
            sp_mom_diff = -(feats.get("sp_wr_momentum_diff", np.nan))

        # Team filters
        if rpi_diff < min_rpi_diff:
            skipped["rpi_diff"] += 1
            continue
        rpi_min_val = min(fav_rpi, dog_rpi)
        if rpi_min_val < min_rpi_min:
            skipped["rpi_min"] += 1
            continue
        wp_diff = fav_wp - dog_wp
        if wp_diff < min_wp_diff:
            skipped["wp_diff"] += 1
            continue
        if min_streak_fav is not None and fav_streak < min_streak_fav:
            skipped["streak"] += 1
            continue

        # Pitcher filters (skip if no pitcher data)
        has_pitcher_data = not (np.isnan(sp_ra_diff) if isinstance(sp_ra_diff, float) else False)
        pitcher_filter_active = any(x is not None for x in [
            max_sp_ra_long_diff, min_sp_wr_long_diff,
            min_sp_wr_momentum_diff, max_sp_fi_combined, min_sp_starts,
        ])

        if pitcher_filter_active and not has_pitcher_data:
            skipped["no_pitcher_data"] += 1
            continue

        if has_pitcher_data:
            # SP RA diff: favorite pitcher should have lower RA (negative diff = fav better)
            if max_sp_ra_long_diff is not None and sp_ra_diff > max_sp_ra_long_diff:
                skipped["sp_ra_diff"] += 1
                continue
            # SP WR diff: favorite pitcher should have higher WR
            if min_sp_wr_long_diff is not None and sp_wr_diff < min_sp_wr_long_diff:
                skipped["sp_wr_diff"] += 1
                continue
            # Momentum: favorite pitcher should be trending better
            if min_sp_wr_momentum_diff is not None:
                if np.isnan(sp_mom_diff) or sp_mom_diff < min_sp_wr_momentum_diff:
                    skipped["sp_momentum"] += 1
                    continue
            # First inning combined RA
            sp_fi = feats.get("sp_fi_ra_combined", np.nan)
            if max_sp_fi_combined is not None:
                if np.isnan(sp_fi) or sp_fi > max_sp_fi_combined:
                    skipped["sp_fi"] += 1
                    continue
            # Min starts (experience)
            if min_sp_starts is not None:
                home_starts = feats.get("home_sp_starts", 0) or 0
                away_starts = feats.get("away_sp_starts", 0) or 0
                if min(home_starts, away_starts) < min_sp_starts:
                    skipped["sp_starts"] += 1
                    continue

        result = run_series_dogon(series, favorite, target_profit, max_games)
        results.append(result)

    summary = build_backtest_summary(results)
    return results, summary


def report(name: str, results, summary):
    """Print compact report."""
    if summary.empty:
        print(f"  {name}: 0 series (all filtered out)")
        return
    n = len(summary)
    wr = summary["won"].mean()
    pnl = summary["total_pnl"].sum()
    staked = summary["total_stake"].sum()
    roi = pnl / staked if staked > 0 else 0
    max_exp = summary["max_exposure"].max()
    print(f"  {name:<55} {n:>5} ser, {wr:>5.1%} WR, "
          f"P&L ${pnl:>+8,.0f}, ROI {roi:>+6.2%}, Max$ {max_exp:>6,.0f}")


# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("BASELINE: Team features only (from previous session)")
print("=" * 70)

for rpi_t in [0.00, 0.02, 0.03, 0.05]:
    r, s = run_filtered_dogon(all_series, min_rpi_diff=rpi_t)
    report(f"RPI>={rpi_t:.2f} (team only)", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 1: Pitcher RA filter alone")
print("=" * 70)

for ra_max in [0.0, -0.5, -1.0, -1.5, -2.0]:
    r, s = run_filtered_dogon(all_series, max_sp_ra_long_diff=ra_max)
    report(f"Fav SP RA advantage <= {ra_max:.1f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 2: Pitcher WR filter alone")
print("=" * 70)

for wr_min in [0.0, 0.05, 0.10, 0.15, 0.20]:
    r, s = run_filtered_dogon(all_series, min_sp_wr_long_diff=wr_min)
    report(f"Fav SP WR advantage >= {wr_min:.2f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 3: RPI + Pitcher RA combined")
print("=" * 70)

combos_rpi_ra = [
    (0.02, 0.0),
    (0.02, -0.5),
    (0.02, -1.0),
    (0.03, 0.0),
    (0.03, -0.5),
    (0.03, -1.0),
    (0.05, 0.0),
    (0.05, -1.0),
]
for rpi_t, ra_max in combos_rpi_ra:
    r, s = run_filtered_dogon(all_series, min_rpi_diff=rpi_t, max_sp_ra_long_diff=ra_max)
    report(f"RPI>={rpi_t:.2f} + SP_RA<={ra_max:.1f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 4: RPI + Pitcher WR combined")
print("=" * 70)

combos_rpi_wr = [
    (0.02, 0.05),
    (0.02, 0.10),
    (0.02, 0.15),
    (0.03, 0.05),
    (0.03, 0.10),
    (0.05, 0.10),
]
for rpi_t, wr_min in combos_rpi_wr:
    r, s = run_filtered_dogon(all_series, min_rpi_diff=rpi_t, min_sp_wr_long_diff=wr_min)
    report(f"RPI>={rpi_t:.2f} + SP_WR>={wr_min:.2f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 5: Triple filter (RPI + Pitcher RA + Pitcher WR)")
print("=" * 70)

triple_combos = [
    {"min_rpi_diff": 0.02, "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.05},
    {"min_rpi_diff": 0.02, "max_sp_ra_long_diff": -0.5, "min_sp_wr_long_diff": 0.05},
    {"min_rpi_diff": 0.02, "max_sp_ra_long_diff": -1.0, "min_sp_wr_long_diff": 0.10},
    {"min_rpi_diff": 0.03, "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.05},
    {"min_rpi_diff": 0.03, "max_sp_ra_long_diff": -0.5, "min_sp_wr_long_diff": 0.10},
    {"min_rpi_diff": 0.03, "max_sp_ra_long_diff": -1.0, "min_sp_wr_long_diff": 0.05},
]
for combo in triple_combos:
    r, s = run_filtered_dogon(all_series, **combo)
    desc = f"RPI>={combo['min_rpi_diff']:.2f} + RA<={combo['max_sp_ra_long_diff']:.1f} + WR>={combo['min_sp_wr_long_diff']:.2f}"
    report(desc, r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 6: Momentum oscillator")
print("=" * 70)

for mom_min in [-0.1, 0.0, 0.05, 0.10, 0.15]:
    r, s = run_filtered_dogon(all_series, min_sp_wr_momentum_diff=mom_min)
    report(f"SP momentum diff >= {mom_min:.2f}", r, s)

# Combined with RPI
for mom_min in [0.0, 0.05, 0.10]:
    r, s = run_filtered_dogon(all_series, min_rpi_diff=0.02, min_sp_wr_momentum_diff=mom_min)
    report(f"RPI>=0.02 + momentum>={mom_min:.2f}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 7: Experience filter (min starts)")
print("=" * 70)

for starts_min in [10, 20, 30, 50]:
    r, s = run_filtered_dogon(all_series, min_sp_starts=starts_min)
    report(f"Both SP >= {starts_min} starts", r, s)

# Combined with RPI
for starts_min in [20, 30]:
    r, s = run_filtered_dogon(all_series, min_rpi_diff=0.02, min_sp_starts=starts_min)
    report(f"RPI>=0.02 + starts>={starts_min}", r, s)

# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("TEST 8: Kitchen sink — best team + best pitcher combos")
print("=" * 70)

kitchen_combos = [
    {
        "min_rpi_diff": 0.02, "min_wp_diff": 0.05,
        "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.05,
    },
    {
        "min_rpi_diff": 0.02, "min_wp_diff": 0.05,
        "max_sp_ra_long_diff": -0.5, "min_sp_wr_long_diff": 0.05,
        "min_sp_starts": 20,
    },
    {
        "min_rpi_diff": 0.03, "min_wp_diff": 0.05,
        "max_sp_ra_long_diff": 0.0, "min_sp_wr_long_diff": 0.10,
    },
    {
        "min_rpi_diff": 0.02, "min_streak_fav": 1,
        "max_sp_ra_long_diff": -0.5, "min_sp_wr_long_diff": 0.05,
    },
    {
        "min_rpi_diff": 0.03, "min_wp_diff": 0.10,
        "max_sp_ra_long_diff": -0.5,
    },
    {
        "min_rpi_diff": 0.02, "min_wp_diff": 0.05,
        "max_sp_ra_long_diff": -1.0,
        "min_sp_wr_momentum_diff": 0.0,
    },
]

for combo in kitchen_combos:
    r, s = run_filtered_dogon(all_series, **combo)
    parts = []
    if "min_rpi_diff" in combo:
        parts.append(f"RPI>={combo['min_rpi_diff']:.2f}")
    if "min_wp_diff" in combo:
        parts.append(f"WP>={combo['min_wp_diff']:.2f}")
    if "min_streak_fav" in combo:
        parts.append(f"Str>={combo['min_streak_fav']}")
    if "max_sp_ra_long_diff" in combo:
        parts.append(f"RA<={combo['max_sp_ra_long_diff']:.1f}")
    if "min_sp_wr_long_diff" in combo:
        parts.append(f"WR>={combo['min_sp_wr_long_diff']:.2f}")
    if "min_sp_wr_momentum_diff" in combo:
        parts.append(f"Mom>={combo['min_sp_wr_momentum_diff']:.2f}")
    if "min_sp_starts" in combo:
        parts.append(f"St>={combo['min_sp_starts']}")
    desc = " + ".join(parts)
    report(desc, r, s)

# ══════════════════════════════════════════════════════════════════════════
# DETAILED REPORT for best config
# ══════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("DETAILED: Most promising config")
print("=" * 70)

# Run a promising-looking combo
best_r, best_s = run_filtered_dogon(
    all_series,
    min_rpi_diff=0.02,
    min_wp_diff=0.05,
    max_sp_ra_long_diff=0.0,
    min_sp_wr_long_diff=0.05,
)
print_backtest_report(best_r, best_s)
