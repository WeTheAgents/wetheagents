"""Portfolio correlation analysis: S3-dual (away ML) + RL +1.5 (away cover).

Both strategies bet on the away underdog but with OPPOSITE edge signals:
  S3-dual: edge < -0.05 (underdog underpriced → ML win)
  RL +1.5: edge > 0.05 (favorite overpriced → tight game → +1.5 covers)

Questions:
  1. How many games overlap? (bet on same game by both strategies)
  2. Are daily/monthly returns correlated?
  3. What does combined portfolio look like? (total volume, Sharpe, drawdown)
  4. Does diversification improve risk-adjusted returns?

Usage:
    python scripts/portfolio_away_underdog.py
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

ASG_DAY = 15


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def max_ls(outcomes):
    m = c = 0
    for o in outcomes:
        if not o:
            c += 1
            m = max(m, c)
        else:
            c = 0
    return m


def bankroll_metrics(pnl_series, name, seasons):
    n = len(pnl_series)
    if n < 10:
        return None
    pnl = pnl_series.values
    cum = np.cumsum(pnl)
    bk = 10000 + cum
    pk = np.maximum.accumulate(bk)
    mdd = ((pk - bk) / pk * 100).max()

    wins = (pnl > 0).astype(float)
    wr = wins.mean()
    roi = pnl.sum() / (n * 100) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1
    n_seasons = seasons.nunique()
    bps = n / n_seasons if n_seasons > 0 else n
    sharpe = ev / std * np.sqrt(bps) if std > 0 else 0
    mls = max_ls(pnl < 0)

    season_rois = []
    for s in sorted(seasons.unique()):
        sm = seasons == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = pnl[sm.values]
        season_rois.append(sp.sum() / (sn * 100) * 100)
    n_pos = sum(1 for r in season_rois if r > 0)

    return {
        "name": name, "bets": n, "bps": bps, "wr": wr, "roi": roi,
        "sharpe": sharpe, "max_ls": mls, "max_dd": mdd,
        "folds_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
        "cum_pnl": cum,
    }


def print_metrics(m):
    if m is None:
        print("  (too few bets)")
        return
    rois_str = ", ".join(f"{r:+.0f}" for r in m["season_rois"])
    print(f"  {m['name']}")
    print(f"    Bets: {m['bets']} ({m['bps']:.0f}/season)")
    print(f"    WR: {m['wr']*100:.1f}%  ROI: {m['roi']:+.1f}%  Sharpe: {m['sharpe']:.3f}")
    print(f"    MaxL: {m['max_ls']}  MaxDD: {m['max_dd']:.1f}%")
    print(f"    Folds: {m['folds_pos']}  Seasons: [{rois_str}]")


# ---------------------------------------------------------------------------
# Data pipeline (shared)
# ---------------------------------------------------------------------------

def build_shared_dataset():
    from src.features import build_spec_features, SPEC_FEATURES
    from src.model import ModelConfig, compute_divergence, run_walk_forward
    from src.data_loader import american_to_decimal

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

    mk = ["season", "date", "home_team", "away_team"]
    full["month"] = pd.to_datetime(full["date"]).dt.month
    full["day"] = pd.to_datetime(full["date"]).dt.day
    keep = [c for c in full.columns if c not in div.columns or c in mk]
    fs = full[keep].drop_duplicates(subset=mk)
    df = div.merge(fs, on=mk, how="left").drop_duplicates(subset=mk, keep="first")

    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df["closing_decimal_odds_favorite"] - df["pred_consensus"]
    df["fav_won"] = df["fav_margin"] > 0
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["day"] = pd.to_datetime(df["date"]).dt.day
    df["is_first_half"] = (df["month"] < 7) | ((df["month"] == 7) & (df["day"] <= ASG_DAY))
    df["margin_home"] = df["home_final"] - df["away_final"]

    # Away underdog universe
    away_dog = df[df["fav_is_home"]].copy()
    away_dog["dog_decimal"] = away_dog["away_decimal_odds"]
    away_dog["dog_won"] = ~away_dog["fav_won"]

    # RL data
    if "away_run_line_odds" in away_dog.columns:
        away_dog["rl_odds"] = away_dog["away_run_line_odds"].apply(
            lambda x: american_to_decimal(x) if pd.notna(x) and x != 0 else np.nan
        )
    else:
        away_dog["rl_odds"] = np.nan
    away_dog["rl_odds"] = away_dog["rl_odds"].fillna(1.87)
    away_dog["rl_covers"] = away_dog["margin_home"] <= 1

    if "home_run_line" in away_dog.columns:
        away_dog["rl_valid"] = away_dog["home_run_line"].isin([-1.5, 1.5])
    else:
        away_dog["rl_valid"] = False

    # Game ID for overlap tracking
    away_dog["game_id"] = (
        away_dog["season"].astype(str) + "_" +
        away_dog["date"].astype(str) + "_" +
        away_dog["home_team"] + "_" +
        away_dog["away_team"]
    )

    print(f"Away underdog universe: {len(away_dog)} games")
    return away_dog


# ---------------------------------------------------------------------------
# Strategy definitions
# ---------------------------------------------------------------------------

def apply_s3_dual(df):
    """S3-dual: away ML underdog with dual-regime filters."""
    base = df["edge_consensus"] < -0.05
    rpi_ok = df["rpi_diff"] <= 0
    elo_ok = df["elo_diff"] <= 30
    s3_base = base & rpi_ok & elo_ok

    h1_strict = s3_base & df["is_first_half"] & (df["rpi_diff"] <= -0.01) & (df["elo_diff"] <= 15)
    h2_base = s3_base & ~df["is_first_half"]
    mask = h1_strict | h2_base

    bets = df[mask].copy()
    bets["pnl"] = np.where(bets["dog_won"], (bets["dog_decimal"] - 1) * 100, -100)
    bets["strategy"] = "S3-dual"
    return bets


def apply_rl_1h(df):
    """RL +1.5 away: 1H + edge > 0.10."""
    mask = (df["edge_consensus"] > 0.10) & df["is_first_half"] & df["rl_valid"]
    bets = df[mask].copy()
    bets["pnl"] = np.where(bets["rl_covers"], (bets["rl_odds"] - 1) * 100, -100)
    bets["strategy"] = "RL-1H"
    return bets


def apply_rl_fip(df):
    """RL +1.5 away: FIP > 0.5 + edge > 0.10."""
    if "starter_fip_diff" not in df.columns:
        return df.iloc[:0].copy()
    mask = (
        (df["edge_consensus"] > 0.10) &
        (df["starter_fip_diff"] > 0.5) &
        df["rl_valid"]
    )
    bets = df[mask].copy()
    bets["pnl"] = np.where(bets["rl_covers"], (bets["rl_odds"] - 1) * 100, -100)
    bets["strategy"] = "RL-FIP"
    return bets


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def section1_overlap(s3, rl, rl_fip, label_rl):
    print(f"\n{'#'*80}")
    print(f"SECTION 1: OVERLAP ANALYSIS — S3-dual vs {label_rl}")
    print(f"{'#'*80}")

    s3_ids = set(s3["game_id"])
    rl_ids = set(rl["game_id"])

    overlap = s3_ids & rl_ids
    s3_only = s3_ids - rl_ids
    rl_only = rl_ids - s3_ids

    print(f"\n  S3-dual bets: {len(s3_ids)}")
    print(f"  {label_rl} bets: {len(rl_ids)}")
    print(f"  Overlap (same game): {len(overlap)}")
    print(f"  S3-only: {len(s3_only)}")
    print(f"  {label_rl}-only: {len(rl_only)}")
    print(f"  Overlap rate: {len(overlap)/max(len(s3_ids|rl_ids),1)*100:.1f}% of union")
    print(f"  Jaccard similarity: {len(overlap)/max(len(s3_ids|rl_ids),1):.3f}")

    if overlap:
        # What happens on overlap games?
        s3_overlap = s3[s3["game_id"].isin(overlap)].set_index("game_id")
        rl_overlap = rl[rl["game_id"].isin(overlap)].set_index("game_id")
        common = s3_overlap.index.intersection(rl_overlap.index)

        s3_pnl = s3_overlap.loc[common, "pnl"]
        rl_pnl = rl_overlap.loc[common, "pnl"]

        print(f"\n  Overlap games ({len(common)}):")
        print(f"    S3 WR on overlap: {(s3_pnl > 0).mean()*100:.1f}%")
        print(f"    RL cover on overlap: {(rl_pnl > 0).mean()*100:.1f}%")
        both_win = ((s3_pnl > 0) & (rl_pnl > 0)).sum()
        both_lose = ((s3_pnl < 0) & (rl_pnl < 0)).sum()
        s3_win_rl_lose = ((s3_pnl > 0) & (rl_pnl < 0)).sum()
        rl_win_s3_lose = ((rl_pnl > 0) & (s3_pnl < 0)).sum()
        print(f"    Both win: {both_win} ({both_win/len(common)*100:.1f}%)")
        print(f"    Both lose: {both_lose} ({both_lose/len(common)*100:.1f}%)")
        print(f"    S3 win, RL lose: {s3_win_rl_lose}")
        print(f"    RL win, S3 lose: {rl_win_s3_lose}")

    # FIP variant overlap
    if len(rl_fip) > 0:
        fip_ids = set(rl_fip["game_id"])
        print(f"\n  RL-FIP bets: {len(fip_ids)}")
        print(f"  RL-FIP overlap with S3: {len(s3_ids & fip_ids)}")
        print(f"  RL-FIP overlap with {label_rl}: {len(rl_ids & fip_ids)}")


def section2_correlation(s3, rl, label_rl):
    print(f"\n{'#'*80}")
    print(f"SECTION 2: RETURN CORRELATION — S3-dual vs {label_rl}")
    print(f"{'#'*80}")

    # Daily PnL
    s3["date_norm"] = pd.to_datetime(s3["date"]).dt.normalize()
    rl["date_norm"] = pd.to_datetime(rl["date"]).dt.normalize()

    s3_daily = s3.groupby("date_norm")["pnl"].sum()
    rl_daily = rl.groupby("date_norm")["pnl"].sum()

    # Align on common dates where at least one strategy has bets
    all_dates = s3_daily.index.union(rl_daily.index)
    s3_aligned = s3_daily.reindex(all_dates, fill_value=0)
    rl_aligned = rl_daily.reindex(all_dates, fill_value=0)

    # Only dates where both have bets
    both_active = (s3_aligned != 0) & (rl_aligned != 0)

    print(f"\n  Trading days: {len(all_dates)}")
    print(f"  Days S3 active: {(s3_aligned != 0).sum()}")
    print(f"  Days {label_rl} active: {(rl_aligned != 0).sum()}")
    print(f"  Days both active: {both_active.sum()}")

    if both_active.sum() >= 20:
        corr = s3_aligned[both_active].corr(rl_aligned[both_active])
        print(f"  Daily PnL correlation (both active): {corr:.3f}")
    else:
        print(f"  Too few co-active days for correlation ({both_active.sum()})")

    # Full daily correlation (0 on inactive days)
    if len(all_dates) > 20:
        full_corr = s3_aligned.corr(rl_aligned)
        print(f"  Daily PnL correlation (all dates, 0-filled): {full_corr:.3f}")

    # Monthly correlation
    s3_monthly = s3.groupby([s3["season"], s3["month"]])["pnl"].sum()
    rl_monthly = rl.groupby([rl["season"], rl["month"]])["pnl"].sum()
    common_months = s3_monthly.index.intersection(rl_monthly.index)
    if len(common_months) >= 10:
        monthly_corr = s3_monthly.loc[common_months].corr(rl_monthly.loc[common_months])
        print(f"  Monthly PnL correlation: {monthly_corr:.3f}")

    # Season correlation
    s3_season = s3.groupby("season")["pnl"].sum()
    rl_season = rl.groupby("season")["pnl"].sum()
    common_seasons = s3_season.index.intersection(rl_season.index)
    if len(common_seasons) >= 5:
        season_corr = s3_season.loc[common_seasons].corr(rl_season.loc[common_seasons])
        print(f"  Season PnL correlation: {season_corr:.3f}")

        print(f"\n  Per-season PnL:")
        print(f"    {'Season':<8} {'S3':>8} {label_rl:>8} {'Combined':>10}")
        for s in sorted(common_seasons):
            s3v = s3_season.loc[s]
            rlv = rl_season.loc[s]
            print(f"    {int(s):<8} ${s3v:>+7,.0f} ${rlv:>+7,.0f} ${s3v+rlv:>+9,.0f}")


def section3_combined_portfolio(s3, rl, label_rl):
    print(f"\n{'#'*80}")
    print(f"SECTION 3: COMBINED PORTFOLIO — S3-dual + {label_rl}")
    print(f"{'#'*80}")

    # Combine all bets chronologically
    combined = pd.concat([
        s3[["date", "season", "month", "game_id", "pnl", "strategy"]],
        rl[["date", "season", "month", "game_id", "pnl", "strategy"]],
    ]).sort_values("date")

    print(f"\n  Total bets: {len(combined)} ({len(s3)} S3 + {len(rl)} RL)")

    # Individual metrics
    print("\n  --- Individual strategies ---")
    m_s3 = bankroll_metrics(s3.sort_values("date")["pnl"], "S3-dual (away ML)", s3["season"])
    print_metrics(m_s3)

    m_rl = bankroll_metrics(rl.sort_values("date")["pnl"], f"{label_rl} (away +1.5)", rl["season"])
    print_metrics(m_rl)

    # Combined (flat $100 per bet on both)
    print("\n  --- Combined portfolio (flat $100/bet) ---")
    m_comb = bankroll_metrics(combined["pnl"], "Combined (flat)", combined["season"])
    print_metrics(m_comb)

    # Diversification ratio
    if m_s3 and m_rl and m_comb:
        # Theoretical: if uncorrelated, combined Sharpe = sqrt(S1^2 + S2^2)
        theoretical_sharpe = np.sqrt(m_s3["sharpe"]**2 + m_rl["sharpe"]**2)
        print(f"\n  Diversification analysis:")
        print(f"    S3 Sharpe: {m_s3['sharpe']:.3f}")
        print(f"    {label_rl} Sharpe: {m_rl['sharpe']:.3f}")
        print(f"    Combined Sharpe: {m_comb['sharpe']:.3f}")
        print(f"    Theoretical (uncorrelated): {theoretical_sharpe:.3f}")
        print(f"    S3 MaxDD: {m_s3['max_dd']:.1f}%  {label_rl} MaxDD: {m_rl['max_dd']:.1f}%  Combined MaxDD: {m_comb['max_dd']:.1f}%")

    # Combined per-season breakdown
    print(f"\n  --- Combined per-season ---")
    print(f"    {'Season':<8} {'S3 bets':>8} {'RL bets':>8} {'Total':>6} {'S3 PnL':>9} {'RL PnL':>9} {'Combined':>10} {'ROI':>7}")
    for s in sorted(combined["season"].unique()):
        s3s = s3[s3["season"] == s]
        rls = rl[rl["season"] == s]
        cs = combined[combined["season"] == s]
        s3_pnl = s3s["pnl"].sum() if len(s3s) > 0 else 0
        rl_pnl = rls["pnl"].sum() if len(rls) > 0 else 0
        total = len(cs)
        roi = (s3_pnl + rl_pnl) / (total * 100) * 100 if total > 0 else 0
        print(f"    {int(s):<8} {len(s3s):>8} {len(rls):>8} {total:>6} ${s3_pnl:>+8,.0f} ${rl_pnl:>+8,.0f} ${s3_pnl+rl_pnl:>+9,.0f} {roi:>+6.1f}%")

    return combined, m_s3, m_rl, m_comb


def section4_drawdown(s3, rl, combined):
    print(f"\n{'#'*80}")
    print("SECTION 4: DRAWDOWN & BANKROLL CURVES")
    print(f"{'#'*80}")

    # Daily aggregate PnL for all three
    s3_daily = s3.sort_values("date").groupby(pd.to_datetime(s3["date"]).dt.normalize())["pnl"].sum()
    rl_daily = rl.sort_values("date").groupby(pd.to_datetime(rl["date"]).dt.normalize())["pnl"].sum()
    comb_daily = combined.sort_values("date").groupby(pd.to_datetime(combined["date"]).dt.normalize())["pnl"].sum()

    all_dates = sorted(set(s3_daily.index) | set(rl_daily.index))
    s3_a = s3_daily.reindex(all_dates, fill_value=0).cumsum()
    rl_a = rl_daily.reindex(all_dates, fill_value=0).cumsum()
    comb_a = comb_daily.reindex(all_dates, fill_value=0).cumsum()

    # Print sparkline-style curve
    def sparkline(cum, label, width=60):
        if len(cum) == 0:
            return
        vals = cum.values
        n_pts = min(width, len(vals))
        indices = np.linspace(0, len(vals) - 1, n_pts, dtype=int)
        pts = vals[indices]
        vmin, vmax = pts.min(), pts.max()
        rng = vmax - vmin if vmax > vmin else 1
        chars = "_.-~+*#"
        bars = "".join(chars[min(6, int((v - vmin) / rng * 6))] for v in pts)
        print(f"  {label}")
        print(f"    [{bars}]")
        print(f"    End: ${vals[-1]:+,.0f}  Peak: ${vals.max():+,.0f}  Trough: ${vals.min():+,.0f}")

    sparkline(s3_a, "S3-dual")
    sparkline(rl_a, "RL +1.5")
    sparkline(comb_a, "Combined")

    # Simultaneous drawdown analysis
    print(f"\n  Worst simultaneous drawdowns (monthly):")
    s3_m = s3.groupby([s3["season"], s3["month"]])["pnl"].sum()
    rl_m = rl.groupby([rl["season"], rl["month"]])["pnl"].sum()
    all_months = s3_m.index.union(rl_m.index)
    s3_ma = s3_m.reindex(all_months, fill_value=0)
    rl_ma = rl_m.reindex(all_months, fill_value=0)
    comb_ma = s3_ma + rl_ma

    worst_months = comb_ma.nsmallest(10)
    print(f"    {'Month':>12} {'S3':>8} {'RL':>8} {'Combined':>10}")
    for (season, month), val in worst_months.items():
        s3v = s3_ma.get((season, month), 0)
        rlv = rl_ma.get((season, month), 0)
        print(f"    {int(season)}-{int(month):02d}       ${s3v:>+7,.0f} ${rlv:>+7,.0f} ${val:>+9,.0f}")

    # Count months where both strategies lose
    both_neg = ((s3_ma < 0) & (rl_ma < 0)).sum()
    total_common = ((s3_ma != 0) & (rl_ma != 0)).sum()
    print(f"\n  Months both lose: {both_neg}/{total_common} ({both_neg/max(total_common,1)*100:.0f}%)")

    # Recovery: worst S3 months — does RL offset?
    s3_worst = s3_ma.nsmallest(5)
    print(f"\n  S3's 5 worst months — RL offset:")
    for (season, month), val in s3_worst.items():
        rlv = rl_ma.get((season, month), 0)
        print(f"    {int(season)}-{int(month):02d}: S3 ${val:>+7,.0f}  RL ${rlv:>+7,.0f}  Net ${val+rlv:>+7,.0f}")

    rl_worst = rl_ma.nsmallest(5)
    print(f"\n  RL's 5 worst months — S3 offset:")
    for (season, month), val in rl_worst.items():
        s3v = s3_ma.get((season, month), 0)
        print(f"    {int(season)}-{int(month):02d}: RL ${val:>+7,.0f}  S3 ${s3v:>+7,.0f}  Net ${val+s3v:>+7,.0f}")


def section5_allocation(s3, rl, label_rl):
    print(f"\n{'#'*80}")
    print("SECTION 5: ALLOCATION SCENARIOS")
    print(f"{'#'*80}")

    # Test different allocation ratios (% of $100 base stake to each strategy)
    # With Kelly sizing from individual strategies
    print(f"\n  Equal allocation ($100 per bet on each):")
    combined_equal = pd.concat([
        s3[["date", "season", "pnl"]],
        rl[["date", "season", "pnl"]],
    ]).sort_values("date")
    m = bankroll_metrics(combined_equal["pnl"], "Equal $100", combined_equal["season"])
    if m:
        print(f"    Bets: {m['bets']} ({m['bps']:.0f}/s)  ROI: {m['roi']:+.1f}%  Sharpe: {m['sharpe']:.3f}  MaxDD: {m['max_dd']:.1f}%")

    # Weighted: S3 gets higher stake (higher ROI), RL lower
    for s3_stake, rl_stake, desc in [
        (150, 75, "S3=$150, RL=$75 (2:1 favor S3)"),
        (100, 50, "S3=$100, RL=$50 (2:1 favor S3)"),
        (75, 100, "S3=$75, RL=$100 (favor RL volume)"),
        (100, 100, "S3=$100, RL=$100 (equal — baseline)"),
    ]:
        s3_pnl = np.where(s3["pnl"] > 0, s3["pnl"] / 100 * s3_stake, -s3_stake)
        rl_pnl = np.where(rl["pnl"] > 0, rl["pnl"] / 100 * rl_stake, -rl_stake)

        all_pnl = np.concatenate([s3_pnl, rl_pnl])
        all_seasons = pd.concat([s3["season"], rl["season"]])

        total_stake = len(s3_pnl) * s3_stake + len(rl_pnl) * rl_stake
        roi = all_pnl.sum() / total_stake * 100

        cum = np.cumsum(np.sort(all_pnl))  # approximate
        n = len(all_pnl)
        ev = all_pnl.mean()
        std = all_pnl.std(ddof=1)
        bps = n / all_seasons.nunique()
        sharpe = ev / std * np.sqrt(bps) if std > 0 else 0

        print(f"  {desc}")
        print(f"    Total stake: ${total_stake:,.0f}  PnL: ${all_pnl.sum():+,.0f}  ROI: {roi:+.1f}%  Sharpe: {sharpe:.3f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = build_shared_dataset()

    s3 = apply_s3_dual(df)
    rl_1h = apply_rl_1h(df)
    rl_fip = apply_rl_fip(df)

    print(f"\nStrategies built:")
    print(f"  S3-dual: {len(s3)} bets")
    print(f"  RL-1H (1H + edge>0.10): {len(rl_1h)} bets")
    print(f"  RL-FIP (FIP>0.5 + edge>0.10): {len(rl_fip)} bets")

    # Main analysis: S3 + RL-1H
    label = "RL-1H"
    section1_overlap(s3, rl_1h, rl_fip, label)
    section2_correlation(s3, rl_1h, label)
    combined, m_s3, m_rl, m_comb = section3_combined_portfolio(s3, rl_1h, label)
    section4_drawdown(s3, rl_1h, combined)
    section5_allocation(s3, rl_1h, label)

    # Also test with RL-FIP variant
    if len(rl_fip) >= 30:
        print(f"\n\n{'*'*80}")
        print("VARIANT: S3-dual + RL-FIP")
        print(f"{'*'*80}")
        label2 = "RL-FIP"
        section1_overlap(s3, rl_fip, rl_fip, label2)
        section2_correlation(s3, rl_fip, label2)
        section3_combined_portfolio(s3, rl_fip, label2)


if __name__ == "__main__":
    main()
