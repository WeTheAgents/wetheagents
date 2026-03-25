"""NRFI research: find profitable No-Run-First-Inning filters WITHOUT the O/U line.

Mirror of run_yrfi_research.py with inverted filter directions and NRFI odds calibration.

For NRFI, the sweet spot is HIGH close_ou games (9+) where the market gives long NRFI
odds (2.0+) but our pitcher/batter features identify dominant pitching matchups the
market doesn't see. Low close_ou games already price NRFI cheaply (~1.61 odds).

Approach:
  Phase 1: single-feature sweep (adjusted ROI)
  Phase 2: two-way combos from best-per-feature thresholds
  Phase 3: three-way combos
  Phase 4: walk-forward validation + bootstrap CI

Usage:
    python scripts/run_nrfi_research.py
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

# ── NRFI odds calibration table ─────────────────────────────────────────
# Derived from YRFI calibration: NRFI rate = 1 - YRFI rate per OU bucket
# YRFI rate = 0.95/yrfi_odds → NRFI rate = 1 - 0.95/yrfi_odds
# NRFI odds = 0.95/nrfi_rate (5% vig)
#
# Low OU → high NRFI rate → cheap odds (market knows pitchers dominate)
# High OU → low NRFI rate → expensive odds (good value if we find dominant arms)
CALIB_POINTS = [
    # (close_ou midpoint, estimated NRFI odds)
    (6.5, 1.61),    # NRFI rate ~59%
    (7.25, 1.79),   # NRFI rate ~53%
    (7.75, 1.86),   # NRFI rate ~51%
    (8.25, 1.91),   # NRFI rate ~50%
    (8.75, 1.96),   # NRFI rate ~48%
    (9.50, 2.01),   # NRFI rate ~47%
    (10.25, 2.14),  # NRFI rate ~44%
    (11.0, 2.36),   # NRFI rate ~40%
]
CALIB_OU = np.array([p[0] for p in CALIB_POINTS])
CALIB_ODDS = np.array([p[1] for p in CALIB_POINTS])


def estimate_nrfi_odds(close_ou: pd.Series) -> pd.Series:
    """Piecewise-linear interpolation: close_ou -> estimated NRFI decimal odds."""
    return pd.Series(
        np.interp(close_ou.values, CALIB_OU, CALIB_ODDS),
        index=close_ou.index,
    )


def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def metrics_adjusted(df, name, min_bets=20):
    """Compute NRFI metrics with market-adjusted odds."""
    df = df.dropna(subset=["close_ou"]).sort_values("date").copy()
    n = len(df)
    if n < min_bets:
        return None

    hit = df["nrfi"].values.astype(float)
    hr = hit.mean()

    # Estimated odds per game from close_ou
    est_odds = estimate_nrfi_odds(df["close_ou"])
    avg_ou = df["close_ou"].mean()
    avg_odds = est_odds.mean()

    # Adjusted PnL (per-game odds from market)
    adj_pnl = np.where(hit, (est_odds.values - 1) * 100, -100)
    adj_roi = adj_pnl.sum() / (n * 100) * 100

    # Fixed-odds PnL (1.85)
    fixed_pnl = np.where(hit, 0.85 * 100, -100)
    fixed_roi = fixed_pnl.sum() / (n * 100) * 100

    # Edge over market implied probability
    implied_prob = (1 / avg_odds) if avg_odds > 0 else 0.5
    edge = hr - implied_prob

    # Sharpe (annualized by bets per season)
    ev = adj_pnl.mean()
    std = adj_pnl.std(ddof=1) if n > 1 else 1
    sharpe_bet = ev / std if std > 0 else 0
    n_seasons = df["season"].nunique()
    bps = n / n_seasons if n_seasons > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    mls = max_streak(hit, target=0)

    # Per-season adjusted ROI
    season_rois = []
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        s_hit = df.loc[sm, "nrfi"].values.astype(float)
        s_odds = est_odds.loc[sm].values
        s_pnl = np.where(s_hit, (s_odds - 1) * 100, -100)
        season_rois.append(s_pnl.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name,
        "bets": n,
        "bps": bps,
        "hit_rate": hr,
        "avg_ou": avg_ou,
        "est_odds": avg_odds,
        "adj_roi": adj_roi,
        "fixed_roi": fixed_roi,
        "edge": edge,
        "sharpe": sharpe,
        "mls": mls,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def print_header():
    print(
        f"  {'Filter':<50} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
        f"{'AvgOU':>6} {'EstOd':>5} {'AdjROI':>7} {'Edge':>6} "
        f"{'Shrp':>5} {'Flds':>5}"
    )
    print("-" * 110)


def print_row(m):
    if m is None:
        return
    marker = " ***" if m["adj_roi"] > 0 and m["edge"] > 0 else ""
    print(
        f"  {m['name']:<50} {m['bets']:5d} {m['bps']:4.0f} "
        f"{m['hit_rate']*100:5.1f}% {m['avg_ou']:5.2f} {m['est_odds']:5.3f} "
        f"{m['adj_roi']:+6.1f}% {m['edge']*100:+5.1f}pp "
        f"{m['sharpe']:5.2f} {m['seasons_pos']:>5}{marker}"
    )


# ========================================================================
# MAIN
# ========================================================================
def main():
    from src.data_loader import (
        PROCESSED_DIR,
        _map_team_code_to_retrosheet,
        add_derived_odds,
        apply_data_filters,
        load_all_seasons,
    )
    from src.features import build_all_features

    print("Loading games and building features...")
    games = load_all_seasons()
    games = apply_data_filters(games)
    games = add_derived_odds(games)
    enriched = build_all_features(games)
    df = enriched.copy()

    # Filter to real inning data (exclude 2004-2009 fake zeros)
    away_inn_sum = sum(
        df[f"away_inn_{i}"] for i in range(1, 10) if f"away_inn_{i}" in df.columns
    )
    home_inn_sum = sum(
        df[f"home_inn_{i}"] for i in range(1, 10) if f"home_inn_{i}" in df.columns
    )
    df = df[(away_inn_sum + home_inn_sum) > 0].copy()

    # Standard filters
    if "involves_col" in df.columns:
        df = df[~df["involves_col"]].copy()
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df = df[df["month"] != 4].copy()

    # NRFI outcome
    df["inn1_runs"] = df["away_inn_1"] + df["home_inn_1"]
    df["nrfi"] = df["inn1_runs"] == 0

    print(f"Games with inning data: {len(df)}")
    print(f"NRFI rate (unconditional): {df['nrfi'].mean()*100:.1f}%")

    # ── Merge BvP lineup features ────────────────────────────────────
    lineup_path = PROCESSED_DIR / "retrosheet" / "game_lineup_features.parquet"
    if lineup_path.exists():
        lineup = pd.read_parquet(lineup_path)
        lineup["date"] = pd.to_datetime(lineup["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_lu_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]),
                axis=1,
            )
            lu_cols = [
                c
                for c in lineup.columns
                if c.startswith("top3_") or c == "n_batters"
            ]
            lu_rename = {"team": f"_lu_{side}_team"}
            for c in lu_cols:
                lu_rename[c] = f"{c}_{side}"

            side_lu = lineup[["team", "date"] + lu_cols].rename(columns=lu_rename)
            side_lu = side_lu.drop_duplicates(
                subset=[f"_lu_{side}_team", "date"], keep="first"
            )
            df = df.merge(side_lu, on=[f"_lu_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_lu_{side}_team"])

        # Combined batter features
        for stat in [
            "obp_short", "obp_long", "k_rate_short", "k_rate_long",
            "hr_rate_short", "obp_vs_rhp", "k_rate_vs_rhp",
            "obp_vs_lhp", "k_rate_vs_lhp",
        ]:
            h_col = f"top3_{stat}_home"
            a_col = f"top3_{stat}_away"
            if h_col in df.columns and a_col in df.columns:
                df[f"top3_{stat}_combined"] = df[h_col] + df[a_col]

        n_bvp = df["top3_obp_short_home"].notna().sum()
        print(f"BvP merged: {n_bvp}/{len(df)} ({n_bvp/len(df)*100:.0f}%)")
    else:
        print("WARNING: No lineup features found.")

    # ── Merge 1st-inning BABIP ───────────────────────────────────────
    babip_path = PROCESSED_DIR / "retrosheet" / "first_inning_babip.parquet"
    if babip_path.exists():
        babip = pd.read_parquet(babip_path)
        babip["date"] = pd.to_datetime(babip["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_bb_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]),
                axis=1,
            )
            bb_rename = {
                "team": f"_bb_{side}_team",
                "top3_babip_inn1": f"top3_babip_inn1_{side}",
                "sp_babip_inn1": f"sp_babip_inn1_{side}",
            }
            side_bb = babip[
                ["team", "date", "top3_babip_inn1", "sp_babip_inn1"]
            ].rename(columns=bb_rename)
            side_bb = side_bb.drop_duplicates(
                subset=[f"_bb_{side}_team", "date"], keep="first"
            )
            df = df.merge(side_bb, on=[f"_bb_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_bb_{side}_team"])

        for stat in ["top3_babip_inn1", "sp_babip_inn1"]:
            h_col = f"{stat}_home"
            a_col = f"{stat}_away"
            if h_col in df.columns and a_col in df.columns:
                df[f"{stat}_combined"] = df[h_col] + df[a_col]

        n_bb = df["top3_babip_inn1_home"].notna().sum()
        print(f"BABIP merged: {n_bb}/{len(df)} ({n_bb/len(df)*100:.0f}%)")
    else:
        print("WARNING: No BABIP features found.")

    # ── Build pitcher SUM composites ─────────────────────────────────
    composites_built = []
    for col, h_col, a_col in [
        ("sp_ra_combined_short", "home_sp_ra_short", "away_sp_ra_short"),
        ("sp_ra_combined_long", "home_sp_ra_long", "away_sp_ra_long"),
        ("sp_fi_ra_combined", "home_sp_fi_ra_short", "away_sp_fi_ra_short"),
        ("sp_fi_ra_combined_long", "home_sp_fi_ra_long", "away_sp_fi_ra_long"),
        ("starter_fip_combined", "home_sp_fip_short", "away_sp_fip_short"),
        ("starter_whip_combined", "home_sp_whip_short", "away_sp_whip_short"),
        ("starter_kbb_combined", "home_sp_kbb_short", "away_sp_kbb_short"),
        ("sp_fi_momentum_combined", "home_sp_fi_momentum", "away_sp_fi_momentum"),
        ("sp_ra_momentum_combined", "home_sp_ra_momentum", "away_sp_ra_momentum"),
    ]:
        if h_col in df.columns and a_col in df.columns:
            df[col] = df[h_col] + df[a_col]
            composites_built.append(col)

    # Team SUM composites
    for col, h_col, a_col in [
        ("combined_rpg", "rpg_home", "rpg_away"),
        ("combined_rpg_last10", "rpg_last10_home", "rpg_last10_away"),
        ("combined_rapg", "rapg_home", "rapg_away"),
    ]:
        if h_col in df.columns and a_col in df.columns:
            df[col] = df[h_col] + df[a_col]
            composites_built.append(col)

    # Effective OBP (true handedness matchup)
    if all(
        c in df.columns
        for c in [
            "away_sp_hand", "home_sp_hand",
            "top3_obp_vs_rhp_home", "top3_obp_vs_lhp_home",
            "top3_obp_vs_rhp_away", "top3_obp_vs_lhp_away",
        ]
    ):
        df["effective_obp_home"] = np.where(
            df["away_sp_hand"] == "R",
            df["top3_obp_vs_rhp_home"],
            df["top3_obp_vs_lhp_home"],
        )
        df["effective_obp_away"] = np.where(
            df["home_sp_hand"] == "R",
            df["top3_obp_vs_rhp_away"],
            df["top3_obp_vs_lhp_away"],
        )
        df["effective_obp_combined"] = df["effective_obp_home"] + df["effective_obp_away"]
        composites_built.append("effective_obp_combined")

    print(f"Composites built: {len(composites_built)}")
    for c in composites_built:
        n_ok = df[c].notna().sum()
        print(f"  {c}: {n_ok}/{len(df)}")

    # ================================================================
    # PHASE 1: SINGLE-FEATURE SWEEP
    # ================================================================
    print(f"\n{'='*110}")
    print("PHASE 1: SINGLE-FEATURE SWEEP (adjusted ROI)")
    print(f"{'='*110}")

    # NRFI filter directions are INVERTED from YRFI:
    #   Pitcher features: LOW values = strong pitchers = more NRFI
    #   Batter features: LOW OBP/BABIP = weak batters; HIGH K-rate = strikeout-prone
    #   Team features: LOW RPG = low-scoring environment
    feature_sweeps = []

    # Pitcher features (LOW -> fewer 1st-inn runs -> NRFI)
    for feat in ["sp_fi_ra_combined", "sp_fi_ra_combined_long"]:
        if feat in df.columns:
            feature_sweeps.append((feat, "<", "pct", [50, 40, 30, 25, 20, 10]))

    if "sp_ra_combined_short" in df.columns:
        feature_sweeps.append(("sp_ra_combined_short", "<", "abs", [9.0, 8.5, 8.0, 7.5, 7.0]))

    for feat in ["starter_fip_combined", "starter_whip_combined"]:
        if feat in df.columns:
            feature_sweeps.append((feat, "<", "pct", [50, 40, 30, 25, 20, 10]))

    # High K/BB = dominant pitchers = NRFI
    if "starter_kbb_combined" in df.columns:
        feature_sweeps.append(("starter_kbb_combined", ">", "pct", [50, 60, 70, 75, 90]))

    # Negative momentum = pitchers improving = NRFI
    for feat in ["sp_fi_momentum_combined", "sp_ra_momentum_combined"]:
        if feat in df.columns:
            feature_sweeps.append((feat, "<", "abs_pct", [0.0, "p40", "p25", "p10"]))

    # Batter features (LOW OBP/BABIP -> weaker hitters -> NRFI)
    for feat in ["top3_obp_short_combined", "top3_babip_inn1_combined"]:
        if feat in df.columns:
            feature_sweeps.append((feat, "<", "pct", [50, 40, 30, 25, 10]))

    if "effective_obp_combined" in df.columns:
        feature_sweeps.append(("effective_obp_combined", "<", "pct", [50, 40, 30, 25, 10]))

    # High K-rate = strikeout-prone = NRFI
    if "top3_k_rate_short_combined" in df.columns:
        feature_sweeps.append(("top3_k_rate_short_combined", ">", "pct", [50, 60, 70, 75, 90]))

    # Low HR rate = fewer long balls = NRFI
    if "top3_hr_rate_short_combined" in df.columns:
        feature_sweeps.append(("top3_hr_rate_short_combined", "<", "pct", [50, 25, 10]))

    # Team features (LOW RPG -> low-scoring -> NRFI)
    for feat in ["combined_rpg", "combined_rpg_last10"]:
        if feat in df.columns:
            feature_sweeps.append((feat, "<", "pct", [50, 40, 25]))

    phase1_results = []
    phase1_survivors = []

    baseline = metrics_adjusted(df, "No filters (all games)")
    phase1_results.append(baseline)

    for feat, direction, thresh_type, thresholds in feature_sweeps:
        for t in thresholds:
            if thresh_type == "pct":
                q = df[feat].quantile(t / 100)
                label = f"p{t}"
            elif thresh_type == "abs":
                q = t
                label = f"{t}"
            elif thresh_type == "abs_pct":
                if isinstance(t, str) and t.startswith("p"):
                    pct = int(t[1:])
                    q = df[feat].quantile(pct / 100)
                    label = t
                else:
                    q = t
                    label = f"{t}"

            if direction == ">":
                filt = df[df[feat] > q]
                name = f"{feat}>{q:.2f} ({label})"
            else:
                filt = df[df[feat] < q]
                name = f"{feat}<{q:.2f} ({label})"

            m = metrics_adjusted(filt, name, min_bets=50)
            if m is not None:
                phase1_results.append(m)
                if m["adj_roi"] > 0 and m["edge"] > 0.015 and m["bets"] >= 500:
                    phase1_survivors.append((feat, direction, q, m))

    print_header()
    for m in phase1_results:
        print_row(m)

    phase1_survivors.sort(key=lambda x: -x[3]["adj_roi"])
    print(f"\n  Phase 1 survivors (adj_roi>0, edge>1.5pp, bets>=500): {len(phase1_survivors)}")
    for feat, direction, q, m in phase1_survivors:
        op = ">" if direction == ">" else "<"
        print(f"    {feat}{op}{q:.2f}: adj_roi={m['adj_roi']:+.1f}%, edge={m['edge']*100:+.1f}pp, bets={m['bets']}")

    # ================================================================
    # PHASE 2: TWO-WAY COMBINATIONS
    # ================================================================
    # Build best threshold per feature (by adj_roi)
    best_per_feat = {}
    for feat, direction, thresh_type, thresholds in feature_sweeps:
        for t in thresholds:
            if thresh_type == "pct":
                q = df[feat].quantile(t / 100)
            elif thresh_type == "abs":
                q = t
            elif thresh_type == "abs_pct":
                if isinstance(t, str) and t.startswith("p"):
                    q = df[feat].quantile(int(t[1:]) / 100)
                else:
                    q = t

            if direction == ">":
                filt = df[df[feat] > q]
            else:
                filt = df[df[feat] < q]

            m = metrics_adjusted(filt, "", min_bets=50)
            if m is None:
                continue
            key = feat
            if key not in best_per_feat or m["adj_roi"] > best_per_feat[key][3]["adj_roi"]:
                best_per_feat[key] = (feat, direction, q, m)

    top_survivors = sorted(best_per_feat.values(), key=lambda x: -x[3]["adj_roi"])
    print(f"\n  Best single threshold per feature (by adj_roi):")
    for feat, direction, q, m in top_survivors:
        op = ">" if direction == ">" else "<"
        print(f"    {feat}{op}{q:.2f}: adj_roi={m['adj_roi']:+.1f}%, edge={m['edge']*100:+.1f}pp, bets={m['bets']}, avg_ou={m['avg_ou']:.2f}")

    print(f"\n{'='*110}")
    print(f"PHASE 2: TWO-WAY COMBINATIONS (all {len(top_survivors)} features)")
    print(f"{'='*110}")

    phase2_results = []
    phase2_survivors = []

    for i in range(len(top_survivors)):
        for j in range(i + 1, len(top_survivors)):
            f1, d1, q1, _ = top_survivors[i]
            f2, d2, q2, _ = top_survivors[j]

            # Skip if same feature family
            if f1.split("_")[0:3] == f2.split("_")[0:3]:
                continue

            mask1 = df[f1] > q1 if d1 == ">" else df[f1] < q1
            mask2 = df[f2] > q2 if d2 == ">" else df[f2] < q2
            filt = df[mask1 & mask2]

            op1 = ">" if d1 == ">" else "<"
            op2 = ">" if d2 == ">" else "<"

            n1 = f1.replace("_combined", "").replace("_short", "").replace("starter_", "")
            n2 = f2.replace("_combined", "").replace("_short", "").replace("starter_", "")
            name = f"{n1}{op1}{q1:.1f} + {n2}{op2}{q2:.1f}"

            m = metrics_adjusted(filt, name, min_bets=50)
            if m is not None:
                phase2_results.append(m)
                if m["adj_roi"] > 0 and m["bets"] >= 100:
                    phase2_survivors.append((f1, d1, q1, f2, d2, q2, m))

    phase2_results.sort(key=lambda x: -x["adj_roi"])

    print_header()
    for m in phase2_results[:50]:
        print_row(m)

    phase2_survivors.sort(key=lambda x: -x[6]["adj_roi"])
    print(f"\n  Phase 2 survivors (adj_roi>0%, bets>=100): {len(phase2_survivors)}")
    for f1, d1, q1, f2, d2, q2, m in phase2_survivors[:10]:
        print(f"    {m['name']}: adj_roi={m['adj_roi']:+.1f}%, edge={m['edge']*100:+.1f}pp, bets={m['bets']}, avg_ou={m['avg_ou']:.2f}")

    # ================================================================
    # PHASE 3: THREE-WAY COMBINATIONS
    # ================================================================
    if phase2_survivors:
        print(f"\n{'='*110}")
        print(f"PHASE 3: THREE-WAY COMBINATIONS")
        print(f"{'='*110}")

        phase3_results = []

        for f1, d1, q1, f2, d2, q2, _ in phase2_survivors[:8]:
            for f3, d3, q3, _ in top_survivors:
                if f3 == f1 or f3 == f2:
                    continue
                if f3.split("_")[0:2] == f1.split("_")[0:2]:
                    continue
                if f3.split("_")[0:2] == f2.split("_")[0:2]:
                    continue

                mask1 = df[f1] > q1 if d1 == ">" else df[f1] < q1
                mask2 = df[f2] > q2 if d2 == ">" else df[f2] < q2
                mask3 = df[f3] > q3 if d3 == ">" else df[f3] < q3
                filt = df[mask1 & mask2 & mask3]

                op3 = ">" if d3 == ">" else "<"
                n1 = f1.replace("_combined", "").replace("_short", "").replace("starter_", "")
                n2 = f2.replace("_combined", "").replace("_short", "").replace("starter_", "")
                n3 = f3.replace("_combined", "").replace("_short", "").replace("starter_", "")
                name = f"{n1}+{n2}+{n3}{op3}{q3:.1f}"

                m = metrics_adjusted(filt, name, min_bets=50)
                if m is not None:
                    phase3_results.append(m)

        phase3_results.sort(key=lambda x: -x["adj_roi"])
        print_header()
        for m in phase3_results[:40]:
            print_row(m)

    # ================================================================
    # PHASE 4: VALIDATION
    # ================================================================
    print(f"\n{'='*110}")
    print("PHASE 4: VALIDATION")
    print(f"{'='*110}")

    # Walk-forward: TRAIN 2010-2017, TEST 2018+
    train = df[df["season"] <= 2017]
    test = df[df["season"] >= 2018]
    print(f"\n  Walk-forward split: TRAIN {train['season'].min()}-{train['season'].max()} ({len(train)} games)")
    print(f"                      TEST  {test['season'].min()}-{test['season'].max()} ({len(test)} games)")

    # Phase 2 top strategies on TEST
    print(f"\n  Phase 2 top strategies on TEST:")
    print_header()
    for f1, d1, q1, f2, d2, q2, m_full in phase2_survivors[:10]:
        mask1 = test[f1] > q1 if d1 == ">" else test[f1] < q1
        mask2 = test[f2] > q2 if d2 == ">" else test[f2] < q2
        filt = test[mask1 & mask2]
        m_test = metrics_adjusted(filt, f"[TEST] {m_full['name']}", min_bets=20)
        print_row(m_test)

    # Bootstrap CI
    print(f"\n  Bootstrap 95% CI (1000 resamples):")
    boot_targets = phase2_survivors[:5]
    for f1, d1, q1, f2, d2, q2, m_full in boot_targets:
        mask1 = df[f1] > q1 if d1 == ">" else df[f1] < q1
        mask2 = df[f2] > q2 if d2 == ">" else df[f2] < q2
        filt = df[mask1 & mask2].dropna(subset=["close_ou"]).copy()
        if len(filt) < 30:
            continue

        hit = filt["nrfi"].values.astype(float)
        odds_arr = estimate_nrfi_odds(filt["close_ou"]).values
        adj_pnl = np.where(hit, (odds_arr - 1) * 100, -100)

        boot_rois = []
        rng = np.random.default_rng(42)
        for _ in range(1000):
            idx = rng.choice(len(adj_pnl), size=len(adj_pnl), replace=True)
            sample_pnl = adj_pnl[idx]
            boot_rois.append(sample_pnl.sum() / (len(sample_pnl) * 100) * 100)

        ci_lo, ci_hi = np.percentile(boot_rois, [2.5, 97.5])
        sig = "SIGNIFICANT" if ci_lo > 0 else ""
        print(
            f"    {m_full['name']:<50} "
            f"adj_roi={m_full['adj_roi']:+.1f}%  "
            f"95% CI: [{ci_lo:+.1f}%, {ci_hi:+.1f}%]  {sig}"
        )

    # Per-season breakdown for top strategy
    if phase2_survivors:
        f1, d1, q1, f2, d2, q2, m_top = phase2_survivors[0]
        mask1 = df[f1] > q1 if d1 == ">" else df[f1] < q1
        mask2 = df[f2] > q2 if d2 == ">" else df[f2] < q2
        filt = df[mask1 & mask2]

        print(f"\n  Per-season: {m_top['name']}")
        print(f"  {'Season':>6} {'Bets':>5} {'Hit%':>6} {'AvgOU':>6} {'AdjROI':>7}")
        for s in sorted(filt["season"].unique()):
            sb = filt[filt["season"] == s]
            if len(sb) < 3:
                continue
            sm = metrics_adjusted(sb, "", min_bets=3)
            if sm:
                print(f"  {s:>6} {sm['bets']:5d} {sm['hit_rate']*100:5.1f}% {sm['avg_ou']:5.2f} {sm['adj_roi']:+6.1f}%")

    # Monthly breakdown
    if phase2_survivors:
        f1, d1, q1, f2, d2, q2, m_top = phase2_survivors[0]
        mask1 = df[f1] > q1 if d1 == ">" else df[f1] < q1
        mask2 = df[f2] > q2 if d2 == ">" else df[f2] < q2
        filt = df[mask1 & mask2]

        print(f"\n  Monthly: {m_top['name']}")
        for mo in sorted(filt["month"].unique()):
            mb = filt[filt["month"] == mo]
            if len(mb) < 10:
                continue
            sm = metrics_adjusted(mb, "", min_bets=10)
            if sm:
                print(f"    Month {mo:2d}: {sm['bets']:5d} bets  {sm['hit_rate']*100:5.1f}%  adj_roi {sm['adj_roi']:+.1f}%")

    # ================================================================
    # HYPOTHESIS SCORECARD
    # ================================================================
    print(f"\n{'='*110}")
    print("HYPOTHESIS SCORECARD")
    print(f"{'='*110}")

    def best_single(feat):
        for m in phase1_results:
            if m and feat in m["name"]:
                return m
        return None

    # H1: 1st-inn pitcher features beat general pitcher features for NRFI
    h1_fi = best_single("sp_fi_ra")
    h1_ra = best_single("sp_ra_combined")
    if h1_fi and h1_ra:
        winner = "sp_fi_ra" if h1_fi["adj_roi"] > h1_ra["adj_roi"] else "sp_ra"
        print(f"  H1 (1st-inn > general pitcher for NRFI): sp_fi_ra={h1_fi['adj_roi']:+.1f}% vs sp_ra={h1_ra['adj_roi']:+.1f}% -> {winner}")

    # H2: Effective OBP (vs-hand) beats generic OBP for NRFI
    h2_eff = best_single("effective_obp")
    h2_gen = best_single("top3_obp_short")
    if h2_eff and h2_gen:
        winner = "effective_obp" if h2_eff["adj_roi"] > h2_gen["adj_roi"] else "generic_obp"
        print(f"  H2 (effective OBP > generic for NRFI): eff={h2_eff['adj_roi']:+.1f}% vs gen={h2_gen['adj_roi']:+.1f}% -> {winner}")

    # H3: K-rate identifies strikeout-prone lineups for NRFI
    h3_k = best_single("k_rate_short")
    if h3_k:
        print(f"  H3 (high K-rate -> NRFI): best adj_roi={h3_k['adj_roi']:+.1f}%")

    # H4: Negative momentum = pitchers improving -> NRFI
    h4_mom = best_single("sp_fi_momentum")
    if h4_mom:
        print(f"  H4 (negative momentum -> NRFI): sp_fi_momentum best adj_roi={h4_mom['adj_roi']:+.1f}%")

    # H5: High-OU NRFI bets outperform low-OU after odds adjustment
    # (Because high-OU games give better NRFI odds)
    low_ou = df[df["close_ou"] < 8.5]
    high_ou = df[df["close_ou"] >= 8.5]
    m_low = metrics_adjusted(low_ou, "OU<8.5")
    m_high = metrics_adjusted(high_ou, "OU>=8.5")
    if m_low and m_high:
        winner = "high-OU" if m_high["adj_roi"] > m_low["adj_roi"] else "low-OU"
        print(f"  H5 (high-OU NRFI > low-OU after adj): low={m_low['adj_roi']:+.1f}% vs high={m_high['adj_roi']:+.1f}% -> {winner}")

    print(f"\n{'='*110}")
    print("DONE")
    print(f"{'='*110}")


if __name__ == "__main__":
    main()
