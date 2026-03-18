#!/usr/bin/env python3
"""Training Arena — launch multiple bots at the same PokerNow table.

Each bot runs as a separate process with its own Chrome profile and strategy config.
After the session, run analyze_arena.py to compare performance.

Usage:
    # Launch 4 bots with different strategies
    python scripts/run_arena.py --url <pokernow_url> --strategies tag_standard tag_tight lag nit

    # Launch with custom profiles
    python scripts/run_arena.py --url <url> --strategies tag_standard lag --profiles-dir ./profiles
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STRATEGIES_DIR = PROJECT_ROOT / "data" / "strategies"
PROFILES_DIR = PROJECT_ROOT / "profiles"

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [ARENA] %(message)s",
        datefmt="%H:%M:%S",
    )


def list_strategies() -> list[str]:
    """List available strategy configs."""
    return [f.stem for f in STRATEGIES_DIR.glob("*.json") if not f.stem.startswith("_")]


def launch_bot(
    url: str,
    strategy_name: str,
    profile_dir: str,
    bot_index: int,
) -> subprocess.Popen:
    """Launch a single bot process."""
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_bot.py"),
        "--url", url,
        "--profile", profile_dir,
        "--no-humanize",  # no delays in training
        "-v",
    ]

    env = os.environ.copy()
    env["WEA_POKER_STRATEGY"] = strategy_name
    env["WEA_POKER_BOT_INDEX"] = str(bot_index)

    logger.info(f"Launching bot-{bot_index} with strategy '{strategy_name}'")
    logger.info(f"  Profile: {profile_dir}")
    logger.info(f"  Command: {' '.join(cmd)}")

    # Each bot gets its own log file
    log_file = PROJECT_ROOT / "data" / "arena_sessions" / f"bot-{bot_index}-{strategy_name}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "w") as lf:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
        )
    return proc


def main() -> None:
    parser = argparse.ArgumentParser(description="WEA Poker Training Arena")
    parser.add_argument("--url", required=True, help="PokerNow game URL")
    parser.add_argument(
        "--strategies",
        nargs="+",
        default=["tag_standard", "tag_tight", "lag", "nit"],
        help=f"Strategy configs to use. Available: {list_strategies()}",
    )
    parser.add_argument(
        "--profiles-dir",
        default=str(PROFILES_DIR),
        help="Directory for Chrome profiles",
    )
    parser.add_argument(
        "--stagger-delay",
        type=float,
        default=5.0,
        help="Seconds between launching bots (for PokerNow join order)",
    )

    args = parser.parse_args()
    setup_logging()

    available = list_strategies()
    for s in args.strategies:
        if s not in available:
            logger.error(f"Unknown strategy: {s}. Available: {available}")
            sys.exit(1)

    logger.info(f"=== WEA POKER TRAINING ARENA ===")
    logger.info(f"URL: {args.url}")
    logger.info(f"Strategies: {args.strategies}")
    logger.info(f"Bots: {len(args.strategies)}")
    logger.info("")
    logger.info("IMPORTANT: Each bot needs to join the table manually the first time.")
    logger.info("After first join, cookies persist in the Chrome profile.")
    logger.info("")

    processes: list[subprocess.Popen] = []

    for i, strategy in enumerate(args.strategies):
        profile_dir = os.path.join(args.profiles_dir, f"bot-{i}")
        os.makedirs(profile_dir, exist_ok=True)

        proc = launch_bot(args.url, strategy, profile_dir, i)
        processes.append(proc)

        if i < len(args.strategies) - 1:
            logger.info(f"Waiting {args.stagger_delay}s before next bot...")
            time.sleep(args.stagger_delay)

    logger.info("")
    logger.info(f"All {len(processes)} bots launched. Press Ctrl+C to stop all.")
    logger.info(f"Logs: data/arena_sessions/bot-*.log")

    try:
        # Wait for all processes
        while True:
            alive = [p for p in processes if p.poll() is None]
            if not alive:
                logger.info("All bots finished.")
                break
            time.sleep(5)

    except KeyboardInterrupt:
        logger.info("Stopping all bots...")
        for p in processes:
            if p.poll() is None:
                p.terminate()
        # Give them time to clean up
        time.sleep(3)
        for p in processes:
            if p.poll() is None:
                p.kill()

    logger.info("Arena session complete.")
    logger.info(f"Run: python scripts/analyze_arena.py to review results")


if __name__ == "__main__":
    main()
