"""Rebuild settlement labels for every (city, target_date) market event.

The old ml_panel `realized_in_bracket` labels are broken (643/924 disagreements
with market resolution): build_ml_panel compares the raw observed max against
bracket bounds without native-unit rounding, and international obs come from
ERA5 (underestimates daily max, ~5-day lag). This script produces the canonical
label table both the exceedance dataset and any future study must use.

Two independent label sources per (slug, target_date):
  1. market  -- market-implied winner: unique bracket whose LAST price candle
     is >= 0.90. Empirical facts (2026-07-07 diagnosis on the full archive):
     candles are TRADES, so most markets go quiet before local midnight and
     only ~34% of events ever print a >=0.90 last candle; agreement with the
     METAR label is 89-99% regardless of how early trading died, EXCEPT when
     trading continues >6h past local day end (50% agreement, n=40 -- dispute
     signature). So: no minimum-history gate; events trading >6h past day end
     are quarantined as disputed instead.
  2. metar   -- bracket containing the rounded-native METAR daily max from
     data/processed/metar_day_table.parquet (rebuilt on corrected stations,
     PR #929). Covers ~89% of events; fallback label where the market never
     locked, and cross-check where it did.

Final training label: market where trusted, else METAR; conflicts quarantined
(label_source/train_ok columns).

Output: data/processed/labels.parquet, one row per (slug, target_date), with
both winners, agreement flags, label_quality, and per-city exclusion counters
in data/processed/labels_meta.json + an HTML report.

Data root: pass --data-root or set WEATHER_DATA_ROOT to the MAIN checkout's
data directory when running from a worktree (worktree data/ has only static/).

Usage
-----
    python -m scripts.build_labels --data-root D:/GitHub/wetheagents/domains/weather_kalshi/data
    WEATHER_DATA_ROOT=D:/GitHub/wetheagents/domains/weather_kalshi/data \
        python -m scripts.build_labels
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_ml_panel import parse_bracket, temp_in_bracket  # noqa: E402

DISPUTE_H = 6        # trading >this many hours past local day end = dispute signature
RECENCY_MARGIN_H = 12  # day_end must precede the download tip by this much
MIN_METAR_OBS = 12   # same bar as metar_day_table

# Operator data-prep contract (knowledge/data_manifest.md, 2026-07-06)
EXCLUDED_SLUGS = {"taipei"}   # CWA resolution != RCTP proxy, short METAR
NO_TRAIN_SLUGS = {"jakarta"}  # only ~49 days of price history


def data_root(cli_value: str | None) -> Path:
    if cli_value:
        return Path(cli_value)
    env = os.environ.get("WEATHER_DATA_ROOT")
    if env:
        return Path(env)
    return ROOT / "data"


def load_city_meta(static_dir: Path) -> dict[str, dict]:
    cities = json.loads((static_dir / "polymarket_cities.json").read_text(encoding="utf-8"))
    return {
        slug: {"tz": ZoneInfo(info["timezone"]), "name": info["name"],
               "unit": info.get("unit", "F")}
        for slug, info in cities.items()
    }


def load_brackets(pm_dir: Path) -> pd.DataFrame:
    mk = pd.read_parquet(
        pm_dir / "all_cities_markets.parquet",
        columns=["city_slug", "market_date", "bracket_index", "question"],
    )
    mk = mk.drop_duplicates(subset=["city_slug", "market_date", "bracket_index"], keep="last")
    parsed = mk["question"].map(parse_bracket)
    mk["lower"] = parsed.map(lambda t: t[0])
    mk["upper"] = parsed.map(lambda t: t[1])
    mk["unit"] = parsed.map(lambda t: t[2])
    mk["md"] = mk["market_date"].astype(str).str[:10]
    return mk


def metar_winner(day_max_nat: float, bk: pd.DataFrame) -> tuple[int | None, str]:
    """Map a rounded-native daily max onto exactly one bracket."""
    hits = [
        int(r.bracket_index)
        for r in bk.itertuples()
        if temp_in_bracket(day_max_nat, r.lower, r.upper)
    ]
    if len(hits) == 1:
        return hits[0], "labeled"
    if len(hits) == 0:
        return None, "no_bracket_match"
    return None, "ambiguous_match"


def build(data: Path) -> tuple[pd.DataFrame, dict]:
    static_dir = data / "static"
    pm_dir = data / "raw" / "polymarket"
    meta = load_city_meta(static_dir)
    brackets = load_brackets(pm_dir)

    hist = pd.read_parquet(
        pm_dir / "all_cities_price_history.parquet",
        columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"],
    )
    hist["ts_utc"] = pd.to_datetime(hist["timestamp"], unit="s", utc=True)
    hist["md"] = hist["market_date"].astype(str).str[:10]
    hist_max_ts = hist["ts_utc"].max()
    hist_groups = {k: g for k, g in hist.groupby(["city_slug", "md"])}

    day_table_path = data / "processed" / "metar_day_table.parquet"
    day_table = None
    if day_table_path.exists():
        day_table = pd.read_parquet(
            day_table_path, columns=["city_slug", "local_date", "day_max_nat", "n_obs"]
        ).set_index(["city_slug", "local_date"])

    rows: list[dict] = []

    # Drive by market events (a bracket set exists), not by price history:
    # some city-days have brackets + a METAR outcome but no traded candles,
    # and they still deserve a METAR-fallback label row.
    events = brackets[["city_slug", "md"]].drop_duplicates().itertuples(index=False)

    for slug, mdate in events:
        cm = meta.get(slug)
        if cm is None:
            continue
        tz = cm["tz"]
        day = pd.Timestamp(mdate).date()
        # next local midnight (NOT +24h: DST-transition days are 23h or 25h long)
        day_end = pd.Timestamp(day + timedelta(days=1), tz=tz)
        ev = hist_groups.get((slug, mdate))
        has_hist = ev is not None and not ev.empty
        last_ts = ev["ts_utc"].max() if has_hist else pd.NaT

        row: dict = {
            "slug": slug,
            "target_date": day.isoformat(),
            "unit": cm["unit"],
            "n_brackets_traded": int(ev["bracket_index"].nunique()) if has_hist else 0,
            "last_candle_utc": last_ts,
            "day_end_utc": day_end.tz_convert("UTC"),
            "hours_past_day_end": (last_ts - day_end) / pd.Timedelta(hours=1) if has_hist else np.nan,
            "excluded": slug in EXCLUDED_SLUGS,
            "no_train": slug in NO_TRAIN_SLUGS,
        }

        # --- market label ---
        winner_raw: int | None = None
        if has_hist:
            last = ev.loc[ev.groupby("bracket_index")["ts_utc"].idxmax()]
            winners = last[last["price"] >= 0.90]
            winner_raw = int(winners["bracket_index"].iloc[0]) if len(winners) == 1 else None
        row["winner_bracket_market_raw"] = winner_raw

        winner_market: int | None = None
        if not has_hist:
            status = "no_history"
        elif day_end + pd.Timedelta(hours=RECENCY_MARGIN_H) > hist_max_ts:
            # the day may not be fully traded/downloaded yet: an intraday
            # >=0.90 print can still reverse before the day is over
            status = "too_recent"
        elif winner_raw is None:
            status = "no_unique_winner"
        elif row["hours_past_day_end"] > DISPUTE_H:
            # markets still trading long past day end are resolution disputes;
            # their last-candle "winner" is wrong half the time
            status = "labeled_disputed"
        else:
            winner_market = winner_raw
            status = "labeled"
        row["winner_bracket_market"] = winner_market
        row["market_label_status"] = status

        # --- metar label ---
        winner_metar: int | None = None
        metar_status = "no_metar_day"
        day_max_nat = np.nan
        n_obs = 0
        if day_table is not None:
            try:
                rec = day_table.loc[(slug, day.isoformat())]
                day_max_nat = float(rec["day_max_nat"])
                n_obs = int(rec["n_obs"])
            except KeyError:
                pass
        if not np.isnan(day_max_nat):
            if day_end > hist_max_ts:
                # local day not fully elapsed as of our freshest data pull: the
                # day-table max is a running (partial) max, not the settled high.
                # Never let an incomplete day become a trainable label.
                metar_status = "too_recent"
            elif n_obs < MIN_METAR_OBS:
                metar_status = "too_few_obs"
            else:
                bk = brackets[(brackets["city_slug"] == slug) & (brackets["md"] == day.isoformat())]
                if bk.empty:
                    metar_status = "no_bracket_defs"
                else:
                    winner_metar, metar_status = metar_winner(day_max_nat, bk)
        row["winner_bracket_metar"] = winner_metar
        row["metar_label_status"] = metar_status
        row["metar_day_max_nat"] = day_max_nat
        row["metar_n_obs"] = n_obs

        # --- agreement / final label ---
        # Agreement is checked against the RAW market winner (present whenever a
        # unique >=0.90 winner exists, including disputed days), so a disputed
        # day whose winner disagrees with METAR is surfaced as a conflict instead
        # of silently falling through to the METAR label.
        if winner_raw is not None and winner_metar is not None:
            agree = winner_raw == winner_metar
            row["agree"] = agree
            row["label_quality"] = "both_agree" if agree else "conflict"
        elif winner_market is not None:
            row["agree"] = np.nan
            row["label_quality"] = "market_only"
        elif winner_metar is not None:
            row["agree"] = np.nan
            row["label_quality"] = "metar_only"
        else:
            row["agree"] = np.nan
            row["label_quality"] = "none"

        # Trusted market winner wins; else METAR (incl. disputed days that AGREE
        # with METAR — the dispute was benign). Conflicts carry no final label,
        # so a disputed day whose raw winner disagrees with METAR is quarantined.
        if row["label_quality"] == "conflict":
            row["winner_bracket_final"] = None
            row["label_source"] = "conflict"
        elif winner_market is not None:
            row["winner_bracket_final"] = winner_market
            row["label_source"] = "market"
        elif winner_metar is not None:
            row["winner_bracket_final"] = winner_metar
            row["label_source"] = "metar"
        else:
            row["winner_bracket_final"] = None
            row["label_source"] = "none"
        row["train_ok"] = (
            row["winner_bracket_final"] is not None
            and not row["excluded"]
            and not row["no_train"]
        )
        rows.append(row)

    df = pd.DataFrame(rows).sort_values(["slug", "target_date"]).reset_index(drop=True)

    counters = {
        "events_total": len(df),
        "market_labeled": int((df["market_label_status"] == "labeled").sum()),
        "market_status_counts": df["market_label_status"].value_counts().to_dict(),
        "metar_status_counts": df["metar_label_status"].value_counts().to_dict(),
        "label_quality_counts": df["label_quality"].value_counts().to_dict(),
        "label_source_counts": df["label_source"].value_counts().to_dict(),
        "train_ok": int(df["train_ok"].sum()),
        "dispute_hours": DISPUTE_H,
        "recency_margin_hours": RECENCY_MARGIN_H,
        "history_max_ts": str(hist_max_ts),
        "agree_rate_when_both": float(df["agree"].dropna().mean()) if df["agree"].notna().any() else None,
    }
    return df, counters


def agreement_by_history_bucket(labels: pd.DataFrame) -> pd.DataFrame:
    """Raw-winner vs METAR agreement, sliced by how long trading outlived the
    day. Documents why DISPUTE_H exists (the >6h bucket sits at ~50%)."""
    raw = labels[
        labels["winner_bracket_market_raw"].notna() & labels["winner_bracket_metar"].notna()
    ].copy()
    raw["agree_raw"] = raw["winner_bracket_market_raw"] == raw["winner_bracket_metar"]
    raw["bucket"] = pd.cut(
        raw["hours_past_day_end"], [-np.inf, -12, -6, -3, 0, DISPUTE_H, np.inf]
    ).astype(str)
    out = raw.groupby("bucket")["agree_raw"].agg(["mean", "count"]).reset_index()
    return out.rename(columns={"mean": "agree_rate", "count": "n"})


def compare_with_old_panel(labels: pd.DataFrame, data: Path) -> dict | None:
    """Old winner = the unique bracket with realized_in_bracket == 1."""
    panel_path = data / "processed" / "ml_panel.parquet"
    if not panel_path.exists():
        return None
    panel = pd.read_parquet(
        panel_path, columns=["slug", "target_date", "bracket_index", "realized_in_bracket"]
    )
    panel["target_date"] = panel["target_date"].astype(str).str[:10]
    all_events = panel.groupby(["slug", "target_date"]).size()
    hits = panel[panel["realized_in_bracket"] == 1]
    counts = hits.groupby(["slug", "target_date"]).size()
    unique_old = counts[counts == 1].index
    old = (
        hits.set_index(["slug", "target_date"])
        .loc[unique_old, "bracket_index"]
        .rename("winner_bracket_old")
    )

    lab = labels[labels["winner_bracket_final"].notna()].set_index(["slug", "target_date"])
    joined = lab.join(old, how="inner")
    n = len(joined)
    disagree = int((joined["winner_bracket_final"] != joined["winner_bracket_old"]).sum())
    per_city = (
        (joined["winner_bracket_final"] != joined["winner_bracket_old"])
        .groupby(level=0).agg(["sum", "count"])
    )
    per_city.columns = ["disagree", "n"]
    return {
        "events_compared": n,
        "old_label_disagrees": disagree,
        "old_panel_events": int(len(all_events)),
        "old_label_multi_hit": int((counts > 1).sum()),
        "old_label_zero_hit": int(len(all_events) - len(counts)),
        "per_city": per_city.reset_index().to_dict(orient="records"),
    }


def write_report(labels: pd.DataFrame, counters: dict, old_cmp: dict | None, out_html: Path) -> None:
    by_city = labels.groupby("slug").agg(
        events=("target_date", "count"),
        market_labeled=("market_label_status", lambda s: (s == "labeled").sum()),
        disputed=("market_label_status", lambda s: (s == "labeled_disputed").sum()),
        no_unique_winner=("market_label_status", lambda s: (s == "no_unique_winner").sum()),
        no_history=("market_label_status", lambda s: (s == "no_history").sum()),
        too_recent=("market_label_status", lambda s: (s == "too_recent").sum()),
        metar_fallback=("label_source", lambda s: (s == "metar").sum()),
        conflicts=("label_quality", lambda s: (s == "conflict").sum()),
        unlabeled=("label_source", lambda s: (s == "none").sum()),
        train_ok=("train_ok", "sum"),
        agree_rate=("agree", "mean"),
    ).reset_index()
    by_city["final_coverage"] = 1 - by_city["unlabeled"] / by_city["events"]

    # raw (not the trust-gated) market winner, so disputed conflicts — whose
    # winner_bracket_market is nulled — still show a market side for auditing.
    conflicts = labels[labels["label_quality"] == "conflict"][
        ["slug", "target_date", "winner_bracket_market_raw", "winner_bracket_metar",
         "metar_day_max_nat", "hours_past_day_end", "market_label_status"]
    ]

    parts = [
        "<h1>Labels rebuild report</h1>",
        f"<pre>{json.dumps(counters, indent=2, default=str)}</pre>",
        "<h2>Raw-winner vs METAR agreement by trading-lifetime bucket</h2>",
        "<p>Why DISPUTE_H exists: markets still trading &gt;6h past local day end "
        "agree with METAR only ~50% of the time (resolution disputes).</p>",
        agreement_by_history_bucket(labels).to_html(index=False, float_format=lambda x: f"{x:.3f}"),
        "<h2>Old ml_panel label comparison</h2>",
        f"<pre>{json.dumps(old_cmp, indent=2, default=str) if old_cmp else 'ml_panel.parquet not found'}</pre>",
        "<h2>Per-city coverage & exclusions</h2>",
        by_city.to_html(index=False, float_format=lambda x: f"{x:.3f}"),
        f"<h2>Conflicts (market vs METAR winner) — {len(conflicts)} rows</h2>",
        conflicts.to_html(index=False),
    ]
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=None, help="data dir (default: env WEATHER_DATA_ROOT or ROOT/data)")
    args = ap.parse_args()

    data = data_root(args.data_root)
    labels, counters = build(data)
    old_cmp = compare_with_old_panel(labels, data)

    out = data / "processed" / "labels.parquet"
    labels.to_parquet(out, index=False)
    (data / "processed" / "labels_meta.json").write_text(
        json.dumps({"counters": counters, "old_panel_comparison": old_cmp}, indent=2, default=str),
        encoding="utf-8",
    )
    write_report(labels, counters, old_cmp, data.parent / "reports" / "labels_report.html")

    print(json.dumps(counters, indent=2, default=str))
    if old_cmp:
        print(f"old-label comparison: {old_cmp['old_label_disagrees']}/{old_cmp['events_compared']} disagree")
    print(f"labels -> {out} ({len(labels)} rows)")


if __name__ == "__main__":
    main()
