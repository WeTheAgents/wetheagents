#!/usr/bin/env python3
"""Analyze training arena session results.

Parses bot log files to extract key metrics and compare strategies.

Usage:
    python scripts/analyze_arena.py
    python scripts/analyze_arena.py --session-dir data/arena_sessions/
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / "arena_sessions"


def parse_log(log_path: Path) -> dict:
    """Parse a bot log file and extract key metrics."""
    stats = {
        "file": log_path.name,
        "hands": 0,
        "folds": 0,
        "calls": 0,
        "raises": 0,
        "all_ins": 0,
        "checks": 0,
        "decisions": [],
    }

    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return stats

    # Count hands
    stats["hands"] = len(re.findall(r"Hand #\d+:", text))

    # Count decisions
    stats["folds"] = len(re.findall(r"DECISION: fold", text, re.IGNORECASE))
    stats["calls"] = len(re.findall(r"DECISION: call", text, re.IGNORECASE))
    stats["raises"] = len(re.findall(r"DECISION: raise", text, re.IGNORECASE))
    stats["all_ins"] = len(re.findall(r"DECISION: all_in", text, re.IGNORECASE))
    stats["checks"] = len(re.findall(r"DECISION: check", text, re.IGNORECASE))

    total_actions = stats["folds"] + stats["calls"] + stats["raises"] + stats["all_ins"] + stats["checks"]
    if total_actions > 0:
        stats["vpip_approx"] = (stats["calls"] + stats["raises"] + stats["all_ins"]) / total_actions
        stats["pfr_approx"] = (stats["raises"] + stats["all_ins"]) / total_actions
    else:
        stats["vpip_approx"] = 0
        stats["pfr_approx"] = 0

    # Extract strategy from filename
    match = re.match(r"bot-\d+-(.+)\.log", log_path.name)
    stats["strategy"] = match.group(1) if match else "unknown"

    # Extract bot index
    match = re.match(r"bot-(\d+)-", log_path.name)
    stats["bot_index"] = int(match.group(1)) if match else -1

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze arena session results")
    parser.add_argument(
        "--session-dir",
        default=str(DEFAULT_SESSION_DIR),
        help="Directory with bot log files",
    )
    args = parser.parse_args()

    session_dir = Path(args.session_dir)
    if not session_dir.exists():
        print(f"No session data found at {session_dir}")
        sys.exit(1)

    log_files = sorted(session_dir.glob("bot-*.log"))
    if not log_files:
        print(f"No bot log files found in {session_dir}")
        sys.exit(1)

    results = [parse_log(f) for f in log_files]

    # Print results table
    print("\n" + "=" * 80)
    print("WEA POKER ARENA — Session Results")
    print("=" * 80)
    print(f"\n{'Bot':<8} {'Strategy':<16} {'Hands':<8} {'VPIP%':<8} {'PFR%':<8} "
          f"{'Folds':<8} {'Calls':<8} {'Raises':<8} {'All-in':<8}")
    print("-" * 80)

    for r in sorted(results, key=lambda x: x["bot_index"]):
        print(
            f"Bot-{r['bot_index']:<4} {r['strategy']:<16} {r['hands']:<8} "
            f"{r['vpip_approx']:.0%}{'':<5} {r['pfr_approx']:.0%}{'':<5} "
            f"{r['folds']:<8} {r['calls']:<8} {r['raises']:<8} {r['all_ins']:<8}"
        )

    print("\n" + "=" * 80)
    print("Notes:")
    print("  - VPIP/PFR are approximate (based on action counts, not hand-by-hand)")
    print("  - For accurate chip results, check PokerNow hand history CSV export")
    print("  - Compare strategies by BB/100 from the hand history data")
    print("=" * 80)


if __name__ == "__main__":
    main()
