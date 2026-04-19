"""Settle logged UNDER picks against Polymarket close-history proxies."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.polymarket_client import fetch_price_history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
PICKS_DIR = ROOT / "picks"
PICK_LOG = PICKS_DIR / "pick_log.jsonl"
DEFAULT_OUTPUT = PICKS_DIR / "under_clv_settlements.json"


def _load_pick_log(path: Path) -> pd.DataFrame:
    rows = []
    if not path.exists():
        return pd.DataFrame()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _safe_decimal(price: float | None) -> float | None:
    if price is None or not np.isfinite(price) or price <= 0:
        return None
    return 1.0 / price


def _history_close_quote(token_id: str, entry_ts: int) -> tuple[float | None, int | None, str]:
    history = fetch_price_history(token_id, interval="1h", start_ts=entry_ts)
    if not history:
        return None, None, "missing_history"
    valid = [point for point in history if point.get("p") is not None and point.get("t") is not None]
    if not valid:
        return None, None, "missing_history"
    last = valid[-1]
    try:
        return float(last["p"]), int(last["t"]), "last_history_point"
    except (TypeError, ValueError):
        return None, None, "missing_history"


def main() -> int:
    parser = argparse.ArgumentParser(description="Settle UNDER pick CLV from logged Polymarket token IDs")
    parser.add_argument("--date", type=str, default=None, help="Optional pick date YYYY-MM-DD filter")
    parser.add_argument("--output", type=str, default=str(DEFAULT_OUTPUT), help="Output JSON path")
    args = parser.parse_args()

    picks = _load_pick_log(PICK_LOG)
    if picks.empty:
        logger.info("No pick log rows found at %s", PICK_LOG)
        return 0
    required_cols = {"market", "side", "polymarket_token_id"}
    missing_cols = required_cols - set(picks.columns)
    if missing_cols:
        logger.info(
            "Pick log does not yet contain CLV columns %s; nothing to settle.",
            sorted(missing_cols),
        )
        return 0

    mask = (
        picks["market"].eq("O/U")
        & picks["side"].eq("under")
        & picks["polymarket_token_id"].notna()
    )
    if args.date:
        mask &= picks["date"].eq(args.date)
    picks = picks.loc[mask].copy()
    if picks.empty:
        logger.info("No UNDER Polymarket picks matched the requested filters.")
        return 0

    picks = picks.sort_values("generated_at").drop_duplicates(subset=["pick_id"], keep="last")
    settlements = []
    for row in picks.itertuples(index=False):
        entry_price = getattr(row, "polymarket_price", None)
        token_id = str(getattr(row, "polymarket_token_id"))
        generated_at = pd.Timestamp(getattr(row, "generated_at"), tz="UTC")
        entry_ts = int(generated_at.timestamp())
        close_price, close_ts, close_status = _history_close_quote(token_id, entry_ts)

        entry_decimal = _safe_decimal(entry_price)
        close_decimal = _safe_decimal(close_price)
        entry_implied = float(entry_price) if entry_price is not None else None
        close_implied = float(close_price) if close_price is not None else None

        settlements.append(
            {
                "pick_id": row.pick_id,
                "date": row.date,
                "away": row.away,
                "home": row.home,
                "tier": row.tier,
                "pick_line": getattr(row, "pick_line", None),
                "event_id": getattr(row, "polymarket_event_id", None),
                "market_id": getattr(row, "polymarket_market_id", None),
                "condition_id": getattr(row, "polymarket_condition_id", None),
                "token_id": token_id,
                "entry_price": entry_price,
                "entry_best_bid": getattr(row, "polymarket_best_bid", None),
                "entry_best_ask": getattr(row, "polymarket_best_ask", None),
                "entry_decimal": entry_decimal,
                "entry_implied_prob": entry_implied,
                "close_price": close_price,
                "close_decimal": close_decimal,
                "close_implied_prob": close_implied,
                "close_ts": close_ts,
                "close_timestamp_utc": (
                    datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if close_ts is not None
                    else None
                ),
                "close_status": close_status,
                "clv_cents": (
                    (close_price - entry_price) * 100.0
                    if close_price is not None and entry_price is not None
                    else None
                ),
                "clv_decimal": (
                    close_decimal - entry_decimal
                    if close_decimal is not None and entry_decimal is not None
                    else None
                ),
                "clv_implied_prob": (
                    close_implied - entry_implied
                    if close_implied is not None and entry_implied is not None
                    else None
                ),
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(settlements, indent=2), encoding="utf-8")
    logger.info("Wrote %d UNDER CLV settlements -> %s", len(settlements), output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
