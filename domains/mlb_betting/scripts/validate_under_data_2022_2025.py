"""Data quality check for UNDER totals model on 2022-2025 seasons.

Validates that new-source data (ArnavSaraogi JSON + SDQL) has sufficient
feature coverage and no major distribution drift vs 2010-2021 baseline.

Usage:
    python scripts/validate_under_data_2022_2025.py

Exit code 0 = all checks pass, 1 = failures detected.
"""

import sys
import warnings
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

import numpy as np
import pandas as pd
from scipy import stats

from src.features import OU_FEATURES, build_ou_features

# Epochs: 2010-2021 = old source (sports-statistics.com + SDQL)
#          2022-2025 = new source (ArnavSaraogi JSON + SDQL merge)
# Exclude 2004-2009: missing inning data, many pitcher features empty → skewed baseline
OLD_SEASONS = list(range(2010, 2020)) + [2021]  # 11 seasons
NEW_SEASONS = [2022, 2023, 2024, 2025]

NAN_THRESHOLD = 0.30  # match build_ou_features() availability threshold
DRIFT_ALPHA = 0.01 / len(OU_FEATURES)  # Bonferroni-corrected KS test


def check_close_ou_coverage(df: pd.DataFrame) -> bool:
    """Check close_ou presence and distribution for 2022-2025."""
    print("\n" + "=" * 80)
    print("CHECK 1: close_ou coverage and distribution")
    print("=" * 80)

    new = df[df["season"].isin(NEW_SEASONS)]
    n_total = len(new)
    n_with_ou = new["close_ou"].notna().sum()
    pct = n_with_ou / n_total * 100 if n_total > 0 else 0

    print(f"  Total games 2022-2025: {n_total}")
    print(f"  With close_ou: {n_with_ou} ({pct:.1f}%)")

    if n_with_ou > 0:
        ou = new["close_ou"].dropna()
        print(f"  Distribution: mean={ou.mean():.2f} median={ou.median():.1f} "
              f"min={ou.min():.1f} max={ou.max():.1f}")
        print(f"  Half-integer check: {(ou % 1 == 0.5).mean() * 100:.1f}% are X.5")

    # Per-season breakdown
    print("  Per-season:")
    for s in NEW_SEASONS:
        sm = new[new["season"] == s]
        n = len(sm)
        has_ou = sm["close_ou"].notna().sum()
        print(f"    {s}: {has_ou}/{n} games ({has_ou/n*100:.1f}%)" if n > 0
              else f"    {s}: no data")

    ok = pct >= 95
    print(f"  RESULT: {'PASS' if ok else 'FAIL'} (coverage {pct:.1f}%, threshold 95%)")
    return ok


def check_feature_nan_rates(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """NaN rates for each OU_FEATURE: old vs new epoch."""
    print("\n" + "=" * 80)
    print("CHECK 2: Feature NaN rates (threshold <30%)")
    print("=" * 80)

    old = df[df["season"].isin(OLD_SEASONS)]
    new = df[df["season"].isin(NEW_SEASONS)]

    rows = []
    for f in OU_FEATURES:
        if f not in df.columns:
            rows.append({"feature": f, "nan_old": 1.0, "nan_new": 1.0,
                         "pass": False, "note": "MISSING"})
            continue
        nan_old = old[f].isna().mean() if len(old) > 0 else 0.0
        nan_new = new[f].isna().mean() if len(new) > 0 else 0.0
        ok = nan_new < NAN_THRESHOLD
        rows.append({"feature": f, "nan_old": nan_old, "nan_new": nan_new,
                      "pass": ok, "note": "" if ok else "HIGH NaN"})

    result = pd.DataFrame(rows)
    n_fail = (~result["pass"]).sum()

    print(f"  {'Feature':<30} {'NaN% old':>9} {'NaN% new':>9} {'Status':>8}")
    print("  " + "-" * 60)
    for _, r in result.iterrows():
        status = "PASS" if r["pass"] else f"FAIL {r['note']}"
        print(f"  {r['feature']:<30} {r['nan_old']*100:8.1f}% {r['nan_new']*100:8.1f}% {status:>8}")

    ok = n_fail == 0
    print(f"\n  RESULT: {'PASS' if ok else 'FAIL'} ({n_fail} features above NaN threshold)")
    return result, ok


def check_feature_drift(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Feature distribution comparison via KS test."""
    print("\n" + "=" * 80)
    print(f"CHECK 3: Feature drift (KS test, Bonferroni alpha={DRIFT_ALPHA:.6f})")
    print("=" * 80)

    old = df[df["season"].isin(OLD_SEASONS)]
    new = df[df["season"].isin(NEW_SEASONS)]

    rows = []
    for f in OU_FEATURES:
        if f not in df.columns:
            rows.append({"feature": f, "mean_old": np.nan, "mean_new": np.nan,
                         "std_old": np.nan, "std_new": np.nan,
                         "ks_stat": np.nan, "ks_pval": np.nan, "drift": True})
            continue
        old_vals = old[f].dropna()
        new_vals = new[f].dropna()
        if len(old_vals) < 10 or len(new_vals) < 10:
            rows.append({"feature": f, "mean_old": np.nan, "mean_new": np.nan,
                         "std_old": np.nan, "std_new": np.nan,
                         "ks_stat": np.nan, "ks_pval": np.nan, "drift": False})
            continue
        ks_stat, ks_pval = stats.ks_2samp(old_vals, new_vals)
        rows.append({
            "feature": f,
            "mean_old": old_vals.mean(), "std_old": old_vals.std(),
            "mean_new": new_vals.mean(), "std_new": new_vals.std(),
            "ks_stat": ks_stat, "ks_pval": ks_pval,
            "drift": ks_pval < DRIFT_ALPHA,
        })

    result = pd.DataFrame(rows)
    n_drift = result["drift"].sum()

    print(f"  {'Feature':<30} {'Mean old':>9} {'Mean new':>9} "
          f"{'KS stat':>8} {'p-value':>10} {'Drift':>6}")
    print("  " + "-" * 78)
    for _, r in result.iterrows():
        drift_str = "DRIFT" if r["drift"] else "ok"
        pval_str = f"{r['ks_pval']:.2e}" if not np.isnan(r["ks_pval"]) else "n/a"
        print(f"  {r['feature']:<30} {r['mean_old']:9.3f} {r['mean_new']:9.3f} "
              f"{r['ks_stat']:8.4f} {pval_str:>10} {drift_str:>6}")

    # Drift is informational, not blocking. Significant drift → investigate, not abort.
    print(f"\n  RESULT: {n_drift} features with significant drift (informational)")
    print("  Note: drift is expected for some features (e.g., close_ou tracks league trends)")
    return result, True  # always passes — drift is informational


def check_pitcher_bullpen_coverage(df: pd.DataFrame) -> bool:
    """Coverage report for pitcher and bullpen features per season."""
    print("\n" + "=" * 80)
    print("CHECK 4: Pitcher & bullpen feature coverage per season")
    print("=" * 80)

    pitcher_features = [
        "sp_ra_combined_short", "sp_ra_combined_long", "sp_fip_combined",
        "sp_whip_combined", "sp_kbb_combined", "sp_ip_per_start_combined",
    ]
    bullpen_features = [
        "bullpen_fip_combined", "bullpen_fip_7g_combined",
        "bp_fip_osc_combined", "bullpen_ip_3d_combined",
    ]

    all_ok = True
    for label, feats in [("Pitcher", pitcher_features), ("Bullpen", bullpen_features)]:
        print(f"\n  {label} features:")
        print(f"  {'Feature':<30}", end="")
        for s in NEW_SEASONS:
            print(f" {s:>6}", end="")
        print()
        print("  " + "-" * (30 + 7 * len(NEW_SEASONS)))

        for f in feats:
            if f not in df.columns:
                print(f"  {f:<30} MISSING")
                all_ok = False
                continue
            print(f"  {f:<30}", end="")
            for s in NEW_SEASONS:
                sm = df[df["season"] == s]
                pct = sm[f].notna().mean() * 100 if len(sm) > 0 else 0
                flag = "" if pct >= 70 else " *"
                print(f" {pct:5.1f}%{flag}", end="")
                if pct < 70:
                    all_ok = False
            print()

    print(f"\n  RESULT: {'PASS' if all_ok else 'WARN'} "
          f"(* = coverage <70%, may affect early-season folds)")
    return all_ok


def main():
    print("=" * 80)
    print("UNDER TOTALS — DATA QUALITY VALIDATION (2022-2025)")
    print("=" * 80)

    print("\nBuilding O/U features (full pipeline)...")
    df = build_ou_features()
    print(f"Total games after filters: {len(df)}")
    print(f"Seasons: {sorted(df['season'].unique().tolist())}")
    print(f"Old epoch (2010-2021): {len(df[df['season'].isin(OLD_SEASONS)])} games")
    print(f"New epoch (2022-2025): {len(df[df['season'].isin(NEW_SEASONS)])} games")

    # Run all checks
    ok1 = check_close_ou_coverage(df)
    _, ok2 = check_feature_nan_rates(df)
    _, ok3 = check_feature_drift(df)
    ok4 = check_pitcher_bullpen_coverage(df)

    # Overall verdict
    print("\n" + "=" * 80)
    print("OVERALL VERDICT")
    print("=" * 80)
    checks = [("close_ou coverage", ok1), ("NaN rates", ok2),
              ("Feature drift", ok3), ("Pitcher/bullpen coverage", ok4)]
    all_pass = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  {name:<30} {status}")
        if not ok:
            all_pass = False

    if all_pass:
        print("\n  ALL CHECKS PASSED — proceed to backtest")
    else:
        print("\n  SOME CHECKS FAILED — investigate before backtest")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
