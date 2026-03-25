"""Away underdog deep dive: RL +1.5 and ML win with feature filters.

Uses REAL closing odds, 4-model divergence, team/pitcher/bullpen features,
home/away splits, and per-fold consistency checks.

Usage:
    python -m scripts.analyze_divergence
"""

import logging
import sys
from itertools import combinations

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
logger = logging.getLogger(__name__)

AWAY_RL_DOG_ODDS = 1.87  # conservative estimate for away +1.5


def _roi(pnl: np.ndarray, n: int) -> float:
    return float(pnl.sum() / (n * 100) * 100)


def _bet_fav(b: pd.DataFrame) -> tuple[np.ndarray, float]:
    pnl = np.where(b["fav_won"], (b["fav_decimal"] - 1) * 100, -100)
    return pnl, b["fav_won"].mean() * 100


def _bet_dog(b: pd.DataFrame) -> tuple[np.ndarray, float]:
    dog_won = ~b["fav_won"]
    pnl = np.where(dog_won, (b["dog_decimal"] - 1) * 100, -100)
    return pnl, dog_won.mean() * 100


def _fold_check(df: pd.DataFrame, mask: pd.Series, side: str,
                rl_col: str | None = None) -> dict:
    """Per-fold ROI. For RL bets, pass rl_col (cover column); uses per-game away_rl_dec."""
    rois = []
    for fold in df["fold"].unique():
        fm = mask & (df["fold"] == fold)
        n = fm.sum()
        if n < 5:
            continue
        b = df[fm]
        if rl_col is not None:
            pnl = np.where(b[rl_col], (b["away_rl_dec"] - 1) * 100, -100)
        elif side == "fav":
            pnl, _ = _bet_fav(b)
        else:
            pnl, _ = _bet_dog(b)
        rois.append(_roi(pnl, n))
    if len(rois) < 3:
        return {"avg": float("nan"), "min": float("nan"), "all_pos": False, "folds": 0}
    return {
        "avg": np.mean(rois),
        "min": min(rois),
        "all_pos": all(r > 0 for r in rois),
        "folds": len(rois),
        "rois": rois,
    }


def _fold_str(fc: dict) -> str:
    if fc["folds"] == 0:
        return "no folds"
    marker = " <<<" if fc["all_pos"] else ""
    rois_str = ",".join(f"{r:+.0f}" for r in fc.get("rois", []))
    return f"folds=[{rois_str}] avg={fc['avg']:+.1f}% min={fc['min']:+.1f}%{marker}"


def build_analysis_df() -> pd.DataFrame:
    """Merge divergence predictions with full game data including all features."""
    from src.features import SPEC_FEATURES, build_spec_features
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    logger.info("Building spec features...")
    full = build_spec_features()

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    merge_keys = ["season", "date", "home_team", "away_team"]

    extra_cols = [
        # Odds & scores
        "home_decimal_odds", "away_decimal_odds",
        "home_implied_prob", "away_implied_prob",
        "home_close_ml", "away_close_ml",
        "home_run_line", "home_run_line_odds",
        "away_run_line", "away_run_line_odds",
        "home_final", "away_final",
        "fav_is_home", "fav_margin",
        # Team form & quality
        "wp_last3_home", "wp_last3_away", "wp_last6_home", "wp_last6_away",
        "wp_last10_home", "wp_last10_away",
        "rpg_home", "rpg_away", "rapg_home", "rapg_away",
        "rpi_home", "rpi_away", "rpi_diff",
        "pyth_wp_home", "pyth_wp_away", "pyth_wp_diff",
        "streak_home", "streak_away",
        "games_played_home", "games_played_away",
        # Elo
        "elo_diff", "home_elo", "away_elo",
        # Pitcher quality
        "home_sp_ra_short", "away_sp_ra_short",
        "home_sp_wr_short", "away_sp_wr_short",
        "home_sp_fi_ra_short", "away_sp_fi_ra_short",
        "sp_ra_short_diff", "sp_wr_short_diff",
        "starter_fip_diff", "starter_whip_diff",
        # Bullpen
        "bp_fip_short_home", "bp_fip_short_away",
        "bp_ip_3d_home", "bp_ip_3d_away",
        "bullpen_fip_diff", "bullpen_workload_3d_diff",
    ]
    extra_cols = [c for c in extra_cols if c in full.columns]
    full_subset = full[merge_keys + extra_cols].copy()
    full_subset = full_subset.drop_duplicates(subset=merge_keys)

    df = div.merge(full_subset, on=merge_keys, how="left")

    # Integrity check: duplicates should no longer appear after bullpen_features fix.
    dup_count = df.duplicated(
        subset=["season", "date", "home_team", "away_team", "fold"]
    ).sum()
    if dup_count > 0:
        logger.error(
            f"Unexpected duplicates: {dup_count} rows ({dup_count/len(df)*100:.1f}%). "
            "Root cause may not be fully fixed — investigate build_spec_features()."
        )
        df = df.drop_duplicates(
            subset=["season", "date", "home_team", "away_team", "fold"],
            keep="first",
        )

    return df


def main() -> None:
    print("Building analysis dataset (features + models + real odds)...")
    df = build_analysis_df()

    target = "closing_decimal_odds_favorite"
    pred_cols = ["pred_M0", "pred_M2", "pred_M3", "pred_M4"]

    # === Real odds ===
    df["fav_won"] = df["regime"].isin(["M2", "M3"])
    df["fav_decimal"] = np.where(df["fav_is_home"], df["home_decimal_odds"], df["away_decimal_odds"])
    df["dog_decimal"] = np.where(df["fav_is_home"], df["away_decimal_odds"], df["home_decimal_odds"])

    n_before = len(df)
    df = df[df["dog_decimal"] <= 3.0].copy()
    n_extreme = n_before - len(df)

    # === Derived signals ===
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df[target] - df["pred_consensus"]
    df["m34_vs_m02"] = (df["pred_M3"] + df["pred_M4"]) / 2 - (df["pred_M0"] + df["pred_M2"]) / 2
    df["m4_edge"] = df[target] - df["pred_M4"]
    df["dog_is_home"] = ~df["fav_is_home"]
    df["margin_home"] = df["home_final"] - df["away_final"]
    df["away_dog_covers"] = df["margin_home"] <= 1  # away +1.5 covers
    df["away_dog_won"] = df["margin_home"] < 0       # away wins outright

    # Real away RL +1.5 odds (from SBR data for 2022+, fallback for older seasons)
    from src.data_loader import american_to_decimal
    if "away_run_line_odds" in df.columns:
        df["away_rl_dec"] = df["away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    else:
        df["away_rl_dec"] = np.nan
    # Fallback for games without real away RL odds
    df["away_rl_dec"] = df["away_rl_dec"].fillna(AWAY_RL_DOG_ODDS)

    print(f"\n{'='*70}")
    print(f"DATASET: {len(df)} games ({n_extreme} excluded: dog odds > 3.0)")
    print(f"Fav win rate: {df['fav_won'].mean()*100:.1f}%")
    print(f"Available features: {[c for c in df.columns if c.startswith(('wp_', 'rpi_', 'elo_', 'streak_', 'sp_', 'bp_', 'bullpen_', 'starter_', 'pyth_', 'rpg_', 'rapg_'))]}")

    # ===================================================================
    print(f"\n{'='*70}")
    print("PART 1: FAV BASELINE (reference)")
    print("=" * 70)

    for threshold in [0.03, 0.05, 0.07]:
        mask = df["edge_consensus"] > threshold
        n = mask.sum()
        if n < 10:
            continue
        b = df[mask]
        pnl, wr = _bet_fav(b)
        fc = _fold_check(df, mask, "fav")
        print(f"  edge>{threshold:.2f}: {n:5d} bets, WR={wr:.1f}%, ROI={_roi(pnl, n):+.2f}%, {_fold_str(fc)}")

    # ===================================================================
    # Away underdog universe
    # ===================================================================
    # For RL: home is favorite on run line (home_run_line = -1.5)
    has_rl = df["home_run_line"].isin([-1.5, 1.5])
    away_rl = df[has_rl & (df["home_run_line"] == -1.5)].copy()

    print(f"\n{'='*70}")
    print(f"PART 2: AWAY DOG +1.5 DEEP DIVE ({len(away_rl)} games with RL data)")
    print("=" * 70)

    # --- 2A: Baseline with folds ---
    print("\n--- 2A: Baseline + edge filter ---")
    for label, mask in [
        ("Blind", pd.Series(True, index=away_rl.index)),
        ("edge<-0.02", away_rl["edge_consensus"] < -0.02),
        ("edge<-0.03", away_rl["edge_consensus"] < -0.03),
        ("edge<-0.05", away_rl["edge_consensus"] < -0.05),
        ("edge<-0.07", away_rl["edge_consensus"] < -0.07),
    ]:
        n = mask.sum()
        if n < 10:
            continue
        b = away_rl[mask]
        covers = b["away_dog_covers"]
        pnl = np.where(covers, (b["away_rl_dec"] - 1) * 100, -100)
        wr = covers.mean() * 100
        fc = _fold_check(away_rl, mask, "dog", rl_col="away_dog_covers")
        print(f"  {label:>14}: {n:5d} bets, cover={wr:.1f}%, ROI={_roi(pnl, n):+.2f}%, {_fold_str(fc)}")

    # --- 2B: Single feature filters on top of edge<-0.05 ---
    print("\n--- 2B: Feature filters (stacked on edge<-0.05) ---")
    base_mask = (away_rl["edge_consensus"] < -0.05)
    base_n = base_mask.sum()
    base_b = away_rl[base_mask]
    base_covers = base_b["away_dog_covers"]
    base_pnl = np.where(base_covers, (base_b["away_rl_dec"] - 1) * 100, -100)
    print(f"  BASE (edge<-0.05): {base_n} bets, cover={base_covers.mean()*100:.1f}%, ROI={_roi(base_pnl, base_n):+.2f}%")

    # Define named filters with their masks (computed on away_rl)
    filters = {}

    # Team form
    if "wp_last3_away" in away_rl.columns:
        filters["wp3_away>=.50"] = away_rl["wp_last3_away"] >= 0.50
        filters["wp3_away>=.33"] = away_rl["wp_last3_away"] >= 0.33
    if "wp_last6_away" in away_rl.columns:
        filters["wp6_away>=.45"] = away_rl["wp_last6_away"] >= 0.45
        filters["wp6_away>=.40"] = away_rl["wp_last6_away"] >= 0.40
    if "wp_last10_away" in away_rl.columns:
        filters["wp10_away>=.45"] = away_rl["wp_last10_away"] >= 0.45

    # RPI
    if "rpi_diff" in away_rl.columns:
        filters["rpi_diff<=0.03"] = away_rl["rpi_diff"].abs() <= 0.03
        filters["rpi_diff<=0.05"] = away_rl["rpi_diff"].abs() <= 0.05
        filters["rpi_diff<=0"] = away_rl["rpi_diff"] <= 0  # away is better

    # Elo
    if "elo_diff" in away_rl.columns:
        filters["elo_diff<=50"] = away_rl["elo_diff"].abs() <= 50
        filters["elo_diff<=30"] = away_rl["elo_diff"].abs() <= 30
        filters["elo_diff<=0"] = away_rl["elo_diff"] <= 0  # away is better by elo

    # Streaks
    if "streak_away" in away_rl.columns:
        filters["away_streak>=0"] = away_rl["streak_away"] >= 0
        filters["away_streak>=1"] = away_rl["streak_away"] >= 1

    # Pitcher quality
    if "away_sp_ra_short" in away_rl.columns:
        med = away_rl["away_sp_ra_short"].median()
        filters[f"away_sp_ra<=med({med:.2f})"] = away_rl["away_sp_ra_short"] <= med
    if "home_sp_ra_short" in away_rl.columns:
        med = away_rl["home_sp_ra_short"].median()
        filters[f"home_sp_ra>=med({med:.2f})"] = away_rl["home_sp_ra_short"] >= med
    if "starter_fip_diff" in away_rl.columns:
        filters["fip_diff>0"] = away_rl["starter_fip_diff"] > 0  # home pitcher worse
    if "starter_whip_diff" in away_rl.columns:
        filters["whip_diff>0"] = away_rl["starter_whip_diff"] > 0

    # Bullpen
    if "bp_ip_3d_home" in away_rl.columns:
        med = away_rl["bp_ip_3d_home"].median()
        filters[f"home_bp_3d>med({med:.1f})"] = away_rl["bp_ip_3d_home"] > med
        p75 = away_rl["bp_ip_3d_home"].quantile(0.75)
        filters[f"home_bp_3d>p75({p75:.1f})"] = away_rl["bp_ip_3d_home"] > p75
    if "bullpen_fip_diff" in away_rl.columns:
        filters["bp_fip_diff>0"] = away_rl["bullpen_fip_diff"] > 0

    # Pyth & RPG
    if "pyth_wp_diff" in away_rl.columns:
        filters["pyth_diff<=0.05"] = away_rl["pyth_wp_diff"] <= 0.05
    if "rpg_away" in away_rl.columns:
        med = away_rl["rpg_away"].median()
        filters[f"away_rpg>=med({med:.2f})"] = away_rl["rpg_away"] >= med

    # Model signals
    filters["m34>m02"] = away_rl["m34_vs_m02"] > 0
    filters["m4_edge<-0.03"] = away_rl["m4_edge"] < -0.03

    # Games played
    if "games_played_away" in away_rl.columns:
        filters["gp_away>=30"] = away_rl["games_played_away"] >= 30

    # Dog odds band
    filters["dog<=2.30"] = away_rl["dog_decimal"] <= 2.30
    filters["dog<=2.50"] = away_rl["dog_decimal"] <= 2.50

    print(f"\n  {'Filter':<30} {'N':>5} {'Cover':>6} {'ROI':>8} Folds")
    for fname, fmask in sorted(filters.items()):
        combined = base_mask & fmask
        n = combined.sum()
        if n < 20:
            continue
        b = away_rl[combined]
        covers = b["away_dog_covers"]
        pnl = np.where(covers, (b["away_rl_dec"] - 1) * 100, -100)
        fc = _fold_check(away_rl, combined, "dog", rl_col="away_dog_covers")
        print(f"  {fname:<30} {n:5d} {covers.mean()*100:5.1f}% {_roi(pnl, n):+7.2f}% {_fold_str(fc)}")

    # --- 2C: Best combos (pairs of filters on top of edge<-0.05) ---
    print(f"\n--- 2C: Top combos (pairs on edge<-0.05, ROI>5%, >=3 folds positive) ---")
    combos = []
    filter_items = list(filters.items())
    for (n1, m1), (n2, m2) in combinations(filter_items, 2):
        combined = base_mask & m1 & m2
        n = combined.sum()
        if n < 20:
            continue
        b = away_rl[combined]
        covers = b["away_dog_covers"]
        pnl = np.where(covers, (b["away_rl_dec"] - 1) * 100, -100)
        roi = _roi(pnl, n)
        fc = _fold_check(away_rl, combined, "dog", rl_col="away_dog_covers")
        pos_folds = sum(1 for r in fc.get("rois", []) if r > 0)
        if roi > 5.0 and pos_folds >= 3:
            combos.append((roi, n, covers.mean() * 100, f"{n1} + {n2}", fc))

    combos.sort(key=lambda x: x[0], reverse=True)
    print(f"  {'Combo':<55} {'N':>5} {'Cover':>6} {'ROI':>8} Folds")
    for roi, n, cov, label, fc in combos[:25]:
        print(f"  {label:<55} {n:5d} {cov:5.1f}% {roi:+7.2f}% {_fold_str(fc)}")

    if not combos:
        print("  No combos found meeting criteria.")

    # ===================================================================
    print(f"\n{'='*70}")
    print("PART 3: AWAY DOG ML WIN (same universe)")
    print("=" * 70)

    # Away dog ML: away team wins outright (fav loses)
    # For these games, dog_decimal = away team's closing odds
    away_games = df[~df["fav_is_home"]].copy()  # fav is away => dog is home... no.
    # Wait: if fav_is_home=True, dog is away. These are our away underdog games.
    away_dog_all = df[df["fav_is_home"]].copy()  # fav is home, dog is away
    print(f"\nAway underdog ML universe: {len(away_dog_all)} games")

    # --- 3A: Baseline ---
    print("\n--- 3A: Edge filters ---")
    for label, mask in [
        ("Blind", pd.Series(True, index=away_dog_all.index)),
        ("edge<-0.02", away_dog_all["edge_consensus"] < -0.02),
        ("edge<-0.03", away_dog_all["edge_consensus"] < -0.03),
        ("edge<-0.05", away_dog_all["edge_consensus"] < -0.05),
        ("edge<-0.07", away_dog_all["edge_consensus"] < -0.07),
    ]:
        n = mask.sum()
        if n < 10:
            continue
        b = away_dog_all[mask]
        pnl, wr = _bet_dog(b)
        fc = _fold_check(away_dog_all, mask, "dog")
        print(f"  {label:>14}: {n:5d} bets, WR={wr:.1f}%, dog_odds={b['dog_decimal'].mean():.3f}, "
              f"ROI={_roi(pnl, n):+.2f}%, {_fold_str(fc)}")

    # --- 3B: Feature filters on edge<-0.05 for ML ---
    print("\n--- 3B: Feature filters (on edge<-0.05) ---")
    base_ml = away_dog_all["edge_consensus"] < -0.05
    base_ml_n = base_ml.sum()
    base_ml_b = away_dog_all[base_ml]
    base_ml_pnl, base_ml_wr = _bet_dog(base_ml_b)
    print(f"  BASE (edge<-0.05): {base_ml_n} bets, WR={base_ml_wr:.1f}%, "
          f"ROI={_roi(base_ml_pnl, base_ml_n):+.2f}%")

    # Build filters for ML universe
    ml_filters = {}

    # Odds bands (key for ML: short dogs win more often)
    ml_filters["dog<=2.30"] = away_dog_all["dog_decimal"] <= 2.30
    ml_filters["dog<=2.20"] = away_dog_all["dog_decimal"] <= 2.20
    ml_filters["dog<=2.50"] = away_dog_all["dog_decimal"] <= 2.50

    # Team form
    if "wp_last3_away" in away_dog_all.columns:
        ml_filters["wp3_away>=.50"] = away_dog_all["wp_last3_away"] >= 0.50
        ml_filters["wp3_away>=.67"] = away_dog_all["wp_last3_away"] >= 0.67
    if "wp_last6_away" in away_dog_all.columns:
        ml_filters["wp6_away>=.50"] = away_dog_all["wp_last6_away"] >= 0.50

    # RPI
    if "rpi_diff" in away_dog_all.columns:
        ml_filters["rpi_diff<=0"] = away_dog_all["rpi_diff"] <= 0
        ml_filters["rpi_diff<=0.02"] = away_dog_all["rpi_diff"].abs() <= 0.02

    # Elo
    if "elo_diff" in away_dog_all.columns:
        ml_filters["elo_diff<=30"] = away_dog_all["elo_diff"].abs() <= 30
        ml_filters["elo_diff<=0"] = away_dog_all["elo_diff"] <= 0

    # Pitcher
    if "away_sp_ra_short" in away_dog_all.columns:
        p25 = away_dog_all["away_sp_ra_short"].quantile(0.25)
        med = away_dog_all["away_sp_ra_short"].median()
        ml_filters[f"away_sp_ra<=p25({p25:.2f})"] = away_dog_all["away_sp_ra_short"] <= p25
        ml_filters[f"away_sp_ra<=med({med:.2f})"] = away_dog_all["away_sp_ra_short"] <= med
    if "home_sp_ra_short" in away_dog_all.columns:
        p75 = away_dog_all["home_sp_ra_short"].quantile(0.75)
        ml_filters[f"home_sp_ra>=p75({p75:.2f})"] = away_dog_all["home_sp_ra_short"] >= p75
    if "starter_fip_diff" in away_dog_all.columns:
        ml_filters["fip_diff>0"] = away_dog_all["starter_fip_diff"] > 0

    # Bullpen
    if "bp_ip_3d_home" in away_dog_all.columns:
        p75 = away_dog_all["bp_ip_3d_home"].quantile(0.75)
        ml_filters[f"home_bp_3d>p75({p75:.1f})"] = away_dog_all["bp_ip_3d_home"] > p75
    if "bullpen_fip_diff" in away_dog_all.columns:
        ml_filters["bp_fip_diff>0"] = away_dog_all["bullpen_fip_diff"] > 0

    # Streak
    if "streak_away" in away_dog_all.columns:
        ml_filters["away_streak>=1"] = away_dog_all["streak_away"] >= 1
        ml_filters["away_streak>=0"] = away_dog_all["streak_away"] >= 0

    # Model signals
    ml_filters["m34>m02"] = away_dog_all["m34_vs_m02"] > 0
    ml_filters["m4_edge<-0.05"] = away_dog_all["m4_edge"] < -0.05

    # Sample size
    if "games_played_away" in away_dog_all.columns:
        ml_filters["gp_away>=30"] = away_dog_all["games_played_away"] >= 30

    print(f"\n  {'Filter':<35} {'N':>5} {'WR':>6} {'Odds':>6} {'ROI':>8} Folds")
    for fname, fmask in sorted(ml_filters.items()):
        combined = base_ml & fmask
        n = combined.sum()
        if n < 15:
            continue
        b = away_dog_all[combined]
        pnl, wr = _bet_dog(b)
        fc = _fold_check(away_dog_all, combined, "dog")
        print(f"  {fname:<35} {n:5d} {wr:5.1f}% {b['dog_decimal'].mean():5.3f} "
              f"{_roi(pnl, n):+7.2f}% {_fold_str(fc)}")

    # --- 3C: Best ML combos ---
    print(f"\n--- 3C: Top ML combos (pairs on edge<-0.05, ROI>0%, >=3 folds) ---")
    ml_combos = []
    ml_items = list(ml_filters.items())
    for (n1, m1), (n2, m2) in combinations(ml_items, 2):
        combined = base_ml & m1 & m2
        n = combined.sum()
        if n < 15:
            continue
        b = away_dog_all[combined]
        pnl, wr = _bet_dog(b)
        roi = _roi(pnl, n)
        fc = _fold_check(away_dog_all, combined, "dog")
        pos_folds = sum(1 for r in fc.get("rois", []) if r > 0)
        if roi > 0.0 and pos_folds >= 3:
            ml_combos.append((roi, n, wr, b["dog_decimal"].mean(), f"{n1} + {n2}", fc))

    ml_combos.sort(key=lambda x: x[0], reverse=True)
    print(f"  {'Combo':<55} {'N':>5} {'WR':>6} {'Odds':>6} {'ROI':>8} Folds")
    for roi, n, wr, odds, label, fc in ml_combos[:25]:
        print(f"  {label:<55} {n:5d} {wr:5.1f}% {odds:5.3f} {roi:+7.2f}% {_fold_str(fc)}")

    if not ml_combos:
        print("  No combos found meeting criteria.")

    # ===================================================================
    print(f"\n{'='*70}")
    print("PART 4: EDGE DECILE ANALYSIS (margin + cover rate + dog WR)")
    print("=" * 70)

    # Use away_rl for RL analysis, full df for ML
    away_rl_all = df[df["home_run_line"] == -1.5].copy()
    away_rl_all["edge_decile"] = pd.qcut(
        away_rl_all["edge_consensus"], 5, labels=False, duplicates="drop"
    )

    print(f"\n{'Quint':>5} {'Edge range':>26} {'N':>5} {'AwDog':>7} {'Cover':>7} "
          f"{'RL ROI':>8} {'ML ROI':>8} {'Avg margin':>10} {'1-run%':>7}")
    for q in range(5):
        mask = away_rl_all["edge_decile"] == q
        b = away_rl_all[mask]
        n = len(b)
        er = f"[{b['edge_consensus'].min():.3f}, {b['edge_consensus'].max():.3f}]"
        margin = b["margin_home"]

        # Away dog wins (margin < 0)
        dog_wr = (margin < 0).mean() * 100
        # Cover rate (+1.5)
        cov = (margin <= 1).mean() * 100
        # RL ROI
        rl_pnl = np.where(margin <= 1, (b["away_rl_dec"] - 1) * 100, -100)
        rl_roi = _roi(rl_pnl, n)
        # ML ROI (bet on away dog to win)
        # Need away dog odds for these games — dog is away when fav_is_home
        fav_home = b["fav_is_home"]
        dog_dec = np.where(fav_home, b["away_decimal_odds"], b["home_decimal_odds"])
        dog_won = margin < 0
        ml_pnl = np.where(dog_won, (dog_dec - 1) * 100, -100)
        ml_roi = _roi(ml_pnl, n)
        # Margin stats
        avg_margin = margin.mean()
        one_run_pct = (margin.abs() == 1).mean() * 100

        print(f"  Q{q}   {er:>26} {n:5d} {dog_wr:6.1f}% {cov:6.1f}% "
              f"{rl_roi:+7.2f}% {ml_roi:+7.2f}% {avg_margin:+9.2f} {one_run_pct:6.1f}%")

    # ===================================================================
    print(f"\n{'='*70}")
    print("PART 5: MARGIN DISTRIBUTION BY EDGE BAND")
    print("=" * 70)

    # Compare margin distribution: high edge (Q0) vs low edge (Q4)
    for q_label, q_vals in [("Bottom edge (Q0, fav overvalued)", [0]),
                             ("Top edge (Q4, fav undervalued)", [4])]:
        mask = away_rl_all["edge_decile"].isin(q_vals)
        b = away_rl_all[mask]
        margin = b["margin_home"]
        print(f"\n  {q_label}: {len(b)} games")
        margin_dist = margin.clip(-5, 5).value_counts().sort_index()
        for m, cnt in margin_dist.items():
            pct = cnt / len(b) * 100
            bar = "#" * int(pct)
            print(f"    margin={int(m):+d}: {cnt:4d} ({pct:4.1f}%) {bar}")

    print(f"\n{'='*70}")
    print("DONE")
    print("=" * 70)


if __name__ == "__main__":
    main()
