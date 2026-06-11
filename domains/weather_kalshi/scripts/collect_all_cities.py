"""Daily collection of Polymarket weather data with city-scoped gap-filling.

Collects market brackets and CLOB price history. Detects missing (city, date)
pairs and backfills them automatically — so a failed run yesterday is covered today.

Data files:
  - data/raw/polymarket/all_cities_markets.parquet       (bracket snapshots)
  - data/raw/polymarket/all_cities_price_history.parquet  (CLOB candles)

Usage:
    python scripts/collect_all_cities.py                 # default: 14 days back, 5 ahead
    python scripts/collect_all_cities.py --days-back 7   # scan fewer days
    python scripts/collect_all_cities.py --dry-run        # show gaps only
    python scripts/collect_all_cities.py --skip-history   # markets only (fast)
    python scripts/collect_all_cities.py --city tokyo --phase markets
    python scripts/collect_all_cities.py --phase history --days-back 14 --days-ahead 0
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.polymarket_client import build_event_slug, fetch_price_history  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = ROOT / "data" / "raw" / "polymarket"
CITIES_PATH = ROOT / "data" / "static" / "polymarket_cities.json"
MARKETS_PATH = DATA_DIR / "all_cities_markets.parquet"
HISTORY_PATH = DATA_DIR / "all_cities_price_history.parquet"

DAYS_AHEAD_DEFAULT = 5
DAYS_BACK_DEFAULT = 14
RATE_LIMIT_GAMMA = 0.15   # seconds between Gamma API calls
RATE_LIMIT_CLOB = 0.25    # seconds between CLOB API calls
ALIAS_CITY_SLUGS = {"new-york-city"}


class Phase(StrEnum):
    ALL = "all"
    MARKETS = "markets"
    HISTORY = "history"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_cities(*, include_aliases: bool = False) -> dict:
    with open(CITIES_PATH) as f:
        cities = json.load(f)
    if include_aliases:
        return cities
    return {slug: meta for slug, meta in cities.items() if slug not in ALIAS_CITY_SLUGS}


def select_cities(
    cities: dict,
    selected: list[str] | None,
) -> dict:
    """Return selected city metadata, preserving registry order."""
    if not selected:
        return cities

    unknown = [slug for slug in selected if slug not in cities]
    if unknown:
        raise SystemExit(f"Unknown city slug(s): {', '.join(sorted(unknown))}")

    wanted = set(selected)
    return {slug: meta for slug, meta in cities.items() if slug in wanted}


def load_existing(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_parquet(path)
    return pd.DataFrame()


def normalize_date(val) -> date:
    """Coerce various date-like objects to datetime.date."""
    if isinstance(val, date) and not isinstance(val, pd.Timestamp):
        return val
    if hasattr(val, "date"):
        return val.date()
    return date.fromisoformat(str(val))


def find_market_gaps(
    existing: pd.DataFrame,
    cities: dict,
    start: date,
    end: date,
) -> list[tuple[str, date]]:
    """Return (city_slug, target_date) pairs absent from existing markets."""
    if existing.empty:
        covered: set[tuple[str, date]] = set()
    else:
        covered = set()
        for _, row in existing.iterrows():
            covered.add((row["city_slug"], normalize_date(row["market_date"])))

    gaps: list[tuple[str, date]] = []
    d = start
    while d <= end:
        for slug in cities:
            if (slug, d) not in covered:
                gaps.append((slug, d))
        d += timedelta(days=1)
    return gaps


def find_history_gaps(
    markets: pd.DataFrame,
    history: pd.DataFrame,
    *,
    cities: set[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Return market rows whose price history hasn't been fetched yet."""
    if markets.empty:
        return pd.DataFrame()

    markets = filter_market_rows(markets, cities=cities, start=start, end=end)
    if markets.empty:
        return pd.DataFrame()

    if history.empty:
        return markets

    hist_keys = set()
    for _, row in history.iterrows():
        hist_keys.add((
            row["city_slug"],
            str(normalize_date(row["market_date"])),
            int(row["bracket_index"]),
        ))

    mask = []
    for _, row in markets.iterrows():
        key = (
            row["city_slug"],
            str(normalize_date(row["market_date"])),
            int(row["bracket_index"]),
        )
        mask.append(key not in hist_keys)

    return markets[mask]


def filter_market_rows(
    markets: pd.DataFrame,
    *,
    cities: set[str] | None = None,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Restrict market rows by city and market-date window."""
    if markets.empty:
        return markets

    out = markets
    if cities is not None:
        out = out[out["city_slug"].isin(cities)]
    if start is not None or end is not None:
        market_dates = out["market_date"].map(normalize_date)
        mask = pd.Series(True, index=out.index)
        if start is not None:
            mask &= market_dates >= start
        if end is not None:
            mask &= market_dates <= end
        out = out[mask]
    return out


def merge_rows(
    existing: pd.DataFrame,
    new_rows: pd.DataFrame,
    *,
    key_cols: list[str],
) -> pd.DataFrame:
    """Append rows and keep the latest row for each logical key."""
    if new_rows.empty:
        return existing
    if existing.empty:
        return new_rows
    combined = pd.concat([existing, new_rows], ignore_index=True)
    return combined.drop_duplicates(subset=key_cols, keep="last")


def split_gaps_by_date(
    gaps: list[tuple[str, date]],
    *,
    today: date,
) -> tuple[int, int]:
    """Return counts for actionable gaps and future-not-yet-published gaps."""
    past_or_today = sum(1 for _, gap_date in gaps if gap_date <= today)
    future = len(gaps) - past_or_today
    return past_or_today, future


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_event_brackets(city_slug: str, target: date) -> list[dict]:
    """Fetch bracket data for one (city, date) via Gamma API."""
    slug = build_event_slug(city_slug, target)
    try:
        r = httpx.get(
            "https://gamma-api.polymarket.com/events",
            params={"slug": slug},
            timeout=15,
        )
        r.raise_for_status()
        events = r.json()
        if not events:
            return []

        e = events[0]
        rows = []
        for i, m in enumerate(e.get("markets", [])):
            prices_raw = m.get("outcomePrices", "[]")
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw

            clob_raw = m.get("clobTokenIds", "[]")
            clob_ids = json.loads(clob_raw) if isinstance(clob_raw, str) else clob_raw

            rows.append({
                "city_slug": city_slug,
                "city_name": "",
                "market_date": target,
                "bracket_index": i,
                "question": m.get("question", ""),
                "yes_price": float(prices[0]) if prices else 0,
                "clob_token_id_yes": clob_ids[0] if clob_ids else "",
                "market_id": m.get("id", ""),
                "volume": e.get("volume", 0),
            })
        return rows
    except Exception as ex:
        logger.warning("Gamma fetch failed %s %s: %s", city_slug, target, ex)
        return []


def fetch_history_batch(
    brackets: pd.DataFrame,
    *,
    deadline: float | None = None,
    max_brackets: int | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Fetch CLOB price history for a batch of brackets."""
    new_rows = []
    n_ok = 0
    n_err = 0
    n_attempted = 0
    deadline_hit = False

    if max_brackets is not None:
        brackets = brackets.head(max_brackets)

    total = len(brackets)
    for idx, (_, row) in enumerate(brackets.iterrows()):
        if deadline is not None and time.monotonic() >= deadline:
            logger.warning("  CLOB deadline reached after %d/%d brackets", idx, total)
            deadline_hit = True
            break

        token = str(row.get("clob_token_id_yes", ""))
        if not token or len(token) < 10:
            continue

        n_attempted += 1
        candles = fetch_price_history(token, interval="max")
        time.sleep(RATE_LIMIT_CLOB)

        if candles:
            n_ok += 1
            for c in candles:
                new_rows.append({
                    "city_slug": row["city_slug"],
                    "city_name": row.get("city_name", ""),
                    "market_date": row["market_date"],
                    "bracket_index": row["bracket_index"],
                    "question": row["question"],
                    "timestamp": c["t"],
                    "price": c["p"],
                })
        else:
            n_err += 1

        if (idx + 1) % 100 == 0:
            logger.info(
                "  CLOB progress: %d/%d (%d ok, %d err, %d candles)",
                idx + 1, total, n_ok, n_err, len(new_rows),
            )

    logger.info("CLOB done: %d ok, %d errors, %d candles", n_ok, n_err, len(new_rows))

    if new_rows:
        df = pd.DataFrame(new_rows)
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        return df, {"attempted": n_attempted, "deadline_hit": deadline_hit}
    return pd.DataFrame(), {"attempted": n_attempted, "deadline_hit": deadline_hit}


def collect_city_markets(
    city_slug: str,
    city_meta: dict,
    *,
    start: date,
    end: date,
    today: date,
    existing_markets: pd.DataFrame,
    dry_run: bool,
    deadline: float | None,
) -> tuple[pd.DataFrame, dict]:
    """Fetch and save missing Gamma market rows for one city."""
    gaps = find_market_gaps(existing_markets, {city_slug: city_meta}, start, end)
    past_gaps, future_gaps = split_gaps_by_date(gaps, today=today)
    report = {
        "city": city_slug,
        "market_gaps": len(gaps),
        "market_past_gaps": past_gaps,
        "market_future_gaps": future_gaps,
        "market_rows_added": 0,
        "status": "OK" if not gaps else "NO_MARKET",
        "error": "",
    }

    if dry_run or not gaps:
        return existing_markets, report

    new_rows = []
    for idx, (_, gap_date) in enumerate(gaps):
        if deadline is not None and time.monotonic() >= deadline:
            report["status"] = "TIMEOUT"
            report["error"] = f"deadline reached after {idx}/{len(gaps)} market gaps"
            break

        rows = fetch_event_brackets(city_slug, gap_date)
        if rows:
            name = city_meta.get("name", "")
            for row in rows:
                row["city_name"] = name
            new_rows.extend(rows)
        time.sleep(RATE_LIMIT_GAMMA)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        combined = merge_rows(
            existing_markets,
            new_df,
            key_cols=["city_slug", "market_date", "bracket_index"],
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(MARKETS_PATH, index=False)
        report["market_rows_added"] = len(new_df)
        report["status"] = "OK"
        return combined, report

    return existing_markets, report


def collect_city_history(
    city_slug: str,
    *,
    start: date,
    end: date,
    markets: pd.DataFrame,
    existing_history: pd.DataFrame,
    dry_run: bool,
    backfill_all_history: bool,
    deadline: float | None,
    max_brackets: int | None,
) -> tuple[pd.DataFrame, dict]:
    """Fetch and save missing CLOB candles for one city."""
    window_start = None if backfill_all_history else start
    window_end = None if backfill_all_history else end
    to_fetch = find_history_gaps(
        markets,
        existing_history,
        cities={city_slug},
        start=window_start,
        end=window_end,
    )
    planned_attempts = min(len(to_fetch), max_brackets) if max_brackets is not None else len(to_fetch)
    report = {
        "city": city_slug,
        "history_brackets": len(to_fetch),
        "history_brackets_attempted": planned_attempts,
        "history_candles_added": 0,
        "status": "OK" if to_fetch.empty else "PENDING",
        "error": "",
    }

    if dry_run or to_fetch.empty:
        return existing_history, report

    new_history, fetch_report = fetch_history_batch(
        to_fetch,
        deadline=deadline,
        max_brackets=max_brackets,
    )
    report["history_brackets_attempted"] = fetch_report["attempted"]
    if new_history.empty:
        report["status"] = "TIMEOUT" if fetch_report["deadline_hit"] else "NO_CANDLES"
        if fetch_report["deadline_hit"]:
            report["error"] = "deadline reached before all planned CLOB brackets completed"
        return existing_history, report

    combined = merge_rows(
        existing_history,
        new_history,
        key_cols=["city_slug", "market_date", "bracket_index", "timestamp"],
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(HISTORY_PATH, index=False)
    report["history_candles_added"] = len(new_history)
    if fetch_report["deadline_hit"]:
        report["status"] = "TIMEOUT"
        report["error"] = "deadline reached before all planned CLOB brackets completed"
    elif max_brackets is not None and len(to_fetch) > max_brackets:
        report["status"] = "PARTIAL"
        report["error"] = f"limited to {max_brackets}/{len(to_fetch)} CLOB brackets"
    else:
        report["status"] = "OK"
    return combined, report


def print_gap_report(reports: list[dict], *, phase: Phase) -> None:
    """Print a compact city-level status table."""
    print(f"\n{'=' * 60}")
    print(f"City collection report ({phase})")
    for report in reports:
        if "market_gaps" in report:
            print(
                f"  {report['city']:20s} {report['status']:10s} "
                f"market_gaps={report['market_gaps']:3d} "
                f"past={report['market_past_gaps']:3d} "
                f"future={report['market_future_gaps']:3d} "
                f"rows_added={report['market_rows_added']:4d}"
                + (f" error={report['error']}" if report["error"] else "")
            )
        else:
            print(
                f"  {report['city']:20s} {report['status']:10s} "
                f"history_brackets={report['history_brackets']:4d} "
                f"attempted={report['history_brackets_attempted']:4d} "
                f"candles_added={report['history_candles_added']:6d}"
                + (f" error={report['error']}" if report["error"] else "")
            )
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Collect all-cities Polymarket weather data")
    parser.add_argument("--days-back", type=int, default=DAYS_BACK_DEFAULT)
    parser.add_argument("--days-ahead", type=int, default=DAYS_AHEAD_DEFAULT)
    parser.add_argument(
        "--city",
        action="append",
        help="Restrict to one city slug. Can be supplied more than once.",
    )
    parser.add_argument(
        "--phase",
        choices=[phase.value for phase in Phase],
        default=Phase.ALL.value,
        help="Collect markets, CLOB history, or both.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show gaps only")
    parser.add_argument("--skip-history", action="store_true", help="Markets only")
    parser.add_argument(
        "--include-aliases",
        action="store_true",
        help="Include alias slugs such as new-york-city. Default skips aliases.",
    )
    parser.add_argument(
        "--backfill-all-history",
        action="store_true",
        help="Fetch every missing CLOB history row, not just the requested date window.",
    )
    parser.add_argument(
        "--max-city-seconds",
        type=int,
        default=0,
        help="Best-effort per-city deadline in seconds. 0 disables the deadline.",
    )
    parser.add_argument(
        "--max-history-brackets-per-city",
        type=int,
        default=0,
        help="Limit CLOB brackets fetched per city in this run. 0 means unlimited.",
    )
    args = parser.parse_args()

    phase = Phase.MARKETS if args.skip_history else Phase(args.phase)
    cities = select_cities(
        load_cities(include_aliases=args.include_aliases),
        args.city,
    )
    today = date.today()
    start = today - timedelta(days=args.days_back)
    end = today + timedelta(days=args.days_ahead)

    n_slots = (end - start).days * len(cities) + len(cities)
    logger.info("%d cities, %s to %s (%d date-city slots)", len(cities), start, end, n_slots)

    # ---- Phase 1: Markets ----
    combined = load_existing(MARKETS_PATH)
    market_reports: list[dict] = []
    if phase in {Phase.ALL, Phase.MARKETS}:
        gaps = find_market_gaps(combined, cities, start, end)
        logger.info("Existing markets: %d rows. Gaps: %d", len(combined), len(gaps))

        for city_slug, city_meta in cities.items():
            deadline = (
                time.monotonic() + args.max_city_seconds
                if args.max_city_seconds > 0
                else None
            )
            combined, report = collect_city_markets(
                city_slug,
                city_meta,
                start=start,
                end=end,
                today=today,
                existing_markets=combined,
                dry_run=args.dry_run,
                deadline=deadline,
            )
            market_reports.append(report)

    # ---- Phase 2: Price History ----
    if phase == Phase.MARKETS:
        logger.info("Skipping price history")
        print_gap_report(market_reports, phase=phase)
        _print_summary()
        return

    existing_history = load_existing(HISTORY_PATH)
    history_reports: list[dict] = []
    window_start = None if args.backfill_all_history else start
    window_end = None if args.backfill_all_history else end
    to_fetch = find_history_gaps(
        combined,
        existing_history,
        cities=set(cities),
        start=window_start,
        end=window_end,
    )
    logger.info("History: %d existing rows. To fetch: %d brackets", len(existing_history), len(to_fetch))

    for city_slug in cities:
        deadline = (
            time.monotonic() + args.max_city_seconds
            if args.max_city_seconds > 0
            else None
        )
        existing_history, report = collect_city_history(
            city_slug,
            start=start,
            end=end,
            markets=combined,
            existing_history=existing_history,
            dry_run=args.dry_run,
            backfill_all_history=args.backfill_all_history,
            deadline=deadline,
            max_brackets=(
                args.max_history_brackets_per_city
                if args.max_history_brackets_per_city > 0
                else None
            )
        )
        history_reports.append(report)

    if market_reports:
        print_gap_report(market_reports, phase=Phase.MARKETS)
    print_gap_report(history_reports, phase=Phase.HISTORY)
    _print_summary()


def _print_summary() -> None:
    print(f"\n{'='*60}")
    print("Collection complete")
    if MARKETS_PATH.exists():
        m = pd.read_parquet(MARKETS_PATH)
        print(f"  Markets: {len(m)} rows, {m['city_slug'].nunique()} cities")
        print(f"  Dates: {m['market_date'].min()} to {m['market_date'].max()}")
    if HISTORY_PATH.exists():
        h = pd.read_parquet(HISTORY_PATH)
        print(f"  Price history: {len(h)} candles")
        print(f"  Range: {h['datetime'].min()} to {h['datetime'].max()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
