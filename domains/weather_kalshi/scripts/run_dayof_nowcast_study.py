"""Day-of nowcast edge study: METAR running max vs Polymarket intraday prices.

Research pipeline (see oled/changes/dayof-nowcast-edge-study/spec.md):
  1. Ground truth  = market-implied winner (unique bracket with last price >= 0.90,
     history extending past local day end).
  2. Dead bracket  = METAR running max >= bracket_upper_f + buffer (buffer 0/1/2 F).
  3. Measures      = checkpoint mispricing, basis-error rate, latency decay,
     strategy backtest at 12/15/18 local.

Outputs:
  data/processed/dayof_study_checkpoints.parquet  -- per (event, hour, bracket) rows
  data/processed/dayof_study_deaths.parquet       -- bracket-death latency events
  data/processed/dayof_study_meta.json            -- exclusion counters, run info

Usage:
  python -m scripts.run_dayof_nowcast_study            # full rebuild
  python -m scripts.run_dayof_nowcast_study --no-rebuild  # reuse cached parquet
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scripts.build_ml_panel import parse_bracket

ROOT = Path(__file__).resolve().parents[1]
PM_DIR = ROOT / "data" / "raw" / "polymarket"
METAR_DIR = ROOT / "data" / "raw" / "metar"
OUT_DIR = ROOT / "data" / "processed"
STATIC = ROOT / "data" / "static"

CHECKPOINT_HOURS = list(range(10, 22))  # 10:00 .. 21:00 local
BUFFERS = [0.0, 1.0, 2.0]
PRICE_STALENESS_MIN = 120  # candle must be at most this old at a checkpoint
DECAY_OFFSETS_MIN = [0, 10, 30, 60, 120, 180]


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def load_city_meta() -> dict:
    """slug -> {tz: ZoneInfo, icao: str|None, name: str}"""
    cities = json.loads((STATIC / "polymarket_cities.json").read_text(encoding="utf-8"))
    icao_map = json.loads((STATIC / "icao_map.json").read_text(encoding="utf-8"))
    meta = {}
    for slug, info in cities.items():
        icao = (icao_map.get(slug) or {}).get("primary")
        meta[slug] = {
            "tz": ZoneInfo(info["timezone"]),
            "icao": icao,
            "name": info["name"],
            "unit": info.get("unit", "F"),
        }
    return meta


def load_brackets() -> pd.DataFrame:
    mk = pd.read_parquet(PM_DIR / "all_cities_markets.parquet")
    mk = mk.drop_duplicates(subset=["city_slug", "market_date", "bracket_index"])
    parsed = mk["question"].map(parse_bracket)
    mk["lower"] = parsed.map(lambda t: t[0])
    mk["upper"] = parsed.map(lambda t: t[1])
    mk["unit"] = parsed.map(lambda t: t[2])
    mk["upper_f"] = mk.apply(
        lambda r: (c_to_f(r["upper"]) if r["unit"] == "C" else r["upper"])
        if r["upper"] is not None else np.nan,
        axis=1,
    )
    return mk[["city_slug", "market_date", "bracket_index", "question", "upper_f", "unit"]]


def load_metar_local(icao: str, tz: ZoneInfo) -> pd.DataFrame | None:
    path = METAR_DIR / f"metar_{icao}.parquet"
    if not path.exists():
        return None
    m = pd.read_parquet(path, columns=["valid_time_utc", "temp_f"]).dropna()
    m["local"] = m["valid_time_utc"].dt.tz_convert(tz)
    m["local_date"] = m["local"].dt.date
    return m.sort_values("local")


def rebuild() -> dict:
    meta = load_city_meta()
    brackets = load_brackets()
    hist = pd.read_parquet(
        PM_DIR / "all_cities_price_history.parquet",
        columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"],
    )
    hist["ts_utc"] = pd.to_datetime(hist["timestamp"], unit="s", utc=True)

    counters = {
        "events_total": 0, "no_metar_station": 0, "no_obs_that_day": 0,
        "history_not_past_day_end": 0, "no_unique_winner": 0, "events_used": 0,
    }
    checkpoint_rows: list[dict] = []
    death_rows: list[dict] = []

    metar_cache: dict[str, pd.DataFrame | None] = {}

    for (slug, mdate), ev in hist.groupby(["city_slug", "market_date"]):
        counters["events_total"] += 1
        cm = meta.get(slug)
        if cm is None or not cm["icao"]:
            counters["no_metar_station"] += 1
            continue
        if slug not in metar_cache:
            metar_cache[slug] = load_metar_local(cm["icao"], cm["tz"])
        obs_all = metar_cache[slug]
        if obs_all is None:
            counters["no_metar_station"] += 1
            continue

        tz = cm["tz"]
        day = pd.Timestamp(mdate).date()
        day_start = pd.Timestamp(day, tz=tz)
        day_end = day_start + pd.Timedelta(days=1)

        obs = obs_all[obs_all["local_date"] == day]
        if len(obs) < 5:
            counters["no_obs_that_day"] += 1
            continue

        # market-truth winner: last candle per bracket, unique >= 0.90,
        # and history must extend past local day end (else market unresolved)
        if ev["ts_utc"].max() < day_end:
            counters["history_not_past_day_end"] += 1
            continue
        last = ev.loc[ev.groupby("bracket_index")["ts_utc"].idxmax()]
        winners = last[last["price"] >= 0.90]
        if len(winners) != 1:
            counters["no_unique_winner"] += 1
            continue
        winner_idx = int(winners["bracket_index"].iloc[0])

        bk = brackets[(brackets["city_slug"] == slug) & (brackets["market_date"] == mdate)]
        if bk.empty:
            counters["no_unique_winner"] += 1
            continue
        upper_by_idx = dict(zip(bk["bracket_index"], bk["upper_f"]))

        ev = ev.copy()
        ev["local"] = ev["ts_utc"].dt.tz_convert(tz)
        ev_day = ev[(ev["local"] >= day_start) & (ev["local"] < day_end)]

        # running max at each observation time
        obs = obs.copy()
        obs["run_max"] = obs["temp_f"].cummax()

        # --- death events per bracket (buffer sweep) ---
        for bidx, upper_f in upper_by_idx.items():
            if pd.isna(upper_f):
                continue
            bc = ev_day[ev_day["bracket_index"] == bidx].sort_values("local")
            for buf in BUFFERS:
                crossed = obs[obs["run_max"] >= upper_f + buf]
                if crossed.empty:
                    continue
                death_t = crossed["local"].iloc[0]
                row = {
                    "city_slug": slug, "market_date": str(day), "bracket_index": bidx,
                    "buffer": buf, "death_local": death_t.isoformat(),
                    "death_hour": death_t.hour + death_t.minute / 60.0,
                    "won_market": int(bidx == winner_idx),
                }
                if buf == 1.0 and not bc.empty:
                    for off in DECAY_OFFSETS_MIN:
                        t = death_t + pd.Timedelta(minutes=off)
                        recent = bc[bc["local"] <= t]
                        if not recent.empty and (t - recent["local"].iloc[-1]) <= pd.Timedelta(minutes=PRICE_STALENESS_MIN):
                            row[f"px_{off}m"] = float(recent["price"].iloc[-1])
                    after = bc[(bc["local"] > death_t) & (bc["price"] <= 0.01)]
                    if not after.empty:
                        row["min_to_1c"] = float((after["local"].iloc[0] - death_t).total_seconds() / 60.0)
                death_rows.append(row)

        # --- checkpoint snapshots ---
        for hour in CHECKPOINT_HOURS:
            cp = day_start + pd.Timedelta(hours=hour)
            obs_upto = obs[obs["local"] <= cp]
            if obs_upto.empty or (cp - obs_upto["local"].iloc[-1]) > pd.Timedelta(hours=3):
                continue
            run_max = float(obs_upto["run_max"].iloc[-1])
            for bidx, upper_f in upper_by_idx.items():
                bc = ev_day[(ev_day["bracket_index"] == bidx) & (ev_day["local"] <= cp)]
                if bc.empty:
                    continue
                last_c = bc.sort_values("local").iloc[-1]
                if (cp - last_c["local"]) > pd.Timedelta(minutes=PRICE_STALENESS_MIN):
                    continue
                rec = {
                    "city_slug": slug, "market_date": str(day), "hour": hour,
                    "bracket_index": bidx, "upper_f": upper_f, "run_max_f": run_max,
                    "yes_price": float(last_c["price"]),
                    "won_market": int(bidx == winner_idx),
                    "is_us": cm["unit"] == "F",
                }
                for buf in BUFFERS:
                    rec[f"dead_b{int(buf)}"] = bool(
                        not pd.isna(upper_f) and run_max >= upper_f + buf
                    )
                checkpoint_rows.append(rec)
        counters["events_used"] += 1

    cps = pd.DataFrame(checkpoint_rows)
    deaths = pd.DataFrame(death_rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cps.to_parquet(OUT_DIR / "dayof_study_checkpoints.parquet", index=False)
    deaths.to_parquet(OUT_DIR / "dayof_study_deaths.parquet", index=False)
    (OUT_DIR / "dayof_study_meta.json").write_text(json.dumps(counters, indent=1))
    print("Counters:", json.dumps(counters, indent=1))
    print(f"checkpoint rows: {len(cps)}, death rows: {len(deaths)}")
    return counters


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rebuild", action="store_true", help="reuse cached parquet")
    args = ap.parse_args()
    if not args.no_rebuild:
        rebuild()
    else:
        print("Using cached artifacts in data/processed/")


if __name__ == "__main__":
    main()
