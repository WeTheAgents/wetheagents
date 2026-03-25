"""Bankroll management metrics for away underdog ML strategies.

Computes: Kelly criterion, max drawdown, losing/winning streaks,
variance, Sharpe, ruin probability, optimal bankroll sizing.

Usage:
    python -m scripts.bankroll_analysis
"""

import logging
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)


@dataclass
class BankrollMetrics:
    name: str
    n_bets: int
    win_rate: float
    avg_odds: float
    median_odds: float
    roi: float
    ev_per_bet: float          # expected value per $100 bet
    variance_per_bet: float    # variance of single bet outcome
    std_per_bet: float         # std of single bet
    sharpe: float              # annualized Sharpe (per-bet Sharpe * sqrt(bets/season))

    # Kelly
    kelly_full: float          # full Kelly fraction
    kelly_half: float          # half Kelly (practical)
    kelly_quarter: float       # quarter Kelly (conservative)

    # Streaks
    max_consecutive_losses: int
    max_consecutive_wins: int
    avg_loss_streak: float
    avg_win_streak: float

    # Drawdown
    max_drawdown_units: float    # in flat $100 units
    max_drawdown_pct: float      # % of peak bankroll (starting 100 units)
    max_drawdown_bets: int       # how many bets the max DD lasted
    avg_drawdown_pct: float      # average drawdown from peaks

    # Ruin
    prob_ruin_50pct: float       # P(losing 50% of bankroll)
    bankroll_for_1pct_ruin: float  # bankroll needed for <1% ruin probability

    # Distribution
    pnl_p5: float    # 5th percentile of cumulative PnL at end
    pnl_p25: float
    pnl_p50: float
    pnl_p75: float
    pnl_p95: float

    # Per-season
    seasons_profitable: int
    seasons_total: int
    worst_season_roi: float
    best_season_roi: float


def compute_metrics(df: pd.DataFrame, mask: pd.Series, name: str) -> BankrollMetrics:
    """Compute full bankroll metrics for a strategy."""
    b = df[mask].sort_values("date").copy()
    n = len(b)

    dog_won = ~b["fav_won"]
    odds = b["dog_decimal"].values
    outcomes = dog_won.values.astype(float)

    # PnL per bet (flat $100)
    pnl = np.where(outcomes, (odds - 1) * 100, -100)
    cum_pnl = np.cumsum(pnl)

    # Basic stats
    win_rate = outcomes.mean()
    avg_odds = odds.mean()
    median_odds = np.median(odds)
    roi = pnl.sum() / (n * 100) * 100
    ev_per_bet = pnl.mean()

    # Variance & Sharpe
    var_per_bet = np.var(pnl, ddof=1)
    std_per_bet = np.sqrt(var_per_bet)
    sharpe_per_bet = ev_per_bet / std_per_bet if std_per_bet > 0 else 0
    # Annualize: ~250 bets/season for large strategies, use actual
    bets_per_season = n / b["season"].nunique() if b["season"].nunique() > 0 else n
    sharpe_annual = sharpe_per_bet * np.sqrt(bets_per_season)

    # Kelly criterion: f* = (p * b - q) / b  where b = avg_odds - 1, p = win_rate, q = 1-p
    b_kelly = avg_odds - 1
    q = 1 - win_rate
    kelly_full = (win_rate * b_kelly - q) / b_kelly if b_kelly > 0 else 0
    kelly_full = max(0, kelly_full)  # never negative
    kelly_half = kelly_full / 2
    kelly_quarter = kelly_full / 4

    # Streaks
    max_loss_streak = _max_streak(outcomes, target=0)
    max_win_streak = _max_streak(outcomes, target=1)
    avg_loss_streak = _avg_streak(outcomes, target=0)
    avg_win_streak = _avg_streak(outcomes, target=1)

    # Drawdown
    peak = np.maximum.accumulate(cum_pnl)
    drawdown = peak - cum_pnl  # always >= 0
    max_dd_units = drawdown.max()

    # Max DD as % of peak bankroll (starting with 100 units = $10,000)
    starting_bankroll = 10000  # $10,000 = 100 units
    bankroll_curve = starting_bankroll + cum_pnl
    peak_bankroll = np.maximum.accumulate(bankroll_curve)
    dd_pct = (peak_bankroll - bankroll_curve) / peak_bankroll * 100
    max_dd_pct = dd_pct.max()
    avg_dd_pct = dd_pct[dd_pct > 0].mean() if (dd_pct > 0).any() else 0

    # DD duration (number of bets in max DD period)
    max_dd_idx = np.argmax(drawdown)
    peak_before_dd = np.argmax(cum_pnl[:max_dd_idx + 1]) if max_dd_idx > 0 else 0
    max_dd_bets = max_dd_idx - peak_before_dd

    # Ruin probability (simplified binomial model)
    # P(ruin) ≈ (q/p)^(bankroll/avg_bet) for favorable games
    # More practical: Monte Carlo
    prob_ruin_50, bankroll_1pct = _ruin_simulation(
        win_rate, avg_odds, n_bets=n, n_sims=10000
    )

    # Monte Carlo PnL distribution (resample with replacement)
    mc_finals = []
    rng = np.random.default_rng(42)
    for _ in range(5000):
        sample_idx = rng.choice(n, size=n, replace=True)
        mc_finals.append(pnl[sample_idx].sum())
    mc_finals = np.array(mc_finals)

    # Per-season breakdown
    season_rois = []
    for s in sorted(b["season"].unique()):
        sm = b["season"] == s
        sn = sm.sum()
        if sn < 5:
            continue
        s_pnl = pnl[sm.values]
        s_roi = s_pnl.sum() / (sn * 100) * 100
        season_rois.append(s_roi)

    return BankrollMetrics(
        name=name,
        n_bets=n,
        win_rate=win_rate,
        avg_odds=avg_odds,
        median_odds=median_odds,
        roi=roi,
        ev_per_bet=ev_per_bet,
        variance_per_bet=var_per_bet,
        std_per_bet=std_per_bet,
        sharpe=sharpe_annual,
        kelly_full=kelly_full,
        kelly_half=kelly_half,
        kelly_quarter=kelly_quarter,
        max_consecutive_losses=max_loss_streak,
        max_consecutive_wins=max_win_streak,
        avg_loss_streak=avg_loss_streak,
        avg_win_streak=avg_win_streak,
        max_drawdown_units=max_dd_units,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_bets=max_dd_bets,
        avg_drawdown_pct=avg_dd_pct,
        prob_ruin_50pct=prob_ruin_50,
        bankroll_for_1pct_ruin=bankroll_1pct,
        pnl_p5=np.percentile(mc_finals, 5),
        pnl_p25=np.percentile(mc_finals, 25),
        pnl_p50=np.percentile(mc_finals, 50),
        pnl_p75=np.percentile(mc_finals, 75),
        pnl_p95=np.percentile(mc_finals, 95),
        seasons_profitable=sum(1 for r in season_rois if r > 0),
        seasons_total=len(season_rois),
        worst_season_roi=min(season_rois) if season_rois else 0,
        best_season_roi=max(season_rois) if season_rois else 0,
    )


def _max_streak(outcomes: np.ndarray, target: int) -> int:
    """Maximum consecutive occurrences of target value."""
    max_s = 0
    current = 0
    for o in outcomes:
        if o == target:
            current += 1
            max_s = max(max_s, current)
        else:
            current = 0
    return max_s


def _avg_streak(outcomes: np.ndarray, target: int) -> float:
    """Average streak length of target value."""
    streaks = []
    current = 0
    for o in outcomes:
        if o == target:
            current += 1
        else:
            if current > 0:
                streaks.append(current)
            current = 0
    if current > 0:
        streaks.append(current)
    return np.mean(streaks) if streaks else 0


def _ruin_simulation(
    win_rate: float, avg_odds: float, n_bets: int, n_sims: int = 10000
) -> tuple[float, float]:
    """Monte Carlo ruin probability.

    Returns:
        (prob_ruin_50pct_at_100units, bankroll_needed_for_1pct_ruin)
    """
    rng = np.random.default_rng(42)
    b = avg_odds - 1  # net win per unit

    # Test at 100 units starting bankroll
    ruin_count = 0
    for _ in range(n_sims):
        bankroll = 100.0  # 100 units
        for _ in range(n_bets):
            if rng.random() < win_rate:
                bankroll += b  # win b units
            else:
                bankroll -= 1  # lose 1 unit
            if bankroll <= 50:  # 50% drawdown = ruin
                ruin_count += 1
                break

    prob_ruin_50 = ruin_count / n_sims

    # Binary search for bankroll where P(ruin) < 1%
    lo, hi = 50, 5000
    for _ in range(15):
        mid = (lo + hi) / 2
        ruin_c = 0
        for _ in range(n_sims):
            br = float(mid)
            for _ in range(n_bets):
                if rng.random() < win_rate:
                    br += b
                else:
                    br -= 1
                if br <= mid * 0.5:
                    ruin_c += 1
                    break
        p = ruin_c / n_sims
        if p > 0.01:
            lo = mid
        else:
            hi = mid

    return prob_ruin_50, hi


def print_metrics(m: BankrollMetrics) -> None:
    """Pretty-print all metrics for one strategy."""
    print(f"\n{'='*70}")
    print(f"  {m.name}")
    print(f"{'='*70}")

    print(f"\n  --- Basic ---")
    print(f"  Bets:           {m.n_bets}")
    print(f"  Win rate:       {m.win_rate*100:.1f}%")
    print(f"  Avg odds:       {m.avg_odds:.3f}  (median: {m.median_odds:.3f})")
    print(f"  ROI:            {m.roi:+.2f}%")
    print(f"  EV per $100:    ${m.ev_per_bet:+.2f}")
    print(f"  Std per bet:    ${m.std_per_bet:.2f}")
    print(f"  Sharpe (ann):   {m.sharpe:.3f}")

    print(f"\n  --- Kelly Criterion ---")
    print(f"  Full Kelly:     {m.kelly_full*100:.2f}% of bankroll per bet")
    print(f"  Half Kelly:     {m.kelly_half*100:.2f}%")
    print(f"  Quarter Kelly:  {m.kelly_quarter*100:.2f}%")
    if m.kelly_full > 0:
        growth = m.win_rate * np.log(1 + m.kelly_full * (m.avg_odds - 1)) + \
                 (1 - m.win_rate) * np.log(1 - m.kelly_full)
        print(f"  Kelly growth:   {growth*100:.4f}% per bet (log-optimal)")
        # Bankroll needed for $100 flat bet at half Kelly
        flat_unit = 100
        bankroll_half_k = flat_unit / m.kelly_half if m.kelly_half > 0 else float("inf")
        print(f"  Bankroll for $100 flat @ half Kelly: ${bankroll_half_k:,.0f}")

    print(f"\n  --- Streaks ---")
    print(f"  Max losses in a row:  {m.max_consecutive_losses}")
    print(f"  Max wins in a row:    {m.max_consecutive_wins}")
    print(f"  Avg loss streak:      {m.avg_loss_streak:.1f}")
    print(f"  Avg win streak:       {m.avg_win_streak:.1f}")

    print(f"\n  --- Drawdown ---")
    print(f"  Max drawdown:         {m.max_drawdown_units:.0f} units (${m.max_drawdown_units*100:,.0f} at $100/bet)")
    print(f"  Max DD % of peak:     {m.max_drawdown_pct:.1f}%")
    print(f"  Max DD duration:      {m.max_drawdown_bets} bets")
    print(f"  Avg DD % of peak:     {m.avg_drawdown_pct:.1f}%")

    print(f"\n  --- Ruin Probability (Monte Carlo, 10K sims) ---")
    print(f"  P(50% ruin) @ 100 units:  {m.prob_ruin_50pct*100:.1f}%")
    print(f"  Bankroll for <1% ruin:    {m.bankroll_for_1pct_ruin:.0f} units (${m.bankroll_for_1pct_ruin*100:,.0f})")

    print(f"\n  --- PnL Distribution (5K bootstrap) ---")
    print(f"  5th percentile:   ${m.pnl_p5:+,.0f}")
    print(f"  25th percentile:  ${m.pnl_p25:+,.0f}")
    print(f"  50th (median):    ${m.pnl_p50:+,.0f}")
    print(f"  75th percentile:  ${m.pnl_p75:+,.0f}")
    print(f"  95th percentile:  ${m.pnl_p95:+,.0f}")

    print(f"\n  --- Per Season ---")
    print(f"  Profitable seasons: {m.seasons_profitable}/{m.seasons_total}")
    print(f"  Worst season ROI:   {m.worst_season_roi:+.1f}%")
    print(f"  Best season ROI:    {m.best_season_roi:+.1f}%")


def main() -> None:
    # Reuse build_analysis_df from divergence script
    from scripts.analyze_divergence import build_analysis_df

    print("Building analysis dataset...")
    df = build_analysis_df()

    target = "closing_decimal_odds_favorite"
    pred_cols = ["pred_M0", "pred_M2", "pred_M3", "pred_M4"]

    # Setup (same as analyze_divergence.py)
    df["fav_won"] = df["regime"].isin(["M2", "M3"])
    df["fav_decimal"] = np.where(df["fav_is_home"], df["home_decimal_odds"], df["away_decimal_odds"])
    df["dog_decimal"] = np.where(df["fav_is_home"], df["away_decimal_odds"], df["home_decimal_odds"])
    df = df[df["dog_decimal"] <= 3.0].copy()

    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df[target] - df["pred_consensus"]
    df["dog_is_home"] = ~df["fav_is_home"]

    # Away underdog ML universe: fav is home, dog is away
    away_dog = df[df["fav_is_home"]].copy()
    base = away_dog["edge_consensus"] < -0.05

    print(f"\nAway underdog ML universe: {len(away_dog)} games")
    print(f"Base filter (edge<-0.05): {base.sum()} games")

    # Define 4 strategies
    strategies = {
        "S1: elo_diff<=0 + edge<-0.05": base & (away_dog["elo_diff"] <= 0),
        "S2: elo_diff<=30 + edge<-0.05": base & (away_dog["elo_diff"] <= 30),
        "S3: rpi<=0 + elo<=30 + edge<-0.05": base & (away_dog["rpi_diff"] <= 0) & (away_dog["elo_diff"] <= 30),
        "S4: rpi<=0 + home_bp>p75 + edge<-0.05": base & (away_dog["rpi_diff"] <= 0) & (away_dog["bp_ip_3d_home"] > away_dog["bp_ip_3d_home"].quantile(0.75)),
    }

    all_metrics = []
    for name, mask in strategies.items():
        print(f"\nComputing metrics for {name}...")
        m = compute_metrics(away_dog, mask, name)
        all_metrics.append(m)
        print_metrics(m)

    # Comparison table
    print(f"\n\n{'='*70}")
    print("COMPARISON TABLE")
    print(f"{'='*70}")
    header = f"{'Strategy':<45} {'N':>5} {'WR':>6} {'ROI':>7} {'Kelly½':>7} {'MaxDD':>7} {'MaxL':>5} {'Sharpe':>7} {'Ruin%':>6}"
    print(header)
    for m in all_metrics:
        print(f"{m.name:<45} {m.n_bets:5d} {m.win_rate*100:5.1f}% {m.roi:+6.1f}% "
              f"{m.kelly_half*100:6.2f}% {m.max_drawdown_pct:6.1f}% {m.max_consecutive_losses:5d} "
              f"{m.sharpe:6.3f} {m.prob_ruin_50pct*100:5.1f}%")

    # Kelly sizing recommendation
    print(f"\n{'='*70}")
    print("KELLY SIZING RECOMMENDATIONS (for $100 flat bet)")
    print(f"{'='*70}")
    for m in all_metrics:
        if m.kelly_half > 0:
            bankroll = 100 / m.kelly_half
            print(f"\n  {m.name}:")
            print(f"    Half Kelly bankroll: ${bankroll:,.0f}")
            print(f"    Quarter Kelly bankroll: ${100/m.kelly_quarter:,.0f}")
            print(f"    Expected annual profit (half K): ${m.ev_per_bet * m.n_bets / m.seasons_total:+,.0f}")
            print(f"    Max expected loss streak: {m.max_consecutive_losses} bets (${m.max_consecutive_losses * 100:,})")


if __name__ == "__main__":
    main()
