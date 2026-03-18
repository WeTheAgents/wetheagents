#!/usr/bin/env python3
"""WEA Poker Bot — main entry point.

Usage:
    python scripts/run_bot.py --url https://www.pokernow.club/games/XXXXX
    python scripts/run_bot.py --url <url> --profile profiles/bot-1
    python scripts/run_bot.py --url <url> --bubble --players-remaining 12 --players-paid 10
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy.engine import PokerEngine, TournamentState
from src.table.connector import PokerNowConnector, run_bot_loop


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="WEA Poker Bot")
    parser.add_argument("--url", required=True, help="PokerNow game URL")
    parser.add_argument("--profile", default=None, help="Chrome profile directory (for multi-bot)")
    parser.add_argument("--headless", action="store_true", help="Run Chrome headless")
    parser.add_argument("--no-humanize", action="store_true", help="Disable human-like delays")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    # Tournament settings
    parser.add_argument("--players-started", type=int, default=0,
                        help="Total players who started the tournament")
    parser.add_argument("--players-remaining", type=int, default=0,
                        help="Players currently remaining")
    parser.add_argument("--players-paid", type=int, default=0,
                        help="Number of paid places")
    parser.add_argument("--bubble", action="store_true",
                        help="Enable bubble aggression mode")

    args = parser.parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger(__name__)
    logger.info("WEA Poker Bot starting...")

    # Tournament state
    tournament = TournamentState(
        players_started=args.players_started,
        players_remaining=args.players_remaining,
        players_paid=args.players_paid,
    )

    # Force bubble mode if flag is set
    if args.bubble and tournament.players_paid == 0:
        tournament.players_paid = max(1, tournament.players_remaining - 1)
        logger.info("Bubble mode enabled (forced)")

    engine = PokerEngine(tournament=tournament)

    # Connect to table
    connector = PokerNowConnector(
        profile_dir=args.profile,
        headless=args.headless,
        humanize=not args.no_humanize,
    )

    try:
        connector.connect(args.url)
        logger.info("Connected to table. Starting bot loop...")
        logger.info(f"Tournament phase: {tournament.phase}")

        run_bot_loop(connector, engine.get_action)

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        connector.disconnect()
        logger.info("Disconnected. GG.")


if __name__ == "__main__":
    main()
