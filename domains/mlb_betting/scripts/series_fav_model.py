"""Favorite series dogon with model signals.

Three filter layers:
  1. Odds-based: G1 fav odds >= 1.50, odds bands
  2. Feature-based: RPI, Elo, pitcher, form (G1 only)
  3. Model-based: edge_consensus, m4_edge, div_std (G1 only)

All decisions use ONLY G1 data. G2 pitcher/odds unknown at decision time.

Usage:
    python scripts/series_fav_model.py
"""

import sys
import warnings
import logging
from pathlib import Path
from itertools import combinations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)

import numpy as np
import pandas as pd
from src.series import identify_series, run_series_dogon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def breakeven_wr(avg_g1_odds, avg_g2_odds=None):
    """Compute breakeven series WR for 2-game dogon."""
    k1 = avg_g1_odds - 1
    stake_g1 = 100 / k1
    if avg_g2_odds is None:
        avg_g2_odds = avg_g1_odds  # assume same
    k2 = avg_g2_odds - 1
    stake_g2 = (100 + stake_g1) / k2
    total_loss = stake_g1 + stake_g2
    return total_loss / (total_loss + 100)


def eval_series(results, name):
    """Evaluate a list of SeriesResult."""
    n = len(results)
    if n < 10:
        return None
    won = sum(1 for r in results if r.won)
    wr = won / n
    total_pnl = sum(r.total_pnl for r in results)
    total_stake = sum(r.total_stake for r in results)
    roi = total_pnl / total_stake * 100 if total_stake > 0 else 0

    # Per-season
    by_season = {}
    for r in results:
        by_season.setdefault(r.season, []).append(r)
    season_rois = []
    for s in sorted(by_season):
        sr = by_season[s]
        sp = sum(r.total_pnl for r in sr)
        ss = sum(r.total_stake for r in sr)
        season_rois.append(sp / ss * 100 if ss > 0 else 0)
    n_pos = sum(1 for r in season_rois if r > 0)

    # Drawdown
    cum_pnl = np.cumsum([r.total_pnl for r in results])
    peak = np.maximum.accumulate(cum_pnl)
    dd = peak - cum_pnl
    max_dd = dd.max()

    # Max loss streak
    ml = mc = 0
    for r in results:
        if not r.won:
            mc += 1
            ml = max(ml, mc)
        else:
            mc = 0

    # Sharpe (per-series)
    pnls = [r.total_pnl for r in results]
    ev = np.mean(pnls)
    std = np.std(pnls, ddof=1)
    bps = n / len(by_season) if by_season else n
    sharpe = (ev / std * np.sqrt(bps)) if std > 0 else 0

    # Avg G1 odds
    g1_odds_list = []
    for r in results:
        if r.bets:
            g1_odds_list.append(r.bets[0].decimal_odds)
    avg_g1_odds = np.mean(g1_odds_list) if g1_odds_list else 1.65

    # Breakeven
    be = breakeven_wr(avg_g1_odds)
    gap = (wr - be) * 100

    return {
        "filter": name, "series": n, "sps": n / len(by_season),
        "wr": wr, "roi": roi, "total_pnl": total_pnl,
        "max_dd": max_dd, "max_ls": ml, "sharpe": sharpe,
        "avg_g1_odds": avg_g1_odds, "be_wr": be, "gap_pp": gap,
        "folds_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def ptable(results, title):
    print(f"\n{'='*130}")
    print(title)
    print(f"{'='*130}")
    h = (f"{'Filter':<55} {'Ser':>4} {'S/S':>4} {'WR':>6} {'BE':>6} {'Gap':>6} "
         f"{'ROI':>7} {'PnL':>8} {'MaxDD':>7} {'ML':>3} {'Shrp':>6} {'Flds':>6}")
    print(h)
    print("-" * 130)
    for r in results:
        if r is None:
            continue
        print(
            f"  {r['filter']:<53} {r['series']:4d} {r['sps']:4.0f} "
            f"{r['wr']*100:5.1f}% {r['be_wr']*100:5.1f}% {r['gap_pp']:+5.1f}p "
            f"{r['roi']:+6.1f}% {r['total_pnl']:+7.0f} {r['max_dd']:6.0f} "
            f"{r['max_ls']:3d} {r['sharpe']:5.3f} {r['folds_pos']:>6}"
        )


# ---------------------------------------------------------------------------
# Data pipeline
# ---------------------------------------------------------------------------

def build_dataset():
    """Build full dataset with model predictions + features."""
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward
    from src.data_loader import load_all_seasons, apply_data_filters, add_derived_odds

    print("Building spec features...")
    full = build_spec_features()

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()
    print("Running walk-forward...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    # Merge
    mk = ["season", "date", "home_team", "away_team"]
    keep = [c for c in full.columns if c not in div.columns or c in mk]
    fs = full[keep].drop_duplicates(subset=mk)
    df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")

    # Derived
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0
    df["fav_decimal"] = np.where(
        df["fav_is_home"], df["home_decimal_odds"], df["away_decimal_odds"]
    )
    if "pred_M4" in df.columns and "pred_M0" in df.columns:
        df["m4_edge"] = df["closing_decimal_odds_favorite"] - df["pred_M4"]
    if "pred_M3" in df.columns and "pred_M4" in df.columns and "pred_M0" in df.columns and "pred_M2" in df.columns:
        df["m34_vs_m02"] = (df["pred_M3"] + df["pred_M4"]) / 2 - (df["pred_M0"] + df["pred_M2"]) / 2

    # Load raw games for series identification
    print("Loading raw games for series...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    print(f"Predictions: {len(df)} games, Raw games: {len(games)}")
    return df, games


# ---------------------------------------------------------------------------
# Core: run series dogon with model pre-filter
# ---------------------------------------------------------------------------

def run_filtered_series_dogon(
    games, all_series, pred_lookup, filters, target_profit=100.0
):
    """Run series dogon with pre-filter on G1 predictions.

    Args:
        games: raw games DataFrame
        all_series: list of Series from identify_series
        pred_lookup: DataFrame indexed by (season, date, home_team, away_team)
        filters: dict of filter_name -> callable(g1_pred_row) -> bool
        target_profit: dogon target

    Returns:
        list of SeriesResult
    """
    results = []
    skipped = {"colorado": 0, "no_pred": 0, "odds_low": 0, "filter": 0}

    for series in all_series:
        if series.length < 2:
            continue

        # Colorado exclusion
        if "COL" in (series.home_team, series.away_team):
            skipped["colorado"] += 1
            continue

        g1 = series.games[0]

        # Determine favorite by G1 odds
        if g1.home_implied_prob > g1.away_implied_prob:
            favorite = g1.home_team
            fav_odds = g1.home_decimal_odds
            fav_prob = g1.home_implied_prob
        else:
            favorite = g1.away_team
            fav_odds = g1.away_decimal_odds
            fav_prob = g1.away_implied_prob

        # Hard filter: skip extreme favorites (odds < 1.50)
        if fav_odds < 1.50:
            skipped["odds_low"] += 1
            continue

        # Lookup G1 prediction
        key = (series.season, g1.date, g1.home_team, g1.away_team)
        try:
            g1_pred = pred_lookup.loc[key]
            if isinstance(g1_pred, pd.DataFrame):
                g1_pred = g1_pred.iloc[0]
        except KeyError:
            skipped["no_pred"] += 1
            continue

        # Apply all filters on G1 data
        passed = True
        for fname, ffunc in filters.items():
            try:
                if not ffunc(g1_pred, favorite):
                    passed = False
                    break
            except (KeyError, TypeError):
                passed = False
                break
        if not passed:
            skipped["filter"] += 1
            continue

        # Run dogon
        result = run_series_dogon(series, favorite, target_profit, max_games=2)
        results.append(result)

    return results


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def table1_baseline(games, all_series, pred_lookup):
    """Table 1: Baseline — odds bands only, no model."""
    print(f"\n{'#'*80}")
    print("TABLE 1: BASELINE (odds bands, no model filters)")
    print(f"{'#'*80}")

    configs = [
        ("All >= 1.50", {}),
        ("Odds 1.50-1.65", {"max_fav_odds": 1.65}),
        ("Odds 1.50-1.80", {"max_fav_odds": 1.80}),
        ("Odds 1.50-1.90", {"max_fav_odds": 1.90}),
        ("Odds 1.50-2.00", {"max_fav_odds": 2.00}),
        ("Odds 1.65-1.90", {"min_fav_odds": 1.65, "max_fav_odds": 1.90}),
        ("Odds 1.65-2.00", {"min_fav_odds": 1.65, "max_fav_odds": 2.00}),
        ("Odds 1.80-2.20", {"min_fav_odds": 1.80, "max_fav_odds": 2.20}),
    ]

    results = []
    for name, params in configs:
        min_o = params.get("min_fav_odds", 1.50)
        max_o = params.get("max_fav_odds", 99.0)
        filters = {
            "odds_band": lambda row, fav, _min=min_o, _max=max_o: (
                _min <= (row.get("home_decimal_odds") if row.get("fav_is_home") else row.get("away_decimal_odds", 1.5)) <= _max
                if True else True
            ),
        }
        # Simpler: use fav_decimal
        filters = {
            "odds_band": lambda row, fav, _min=min_o, _max=max_o: _min <= row.get("fav_decimal", 1.6) <= _max,
        }
        res = run_filtered_series_dogon(games, all_series, pred_lookup, filters)
        r = eval_series(res, name)
        if r:
            results.append(r)

    ptable(results, "ODDS BAND ANALYSIS")
    return results


def table2_features(games, all_series, pred_lookup, best_odds_band=None):
    """Table 2: Feature filters on top of baseline."""
    print(f"\n{'#'*80}")
    print("TABLE 2: FEATURE FILTERS (G1 data only)")
    print(f"{'#'*80}")

    # Always apply odds >= 1.50 (hard filter in run_filtered already)
    feature_filters = {}

    # RPI
    for t in [0.01, 0.02, 0.03]:
        feature_filters[f"rpi_diff >= {t}"] = {
            "f": lambda row, fav, _t=t: row.get("rpi_diff", 0) >= _t if row.get("fav_is_home") else row.get("rpi_diff", 0) <= -_t,
        }

    # Elo
    for t in [-10, -20, -30]:
        feature_filters[f"elo_diff <= {t}"] = {
            "f": lambda row, fav, _t=t: row.get("elo_diff", 0) <= _t if row.get("fav_is_home") else row.get("elo_diff", 0) >= -_t,
        }

    # Pitcher FIP
    if True:
        feature_filters["starter_fip_diff < 0 (fav better)"] = {
            "f": lambda row, fav: (row.get("starter_fip_diff", 0) < 0) if row.get("fav_is_home") else (row.get("starter_fip_diff", 0) > 0),
        }

    # Form
    feature_filters["wp_last6_fav >= 0.50"] = {
        "f": lambda row, fav: (row.get("wp_last6_home", 0.5) >= 0.50) if row.get("fav_is_home") else (row.get("wp_last6_away", 0.5) >= 0.50),
    }
    feature_filters["wp_last6_fav >= 0.60"] = {
        "f": lambda row, fav: (row.get("wp_last6_home", 0.5) >= 0.60) if row.get("fav_is_home") else (row.get("wp_last6_away", 0.5) >= 0.60),
    }

    # Pyth
    feature_filters["pyth_wp_diff >= 0.03 (fav)"] = {
        "f": lambda row, fav: (row.get("pyth_wp_diff", 0) >= 0.03) if row.get("fav_is_home") else (row.get("pyth_wp_diff", 0) <= -0.03),
    }

    # GP filter (skip early season)
    feature_filters["games_played >= 30"] = {
        "f": lambda row, fav: row.get("games_played_min", 0) >= 30,
    }

    results = []
    # Baseline (no feature filter)
    base_res = run_filtered_series_dogon(games, all_series, pred_lookup, {})
    r = eval_series(base_res, "No feature filter (baseline)")
    if r:
        results.append(r)

    for name, cfg in feature_filters.items():
        filters = {name: cfg["f"]}
        res = run_filtered_series_dogon(games, all_series, pred_lookup, filters)
        r = eval_series(res, name)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["gap_pp"])
    ptable(results, "SINGLE FEATURE FILTERS")

    # Top combos
    top_names = [r["filter"] for r in results
                 if r["gap_pp"] > 0 and r["filter"] != "No feature filter (baseline)"][:8]
    if len(top_names) >= 2:
        combo_results = []
        for f1, f2 in combinations(top_names, 2):
            filters = {
                f1: feature_filters[f1]["f"],
                f2: feature_filters[f2]["f"],
            }
            res = run_filtered_series_dogon(games, all_series, pred_lookup, filters)
            r = eval_series(res, f"{f1} + {f2}")
            if r:
                combo_results.append(r)
        combo_results.sort(key=lambda x: -x["gap_pp"])
        ptable(combo_results[:15], "FEATURE COMBOS")

    return results


def table3_model(games, all_series, pred_lookup):
    """Table 3: Model filters."""
    print(f"\n{'#'*80}")
    print("TABLE 3: MODEL FILTERS (G1 predictions only)")
    print(f"{'#'*80}")

    model_filters = {}

    # Edge consensus
    for t in [-0.03, -0.05, -0.07, -0.10]:
        model_filters[f"edge < {t}"] = lambda row, fav, _t=t: row.get("edge_consensus", 0) < _t

    # m4_edge (upset model confirms)
    model_filters["m4_edge < 0"] = lambda row, fav: row.get("m4_edge", 0) < 0
    model_filters["m4_edge < -0.05"] = lambda row, fav: row.get("m4_edge", 0) < -0.05

    # div_std (model agreement)
    model_filters["div_std < 0.012"] = lambda row, fav: row.get("div_std", 0.02) < 0.012
    model_filters["div_std < 0.008"] = lambda row, fav: row.get("div_std", 0.02) < 0.008

    # m34_vs_m02 (dominant models stronger)
    model_filters["m34_vs_m02 < 0"] = lambda row, fav: row.get("m34_vs_m02", 0) < 0

    results = []
    # Baseline
    base_res = run_filtered_series_dogon(games, all_series, pred_lookup, {})
    r = eval_series(base_res, "No model filter (baseline)")
    if r:
        results.append(r)

    for name, ffunc in model_filters.items():
        filters = {name: ffunc}
        res = run_filtered_series_dogon(games, all_series, pred_lookup, filters)
        r = eval_series(res, name)
        if r:
            results.append(r)

    results.sort(key=lambda x: -x["gap_pp"])
    ptable(results, "SINGLE MODEL FILTERS")

    # Combos
    top_names = [r["filter"] for r in results
                 if r["gap_pp"] > 0 and r["filter"] != "No model filter (baseline)"][:6]
    if len(top_names) >= 2:
        combo_results = []
        for f1, f2 in combinations(top_names, 2):
            filters = {f1: model_filters[f1], f2: model_filters[f2]}
            res = run_filtered_series_dogon(games, all_series, pred_lookup, filters)
            r = eval_series(res, f"{f1} + {f2}")
            if r:
                combo_results.append(r)
        combo_results.sort(key=lambda x: -x["gap_pp"])
        ptable(combo_results[:15], "MODEL COMBOS")

    return results


def table4_three_layer(games, all_series, pred_lookup, feature_filters_map, model_filters_map):
    """Table 4: Three-layer combos (odds + feature + model)."""
    print(f"\n{'#'*80}")
    print("TABLE 4: THREE-LAYER COMBOS (feature + model)")
    print(f"{'#'*80}")

    # Hardcode top feature + model candidates
    feat_candidates = {
        "rpi>=0.02": lambda row, fav: (row.get("rpi_diff", 0) >= 0.02) if row.get("fav_is_home") else (row.get("rpi_diff", 0) <= -0.02),
        "rpi>=0.01": lambda row, fav: (row.get("rpi_diff", 0) >= 0.01) if row.get("fav_is_home") else (row.get("rpi_diff", 0) <= -0.01),
        "elo<=-10": lambda row, fav: (row.get("elo_diff", 0) <= -10) if row.get("fav_is_home") else (row.get("elo_diff", 0) >= 10),
        "fip<0": lambda row, fav: (row.get("starter_fip_diff", 0) < 0) if row.get("fav_is_home") else (row.get("starter_fip_diff", 0) > 0),
        "pyth>=0.03": lambda row, fav: (row.get("pyth_wp_diff", 0) >= 0.03) if row.get("fav_is_home") else (row.get("pyth_wp_diff", 0) <= -0.03),
        "wp6>=0.50": lambda row, fav: (row.get("wp_last6_home", 0.5) >= 0.50) if row.get("fav_is_home") else (row.get("wp_last6_away", 0.5) >= 0.50),
    }
    model_candidates = {
        "edge<-0.03": lambda row, fav: row.get("edge_consensus", 0) < -0.03,
        "edge<-0.05": lambda row, fav: row.get("edge_consensus", 0) < -0.05,
        "m4<0": lambda row, fav: row.get("m4_edge", 0) < 0,
        "div<0.012": lambda row, fav: row.get("div_std", 0.02) < 0.012,
        "m34<0": lambda row, fav: row.get("m34_vs_m02", 0) < 0,
    }

    results = []
    for fn, ff in feat_candidates.items():
        for mn, mf in model_candidates.items():
            filters = {fn: ff, mn: mf}
            res = run_filtered_series_dogon(games, all_series, pred_lookup, filters)
            r = eval_series(res, f"{fn} + {mn}")
            if r:
                results.append(r)

    results.sort(key=lambda x: -x["gap_pp"])
    ptable(results[:25], "THREE-LAYER COMBOS (top 25)")

    return results


def table5_summary(all_results):
    """Table 5: Best strategies summary."""
    print(f"\n{'#'*80}")
    print("TABLE 5: BEST STRATEGIES SUMMARY")
    print(f"{'#'*80}")

    # Viable: positive gap, >= 30 series, 4+ seasons profitable
    viable = []
    for r in all_results:
        if r is None:
            continue
        if r["gap_pp"] > 0 and r["series"] >= 30:
            folds = r["folds_pos"].split("/")
            if len(folds) == 2 and int(folds[0]) >= 4:
                viable.append(r)

    viable.sort(key=lambda x: -x["sharpe"])
    ptable(viable[:10], "VIABLE STRATEGIES (gap>0, series>=30, folds>=4)")

    if viable:
        best = viable[0]
        rois_str = ", ".join(f"{x:+.0f}" for x in best["season_rois"])
        print(f"\n  BEST: {best['filter']}")
        print(f"    {best['series']} series ({best['sps']:.0f}/s)  WR {best['wr']*100:.1f}%  BE {best['be_wr']*100:.1f}%  Gap {best['gap_pp']:+.1f}pp")
        print(f"    ROI {best['roi']:+.1f}%  Sharpe {best['sharpe']:.3f}  MaxDD ${best['max_dd']:.0f}")
        print(f"    Seasons: [{rois_str}]")

    print(f"\n  Portfolio context:")
    print(f"    S3-dual (away underdog): ~44 bets/season, +17.9% ROI, Sharpe 0.98")
    if viable:
        print(f"    Fav series dogon: ~{viable[0]['sps']:.0f} series/season, {viable[0]['roi']:+.1f}% ROI, Sharpe {viable[0]['sharpe']:.3f}")

    return viable


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df, games = build_dataset()

    # Build prediction lookup from G1 data only
    mk = ["season", "date", "home_team", "away_team"]
    pred_lookup = df.set_index(mk)
    # Remove duplicates from index
    pred_lookup = pred_lookup[~pred_lookup.index.duplicated(keep="first")]

    # Identify series
    all_series = identify_series(games)
    print(f"Total series: {len(all_series)}")

    # Run all tables
    r1 = table1_baseline(games, all_series, pred_lookup)
    r2 = table2_features(games, all_series, pred_lookup)
    r3 = table3_model(games, all_series, pred_lookup)
    r4 = table4_three_layer(games, all_series, pred_lookup, {}, {})

    all_results = r1 + r2 + r3 + r4
    table5_summary(all_results)


if __name__ == "__main__":
    main()
