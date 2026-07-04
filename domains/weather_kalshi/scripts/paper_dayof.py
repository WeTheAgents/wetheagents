"""Day-of paper trading runner (no real orders — reads only, simulated fills).

Scalp v2 (oled/changes/scalp-v2-runner, 2026-07-03):
  A (curmax-buy):  on CLEAN days enter at the city's rolling median settle hour
                   h*50 (12-19 local); on FLAGGED days (abnormal-day flag v2)
                   enter at 17:00. Place a virtual $24 YES bid ladder on the
                   bracket containing the rounded native-unit METAR running max.
  B (above-NO):    at 16:30-16:45 local, place a virtual $24 NO bid ladder on
                   the bracket above the current-max bracket.

Flag v2 (computed at trade time from local data + live METAR):
  flag = city_rate >= 0.5 OR fc_warm >= 3 native deg
         OR (yesterday was a rise day AND market entropy at D-1 20:00 >= q75)

Modes (combinable):
  --trade    execute strategies for cities currently inside their window
             (auto-retunes the rolling config when older than 30 days)
  --settle   settle open trades whose local day ended >= 3h ago
  --sweep    executability sweep: record books for key brackets (ad-hoc)
  --retune   rebuild data/static/scalp_hours.json from the rolling 60-day
             METAR window (h*50 + city_rate per city, entropy_q75)

Ledger:  data/paper/paper_trades.jsonl          (one JSON object per trade)
Orders:  data/paper/paper_order_snapshots.jsonl (post-signal book observations)
Traces:  data/paper/paper_runs.jsonl            (one object per run)
Sweeps:  data/paper/book_sweeps.parquet

Scheduled every 15 min by Windows task `dayof-paper-trade`
(remove: schtasks /delete /tn dayof-paper-trade /f).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

# allow running by file path (python scripts/paper_dayof.py) as well as -m
import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_ml_panel import parse_bracket
from src.clob_book import fetch_order_book, no_levels_from_yes_bids, walk_fill
from src.metar_client import fetch_metar_bulk
from src.polymarket_client import fetch_price_history

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PAPER_DIR = ROOT / "data" / "paper"
TRADES_PATH = PAPER_DIR / "paper_trades.jsonl"
ORDER_SNAPSHOTS_PATH = PAPER_DIR / "paper_order_snapshots.jsonl"
RUNS_PATH = PAPER_DIR / "paper_runs.jsonl"
SWEEPS_PATH = PAPER_DIR / "book_sweeps.parquet"
MARKETS_PATH = ROOT / "data" / "raw" / "polymarket" / "all_cities_markets.parquet"
STATIC = ROOT / "data" / "static"

# Passive paper execution model (operator decision 2026-07-04): place a virtual
# bid ladder instead of crossing the spread. Orders fill fully when the market
# passes through the bid, and half-fill when it only touches.
PASSIVE_MODEL = "passive_bid_ladder_v1"
LADDER_STAKES = (10.0, 8.0, 6.0)
STAKE = sum(LADDER_STAKES)  # primary headline notional
LADDER_TICK = 0.01
PRICE_EPS = 1e-9
WINDOW_B = (16 * 60 + 30, 16 * 60 + 45)  # minutes since local midnight, [start, end)
LATE_HOUR = 17                            # A-entry on flagged days
MAX_ASK_A = 0.85
YES_BID_RANGE_B = (0.02, 0.50)
SETTLE_GRACE_H = 3
BOOK_RATE_S = 0.25  # polite delay between book requests

# Scalp v2 rolling config (see --retune)
CONFIG_PATH = STATIC / "scalp_hours.json"
RETUNE_WINDOW_DAYS = 60
RETUNE_MAX_AGE_DAYS = 30
DEFAULT_H50 = 15
CR_CUT = 0.5
WARM_CUT = 3.0
# skip reasons that must NOT dedup-block a later attempt the same day
NONBLOCKING_SKIPS = {"flagged_wait_17", "clean_not_17_window"}


# ---------------------------------------------------------------------------
# Shared loading
# ---------------------------------------------------------------------------

def load_cities() -> dict[str, dict]:
    cities = json.loads((STATIC / "polymarket_cities.json").read_text(encoding="utf-8"))
    icao_map = json.loads((STATIC / "icao_map.json").read_text(encoding="utf-8"))
    out = {}
    for slug, info in cities.items():
        icao = (icao_map.get(slug) or {}).get("primary")
        if not icao:
            continue
        out[slug] = {"name": info["name"], "tz": ZoneInfo(info["timezone"]),
                     "unit": info.get("unit", "F"), "icao": icao}
    return out


def load_markets() -> pd.DataFrame:
    mk = pd.read_parquet(MARKETS_PATH)
    mk = mk.drop_duplicates(subset=["city_slug", "market_date", "bracket_index"], keep="last")
    mk["md"] = mk["market_date"].astype(str).str[:10]
    parsed = mk["question"].map(parse_bracket)
    mk["lower"] = parsed.map(lambda t: t[0])
    mk["upper"] = parsed.map(lambda t: t[1])
    mk["unit"] = parsed.map(lambda t: t[2])
    # native integer upper bound (INTL single-C brackets are n..n+0.999)
    mk["upper_nat"] = mk["upper"].map(lambda u: None if u is None or pd.isna(u) else float(int(u)))
    return mk


def city_brackets(mk: pd.DataFrame, slug: str, local_date: str) -> pd.DataFrame:
    """Brackets for one city-day, sorted by upper bound, open-top last."""
    g = mk[(mk["city_slug"] == slug) & (mk["md"] == local_date)].copy()
    return g.sort_values("upper_nat", na_position="last").reset_index(drop=True)


def _to_native(temp_c: float, unit: str) -> float:
    return float(round(temp_c * 9 / 5 + 32)) if unit == "F" else float(round(temp_c))


def metar_bundle(icao: str, tz: ZoneInfo, unit: str) -> dict | None:
    """One AWC fetch (48h) -> today's running max + yesterday's rise stats."""
    rows = fetch_metar_bulk([icao], hours=48)
    if not rows:
        return None
    today = datetime.now(tz).date()
    yday = today - timedelta(days=1)
    t_c, latest = [], None
    y_all, y_by15 = [], []
    for r in rows:
        t = r.valid_time_utc
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        loc = t.astimezone(tz)
        if r.temp_c is None:
            continue
        if loc.date() == today:
            t_c.append(r.temp_c)
            if latest is None or loc > latest:
                latest = loc
        elif loc.date() == yday:
            y_all.append(r.temp_c)
            if loc.hour < 15 or (loc.hour == 15 and loc.minute == 0):
                y_by15.append(r.temp_c)
    if not t_c:
        return None
    max_c = max(t_c)
    out = {"max_c": max_c, "max_f": max_c * 9 / 5 + 32,
           "rounded_native": _to_native(max_c, unit), "n_obs": len(t_c),
           "latest_obs_local": latest.isoformat(),
           "yday_max_nat": _to_native(max(y_all), unit) if y_all else None,
           "yday_rise": (int(_to_native(max(y_all), unit) > _to_native(max(y_by15), unit))
                         if y_all and y_by15 else None)}
    return out


# ---------------------------------------------------------------------------
# Scalp v2: rolling config + abnormal-day flag
# ---------------------------------------------------------------------------

def retune() -> dict:
    """Rebuild data/static/scalp_hours.json from the rolling METAR window.

    Local data only: hourly METAR archive (h*50 + city_rate) and the collected
    candle parquet (entropy_q75 at D-1 20:00 local).
    """
    from scripts.run_dayof_nowcast_study import load_metar_local

    cities = load_cities()
    since = (datetime.now(timezone.utc) - timedelta(days=RETUNE_WINDOW_DAYS)).date()
    per_city: dict[str, dict] = {}
    for slug, cm in cities.items():
        m = load_metar_local(cm["icao"], cm["tz"])
        if m is None or m.empty:
            continue
        m = m[m["local_date"] >= since]
        settles, rises = [], []
        for d, g in m.groupby("local_date"):
            if len(g) < 12:
                continue
            g = g.sort_values("local")
            run = g["temp_f"].cummax()
            unit = cm["unit"]
            day_max = _to_native((g["temp_f"].max() - 32) * 5 / 9, unit)
            hour_f = g["local"].dt.hour + g["local"].dt.minute / 60
            settle = next((h for h in range(10, 22)
                           if len(run[hour_f <= h])
                           and _to_native((run[hour_f <= h].iloc[-1] - 32) * 5 / 9, unit) == day_max),
                          None)
            by15 = run[hour_f <= 15]
            if settle is not None:
                settles.append(settle)
            if len(by15):
                rises.append(int(day_max > _to_native((by15.iloc[-1] - 32) * 5 / 9, unit)))
        if len(settles) >= 15:
            h50 = int(min(max(float(pd.Series(settles).median()), 12), 19))
        else:
            h50 = DEFAULT_H50
        per_city[slug] = {"h50": h50,
                          "city_rate": round(float(pd.Series(rises).mean()), 3) if len(rises) >= 15 else None,
                          "n_days": len(rises)}

    # entropy distribution at D-1 20:00 local over the window
    hist = pd.read_parquet(
        ROOT / "data" / "raw" / "polymarket" / "all_cities_price_history.parquet",
        columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"])
    hist["md"] = hist["market_date"].astype(str).str[:10]
    hist = hist[hist["md"] >= since.isoformat()]
    hist["ts"] = pd.to_datetime(hist["timestamp"], unit="s", utc=True)
    ents = []
    for (slug, md), g in hist.groupby(["city_slug", "md"]):
        cm = cities.get(slug)
        if cm is None:
            continue
        cutoff = pd.Timestamp(md, tz=cm["tz"]) - pd.Timedelta(hours=4)
        gg = g[g["ts"] <= cutoff]
        if gg["bracket_index"].nunique() < 5:
            continue
        p = gg.loc[gg.groupby("bracket_index")["ts"].idxmax()].set_index("bracket_index")["price"]
        p = p.clip(lower=0.001)
        p = p / p.sum()
        ents.append(float(-(p * np.log(p)).sum()))
    entropy_q75 = round(float(pd.Series(ents).quantile(0.75)), 4) if ents else None

    cfg = {"generated_at": datetime.now(timezone.utc).isoformat(),
           "window_days": RETUNE_WINDOW_DAYS,
           "entropy_q75": entropy_q75, "cr_cut": CR_CUT, "warm_cut": WARM_CUT,
           "cities": per_city}
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    logger.info("retune: %d cities, entropy_q75=%s -> %s", len(per_city), entropy_q75, CONFIG_PATH)
    return cfg


def load_scalp_config() -> dict:
    """Load rolling config; auto-retune when missing or stale (spec B2)."""
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        age = datetime.now(timezone.utc) - datetime.fromisoformat(cfg["generated_at"])
        if age <= timedelta(days=RETUNE_MAX_AGE_DAYS):
            return cfg
        logger.info("scalp config is %.0f days old -> auto-retune", age.days)
    else:
        logger.info("scalp config missing -> retune")
    return retune()


def market_entropy_yesterday_evening(slug: str, cm: dict, md: str) -> float | None:
    """Entropy of today's bracket prices as of D-1 20:00 local (collected candles)."""
    try:
        hist = pd.read_parquet(
            ROOT / "data" / "raw" / "polymarket" / "all_cities_price_history.parquet",
            columns=["city_slug", "market_date", "bracket_index", "timestamp", "price"],
            filters=[("city_slug", "==", slug)])
    except Exception as e:
        logger.warning("entropy read failed %s: %s", slug, e)
        return None
    hist["md"] = hist["market_date"].astype(str).str[:10]
    g = hist[hist["md"] == md]
    if g.empty:
        return None
    g = g.copy()
    g["ts"] = pd.to_datetime(g["timestamp"], unit="s", utc=True)
    cutoff = pd.Timestamp(md, tz=cm["tz"]) - pd.Timedelta(hours=4)
    g = g[g["ts"] <= cutoff]
    if g["bracket_index"].nunique() < 5:
        return None
    p = g.loc[g.groupby("bracket_index")["ts"].idxmax()].set_index("bracket_index")["price"]
    p = p.clip(lower=0.001)
    p = p / p.sum()
    return float(-(p * np.log(p)).sum())


def snapshot_forecast_for_today(slug: str, md: str) -> float | None:
    """Yesterday's ensemble day-ahead forecast for today (native units), local snapshots."""
    yday = (pd.Timestamp(md) - pd.Timedelta(days=1)).date().isoformat()
    path = ROOT / "data" / "raw" / "snapshots" / f"snapshot_{yday}.parquet"
    if not path.exists():
        return None
    try:
        s = pd.read_parquet(path, columns=["slug", "target_date", "days_ahead", "ens_mean"])
    except Exception:
        return None
    s = s[(s["slug"] == slug) & (s["days_ahead"] == 1)]
    if s.empty or pd.isna(s["ens_mean"].iloc[0]):
        return None
    return float(s["ens_mean"].iloc[0])


def compute_flag(slug: str, cm: dict, cfg: dict, md: str, bundle: dict) -> dict:
    """Abnormal-day flag v2; missing components degrade to False for their clause."""
    city = (cfg.get("cities") or {}).get(slug) or {}
    city_rate = city.get("city_rate")
    fc = snapshot_forecast_for_today(slug, md)
    yday_max = bundle.get("yday_max_nat")
    fc_warm = (fc - yday_max) if fc is not None and yday_max is not None else None
    lag1 = bundle.get("yday_rise")
    entropy = None
    ent_q75 = cfg.get("entropy_q75")
    if lag1 == 1 and ent_q75 is not None:  # entropy only matters for this clause
        entropy = market_entropy_yesterday_evening(slug, cm, md)
    c1 = city_rate is not None and city_rate >= cfg.get("cr_cut", CR_CUT)
    c2 = fc_warm is not None and fc_warm >= cfg.get("warm_cut", WARM_CUT)
    c3 = (lag1 == 1 and entropy is not None and ent_q75 is not None
          and entropy >= ent_q75)
    return {"flag": bool(c1 or c2 or c3),
            "inputs": {"city_rate": city_rate, "fc_warm": fc_warm, "lag1": lag1,
                       "entropy": entropy, "clauses": [bool(c1), bool(c2), bool(c3)]}}


def select_strategy(minutes: int, h50: int) -> str | None:
    """Which window is open at `minutes` since local midnight.

    Returns "A_h50" | "A_17" | "B" | None. When h50 == 17 the two A-windows
    coincide and "A_h50" is returned (variant decided later by the flag).
    """
    if h50 * 60 <= minutes < h50 * 60 + 15:
        return "A_h50"
    if h50 != LATE_HOUR and LATE_HOUR * 60 <= minutes < LATE_HOUR * 60 + 15:
        return "A_17"
    if WINDOW_B[0] <= minutes < WINDOW_B[1]:
        return "B"
    return None


def positions(brackets: pd.DataFrame, rounded_native: float) -> tuple[pd.Series | None, pd.Series | None]:
    """(bracket containing rounded running max, bracket above it)."""
    cand = brackets[brackets["upper_nat"].notna() & (brackets["upper_nat"] >= rounded_native)]
    if cand.empty:
        # running max already in the open-top bracket
        top = brackets[brackets["upper_nat"].isna()]
        return (top.iloc[0], None) if len(top) else (None, None)
    i = cand.index[0]
    above = brackets.iloc[i + 1] if i + 1 < len(brackets) else None
    return cand.loc[i], above


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")


def rewrite_jsonl(path: Path, objs: list[dict]) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for o in objs:
            f.write(json.dumps(o, ensure_ascii=False, default=str) + "\n")
    tmp.replace(path)


def clamp_price(price: float) -> float:
    return round(min(max(float(price), 0.01), 0.99), 4)


def bought_side_touch(side: str, best_bid: float | None, best_ask: float | None) -> float | None:
    """Return the taker price for buying the target side from a YES-token book."""
    if side == "YES":
        return best_ask
    if best_bid is None:
        return None
    return clamp_price(1.0 - best_bid)


def bought_side_mid(side: str, best_bid: float | None, best_ask: float | None) -> float | None:
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2
    return clamp_price(mid if side == "YES" else 1.0 - mid)


def desired_bid_price(side: str, best_bid: float | None, best_ask: float | None) -> tuple[float, str] | None:
    """Desired passive buy price in the bought-side unit."""
    mid = bought_side_mid(side, best_bid, best_ask)
    if mid is not None:
        return mid, "mid"
    touch = bought_side_touch(side, best_bid, best_ask)
    if touch is None:
        return None
    return clamp_price(touch - LADDER_TICK), "touch_minus_1c"


def make_bid_ladder(desired_price: float) -> list[dict]:
    orders = []
    for i, stake in enumerate(LADDER_STAKES):
        orders.append({
            "level": i + 1,
            "price": clamp_price(desired_price - i * LADDER_TICK),
            "stake_target": stake,
            "filled_stake": 0.0,
            "filled_shares": 0.0,
            "status": "open",
            "last_event": None,
        })
    return orders


def sync_passive_fill_summary(trade: dict) -> None:
    orders = trade.get("bid_orders") or []
    stake = sum(float(o.get("filled_stake") or 0.0) for o in orders)
    shares = sum(float(o.get("filled_shares") or 0.0) for o in orders)
    target = sum(float(o.get("stake_target") or 0.0) for o in orders) or float(trade.get("stake") or 0.0)
    avg = stake / shares if shares > 0 else None
    trade.update({
        "fill_avg_price": avg,
        "fill_shares": shares,
        "fill_stake": stake,
        "fill_complete": stake >= target * 0.999 if target else False,
        "fill_levels_used": sum(1 for o in orders if float(o.get("filled_stake") or 0.0) > 0),
        "fills": {
            str(int(target)): {
                "avg_price": avg,
                "shares": shares,
                "stake_filled": stake,
                "complete": stake >= target * 0.999 if target else False,
            }
        },
    })


def apply_passive_bid_observation(trade: dict, book_bid: float | None, book_ask: float | None,
                                  ts_utc: str) -> tuple[list[dict], float | None]:
    """Apply one post-signal book observation to a passive bid ladder.

    Returns (events, bought-side touch). A pass fills the remaining level; an
    exact touch fills up to half of that level.
    """
    touch = bought_side_touch(trade["side"], book_bid, book_ask)
    events = []
    if touch is None:
        sync_passive_fill_summary(trade)
        return events, None

    for order in trade.get("bid_orders") or []:
        target = float(order.get("stake_target") or 0.0)
        price = float(order.get("price") or 0.0)
        before = float(order.get("filled_stake") or 0.0)
        if target <= 0 or before >= target * 0.999:
            continue

        event_type = None
        after = before
        if touch < price - PRICE_EPS:
            after = target
            event_type = "passed"
        elif abs(touch - price) <= PRICE_EPS:
            after = max(before, target / 2)
            event_type = "touched"

        if after <= before + PRICE_EPS:
            continue
        delta = after - before
        order["filled_stake"] = after
        order["filled_shares"] = float(order.get("filled_shares") or 0.0) + delta / price
        order["status"] = "filled" if after >= target * 0.999 else "partial"
        order["last_event"] = event_type
        event = {
            "ts_utc": ts_utc,
            "level": order.get("level"),
            "event": event_type,
            "price": price,
            "market_touch": touch,
            "delta_stake": round(delta, 4),
            "filled_stake": round(after, 4),
        }
        events.append(event)

    sync_passive_fill_summary(trade)
    return events, touch


def already_traded(trades: list[dict], strategy: str, slug: str, md: str) -> bool:
    """One attempt per (strategy, city, day) — except explicitly non-blocking
    skips (a flagged city waiting for its 17:00 window must retry)."""
    return any(t["strategy"] == strategy and t["city_slug"] == slug
               and t["market_date"] == md and t["status"] != "error"
               and t.get("execution_model") == PASSIVE_MODEL
               and t.get("skip_reason") not in NONBLOCKING_SKIPS
               for t in trades)


# ---------------------------------------------------------------------------
# --track
# ---------------------------------------------------------------------------

def run_track_open_orders() -> dict:
    trades = read_jsonl(TRADES_PATH)
    ts = datetime.now(timezone.utc).isoformat()
    trace = {"ts_utc": ts, "mode": "track", "checked": 0, "updated": 0,
             "filled_events": 0, "errors": []}
    changed = False

    for t in trades:
        if t.get("status") != "open" or t.get("settled"):
            continue
        if t.get("execution_model") != PASSIVE_MODEL:
            continue
        token_id = t.get("token_id")
        if not token_id:
            continue
        trace["checked"] += 1
        try:
            book = fetch_order_book(str(token_id))
        except Exception as e:
            trace["errors"].append(f"{t.get('trade_id')}: {type(e).__name__}: {e}")
            continue

        events, market_touch = apply_passive_bid_observation(
            t, book.best_bid, book.best_ask, ts)
        t["last_observed"] = {
            "ts_utc": ts,
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
            "spread": book.spread,
            "mid": book.mid,
            "market_touch": market_touch,
        }
        append_jsonl(ORDER_SNAPSHOTS_PATH, {
            "ts_utc": ts,
            "trade_id": t.get("trade_id"),
            "strategy": t.get("strategy"),
            "city_slug": t.get("city_slug"),
            "market_date": t.get("market_date"),
            "bracket_index": t.get("bracket_index"),
            "side": t.get("side"),
            "token_id": token_id,
            "desired_price": t.get("desired_price"),
            "best_bid": book.best_bid,
            "best_ask": book.best_ask,
            "spread": book.spread,
            "mid": book.mid,
            "market_touch": market_touch,
            "fill_stake": t.get("fill_stake"),
            "fill_shares": t.get("fill_shares"),
            "fill_complete": t.get("fill_complete"),
            "events": events,
        })
        trace["updated"] += 1
        trace["filled_events"] += len(events)
        changed = True
        time.sleep(BOOK_RATE_S)

    if changed:
        rewrite_jsonl(TRADES_PATH, trades)
    append_jsonl(RUNS_PATH, trace)
    return trace


# ---------------------------------------------------------------------------
# --trade
# ---------------------------------------------------------------------------

def run_trade(cities: dict, mk: pd.DataFrame, cfg: dict) -> dict:
    trades = read_jsonl(TRADES_PATH)
    trace = {"ts_utc": datetime.now(timezone.utc).isoformat(), "mode": "trade",
             "considered": [], "traded": 0, "errors": []}

    for slug, cm in cities.items():
        now_local = datetime.now(cm["tz"])
        minutes = now_local.hour * 60 + now_local.minute
        h50 = ((cfg.get("cities") or {}).get(slug) or {}).get("h50", DEFAULT_H50)
        window = select_strategy(minutes, h50)
        if window is None:
            continue
        strategy = "B_above_no" if window == "B" else "A_curmax_buy"

        md = now_local.date().isoformat()
        if already_traded(trades, strategy, slug, md):
            trace["considered"].append(f"{slug}:{strategy}:dedup")
            continue
        try:
            result = trade_city(slug, cm, mk, md, strategy, window, h50, cfg)
        except Exception as e:  # network etc. — next run retries (spec B8)
            trace["considered"].append(f"{slug}:{strategy}:error")
            trace["errors"].append(f"{slug}: {type(e).__name__}: {e}")
            continue
        append_jsonl(TRADES_PATH, result)
        trades.append(result)
        outcome = result["skip_reason"] if result["status"] == "skipped" else result["status"]
        trace["considered"].append(f"{slug}:{strategy}:{outcome}")
        if result["status"] == "open":
            trace["traded"] += 1

    append_jsonl(RUNS_PATH, trace)
    return trace


def trade_city(slug: str, cm: dict, mk: pd.DataFrame, md: str, strategy: str,
               window: str, h50: int, cfg: dict) -> dict:
    base = {
        "trade_id": uuid.uuid4().hex[:12],
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy, "city_slug": slug, "market_date": md,
        "unit": cm["unit"], "icao": cm["icao"], "stake": STAKE,
        "execution_model": PASSIVE_MODEL,
        "window": window, "h_star": h50,
        "status": "skipped", "skip_reason": None, "settled": None,
    }
    brackets = city_brackets(mk, slug, md)
    if brackets.empty:
        return {**base, "skip_reason": "no_market_metadata"}
    rm = metar_bundle(cm["icao"], cm["tz"], cm["unit"])
    if rm is None:
        return {**base, "skip_reason": "no_live_metar"}
    base.update({"run_max": rm})

    # scalp v2: flag decides which A-window is the right one for today
    if strategy == "A_curmax_buy":
        fl = compute_flag(slug, cm, cfg, md, rm)
        base.update({"flag": fl["flag"], "flag_inputs": fl["inputs"]})
        if window == "A_h50" and fl["flag"] and h50 != LATE_HOUR:
            return {**base, "skip_reason": "flagged_wait_17"}
        if window == "A_17" and not fl["flag"]:
            return {**base, "skip_reason": "clean_not_17_window"}
        base["variant"] = "late17_flagged" if fl["flag"] else "h50_clean"

    cur, above = positions(brackets, rm["rounded_native"])
    if strategy == "A_curmax_buy":
        target, side = cur, "YES"
    else:
        target, side = above, "NO"
    if target is None:
        return {**base, "skip_reason": "no_target_bracket"}

    book = fetch_order_book(str(target["clob_token_id_yes"]))
    base.update({
        "bracket_index": int(target["bracket_index"]), "question": target["question"],
        "token_id": str(target["clob_token_id_yes"]), "side": side,
        "best_bid": book.best_bid, "best_ask": book.best_ask,
        "spread": book.spread, "mid": book.mid, "book": book.to_dict(),
    })

    if strategy == "A_curmax_buy":
        if book.best_ask is None:
            return {**base, "skip_reason": "empty_ask_side"}
        if book.best_ask > MAX_ASK_A:
            return {**base, "skip_reason": f"ask_above_{MAX_ASK_A}"}
    else:
        if book.best_bid is None:
            return {**base, "skip_reason": "empty_bid_side"}
        if not (YES_BID_RANGE_B[0] <= book.best_bid <= YES_BID_RANGE_B[1]):
            return {**base, "skip_reason": "yes_bid_outside_band"}

    desired = desired_bid_price(side, book.best_bid, book.best_ask)
    if desired is None:
        return {**base, "skip_reason": "no_passive_price"}
    desired_price, desired_source = desired
    base.update({
        "status": "open",
        "desired_price": desired_price,
        "desired_price_source": desired_source,
        "bid_orders": make_bid_ladder(desired_price),
        "fill_avg_price": None,
        "fill_shares": 0.0,
        "fill_stake": 0.0,
        "fill_complete": False,
        "fill_levels_used": 0,
        "fills": {},
    })
    sync_passive_fill_summary(base)
    return base


# ---------------------------------------------------------------------------
# --settle
# ---------------------------------------------------------------------------

def run_settle(cities: dict) -> dict:
    trades = read_jsonl(TRADES_PATH)
    trace = {"ts_utc": datetime.now(timezone.utc).isoformat(), "mode": "settle",
             "settled": 0, "checked": 0, "ignored_legacy": 0, "errors": []}
    changed = False
    for t in trades:
        if t["status"] != "open" or t.get("settled"):
            continue
        if t.get("execution_model") != PASSIVE_MODEL:
            trace["ignored_legacy"] += 1
            continue
        cm = cities.get(t["city_slug"])
        if cm is None:
            continue
        day_end = datetime.fromisoformat(t["market_date"]).replace(tzinfo=cm["tz"]) + timedelta(days=1)
        if datetime.now(cm["tz"]) < day_end + timedelta(hours=SETTLE_GRACE_H):
            continue
        trace["checked"] += 1
        try:
            hist = fetch_price_history(t["token_id"], interval="max")
        except Exception as e:
            trace["errors"].append(f"{t['trade_id']}: {e}")
            continue
        if not hist:
            continue
        last_p = float(hist[-1]["p"])
        if 0.10 < last_p < 0.90:
            continue  # not yet resolved
        yes_won = last_p >= 0.90
        trade_won = yes_won if t["side"] == "YES" else not yes_won
        fill_shares = float(t.get("fill_shares") or 0.0)
        fill_stake = float(t.get("fill_stake") or 0.0)
        pnl = fill_shares * 1.0 - fill_stake if trade_won else -fill_stake
        t["settled"] = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "yes_last_price": last_p, "won": trade_won, "pnl": round(pnl, 2),
        }
        # per-stake P&L when the row carries multiple simulated fills
        for k, f in (t.get("fills") or {}).items():
            shares = float(f.get("shares") or 0.0)
            stake_filled = float(f.get("stake_filled") or 0.0)
            fp = shares * 1.0 - stake_filled if trade_won else -stake_filled
            t["settled"][f"pnl_{k}"] = round(fp, 2)
        t["status"] = "settled"
        trace["settled"] += 1
        changed = True
    if changed:
        rewrite_jsonl(TRADES_PATH, trades)
    append_jsonl(RUNS_PATH, trace)
    return trace


# ---------------------------------------------------------------------------
# --sweep
# ---------------------------------------------------------------------------

def run_sweep(cities: dict, mk: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ts = datetime.now(timezone.utc).isoformat()
    for slug, cm in cities.items():
        now_local = datetime.now(cm["tz"])
        md = now_local.date().isoformat()
        brackets = city_brackets(mk, slug, md)
        if brackets.empty:
            continue
        rm = metar_bundle(cm["icao"], cm["tz"], cm["unit"])
        if rm is None:
            continue
        cur, above = positions(brackets, rm["rounded_native"])
        fav = brackets.loc[brackets["yes_price"].idxmax()] if brackets["yes_price"].notna().any() else None
        targets = {}
        if cur is not None:
            targets["curmax"] = cur
        if above is not None:
            targets["above"] = above
        if fav is not None and all(fav["bracket_index"] != t["bracket_index"] for t in targets.values()):
            targets["favorite"] = fav
        for role, br in targets.items():
            try:
                book = fetch_order_book(str(br["clob_token_id_yes"]))
            except Exception as e:
                logger.warning("sweep book failed %s %s: %s", slug, role, e)
                continue
            fill_yes = walk_fill(book.asks, STAKE)
            fill_no = walk_fill(no_levels_from_yes_bids(book.bids), STAKE)
            rows.append({
                "ts_utc": ts, "city_slug": slug, "market_date": md, "role": role,
                "local_hour": now_local.hour + now_local.minute / 60,
                "bracket_index": int(br["bracket_index"]), "question": br["question"],
                "run_max_native": rm["rounded_native"], "n_obs": rm["n_obs"],
                "best_bid": book.best_bid, "best_ask": book.best_ask,
                "spread": book.spread, "mid": book.mid,
                "bid_depth_shares": sum(s for _, s in book.bids),
                "ask_depth_shares": sum(s for _, s in book.asks),
                "yes24_avg": fill_yes.avg_price, "yes24_complete": fill_yes.complete,
                "no24_avg": fill_no.avg_price, "no24_complete": fill_no.complete,
            })
            time.sleep(BOOK_RATE_S)
    df = pd.DataFrame(rows)
    if not df.empty:
        PAPER_DIR.mkdir(parents=True, exist_ok=True)
        if SWEEPS_PATH.exists():
            df = pd.concat([pd.read_parquet(SWEEPS_PATH), df], ignore_index=True)
        df.to_parquet(SWEEPS_PATH, index=False)
    print(f"sweep: {len(rows)} book snapshots recorded")
    return df


def main() -> None:
    log_path = ROOT / "logs" / "paper_dayof.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(log_path, encoding="utf-8")],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--trade", action="store_true")
    ap.add_argument("--settle", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--retune", action="store_true",
                    help="rebuild rolling scalp config from local data")
    args = ap.parse_args()
    if not (args.trade or args.settle or args.sweep or args.retune):
        ap.error("pick at least one of --trade / --settle / --sweep / --retune")

    if args.retune:
        retune()
    cities = load_cities()
    mk = load_markets() if (args.trade or args.sweep) else None
    if args.trade or args.settle:
        tk = run_track_open_orders()
        logger.info("track: checked=%d updated=%d fills=%d errors=%d",
                    tk["checked"], tk["updated"], tk["filled_events"], len(tk["errors"]))
    if args.trade:
        cfg = load_scalp_config()
        tr = run_trade(cities, mk, cfg)
        logger.info("trade: considered=%d traded=%d errors=%d",
                    len(tr["considered"]), tr["traded"], len(tr["errors"]))
    if args.settle:
        st = run_settle(cities)
        logger.info("settle: checked=%d settled=%d", st["checked"], st["settled"])
    if args.sweep:
        run_sweep(cities, mk)


if __name__ == "__main__":
    main()
