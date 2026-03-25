"""Dual-regime S3: strict filters pre-ASG, base filters post-ASG.

Split at All-Star break (~Jul 15). Three backtests:
  1H: S3 + rpi<=-0.01 + elo<=15 (first half only)
  2H: S3 base (second half only)
  Combined: 1H-strict in first half, base in second half

Usage:
    python scripts/dual_regime_s3.py
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

ASG_CUTOFF_DAY = 15  # July 15 — games on/before = 1st half


def max_ls(outcomes):
    m = c = 0
    for o in outcomes:
        if not o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def bankroll_metrics(df, name):
    """Compute full bankroll metrics for a bet sequence."""
    df = df.sort_values("date").copy()
    n = len(df)
    if n < 10:
        return None

    won = df["dog_won"].values.astype(float)
    odds = df["dog_decimal"].values
    pnl = np.where(won, (odds - 1) * 100, -100)
    cum_pnl = np.cumsum(pnl)

    wr = won.mean()
    avg_odds = odds.mean()
    roi = pnl.sum() / (n * 100) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    # Sharpe
    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    # Kelly
    b = avg_odds - 1
    kelly_full = (wr * b - (1 - wr)) / b if b > 0 else 0
    kelly_full = max(0, kelly_full)

    # Streaks
    mls = max_ls(won == 0)
    mws = max_ls(won == 1)

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
            df.loc[sm, "dog_won"].values,
            (df.loc[sm, "dog_decimal"].values - 1) * 100,
            -100,
        )
        season_rois.append(sp.sum() / (sn * 100) * 100)

    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name,
        "bets": n,
        "bets_per_season": n / df["season"].nunique(),
        "wr": wr,
        "avg_odds": avg_odds,
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
    print(f"    WR: {m['wr']*100:.1f}%  Avg odds: {m['avg_odds']:.2f}  ROI: {m['roi']:+.1f}%")
    print(f"    Sharpe: {m['sharpe']:.3f}  Kelly full: {m['kelly_full']*100:.1f}%  Kelly half: {m['kelly_half']*100:.1f}%")
    print(f"    Max loss streak: {m['max_loss_streak']}  Max DD: {m['max_dd_pct']:.1f}%  Avg DD: {m['avg_dd_pct']:.1f}%")
    print(f"    Seasons profitable: {m['seasons_pos']}")
    rois_str = ", ".join(f"{r:+.0f}" for r in m["season_rois"])
    print(f"    Per-season ROI: [{rois_str}]")
    print(f"    Worst: {m['worst_season']:+.1f}%  Best: {m['best_season']:+.1f}%")


def main():
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward

    print("Building spec features...")
    full = build_spec_features()
    print(f"Games: {len(full)}")

    features_available = [
        f for f in SPEC_FEATURES if f in full.columns and full[f].notna().mean() > 0.3
    ]
    target = "closing_decimal_odds_favorite"
    cfg = ModelConfig()
    print("Running walk-forward...")
    fold_results = run_walk_forward(full, features_available, target, cfg=cfg)
    div = compute_divergence(fold_results)

    # Merge
    merge_keys = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    full["day"] = pd.to_datetime(full["date"]).dt.day
    keep_cols = [c for c in full.columns if c not in div.columns or c in merge_keys]
    full_sub = full[keep_cols].drop_duplicates(subset=merge_keys)
    df = div.merge(full_sub, on=merge_keys, how="left")
    df = df.drop_duplicates(subset=merge_keys, keep="first")

    # S3 base setup
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0
    away_dog = df[df["fav_is_home"]].copy()
    away_dog["dog_decimal"] = away_dog["away_decimal_odds"]
    away_dog["dog_won"] = ~away_dog["fav_won"]
    away_dog["month"] = pd.to_datetime(away_dog["date"]).dt.month
    away_dog["day"] = pd.to_datetime(away_dog["date"]).dt.day

    # Half-season flag: 1st half = up to Jul 15
    away_dog["is_first_half"] = (away_dog["month"] < 7) | (
        (away_dog["month"] == 7) & (away_dog["day"] <= ASG_CUTOFF_DAY)
    )
    away_dog["pnl"] = np.where(
        away_dog["dog_won"], (away_dog["dog_decimal"] - 1) * 100, -100
    )

    # S3 base filters
    base = away_dog["edge_consensus"] < -0.05
    rpi_ok = away_dog["rpi_diff"] <= 0
    elo_ok = away_dog["elo_diff"] <= 30
    s3_mask = base & rpi_ok & elo_ok

    # Strict 1H filters (on top of S3)
    strict_rpi = away_dog["rpi_diff"] <= -0.01
    strict_elo = away_dog["elo_diff"] <= 15

    # === Build three regimes ===
    # 1H strict: first half with strict filters
    h1_mask = s3_mask & away_dog["is_first_half"] & strict_rpi & strict_elo
    # 2H base: second half with base S3 only
    h2_mask = s3_mask & ~away_dog["is_first_half"]
    # Combined: union
    combined_mask = h1_mask | h2_mask

    # Also: 1H with base (for comparison)
    h1_base_mask = s3_mask & away_dog["is_first_half"]

    h1_strict = away_dog[h1_mask].copy()
    h1_base = away_dog[h1_base_mask].copy()
    h2 = away_dog[h2_mask].copy()
    combined = away_dog[combined_mask].copy()
    s3_all = away_dog[s3_mask].copy()

    print(f"\n{'='*80}")
    print("DUAL-REGIME S3 BACKTEST")
    print(f"Split: All-Star break (Jul {ASG_CUTOFF_DAY})")
    print(f"1H strict: S3 + rpi<=-0.01 + elo<=15")
    print(f"2H base:   S3 (edge<-0.05, rpi<=0, elo<=30)")
    print(f"{'='*80}")

    metrics = []
    for data, name in [
        (s3_all, "S3 full season (base filters everywhere)"),
        (h1_base, "1H: S3 base (pre-ASG, no extra filters)"),
        (h1_strict, "1H: S3 strict (pre-ASG, rpi<=-0.01 + elo<=15)"),
        (h2, "2H: S3 base (post-ASG)"),
        (combined, "COMBINED: 1H-strict + 2H-base"),
    ]:
        print()
        m = bankroll_metrics(data, name)
        metrics.append(m)
        print_metrics(m)

    # === Comparison table ===
    print(f"\n{'='*80}")
    print("COMPARISON TABLE")
    print(f"{'='*80}")
    header = (
        f"{'Regime':<50} {'Bets':>5} {'B/S':>4} {'WR':>6} "
        f"{'ROI':>7} {'MaxL':>5} {'DD%':>6} {'Shrp':>6} {'K/2':>6} {'Flds':>6}"
    )
    print(header)
    print("-" * 110)
    for m in metrics:
        if m is None:
            continue
        print(
            f"  {m['name']:<48} {m['bets']:5d} {m['bets_per_season']:4.0f} "
            f"{m['wr']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
            f"{m['max_dd_pct']:5.1f}% {m['sharpe']:5.3f} "
            f"{m['kelly_half']*100:5.2f}% {m['seasons_pos']:>6}"
        )

    # === Monthly breakdown for combined ===
    print(f"\n{'='*80}")
    print("COMBINED: Monthly breakdown")
    print(f"{'='*80}")
    combined = combined.sort_values("date")
    for m in sorted(combined["month"].unique()):
        mb = combined[combined["month"] == m]
        nm = len(mb)
        if nm < 3:
            continue
        wr = mb["dog_won"].mean()
        roi = mb["pnl"].sum() / (nm * 100) * 100
        ml = max_ls(mb["dog_won"].values)
        regime = "1H-strict" if m < 7 else ("1H-strict/2H-base" if m == 7 else "2H-base")
        print(f"  Month {m:2d} ({regime:<16}): {nm:4d} bets  WR {wr*100:5.1f}%  ROI {roi:+6.1f}%  MaxL {ml}")

    # === Cumulative PnL curve (text sparkline) ===
    combined = combined.sort_values("date")
    cum = combined["pnl"].cumsum().values
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


if __name__ == "__main__":
    main()
