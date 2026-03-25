"""NRFI/YRFI two-sided backtest with batter-vs-pitcher features.

Two-sided strategy:
  - NRFI (No Run First Inning): bet when conditions favor scoreless 1st
  - YRFI (Yes Run First Inning): bet when conditions favor runs in 1st
  - Skip the uncertain middle zone

Assumed odds: 1.85 for both sides (breakeven ~54.1%).

Features: pitcher quality (sp_fi_ra, sp_ra, FIP, WHIP) + batter quality
(top-3 lineup OBP, K-rate, vs-hand splits).

Usage:
    python scripts/run_nrfi_backtest.py
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

NRFI_ODDS = 1.85  # assumed decimal odds
BREAKEVEN = 1 / NRFI_ODDS


def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def metrics(df, hit_col, name):
    df = df.sort_values("date").copy()
    n = len(df)
    if n < 20:
        return None

    hit = df[hit_col].values.astype(float)
    pnl = np.where(hit, (NRFI_ODDS - 1) * 100, -100)
    cum_pnl = np.cumsum(pnl)

    hr = hit.mean()
    roi = pnl.sum() / (n * 100) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    b = NRFI_ODDS - 1
    kelly_full = (hr * b - (1 - hr)) / b if b > 0 else 0
    kelly_full = max(0, kelly_full)
    mls = max_streak(hit, target=0)

    season_rois = []
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(df.loc[sm, hit_col].values, (NRFI_ODDS - 1) * 100, -100)
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name,
        "bets": n,
        "bets_per_season": n / df["season"].nunique(),
        "hit_rate": hr,
        "roi": roi,
        "sharpe": sharpe,
        "kelly_half": kelly_full / 2,
        "max_loss_streak": mls,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
    }


def print_row(m):
    if m is None:
        return
    print(
        f"  {m['name']:<55} {m['bets']:5d} {m['bets_per_season']:4.0f} "
        f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
        f"{m['sharpe']:6.3f} {m['seasons_pos']:>6}"
    )


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
    away_inn_sum = sum(df[f"away_inn_{i}"] for i in range(1, 10) if f"away_inn_{i}" in df.columns)
    home_inn_sum = sum(df[f"home_inn_{i}"] for i in range(1, 10) if f"home_inn_{i}" in df.columns)
    df = df[(away_inn_sum + home_inn_sum) > 0].copy()

    # Standard filters (no Colorado, no April)
    if "involves_col" in df.columns:
        df = df[~df["involves_col"]].copy()
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df = df[df["month"] != 4].copy()

    print(f"Games with inning data: {len(df)}")

    # NRFI outcome
    df["inn1_runs"] = df["away_inn_1"] + df["home_inn_1"]
    df["nrfi"] = df["inn1_runs"] == 0

    # ── Merge BvP lineup features ──────────────────────────────────────
    lineup_path = PROCESSED_DIR / "retrosheet" / "game_lineup_features.parquet"
    if lineup_path.exists():
        lineup = pd.read_parquet(lineup_path)
        lineup["date"] = pd.to_datetime(lineup["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        # Map team codes for matching
        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_lu_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]), axis=1
            )
            lu_cols = [c for c in lineup.columns if c.startswith("top3_") or c == "n_batters"]
            lu_rename = {"team": f"_lu_{side}_team"}
            for c in lu_cols:
                lu_rename[c] = f"{c}_{side}"

            side_lu = lineup[["team", "date"] + lu_cols].rename(columns=lu_rename)
            side_lu = side_lu.drop_duplicates(subset=[f"_lu_{side}_team", "date"], keep="first")
            df = df.merge(side_lu, on=[f"_lu_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_lu_{side}_team"])

        # Combined features (NRFI = both lineups matter)
        for stat in ["obp_short", "obp_long", "k_rate_short", "k_rate_long",
                      "hr_rate_short", "obp_vs_rhp", "k_rate_vs_rhp",
                      "obp_vs_lhp", "k_rate_vs_lhp"]:
            h_col = f"top3_{stat}_home"
            a_col = f"top3_{stat}_away"
            if h_col in df.columns and a_col in df.columns:
                df[f"top3_{stat}_combined"] = df[h_col] + df[a_col]

        # "Effective" OBP vs actual starter hand
        # Home batters face away starter → use home batters' vs-hand matching away pitcher
        # This requires knowing the starter hand, which is in pitcher_features
        # For now: use the combined OBP (overall) as primary signal

        n_bvp = df["top3_obp_short_home"].notna().sum()
        print(f"BvP features merged: {n_bvp}/{len(df)} games ({n_bvp/len(df)*100:.0f}%)")
    else:
        print("WARNING: No lineup features found. Run scripts/build_retrosheet_batters.py first.")

    # ── Merge 1st-inning BABIP features ──────────────────────────────
    babip_path = PROCESSED_DIR / "retrosheet" / "first_inning_babip.parquet"
    if babip_path.exists():
        babip = pd.read_parquet(babip_path)
        babip["date"] = pd.to_datetime(babip["date"]).dt.normalize()
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()

        for side, team_col in [("home", "home_team"), ("away", "away_team")]:
            df[f"_bb_{side}_team"] = df.apply(
                lambda r: _map_team_code_to_retrosheet(r[team_col], r["season"]), axis=1
            )
            bb_rename = {
                "team": f"_bb_{side}_team",
                "top3_babip_inn1": f"top3_babip_inn1_{side}",
                "sp_babip_inn1": f"sp_babip_inn1_{side}",
            }
            side_bb = babip[["team", "date", "top3_babip_inn1", "sp_babip_inn1"]].rename(columns=bb_rename)
            side_bb = side_bb.drop_duplicates(subset=[f"_bb_{side}_team", "date"], keep="first")
            df = df.merge(side_bb, on=[f"_bb_{side}_team", "date"], how="left")
            df = df.drop(columns=[f"_bb_{side}_team"])

        # Combined BABIP features
        # top3_babip: both lineups' top-3 batter BABIP (high = more contact hits)
        for stat in ["top3_babip_inn1", "sp_babip_inn1"]:
            h_col = f"{stat}_home"
            a_col = f"{stat}_away"
            if h_col in df.columns and a_col in df.columns:
                df[f"{stat}_combined"] = df[h_col] + df[a_col]

        n_bb = df["top3_babip_inn1_home"].notna().sum()
        print(f"1st-inning BABIP merged: {n_bb}/{len(df)} games ({n_bb/len(df)*100:.0f}%)")
    else:
        print("WARNING: No BABIP features. Run scripts/build_retrosheet_batters.py first.")

    # ========================================================================
    # BASELINE
    # ========================================================================
    print(f"\n{'='*80}")
    print(f"NRFI BACKTEST (odds {NRFI_ODDS}, breakeven {BREAKEVEN*100:.1f}%)")
    print(f"{'='*80}")

    nrfi_rate = df["nrfi"].mean()
    print(f"  Total games: {len(df)}")
    print(f"  NRFI rate (unconditional): {nrfi_rate*100:.1f}%")
    marker = " *** ABOVE BREAKEVEN" if nrfi_rate > BREAKEVEN else ""
    print(f"  vs breakeven {BREAKEVEN*100:.1f}%{marker}")

    # ========================================================================
    # PITCHER-ONLY FILTERS
    # ========================================================================
    print(f"\n{'='*80}")
    print("PITCHER-ONLY FILTERS")
    print(f"{'='*80}")

    results = []
    m = metrics(df, "nrfi", "No filters (all games)")
    results.append(m)

    # sp_fi_ra_combined (1st inning RA of both starters)
    if "sp_fi_ra_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p25", 25), ("p10", 10)]:
            q = df["sp_fi_ra_combined"].quantile(pct / 100)
            filt = df[df["sp_fi_ra_combined"] < q]
            m = metrics(filt, "nrfi", f"sp_fi_ra<{q:.2f} ({pct_label})")
            results.append(m)

    # sp_ra_combined_short (overall RA)
    if "sp_ra_combined_short" in df.columns:
        for thresh in [7.0, 7.5, 8.0, 8.5]:
            filt = df[df["sp_ra_combined_short"] < thresh]
            m = metrics(filt, "nrfi", f"sp_ra<{thresh:.1f}")
            results.append(m)

    # close_ou (low O/U line)
    if "close_ou" in df.columns:
        for thresh in [7.0, 7.5, 8.0, 8.5]:
            filt = df[df["close_ou"] <= thresh]
            m = metrics(filt, "nrfi", f"close_ou<={thresh:.1f}")
            results.append(m)

    print(f"\n{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
          f"{'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'Flds':>6}")
    print("-" * 100)
    for m in results:
        print_row(m)

    # ========================================================================
    # BvP FILTERS
    # ========================================================================
    if "top3_obp_short_combined" in df.columns:
        print(f"\n{'='*80}")
        print("BvP FILTERS (top-3 lineup quality)")
        print(f"{'='*80}")

        bvp_results = []
        m = metrics(df, "nrfi", "No filters (baseline)")
        bvp_results.append(m)

        # Low combined top-3 OBP (weak lineups)
        for pct_label, pct in [("p50", 50), ("p25", 25), ("p10", 10)]:
            q = df["top3_obp_short_combined"].quantile(pct / 100)
            filt = df[df["top3_obp_short_combined"] < q]
            m = metrics(filt, "nrfi", f"top3_obp<{q:.3f} ({pct_label})")
            bvp_results.append(m)

        # High combined K-rate (strikeout-prone lineups)
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["top3_k_rate_short_combined"].quantile(pct / 100)
            filt = df[df["top3_k_rate_short_combined"] > q]
            m = metrics(filt, "nrfi", f"top3_k_rate>{q:.3f} ({pct_label})")
            bvp_results.append(m)

        # Low combined HR rate (no power)
        if "top3_hr_rate_short_combined" in df.columns:
            for pct_label, pct in [("p50", 50), ("p25", 25)]:
                q = df["top3_hr_rate_short_combined"].quantile(pct / 100)
                filt = df[df["top3_hr_rate_short_combined"] < q]
                m = metrics(filt, "nrfi", f"top3_hr_rate<{q:.4f} ({pct_label})")
                bvp_results.append(m)

        print(f"\n{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
              f"{'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'Flds':>6}")
        print("-" * 100)
        for m in bvp_results:
            print_row(m)

    # ========================================================================
    # COMBINED: PITCHER + BvP
    # ========================================================================
    if "top3_obp_short_combined" in df.columns and "sp_ra_combined_short" in df.columns:
        print(f"\n{'='*80}")
        print("COMBINED: PITCHER + BvP FILTER GRID")
        print(f"{'='*80}")

        combos = []

        # sp_ra x top3_obp
        for sp in [7.0, 7.5, 8.0]:
            for obp_pct in [50, 25]:
                obp_q = df["top3_obp_short_combined"].quantile(obp_pct / 100)
                filt = df[(df["sp_ra_combined_short"] < sp) & (df["top3_obp_short_combined"] < obp_q)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt["nrfi"].mean()
                roi = np.where(filt["nrfi"], (NRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                combos.append((f"sp_ra<{sp:.0f} + obp<{obp_q:.3f}(p{obp_pct})", n, n/filt["season"].nunique(), hr, roi))

        # sp_ra x top3_k_rate
        for sp in [7.0, 7.5, 8.0]:
            for k_pct in [50, 75]:
                k_q = df["top3_k_rate_short_combined"].quantile(k_pct / 100)
                filt = df[(df["sp_ra_combined_short"] < sp) & (df["top3_k_rate_short_combined"] > k_q)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt["nrfi"].mean()
                roi = np.where(filt["nrfi"], (NRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                combos.append((f"sp_ra<{sp:.0f} + k_rate>{k_q:.3f}(p{k_pct})", n, n/filt["season"].nunique(), hr, roi))

        # close_ou x top3_obp
        for ou in [7.5, 8.0, 8.5]:
            for obp_pct in [50, 25]:
                obp_q = df["top3_obp_short_combined"].quantile(obp_pct / 100)
                filt = df[(df["close_ou"] <= ou) & (df["top3_obp_short_combined"] < obp_q)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt["nrfi"].mean()
                roi = np.where(filt["nrfi"], (NRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                combos.append((f"ou<={ou:.1f} + obp<{obp_q:.3f}(p{obp_pct})", n, n/filt["season"].nunique(), hr, roi))

        # sp_fi_ra + top3_k_rate (best 1st-inn pitchers + K-prone batters)
        if "sp_fi_ra_combined" in df.columns:
            fi_med = df["sp_fi_ra_combined"].median()
            for k_pct in [50, 75]:
                k_q = df["top3_k_rate_short_combined"].quantile(k_pct / 100)
                filt = df[(df["sp_fi_ra_combined"] < fi_med) & (df["top3_k_rate_short_combined"] > k_q)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt["nrfi"].mean()
                roi = np.where(filt["nrfi"], (NRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                combos.append((f"sp_fi_ra<{fi_med:.2f} + k_rate>{k_q:.3f}(p{k_pct})", n, n/filt["season"].nunique(), hr, roi))

        # Triple: sp_ra + close_ou + top3_obp
        for sp in [7.5, 8.0]:
            for ou in [8.0, 8.5]:
                for obp_pct in [50, 25]:
                    obp_q = df["top3_obp_short_combined"].quantile(obp_pct / 100)
                    filt = df[
                        (df["sp_ra_combined_short"] < sp)
                        & (df["close_ou"] <= ou)
                        & (df["top3_obp_short_combined"] < obp_q)
                    ]
                    n = len(filt)
                    if n < 30:
                        continue
                    hr = filt["nrfi"].mean()
                    roi = np.where(filt["nrfi"], (NRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    combos.append((f"sp_ra<{sp:.0f}+ou<={ou:.1f}+obp<{obp_q:.3f}(p{obp_pct})", n, n/filt["season"].nunique(), hr, roi))

        if combos:
            print(f"{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Hit%':>6} {'ROI':>7}")
            print("-" * 80)
            for name, n, bps, hr, roi in sorted(combos, key=lambda x: -x[4]):
                marker = " ***" if hr > BREAKEVEN and roi > 0 else ""
                print(f"  {name:<53} {n:5d} {bps:4.0f} {hr*100:5.1f}% {roi:+6.1f}%{marker}")

    # ========================================================================
    # YRFI SIDE (bet on runs in 1st inning)
    # ========================================================================
    YRFI_ODDS = NRFI_ODDS  # symmetric 1.85
    df["yrfi"] = ~df["nrfi"]  # inverse

    # Build pitcher composites (SUM-based) — not in build_all_features
    for col, h_col, a_col in [
        ("sp_ra_combined_short", "home_sp_ra_short", "away_sp_ra_short"),
        ("sp_fi_ra_combined", "home_sp_fi_ra_short", "away_sp_fi_ra_short"),
        ("starter_fip_combined", "home_sp_fip_short", "away_sp_fip_short"),
        ("starter_whip_combined", "home_sp_whip_short", "away_sp_whip_short"),
        ("starter_kbb_combined", "home_sp_kbb_short", "away_sp_kbb_short"),
    ]:
        if h_col in df.columns and a_col in df.columns:
            df[col] = df[h_col] + df[a_col]
            n_ok = df[col].notna().sum()
            print(f"  Built {col}: {n_ok}/{len(df)} non-null")

    print(f"\n{'='*80}")
    print(f"YRFI BACKTEST (odds {YRFI_ODDS}, breakeven {BREAKEVEN*100:.1f}%)")
    print(f"{'='*80}")

    yrfi_rate = df["yrfi"].mean()
    print(f"  YRFI rate (unconditional): {yrfi_rate*100:.1f}%")

    yrfi_results = []
    m = metrics(df, "yrfi", "No filters (all games)")
    yrfi_results.append(m)

    # High sp_ra (both starters bad)
    if "sp_ra_combined_short" in df.columns:
        for thresh in [9.0, 9.5, 10.0, 10.5, 11.0]:
            filt = df[df["sp_ra_combined_short"] > thresh]
            m = metrics(filt, "yrfi", f"sp_ra>{thresh:.1f}")
            yrfi_results.append(m)

    # High close_ou (market expects many runs)
    if "close_ou" in df.columns:
        for thresh in [9.0, 9.5, 10.0, 10.5]:
            filt = df[df["close_ou"] >= thresh]
            m = metrics(filt, "yrfi", f"close_ou>={thresh:.1f}")
            yrfi_results.append(m)

    # High 1st-inning RA (both pitchers historically leak in 1st)
    if "sp_fi_ra_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["sp_fi_ra_combined"].quantile(pct / 100)
            filt = df[df["sp_fi_ra_combined"] > q]
            m = metrics(filt, "yrfi", f"sp_fi_ra>{q:.2f} ({pct_label})")
            yrfi_results.append(m)

    # High top-3 OBP (strong lineups)
    if "top3_obp_short_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["top3_obp_short_combined"].quantile(pct / 100)
            filt = df[df["top3_obp_short_combined"] > q]
            m = metrics(filt, "yrfi", f"top3_obp>{q:.3f} ({pct_label})")
            yrfi_results.append(m)

    # Low K-rate (batters make contact)
    if "top3_k_rate_short_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p25", 25), ("p10", 10)]:
            q = df["top3_k_rate_short_combined"].quantile(pct / 100)
            filt = df[df["top3_k_rate_short_combined"] < q]
            m = metrics(filt, "yrfi", f"top3_k_rate<{q:.3f} ({pct_label})")
            yrfi_results.append(m)

    # High FIP combined (bad starters -> more 1st inning runs)
    if "starter_fip_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["starter_fip_combined"].quantile(pct / 100)
            filt = df[df["starter_fip_combined"] > q]
            m = metrics(filt, "yrfi", f"fip_combined>{q:.2f} ({pct_label})")
            yrfi_results.append(m)
        # Also try absolute thresholds
        for thresh in [8.0, 8.5, 9.0, 9.5, 10.0]:
            filt = df[df["starter_fip_combined"] > thresh]
            m = metrics(filt, "yrfi", f"fip_combined>{thresh:.1f}")
            yrfi_results.append(m)

    # High WHIP combined (bad starters leak baserunners)
    if "starter_whip_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["starter_whip_combined"].quantile(pct / 100)
            filt = df[df["starter_whip_combined"] > q]
            m = metrics(filt, "yrfi", f"whip_combined>{q:.2f} ({pct_label})")
            yrfi_results.append(m)
        for thresh in [2.4, 2.6, 2.8, 3.0]:
            filt = df[df["starter_whip_combined"] > thresh]
            m = metrics(filt, "yrfi", f"whip_combined>{thresh:.1f}")
            yrfi_results.append(m)

    # Low K/BB combined (poor command -> walks + hits)
    if "starter_kbb_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p25", 25), ("p10", 10)]:
            q = df["starter_kbb_combined"].quantile(pct / 100)
            filt = df[df["starter_kbb_combined"] < q]
            m = metrics(filt, "yrfi", f"kbb_combined<{q:.2f} ({pct_label})")
            yrfi_results.append(m)

    # High 1st-inning BABIP (batters hitting well on contact in 1st inning)
    if "top3_babip_inn1_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["top3_babip_inn1_combined"].quantile(pct / 100)
            filt = df[df["top3_babip_inn1_combined"] > q]
            m = metrics(filt, "yrfi", f"top3_babip_inn1>{q:.3f} ({pct_label})")
            yrfi_results.append(m)

    # High pitcher 1st-inning BABIP-against (pitchers leaking hits on contact)
    if "sp_babip_inn1_combined" in df.columns:
        for pct_label, pct in [("p50", 50), ("p75", 75), ("p90", 90)]:
            q = df["sp_babip_inn1_combined"].quantile(pct / 100)
            filt = df[df["sp_babip_inn1_combined"] > q]
            m = metrics(filt, "yrfi", f"sp_babip_inn1>{q:.3f} ({pct_label})")
            yrfi_results.append(m)

    print(f"\n{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
          f"{'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'Flds':>6}")
    print("-" * 100)
    for m in yrfi_results:
        print_row(m)

    # ========================================================================
    # YRFI COMBINED: PITCHER + BvP
    # ========================================================================
    if "top3_obp_short_combined" in df.columns and "sp_ra_combined_short" in df.columns:
        print(f"\n{'='*80}")
        print("YRFI COMBINED: PITCHER + BvP")
        print(f"{'='*80}")

        yrfi_combos = []

        # High sp_ra + high top3_obp
        for sp in [9.5, 10.0, 10.5, 11.0]:
            for obp_pct in [50, 75]:
                obp_q = df["top3_obp_short_combined"].quantile(obp_pct / 100)
                filt = df[(df["sp_ra_combined_short"] > sp) & (df["top3_obp_short_combined"] > obp_q)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt["yrfi"].mean()
                roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                yrfi_combos.append((f"sp_ra>{sp:.0f} + obp>{obp_q:.3f}(p{obp_pct})", n, n/filt["season"].nunique(), hr, roi))

        # High close_ou + high sp_fi_ra
        if "sp_fi_ra_combined" in df.columns:
            for ou in [9.0, 9.5, 10.0]:
                fi_med = df["sp_fi_ra_combined"].median()
                for fi_pct_label, fi_pct in [("p50", 50), ("p75", 75)]:
                    fi_q = df["sp_fi_ra_combined"].quantile(fi_pct / 100)
                    filt = df[(df["close_ou"] >= ou) & (df["sp_fi_ra_combined"] > fi_q)]
                    n = len(filt)
                    if n < 30:
                        continue
                    hr = filt["yrfi"].mean()
                    roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    yrfi_combos.append((f"ou>={ou:.1f} + sp_fi_ra>{fi_q:.2f}({fi_pct_label})", n, n/filt["season"].nunique(), hr, roi))

        # High sp_ra + high close_ou + high top3_obp (triple)
        for sp in [9.5, 10.0]:
            for ou in [9.0, 9.5]:
                for obp_pct in [50, 75]:
                    obp_q = df["top3_obp_short_combined"].quantile(obp_pct / 100)
                    filt = df[
                        (df["sp_ra_combined_short"] > sp)
                        & (df["close_ou"] >= ou)
                        & (df["top3_obp_short_combined"] > obp_q)
                    ]
                    n = len(filt)
                    if n < 30:
                        continue
                    hr = filt["yrfi"].mean()
                    roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    yrfi_combos.append((f"sp_ra>{sp:.0f}+ou>={ou:.1f}+obp>{obp_q:.3f}(p{obp_pct})", n, n/filt["season"].nunique(), hr, roi))

        # ── FIP-based combos ──────────────────────────────────────────
        if "starter_fip_combined" in df.columns:
            # close_ou + FIP
            for ou in [9.0, 9.5, 10.0]:
                for fip_thresh in [8.0, 8.5, 9.0, 9.5]:
                    filt = df[(df["close_ou"] >= ou) & (df["starter_fip_combined"] > fip_thresh)]
                    n = len(filt)
                    if n < 20:
                        continue
                    hr = filt["yrfi"].mean()
                    roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    yrfi_combos.append((f"ou>={ou:.1f} + fip>{fip_thresh:.1f}", n, n/filt["season"].nunique(), hr, roi))

            # FIP + sp_fi_ra (1st inning)
            if "sp_fi_ra_combined" in df.columns:
                fi_med = df["sp_fi_ra_combined"].median()
                for fip_thresh in [8.0, 8.5, 9.0]:
                    for fi_pct_label, fi_pct in [("p50", 50), ("p75", 75)]:
                        fi_q = df["sp_fi_ra_combined"].quantile(fi_pct / 100)
                        filt = df[(df["starter_fip_combined"] > fip_thresh) & (df["sp_fi_ra_combined"] > fi_q)]
                        n = len(filt)
                        if n < 20:
                            continue
                        hr = filt["yrfi"].mean()
                        roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                        yrfi_combos.append((f"fip>{fip_thresh:.1f}+sp_fi_ra>{fi_q:.2f}({fi_pct_label})", n, n/filt["season"].nunique(), hr, roi))

            # FIP + sp_ra (overall pitcher quality)
            for fip_thresh in [8.0, 8.5, 9.0]:
                for sp in [9.5, 10.0, 10.5]:
                    filt = df[(df["starter_fip_combined"] > fip_thresh) & (df["sp_ra_combined_short"] > sp)]
                    n = len(filt)
                    if n < 20:
                        continue
                    hr = filt["yrfi"].mean()
                    roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    yrfi_combos.append((f"fip>{fip_thresh:.1f}+sp_ra>{sp:.1f}", n, n/filt["season"].nunique(), hr, roi))

            # Triple: close_ou + FIP + sp_fi_ra
            if "sp_fi_ra_combined" in df.columns:
                for ou in [9.5, 10.0]:
                    for fip_thresh in [8.0, 8.5, 9.0]:
                        fi_q = df["sp_fi_ra_combined"].median()
                        filt = df[
                            (df["close_ou"] >= ou)
                            & (df["starter_fip_combined"] > fip_thresh)
                            & (df["sp_fi_ra_combined"] > fi_q)
                        ]
                        n = len(filt)
                        if n < 20:
                            continue
                        hr = filt["yrfi"].mean()
                        roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                        yrfi_combos.append((f"ou>={ou:.1f}+fip>{fip_thresh:.1f}+fi_ra>p50", n, n/filt["season"].nunique(), hr, roi))

        # ── WHIP-based combos ─────────────────────────────────────────
        if "starter_whip_combined" in df.columns:
            for ou in [9.0, 9.5, 10.0]:
                for whip_thresh in [2.4, 2.6, 2.8, 3.0]:
                    filt = df[(df["close_ou"] >= ou) & (df["starter_whip_combined"] > whip_thresh)]
                    n = len(filt)
                    if n < 20:
                        continue
                    hr = filt["yrfi"].mean()
                    roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    yrfi_combos.append((f"ou>={ou:.1f}+whip>{whip_thresh:.1f}", n, n/filt["season"].nunique(), hr, roi))

        # ── BABIP-based combos ────────────────────────────────────────
        # close_ou + top3_babip (high line + hitters who get hits on contact in 1st)
        if "top3_babip_inn1_combined" in df.columns:
            for ou in [9.0, 9.5, 10.0]:
                for babip_pct_label, babip_pct in [("p50", 50), ("p75", 75)]:
                    babip_q = df["top3_babip_inn1_combined"].quantile(babip_pct / 100)
                    filt = df[(df["close_ou"] >= ou) & (df["top3_babip_inn1_combined"] > babip_q)]
                    n = len(filt)
                    if n < 20:
                        continue
                    hr = filt["yrfi"].mean()
                    roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    yrfi_combos.append((f"ou>={ou:.1f}+top3_babip>{babip_q:.3f}({babip_pct_label})", n, n/filt["season"].nunique(), hr, roi))

            # close_ou + sp_babip (high line + pitchers who leak hits)
            if "sp_babip_inn1_combined" in df.columns:
                for ou in [9.0, 9.5, 10.0]:
                    for babip_pct_label, babip_pct in [("p50", 50), ("p75", 75)]:
                        babip_q = df["sp_babip_inn1_combined"].quantile(babip_pct / 100)
                        filt = df[(df["close_ou"] >= ou) & (df["sp_babip_inn1_combined"] > babip_q)]
                        n = len(filt)
                        if n < 20:
                            continue
                        hr = filt["yrfi"].mean()
                        roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                        yrfi_combos.append((f"ou>={ou:.1f}+sp_babip>{babip_q:.3f}({babip_pct_label})", n, n/filt["season"].nunique(), hr, roi))

            # FIP + BABIP (bad starters + hitters who capitalize on contact)
            if "starter_fip_combined" in df.columns:
                for fip_thresh in [8.0, 8.5, 9.0]:
                    for babip_pct_label, babip_pct in [("p50", 50), ("p75", 75)]:
                        babip_q = df["top3_babip_inn1_combined"].quantile(babip_pct / 100)
                        filt = df[(df["starter_fip_combined"] > fip_thresh) & (df["top3_babip_inn1_combined"] > babip_q)]
                        n = len(filt)
                        if n < 20:
                            continue
                        hr = filt["yrfi"].mean()
                        roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                        yrfi_combos.append((f"fip>{fip_thresh:.1f}+top3_babip>{babip_q:.3f}({babip_pct_label})", n, n/filt["season"].nunique(), hr, roi))

            # Triple: close_ou + FIP + top3_babip
            if "starter_fip_combined" in df.columns:
                for ou in [9.5, 10.0]:
                    for fip_thresh in [8.0, 8.5]:
                        for babip_pct_label, babip_pct in [("p50", 50), ("p75", 75)]:
                            babip_q = df["top3_babip_inn1_combined"].quantile(babip_pct / 100)
                            filt = df[
                                (df["close_ou"] >= ou)
                                & (df["starter_fip_combined"] > fip_thresh)
                                & (df["top3_babip_inn1_combined"] > babip_q)
                            ]
                            n = len(filt)
                            if n < 20:
                                continue
                            hr = filt["yrfi"].mean()
                            roi = np.where(filt["yrfi"], (YRFI_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                            yrfi_combos.append((f"ou>={ou:.1f}+fip>{fip_thresh:.1f}+babip({babip_pct_label})", n, n/filt["season"].nunique(), hr, roi))

        if yrfi_combos:
            print(f"{'Filter':<55} {'Bets':>5} {'B/S':>4} {'Hit%':>6} {'ROI':>7}")
            print("-" * 80)
            for name, n, bps, hr, roi in sorted(yrfi_combos, key=lambda x: -x[4]):
                marker = " ***" if hr > BREAKEVEN and roi > 0 else ""
                print(f"  {name:<53} {n:5d} {bps:4.0f} {hr*100:5.1f}% {roi:+6.1f}%{marker}")

    # ========================================================================
    # MONTHLY + SEASONAL (both sides)
    # ========================================================================
    print(f"\n{'='*80}")
    print("MONTHLY: NRFI vs YRFI RATES")
    print(f"{'='*80}")
    for mo in sorted(df["month"].unique()):
        mb = df[df["month"] == mo]
        n = len(mb)
        if n < 20:
            continue
        nr = mb["nrfi"].mean()
        yr = mb["yrfi"].mean()
        print(f"  Month {mo:2d}: {n:5d} games  NRFI {nr*100:5.1f}%  YRFI {yr*100:5.1f}%")

    print(f"\n{'='*80}")
    print("PER-SEASON: NRFI vs YRFI")
    print(f"{'='*80}")
    for s in sorted(df["season"].unique()):
        sb = df[df["season"] == s]
        n = len(sb)
        if n < 20:
            continue
        nr = sb["nrfi"].mean()
        yr = sb["yrfi"].mean()
        print(f"  {s}: {n:5d}  NRFI {nr*100:5.1f}%  YRFI {yr*100:5.1f}%")


if __name__ == "__main__":
    main()
