"""Extended analysis of UNDER Gate v2 checkpoint — 15 second-order signals.

Post-hoc analysis only, no LLM calls. Reads:
  picks/_under_gate_experiment_v2.json
  picks/_under_gate_experiment.json (for DA verdicts)

Usage:
    python scripts/analyze_under_gate_v2.py
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PICKS = ROOT / "picks"
V2 = PICKS / "_under_gate_experiment_v2.json"
V1 = PICKS / "_under_gate_experiment.json"

ODDS_UNDER = 1.909
BREAKEVEN = 100 / ODDS_UNDER  # 52.38%
LG_AVG = 8.87  # combined RPG, 2021-2025


def load() -> pd.DataFrame:
    v2 = json.loads(V2.read_text())
    df = pd.DataFrame(v2["results"])
    da = {r["game_key"]: r for r in json.loads(V1.read_text())["results"]}
    df["da_action"] = df["game_key"].map(lambda k: da.get(k, {}).get("da_action", "N/A"))
    df["da_conf"] = df["game_key"].map(lambda k: da.get(k, {}).get("da_conf", 0.0))
    # Derived signals
    df["gap_to_line"] = df["ou_line"] - df["scorer_total"]
    df["gap_to_lg"] = LG_AVG - df["scorer_total"]
    df["line_vs_lg"] = df["ou_line"] - LG_AVG
    df["ceil"] = df["scorer_total"] + df["scorer_delta"]
    df["ceil_gap"] = df["ou_line"] - df["ceil"]
    return df


def roi(sub: pd.DataFrame) -> tuple[int, float, float]:
    n = len(sub)
    if n == 0:
        return 0, 0.0, 0.0
    hit = sub["under_hit"].mean() * 100
    pnl = np.where(sub["under_hit"].astype(bool), ODDS_UNDER - 1, -1).mean() * 100
    return n, hit, pnl


def row(label: str, sub: pd.DataFrame, min_n: int = 5) -> str:
    n, hit, r = roi(sub)
    if n < min_n:
        return f"  {label:<42} {n:>4}   (too few)"
    mark = " <--" if hit > BREAKEVEN else ""
    return f"  {label:<42} {n:>4} {hit:>6.1f}% {r:>+7.1f}%{mark}"


def section(title: str):
    print(f"\n{'=' * 90}\n{title}\n{'=' * 90}")


def sig_2_gap_to_lg(df):
    section("SIGNAL 2: gap_to_lg_avg (8.87 - predicted_total) -- UNDER when LLM sees low env")
    for t in [-0.5, 0.0, 0.3, 0.5, 1.0, 1.5, 2.0]:
        print(row(f"gap_to_lg >= {t:+.1f}", df[df["gap_to_lg"] >= t]))


def sig_3_line_vs_lg(df):
    section("SIGNAL 3: line_vs_lg (market only) -- baseline, NO LLM")
    for t in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        print(row(f"line_vs_lg >= {t:+.1f}", df[df["line_vs_lg"] >= t]))
    for t in [-0.5, 0.0, 0.5, 1.0]:
        print(row(f"line_vs_lg <= {t:+.1f} (low-total mkts)", df[df["line_vs_lg"] <= t]))


def sig_5_6_agreement(df):
    section("SIGNAL 5-6: AGREEMENT between LLM (gap_to_line) and LG deviation (gap_to_lg)")
    both_u = df[(df["gap_to_line"] > 0) & (df["gap_to_lg"] > 0)]
    both_o = df[(df["gap_to_line"] < 0) & (df["gap_to_lg"] < 0)]
    disagree_llm_under = df[(df["gap_to_line"] > 0) & (df["gap_to_lg"] < 0)]  # line high, lg low
    disagree_llm_over = df[(df["gap_to_line"] < 0) & (df["gap_to_lg"] > 0)]
    print(row("BOTH say UNDER (gap_line>0 & gap_lg>0)", both_u))
    print(row("BOTH say OVER", both_o))
    print(row("LLM under, LG over (line inflated)", disagree_llm_under))
    print(row("LLM over, LG under", disagree_llm_over))
    # strong agreement tiers
    for t_line, t_lg in [(0.5, 0.0), (0.5, 0.3), (1.0, 0.0), (1.0, 0.5), (1.5, 0.5)]:
        sub = df[(df["gap_to_line"] >= t_line) & (df["gap_to_lg"] >= t_lg)]
        print(row(f"gap_line>={t_line} & gap_lg>={t_lg}", sub))


def sig_7_8_9_calibration(df):
    section("SIGNAL 7-9: CALIBRATION -- does predicted_total track reality?")
    # Correlation
    corr = df[["scorer_total", "total_runs"]].corr().iloc[0, 1]
    # Residuals
    resid = df["total_runs"] - df["scorer_total"]
    naive_resid = df["total_runs"] - LG_AVG
    print(f"  Correlation(pred, actual):        {corr:+.3f}")
    print(f"  MAE(pred)  = {resid.abs().mean():.3f}   MAE(naive 8.87) = {naive_resid.abs().mean():.3f}")
    print(f"  RMSE(pred) = {(resid**2).mean()**0.5:.3f}   RMSE(naive)     = {(naive_resid**2).mean()**0.5:.3f}")
    # Calibration by predicted bucket
    print("\n  Predicted bucket calibration:")
    print(f"  {'bucket':<14} {'N':>4} {'mean_pred':>10} {'mean_actual':>12} {'under%':>8}")
    for lo, hi in [(0, 7.5), (7.5, 8.0), (8.0, 8.5), (8.5, 9.0), (9.0, 9.5), (9.5, 15)]:
        sub = df[(df["scorer_total"] >= lo) & (df["scorer_total"] < hi)]
        if len(sub) < 5:
            continue
        print(f"  [{lo:4.1f}-{hi:4.1f})  {len(sub):>4} {sub['scorer_total'].mean():>10.2f} "
              f"{sub['total_runs'].mean():>12.2f} {sub['under_hit'].mean()*100:>7.1f}%")


def sig_10_p_under_combo(df):
    section("SIGNAL 10: LLM on top of CatBoost p_under (already in [0.52, 0.53))")
    # All in zone; split by gap
    print(row("p_under in zone (all)", df))
    for t in [0.5, 1.0, 1.5, 2.0]:
        print(row(f"zone + gap_to_line >= {t:.1f}", df[df["gap_to_line"] >= t]))
    # p_under sub-slices within zone
    for lo, hi in [(0.520, 0.524), (0.524, 0.527), (0.527, 0.530)]:
        sub = df[(df["p_under"] >= lo) & (df["p_under"] < hi)]
        print(row(f"p_under [{lo:.3f}-{hi:.3f})", sub))


def sig_12_delta_confidence(df):
    section("SIGNAL 12: probable_delta as CONFIDENCE -- tight delta = LLM sure")
    for thr in [1.5, 1.8, 2.0, 2.2, 2.5]:
        sub = df[df["scorer_delta"] <= thr]
        print(row(f"delta <= {thr}", sub))
    # delta + gap combo
    print("\n  Combo: gap + delta")
    for gap_t in [0.5, 1.0, 1.5]:
        for d_t in [1.8, 2.0, 2.2]:
            sub = df[(df["gap_to_line"] >= gap_t) & (df["scorer_delta"] <= d_t)]
            print(row(f"gap>={gap_t} & delta<={d_t}", sub))


def sig_13_per_season(df):
    section("SIGNAL 13: PER-SEASON regime check")
    print(f"  {'season':<8} {'N':>4} {'under%':>8} {'ROI':>8}  |  {'gap>=1 N':>9} {'under%':>8} {'ROI':>8}")
    for s in sorted(df["season"].unique()):
        ss = df[df["season"] == s]
        sg = ss[ss["gap_to_line"] >= 1.0]
        n_a, h_a, r_a = roi(ss)
        n_g, h_g, r_g = roi(sg)
        print(f"  {int(s):<8} {n_a:>4} {h_a:>7.1f}% {r_a:>+7.1f}%  |  {n_g:>9} {h_g:>7.1f}% {r_g:>+7.1f}%")


def sig_14_line_bucket(df):
    section("SIGNAL 14: BY O/U LINE bucket (market concentration of mispricing)")
    print(f"  {'line':<12} {'N':>4} {'under%':>8} {'ROI':>8}  |  gap>=1.0 cell")
    for lo, hi in [(6.5, 7.5), (7.5, 8.0), (8.0, 8.5), (8.5, 9.0), (9.0, 9.5), (9.5, 10.5), (10.5, 15)]:
        sub = df[(df["ou_line"] >= lo) & (df["ou_line"] < hi)]
        sg = sub[sub["gap_to_line"] >= 1.0]
        n_a, h_a, r_a = roi(sub)
        n_g, h_g, r_g = roi(sg)
        sg_str = f"{n_g:>3d}/{h_g:.0f}%/{r_g:+.0f}%" if n_g >= 10 else f"{n_g:>3d}/--"
        print(f"  [{lo:4.1f}-{hi:4.1f})  {n_a:>4} {h_a:>7.1f}% {r_a:>+7.1f}%  |  {sg_str}")


def sig_15_month(df):
    section("SIGNAL 15: BY MONTH")
    df = df.copy()
    df["month"] = pd.to_datetime(df["date"]).dt.month
    print(f"  {'month':<6} {'N':>4} {'under%':>8} {'ROI':>8}  |  gap>=1.0")
    for m in sorted(df["month"].unique()):
        sub = df[df["month"] == m]
        sg = sub[sub["gap_to_line"] >= 1.0]
        n_a, h_a, r_a = roi(sub)
        n_g, h_g, r_g = roi(sg)
        sg_str = f"{n_g:>3d}/{h_g:.0f}%/{r_g:+.0f}%" if n_g >= 5 else f"{n_g:>3d}/--"
        print(f"  {int(m):<6} {n_a:>4} {h_a:>7.1f}% {r_a:>+7.1f}%  |  {sg_str}")


def sig_train_holdout(df):
    section("TRAIN (2021-2023) vs HOLDOUT (2024-2025)")
    tr = df[df["season"].isin([2021, 2022, 2023])]
    ho = df[df["season"].isin([2024, 2025])]
    print(f"  {'strategy':<38} {'TRAIN N/hit/ROI':<24} {'HOLDOUT N/hit/ROI':<24}")
    strats = [
        ("gap_to_line >= 2.0", lambda d: d[d["gap_to_line"] >= 2.0]),
        ("gap_to_line >= 1.5", lambda d: d[d["gap_to_line"] >= 1.5]),
        ("gap_to_line >= 1.0", lambda d: d[d["gap_to_line"] >= 1.0]),
        ("ceil_gap >= 0.5", lambda d: d[d["ceil_gap"] >= 0.5]),
        ("DA=UNDER + gap>=0.5", lambda d: d[(d["da_action"] == "UNDER") & (d["gap_to_line"] >= 0.5)]),
        ("gap_line>=1 & gap_lg>=0.5", lambda d: d[(d["gap_to_line"] >= 1.0) & (d["gap_to_lg"] >= 0.5)]),
        ("gap_line>=0.5 & delta<=1.8", lambda d: d[(d["gap_to_line"] >= 0.5) & (d["scorer_delta"] <= 1.8)]),
    ]
    for label, fn in strats:
        t_n, t_h, t_r = roi(fn(tr))
        h_n, h_h, h_r = roi(fn(ho))
        t_str = f"{t_n:>3}/{t_h:>5.1f}%/{t_r:>+6.1f}%" if t_n >= 5 else f"{t_n:>3}/--"
        h_str = f"{h_n:>3}/{h_h:>5.1f}%/{h_r:>+6.1f}%" if h_n >= 5 else f"{h_n:>3}/--"
        print(f"  {label:<38} {t_str:<24} {h_str:<24}")


def main():
    df = load()
    n = len(df)
    print(f"Loaded {n} games | base under% = {df['under_hit'].mean()*100:.1f}% | breakeven = {BREAKEVEN:.2f}%")
    print(f"LG_AVG = {LG_AVG} | pred mean = {df['scorer_total'].mean():.2f} | "
          f"line mean = {df['ou_line'].mean():.2f}")

    sig_2_gap_to_lg(df)
    sig_3_line_vs_lg(df)
    sig_5_6_agreement(df)
    sig_7_8_9_calibration(df)
    sig_10_p_under_combo(df)
    sig_12_delta_confidence(df)
    sig_13_per_season(df)
    sig_14_line_bucket(df)
    sig_15_month(df)
    sig_train_holdout(df)


if __name__ == "__main__":
    main()
