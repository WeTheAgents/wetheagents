"""S3 loss streak anatomy + sub-filter search.

Analyzes the max loss streaks in S3 (rpi<=0 + elo<=30 + edge<-0.05)
to find filterable patterns that reduce max drawdown without destroying ROI.

Usage:
    python scripts/loss_streak_analysis.py
"""

import logging
import sys
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path for sibling script imports
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
logger = logging.getLogger(__name__)


def build_analysis_df():
    """Build clean analysis dataset (reuse from analyze_divergence)."""
    from scripts.analyze_divergence import build_analysis_df as _build
    return _build()


def extract_s3_bets(df: pd.DataFrame) -> pd.DataFrame:
    """Extract S3 strategy bets: away underdog ML with rpi+elo+edge filters."""
    target = "closing_decimal_odds_favorite"
    pred_cols = [c for c in df.columns if c.startswith("pred_M")]
    df = df.copy()
    df["pred_consensus"] = df[pred_cols].mean(axis=1)
    df["edge_consensus"] = df[target] - df["pred_consensus"]

    # Away underdog ML universe
    away_dog = df[df["fav_is_home"]].copy()

    # Derive missing columns
    away_dog["fav_won"] = away_dog["fav_margin"] > 0
    # Away dog = away team; fav_is_home=True means away is dog
    away_dog["dog_decimal"] = away_dog["away_decimal_odds"]

    # Deduplicate: games may appear in multiple walk-forward folds
    away_dog = away_dog.drop_duplicates(
        subset=["season", "date", "home_team", "away_team"], keep="first"
    )

    # S3 filters
    base = away_dog["edge_consensus"] < -0.05
    rpi_ok = away_dog["rpi_diff"] <= 0
    elo_ok = away_dog["elo_diff"] <= 30
    mask = base & rpi_ok & elo_ok

    s3 = away_dog[mask].sort_values("date").copy()

    # Compute bet outcomes
    s3["dog_won"] = ~s3["fav_won"]
    s3["pnl"] = np.where(s3["dog_won"], (s3["dog_decimal"] - 1) * 100, -100)
    s3["cum_pnl"] = s3["pnl"].cumsum()

    return s3


def compute_loss_streaks(df: pd.DataFrame) -> pd.DataFrame:
    """Add running loss streak tracking columns."""
    df = df.copy()
    won = df["dog_won"].values
    streaks = np.zeros(len(df), dtype=int)
    streak_ids = np.zeros(len(df), dtype=int)

    current_loss = 0
    current_id = 0
    for i in range(len(df)):
        if not won[i]:
            current_loss += 1
            if current_loss == 1:
                current_id += 1
        else:
            current_loss = 0
        streaks[i] = current_loss
        streak_ids[i] = current_id if current_loss > 0 else 0

    df["loss_streak_len"] = streaks
    df["loss_streak_id"] = streak_ids
    return df


def profile_streaks(df: pd.DataFrame, min_streak: int = 8) -> None:
    """Print detailed profile of long loss streaks."""
    losing = df[df["loss_streak_len"] >= 1].copy()
    streak_groups = losing.groupby("loss_streak_id")

    long_streaks = []
    for sid, grp in streak_groups:
        slen = grp["loss_streak_len"].max()
        if slen >= min_streak:
            long_streaks.append((sid, slen, grp))

    long_streaks.sort(key=lambda x: -x[1])

    print(f"\n{'='*80}")
    print(f"LONG LOSS STREAKS (>= {min_streak} games)")
    print(f"{'='*80}")

    for sid, slen, grp in long_streaks:
        dates = grp["date"]
        start = dates.min()
        end = dates.max()
        print(f"\n--- Streak #{sid}: {slen} losses ({start.date()} to {end.date()}) ---")

        # Feature profile
        cols_to_show = {
            "season": "Season",
            "dog_decimal": "Dog odds",
            "elo_diff": "Elo diff",
            "rpi_diff": "RPI diff",
            "wp_last6_away": "Away WP6",
            "wp_last3_away": "Away WP3",
            "streak_away": "Away streak",
            "away_sp_ra_short": "Away SP RA",
            "starter_fip_diff": "FIP diff",
            "bp_ip_3d_home": "Home BP 3d",
            "bullpen_fip_diff": "BP FIP diff",
            "games_played_min": "GP min",
        }
        available = {k: v for k, v in cols_to_show.items() if k in grp.columns}

        # Summary stats for this streak
        for col, label in available.items():
            vals = grp[col].dropna()
            if len(vals) > 0:
                print(f"  {label:<18} median={vals.median():7.2f}  mean={vals.mean():7.2f}  range=[{vals.min():.2f}, {vals.max():.2f}]")

        # Game-by-game
        show_cols = ["date", "away_team", "home_team", "dog_decimal", "elo_diff"]
        show_cols = [c for c in show_cols if c in grp.columns]
        print(f"\n  Games:")
        for _, row in grp[show_cols].iterrows():
            parts = [f"{row.get('date', '?').date() if hasattr(row.get('date', '?'), 'date') else row.get('date', '?')}"]
            parts.append(f"{row.get('away_team', '?'):>3}@{row.get('home_team', '?'):<3}")
            parts.append(f"odds={row.get('dog_decimal', 0):.2f}")
            parts.append(f"elo={row.get('elo_diff', 0):.0f}")
            print(f"    {' | '.join(parts)}")


def compare_with_all_s3(df_streak: pd.DataFrame, df_all: pd.DataFrame) -> None:
    """Compare feature distributions: streak games vs all S3 games."""
    compare_cols = [
        ("dog_decimal", "Dog odds"),
        ("elo_diff", "Elo diff"),
        ("rpi_diff", "RPI diff"),
        ("wp_last6_away", "Away WP L6"),
        ("wp_last3_away", "Away WP L3"),
        ("streak_away", "Away streak"),
        ("away_sp_ra_short", "Away SP RA"),
        ("starter_fip_diff", "Starter FIP diff"),
        ("bp_ip_3d_home", "Home BP IP 3d"),
        ("bullpen_fip_diff", "BP FIP diff"),
        ("games_played_min", "GP min"),
        ("edge_consensus", "Edge"),
    ]

    print(f"\n{'='*80}")
    print("FEATURE COMPARISON: Long loss streak games vs ALL S3 games")
    print(f"{'='*80}")
    print(f"{'Feature':<20} {'Streak med':>12} {'All med':>12} {'Delta':>10} {'Direction':>12}")
    print("-" * 70)

    for col, label in compare_cols:
        if col not in df_streak.columns or col not in df_all.columns:
            continue
        s_med = df_streak[col].median()
        a_med = df_all[col].median()
        if pd.isna(s_med) or pd.isna(a_med):
            continue
        delta = s_med - a_med
        direction = "WORSE" if (
            (col in ["elo_diff", "rpi_diff", "bp_ip_3d_home"] and delta < 0)
            or (col in ["dog_decimal"] and delta > 0)
            or (col in ["wp_last6_away", "wp_last3_away", "streak_away"] and delta < 0)
            or (col in ["away_sp_ra_short"] and delta > 0)
            or (col in ["starter_fip_diff", "bullpen_fip_diff"] and delta < 0)
            or (col in ["games_played_min"] and delta < 0)
        ) else ""
        print(f"  {label:<18} {s_med:12.3f} {a_med:12.3f} {delta:+10.3f} {direction:>12}")


def test_subfilters(s3: pd.DataFrame) -> pd.DataFrame:
    """Test sub-filter candidates on S3 bets."""
    n_total = len(s3)
    won = s3["dog_won"].values
    odds = s3["dog_decimal"].values
    pnl = s3["pnl"].values

    # Baseline metrics
    baseline = _compute_filter_metrics(s3, "S3 baseline (no filter)")

    # Define candidate filters
    candidates = {}

    # Form filters
    if "wp_last6_away" in s3.columns:
        for thresh in [0.35, 0.40, 0.45]:
            key = f"wp_last6_away >= {thresh}"
            candidates[key] = s3["wp_last6_away"] >= thresh

    if "wp_last3_away" in s3.columns:
        for thresh in [0.33, 0.50, 0.67]:
            key = f"wp_last3_away >= {thresh}"
            candidates[key] = s3["wp_last3_away"] >= thresh

    # Odds band
    for thresh in [2.20, 2.40, 2.60]:
        key = f"dog_decimal <= {thresh}"
        candidates[key] = s3["dog_decimal"] <= thresh

    # Pitcher quality
    if "away_sp_ra_short" in s3.columns:
        med = s3["away_sp_ra_short"].median()
        candidates[f"away_sp_ra <= median ({med:.2f})"] = s3["away_sp_ra_short"] <= med

    if "starter_fip_diff" in s3.columns:
        candidates["starter_fip_diff > 0"] = s3["starter_fip_diff"] > 0

    # Bullpen
    if "bp_ip_3d_home" in s3.columns:
        p75 = s3["bp_ip_3d_home"].quantile(0.75)
        med = s3["bp_ip_3d_home"].median()
        candidates[f"home_bp_3d >= p75 ({p75:.1f})"] = s3["bp_ip_3d_home"] >= p75
        candidates[f"home_bp_3d >= med ({med:.1f})"] = s3["bp_ip_3d_home"] >= med

    if "bullpen_fip_diff" in s3.columns:
        candidates["bullpen_fip_diff > 0"] = s3["bullpen_fip_diff"] > 0

    # Early season
    if "games_played_min" in s3.columns:
        candidates["games_played_min >= 30"] = s3["games_played_min"] >= 30

    # Elo tightening
    candidates["elo_diff <= 0"] = s3["elo_diff"] <= 0
    candidates["elo_diff <= 15"] = s3["elo_diff"] <= 15

    # Streak positive
    if "streak_away" in s3.columns:
        candidates["streak_away >= 0"] = s3["streak_away"] >= 0
        candidates["streak_away >= 1"] = s3["streak_away"] >= 1

    # Evaluate each
    results = [baseline]
    for name, mask in candidates.items():
        mask_clean = mask.fillna(False)
        if mask_clean.sum() < 20:
            continue
        m = _compute_filter_metrics(s3[mask_clean], name)
        results.append(m)

    results_df = pd.DataFrame(results)
    return results_df


def test_combo_filters(s3: pd.DataFrame, top_singles: list[str]) -> pd.DataFrame:
    """Test 2-way combinations of the best single filters."""
    # Rebuild filter masks
    filter_map = _build_filter_map(s3)
    available = [f for f in top_singles if f in filter_map]

    results = []
    for f1, f2 in combinations(available, 2):
        combo_mask = filter_map[f1] & filter_map[f2]
        combo_mask = combo_mask.fillna(False)
        if combo_mask.sum() < 20:
            continue
        name = f"{f1} + {f2}"
        m = _compute_filter_metrics(s3[combo_mask], name)
        results.append(m)

    return pd.DataFrame(results)


def _build_filter_map(s3: pd.DataFrame) -> dict:
    """Build name → boolean mask mapping for all filters."""
    fm = {}
    if "wp_last6_away" in s3.columns:
        fm["wp_last6_away >= 0.40"] = s3["wp_last6_away"] >= 0.40
    if "wp_last3_away" in s3.columns:
        fm["wp_last3_away >= 0.33"] = s3["wp_last3_away"] >= 0.33
    fm["dog_decimal <= 2.40"] = s3["dog_decimal"] <= 2.40
    fm["dog_decimal <= 2.60"] = s3["dog_decimal"] <= 2.60
    if "away_sp_ra_short" in s3.columns:
        med = s3["away_sp_ra_short"].median()
        fm[f"away_sp_ra <= median ({med:.2f})"] = s3["away_sp_ra_short"] <= med
    if "starter_fip_diff" in s3.columns:
        fm["starter_fip_diff > 0"] = s3["starter_fip_diff"] > 0
    if "bp_ip_3d_home" in s3.columns:
        med = s3["bp_ip_3d_home"].median()
        fm[f"home_bp_3d >= med ({med:.1f})"] = s3["bp_ip_3d_home"] >= med
    if "bullpen_fip_diff" in s3.columns:
        fm["bullpen_fip_diff > 0"] = s3["bullpen_fip_diff"] > 0
    if "games_played_min" in s3.columns:
        fm["games_played_min >= 30"] = s3["games_played_min"] >= 30
    fm["elo_diff <= 0"] = s3["elo_diff"] <= 0
    fm["elo_diff <= 15"] = s3["elo_diff"] <= 15
    if "streak_away" in s3.columns:
        fm["streak_away >= 0"] = s3["streak_away"] >= 0
    return fm


def _compute_filter_metrics(df: pd.DataFrame, name: str) -> dict:
    """Compute key metrics for a filtered subset."""
    n = len(df)
    if n == 0:
        return {"filter": name, "bets": 0}

    won = df["dog_won"].values.astype(float)
    odds = df["dog_decimal"].values
    pnl = np.where(won, (odds - 1) * 100, -100)

    wr = won.mean()
    roi = pnl.sum() / (n * 100) * 100
    avg_odds = odds.mean()

    # Max loss streak
    max_ls = _max_streak(won, target=0)

    # Max drawdown %
    cum_pnl = np.cumsum(pnl)
    bankroll = 10000 + cum_pnl
    peak = np.maximum.accumulate(bankroll)
    dd_pct = ((peak - bankroll) / peak * 100)
    max_dd = dd_pct.max()

    # Sharpe
    ev = pnl.mean()
    std = pnl.std(ddof=1) if n > 1 else 1
    sharpe_bet = ev / std if std > 0 else 0
    bps = n / df["season"].nunique() if df["season"].nunique() > 0 else n
    sharpe = sharpe_bet * np.sqrt(bps)

    # Kelly
    b = avg_odds - 1
    kelly = (wr * b - (1 - wr)) / b if b > 0 else 0
    kelly = max(0, kelly) / 2  # half Kelly

    # Per-fold consistency
    if "fold" in df.columns:
        fold_rois = []
        for f in df["fold"].unique():
            fb = df[df["fold"] == f]
            fn = len(fb)
            if fn < 5:
                continue
            fpnl = np.where(fb["dog_won"].values, (fb["dog_decimal"].values - 1) * 100, -100)
            fold_rois.append(fpnl.sum() / (fn * 100) * 100)
        n_folds_pos = sum(1 for r in fold_rois if r > 0)
        n_folds = len(fold_rois)
    else:
        n_folds_pos = 0
        n_folds = 0

    return {
        "filter": name,
        "bets": n,
        "wr": wr,
        "avg_odds": avg_odds,
        "roi": roi,
        "max_lstreak": max_ls,
        "max_dd_pct": max_dd,
        "sharpe": sharpe,
        "kelly_half": kelly,
        "folds_pos": f"{n_folds_pos}/{n_folds}" if n_folds > 0 else "—",
    }


def _max_streak(outcomes, target=0):
    """Max consecutive run of target value."""
    max_s = 0
    cur = 0
    for o in outcomes:
        if o == target:
            cur += 1
            max_s = max(max_s, cur)
        else:
            cur = 0
    return max_s


def print_results(results_df: pd.DataFrame, title: str) -> None:
    """Print formatted results table."""
    print(f"\n{'='*110}")
    print(title)
    print(f"{'='*110}")
    header = (
        f"{'Filter':<48} {'Bets':>5} {'WR':>6} {'Odds':>5} "
        f"{'ROI':>7} {'MaxL':>5} {'MaxDD%':>7} {'Sharpe':>7} {'K_half':>7} {'Folds+':>7}"
    )
    print(header)
    print("-" * 110)

    for _, row in results_df.iterrows():
        if row["bets"] == 0:
            continue
        print(
            f"  {row['filter']:<46} {row['bets']:5d} "
            f"{row['wr']*100:5.1f}% {row['avg_odds']:5.2f} "
            f"{row['roi']:+6.1f}% {row['max_lstreak']:5d} "
            f"{row['max_dd_pct']:6.1f}% {row['sharpe']:6.3f} "
            f"{row['kelly_half']*100:6.2f}% {row['folds_pos']:>7}"
        )


def main():
    print("Building analysis dataset...")
    df = build_analysis_df()
    print(f"Dataset: {len(df)} rows, {df['season'].nunique()} seasons")

    print("\nExtracting S3 bets...")
    s3 = extract_s3_bets(df)
    print(f"S3 bets: {len(s3)}")
    print(f"Win rate: {s3['dog_won'].mean()*100:.1f}%")
    print(f"ROI: {s3['pnl'].sum() / (len(s3)*100)*100:+.1f}%")

    # Add loss streak tracking
    s3 = compute_loss_streaks(s3)

    # 1. Profile long streaks
    profile_streaks(s3, min_streak=8)

    # 2. Compare streak games vs all
    long_streak_games = s3[s3["loss_streak_len"] >= 8]
    if len(long_streak_games) > 0:
        compare_with_all_s3(long_streak_games, s3)

    # 3. Monthly/seasonal distribution of losses
    print(f"\n{'='*80}")
    print("LOSS DISTRIBUTION BY MONTH")
    print(f"{'='*80}")
    s3["month"] = pd.to_datetime(s3["date"]).dt.month
    month_stats = s3.groupby("month").agg(
        bets=("dog_won", "count"),
        wins=("dog_won", "sum"),
    )
    month_stats["wr"] = month_stats["wins"] / month_stats["bets"] * 100
    month_stats["losses"] = month_stats["bets"] - month_stats["wins"]
    for m, row in month_stats.iterrows():
        bar = "#" * int(row["wr"] / 2)
        print(f"  Month {m:2d}: {row['bets']:4.0f} bets, WR {row['wr']:5.1f}% {bar}")

    # 4. Test single sub-filters
    print("\n\nTesting sub-filters on S3 bets...")
    results = test_subfilters(s3)
    results = results.sort_values("roi", ascending=False)
    print_results(results, "SINGLE SUB-FILTER IMPACT ON S3")

    # 5. Pick top filters (ROI > baseline and max_lstreak < baseline)
    baseline_ls = results.iloc[0]["max_lstreak"] if len(results) > 0 else 99
    baseline_roi = results.iloc[0]["roi"] if len(results) > 0 else 0
    good_singles = results[
        (results["filter"] != "S3 baseline (no filter)")
        & (results["roi"] > 0)
        & (results["max_lstreak"] < baseline_ls)
    ]

    if len(good_singles) >= 2:
        top_names = good_singles["filter"].head(8).tolist()
        print(f"\n\nTesting 2-way combinations of top {len(top_names)} filters...")
        combos = test_combo_filters(s3, top_names)
        if len(combos) > 0:
            combos = combos.sort_values("roi", ascending=False)
            print_results(combos, "2-WAY COMBO FILTER IMPACT ON S3")

    # 6. Summary recommendation
    print(f"\n{'='*80}")
    print("RECOMMENDATION")
    print(f"{'='*80}")
    # Find best filter that has: ROI > 5%, max_lstreak < baseline, bets > 100
    all_results = pd.concat([results, combos if 'combos' in dir() and len(combos) > 0 else pd.DataFrame()])
    viable = all_results[
        (all_results["filter"] != "S3 baseline (no filter)")
        & (all_results["roi"] > 5)
        & (all_results["bets"] > 50)
    ].sort_values(["max_lstreak", "roi"], ascending=[True, False])

    if len(viable) > 0:
        best = viable.iloc[0]
        print(f"  Best S3+ candidate: {best['filter']}")
        print(f"  Bets: {best['bets']:.0f} | ROI: {best['roi']:+.1f}% | Max loss streak: {best['max_lstreak']:.0f} | Max DD: {best['max_dd_pct']:.1f}%")
        print(f"  vs baseline: Bets {results.iloc[0]['bets']:.0f} | ROI {results.iloc[0]['roi']:+.1f}% | MaxL {results.iloc[0]['max_lstreak']:.0f} | MaxDD {results.iloc[0]['max_dd_pct']:.1f}%")
    else:
        print("  No clear S3+ filter improves both streak length and ROI. Consider portfolio diversification with S1/S4 instead.")


if __name__ == "__main__":
    main()
