"""Per-season breakdown of OVER candidate:
rpg_vs_line >= 2.0  &  bullpen_fip_7g_combined >= 7.5  &  sp_fip_floor_short >= 4.5

Wide variant (N~298 total). Shows:
- Per-season N / over% / ROI / 10%-trim
- Cumulative P&L
- Sub-breakdowns: month, line bucket, era
- Outlier stress total
"""

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

ODDS = 1.909
BREAKEVEN = 100 / ODDS

# ---- Filter definition (wide variant) ----
LABEL = "rpg_vs_line >= 2.0  &  bullpen_fip_7g_combined >= 7.5  &  sp_fip_floor_short >= 4.5"


def stats(sub: pd.DataFrame):
    sub = sub[~sub["is_push"]]
    n = len(sub)
    if n == 0:
        return 0, 0.0, 0.0
    h = float(sub["over_hit"].mean() * 100)
    r = float(np.where(sub["over_hit"].astype(bool), ODDS - 1, -1).mean() * 100)
    return n, h, r


def trim10(sub: pd.DataFrame):
    s = sub.sort_values("total_runs", ascending=True)
    k = int(len(s) * 0.10)
    return stats(s.iloc[: len(s) - k])


def build_df():
    logger.info("Loading seasons...")
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
    for train_s, val_s, test_s in folds:
        cb, lr, cal, metrics = train_under_model(ou, feats, train_s, val_s, cfg=cfg)
        test_mask = ou["season"].isin(test_s) & ~push_mask
        if test_mask.sum() < 10:
            continue
        X_test = ou.loc[test_mask, feats].values.astype(float)
        p_under = predict_under_proba(X_test, cb, lr, cal, metrics["train_medians"], cfg=cfg)
        meta = [c for c in ["season", "date", "home_team", "away_team", "close_ou",
                             "total_runs", "over_hit", "is_push"] if c in ou.columns]
        pdf = ou.loc[test_mask, meta].copy()
        pdf["p_under"] = p_under
        all_preds.append(pdf)

    preds = pd.concat(all_preds, ignore_index=True)
    logger.info(f"Predictions: {len(preds)}")

    # Feature columns to join (exclude duplicates with prediction keys)
    join_keys = {"season", "date", "home_team", "away_team"}
    pred_cols = set(preds.columns)
    extra_cols = [c for c in ou.columns if c not in pred_cols and c not in
                  {"under_hit", "ou_regime", "ou_regime_v3"}]
    ou_join = ou[list(join_keys) + extra_cols].drop_duplicates(subset=list(join_keys))
    df = preds.merge(ou_join, on=list(join_keys), how="left")
    logger.info(f"After join: {df.shape[1]} columns")

    df["month"] = pd.to_datetime(df["date"]).dt.month

    # Ensure derived features exist
    for c in ["home_sp_fip_short", "away_sp_fip_short"]:
        if c not in df.columns:
            df[c] = np.nan
    if "sp_fip_floor_short" not in df.columns:
        df["sp_fip_floor_short"] = df[["home_sp_fip_short", "away_sp_fip_short"]].max(
            axis=1,
            skipna=False,
        )
    if "rpg_vs_line" not in df.columns:
        df["rpg_vs_line"] = df.get("combined_rpg", pd.Series(np.nan, index=df.index)) - df["close_ou"]

    return df


def main():
    df = build_df()

    # Apply filter
    mask = (
        (df["rpg_vs_line"] >= 2.0) &
        (df["bullpen_fip_7g_combined"] >= 7.5) &
        (df["sp_fip_floor_short"] >= 4.5) &
        ~df["is_push"]
    )
    sub = df[mask].copy()
    n_all, h_all, r_all = stats(sub)

    print(f"\n{'='*80}")
    print(f"CANDIDATE: {LABEL}")
    print(f"{'='*80}")
    print(f"Total: N={n_all}  over%={h_all:.1f}%  ROI={r_all:+.1f}%  breakeven={BREAKEVEN:.2f}%")

    # Overall outlier stress
    print(f"\nOutlier stress (all seasons):")
    print(f"  {'trim':<8} {'N':>5} {'over%':>7} {'ROI':>8}")
    for pct in [0, 5, 10, 15, 20]:
        s2 = sub.sort_values("total_runs", ascending=True)
        k = int(len(s2) * pct / 100)
        keep = s2.iloc[: len(s2) - k]
        n, h, r = stats(keep)
        flag = " SURVIVES" if pct == 10 and h >= 52.0 else (" COLLAPSES" if pct == 10 and h < 50.0 else "")
        print(f"  {pct:>3}%     {n:>5} {h:>6.1f}% {r:>+7.1f}%{flag}")

    # Per-season table
    print(f"\n{'='*80}")
    print(f"PER-SEASON BREAKDOWN")
    print(f"{'='*80}")
    print(f"  {'season':<8} {'N':>4} {'over%':>7} {'ROI':>8}  10%-trim  cumul-P&L")
    print("  " + "-" * 58)

    cumulative = 0.0
    yearly = []
    for s in sorted(sub["season"].unique()):
        ss = sub[sub["season"] == s]
        n, h, r = stats(ss)
        _, h10, _ = trim10(ss)
        pnl = np.where(ss["over_hit"].astype(bool), ODDS - 1, -1).sum()
        cumulative += pnl
        flag = " <<" if h >= BREAKEVEN else ("  -" if h >= 50.0 else " xx")
        print(f"  {int(s):<8} {n:>4} {h:>6.1f}% {r:>+7.1f}%  {h10:>5.1f}%   {cumulative:>+7.1f}u{flag}")
        yearly.append((s, n, h, r, h10, pnl))

    # Count profitable seasons
    prof = sum(1 for _, n, h, r, _, _ in yearly if h >= BREAKEVEN and n >= 5)
    total_s = sum(1 for _, n, h, r, _, _ in yearly if n >= 5)
    print(f"\n  Profitable seasons: {prof}/{total_s}  "
          f"(>= {BREAKEVEN:.1f}% over hit rate, N >= 5)")

    # Era comparison
    print(f"\n{'='*80}")
    print(f"ERA COMPARISON")
    print(f"{'='*80}")
    pre = sub[sub["season"] <= 2019]
    mod = sub[sub["season"] >= 2021]
    np_, hp, rp = stats(pre)
    nm, hm, rm = stats(mod)
    _, hp10, _ = trim10(pre)
    _, hm10, _ = trim10(mod)
    print(f"  pre-2021 (2010-2019): N={np_:>4}  over%={hp:.1f}%  ROI={rp:+.1f}%  10%-trim={hp10:.1f}%")
    print(f"  modern (2021-2025):   N={nm:>4}  over%={hm:.1f}%  ROI={rm:+.1f}%  10%-trim={hm10:.1f}%")
    delta = hm - hp
    print(f"  Era delta: {delta:+.1f}pp  "
          f"({'holds in modern era' if abs(delta) < 5 else 'DEGRADED' if delta < -5 else 'STRONGER in modern'})")

    # Sub-breakdowns
    print(f"\n{'='*80}")
    print(f"SUB-BREAKDOWNS")
    print(f"{'='*80}")

    # By month
    print(f"\n  By month:")
    print(f"  {'month':<8} {'N':>4} {'over%':>7} {'ROI':>8}")
    for m in range(3, 11):
        sm = sub[sub["month"] == m]
        n, h, r = stats(sm)
        if n >= 5:
            flag = " *" if h >= BREAKEVEN else ""
            print(f"  {m:<8} {n:>4} {h:>6.1f}% {r:>+7.1f}%{flag}")

    # By line bucket
    print(f"\n  By O/U line bucket:")
    print(f"  {'line':<12} {'N':>4} {'over%':>7} {'ROI':>8}")
    for lo, hi in [(6.5, 7.5), (7.5, 8.0), (8.0, 8.5), (8.5, 9.0), (9.0, 10.0), (10.0, 15)]:
        sl = sub[(sub["close_ou"] >= lo) & (sub["close_ou"] < hi)]
        n, h, r = stats(sl)
        if n >= 5:
            flag = " *" if h >= BREAKEVEN else ""
            print(f"  [{lo:.1f}-{hi:.1f})  {n:>4} {h:>6.1f}% {r:>+7.1f}%{flag}")

    # By rpg_vs_line strength
    print(f"\n  By rpg_vs_line (how much teams outperform the line):")
    print(f"  {'rpg_vs_line':<14} {'N':>4} {'over%':>7} {'ROI':>8}")
    for lo, hi in [(2.0, 2.5), (2.5, 3.0), (3.0, 4.0), (4.0, 10.0)]:
        sr = sub[(sub["rpg_vs_line"] >= lo) & (sub["rpg_vs_line"] < hi)]
        n, h, r = stats(sr)
        if n >= 5:
            flag = " *" if h >= BREAKEVEN else ""
            print(f"  [{lo:.1f}-{hi:.1f})      {n:>4} {h:>6.1f}% {r:>+7.1f}%{flag}")

    # By bullpen FIP 7g strength
    print(f"\n  By bullpen_fip_7g_combined (how bad the bullpens are):")
    print(f"  {'fip_7g':<14} {'N':>4} {'over%':>7} {'ROI':>8}")
    for lo, hi in [(7.5, 8.0), (8.0, 8.5), (8.5, 9.0), (9.0, 10.0), (10.0, 20)]:
        sr = sub[(sub["bullpen_fip_7g_combined"] >= lo) & (sub["bullpen_fip_7g_combined"] < hi)]
        n, h, r = stats(sr)
        if n >= 5:
            flag = " *" if h >= BREAKEVEN else ""
            print(f"  [{lo:.1f}-{hi:.1f})      {n:>4} {h:>6.1f}% {r:>+7.1f}%{flag}")

    # Grey zone subset
    print(f"\n  Grey zone [0.47-0.52) subset:")
    gz = sub[(sub["p_under"] >= 0.47) & (sub["p_under"] < 0.52)]
    n, h, r = stats(gz)
    print(f"  N={n}  over%={h:.1f}%  ROI={r:+.1f}%")


if __name__ == "__main__":
    main()
