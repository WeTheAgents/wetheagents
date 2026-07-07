"""Build the exceedance training dataset for the cheap-wings model.

One row = one strike (a bracket lower bound) for one US city-day. Target
`y = 1[realized daily max >= strike]`, derived from the SETTLEMENT WINNER bracket
in labels.parquet — NOT from a raw temperature, because market-labeled days carry
no exact max (only the winning bracket). The market baseline is the cumulative
bracket price at/above the strike at decision_time; the model learns a correction
to it (offset), so this dataset ships both the target and market_p_exceed.

Key correctness points (learned building stages 1-2):
  * bracket_index is NOT temperature-ordered — brackets are sorted by lower bound
    into a temp_rank, and the target is 1[winner_temp_rank >= r]. Using the raw
    index would scramble the target.
  * NBM features use ONLY P5-P95 (p1/p99 exist in Mar-Apr but vanish Jun-Jul, the
    test/inference period — using them would leak across the walk-forward).
  * Our edge zone (cheapest wings) is beyond P5/P95 where the NBM CDF is pure
    extrapolation, so we ship two NBM exceedance estimates (empirical + parametric)
    whose divergence flags tail uncertainty; z is the robust primary.

v1 scope: the 11 US NBM cities (= nbm_dayof slugs), decision_time = 14:00 UTC.
No snapshot data (the backfill supersedes snapshot NBM). city_rate is NOT written
here — it must be recomputed in-fold in the model stage (the abnormal_features
column leaks via a fixed cutoff).

Output: data/processed/exceedance_dataset.parquet (+ _meta.json, HTML report).

Usage
-----
    python -m scripts.build_exceedance_dataset --data-root <main-checkout>/data
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_ml_panel import parse_bracket  # noqa: E402
from src.bracket_builder import _build_empirical_cdf  # noqa: E402

DECISION_HOUR_UTC = 14
STALE_HOURS = 3.0
WING_PRICE = 0.15
CLIP = (0.005, 0.995)
SUM_OK = (0.9, 1.1)
# ONLY the always-present QMD MaxT percentiles. p1/p99 are excluded on purpose:
# they are present Mar-Apr but absent Jun-Jul (the test period) -> leak if used.
P_COLS = [5, 10, 25, 50, 75, 90, 95]


def data_root(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("WEATHER_DATA_ROOT")
    if env:
        return Path(env)
    return ROOT / "data"


def _lower_key(lower, upper):
    """Sort key placing the bottom tail first and top tail last.

    Uses pd.isna, not `is None`: the parsed None lower bound becomes NaN once it
    lands in the DataFrame column, and `NaN is None` is False — which would sort
    the bottom tail to the end and corrupt every temp_rank.
    """
    if pd.isna(lower):
        return -np.inf
    return float(lower)


def city_brackets(mk_city_day: pd.DataFrame) -> pd.DataFrame:
    """Parse + temperature-sort one city-day's brackets, assign temp_rank."""
    rows = []
    for r in mk_city_day.drop_duplicates("bracket_index").itertuples():
        lo, up, unit = parse_bracket(r.question)
        rows.append({
            "bracket_index": int(r.bracket_index), "lower": lo, "upper": up,
            "unit": unit, "yes_price": r.yes_price,
        })
    df = pd.DataFrame(rows)
    df["sort_key"] = df.apply(lambda x: _lower_key(x["lower"], x["upper"]), axis=1)
    df = df.sort_values("sort_key").reset_index(drop=True)
    df["temp_rank"] = np.arange(len(df))
    return df


def decision_prices(hist_city_day: pd.DataFrame, decision_ts: pd.Timestamp) -> dict[int, tuple]:
    """Last candle at/before decision_time per bracket_index -> (price, age_h)."""
    sub = hist_city_day[hist_city_day["ts_utc"] <= decision_ts]
    out = {}
    for bidx, g in sub.groupby("bracket_index"):
        last = g.loc[g["ts_utc"].idxmax()]
        age_h = (decision_ts - last["ts_utc"]) / pd.Timedelta(hours=1)
        out[int(bidx)] = (float(last["price"]), float(age_h))
    return out


def nbm_exceed_empirical(pctls: dict[int, float], median: float, strike: float) -> float:
    """P(max >= strike) from the P5-P95 empirical CDF (tail extrapolated).

    Enforces strictly-increasing percentile values first: NBM can be so tight
    (e.g. coastal LA, sigma ~1F) that adjacent percentiles tie, which PchipInterpolator
    rejects. A 1e-6 jitter breaks ties without changing the CDF meaningfully.
    """
    keys = sorted(pctls)
    vals = [float(pctls[k]) for k in keys]
    for i in range(1, len(vals)):
        if vals[i] <= vals[i - 1]:
            vals[i] = vals[i - 1] + 1e-6
    dist = _build_empirical_cdf(dict(zip(keys, vals, strict=True)), median)
    return float(np.clip(1.0 - dist.cdf(strike - 0.5), 0.0, 1.0))


def build(data: Path) -> tuple[pd.DataFrame, dict]:
    proc, pm = data / "processed", data / "raw" / "polymarket"
    labels = pd.read_parquet(proc / "labels.parquet")
    labels["target_date"] = labels["target_date"].astype(str)
    nbm = pd.read_parquet(data / "raw" / "nbm_backfill" / "nbm_dayof.parquet")
    nbm = nbm[nbm["days_ahead"] == 0].copy()
    nbm["target_date"] = nbm["target_date"].astype(str)
    us_slugs = set(nbm["slug"].unique())  # the 11 US NBM cities

    lab = labels[(labels["train_ok"]) & (labels["slug"].isin(us_slugs))]
    keep = ["slug", "target_date", "winner_bracket_final", "label_source", "unit", "metar_day_max_nat"]
    joined = lab[keep].merge(
        nbm[["slug", "target_date", "nbm_median", "nbm_sigma"] + [f"nbm_p{p}" for p in P_COLS]],
        on=["slug", "target_date"], how="inner",
    )

    markets = pd.read_parquet(pm / "all_cities_markets.parquet",
                              columns=["city_slug", "market_date", "bracket_index", "question", "yes_price"])
    markets["md"] = markets["market_date"].astype(str).str[:10]
    hist = pd.read_parquet(pm / "all_cities_price_history.parquet",
                           columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"])
    hist["ts_utc"] = pd.to_datetime(hist["timestamp"], unit="s", utc=True)
    hist["md"] = hist["market_date"].astype(str).str[:10]

    # prev-day realized max for the warming feature (known by decision time)
    dt = pd.read_parquet(proc / "metar_day_table.parquet", columns=["city_slug", "local_date", "day_max_nat"])
    dt["local_date"] = dt["local_date"].astype(str).str[:10]
    prev_max = {(r.city_slug, r.local_date): r.day_max_nat for r in dt.itertuples()}

    mk_by = {k: v for k, v in markets.groupby(["city_slug", "md"])}
    hist_by = {k: v for k, v in hist.groupby(["city_slug", "md"])}

    rows: list[dict] = []
    counters = {"events": 0, "no_market": 0, "no_winner_in_brackets": 0,
                "incomplete_prices": 0, "sum_out_of_range": 0, "emitted_events": 0}

    for r in joined.itertuples():
        counters["events"] += 1
        slug, td = r.slug, r.target_date
        bk = mk_by.get((slug, td))
        if bk is None or bk.empty:
            counters["no_market"] += 1
            continue
        br = city_brackets(bk)

        # winner's temperature rank (winner_bracket_final is a raw index)
        wrow = br[br["bracket_index"] == int(r.winner_bracket_final)]
        if wrow.empty:
            counters["no_winner_in_brackets"] += 1
            continue
        winner_rank = int(wrow["temp_rank"].iloc[0])

        decision_ts = pd.Timestamp(td, tz="UTC") + pd.Timedelta(hours=DECISION_HOUR_UTC)
        hh = hist_by.get((slug, td))
        prices = decision_prices(hh, decision_ts) if hh is not None else {}

        # exceedance market curve from decision-time bracket prices
        br = br.copy()
        br["price_dt"] = [prices.get(i, (np.nan, np.nan))[0] for i in br["bracket_index"]]
        br["age_h"] = [prices.get(i, (np.nan, np.nan))[1] for i in br["bracket_index"]]
        if br["price_dt"].isna().any():
            # a bracket never traded before decision_time — its price is unknown;
            # fabricating 0 would corrupt the exceedance cumsum, so drop the day.
            counters["incomplete_prices"] += 1
            continue
        total = br["price_dt"].sum()
        if not (SUM_OK[0] <= total <= SUM_OK[1]):
            counters["sum_out_of_range"] += 1
            continue
        # cumulative price at/above each temp_rank (top-down)
        br = br.sort_values("temp_rank")
        exceed_price = br["price_dt"][::-1].cumsum()[::-1] / total
        br["market_p_exceed"] = exceed_price.values
        # per-strike freshness: the min quote age among the brackets that CONTRIBUTE
        # to the exceedance at this strike (temp_rank >= r). If even the freshest
        # contributing quote is stale, the strike's exceedance has no recent input.
        br["min_age_up"] = br["age_h"][::-1].cummin()[::-1].values

        pctls = {p: getattr(r, f"nbm_p{p}") for p in P_COLS}
        nbm_median, nbm_sigma = float(r.nbm_median), max(float(r.nbm_sigma), 0.1)
        pmax = prev_max.get((slug, (pd.Timestamp(td) - pd.Timedelta(days=1)).date().isoformat()))
        warming = (nbm_median - float(pmax)) if pmax is not None and not pd.isna(pmax) else np.nan
        mo = pd.Timestamp(td).month
        doy = pd.Timestamp(td).dayofyear

        counters["emitted_events"] += 1
        # one row per strike = lower bound of each bracket with temp_rank >= 1
        for b in br.itertuples():
            if b.temp_rank == 0 or pd.isna(b.lower):  # bottom tail has no lower-bound strike
                continue
            strike = float(b.lower)
            z = (strike - nbm_median) / nbm_sigma  # standardized distance feature
            # exceedance event is rounded_max >= strike, i.e. true_max >= strike-0.5;
            # use strike-0.5 for BOTH exceedance probs (param + emp) so they match
            # each other and the target convention.
            z_exc = (strike - 0.5 - nbm_median) / nbm_sigma
            mpe = float(np.clip(b.market_p_exceed, *CLIP))
            # A "wing" in exceedance space = an extreme market exceedance prob (a
            # cheap YES on the hot side or a cheap NO on the cold side), NOT a cheap
            # bracket price. min(p, 1-p) <= 0.15 captures both tails.
            wing_tail = min(mpe, 1.0 - mpe)
            rows.append({
                "slug": slug, "target_date": td, "unit": r.unit,
                "temp_rank": int(b.temp_rank), "bracket_index": int(b.bracket_index),
                "strike": strike,
                "y": int(winner_rank >= b.temp_rank),
                "market_p_exceed": mpe,
                "market_p_bracket": float(b.price_dt) if not pd.isna(b.price_dt) else np.nan,
                "is_wing": int(wing_tail <= WING_PRICE),
                "wing_side": "hot" if mpe <= WING_PRICE else ("cold" if mpe >= 1 - WING_PRICE else "mid"),
                "candle_age_h": float(b.age_h) if not pd.isna(b.age_h) else np.nan,
                "stale": int(b.min_age_up > STALE_HOURS) if not pd.isna(b.min_age_up) else 1,
                "z": z,
                "nbm_exceed_param": float(1.0 - stats.norm.cdf(z_exc)),
                "nbm_exceed_emp": nbm_exceed_empirical(pctls, nbm_median, strike),
                "nbm_median": nbm_median, "nbm_sigma": nbm_sigma, "log_nbm_sigma": float(np.log(nbm_sigma)),
                "warming": warming, "month": mo,
                "doy_sin": float(np.sin(2 * np.pi * doy / 365.25)),
                "doy_cos": float(np.cos(2 * np.pi * doy / 365.25)),
                "label_source": r.label_source,
                "decision_ts": decision_ts,
            })

    df = pd.DataFrame(rows)
    counters["n_rows"] = len(df)
    counters["n_wing_rows"] = int(df["is_wing"].sum()) if len(df) else 0
    counters["n_dates"] = int(df["target_date"].nunique()) if len(df) else 0
    counters["n_cities"] = int(df["slug"].nunique()) if len(df) else 0
    counters["y_base_rate"] = float(df["y"].mean()) if len(df) else None
    counters["stale_frac"] = float(df["stale"].mean()) if len(df) else None
    if len(df):
        fresh = df[df["stale"] == 0]
        counters["fresh_rows"] = len(fresh)
        counters["fresh_dates"] = int(fresh["target_date"].nunique())
        counters["fresh_city_days"] = int(fresh.groupby(["slug", "target_date"]).ngroups)
        # calibration by wing side on FRESH rows: market vs NBM vs realized. If the
        # market already tracks reality better than NBM here, the NBM edge is thin.
        cal = {}
        for side in ("hot", "cold", "mid"):
            s = fresh[fresh["wing_side"] == side]
            if len(s):
                cal[side] = {"n": len(s), "market": round(float(s["market_p_exceed"].mean()), 4),
                             "nbm_param": round(float(s["nbm_exceed_param"].mean()), 4),
                             "realized_y": round(float(s["y"].mean()), 4)}
        counters["fresh_calibration_by_side"] = cal
    return df, counters


def monotonicity_ok(df: pd.DataFrame) -> float:
    """Fraction of city-days where market_p_exceed is non-increasing in strike."""
    ok = 0
    grp = df.sort_values("strike").groupby(["slug", "target_date"])
    n = 0
    for _, g in grp:
        n += 1
        if (g["market_p_exceed"].diff().dropna() <= 1e-9).all():
            ok += 1
    return ok / n if n else 1.0


def write_report(df: pd.DataFrame, counters: dict, mono: float, out_html: Path) -> None:
    wings = df[df["is_wing"] == 1]
    by_city = df.groupby("slug").agg(
        rows=("y", "count"), y_rate=("y", "mean"), stale=("stale", "mean"),
    )
    by_city["wing_rows"] = wings.groupby("slug")["y"].count()
    by_city["wing_y_rate"] = wings.groupby("slug")["y"].mean()
    by_city = by_city.reset_index()
    parts = [
        "<h1>Exceedance dataset report</h1>",
        f"<pre>{json.dumps(counters, indent=2, default=str)}</pre>",
        f"<p>market_p_exceed monotone-in-strike on {mono:.1%} of city-days (want ~100%).</p>",
        "<h2>Per-city</h2>", by_city.to_html(index=False, float_format=lambda x: f'{x:.3f}'),
    ]
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None)
    args = ap.parse_args()
    data = data_root(args.data_root)

    df, counters = build(data)
    if df.empty:
        print(json.dumps(counters, indent=2, default=str))
        raise SystemExit("no rows produced")

    # anti-leak assert: every market candle used is at/before its decision_ts
    assert (df["candle_age_h"].dropna() >= -1e-9).all(), "candle newer than decision_time (leak)"
    mono = monotonicity_ok(df)
    counters["monotone_frac"] = mono

    out = data / "processed" / "exceedance_dataset.parquet"
    df.to_parquet(out, index=False)
    (data / "processed" / "exceedance_dataset_meta.json").write_text(
        json.dumps(counters, indent=2, default=str), encoding="utf-8")
    write_report(df, counters, mono, data.parent / "reports" / "exceedance_dataset_report.html")

    print(json.dumps(counters, indent=2, default=str))
    print(f"exceedance dataset -> {out} ({len(df)} rows)")


if __name__ == "__main__":
    main()
