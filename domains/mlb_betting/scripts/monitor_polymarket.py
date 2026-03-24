"""Monitor live Polymarket MLB game markets and print current prices.

Usage:
    python scripts/monitor_polymarket.py                    # Today's games
    python scripts/monitor_polymarket.py --days 3           # Next 3 days
    python scripts/monitor_polymarket.py --save             # Save snapshot to parquet
    python scripts/monitor_polymarket.py --orderbook        # Include order book depth
"""

import argparse
import logging
import sys

from src.polymarket_client import (
    MLBGameEvent,
    MLBMarket,
    OrderBook,
    build_games_df,
    fetch_order_books_for_game,
    fetch_todays_games,
    fetch_upcoming_games,
    save_market_data,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def format_price(price: float | None) -> str:
    if price is None:
        return "  --"
    return f"{price * 100:4.0f}c"


def format_decimal_odds(price: float | None) -> str:
    if price is None or price == 0:
        return "  --"
    return f"{1 / price:5.2f}"


def print_game(event: MLBGameEvent, show_orderbook: bool = False,
               order_books: dict[str, OrderBook] | None = None) -> None:
    """Print a formatted summary of a single game."""
    time_str = event.game_time.strftime("%H:%M") if event.game_time else "TBD"
    date_str = str(event.event_date) if event.event_date else ""
    vol_str = f"${event.volume:,.0f}" if event.volume else "$0"

    print(f"\n{'=' * 70}")
    print(f"  {event.away_team}  @  {event.home_team}")
    print(f"  {date_str}  {time_str} UTC  |  Vol: {vol_str}  |  {event.slug}")
    print(f"{'=' * 70}")

    # Group markets by type
    by_type: dict[str, list[MLBMarket]] = {}
    for m in event.markets:
        by_type.setdefault(m.market_type, []).append(m)

    # Moneyline
    for m in by_type.get("moneyline", []):
        outcomes = m.outcomes
        prices = m.outcome_prices
        o1 = outcomes[0] if outcomes else "Away"
        o2 = outcomes[1] if len(outcomes) > 1 else "Home"
        p1 = prices[0] if prices else None
        p2 = prices[1] if len(prices) > 1 else None
        status = "CLOSED" if m.closed else ""
        print(f"\n  MONEYLINE {status}")
        print(f"    {o1:<25s} {format_price(p1)}  ({format_decimal_odds(p1)})")
        print(f"    {o2:<25s} {format_price(p2)}  ({format_decimal_odds(p2)})")
        if m.spread is not None:
            print(f"    Spread: {m.spread * 100:.0f}c  |  Last: {format_price(m.last_trade_price)}")

    # Totals
    for m in by_type.get("total", []):
        prices = m.outcome_prices
        p1 = prices[0] if prices else None
        p2 = prices[1] if len(prices) > 1 else None
        line_str = f"O/U {m.line}" if m.line else "O/U"
        status = "CLOSED" if m.closed else ""
        print(f"\n  {line_str} {status}")
        print(f"    Over                      {format_price(p1)}  ({format_decimal_odds(p1)})")
        print(f"    Under                     {format_price(p2)}  ({format_decimal_odds(p2)})")

    # Spreads
    for m in by_type.get("spread", []):
        outcomes = m.outcomes
        prices = m.outcome_prices
        o1 = outcomes[0] if outcomes else "?"
        o2 = outcomes[1] if len(outcomes) > 1 else "?"
        p1 = prices[0] if prices else None
        p2 = prices[1] if len(prices) > 1 else None
        line_str = f"Spread {m.line:+.1f}" if m.line else "Spread"
        status = "CLOSED" if m.closed else ""
        print(f"\n  {line_str} {status}")
        print(f"    {o1:<25s} {format_price(p1)}  ({format_decimal_odds(p1)})")
        print(f"    {o2:<25s} {format_price(p2)}  ({format_decimal_odds(p2)})")

    # Order book depth
    if show_orderbook and order_books:
        for m in event.markets:
            ob = order_books.get(m.market_id)
            if not ob or (not ob.bids and not ob.asks):
                continue
            label = m.group_item_title or m.market_type
            print(f"\n  Order Book: {label}")
            print(f"    {'BIDS':<30s} {'ASKS'}")
            max_levels = max(len(ob.bids), len(ob.asks), 1)
            for i in range(min(max_levels, 5)):
                bid_str = ""
                ask_str = ""
                if i < len(ob.bids):
                    b = ob.bids[i]
                    bid_str = f"{b.price * 100:5.1f}c x {b.size:,.0f}"
                if i < len(ob.asks):
                    a = ob.asks[i]
                    ask_str = f"{a.price * 100:5.1f}c x {a.size:,.0f}"
                print(f"    {bid_str:<30s} {ask_str}")


def print_summary_table(events: list[MLBGameEvent]) -> None:
    """Print a compact summary table of all moneyline markets."""
    print(f"\n{'MONEYLINE SUMMARY':=^70}")
    print(f"  {'Date':<12s} {'Away':<20s} {'Home':<20s} {'Away':>5s} {'Home':>5s} {'Vol':>8s}")
    print(f"  {'-' * 66}")

    for e in events:
        ml = [m for m in e.markets if m.market_type == "moneyline"]
        if not ml:
            continue
        m = ml[0]
        prices = m.outcome_prices
        p1 = prices[0] if prices else None
        p2 = prices[1] if len(prices) > 1 else None
        date_str = str(e.event_date) if e.event_date else ""
        vol_str = f"${e.volume:,.0f}" if e.volume else "$0"
        print(
            f"  {date_str:<12s} {e.away_team:<20s} {e.home_team:<20s} "
            f"{format_price(p1):>5s} {format_price(p2):>5s} {vol_str:>8s}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Polymarket MLB markets")
    parser.add_argument("--days", type=int, default=0,
                        help="Fetch games for next N days (0=today only)")
    parser.add_argument("--save", action="store_true",
                        help="Save snapshot to parquet")
    parser.add_argument("--orderbook", action="store_true",
                        help="Fetch and display order book depth")
    parser.add_argument("--all", action="store_true",
                        help="Fetch all active MLB events (not just upcoming)")
    args = parser.parse_args()

    if args.all:
        from src.polymarket_client import fetch_mlb_events
        events = fetch_mlb_events(active_only=True)
    elif args.days > 0:
        events = fetch_upcoming_games(days=args.days)
    else:
        events = fetch_todays_games()

    if not events:
        print("No MLB games found.")
        sys.exit(0)

    events.sort(key=lambda e: (e.event_date or "", e.game_time or ""))

    print(f"\nFound {len(events)} MLB game(s)")
    print_summary_table(events)

    for event in events:
        order_books = None
        if args.orderbook:
            order_books = fetch_order_books_for_game(event)
        print_game(event, show_orderbook=args.orderbook, order_books=order_books)

    if args.save:
        df = build_games_df(events)
        path = save_market_data(df)
        print(f"\nSaved {len(df)} rows to {path}")


if __name__ == "__main__":
    main()
