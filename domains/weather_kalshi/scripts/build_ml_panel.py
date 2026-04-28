"""Build the unified ML training panel from forecasts + markets + outcomes.

Joins three data products into one row-per-bracket parquet ready for ML:
  - Forecasts: data/raw/snapshots/snapshot_*.parquet
  - Markets:   data/raw/polymarket/all_cities_markets.parquet
  - History:   data/raw/polymarket/all_cities_price_history.parquet
  - Observed:  data/raw/observed/obs_*.parquet

Output: data/processed/ml_panel.parquet
  Primary key: (slug, target_date, bracket_index)
  Includes forecast features (NBM/ensemble), market features (open/close/volume),
  realized outcome (observed temp + which bracket it landed in), and the binary
  label `realized_in_bracket` (1 if observed temp fell in this bracket).

Schema is one-row-per-bracket so ML can learn per-bracket pricing skill.
For per-snapshot intraday training, build a complementary panel later
(see ml_intraday_panel.parquet — TODO).

Usage
-----
    python -m scripts.build_ml_panel
    python -m scripts.build_ml_panel --since 2026-04-01
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.cities import CITIES, City
from src.stations import STATIONS

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SNAPSHOT_DIR = ROOT / "data" / "raw" / "snapshots"
OBSERVED_DIR = ROOT / "data" / "raw" / "observed"
METAR_DIR = ROOT / "data" / "raw" / "metar"
TAF_DIR = ROOT / "data" / "raw" / "taf"
HRRR_DIR = ROOT / "data" / "raw" / "hrrr"
ICAO_MAP_PATH = ROOT / "data" / "static" / "icao_map.json"
MARKETS_PATH = ROOT / "data" / "raw" / "polymarket" / "all_cities_markets.parquet"
HISTORY_PATH = ROOT / "data" / "raw" / "polymarket" / "all_cities_price_history.parquet"
OUTPUT_PATH = ROOT / "data" / "processed" / "ml_panel.parquet"

# ICAO -> polymarket slug (for legacy snapshot rows that used station col)
ICAO_TO_SLUG = {
    s.icao: s.polymarket_city_slug
    for s in STATIONS.values()
    if s.polymarket_city_slug
}

# Lazy-loaded slug -> ICAO map (set on first call)
_ICAO_MAP: dict[str, dict] | None = None
US_ICAOS_FOR_HRRR = {s.icao for s in STATIONS.values() if s.polymarket_city_slug}


def _load_icao_map() -> dict[str, dict]:
    global _ICAO_MAP
    if _ICAO_MAP is None:
        if ICAO_MAP_PATH.exists():
            import json
            with open(ICAO_MAP_PATH) as f:
                _ICAO_MAP = json.load(f)
        else:
            _ICAO_MAP = {}
    return _ICAO_MAP


def _slug_to_icao(slug: str) -> str | None:
    m = _load_icao_map()
    if slug in m:
        return m[slug]["primary"]
    return None


# ---------------------------------------------------------------------------
# Bracket parsing
# ---------------------------------------------------------------------------

# Match patterns like "43°F or below", "70-71°F", "between 44 and 45°F",
# "70°F or above". Polymarket questions use the °F glyph (or sometimes a
# replacement char if encoding mangled).
RE_LOWER_TAIL = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°�]?\s*F\s+or\s+(?:below|lower)",
    re.IGNORECASE,
)
RE_UPPER_TAIL = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°�]?\s*F\s+or\s+(?:above|higher)",
    re.IGNORECASE,
)
RE_RANGE = re.compile(
    r"between\s+(-?\d+(?:\.\d+)?)\s*-?\s*(-?\d+(?:\.\d+)?)\s*[°�]?\s*F",
    re.IGNORECASE,
)
RE_RANGE_C = re.compile(
    r"between\s+(-?\d+(?:\.\d+)?)\s*-?\s*(-?\d+(?:\.\d+)?)\s*[°�]?\s*C",
    re.IGNORECASE,
)
RE_LOWER_TAIL_C = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°�]?\s*C\s+or\s+(?:below|lower)",
    re.IGNORECASE,
)
RE_UPPER_TAIL_C = re.compile(
    r"(-?\d+(?:\.\d+)?)\s*[°�]?\s*C\s+or\s+(?:above|higher)",
    re.IGNORECASE,
)
# Single-integer bracket: "be 14°C on April 14"
RE_SINGLE_C = re.compile(r"\bbe\s+(-?\d+(?:\.\d+)?)\s*[°�]?\s*C\s+on\s", re.IGNORECASE)
RE_SINGLE_F = re.compile(r"\bbe\s+(-?\d+(?:\.\d+)?)\s*[°�]?\s*F\s+on\s", re.IGNORECASE)


def parse_bracket(question: str) -> tuple[float | None, float | None, str]:
    """Parse bracket bounds from question text.

    Returns (lower, upper, unit) where None denotes open bound.
    unit is "F" or "C". Returns (None, None, "?") if unparseable.
    """
    q = question or ""
    if "°F" in q or "F " in q or q.endswith("F?") or q.endswith("F."):
        unit = "F"
    elif "°C" in q or "C " in q or q.endswith("C?") or q.endswith("C."):
        unit = "C"
    else:
        unit = "F"  # default for US-style markets

    if unit == "F":
        m = RE_LOWER_TAIL.search(q)
        if m:
            return None, float(m.group(1)), "F"
        m = RE_UPPER_TAIL.search(q)
        if m:
            return float(m.group(1)), None, "F"
        m = RE_RANGE.search(q)
        if m:
            return float(m.group(1)), float(m.group(2)), "F"
        m = RE_SINGLE_F.search(q)
        if m:
            n = float(m.group(1))
            return n, n + 0.999, "F"
    else:
        m = RE_LOWER_TAIL_C.search(q)
        if m:
            return None, float(m.group(1)), "C"
        m = RE_UPPER_TAIL_C.search(q)
        if m:
            return float(m.group(1)), None, "C"
        m = RE_RANGE_C.search(q)
        if m:
            return float(m.group(1)), float(m.group(2)), "C"
        m = RE_SINGLE_C.search(q)
        if m:
            n = float(m.group(1))
            return n, n + 0.999, "C"

    return None, None, unit


def temp_in_bracket(temp_native: float | None, lower: float | None, upper: float | None) -> bool:
    """Half-open match used by Polymarket: lower ≤ T ≤ upper, with open tails."""
    if temp_native is None or pd.isna(temp_native):
        return False
    if lower is not None and temp_native < lower:
        return False
    if upper is not None and temp_native > upper:
        return False
    return True


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def normalize_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize legacy `station` schema to canonical `slug` schema.

    Old snapshots used `station` with ICAO codes for US cities and tz-naive
    timestamps; new snapshots use `slug` and tz-aware timestamps.
    """
    df = df.copy()

    if "snapshot_time" in df.columns:
        ts = pd.to_datetime(df["snapshot_time"], errors="coerce", utc=True)
        df["snapshot_time"] = ts

    if "slug" not in df.columns or df["slug"].isna().all():
        if "station" not in df.columns:
            return df.iloc[0:0]
        df["slug"] = df["station"].map(
            lambda s: ICAO_TO_SLUG.get(s, s) if isinstance(s, str) else s
        )

    return df


def load_snapshots(since: date | None = None) -> pd.DataFrame:
    """Load and concat all daily snapshot files."""
    files = sorted(SNAPSHOT_DIR.glob("snapshot_*.parquet"))
    if since:
        cutoff = since.isoformat()
        files = [f for f in files if f.stem.split("_", 1)[1] >= cutoff]

    if not files:
        return pd.DataFrame()

    parts = []
    for f in files:
        try:
            part = pd.read_parquet(f)
            part = normalize_snapshot(part)
            if part.empty:
                continue
            parts.append(part)
        except Exception as e:
            logger.warning("Failed to read %s: %s", f.name, e)

    if not parts:
        return pd.DataFrame()

    df = pd.concat(parts, ignore_index=True)
    df = df.dropna(subset=["slug", "target_date"])
    df["target_date"] = pd.to_datetime(df["target_date"]).dt.date
    return df


def load_observed(since: date | None = None) -> pd.DataFrame:
    """Concat all per-city observed parquets."""
    files = sorted(OBSERVED_DIR.glob("obs_*.parquet"))
    if not files:
        return pd.DataFrame()

    parts = []
    for f in files:
        try:
            parts.append(pd.read_parquet(f))
        except Exception as e:
            logger.warning("Failed to read %s: %s", f.name, e)

    if not parts:
        return pd.DataFrame()

    df = pd.concat(parts, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    if since:
        df = df[df["date"] >= since]
    return df


def load_markets() -> pd.DataFrame:
    if not MARKETS_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(MARKETS_PATH)
    df["market_date"] = pd.to_datetime(df["market_date"]).dt.date
    return df


def load_history() -> pd.DataFrame:
    if not HISTORY_PATH.exists():
        return pd.DataFrame()
    df = pd.read_parquet(HISTORY_PATH)
    df["market_date"] = pd.to_datetime(df["market_date"]).dt.date
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def latest_snapshot_per_target(snap: pd.DataFrame) -> pd.DataFrame:
    """For each (slug, target_date, days_ahead), take the latest snapshot row."""
    if snap.empty:
        return snap
    if "snapshot_time" in snap.columns:
        snap = snap.sort_values("snapshot_time")
    return snap.drop_duplicates(
        subset=["slug", "target_date", "days_ahead"], keep="last",
    )


def aggregate_history(hist: pd.DataFrame) -> pd.DataFrame:
    """Aggregate intraday CLOB candles into per-bracket OHLC stats.

    Closing price = last candle on or before midnight UTC of target_date+1
    (rough proxy for end-of-market). Open price = first candle.
    """
    if hist.empty:
        return pd.DataFrame()

    hist = hist.copy()
    hist = hist.sort_values("datetime")

    # Filter candles to those before market settlement (end of target_date)
    end_ts = pd.to_datetime(hist["market_date"]) + pd.Timedelta(days=1)
    hist = hist[hist["datetime"] <= end_ts]

    grouped = hist.groupby(
        ["city_slug", "market_date", "bracket_index"], as_index=False,
    )
    agg = grouped["price"].agg(
        pm_open=("first"),
        pm_close=("last"),
        pm_min=("min"),
        pm_max=("max"),
        pm_n_candles=("count"),
    )
    return agg


def model_prob_in_bracket(
    row: pd.Series,
    lower_f: float | None,
    upper_f: float | None,
) -> float | None:
    """Model-implied probability that observed_max falls in the bracket.

    Uses NBM percentiles when available (linear interpolation on the empirical
    CDF); falls back to ensemble member array when only that is present.
    Returns None when neither source has data.
    """
    pcts = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    nbm_vals = [row.get(f"nbm_p{p}") for p in pcts]
    if all(pd.notna(v) for v in nbm_vals):
        return _prob_from_percentiles(pcts, nbm_vals, lower_f, upper_f)

    # Fallback: ensemble members from multimodel_members_json (intl cities)
    members_json = row.get("multimodel_members_json")
    if isinstance(members_json, str) and members_json:
        try:
            import json
            members = json.loads(members_json)
            members_f = _members_to_f(members, row.get("slug"))
            if members_f:
                return _prob_from_members(members_f, lower_f, upper_f)
        except (ValueError, TypeError):
            pass

    return None


def _prob_from_percentiles(
    pcts: list[int],
    vals: list[float],
    lower: float | None,
    upper: float | None,
) -> float:
    """Compute P(lower ≤ T ≤ upper) from percentile points via linear CDF."""
    cdf_x = list(vals)
    cdf_y = [p / 100.0 for p in pcts]

    def cdf_at(x: float | None) -> float:
        if x is None:
            return 0.0 if cdf_x[0] > -1e9 else 0.0
        if x <= cdf_x[0]:
            return 0.0
        if x >= cdf_x[-1]:
            return 1.0
        return float(np.interp(x, cdf_x, cdf_y))

    p_lo = cdf_at(lower) if lower is not None else 0.0
    p_hi = cdf_at(upper) if upper is not None else 1.0
    return max(0.0, p_hi - p_lo)


def _members_to_f(members: list[float], slug) -> list[float]:
    if not isinstance(slug, str) or slug not in CITIES:
        return [float(m) for m in members]
    city = CITIES[slug]
    if city.unit == "C":
        return [float(m) * 9.0 / 5.0 + 32.0 for m in members]
    return [float(m) for m in members]


def _prob_from_members(members_f: list[float], lower: float | None, upper: float | None) -> float:
    arr = np.array(members_f)
    n = len(arr)
    if n == 0:
        return 0.0
    in_bracket = arr.copy()
    if lower is not None:
        in_bracket = in_bracket[in_bracket >= lower]
    if upper is not None:
        in_bracket = in_bracket[in_bracket <= upper]
    return float(len(in_bracket) / n)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Aviation feature aggregators (METAR + TAF + HRRR)
# ---------------------------------------------------------------------------

def _local_date_window(target_date: date, tz: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return [start, end) UTC bounds covering target_date in city timezone."""
    zone = ZoneInfo(tz)
    start_local = pd.Timestamp(target_date, tz=zone)
    end_local = start_local + pd.Timedelta(days=1)
    return start_local.tz_convert("UTC"), end_local.tz_convert("UTC")


def _temp_at_local_hour(
    df_local: pd.DataFrame, target_date: date, hour_local: int, tol_min: int = 45,
) -> float | None:
    """Pick METAR temp_f closest to (target_date, hour_local) within tolerance."""
    if df_local.empty:
        return None
    target = pd.Timestamp(target_date, tz=df_local["local_dt"].dt.tz) \
        + pd.Timedelta(hours=hour_local)
    diff = (df_local["local_dt"] - target).abs()
    idx = diff.idxmin()
    if diff.loc[idx] > pd.Timedelta(minutes=tol_min):
        return None
    val = df_local.loc[idx, "temp_f"]
    return float(val) if pd.notna(val) else None


def aggregate_metar(slug: str, target_date: date, city: City) -> dict:
    nan_dict = {
        "metar_max_temp_f": None,
        "metar_temp_at_12local_f": None,
        "metar_temp_at_15local_f": None,
        "metar_temp_at_18local_f": None,
        "metar_n_obs": 0,
        "metar_max_t_6h_f": None,
    }
    icao = _slug_to_icao(slug)
    if not icao:
        return nan_dict
    path = METAR_DIR / f"metar_{icao}.parquet"
    if not path.exists():
        return nan_dict

    df = pd.read_parquet(path)
    if df.empty:
        return nan_dict

    df = df.copy()
    df["valid_time_utc"] = pd.to_datetime(df["valid_time_utc"], utc=True)
    start_utc, end_utc = _local_date_window(target_date, city.timezone)
    mask = (df["valid_time_utc"] >= start_utc) & (df["valid_time_utc"] < end_utc)
    sub = df[mask].copy()
    if sub.empty:
        return nan_dict

    sub["local_dt"] = sub["valid_time_utc"].dt.tz_convert(ZoneInfo(city.timezone))

    return {
        "metar_max_temp_f": float(sub["temp_f"].max()) if sub["temp_f"].notna().any() else None,
        "metar_temp_at_12local_f": _temp_at_local_hour(sub, target_date, 12),
        "metar_temp_at_15local_f": _temp_at_local_hour(sub, target_date, 15),
        "metar_temp_at_18local_f": _temp_at_local_hour(sub, target_date, 18),
        "metar_n_obs": int(len(sub)),
        "metar_max_t_6h_f": (
            float(sub["max_t_6h_f"].max()) if sub["max_t_6h_f"].notna().any() else None
        ),
    }


def aggregate_taf(slug: str, target_date: date, city: City) -> dict:
    nan_dict = {
        "taf_max_temp_f": None,
        "taf_min_temp_f": None,
        "taf_issue_time_utc": None,
        "taf_temp_groups_present": False,
    }
    icao = _slug_to_icao(slug)
    if not icao:
        return nan_dict
    path = TAF_DIR / f"taf_{icao}.parquet"
    if not path.exists():
        return nan_dict

    df = pd.read_parquet(path)
    if df.empty:
        return nan_dict

    df = df.copy()
    df["issue_time_utc"] = pd.to_datetime(df["issue_time_utc"], utc=True)
    _, end_utc = _local_date_window(target_date, city.timezone)
    sub = df[df["issue_time_utc"] <= end_utc].sort_values("issue_time_utc")
    if sub.empty:
        return nan_dict

    last = sub.iloc[-1]
    issue_iso = last["issue_time_utc"].isoformat()
    if not last.get("temp_groups_present", False):
        return {**nan_dict, "taf_issue_time_utc": issue_iso}

    import json
    try:
        periods = json.loads(last.get("periods_json") or "[]")
    except (ValueError, TypeError):
        periods = []
    start_utc, end_utc = _local_date_window(target_date, city.timezone)
    temps_c: list[float] = []
    for period in periods:
        for entry in period.get("temp") or []:
            valid_iso = entry.get("validTime")
            sfc = entry.get("sfcTemp")
            if valid_iso is None or sfc is None:
                continue
            try:
                ts = pd.to_datetime(valid_iso, utc=True)
            except (ValueError, TypeError):
                continue
            if start_utc <= ts < end_utc:
                temps_c.append(float(sfc))
    if not temps_c:
        return {**nan_dict, "taf_issue_time_utc": issue_iso, "taf_temp_groups_present": True}

    return {
        "taf_max_temp_f": max(temps_c) * 9.0 / 5.0 + 32.0,
        "taf_min_temp_f": min(temps_c) * 9.0 / 5.0 + 32.0,
        "taf_issue_time_utc": issue_iso,
        "taf_temp_groups_present": True,
    }


def aggregate_hrrr(slug: str, target_date: date, city: City) -> dict:
    nan_dict = {
        "hrrr_max_temp_forecast_f": None,
        "hrrr_run_time_utc": None,
        "hrrr_n_forecasts": 0,
    }
    icao = _slug_to_icao(slug)
    if not icao or icao not in US_ICAOS_FOR_HRRR:
        return nan_dict
    path = HRRR_DIR / f"hrrr_{icao}.parquet"
    if not path.exists():
        return nan_dict

    df = pd.read_parquet(path)
    if df.empty:
        return nan_dict

    df = df.copy()
    df["run_time_utc"] = pd.to_datetime(df["run_time_utc"], utc=True)
    df["valid_time_utc"] = pd.to_datetime(df["valid_time_utc"], utc=True)
    start_utc, end_utc = _local_date_window(target_date, city.timezone)

    in_range = df[(df["valid_time_utc"] >= start_utc) & (df["valid_time_utc"] < end_utc)]
    if in_range.empty:
        return nan_dict

    latest_run = in_range["run_time_utc"].max()
    sub = in_range[in_range["run_time_utc"] == latest_run]
    if sub.empty or sub["temp_2m_f"].isna().all():
        return nan_dict

    return {
        "hrrr_max_temp_forecast_f": float(sub["temp_2m_f"].max()),
        "hrrr_run_time_utc": latest_run.isoformat(),
        "hrrr_n_forecasts": int(len(sub)),
    }


def add_aviation_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute aviation features per (slug, target_date) and merge into panel."""
    if panel.empty:
        return panel

    pairs = panel[["slug", "target_date"]].drop_duplicates()
    rows = []
    for _, row in pairs.iterrows():
        slug = row["slug"]
        target = row["target_date"]
        if not isinstance(slug, str) or slug not in CITIES:
            rows.append({"slug": slug, "target_date": target})
            continue
        city = CITIES[slug]
        feat = {"slug": slug, "target_date": target}
        feat.update(aggregate_metar(slug, target, city))
        feat.update(aggregate_taf(slug, target, city))
        feat.update(aggregate_hrrr(slug, target, city))
        rows.append(feat)

    feat_df = pd.DataFrame(rows)
    return panel.merge(feat_df, on=["slug", "target_date"], how="left")


def build_panel(since: date | None = None) -> pd.DataFrame:
    logger.info("Loading data sources (since=%s)...", since)
    snap = load_snapshots(since)
    obs = load_observed(since)
    markets = load_markets()
    hist = load_history()

    if since:
        markets = markets[markets["market_date"] >= since]

    logger.info(
        "Sources: snapshots=%d rows, observed=%d rows, markets=%d rows, history=%d candles",
        len(snap), len(obs), len(markets), len(hist),
    )

    if markets.empty:
        logger.error("No markets data available; cannot build panel")
        return pd.DataFrame()

    snap = latest_snapshot_per_target(snap)
    history_agg = aggregate_history(hist)

    # Parse brackets from question text
    parsed = markets.apply(
        lambda r: parse_bracket(r.get("question") or ""), axis=1, result_type="expand",
    )
    parsed.columns = ["bracket_lower", "bracket_upper", "bracket_unit"]
    panel = pd.concat([markets.reset_index(drop=True), parsed.reset_index(drop=True)], axis=1)

    panel = panel.rename(columns={
        "city_slug": "slug",
        "market_date": "target_date",
        "yes_price": "snapshot_yes_price",
    })

    # Convert bracket bounds to Fahrenheit for joining with NBM (always F)
    def to_f(val, unit):
        if val is None or pd.isna(val):
            return None
        if unit == "C":
            return float(val) * 9.0 / 5.0 + 32.0
        return float(val)

    panel["bracket_lower_f"] = panel.apply(
        lambda r: to_f(r["bracket_lower"], r["bracket_unit"]), axis=1,
    )
    panel["bracket_upper_f"] = panel.apply(
        lambda r: to_f(r["bracket_upper"], r["bracket_unit"]), axis=1,
    )

    # Join history aggregates
    if not history_agg.empty:
        history_agg = history_agg.rename(columns={
            "city_slug": "slug", "market_date": "target_date",
        })
        panel = panel.merge(
            history_agg, on=["slug", "target_date", "bracket_index"], how="left",
        )

    # Join observed (only attach final outcome — keep observed unit native)
    if not obs.empty:
        obs_keep = obs[[
            "slug", "date", "temp_max_native", "temp_min_native",
            "temp_max_f", "temp_min_f", "unit", "source",
        ]].rename(columns={"date": "target_date"})
        panel = panel.merge(obs_keep, on=["slug", "target_date"], how="left")
    else:
        for col in ["temp_max_native", "temp_min_native", "temp_max_f", "temp_min_f", "unit", "source"]:
            panel[col] = None

    # Realized bracket flag (uses native unit since brackets are in native unit)
    def realized_in(row):
        target = row.get("temp_max_native")
        return bool(temp_in_bracket(target, row["bracket_lower"], row["bracket_upper"]))

    panel["realized_in_bracket"] = panel.apply(realized_in, axis=1).astype(int)
    panel["realized_known"] = panel["temp_max_native"].notna().astype(int)

    # Join the latest D+0 snapshot per (slug, target_date) for forecast features
    if not snap.empty:
        snap_d0 = snap[snap["days_ahead"] == 0].copy()
        forecast_cols = [c for c in snap_d0.columns
                         if c.startswith(("nbm_", "ens_", "multimodel_"))]
        keep = ["slug", "target_date", "snapshot_time"] + forecast_cols
        snap_d0 = snap_d0[keep]
        panel = panel.merge(snap_d0, on=["slug", "target_date"], how="left")

    # ---- Aviation features (METAR + TAF + HRRR) ----
    panel = add_aviation_features(panel)

    # Model probability per bracket
    panel["model_prob_in_bracket"] = panel.apply(
        lambda r: model_prob_in_bracket(r, r["bracket_lower_f"], r["bracket_upper_f"]),
        axis=1,
    )

    # Edge proxy: model prob - market closing price (positive = model says undervalued)
    panel["edge_close"] = panel["model_prob_in_bracket"] - panel["pm_close"]
    panel["edge_open"] = panel["model_prob_in_bracket"] - panel["pm_open"]

    panel["built_at"] = datetime.now(timezone.utc)
    return panel


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ML training panel")
    parser.add_argument("--since", type=date.fromisoformat, default=None,
                        help="Earliest target_date to include")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    panel = build_panel(args.since)
    if panel.empty:
        logger.error("Empty panel; nothing written")
        sys.exit(1)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(args.output, index=False)

    settled = panel[panel["realized_known"] == 1]
    print(f"\n{'=' * 60}")
    print(f"ML panel built: {args.output}")
    print(f"  Total rows:           {len(panel)}")
    print(f"  Cities:               {panel['slug'].nunique()}")
    print(f"  Date range:           {panel['target_date'].min()} -> {panel['target_date'].max()}")
    print(f"  Brackets w/ outcome:  {len(settled)} ({100*len(settled)/max(1,len(panel)):.1f}%)")
    print(f"  Brackets w/ pm close: {panel['pm_close'].notna().sum()}")
    print(f"  Brackets w/ NBM:      {panel.filter(like='nbm_p50').notna().sum().sum()}")
    print(f"  Brackets w/ ens:      {panel['ens_mean'].notna().sum() if 'ens_mean' in panel else 0}")
    if not settled.empty:
        hits = settled["realized_in_bracket"].sum()
        print(f"  Sanity: {hits} of {settled['target_date'].nunique() * settled['slug'].nunique()} (city,date) pairs have exactly-one realized bracket")
        edges = settled.dropna(subset=["edge_close"])
        if not edges.empty:
            print(f"  Edge stats (model_prob - pm_close): "
                  f"mean={edges['edge_close'].mean():.3f}, "
                  f"std={edges['edge_close'].std():.3f}, "
                  f"|edge|>0.10: {(edges['edge_close'].abs() > 0.10).sum()}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
