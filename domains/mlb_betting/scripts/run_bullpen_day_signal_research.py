"""Run the early bullpen-day research + scanner pipeline.

Default behavior:
  * capture ESPN probable-pitcher snapshots for today + tomorrow
  * best-effort capture of Fangraphs Probables Grid
  * build live scanner rows for today + tomorrow
  * build historical ESPN-only research rows and Markdown report
  * build Polymarket event-opening table for today + tomorrow
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.fetch_2026.io_safety import safe_write_parquet
from src.bullpen_day_signals import (
    ESPN_SNAPSHOT_PATH,
    HISTORICAL_REPORT_PATH,
    HISTORICAL_ROWS_PATH,
    LIVE_SCANNER_PATH,
    PROCESSED_DIR,
    build_live_scanner_rows,
    build_pitcher_role_rows,
    fetch_and_save_espn_probables_snapshot,
    load_game_label_frame,
    load_historical_espn_probables_from_pregame_dir,
    persist_scanner_and_report,
    select_latest_snapshot_rows,
)
from src.fangraphs_probables import (
    PROCESSED_PATH as FANGRAPHS_SNAPSHOT_PATH,
)
from src.fangraphs_probables import (
    fetch_fangraphs_html,
    parse_fangraphs_probables_html,
    persist_fangraphs_rows,
    save_raw_fangraphs_snapshot,
)
from src.polymarket_client import (
    build_event_openings_df,
    fetch_upcoming_games,
)

logger = logging.getLogger(__name__)

POLY_EVENT_OPENINGS_PATH = PROCESSED_DIR / "polymarket_event_openings.parquet"
SAVED_POLY_PATH = Path(__file__).resolve().parent.parent / "data" / "raw" / "polymarket" / "polymarket_mlb.parquet"


def _target_dates(start_date: date, horizon_days: int) -> list[date]:
    return [start_date + timedelta(days=offset) for offset in range(horizon_days)]


def _load_parquet_if_exists(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def _capture_fangraphs_rows(
    *,
    html_path: Path | None,
    skip_fetch: bool,
    wanted_dates: set[date],
) -> pd.DataFrame:
    captured_at = datetime.now(UTC)
    html = ""

    if html_path is not None:
        html = html_path.read_text(encoding="utf-8")
        logger.info("Using manual Fangraphs HTML snapshot: %s", html_path)
    elif not skip_fetch:
        try:
            html = fetch_fangraphs_html()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fangraphs fetch unavailable: %s", exc)
            return pd.DataFrame()
    else:
        return pd.DataFrame()

    try:
        rows = parse_fangraphs_probables_html(html, captured_at=captured_at)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse Fangraphs Probables Grid: %s", exc)
        return pd.DataFrame()

    save_raw_fangraphs_snapshot(html, captured_at=captured_at)
    persist_fangraphs_rows(rows)
    rows["target_date"] = pd.to_datetime(rows["target_date"])
    return rows[rows["target_date"].dt.date.isin(wanted_dates)].copy()


def _fallback_polymarket_openings(
    *,
    start_date: date,
    horizon_days: int,
) -> pd.DataFrame:
    if not SAVED_POLY_PATH.exists():
        return pd.DataFrame()

    saved = pd.read_parquet(SAVED_POLY_PATH)
    if saved.empty or "event_date" not in saved.columns:
        return pd.DataFrame()

    saved["event_date"] = pd.to_datetime(saved["event_date"])
    date_min = pd.Timestamp(start_date)
    date_max = pd.Timestamp(start_date + timedelta(days=horizon_days - 1))
    saved = saved[(saved["event_date"] >= date_min) & (saved["event_date"] <= date_max)].copy()
    if saved.empty:
        return pd.DataFrame()

    grouped = (
        saved.groupby(["event_date", "away_team", "home_team", "slug"], dropna=False)
        .agg(
            game_time=("game_time", "first"),
            market_count=("market_type", "size"),
            is_active=("closed", lambda s: not bool(pd.Series(s).all())),
        )
        .reset_index()
    )
    grouped["market_opened_at"] = pd.NaT
    grouped["event_date"] = pd.to_datetime(grouped["event_date"]).dt.date
    has_today_market = bool((grouped["event_date"] == start_date).any())
    has_tomorrow_market = bool((grouped["event_date"] == (start_date + timedelta(days=1))).any())
    grouped["has_today_market"] = has_today_market
    grouped["has_tomorrow_market"] = has_tomorrow_market
    return grouped[
        [
            "event_date",
            "away_team",
            "home_team",
            "market_opened_at",
            "game_time",
            "slug",
            "market_count",
            "is_active",
            "has_today_market",
            "has_tomorrow_market",
        ]
    ].copy()


def _build_and_save_polymarket_openings(
    *,
    start_date: date,
    horizon_days: int,
) -> Path | None:
    try:
        events = fetch_upcoming_games(
            days=max(horizon_days - 1, 1),
            include_market_opened=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Polymarket fetch failed: %s", exc)
        events = []

    openings = build_event_openings_df(events, reference_date=start_date) if events else pd.DataFrame()
    if openings.empty:
        openings = _fallback_polymarket_openings(start_date=start_date, horizon_days=horizon_days)
    if openings.empty:
        return None

    safe_write_parquet(
        openings,
        POLY_EVENT_OPENINGS_PATH,
        generator="run_bullpen_day_signal_research._build_and_save_polymarket_openings",
        date_col="event_date",
        backup=False,
        audit_action="save_polymarket_event_openings",
    )
    return POLY_EVENT_OPENINGS_PATH


def run_pipeline(
    *,
    start_date: date,
    horizon_days: int,
    fangraphs_html_path: Path | None = None,
    skip_fangraphs_fetch: bool = False,
    skip_polymarket: bool = False,
) -> dict[str, Path | None]:
    wanted_dates = set(_target_dates(start_date, horizon_days))

    # 1. ESPN capture for the live window.
    for target in sorted(wanted_dates):
        try:
            fetch_and_save_espn_probables_snapshot(target)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ESPN probable snapshot failed for %s: %s", target, exc)

    # 2. Fangraphs best-effort capture.
    _capture_fangraphs_rows(
        html_path=fangraphs_html_path,
        skip_fetch=skip_fangraphs_fetch,
        wanted_dates=wanted_dates,
    )

    # 3. Load persisted latest rows for live scanner.
    espn_live = select_latest_snapshot_rows(
        _load_parquet_if_exists(ESPN_SNAPSHOT_PATH),
        date_min=min(wanted_dates),
        date_max=max(wanted_dates),
        source="espn",
    )
    fangraphs_live = select_latest_snapshot_rows(
        _load_parquet_if_exists(FANGRAPHS_SNAPSHOT_PATH),
        date_min=min(wanted_dates),
        date_max=max(wanted_dates),
        source="fangraphs",
    )

    live_probables = pd.concat([espn_live, fangraphs_live], ignore_index=True, sort=False)
    live_roles = build_pitcher_role_rows(live_probables) if not live_probables.empty else pd.DataFrame()
    labels = load_game_label_frame()
    live_scanner = build_live_scanner_rows(
        espn_live,
        fangraphs_latest=fangraphs_live,
        role_rows=live_roles,
        label_frame=labels,
    )

    # 4. Historical ESPN research (2026 raw pregame snapshots).
    historical_espn = select_latest_snapshot_rows(
        load_historical_espn_probables_from_pregame_dir(),
        source="espn",
    )
    historical_probables = historical_espn.copy()
    historical_roles = (
        build_pitcher_role_rows(historical_probables) if not historical_probables.empty else pd.DataFrame()
    )
    historical_scanner = build_live_scanner_rows(
        historical_espn,
        fangraphs_latest=pd.DataFrame(),
        role_rows=historical_roles,
        label_frame=labels,
    )

    saved = persist_scanner_and_report(live_scanner, historical_scanner)

    # 5. Polymarket openings.
    saved["polymarket_openings"] = None
    if not skip_polymarket:
        saved["polymarket_openings"] = _build_and_save_polymarket_openings(
            start_date=start_date,
            horizon_days=horizon_days,
        )

    logger.info(
        "Live scanner rows=%d, historical rows=%d, report=%s",
        len(live_scanner),
        len(historical_scanner),
        HISTORICAL_REPORT_PATH.name if HISTORICAL_REPORT_PATH.exists() else "missing",
    )
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Run early bullpen-day research + scanner")
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date for the live scanner window (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=2,
        help="Operational horizon in days (default: today + tomorrow).",
    )
    parser.add_argument(
        "--fangraphs-html",
        type=Path,
        default=None,
        help="Optional local Fangraphs HTML snapshot to parse instead of fetching live.",
    )
    parser.add_argument(
        "--skip-fangraphs-fetch",
        action="store_true",
        help="Do not attempt a live Fangraphs fetch.",
    )
    parser.add_argument(
        "--skip-polymarket",
        action="store_true",
        help="Skip Polymarket market-opened tracking.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    start_date = date.fromisoformat(args.start_date) if args.start_date else date.today()
    saved = run_pipeline(
        start_date=start_date,
        horizon_days=max(1, args.horizon_days),
        fangraphs_html_path=args.fangraphs_html,
        skip_fangraphs_fetch=args.skip_fangraphs_fetch,
        skip_polymarket=args.skip_polymarket,
    )

    print(f"Live scanner: {saved.get('live_scanner') or LIVE_SCANNER_PATH}")
    print(f"Historical rows: {saved.get('historical_rows') or HISTORICAL_ROWS_PATH}")
    print(f"Historical report: {saved.get('historical_report') or HISTORICAL_REPORT_PATH}")
    if not args.skip_polymarket:
        print(f"Polymarket openings: {saved.get('polymarket_openings') or POLY_EVENT_OPENINGS_PATH}")


if __name__ == "__main__":
    main()
