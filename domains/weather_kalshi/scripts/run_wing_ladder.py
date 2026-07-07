"""Wing model ladder: can anything beat the market on cheap-wing exceedance?

Walk-forward evaluation over data/processed/exceedance_dataset.parquet.
Each rung must beat the previous one on Δlog-loss vs the market baseline
(positive Δ = better than market), on the HEADLINE set: fresh wing rows
(is_wing==1, stale==0) in weekly out-of-sample test blocks. Sequential
gatekeeping: rung k's result is confirmatory only if rung k-1 passed; later
rungs are still computed and reported as exploratory.

Rungs
  0. market_p_exceed itself (Δ ≡ 0 by construction — sanity anchor).
  1. NBM parametric exceedance + isotonic calibration (fit per fold on train).
  2. Offset logistic: GLM Binomial with offset = logit(market), features
     z, log_nbm_sigma, warming, nbm_gap. Learns a correction to the market.
  3. CatBoost with baseline = logit(market) carried on train/val/test Pools
     (predict on a plain ndarray would silently drop the offset). Monotone
     constraint on z chosen per fold on a validation tail of the train window.

Context (stage-3 finding): the market is better calibrated than NBM in every
zone, so the prior is that rung 1 fails and any edge must be conditional. CIs
are date-cluster bootstrapped (~45 fresh test dates -> wide); the go bar is a
confident, not borderline, positive Δ.

Outputs: reports/wing_ladder_report.html, data/processed/wing_ladder_meta.json,
data/processed/wing_ladder_preds.parquet (per-row per-rung test predictions).

Usage
-----
    uv run python -m scripts.run_wing_ladder --data-root <main-checkout>/data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.scoring import log_loss, reliability_table  # noqa: E402

TEST_START = "2026-05-15"
STALE_EXCLUDE = True
N_BOOT = 2000
SEED = 7
P_CLIP = (1e-4, 1 - 1e-4)
GLM_FEATURES = ["z", "log_nbm_sigma", "warming_f", "warming_miss", "nbm_gap"]
CB_FEATURES = ["slug", "z", "nbm_exceed_param", "nbm_exceed_emp", "nbm_gap",
               "log_nbm_sigma", "warming_f", "warming_miss", "month",
               "doy_sin", "doy_cos", "candle_age_h"]
VAL_TAIL_DAYS = 14  # last N train dates reserved for early stopping / variant pick
THRESHOLDS = [0.05, 0.08, 0.10]


def data_root(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("WEATHER_DATA_ROOT")
    if env:
        return Path(env)
    return ROOT / "data"


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), *P_CLIP)
    return np.log(p / (1.0 - p))


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.asarray(x, dtype=float)))


# ---------------------------------------------------------------------------
# Rung fitters: each takes (train_df, test_df) and returns test probabilities.
# ---------------------------------------------------------------------------

def rung1_nbm_isotonic(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    from sklearn.isotonic import IsotonicRegression
    iso = IsotonicRegression(y_min=P_CLIP[0], y_max=P_CLIP[1], out_of_bounds="clip")
    iso.fit(train["nbm_exceed_param"].values, train["y"].values)
    return np.clip(iso.predict(test["nbm_exceed_param"].values), *P_CLIP)


def rung2_offset_glm(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    import statsmodels.api as sm
    xtr = sm.add_constant(train[GLM_FEATURES].astype(float), has_constant="add")
    xte = sm.add_constant(test[GLM_FEATURES].astype(float), has_constant="add")
    try:
        model = sm.GLM(train["y"].values, xtr, family=sm.families.Binomial(),
                       offset=logit(train["market_p_exceed"].values))
        res = model.fit(maxiter=200)
        eta = res.predict(xte, offset=logit(test["market_p_exceed"].values), which="linear")
        return np.clip(sigmoid(eta), *P_CLIP)
    except Exception:
        # non-convergence -> zero correction, fall back to the market itself
        return np.clip(test["market_p_exceed"].values, *P_CLIP)


def rung3_catboost(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    from catboost import CatBoostClassifier, Pool

    cat_idx = [CB_FEATURES.index("slug"), CB_FEATURES.index("month")]
    dates = np.sort(train["target_date"].unique())
    val_dates = set(dates[-VAL_TAIL_DAYS:])
    tr = train[~train["target_date"].isin(val_dates)]
    va = train[train["target_date"].isin(val_dates)]
    if len(va) < 50 or len(tr) < 200:
        tr, va = train, train  # degenerate fold; no honest val -> no variant pick

    def mk_pool(df: pd.DataFrame) -> Pool:
        x = df[CB_FEATURES].copy()
        x["month"] = x["month"].astype(str)
        return Pool(x, label=df["y"].values, cat_features=cat_idx,
                    baseline=logit(df["market_p_exceed"].values))

    p_tr, p_va, p_te = mk_pool(tr), mk_pool(va), mk_pool(test)
    variants = {"none": None, "z_dec": {"z": -1}}
    best_name, best_ll, best_model = None, np.inf, None
    for name, mono in variants.items():
        params = dict(loss_function="Logloss", depth=3, learning_rate=0.05,
                      iterations=1500, early_stopping_rounds=100, verbose=False,
                      random_seed=SEED, allow_writing_files=False)
        if mono is not None:
            params["monotone_constraints"] = {CB_FEATURES.index(k): v for k, v in mono.items()}
        m = CatBoostClassifier(**params)
        m.fit(p_tr, eval_set=p_va)
        va_p = np.clip(sigmoid(m.predict(p_va, prediction_type="RawFormulaVal")), *P_CLIP)
        ll = float(log_loss(va["y"].values, va_p).mean())
        if ll < best_ll:
            best_name, best_ll, best_model = name, ll, m
    raw = best_model.predict(p_te, prediction_type="RawFormulaVal")
    rung3_catboost.last_variant = best_name  # surfaced in the report
    return np.clip(sigmoid(raw), *P_CLIP)


RUNGS = [
    ("r1_nbm_iso", rung1_nbm_isotonic),
    ("r2_offset_glm", rung2_offset_glm),
    ("r3_catboost", rung3_catboost),
]


# ---------------------------------------------------------------------------
# Bootstrap CIs
# ---------------------------------------------------------------------------

def cluster_bootstrap_ci(delta: pd.Series, clusters: pd.Series, n_boot: int, seed: int) -> tuple:
    """CI for the mean of `delta`, resampling whole clusters (dates/weeks)."""
    rng = np.random.default_rng(seed)
    groups = delta.groupby(clusters.values)
    keys = list(groups.groups.keys())
    sums = groups.sum().values
    counts = groups.count().values
    idx = rng.integers(0, len(keys), size=(n_boot, len(keys)))
    boot_means = sums[idx].sum(axis=1) / np.maximum(counts[idx].sum(axis=1), 1)
    return float(np.quantile(boot_means, 0.025)), float(np.quantile(boot_means, 0.975))


# ---------------------------------------------------------------------------

def prepare(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["warming_miss"] = df["warming"].isna().astype(int)
    df["warming_f"] = df["warming"].fillna(0.0)
    df["nbm_gap"] = df["nbm_exceed_param"] - df["market_p_exceed"]
    df["candle_age_h"] = df["candle_age_h"].fillna(999.0)
    df["iso_week"] = pd.to_datetime(df["target_date"]).dt.strftime("%G-W%V")
    return df


def evaluate(rows: pd.DataFrame, pcol: str) -> dict:
    """Δlog-loss vs market with date- and week-clustered bootstrap CIs."""
    ll_mkt = log_loss(rows["y"].values, rows["market_p_exceed"].values)
    ll_mod = log_loss(rows["y"].values, rows[pcol].values)
    delta = pd.Series(ll_mkt - ll_mod, index=rows.index)  # >0 = better than market
    lo_d, hi_d = cluster_bootstrap_ci(delta, rows["target_date"], N_BOOT, SEED)
    lo_w, hi_w = cluster_bootstrap_ci(delta, rows["iso_week"], N_BOOT, SEED + 1)
    return {
        "n": len(rows), "n_dates": int(rows["target_date"].nunique()),
        "delta_logloss": float(delta.mean()),
        "ci_date": [lo_d, hi_d], "ci_week": [lo_w, hi_w],
        "ll_market": float(ll_mkt.mean()), "ll_model": float(ll_mod.mean()),
    }


def per_city_two_stage(rows: pd.DataFrame, pcol: str) -> list[dict]:
    weeks = np.sort(rows["iso_week"].unique())
    early = set(weeks[: max(1, len(weeks) // 2)])
    out = []
    for slug, g in rows.groupby("slug"):
        d = log_loss(g["y"].values, g["market_p_exceed"].values) - log_loss(g["y"].values, g[pcol].values)
        d = pd.Series(d, index=g.index)
        d_early = d[g["iso_week"].isin(early)]
        d_late = d[~g["iso_week"].isin(early)]
        out.append({
            "slug": slug, "n": len(g),
            "delta": float(d.mean()),
            "delta_early": float(d_early.mean()) if len(d_early) else None,
            "delta_late": float(d_late.mean()) if len(d_late) else None,
            "sweet_spot": bool(len(d_early) and len(d_late) and d_early.mean() > 0 and d_late.mean() > 0),
        })
    return sorted(out, key=lambda r: -r["delta"])


def threshold_scan(rows: pd.DataFrame, pcol: str) -> list[dict]:
    """Exploratory: on wing rows, when the model disagrees with the market by
    >= thr, is the model right? (Realized vs both, plus a crude EV proxy for a
    1-unit YES/NO bet at the market price with no spread.)"""
    out = []
    for thr in THRESHOLDS:
        m = rows[(rows[pcol] - rows["market_p_exceed"]).abs() >= thr]
        if m.empty:
            out.append({"thr": thr, "n": 0})
            continue
        long_side = m[pcol] > m["market_p_exceed"]  # model says exceed more likely
        ev = np.where(long_side, m["y"] - m["market_p_exceed"], m["market_p_exceed"] - m["y"])
        out.append({
            "thr": thr, "n": len(m), "n_dates": int(m["target_date"].nunique()),
            "mean_model_p": float(m[pcol].mean()), "mean_market_p": float(m["market_p_exceed"].mean()),
            "realized_y": float(m["y"].mean()), "ev_proxy_no_spread": float(np.mean(ev)),
        })
    return out


def main() -> None:
    # ASCII-only description: the module docstring's Greek symbols crash --help
    # on Windows consoles with non-UTF-8 code pages (cp1251 etc.)
    ap = argparse.ArgumentParser(
        description="Wing model ladder: walk-forward test whether any rung beats "
                    "the market on cheap-wing exceedance (see module docstring).")
    ap.add_argument("--data-root", default=None)
    args = ap.parse_args()
    data = data_root(args.data_root)

    df = prepare(pd.read_parquet(data / "processed" / "exceedance_dataset.parquet"))
    test_weeks = np.sort(df.loc[df["target_date"] >= TEST_START, "iso_week"].unique())

    preds: list[pd.DataFrame] = []
    variants_used: dict[str, list] = {"r3_catboost": []}
    for wk in test_weeks:
        # clip the first block to TEST_START: its ISO week may begin earlier, and
        # those earlier days must stay on the train side of the boundary
        te = df[(df["iso_week"] == wk) & (df["target_date"] >= TEST_START)]
        first_date = te["target_date"].min()
        tr = df[df["target_date"] < first_date]
        if tr["target_date"].nunique() < 30 or te.empty:
            continue
        block = te[["slug", "target_date", "iso_week", "strike", "temp_rank", "y",
                    "market_p_exceed", "is_wing", "wing_side", "stale"]].copy()
        for name, fit in RUNGS:
            block[name] = fit(tr, te)
            if name == "r3_catboost":
                variants_used["r3_catboost"].append(getattr(rung3_catboost, "last_variant", None))
        preds.append(block)

    allp = pd.concat(preds, ignore_index=True)
    wings = allp[allp["is_wing"] == 1]
    headline = wings[wings["stale"] == 0] if STALE_EXCLUDE else wings

    results: dict = {"test_weeks": list(map(str, test_weeks)),
                     "r3_variants": variants_used["r3_catboost"]}
    gate_open = True
    # Gate: each rung must beat the PREVIOUS accepted rung (market = rung 0) with
    # a positive date-clustered CI on the INCREMENTAL delta — bootstrapping only
    # vs the market would let a marginal follow-on ride a stronger predecessor.
    prev_col = "market_p_exceed"
    for name, _ in RUNGS:
        res = {
            "headline_fresh_wings": evaluate(headline, name),
            "all_wings": evaluate(wings, name),
            "all_rows": evaluate(allp, name),
        }
        d_prev = pd.Series(
            log_loss(headline["y"].values, headline[prev_col].values)
            - log_loss(headline["y"].values, headline[name].values),
            index=headline.index,
        )
        lo_p, hi_p = cluster_bootstrap_ci(d_prev, headline["target_date"], N_BOOT, SEED + 2)
        res["vs_prev_rung"] = {"prev": prev_col, "delta": float(d_prev.mean()), "ci_date": [lo_p, hi_p]}
        passed = bool(d_prev.mean() > 0 and lo_p > 0)
        res["passes"] = passed
        res["confirmatory"] = gate_open
        res["verdict"] = ("PASS" if passed else "FAIL") + ("" if gate_open else " (exploratory: gate closed)")
        gate_open = gate_open and passed
        if passed:
            prev_col = name
        res["per_city"] = per_city_two_stage(headline, name)
        res["thresholds"] = threshold_scan(headline, name)
        hot = headline[headline["wing_side"] == "hot"]
        res["reliability_hot_2_15"] = {
            "market": reliability_table(hot["y"], hot["market_p_exceed"], [0, .02, .05, .08, .12, .15, 1.0]),
            "model": reliability_table(hot["y"], hot[name], [0, .02, .05, .08, .12, .15, 1.0]),
        }
        results[name] = res

    out_meta = data / "processed" / "wing_ladder_meta.json"
    out_meta.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    allp.to_parquet(data / "processed" / "wing_ladder_preds.parquet", index=False)

    parts = ["<h1>Wing ladder report</h1>",
             f"<p>Test weeks: {', '.join(map(str, test_weeks))}. Headline = fresh wing rows; "
             f"Δlog-loss &gt; 0 = beats the market; CI = date-clustered bootstrap.</p>"]
    for name, _ in RUNGS:
        r = results[name]
        h = r["headline_fresh_wings"]
        parts.append(f"<h2>{name} — {r['verdict']}</h2>")
        parts.append(f"<pre>headline: Δ={h['delta_logloss']:.5f} CI_date=[{h['ci_date'][0]:.5f},{h['ci_date'][1]:.5f}] "
                     f"CI_week=[{h['ci_week'][0]:.5f},{h['ci_week'][1]:.5f}] n={h['n']} dates={h['n_dates']}\n"
                     f"all wings: Δ={r['all_wings']['delta_logloss']:.5f}  all rows: Δ={r['all_rows']['delta_logloss']:.5f}</pre>")
        parts.append("<h3>Per-city (headline)</h3>" + pd.DataFrame(r["per_city"]).to_html(index=False, float_format=lambda x: f"{x:.5f}"))
        parts.append("<h3>Threshold scan (exploratory)</h3>" + pd.DataFrame(r["thresholds"]).to_html(index=False, float_format=lambda x: f"{x:.4f}"))
    report = data.parent / "reports" / "wing_ladder_report.html"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(parts), encoding="utf-8")

    summary = {name: {"verdict": results[name]["verdict"],
                      "delta": round(results[name]["headline_fresh_wings"]["delta_logloss"], 5),
                      "ci_date": [round(x, 5) for x in results[name]["headline_fresh_wings"]["ci_date"]]}
               for name, _ in RUNGS}
    print(json.dumps(summary, indent=2))
    print(f"meta -> {out_meta}\npreds -> {data / 'processed' / 'wing_ladder_preds.parquet'}\nreport -> {report}")


if __name__ == "__main__":
    main()
