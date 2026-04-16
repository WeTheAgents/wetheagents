"""OVER-side post-hoc analysis of UNDER Gate v2 checkpoint.

Mirror of analyze_under_gate_v2.py, OVER perspective. Inverts all 15 signals.
Adds outlier-stress test to check operator's hypothesis: "OVER = 1-2 lucky outlier innings".

Usage:
    python scripts/analyze_over_gate_v2.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PICKS = ROOT / "picks"
V2 = PICKS / "_under_gate_experiment_v2.json"
V1 = PICKS / "_under_gate_experiment.json"

ODDS = 1.909
BREAKEVEN = 100 / ODDS  # 52.38%
LG_AVG = 8.87


def load() -> pd.DataFrame:
    v2 = json.loads(V2.read_text())
    df = pd.DataFrame(v2["results"])
    da = {r["game_key"]: r for r in json.loads(V1.read_text())["results"]}
    df["da_action"] = df["game_key"].map(lambda k: da.get(k, {}).get("da_action", "N/A"))
    # Flip to OVER frame
    df["over_hit"] = 1 - df["under_hit"]
    # Signals (OVER-positive)
    df["gap_over_line"] = df["scorer_total"] - df["ou_line"]       # pred > line
    df["gap_over_lg"]   = df["scorer_total"] - LG_AVG              # pred > league avg
    df["line_below_lg"] = LG_AVG - df["ou_line"]                   # market low vs lg avg
    df["floor"]         = df["scorer_total"] - df["scorer_delta"]
    df["floor_gap"]     = df["floor"] - df["ou_line"]              # even lower bound above line
    return df


def roi(sub: pd.DataFrame) -> tuple[int, float, float]:
    n = len(sub)
    if n == 0:
        return 0, 0.0, 0.0
    hit = sub["over_hit"].mean() * 100
    pnl = np.where(sub["over_hit"].astype(bool), ODDS - 1, -1).mean() * 100
    return n, hit, pnl


def row(label: str, sub: pd.DataFrame, min_n: int = 5) -> str:
    n, h, r = roi(sub)
    if n < min_n:
        return f"  {label:<44} {n:>4}   (too few)"
    mark = " <--" if h > BREAKEVEN else ""
    return f"  {label:<44} {n:>4} {h:>6.1f}% {r:>+7.1f}%{mark}"


def section(title: str):
    print(f"\n{'=' * 92}\n{title}\n{'=' * 92}")


# -- individual signal blocks ---------------------------------------------


def sig_1_gap_over_line(df):
    section("SIGNAL 1: gap_over_line (pred - line) -- OVER when scorer sees more runs than market")
    for t in [-0.5, 0.0, 0.3, 0.5, 1.0, 1.5]:
        print(row(f"gap_over_line >= {t:+.1f}", df[df["gap_over_line"] >= t]))


def sig_2_gap_over_lg(df):
    section("SIGNAL 2: gap_over_lg (pred - 8.87) -- OVER when scorer sees above-average env")
    for t in [-0.5, 0.0, 0.3, 0.5, 1.0, 1.5]:
        print(row(f"gap_over_lg >= {t:+.1f}", df[df["gap_over_lg"] >= t]))


def sig_3_line_vs_lg(df):
    section("SIGNAL 3: line_below_lg (8.87 - line) -- pure market, NO LLM")
    for t in [-1.0, -0.5, 0.0, 0.3, 0.5, 1.0]:
        print(row(f"line_below_lg >= {t:+.1f}", df[df["line_below_lg"] >= t]))


def sig_4_floor(df):
    section("SIGNAL 4: CONSERVATIVE -- floor (pred - delta) > line")
    for t in [-2.0, -1.0, -0.5, 0.0, 0.5]:
        print(row(f"floor_gap >= {t:+.1f}", df[df["floor_gap"] >= t]))


def sig_5_6_agreement(df):
    section("SIGNAL 5-6: AGREEMENT between gap_over_line and gap_over_lg")
    print(row("BOTH say OVER (line>0 & lg>0)", df[(df["gap_over_line"] > 0) & (df["gap_over_lg"] > 0)]))
    print(row("BOTH say UNDER (line<0 & lg<0)", df[(df["gap_over_line"] < 0) & (df["gap_over_lg"] < 0)]))
    print(row("disagree: line>0 & lg<0 (line low, below lg)",
              df[(df["gap_over_line"] > 0) & (df["gap_over_lg"] < 0)]))
    print(row("disagree: line<0 & lg>0 (line high, above lg)",
              df[(df["gap_over_line"] < 0) & (df["gap_over_lg"] > 0)]))
    for t_line, t_lg in [(0.3, 0.0), (0.5, 0.0), (0.5, 0.3), (1.0, 0.5), (1.5, 0.5)]:
        sub = df[(df["gap_over_line"] >= t_line) & (df["gap_over_lg"] >= t_lg)]
        print(row(f"gap_line>={t_line} & gap_lg>={t_lg}", sub))


def sig_10_p_under(df):
    section("SIGNAL 10: p_under sub-buckets (lower p_u -> closer to OVER lean)")
    for lo, hi in [(0.520, 0.524), (0.524, 0.527), (0.527, 0.530)]:
        sub = df[(df["p_under"] >= lo) & (df["p_under"] < hi)]
        print(row(f"p_under [{lo:.3f}-{hi:.3f})", sub))


def sig_11_da(df):
    section("SIGNAL 11: DA combo (v1 verdicts)")
    print(row("DA=OVER (any)", df[df["da_action"] == "OVER"]))
    print(row("DA!=UNDER (OVER+PASS)", df[df["da_action"] != "UNDER"]))
    for t in [0.3, 0.5, 1.0]:
        print(row(f"DA=OVER & gap_line>={t}",
                  df[(df["da_action"] == "OVER") & (df["gap_over_line"] >= t)]))
    for t in [0.3, 0.5, 1.0]:
        print(row(f"DA!=UNDER & gap_line>={t}",
                  df[(df["da_action"] != "UNDER") & (df["gap_over_line"] >= t)]))


def sig_12_delta(df):
    section("SIGNAL 12: probable_delta as CONFIDENCE")
    for thr in [1.5, 1.8, 2.0, 2.2]:
        print(row(f"delta <= {thr}", df[df["scorer_delta"] <= thr]))
    print("\n  combo: gap_line + low delta")
    for g in [0.3, 0.5, 1.0]:
        for d in [1.8, 2.0, 2.2]:
            sub = df[(df["gap_over_line"] >= g) & (df["scorer_delta"] <= d)]
            print(row(f"gap>={g} & delta<={d}", sub))


def sig_13_season(df):
    section("SIGNAL 13: PER-SEASON")
    print(f"  {'season':<8} {'all N':>6} {'over%':>7} {'ROI':>8}  |  "
          f"{'gap>=0.3 N':>11} {'over%':>7} {'ROI':>8}")
    for s in sorted(df["season"].unique()):
        ss = df[df["season"] == s]
        sg = ss[ss["gap_over_line"] >= 0.3]
        n_a, h_a, r_a = roi(ss)
        n_g, h_g, r_g = roi(sg)
        sg_str = f"{n_g:>6} {h_g:>6.1f}% {r_g:>+7.1f}%" if n_g >= 5 else f"{n_g:>6}     --"
        print(f"  {int(s):<8} {n_a:>6} {h_a:>6.1f}% {r_a:>+7.1f}%  |  {sg_str}")


def sig_14_line_bucket(df):
    section("SIGNAL 14: BY O/U LINE bucket (low-total markets = prime OVER?)")
    print(f"  {'line':<12} {'N':>4} {'over%':>8} {'ROI':>8}")
    for lo, hi in [(6.5, 7.5), (7.5, 8.0), (8.0, 8.5), (8.5, 9.0),
                   (9.0, 9.5), (9.5, 10.5), (10.5, 15)]:
        sub = df[(df["ou_line"] >= lo) & (df["ou_line"] < hi)]
        print(row(f"line [{lo:.1f}-{hi:.1f})", sub))


def sig_15_month(df):
    section("SIGNAL 15: BY MONTH")
    d = df.copy()
    d["month"] = pd.to_datetime(d["date"]).dt.month
    for m in sorted(d["month"].unique()):
        sub = d[d["month"] == m]
        print(row(f"month {int(m):>2}", sub))


def train_holdout(df):
    section("TRAIN (2021-2023) vs HOLDOUT (2024-2025)")
    tr = df[df["season"].isin([2021, 2022, 2023])]
    ho = df[df["season"].isin([2024, 2025])]
    print(f"  {'strategy':<42} {'TRAIN':<24} {'HOLDOUT':<24}")
    strats = [
        ("ALL (baseline)", lambda d: d),
        ("gap_over_line >= 0.0", lambda d: d[d["gap_over_line"] >= 0.0]),
        ("gap_over_line >= 0.3", lambda d: d[d["gap_over_line"] >= 0.3]),
        ("gap_over_line >= 0.5", lambda d: d[d["gap_over_line"] >= 0.5]),
        ("gap_over_lg >= 0.3", lambda d: d[d["gap_over_lg"] >= 0.3]),
        ("line_below_lg >= 0.0", lambda d: d[d["line_below_lg"] >= 0.0]),
        ("line_below_lg >= 0.3", lambda d: d[d["line_below_lg"] >= 0.3]),
        ("floor_gap >= 0.0", lambda d: d[d["floor_gap"] >= 0.0]),
        ("DA=OVER (any)", lambda d: d[d["da_action"] == "OVER"]),
        ("DA!=UNDER", lambda d: d[d["da_action"] != "UNDER"]),
        ("gap_line>=0.3 & gap_lg>=0.3",
         lambda d: d[(d["gap_over_line"] >= 0.3) & (d["gap_over_lg"] >= 0.3)]),
        ("gap_line>=0.5 & delta<=2.0",
         lambda d: d[(d["gap_over_line"] >= 0.5) & (d["scorer_delta"] <= 2.0)]),
        ("low line (<=8.5) only",
         lambda d: d[d["ou_line"] <= 8.5]),
    ]
    for label, fn in strats:
        t_n, t_h, t_r = roi(fn(tr))
        h_n, h_h, h_r = roi(fn(ho))
        t_str = f"{t_n:>3}/{t_h:>5.1f}%/{t_r:>+6.1f}%" if t_n >= 5 else f"{t_n:>3}/--"
        h_str = f"{h_n:>3}/{h_h:>5.1f}%/{h_r:>+6.1f}%" if h_n >= 5 else f"{h_n:>3}/--"
        print(f"  {label:<42} {t_str:<24} {h_str:<24}")


def outlier_stress(df: pd.DataFrame, strats: list[tuple[str, pd.Series]]):
    """Drop top-scoring games and recheck edge. Operator's hypothesis:
    OVER edge is driven by 1-2 outlier innings -> edge collapses after trimming."""
    section("OUTLIER STRESS TEST -- drop top N% of total_runs, recompute")
    print(f"  (a structural OVER edge survives trimming; an outlier-driven edge collapses)")
    print(f"\n  {'strategy':<42} " + " ".join(f"{p:>3}%" for p in [0, 5, 10, 15, 20]))
    print("  " + "-" * 86)
    for label, mask in strats:
        sub = df[mask].copy()
        if len(sub) < 30:
            continue
        sub = sub.sort_values("total_runs", ascending=True)  # low first
        cells = []
        for pct in [0, 5, 10, 15, 20]:
            k = int(len(sub) * pct / 100)
            keep = sub.iloc[: len(sub) - k]  # drop top-k highest totals
            n, h, r = roi(keep)
            cells.append(f"{h:>4.1f}%/{r:>+4.0f}%")
        print(f"  {label:<42} " + " ".join(f"{c:>10}" for c in cells))


def calibration(df):
    section("CALIBRATION recap (same numbers as UNDER analysis, reported for symmetry)")
    corr = df[["scorer_total", "total_runs"]].corr().iloc[0, 1]
    resid = df["total_runs"] - df["scorer_total"]
    naive = df["total_runs"] - LG_AVG
    print(f"  Correlation(pred, actual): {corr:+.3f}")
    print(f"  MAE pred = {resid.abs().mean():.3f}    MAE naive(8.87) = {naive.abs().mean():.3f}")
    print(f"  mean(actual - pred) = {resid.mean():+.3f}  "
          f"(positive => LLM systematically underpredicts -> supports OVER)")
    print(f"  Over-hit rate in full sample: {df['over_hit'].mean()*100:.1f}%")


def main():
    df = load()
    print(f"Loaded {len(df)} games | base OVER% = {df['over_hit'].mean()*100:.1f}% "
          f"| breakeven = {BREAKEVEN:.2f}%")
    print(f"LG_AVG = {LG_AVG} | pred mean = {df['scorer_total'].mean():.2f} | "
          f"line mean = {df['ou_line'].mean():.2f} | actual mean = {df['total_runs'].mean():.2f}")

    calibration(df)
    sig_1_gap_over_line(df)
    sig_2_gap_over_lg(df)
    sig_3_line_vs_lg(df)
    sig_4_floor(df)
    sig_5_6_agreement(df)
    sig_10_p_under(df)
    sig_11_da(df)
    sig_12_delta(df)
    sig_13_season(df)
    sig_14_line_bucket(df)
    sig_15_month(df)
    train_holdout(df)

    # Outlier stress on the most promising filter families
    strats = [
        ("ALL", pd.Series(True, index=df.index)),
        ("gap_over_line >= 0.0", df["gap_over_line"] >= 0.0),
        ("gap_over_line >= 0.3", df["gap_over_line"] >= 0.3),
        ("gap_over_line >= 0.5", df["gap_over_line"] >= 0.5),
        ("line_below_lg >= 0.0", df["line_below_lg"] >= 0.0),
        ("low line (<=8.5)", df["ou_line"] <= 8.5),
        ("DA=OVER", df["da_action"] == "OVER"),
        ("DA!=UNDER", df["da_action"] != "UNDER"),
    ]
    outlier_stress(df, strats)


if __name__ == "__main__":
    main()
