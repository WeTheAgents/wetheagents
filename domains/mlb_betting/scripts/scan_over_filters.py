"""OVER Filter Grid — Session 33b.

Full grid search: single-feature and multi-feature OVER filters applied to walk-forward
CatBoost predictions joined with all game-card features.

Two populations analyzed in parallel:
  - all_games: all 27K+ walk-forward predictions
  - grey_zone: p_under in [0.47, 0.52) — CatBoost borderline zone

Sections:
  1. Single-filter grid (A: pitcher, B: bullpen, C: offense, D: matchup, E: market, F: context)
  2. Top two-feature combos (from best single filters)
  3. Three-feature combos (top pairs + one more dimension)
  4. Outlier stress on all candidates (N>=100, over%>=54%)
  5. Era split on survivors (pre-2021 vs 2021+)
  6. Summary: top-20 cells with flags

Usage:
    python scripts/scan_over_filters.py
    python scripts/scan_over_filters.py --quick   # single filters only, no combos
    python scripts/scan_over_filters.py --min-n 50 --min-over 53.0
"""

import argparse
import logging
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

from src.data_loader import add_derived_odds, apply_data_filters, load_all_seasons
from src.features import OU_FEATURES, build_all_features, build_ou_features
from src.model import UnderModelConfig, predict_under_proba, train_under_model, walk_forward_splits

ODDS_OVER = 1.909
BREAKEVEN = 100 / ODDS_OVER  # 52.38%
LG_AVG = 8.87
GREY_LO, GREY_HI = 0.47, 0.52


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def roi_stats(sub: pd.DataFrame) -> tuple[int, float, float]:
    sub = sub[~sub["is_push"]] if "is_push" in sub.columns else sub
    n = len(sub)
    if n == 0:
        return 0, 0.0, 0.0
    hit = float(sub["over_hit"].mean() * 100)
    pnl = float(np.where(sub["over_hit"].astype(bool), ODDS_OVER - 1, -1).mean() * 100)
    return n, hit, pnl


def trim_stress(sub: pd.DataFrame, pct: int) -> tuple[float, float]:
    """Drop top pct% highest-scoring games, return (over%, ROI)."""
    s = sub.sort_values("total_runs", ascending=True)
    k = int(len(s) * pct / 100)
    keep = s.iloc[: len(s) - k]
    _, h, r = roi_stats(keep)
    return h, r


def section(title: str):
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")


def fmt_cell(n: int, h: float, r: float, min_n: int) -> str:
    if n < min_n:
        return f"N={n:>4} (few)"
    mark = " *" if h >= BREAKEVEN else ""
    return f"N={n:>5} {h:>5.1f}%/{r:>+5.1f}%{mark}"


# ─────────────────────────────────────────────────────────────────────────────
# Step 0: Build predictions + join features
# ─────────────────────────────────────────────────────────────────────────────

def build_preds_with_features() -> pd.DataFrame:
    logger.info("Loading all seasons...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)

    logger.info("Building features...")
    enriched = build_all_features(games)
    ou = build_ou_features(enriched=enriched)

    feats = [f for f in OU_FEATURES if f in ou.columns and ou[f].notna().mean() > 0.3]
    cfg = UnderModelConfig()
    all_seasons = sorted(ou["season"].unique().tolist())
    folds = walk_forward_splits(all_seasons, min_train=5, max_train=cfg.max_train_seasons, test_size=1)
    push_mask = ou["is_push"] if "is_push" in ou.columns else pd.Series(False, index=ou.index)

    all_preds = []
    for i, (train_s, val_s, test_s) in enumerate(folds):
        logger.info(f"  fold {i}: test={test_s}")
        cb, lr, cal, metrics = train_under_model(ou, feats, train_s, val_s, cfg=cfg)
        test_mask = ou["season"].isin(test_s) & ~push_mask
        if test_mask.sum() < 10:
            continue
        X_test = ou.loc[test_mask, feats].values.astype(float)
        p_under = predict_under_proba(X_test, cb, lr, cal, metrics["train_medians"], cfg=cfg)
        meta = ["season", "date", "home_team", "away_team", "close_ou",
                "total_runs", "under_hit", "over_hit", "is_push"]
        avail = [c for c in meta if c in ou.columns]
        pdf = ou.loc[test_mask, avail].copy()
        pdf["p_under"] = p_under
        all_preds.append(pdf)

    preds = pd.concat(all_preds, ignore_index=True)
    logger.info(f"Predictions: {len(preds)} games")

    # Join with all ou feature columns
    keep_cols = [c for c in ou.columns if c not in
                 {"under_hit", "over_hit", "is_push", "total_runs",
                  "close_ou", "ou_regime", "ou_regime_v3"}]
    join_keys = ["season", "date", "home_team", "away_team"]
    ou_cols = join_keys + [c for c in keep_cols if c not in join_keys]

    # Deduplicate ou before join
    ou_dedup = ou[ou_cols].drop_duplicates(subset=join_keys)
    df = preds.merge(ou_dedup, on=join_keys, how="left")
    logger.info(f"After join: {len(df)} rows, {df.shape[1]} columns")

    # Derived features
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["line_below_lg"] = LG_AVG - df["close_ou"]

    for col in ["home_sp_fip_short", "away_sp_fip_short"]:
        if col not in df.columns:
            df[col] = np.nan
    df["max_sp_fip"] = df[["home_sp_fip_short", "away_sp_fip_short"]].max(axis=1)
    df["min_sp_fip"] = df[["home_sp_fip_short", "away_sp_fip_short"]].min(axis=1)

    for col in ["bp_ip_3d_home", "bp_ip_3d_away"]:
        if col not in df.columns:
            df[col] = np.nan
    df["bp_ip_3d_max"] = df[["bp_ip_3d_home", "bp_ip_3d_away"]].max(axis=1)

    # Compute interaction features manually (not in base build_ou_features())
    # matchup_rpg_x_sp_ra: offense × opposing starter RA
    for c in ["rpg_home", "rpg_away", "home_sp_ra_long", "away_sp_ra_long"]:
        if c not in df.columns:
            df[c] = np.nan
    df["matchup_rpg_x_sp_ra"] = (
        df["rpg_home"] * df["away_sp_ra_long"] + df["rpg_away"] * df["home_sp_ra_long"]
    ) / 2.0

    # bp_fip_osc_x_rpg: deteriorating bullpen × opponent offense
    for c in ["bp_fip_7g_home", "bp_fip_long_home", "bp_fip_7g_away", "bp_fip_long_away"]:
        if c not in df.columns:
            df[c] = np.nan
    bp_osc_home = df["bp_fip_7g_home"] - df["bp_fip_long_home"]
    bp_osc_away = df["bp_fip_7g_away"] - df["bp_fip_long_away"]
    df["bp_fip_osc_x_rpg"] = (
        bp_osc_home * df["rpg_away"] + bp_osc_away * df["rpg_home"]
    ) / 2.0

    # power_rate_max_x_sp_floor: explosive team × weakest starter FIP
    for c in ["power_rate_home", "power_rate_away"]:
        if c not in df.columns:
            df[c] = np.nan
    df["power_rate_max"] = df[["power_rate_home", "power_rate_away"]].max(axis=1)
    if "sp_fip_floor_short" not in df.columns:
        df["sp_fip_floor_short"] = df[["home_sp_fip_short", "away_sp_fip_short"]].max(
            axis=1,
            skipna=False,
        )
    df["power_rate_max_x_sp_floor"] = df["power_rate_max"] * df["sp_fip_floor_short"]

    # effective_obp_combined — fix thresholds by checking actual distribution
    # (values are per-team OBP vs pitcher hand, typically 0.30-0.36 per team, combined 0.60-0.72)
    # Re-derive combined from individual if available
    for c in ["effective_obp_home", "effective_obp_away"]:
        if c not in df.columns:
            df[c] = np.nan
    df["effective_obp_combined"] = df["effective_obp_home"] + df["effective_obp_away"]

    logger.info(f"Derived interactions computed. Sample matchup_rpg_x_sp_ra coverage: "
                f"{df['matchup_rpg_x_sp_ra'].notna().mean()*100:.1f}%")
    logger.info(f"effective_obp_combined percentiles: "
                f"p25={df['effective_obp_combined'].quantile(0.25):.3f} "
                f"p50={df['effective_obp_combined'].quantile(0.50):.3f} "
                f"p75={df['effective_obp_combined'].quantile(0.75):.3f}")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Filter grid definition
# ─────────────────────────────────────────────────────────────────────────────

def build_filter_grid() -> list[tuple[str, str, str, object]]:
    """Returns list of (category, label, col, threshold_spec).
    threshold_spec: (op, value) where op in ('>=','<=','==').
    """
    grid = []

    def add(cat: str, col: str, op: str, values: list):
        for v in values:
            label = f"{col} {op} {v}"
            grid.append((cat, label, col, op, v))

    # A: Pitcher vulnerability
    add("A_pitcher", "sp_fip_combined", ">=", [7.0, 7.5, 8.0, 8.5, 9.0, 10.0])
    add("A_pitcher", "sp_fip_floor_short", ">=", [3.5, 3.8, 4.2, 4.5, 5.0, 5.5])
    add("A_pitcher", "max_sp_fip", ">=", [3.5, 3.8, 4.2, 4.5, 5.0])
    add("A_pitcher", "sp_ra_combined_short", ">=", [8.0, 9.0, 10.0, 11.0, 12.0])
    add("A_pitcher", "sp_ip_per_start_combined", "<=", [10.5, 10.0, 9.5, 9.0])

    # B: Bullpen fatigue
    add("B_bullpen", "bullpen_ip_3d_combined", ">=", [16, 18, 20, 22, 25])
    add("B_bullpen", "bp_ip_3d_max", ">=", [8, 9, 10, 11, 12])
    add("B_bullpen", "bp_fip_osc_combined", ">=", [0.0, 0.2, 0.5, 0.8, 1.0])
    add("B_bullpen", "bullpen_fip_7g_combined", ">=", [7.0, 7.5, 8.0, 8.5])

    # C: Offensive firepower
    add("C_offense", "combined_rpg", ">=", [9.0, 9.2, 9.5, 10.0, 10.5])
    add("C_offense", "power_rate_combined", ">=", [0.30, 0.35, 0.40, 0.45])
    add("C_offense", "combined_rpg_last10", ">=", [9.0, 9.5, 10.0, 10.5])
    add("C_offense", "rpg_vs_line", ">=", [0.0, 0.5, 1.0, 1.5, 2.0])

    # D: Matchup interactions
    # effective_obp_combined: per-team ~0.31-0.34, combined ~0.62-0.68
    add("D_matchup", "effective_obp_combined", ">=", [0.60, 0.62, 0.64, 0.66, 0.68, 0.70])
    # matchup_rpg_x_sp_ra: (rpg_home * away_sp_ra + rpg_away * home_sp_ra) / 2 — typical ~9-18
    add("D_matchup", "matchup_rpg_x_sp_ra", ">=", [12, 14, 16, 18, 20, 22])
    # bp_fip_osc_x_rpg: deteriorating bullpen * opponent RPG — can be negative
    add("D_matchup", "bp_fip_osc_x_rpg", ">=", [-1.0, 0.0, 0.5, 1.0, 2.0])
    # power_rate_max_x_sp_floor: max power_rate (~0.20-0.45) * sp_fip_floor_short (FIP ~3-6) => ~0.6-2.7
    add("D_matchup", "power_rate_max_x_sp_floor", ">=", [0.8, 1.0, 1.2, 1.5, 1.8])

    # E: Market
    add("E_market", "close_ou", "<=", [7.5, 8.0, 8.5, 9.0])
    add("E_market", "line_below_lg", ">=", [-0.5, 0.0, 0.3, 0.5, 1.0, 1.5])

    # F: Context
    for m in [4, 5, 6, 7, 8, 9]:
        grid.append(("F_context", f"month == {m}", "month", "==", m))
    for m in [6, 7, 8]:
        grid.append(("F_context", f"month >= {m}", "month", ">=", m))

    return grid


def apply_filter(df: pd.DataFrame, col: str, op: str, val) -> pd.Series:
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    s = df[col]
    if op == ">=":
        return s >= val
    elif op == "<=":
        return s <= val
    elif op == "==":
        return s == val
    return pd.Series(False, index=df.index)


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Single-filter grid
# ─────────────────────────────────────────────────────────────────────────────

def single_filter_grid(df: pd.DataFrame, grid: list, min_n: int) -> list[dict]:
    """Evaluate each filter on all_games and grey_zone. Return all results."""
    grey = df[(df["p_under"] >= GREY_LO) & (df["p_under"] < GREY_HI)]

    results = []
    current_cat = None

    for (cat, label, col, op, val) in grid:
        if cat != current_cat:
            section(f"SECTION 1 [{cat}]: {label.split()[0]} single filters")
            print(f"  {'filter':<52} {'ALL GAMES':^22} {'GREY ZONE':^22}")
            print(f"  {'':<52} {'N / over% / ROI':^22} {'N / over% / ROI':^22}")
            print("  " + "-" * 98)
            current_cat = cat

        mask_all = apply_filter(df, col, op, val) & ~df["is_push"]
        mask_gz = apply_filter(grey, col, op, val) & ~grey["is_push"]

        sub_all = df[mask_all]
        sub_gz = grey[mask_gz]

        n_a, h_a, r_a = roi_stats(sub_all)
        n_g, h_g, r_g = roi_stats(sub_gz)

        cell_a = fmt_cell(n_a, h_a, r_a, min_n)
        cell_g = fmt_cell(n_g, h_g, r_g, min_n // 2)
        print(f"  {label:<52} {cell_a:<22} {cell_g:<22}")

        if n_a >= min_n:
            results.append({
                "cat": cat, "label": label, "col": col, "op": op, "val": val,
                "pop": "all", "n": n_a, "over_pct": h_a, "roi": r_a,
                "mask": mask_all,
            })
        if n_g >= min_n // 2:
            results.append({
                "cat": cat, "label": label, "col": col, "op": op, "val": val,
                "pop": "grey", "n": n_g, "over_pct": h_g, "roi": r_g,
                "mask": mask_gz,
            })

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Section 2: Two-feature combos
# ─────────────────────────────────────────────────────────────────────────────

def two_feature_combos(df: pd.DataFrame, single_results: list,
                       min_n: int, min_over: float) -> list[dict]:
    # Select top candidates from single grid — top-15 by over%, regardless of absolute threshold
    base_all = [r for r in single_results if r["pop"] == "all" and r["n"] >= min_n]
    base_all.sort(key=lambda r: r["over_pct"], reverse=True)
    top = base_all[:15]  # top-15 single filters by over%

    if not top:
        print("  (no single-filter candidates above threshold)")
        return []

    section("SECTION 2: TOP TWO-FEATURE COMBOS")
    print(f"  Base: top {len(top)} single filters with over% >= {min_over:.1f}%")
    print(f"  Showing pairs with N >= {min_n // 2}, over% >= {min_over:.1f}%\n")
    print(f"  {'combo':<72} {'N':>5} {'over%':>7} {'ROI':>8}")
    print("  " + "-" * 96)

    combo_results = []
    grey = df[(df["p_under"] >= GREY_LO) & (df["p_under"] < GREY_HI)]

    seen = set()
    for i, r1 in enumerate(top):
        for r2 in top[i + 1:]:
            # Avoid same column combos
            if r1["col"] == r2["col"]:
                continue
            key = tuple(sorted([r1["label"], r2["label"]]))
            if key in seen:
                continue
            seen.add(key)

            # ALL games
            m1 = apply_filter(df, r1["col"], r1["op"], r1["val"])
            m2 = apply_filter(df, r2["col"], r2["op"], r2["val"])
            sub = df[m1 & m2 & ~df["is_push"]]
            n, h, r = roi_stats(sub)
            if n >= min_n // 2 and h >= min_over:
                label = f"{r1['label']}  &  {r2['label']}"
                mark = " <--" if h >= BREAKEVEN else ""
                print(f"  {label:<72} {n:>5} {h:>6.1f}% {r:>+7.1f}%{mark}")
                combo_results.append({
                    "label": label,
                    "filters": [(r1["col"], r1["op"], r1["val"]),
                                (r2["col"], r2["op"], r2["val"])],
                    "pop": "all", "n": n, "over_pct": h, "roi": r,
                })

            # GREY zone
            m1g = apply_filter(grey, r1["col"], r1["op"], r1["val"])
            m2g = apply_filter(grey, r2["col"], r2["op"], r2["val"])
            subg = grey[m1g & m2g & ~grey["is_push"]]
            ng, hg, rg = roi_stats(subg)
            if ng >= max(30, min_n // 4) and hg >= min_over:
                label = f"[GZ] {r1['label']}  &  {r2['label']}"
                mark = " <--" if hg >= BREAKEVEN else ""
                print(f"  {label:<72} {ng:>5} {hg:>6.1f}% {rg:>+7.1f}%{mark}")
                combo_results.append({
                    "label": label,
                    "filters": [(r1["col"], r1["op"], r1["val"]),
                                (r2["col"], r2["op"], r2["val"])],
                    "pop": "grey", "n": ng, "over_pct": hg, "roi": rg,
                })

    if not combo_results:
        print("  (no qualifying pairs found)")

    return combo_results


# ─────────────────────────────────────────────────────────────────────────────
# Section 3: Three-feature combos
# ─────────────────────────────────────────────────────────────────────────────

def three_feature_combos(df: pd.DataFrame, combo_results: list,
                         min_n: int, min_over: float):
    top_pairs = sorted(combo_results, key=lambda r: r["over_pct"], reverse=True)[:10]
    if not top_pairs:
        return []

    # Extra filters to add as third dimension
    extra_filters = [
        ("bullpen_ip_3d_combined", ">=", 20, "bp3d>=20"),
            ("sp_fip_floor_short", ">=", 4.5, "sp_floor>=4.5"),
        ("month", ">=", 7, "month>=7"),
        ("close_ou", "<=", 8.5, "line<=8.5"),
        ("combined_rpg", ">=", 9.5, "rpg>=9.5"),
        ("power_rate_combined", ">=", 0.38, "power>=0.38"),
    ]

    section("SECTION 3: THREE-FEATURE COMBOS (top pairs + one extra dimension)")
    print(f"  Showing N >= {min_n // 4}, over% >= {min_over + 1.0:.1f}%\n")
    print(f"  {'combo':<80} {'N':>5} {'over%':>7} {'ROI':>8}")
    print("  " + "-" * 104)

    trio_results = []
    for pair in top_pairs:
        filt = pair["filters"]
        for ecol, eop, eval_, elabel in extra_filters:
            if any(f[0] == ecol for f in filt):
                continue
            m = pd.Series(True, index=df.index)
            for col, op, val in filt:
                m &= apply_filter(df, col, op, val)
            m &= apply_filter(df, ecol, eop, eval_)
            sub = df[m & ~df["is_push"]]
            n, h, r = roi_stats(sub)
            if n >= min_n // 4 and h >= min_over + 1.0:
                base = pair["label"].replace("[GZ] ", "")
                label = f"{base}  +  {elabel}"
                mark = " <--" if h >= BREAKEVEN else ""
                print(f"  {label:<80} {n:>5} {h:>6.1f}% {r:>+7.1f}%{mark}")
                trio_results.append({
                    "label": label,
                    "filters": filt + [(ecol, eop, eval_)],
                    "pop": "all", "n": n, "over_pct": h, "roi": r,
                })

    if not trio_results:
        print("  (no qualifying trios found)")

    return trio_results


# ─────────────────────────────────────────────────────────────────────────────
# Section 4: Outlier stress on candidates
# ─────────────────────────────────────────────────────────────────────────────

def outlier_stress_candidates(df: pd.DataFrame, candidates: list):
    section("SECTION 4: OUTLIER STRESS on all candidates (N >= 100, over% >= 54%)")
    print(f"  {'filter':<60} {'0%':>10} {'5%':>10} {'10%':>10} {'15%':>10}  flag")
    print("  " + "-" * 110)

    for cand in candidates:
        # Rebuild mask
        m = pd.Series(True, index=df.index)
        for col, op, val in cand["filters"]:
            m &= apply_filter(df, col, op, val)
        sub = df[m & ~df["is_push"]]
        if len(sub) < 100:
            continue

        cells = []
        for pct in [0, 5, 10, 15]:
            h, r = trim_stress(sub, pct)
            cells.append(f"{h:.1f}%/{r:>+.0f}%")

        h10, _ = trim_stress(sub, 10)
        flag = "SURVIVES" if h10 >= 52.0 else ("WATCH" if h10 >= 50.0 else "COLLAPSES")
        label = cand["label"][:58]
        print(f"  {label:<60} " + " ".join(f"{c:>10}" for c in cells) + f"  {flag}")


# ─────────────────────────────────────────────────────────────────────────────
# Section 5: Era split on survivors
# ─────────────────────────────────────────────────────────────────────────────

def era_split_survivors(df: pd.DataFrame, candidates: list):
    survivors = []
    for cand in candidates:
        m = pd.Series(True, index=df.index)
        for col, op, val in cand["filters"]:
            m &= apply_filter(df, col, op, val)
        sub = df[m & ~df["is_push"]]
        if len(sub) < 100:
            continue
        h10, _ = trim_stress(sub, 10)
        if h10 >= 52.0:
            survivors.append((cand, sub))

    if not survivors:
        section("SECTION 5: ERA SPLIT")
        print("  (no survivors from outlier stress)")
        return

    section("SECTION 5: ERA SPLIT on outlier-stress survivors")
    print(f"  {'filter':<58} {'pre-2021':^20} {'2021+':^20} era-shift")
    print("  " + "-" * 110)

    for cand, sub in survivors:
        pre = sub[sub["season"] <= 2019]
        mod = sub[sub["season"] >= 2021]
        np_, hp, _ = roi_stats(pre)
        nm, hm, _ = roi_stats(mod)
        shift = f"+{hm - hp:.1f}pp" if hm - hp >= 1.0 else f"{hm - hp:+.1f}pp"
        flag = " REGIME-SHIFT?" if hm - hp >= 3.0 and hm > 54.0 else ""
        pre_str = f"N={np_:>4} {hp:.1f}%" if np_ >= 20 else f"N={np_:>4} --"
        mod_str = f"N={nm:>4} {hm:.1f}%" if nm >= 20 else f"N={nm:>4} --"
        label = cand["label"][:56]
        print(f"  {label:<58} {pre_str:<20} {mod_str:<20} {shift}{flag}")


# ─────────────────────────────────────────────────────────────────────────────
# Section 6: Summary
# ─────────────────────────────────────────────────────────────────────────────

def summary_report(df: pd.DataFrame, all_candidates: list):
    section("SECTION 6: SUMMARY — top-20 candidates sorted by over%")
    all_candidates.sort(key=lambda c: c["over_pct"], reverse=True)
    top = all_candidates[:20]

    print(f"  {'#':<3} {'filter':<55} {'pop':<5} {'N':>5} {'over%':>7} {'ROI':>8} "
          f"{'10%-trim':>9} {'flag'}")
    print("  " + "-" * 110)

    for i, cand in enumerate(top, 1):
        m = pd.Series(True, index=df.index)
        for col, op, val in cand["filters"]:
            m &= apply_filter(df, col, op, val)
        sub = df[m & ~df["is_push"]]
        n, h, r = roi_stats(sub)
        h10, _ = trim_stress(sub, 10)

        if n >= 100 and h10 >= 52.0:
            flag = "CANDIDATE"
        elif n >= 50 and h >= BREAKEVEN:
            flag = "WATCH"
        else:
            flag = "NOISE"

        label = cand["label"][:53]
        pop = cand.get("pop", "all")[:4]
        print(f"  {i:<3} {label:<55} {pop:<5} {n:>5} {h:>6.1f}% {r:>+7.1f}% "
              f"{h10:>8.1f}% {flag}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true",
                        help="Single filters only, skip combos")
    parser.add_argument("--min-n", type=int, default=100,
                        help="Minimum N for candidates (default 100)")
    parser.add_argument("--min-over", type=float, default=51.5,
                        help="Minimum over%% for single-filter reporting (default 51.5)")
    args = parser.parse_args()

    df = build_preds_with_features()

    # Baseline
    n_all, h_all, r_all = roi_stats(df)
    grey = df[(df["p_under"] >= GREY_LO) & (df["p_under"] < GREY_HI)]
    n_gz, h_gz, r_gz = roi_stats(grey)
    print(f"\nBaseline:")
    print(f"  All games:   N={n_all:>6}  over%={h_all:.1f}%  ROI={r_all:+.1f}%"
          f"  breakeven={BREAKEVEN:.2f}%")
    print(f"  Grey zone:   N={n_gz:>6}  over%={h_gz:.1f}%  ROI={r_gz:+.1f}%")

    grid = build_filter_grid()

    # Section 1
    single_results = single_filter_grid(df, grid, min_n=args.min_n)

    if args.quick:
        return

    # Build candidate list from single filters
    single_candidates = [
        {"label": r["label"], "filters": [(r["col"], r["op"], r["val"])],
         "pop": r["pop"], "n": r["n"], "over_pct": r["over_pct"], "roi": r["roi"]}
        for r in single_results
        if r["over_pct"] >= args.min_over and r["n"] >= args.min_n
    ]

    # Section 2: use lower threshold for combo building (always generate pairs)
    combo_min_over = min(args.min_over, 50.5)  # lower bar to get cross-category pairs
    combo2 = two_feature_combos(df, single_results,
                                 min_n=args.min_n, min_over=combo_min_over)

    # Section 3
    combo3 = three_feature_combos(df, combo2,
                                   min_n=args.min_n, min_over=args.min_over)

    # All candidates
    all_candidates = single_candidates + combo2 + combo3

    # Section 4: outlier stress
    stress_candidates = [c for c in all_candidates
                         if c["n"] >= 100 and c["over_pct"] >= 54.0]
    if stress_candidates:
        outlier_stress_candidates(df, stress_candidates)
    else:
        section("SECTION 4: OUTLIER STRESS")
        print(f"  (no candidates with N>=100 and over%>=54% found)")

    # Section 5: era split
    era_split_survivors(df, stress_candidates)

    # Section 6: summary
    summary_report(df, all_candidates)


if __name__ == "__main__":
    main()
