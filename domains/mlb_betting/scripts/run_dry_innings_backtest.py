"""Conditional dry innings strategy: bet under 0.5 runs in innings 2 and 3
when inning 1 was scoreless.

Logic: if both pitchers shut out the top of the order in inning 1,
they'll continue dominating the weaker 4-9 spots.

Assumed odds: 1.60 decimal for inning under 0.5 runs (breakeven 62.5%).

Usage:
    python scripts/run_dry_innings_backtest.py
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

INN_UNDER_ODDS = 1.60  # assumed decimal odds for inning under 0.5
BREAKEVEN = 1 / INN_UNDER_ODDS  # 62.5%


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
    """Compute bankroll metrics for inning bets at fixed odds."""
    df = df.sort_values("date").copy()
    n = len(df)
    if n < 20:
        return None

    hit = df[hit_col].values.astype(float)
    pnl = np.where(hit, (INN_UNDER_ODDS - 1) * 100, -100)
    cum_pnl = np.cumsum(pnl)

    hr = hit.mean()
    roi = pnl.sum() / (n * 100) * 100
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1

    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    b = INN_UNDER_ODDS - 1
    kelly_full = (hr * b - (1 - hr)) / b if b > 0 else 0
    kelly_full = max(0, kelly_full)

    mls = max_streak(hit, target=0)
    mws = max_streak(hit, target=1)

    bankroll = 10000 + cum_pnl
    peak = np.maximum.accumulate(bankroll)
    dd_pct = (peak - bankroll) / peak * 100
    max_dd = dd_pct.max()

    season_rois = []
    for s in sorted(df["season"].unique()):
        sm = df["season"] == s
        sn = sm.sum()
        if sn < 3:
            continue
        sp = np.where(df.loc[sm, hit_col].values, (INN_UNDER_ODDS - 1) * 100, -100)
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
        "max_win_streak": mws,
        "max_dd_pct": max_dd,
        "seasons_pos": f"{n_pos}/{len(season_rois)}",
        "season_rois": season_rois,
        "cum_pnl": cum_pnl,
    }


def print_metrics(m):
    if m is None:
        print("  (too few bets)")
        return
    print(f"  {m['name']}")
    print(f"    Bets: {m['bets']} ({m['bets_per_season']:.0f}/season)")
    print(f"    Hit: {m['hit_rate']*100:.1f}% (breakeven {BREAKEVEN*100:.1f}%)  "
          f"Odds: {INN_UNDER_ODDS:.2f}  ROI: {m['roi']:+.1f}%")
    print(f"    Sharpe: {m['sharpe']:.3f}  Kelly/2: {m['kelly_half']*100:.1f}%  "
          f"MaxL: {m['max_loss_streak']}  MaxDD: {m['max_dd_pct']:.1f}%")
    print(f"    Seasons: {m['seasons_pos']}")
    rois_str = ", ".join(f"{r:+.0f}" for r in m["season_rois"])
    print(f"    Per-season: [{rois_str}]")


def print_row(m):
    if m is None:
        return
    print(
        f"  {m['name']:<50} {m['bets']:5d} {m['bets_per_season']:4.0f} "
        f"{m['hit_rate']*100:5.1f}% {m['roi']:+6.1f}% {m['max_loss_streak']:5d} "
        f"{m['sharpe']:6.3f} {m['seasons_pos']:>6}"
    )


def main():
    from src.features import build_ou_features

    print("Building features...")
    df = build_ou_features()
    print(f"Total games: {len(df)}")

    # Filter to games with REAL inning data (not fake zeros from SDQL)
    # SDQL seasons (2004-2009) have all-zero inning cols — detect via innings_sum
    inn_cols = [f"away_inn_{i}" for i in range(1, 4)] + [f"home_inn_{i}" for i in range(1, 4)]
    has_inning_data = df[inn_cols].notna().all(axis=1)
    # Real games: at least one team scored at least 1 run across all innings
    away_inn_sum = sum(df[f"away_inn_{i}"] for i in range(1, 10) if f"away_inn_{i}" in df.columns)
    home_inn_sum = sum(df[f"home_inn_{i}"] for i in range(1, 10) if f"home_inn_{i}" in df.columns)
    has_real_data = (away_inn_sum + home_inn_sum) > 0
    df = df[has_inning_data & has_real_data].copy()
    print(f"Games with real inning data: {len(df)}")
    print(f"Seasons: {sorted(df['season'].unique())}")

    # Build inning columns
    for i in range(1, 4):
        df[f"inn{i}_runs"] = df[f"away_inn_{i}"] + df[f"home_inn_{i}"]

    df["scoreless_1st"] = df["inn1_runs"] == 0
    df["inn2_dry"] = df["inn2_runs"] == 0
    df["inn3_dry"] = df["inn3_runs"] == 0
    df["inn23_dry"] = df["inn2_dry"] & df["inn3_dry"]

    df["month"] = pd.to_datetime(df["date"]).dt.month

    # ========================================================================
    # BASELINE STATS
    # ========================================================================
    print(f"\n{'='*80}")
    print("BASELINE STATISTICS")
    print(f"{'='*80}")

    n_total = len(df)
    n_scl1 = df["scoreless_1st"].sum()
    pct_scl1 = n_scl1 / n_total * 100

    print(f"  Total games: {n_total}")
    print(f"  Scoreless 1st inning: {n_scl1} ({pct_scl1:.1f}%)")

    # Unconditional rates (all games)
    print(f"\n  Unconditional dry inning rates (all games):")
    for i in range(1, 4):
        dry_rate = (df[f"inn{i}_runs"] == 0).mean()
        print(f"    Inning {i}: {dry_rate*100:.1f}% scoreless")

    # Conditional rates (given scoreless 1st)
    cond = df[df["scoreless_1st"]].copy()
    print(f"\n  Conditional rates (given scoreless 1st, n={len(cond)}):")
    for col, label in [("inn2_dry", "Inn 2 dry"), ("inn3_dry", "Inn 3 dry"),
                        ("inn23_dry", "Inn 2+3 both dry")]:
        rate = cond[col].mean()
        marker = " *** ABOVE BREAKEVEN" if rate > BREAKEVEN else ""
        print(f"    {label}: {rate*100:.1f}% (breakeven {BREAKEVEN*100:.1f}%){marker}")

    # ========================================================================
    # INNING 2 UNDER 0.5 (conditional on scoreless 1st)
    # ========================================================================
    print(f"\n{'='*80}")
    print("INNING 2 UNDER 0.5 (conditional on scoreless 1st)")
    print(f"{'='*80}")

    base = cond.copy()
    m = metrics(base, "inn2_dry", "Inn2 base (no filters)")
    print()
    print_metrics(m)

    # Filter sweep
    inn2_results = [m]

    # Low sp_ra_combined (quality starters)
    if "sp_ra_combined_short" in base.columns:
        for thresh in [7.0, 7.5, 8.0, 8.5, 9.0]:
            filt = base[base["sp_ra_combined_short"] < thresh]
            m = metrics(filt, "inn2_dry", f"sp_ra<{thresh:.0f}")
            inn2_results.append(m)

    # Low combined RPG (weak offenses)
    if "combined_rpg" in base.columns:
        for thresh in [7.5, 8.0, 8.5, 9.0]:
            filt = base[base["combined_rpg"] < thresh]
            m = metrics(filt, "inn2_dry", f"combined_rpg<{thresh:.1f}")
            inn2_results.append(m)

    # Low O/U line (market expects few runs)
    if "close_ou" in base.columns:
        for thresh in [7.5, 8.0, 8.5]:
            filt = base[base["close_ou"] <= thresh]
            m = metrics(filt, "inn2_dry", f"close_ou<={thresh:.1f}")
            inn2_results.append(m)

    # First-inning RA (pitchers good at 1st inning historically)
    if "sp_fi_ra_combined" in base.columns:
        med = base["sp_fi_ra_combined"].median()
        filt = base[base["sp_fi_ra_combined"] < med]
        m = metrics(filt, "inn2_dry", f"sp_fi_ra<{med:.2f} (median)")
        inn2_results.append(m)
        # Also try lower thresholds
        for pct in [25, 10]:
            q = base["sp_fi_ra_combined"].quantile(pct / 100)
            filt = base[base["sp_fi_ra_combined"] < q]
            m = metrics(filt, "inn2_dry", f"sp_fi_ra<{q:.2f} (p{pct})")
            inn2_results.append(m)

    # Starter FIP combined (quality by FIP)
    if "starter_fip_combined" in base.columns:
        med = base["starter_fip_combined"].median()
        filt = base[base["starter_fip_combined"] < med]
        m = metrics(filt, "inn2_dry", f"starter_fip<{med:.1f}")
        inn2_results.append(m)

    # Starter WHIP combined (don't allow baserunners)
    if "starter_whip_combined" in base.columns:
        med = base["starter_whip_combined"].median()
        filt = base[base["starter_whip_combined"] < med]
        m = metrics(filt, "inn2_dry", f"starter_whip<{med:.2f}")
        inn2_results.append(m)

    print(f"\n{'Filter':<50} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
          f"{'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'Flds':>6}")
    print("-" * 95)
    for m in inn2_results:
        print_row(m)

    # ========================================================================
    # INNING 3 UNDER 0.5 (conditional on scoreless 1st)
    # ========================================================================
    print(f"\n{'='*80}")
    print("INNING 3 UNDER 0.5 (conditional on scoreless 1st)")
    print(f"{'='*80}")

    m = metrics(base, "inn3_dry", "Inn3 base (no filters)")
    print()
    print_metrics(m)

    inn3_results = [m]

    if "sp_ra_combined_short" in base.columns:
        for thresh in [7.0, 7.5, 8.0, 8.5, 9.0]:
            filt = base[base["sp_ra_combined_short"] < thresh]
            m = metrics(filt, "inn3_dry", f"sp_ra<{thresh:.0f}")
            inn3_results.append(m)

    if "combined_rpg" in base.columns:
        for thresh in [7.5, 8.0, 8.5, 9.0]:
            filt = base[base["combined_rpg"] < thresh]
            m = metrics(filt, "inn3_dry", f"combined_rpg<{thresh:.1f}")
            inn3_results.append(m)

    if "close_ou" in base.columns:
        for thresh in [7.5, 8.0, 8.5]:
            filt = base[base["close_ou"] <= thresh]
            m = metrics(filt, "inn3_dry", f"close_ou<={thresh:.1f}")
            inn3_results.append(m)

    if "sp_fi_ra_combined" in base.columns:
        med = base["sp_fi_ra_combined"].median()
        filt = base[base["sp_fi_ra_combined"] < med]
        m = metrics(filt, "inn3_dry", f"sp_fi_ra<{med:.2f}")
        inn3_results.append(m)

    if "starter_fip_combined" in base.columns:
        med = base["starter_fip_combined"].median()
        filt = base[base["starter_fip_combined"] < med]
        m = metrics(filt, "inn3_dry", f"starter_fip<{med:.1f}")
        inn3_results.append(m)

    if "starter_whip_combined" in base.columns:
        med = base["starter_whip_combined"].median()
        filt = base[base["starter_whip_combined"] < med]
        m = metrics(filt, "inn3_dry", f"starter_whip<{med:.2f}")
        inn3_results.append(m)

    print(f"\n{'Filter':<50} {'Bets':>5} {'B/S':>4} {'Hit%':>6} "
          f"{'ROI':>7} {'MaxL':>5} {'Shrp':>6} {'Flds':>6}")
    print("-" * 95)
    for m in inn3_results:
        print_row(m)

    # ========================================================================
    # COMBINED FILTERS (best of inn2 + inn3)
    # ========================================================================
    print(f"\n{'='*80}")
    print("COMBINED FILTER GRID: sp_ra x close_ou x starter_whip")
    print(f"{'='*80}")

    combos = []
    for hit_col, label in [("inn2_dry", "Inn2"), ("inn3_dry", "Inn3")]:
        # sp_ra x close_ou
        if "sp_ra_combined_short" in base.columns and "close_ou" in base.columns:
            for sp in [7.0, 7.5, 8.0, 8.5]:
                for ou in [7.5, 8.0, 8.5]:
                    filt = base[(base["sp_ra_combined_short"] < sp) & (base["close_ou"] <= ou)]
                    n = len(filt)
                    if n < 30:
                        continue
                    hr = filt[hit_col].mean()
                    roi = np.where(filt[hit_col], (INN_UNDER_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                    combos.append((f"{label}: sp_ra<{sp:.0f} + ou<={ou:.1f}", n, n / filt["season"].nunique(), hr, roi))

        # sp_ra x starter_whip
        if "sp_ra_combined_short" in base.columns and "starter_whip_combined" in base.columns:
            whip_med = base["starter_whip_combined"].median()
            for sp in [7.0, 7.5, 8.0]:
                filt = base[(base["sp_ra_combined_short"] < sp) & (base["starter_whip_combined"] < whip_med)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt[hit_col].mean()
                roi = np.where(filt[hit_col], (INN_UNDER_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                combos.append((f"{label}: sp_ra<{sp:.0f} + whip<{whip_med:.1f}", n, n / filt["season"].nunique(), hr, roi))

        # close_ou x starter_fip
        if "close_ou" in base.columns and "starter_fip_combined" in base.columns:
            fip_med = base["starter_fip_combined"].median()
            for ou in [7.5, 8.0, 8.5]:
                filt = base[(base["close_ou"] <= ou) & (base["starter_fip_combined"] < fip_med)]
                n = len(filt)
                if n < 30:
                    continue
                hr = filt[hit_col].mean()
                roi = np.where(filt[hit_col], (INN_UNDER_ODDS - 1) * 100, -100).sum() / (n * 100) * 100
                combos.append((f"{label}: ou<={ou:.1f} + fip<{fip_med:.1f}", n, n / filt["season"].nunique(), hr, roi))

    if combos:
        print(f"{'Filter':<50} {'Bets':>5} {'B/S':>4} {'Hit%':>6} {'ROI':>7}")
        print("-" * 80)
        for name, n, bps, hr, roi in sorted(combos, key=lambda x: -x[4]):
            marker = " ***" if hr > BREAKEVEN and roi > 0 else ""
            print(f"  {name:<48} {n:5d} {bps:4.0f} {hr*100:5.1f}% {roi:+6.1f}%{marker}")

    # ========================================================================
    # MONTHLY BREAKDOWN (baseline)
    # ========================================================================
    print(f"\n{'='*80}")
    print("MONTHLY BREAKDOWN (scoreless 1st, no extra filters)")
    print(f"{'='*80}")
    for mo in sorted(base["month"].unique()):
        mb = base[base["month"] == mo]
        n = len(mb)
        if n < 10:
            continue
        inn2_hr = mb["inn2_dry"].mean()
        inn3_hr = mb["inn3_dry"].mean()
        inn23_hr = mb["inn23_dry"].mean()
        print(f"  Month {mo:2d}: {n:4d} games  "
              f"Inn2 {inn2_hr*100:5.1f}%  Inn3 {inn3_hr*100:5.1f}%  "
              f"Both {inn23_hr*100:5.1f}%")

    # ========================================================================
    # SEASON BREAKDOWN
    # ========================================================================
    print(f"\n{'='*80}")
    print("PER-SEASON BREAKDOWN (scoreless 1st, no extra filters)")
    print(f"{'='*80}")
    for s in sorted(base["season"].unique()):
        sb = base[base["season"] == s]
        n = len(sb)
        if n < 10:
            continue
        inn2_hr = sb["inn2_dry"].mean()
        inn3_hr = sb["inn3_dry"].mean()
        print(f"  {s}: {n:4d} games  Inn2 {inn2_hr*100:5.1f}%  Inn3 {inn3_hr*100:5.1f}%")


if __name__ == "__main__":
    main()
