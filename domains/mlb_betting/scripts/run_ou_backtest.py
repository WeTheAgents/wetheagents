"""OVER betting backtest: regime-split model predicts total runs,
bets OVER when model prediction exceeds closing O/U line.

Assumes standard -110/-110 juice (decimal 1.909, breakeven 52.38%).

Usage:
    python scripts/run_ou_backtest.py
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

OU_DECIMAL_ODDS = 1.909  # -110 standard
ASG_CUTOFF_DAY = 15  # July 15


def max_streak(outcomes, target=False):
    m = c = 0
    for o in outcomes:
        if o == target:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def bankroll_metrics_ou(df, name):
    """Compute bankroll metrics for O/U bets at fixed -110 odds."""
    df = df.sort_values("date").copy()
    n = len(df)
    if n < 10:
        return None

    hit = df["over_hit"].values.astype(float)
    pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * 100, -100)
    cum_pnl = np.cumsum(pnl)

    hr = hit.mean()
    roi = pnl.sum() / (n * 100) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    # Sharpe (annualized by bets per season)
    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    # Kelly
    b = OU_DECIMAL_ODDS - 1
    kelly_full = (hr * b - (1 - hr)) / b if b > 0 else 0
    kelly_full = max(0, kelly_full)

    # Streaks
    mls = max_streak(hit, target=0)
    mws = max_streak(hit, target=1)

    # Drawdown
    bankroll = 10000 + cum_pnl
    peak = np.maximum.accumulate(bankroll)
    dd_pct = (peak - bankroll) / peak * 100
    max_dd = dd_pct.max()
    avg_dd = dd_pct[dd_pct > 0].mean() if (dd_pct > 0).any() else 0

    # Per-season
    season_rois = []
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(
            df.loc[sm, "over_hit"].values,
            (OU_DECIMAL_ODDS - 1) * 100,
            -100,
        )
        season_rois.append(sp.sum() / (sn * 100) * 100)

    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name,
        "bets": n,
        "bets_per_season": n / df["season"].nunique(),
        "hit_rate": hr,
        "roi": roi,
        "sharpe": sharpe,
        "kelly_full": kelly_full,
        "kelly_half": kelly_full / 2,
        "max_loss_streak": mls,
        "max_win_streak": mws,
        "max_dd_pct": max_dd,
        "avg_dd_pct": avg_dd,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "worst_season": min(season_rois) if season_rois else 0,
        "best_season": max(season_rois) if season_rois else 0,
        "season_rois": season_rois,
    }


def print_metrics(m):
    if m is None:
        print("  (too few bets)")
        return
    print(f"  {m['name']}")
    print(f"    Bets: {m['bets']} ({m['bets_per_season']:.0f}/season)")
    print(f"    Hit: {m['hit_rate']*100:.1f}%  Odds: {OU_DECIMAL_ODDS:.3f} (-110)  ROI: {m['roi']:+.1f}%")
    print(f"    Sharpe: {m['sharpe']:.3f}  Kelly full: {m['kelly_full']*100:.1f}%  Kelly half: {m['kelly_half']*100:.1f}%")
    print(f"    Max loss streak: {m['max_loss_streak']}  Max DD: {m['max_dd_pct']:.1f}%  Avg DD: {m['avg_dd_pct']:.1f}%")
    print(f"    Seasons profitable: {m['seasons_pos']}")
    rois_str = ", ".join(f"{r:+.0f}" for r in m["season_rois"])
    print(f"    Per-season ROI: [{rois_str}]")
    print(f"    Worst: {m['worst_season']:+.1f}%  Best: {m['best_season']:+.1f}%")


def main():
    from src.features import build_ou_features, OU_FEATURES
    from src.model import ModelConfig, OU_REGIMES, compute_divergence, run_walk_forward

    print("Building O/U features...")
    full = build_ou_features()
    print(f"Games: {len(full)}")

    # Exclude ou_line_move when target is close_ou (contains target info)
    features_available = [
        f for f in OU_FEATURES
        if f in full.columns and full[f].notna().mean() > 0.3 and f != "ou_line_move"
    ]
    print(f"Features: {len(features_available)}/{len(OU_FEATURES)}: {features_available}")

    target = "close_ou"
    cfg = ModelConfig()
    print("Running walk-forward (O/U regimes)...")
    fold_results = run_walk_forward(
        full, features_available, target, cfg=cfg, regimes=OU_REGIMES
    )
    div = compute_divergence(fold_results)

    if div.empty:
        print("ERROR: No divergence results. Check data/features.")
        return

    # Merge predictions back to full game data
    merge_keys = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    full["day"] = pd.to_datetime(full["date"]).dt.day
    keep_cols = [c for c in full.columns if c not in div.columns or c in merge_keys]
    full_sub = full[keep_cols].drop_duplicates(subset=merge_keys)
    df = div.merge(full_sub, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    # Consensus prediction and edge
    # Model predicts "fair line" — if predicted > actual line → OVER signal
    pred_cols = [c for c in df.columns if c.startswith("pred_T")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["ou_edge"] = df["pred_consensus"] - df["close_ou"]

    # OVER hit (strict > line; push = excluded)
    df["over_hit"] = df["total_runs"] > df["close_ou"]
    df["is_push"] = df["total_runs"] == df["close_ou"]

    # Exclude pushes
    df_no_push = df[~df["is_push"]].copy()

    df_no_push["month"] = pd.to_datetime(df_no_push["date"]).dt.month
    df_no_push["day"] = pd.to_datetime(df_no_push["date"]).dt.day
    df_no_push["is_first_half"] = (df_no_push["month"] < 7) | (
        (df_no_push["month"] == 7) & (df_no_push["day"] <= ASG_CUTOFF_DAY)
    )
    df_no_push["pnl"] = np.where(
        df_no_push["over_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100
    )

    print(f"\n{'='*80}")
    print("OVER BACKTEST — EDGE THRESHOLD SWEEP")
    print(f"Odds: -110 (decimal {OU_DECIMAL_ODDS})  Breakeven: 52.38%")
    print(f"Pushes excluded: {df['is_push'].sum()}")
    print(f"{'='*80}")

    # === Edge threshold sweep ===
    metrics_list = []
    for threshold in [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5]:
        mask = df_no_push["ou_edge"] > threshold
        subset = df_no_push[mask].copy()
        name = f"OVER edge>{threshold:.1f}"
        m = bankroll_metrics_ou(subset, name)
        metrics_list.append(m)
        print()
        print_metrics(m)

    # === Comparison table ===
    print(f"\n{'='*80}")
    print("EDGE SWEEP COMPARISON")
    print(f"{'='*80}")
    header = (
        f"{'Filter':<35} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
        f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>6} {'K/2':>6} {'Flds':>6}"
    )
    print(header)
    print("-" * 100)
    for m in metrics_list:
        if m is None:
            continue
        print(
            f"  {m['name']:<33} {m['bets']:5d} {m['bets_per_season']:4.0f} "
            f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
            f"{m['max_dd_pct']:5.1f}% {m['sharpe']:5.3f} "
            f"{m['kelly_half']*100:5.2f}% {m['seasons_pos']:>6}"
        )

    # === Filter combinations (on best edge threshold) ===
    # Find best edge threshold by ROI
    valid = [m for m in metrics_list if m is not None and m["bets"] >= 50]
    if not valid:
        print("\nNo filter combo with enough bets. Done.")
        return
    best_edge = 0.5  # default
    best_by_roi = max(valid, key=lambda m: m["roi"])
    # Extract threshold from name
    for t in [0.0, 0.3, 0.5, 0.75, 1.0, 1.5]:
        if f"edge>{t:.1f}" in best_by_roi["name"]:
            best_edge = t
            break

    print(f"\n{'='*80}")
    print(f"FILTER COMBOS (base: edge>{best_edge:.1f})")
    print(f"{'='*80}")

    base_mask = df_no_push["ou_edge"] > best_edge
    base_df = df_no_push[base_mask].copy()

    combo_metrics = []

    # 1) Base only
    m = bankroll_metrics_ou(base_df, f"Base: edge>{best_edge:.1f}")
    combo_metrics.append(m)

    # 2) + Both pitchers leaky (sp_ra_combined_short > median)
    if "sp_ra_combined_short" in base_df.columns:
        med = base_df["sp_ra_combined_short"].median()
        for thresh in [med, med + 1, med + 2]:
            filt = base_df[base_df["sp_ra_combined_short"] > thresh].copy()
            name = f"+ sp_ra_combined>{thresh:.1f}"
            m = bankroll_metrics_ou(filt, name)
            combo_metrics.append(m)

    # 3) + Combined RPG > line (teams outscoring the line historically)
    if "combined_rpg" in base_df.columns:
        filt = base_df[base_df["combined_rpg"] > base_df["close_ou"]].copy()
        m = bankroll_metrics_ou(filt, "+ combined_rpg > line")
        combo_metrics.append(m)

    # 4) + Combined recent RPG > line
    if "combined_rpg_last10" in base_df.columns:
        filt = base_df[base_df["combined_rpg_last10"] > base_df["close_ou"]].copy()
        m = bankroll_metrics_ou(filt, "+ rpg_last10 > line")
        combo_metrics.append(m)

    # 5) Summer months (June-August)
    filt = base_df[base_df["month"].isin([6, 7, 8])].copy()
    m = bankroll_metrics_ou(filt, "+ summer (Jun-Aug)")
    combo_metrics.append(m)

    # 6) 1H strict (pre-ASG)
    filt = base_df[base_df["is_first_half"]].copy()
    m = bankroll_metrics_ou(filt, "+ 1st half only")
    combo_metrics.append(m)

    # 7) 2H (post-ASG)
    filt = base_df[~base_df["is_first_half"]].copy()
    m = bankroll_metrics_ou(filt, "+ 2nd half only")
    combo_metrics.append(m)

    # 8) Quality floor high (both starters have high RA)
    if "sp_quality_floor" in base_df.columns:
        med = base_df["sp_quality_floor"].median()
        filt = base_df[base_df["sp_quality_floor"] > med].copy()
        m = bankroll_metrics_ou(filt, f"+ sp_quality_floor>{med:.1f}")
        combo_metrics.append(m)

    # Print filter combo results
    print(f"\n{'Filter':<35} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
          f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>6} {'K/2':>6} {'Flds':>6}")
    print("-" * 100)
    for m in combo_metrics:
        if m is None:
            continue
        print(
            f"  {m['name']:<33} {m['bets']:5d} {m['bets_per_season']:4.0f} "
            f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
            f"{m['max_dd_pct']:5.1f}% {m['sharpe']:5.3f} "
            f"{m['kelly_half']*100:5.2f}% {m['seasons_pos']:>6}"
        )

    # === Monthly breakdown for base ===
    print(f"\n{'='*80}")
    print(f"Base (edge>{best_edge:.1f}): Monthly breakdown")
    print(f"{'='*80}")
    base_df = base_df.sort_values("date")
    for m in sorted(base_df["month"].unique()):
        mb = base_df[base_df["month"] == m]
        nm = len(mb)
        if nm < 3:
            continue
        hr = mb["over_hit"].mean()
        roi = mb["pnl"].sum() / (nm * 100) * 100
        ml = max_streak(mb["over_hit"].values == 0, target=True)
        half = "1H" if m <= 7 else "2H"
        print(f"  Month {m:2d} ({half}): {nm:4d} bets  Hit {hr*100:5.1f}%  ROI {roi:+6.1f}%  MaxL {ml}")

    # === PnL curve ===
    base_df = base_df.sort_values("date")
    cum = base_df["pnl"].cumsum().values
    if len(cum) > 0:
        n_pts = min(50, len(cum))
        indices = np.linspace(0, len(cum) - 1, n_pts, dtype=int)
        vals = cum[indices]
        vmin, vmax = vals.min(), vals.max()
        rng = vmax - vmin if vmax > vmin else 1
        bars = "".join(
            ["_", ".", "-", "~", "+", "*", "#"][int((v - vmin) / rng * 6)]
            for v in vals
        )
        print(f"\n  PnL curve: [{bars}]")
        print(f"  Start: $0  End: ${cum[-1]:+,.0f}  Peak: ${cum.max():+,.0f}  Trough: ${cum.min():+,.0f}")

    # ========================================================================
    # UNDER ANALYSIS
    # ========================================================================
    print(f"\n\n{'='*80}")
    print("UNDER BACKTEST -- EDGE THRESHOLD SWEEP")
    print(f"Odds: -110 (decimal {OU_DECIMAL_ODDS})  Breakeven: 52.38%")
    print(f"{'='*80}")

    # UNDER: ou_edge < -threshold means model predicts LOWER line than market
    under_metrics = []
    for threshold in [0.0, 0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5]:
        mask = df_no_push["ou_edge"] < -threshold
        subset = df_no_push[mask].copy()
        # For UNDER bets: hit = total_runs < close_ou
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        subset_u = subset.copy()
        # Use under_hit as the metric
        n = len(subset_u)
        if n < 10:
            under_metrics.append(None)
            continue
        hit = subset_u["under_hit"].values.astype(float)
        pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * 100, -100)
        hr = hit.mean()
        roi = pnl.sum() / (n * 100) * 100
        ev = pnl.mean()
        std = pnl.std(ddof=1) if n > 1 else 1
        sharpe_bet = ev / std if std > 0 else 0
        bps = n / subset_u["season"].nunique() if subset_u["season"].nunique() > 0 else n
        sharpe = sharpe_bet * np.sqrt(bps)
        mls = max_streak(hit, target=0)

        season_rois = []
        for s in sorted(subset_u["season"].unique()):
            sm = subset_u["season"] == s
            sn = sm.sum()
            if sn < 3:
                continue
            sp = np.where(subset_u.loc[sm, "under_hit"].values,
                          (OU_DECIMAL_ODDS - 1) * 100, -100)
            season_rois.append(sp.sum() / (sn * 100) * 100)
        n_pos = sum(1 for r in season_rois if r > 0)

        m = {
            "name": f"UNDER edge<-{threshold:.1f}",
            "bets": n,
            "bets_per_season": n / subset_u["season"].nunique(),
            "hit_rate": hr,
            "roi": roi,
            "sharpe": sharpe,
            "max_loss_streak": mls,
            "seasons_pos": f"{n_pos}/{len(season_rois)}",
            "season_rois": season_rois,
        }
        under_metrics.append(m)
        print(f"  {m['name']}")
        print(f"    Bets: {m['bets']} ({m['bets_per_season']:.0f}/season)")
        print(f"    Hit: {m['hit_rate']*100:.1f}%  ROI: {m['roi']:+.1f}%  Sharpe: {m['sharpe']:.3f}  MaxL: {m['max_loss_streak']}")
        print(f"    Seasons: {m['seasons_pos']}")
        rois_str = ", ".join(f"{r:+.0f}" for r in m["season_rois"])
        print(f"    Per-season: [{rois_str}]")

    # UNDER comparison table
    print(f"\n{'Filter':<35} {'Bets':>5} {'B/S':>4} {'Hit%':>6} {'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'Flds':>6}")
    print("-" * 85)
    for m in under_metrics:
        if m is None:
            continue
        print(
            f"  {m['name']:<33} {m['bets']:5d} {m['bets_per_season']:4.0f} "
            f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
            f"{m['sharpe']:5.3f} {m['seasons_pos']:>6}"
        )

    # === UNDER filter combos ===
    print(f"\n{'='*80}")
    print("UNDER FILTER COMBOS")
    print(f"{'='*80}")

    # Best UNDER edge threshold by highest hit rate with enough bets
    best_under_edge = 0.5  # start from mid-range

    under_base_mask = df_no_push["ou_edge"] < -best_under_edge
    under_base = df_no_push[under_base_mask].copy()
    under_base["under_hit"] = under_base["total_runs"] < under_base["close_ou"]

    under_combos = []

    # Low sp_ra_combined (both starters are GOOD -> fewer runs)
    if "sp_ra_combined_short" in under_base.columns:
        for thresh in [7.0, 7.5, 8.0, 8.5, 9.0]:
            filt = under_base[under_base["sp_ra_combined_short"] < thresh].copy()
            n = len(filt)
            if n < 20:
                continue
            hr = filt["under_hit"].mean()
            roi_val = np.where(filt["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
            under_combos.append((f"sp_ra<{thresh:.1f} + edge<-0.5", n, hr, roi_val))

    # Low combined_rapg (teams don't allow many runs)
    if "combined_rapg" in under_base.columns:
        for thresh in [7.5, 8.0, 8.5, 9.0]:
            filt = under_base[under_base["combined_rapg"] < thresh].copy()
            n = len(filt)
            if n < 20:
                continue
            hr = filt["under_hit"].mean()
            roi_val = np.where(filt["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
            under_combos.append((f"rapg<{thresh:.1f} + edge<-0.5", n, hr, roi_val))

    # 1H / 2H split
    for half_name, half_mask in [("1H", under_base["is_first_half"]), ("2H", ~under_base["is_first_half"])]:
        filt = under_base[half_mask].copy()
        n = len(filt)
        if n < 20:
            continue
        hr = filt["under_hit"].mean()
        roi_val = np.where(filt["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
        under_combos.append((f"{half_name} + edge<-0.5", n, hr, roi_val))

    # Combined: low sp_ra + rpg_last10 < line
    if "sp_ra_combined_short" in under_base.columns and "combined_rpg_last10" in under_base.columns:
        for sp_thresh in [7.5, 8.0, 8.5]:
            filt = under_base[
                (under_base["sp_ra_combined_short"] < sp_thresh)
                & (under_base["combined_rpg_last10"] < under_base["close_ou"])
            ].copy()
            n = len(filt)
            if n < 20:
                continue
            hr = filt["under_hit"].mean()
            roi_val = np.where(filt["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
            under_combos.append((f"sp_ra<{sp_thresh:.1f} + rpg10<line + edge<-0.5", n, hr, roi_val))

    if under_combos:
        print(f"{'Filter':<50} {'Bets':>5} {'Hit%':>6} {'ROI':>7}")
        print("-" * 75)
        for name, n, hr, roi_val in sorted(under_combos, key=lambda x: -x[3]):
            marker = " ***" if hr > 0.5238 and roi_val > 0 else ""
            print(f"  {name:<48} {n:5d} {hr*100:5.1f}% {roi_val:+6.1f}%{marker}")

    # === UNDER deep dive: sp_ra x edge grid ===
    print(f"\n{'='*80}")
    print("UNDER DEEP DIVE: sp_ra_combined x edge threshold")
    print(f"{'='*80}")
    print(f"{'sp_ra <':<12} {'edge<':<8} {'Bets':>5} {'Hit%':>6} {'ROI':>7} {'MaxL':>5} {'Flds':>6}")
    print("-" * 60)
    for sp_thresh in [7.0, 7.5, 8.0, 8.5, 9.0, 9.5]:
        for edge_thresh in [0.3, 0.5, 0.75, 1.0, 1.5]:
            if "sp_ra_combined_short" not in df_no_push.columns:
                continue
            mask = (
                (df_no_push["ou_edge"] < -edge_thresh)
                & (df_no_push["sp_ra_combined_short"] < sp_thresh)
            )
            subset = df_no_push[mask].copy()
            n = len(subset)
            if n < 20:
                continue
            subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
            hr = subset["under_hit"].mean()
            roi_val = np.where(
                subset["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100
            ).sum() / (n * 100) * 100
            ml = max_streak(subset["under_hit"].values == 0, target=True)
            n_pos = 0
            n_seasons = 0
            for s in sorted(subset["season"].unique()):
                sm = subset[subset["season"] == s]
                sn = len(sm)
                if sn < 3:
                    continue
                sp = np.where(sm["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100).sum() / (sn * 100) * 100
                n_seasons += 1
                if sp > 0:
                    n_pos += 1
            flds = f"{n_pos}/{n_seasons}" if n_seasons > 0 else "n/a"
            print(f"  {sp_thresh:<10.1f} {'-'+str(edge_thresh):<6} {n:5d} {hr*100:5.1f}% {roi_val:+6.1f}% {ml:5d} {flds:>6}")

    # === UNDER VALIDATION: best combos ===
    print(f"\n{'='*80}")
    print("UNDER VALIDATION: BEST COMBOS (full bankroll metrics)")
    print(f"{'='*80}")

    under_validate = []

    # Combo 1: sp_ra < 8.0 + edge < -1.0
    if "sp_ra_combined_short" in df_no_push.columns:
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append(("sp_ra<8.0 + edge<-1.0", subset))

    # Combo 2: sp_ra < 7.0 + edge < -0.75
    if "sp_ra_combined_short" in df_no_push.columns:
        mask = (
            (df_no_push["ou_edge"] < -0.75)
            & (df_no_push["sp_ra_combined_short"] < 7.0)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append(("sp_ra<7.0 + edge<-0.75", subset))

    # Combo 3: rapg < 7.5 + edge < -0.5
    if "combined_rapg" in df_no_push.columns:
        mask = (
            (df_no_push["ou_edge"] < -0.5)
            & (df_no_push["combined_rapg"] < 7.5)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append(("rapg<7.5 + edge<-0.5", subset))

    # Combo 4: sp_ra < 8.0 + edge < -1.0 + 1H
    if "sp_ra_combined_short" in df_no_push.columns:
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & df_no_push["is_first_half"]
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append(("sp_ra<8.0 + edge<-1.0 + 1H", subset))

    # Combo 5: sp_ra < 8.0 + edge < -1.0 + 2H
    if "sp_ra_combined_short" in df_no_push.columns:
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & ~df_no_push["is_first_half"]
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append(("sp_ra<8.0 + edge<-1.0 + 2H", subset))

    # Combo 6: rapg < 7.5 + sp_ra < 8.0 + edge < -0.5
    if "sp_ra_combined_short" in df_no_push.columns and "combined_rapg" in df_no_push.columns:
        mask = (
            (df_no_push["ou_edge"] < -0.5)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & (df_no_push["combined_rapg"] < 7.5)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append(("rapg<7.5 + sp_ra<8.0 + edge<-0.5", subset))

    # Combo 7: sp_ra<8 + edge<-1 + 2H + low bullpen WHIP
    if "sp_ra_combined_short" in df_no_push.columns and "bullpen_whip_combined" in df_no_push.columns:
        bp_whip_med = df_no_push["bullpen_whip_combined"].median()
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & ~df_no_push["is_first_half"]
            & (df_no_push["bullpen_whip_combined"] < bp_whip_med)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append((f"sp_ra<8 + edge<-1 + 2H + bp_whip<{bp_whip_med:.1f}", subset))

    # Combo 8: sp_ra<8 + edge<-1 + 2H + low bullpen FIP
    if "sp_ra_combined_short" in df_no_push.columns and "bullpen_fip_combined" in df_no_push.columns:
        bp_fip_med = df_no_push["bullpen_fip_combined"].median()
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & ~df_no_push["is_first_half"]
            & (df_no_push["bullpen_fip_combined"] < bp_fip_med)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append((f"sp_ra<8 + edge<-1 + 2H + bp_fip<{bp_fip_med:.1f}", subset))

    # Combo 9: sp_ra<8 + edge<-1 + 2H + high bullpen K9
    if "sp_ra_combined_short" in df_no_push.columns and "bullpen_k9_combined" in df_no_push.columns:
        bp_k9_med = df_no_push["bullpen_k9_combined"].median()
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & ~df_no_push["is_first_half"]
            & (df_no_push["bullpen_k9_combined"] > bp_k9_med)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append((f"sp_ra<8 + edge<-1 + 2H + bp_k9>{bp_k9_med:.1f}", subset))

    # Combo 10: sp_ra<8 + edge<-1 + 2H + fresh bullpen (low ip_3d)
    if "sp_ra_combined_short" in df_no_push.columns and "bullpen_ip_3d_combined" in df_no_push.columns:
        bp_ip3d_med = df_no_push["bullpen_ip_3d_combined"].median()
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & ~df_no_push["is_first_half"]
            & (df_no_push["bullpen_ip_3d_combined"] < bp_ip3d_med)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append((f"sp_ra<8 + edge<-1 + 2H + bp_ip3d<{bp_ip3d_med:.1f}", subset))

    # Combo 11: best combo baseline + bullpen_kbb > median (dominant bullpens)
    if "sp_ra_combined_short" in df_no_push.columns and "bullpen_kbb_combined" in df_no_push.columns:
        bp_kbb_med = df_no_push["bullpen_kbb_combined"].median()
        mask = (
            (df_no_push["ou_edge"] < -1.0)
            & (df_no_push["sp_ra_combined_short"] < 8.0)
            & ~df_no_push["is_first_half"]
            & (df_no_push["bullpen_kbb_combined"] > bp_kbb_med)
        )
        subset = df_no_push[mask].copy()
        subset["under_hit"] = subset["total_runs"] < subset["close_ou"]
        under_validate.append((f"sp_ra<8 + edge<-1 + 2H + bp_kbb>{bp_kbb_med:.1f}", subset))

    for name, subset in under_validate:
        n = len(subset)
        if n < 10:
            print(f"\n  {name}: too few bets ({n})")
            continue

        hit = subset["under_hit"].values.astype(float)
        pnl = np.where(hit, (OU_DECIMAL_ODDS - 1) * 100, -100)
        cum_pnl = np.cumsum(pnl)

        hr = hit.mean()
        roi = pnl.sum() / (n * 100) * 100
        ev = pnl.mean()
        std = pnl.std(ddof=1) if n > 1 else 1
        sharpe_bet = ev / std if std > 0 else 0
        bps = n / subset["season"].nunique() if subset["season"].nunique() > 0 else n
        sharpe = sharpe_bet * np.sqrt(bps)

        b = OU_DECIMAL_ODDS - 1
        kelly_full = (hr * b - (1 - hr)) / b if b > 0 else 0
        kelly_full = max(0, kelly_full)

        mls = max_streak(hit, target=0)
        mws = max_streak(hit, target=1)

        bankroll = 10000 + cum_pnl
        peak = np.maximum.accumulate(bankroll)
        dd_pct = (peak - bankroll) / peak * 100
        max_dd = dd_pct.max()

        # Per-season
        season_data = []
        for s in sorted(subset["season"].unique()):
            sm = subset["season"] == s
            sn = sm.sum()
            if sn < 1:
                continue
            sp = np.where(
                subset.loc[sm, "under_hit"].values,
                (OU_DECIMAL_ODDS - 1) * 100, -100
            )
            s_roi = sp.sum() / (sn * 100) * 100
            s_hr = subset.loc[sm, "under_hit"].mean()
            season_data.append((s, sn, s_hr, s_roi))
        n_pos = sum(1 for _, _, _, r in season_data if r > 0)

        print(f"\n  {name}")
        print(f"    Bets: {n} ({n / subset['season'].nunique():.0f}/season)")
        print(f"    Hit: {hr*100:.1f}%  ROI: {roi:+.1f}%  Sharpe: {sharpe:.3f}")
        print(f"    Kelly full: {kelly_full*100:.1f}%  Kelly half: {kelly_full/2*100:.1f}%")
        print(f"    MaxL: {mls}  MaxW: {mws}  MaxDD: {max_dd:.1f}%")
        print(f"    Seasons profitable: {n_pos}/{len(season_data)}")
        print(f"    Per-season:")
        for s, sn, s_hr, s_roi in season_data:
            marker = "+" if s_roi > 0 else " "
            print(f"      {s}: {sn:3d} bets  Hit {s_hr*100:5.1f}%  ROI {s_roi:+6.1f}% {marker}")

        # Monthly breakdown
        subset_sorted = subset.sort_values("date")
        print(f"    Monthly:")
        for m in sorted(subset_sorted["month"].unique()):
            mb = subset_sorted[subset_sorted["month"] == m]
            nm = len(mb)
            if nm < 3:
                continue
            m_hr = mb["under_hit"].mean()
            m_pnl = np.where(mb["under_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100)
            m_roi = m_pnl.sum() / (nm * 100) * 100
            half = "1H" if m <= 7 else "2H"
            print(f"      Month {m:2d} ({half}): {nm:4d} bets  Hit {m_hr*100:5.1f}%  ROI {m_roi:+6.1f}%")

        # PnL sparkline
        if len(cum_pnl) > 10:
            n_pts = min(50, len(cum_pnl))
            indices = np.linspace(0, len(cum_pnl) - 1, n_pts, dtype=int)
            vals = cum_pnl[indices]
            vmin, vmax = vals.min(), vals.max()
            rng = vmax - vmin if vmax > vmin else 1
            bars = "".join(
                ["_", ".", "-", "~", "+", "*", "#"][int((v - vmin) / rng * 6)]
                for v in vals
            )
            print(f"    PnL: [{bars}]")
            print(f"    Start: $0  End: ${cum_pnl[-1]:+,.0f}  Peak: ${cum_pnl.max():+,.0f}  Trough: ${cum_pnl.min():+,.0f}")

    # === Skip OVER deep dives since UNDER is the focus ===

    # === Deep dive: sp_ra_combined x edge grid ===
    print(f"\n{'='*80}")
    print("DEEP DIVE: sp_ra_combined x edge threshold")
    print(f"{'='*80}")
    print(f"{'sp_ra >':<12} {'edge>':<8} {'Bets':>5} {'Hit%':>6} {'ROI':>7} {'MaxL':>5} {'Flds':>6}")
    print("-" * 60)
    for sp_thresh in [8.0, 9.0, 9.5, 10.0, 10.5, 11.0]:
        for edge_thresh in [0.3, 0.5, 0.75, 1.0, 1.5]:
            if "sp_ra_combined_short" not in df_no_push.columns:
                continue
            mask = (
                (df_no_push["ou_edge"] > edge_thresh)
                & (df_no_push["sp_ra_combined_short"] > sp_thresh)
            )
            subset = df_no_push[mask]
            n = len(subset)
            if n < 20:
                continue
            hr = subset["over_hit"].mean()
            roi = np.where(
                subset["over_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100
            ).sum() / (n * 100) * 100
            ml = max_streak(subset["over_hit"].values == 0, target=True)
            # per-season
            n_pos = 0
            n_seasons = 0
            for s in sorted(subset["season"].unique()):
                sm = subset[subset["season"] == s]
                sn = len(sm)
                if sn < 3:
                    continue
                sp = np.where(sm["over_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100).sum() / (sn * 100) * 100
                n_seasons += 1
                if sp > 0:
                    n_pos += 1
            flds = f"{n_pos}/{n_seasons}" if n_seasons > 0 else "n/a"
            print(f"  {sp_thresh:<10.1f} {edge_thresh:<6.1f} {n:5d} {hr*100:5.1f}% {roi:+6.1f}% {ml:5d} {flds:>6}")

    # === Deep dive: combined filters (best combos) ===
    print(f"\n{'='*80}")
    print("COMBINED FILTER EXPLORATION")
    print(f"{'='*80}")
    combos = []

    # sp_ra + rpg_last10 > line
    for sp_thresh in [9.0, 9.5, 10.0]:
        for edge_thresh in [0.5, 0.75, 1.0]:
            if "sp_ra_combined_short" not in df_no_push.columns:
                continue
            mask = (
                (df_no_push["ou_edge"] > edge_thresh)
                & (df_no_push["sp_ra_combined_short"] > sp_thresh)
                & (df_no_push["combined_rpg_last10"] > df_no_push["close_ou"])
            )
            subset = df_no_push[mask]
            n = len(subset)
            if n < 20:
                continue
            hr = subset["over_hit"].mean()
            roi = np.where(
                subset["over_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100
            ).sum() / (n * 100) * 100
            name = f"sp_ra>{sp_thresh:.0f} + rpg10>line + edge>{edge_thresh:.1f}"
            combos.append((name, n, hr, roi))

    # sp_ra + 1st half
    for sp_thresh in [9.0, 9.5, 10.0]:
        for edge_thresh in [0.5, 0.75, 1.0]:
            if "sp_ra_combined_short" not in df_no_push.columns:
                continue
            mask = (
                (df_no_push["ou_edge"] > edge_thresh)
                & (df_no_push["sp_ra_combined_short"] > sp_thresh)
                & df_no_push["is_first_half"]
            )
            subset = df_no_push[mask]
            n = len(subset)
            if n < 20:
                continue
            hr = subset["over_hit"].mean()
            roi = np.where(
                subset["over_hit"], (OU_DECIMAL_ODDS - 1) * 100, -100
            ).sum() / (n * 100) * 100
            name = f"sp_ra>{sp_thresh:.0f} + 1H + edge>{edge_thresh:.1f}"
            combos.append((name, n, hr, roi))

    if combos:
        print(f"{'Filter':<45} {'Bets':>5} {'Hit%':>6} {'ROI':>7}")
        print("-" * 70)
        for name, n, hr, roi in sorted(combos, key=lambda x: -x[3]):
            marker = " ***" if hr > 0.5238 and roi > 0 else ""
            print(f"  {name:<43} {n:5d} {hr*100:5.1f}% {roi:+6.1f}%{marker}")

    # === Regime distribution ===
    print(f"\n{'='*80}")
    print("O/U REGIME DISTRIBUTION")
    print(f"{'='*80}")
    for regime in ["T_OVER2", "T_OVER1", "T_UNDER"]:
        n_r = (df["regime"] == regime).sum()
        pct = n_r / len(df) * 100
        print(f"  {regime:10s}: {n_r:6d} ({pct:5.1f}%)")

    # Prediction quality: how well does model predict close_ou?
    if "pred_consensus" in df.columns:
        rmse_line = np.sqrt(((df["pred_consensus"] - df["close_ou"]) ** 2).mean())
        mae_line = (df["pred_consensus"] - df["close_ou"]).abs().mean()
        corr_line = df["pred_consensus"].corr(df["close_ou"])
        print(f"\n  Model -> close_ou: RMSE={rmse_line:.2f}  MAE={mae_line:.2f}  Corr={corr_line:.3f}")
        print(f"  Edge stats: mean={df['ou_edge'].mean():.3f}  std={df['ou_edge'].std():.3f}")
        # Also: how well does pred_consensus predict total_runs?
        rmse_tr = np.sqrt(((df["pred_consensus"] - df["total_runs"]) ** 2).mean())
        corr_tr = df["pred_consensus"].corr(df["total_runs"])
        print(f"  Model -> total_runs: RMSE={rmse_tr:.2f}  Corr={corr_tr:.3f}")
        rmse_naive = np.sqrt(((df["close_ou"] - df["total_runs"]) ** 2).mean())
        print(f"  Naive (close_ou -> total_runs): RMSE={rmse_naive:.2f}")


if __name__ == "__main__":
    main()
