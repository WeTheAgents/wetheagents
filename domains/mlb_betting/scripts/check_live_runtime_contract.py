"""Strict live runtime smoke for today's production strategy set."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
for _path in (SCRIPT_DIR, BASE_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from src.live_runtime_contracts import evaluate_live_runtime_contract
from src.strategies.catalog import DEFAULT_PRODUCTION_TIERS


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live runtime contract")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    parser.add_argument(
        "--tiers",
        type=str,
        default=",".join(DEFAULT_PRODUCTION_TIERS),
        help="Comma-separated tiers to check",
    )
    parser.add_argument("--json-out", type=str, default=None, help="Optional JSON output path")
    parser.add_argument("--quiet", action="store_true", help="Print only failing tiers")
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else date.today()
    tiers = [tier.strip() for tier in args.tiers.split(",") if tier.strip()]
    report = evaluate_live_runtime_contract(target, requested_tiers=tiers)

    print(f"check_live_runtime_contract.py — {report['target_date']}")
    print(
        "  scoreboard: "
        f"scheduled={report['scoreboard']['scheduled_games']}, "
        f"final={report['scoreboard']['final_games']}"
    )
    print(
        "  completeness: "
        f"overlay={report['completeness']['overlay_games']} "
        f"filtered={report['completeness']['filtered_games']} "
        f"enriched={report['completeness']['enriched_games']}"
    )
    print()

    for tier, info in report["tier_results"].items():
        if args.quiet and info["status"] in {"ready", "strict_but_empty"}:
            continue
        print(f"  [{info['status']}] {tier} — {info['detail']}")

    if report["completeness"]["missing_after_filters"]:
        print()
        print("  dropped between overlay and filtered:")
        for item in report["completeness"]["missing_after_filters"]:
            print(f"    - {item['away']} @ {item['home']}: {item['reason']}")
    if report["completeness"]["missing_after_enrichment"]:
        print()
        print("  dropped between filtered and enriched:")
        for item in report["completeness"]["missing_after_enrichment"]:
            print(f"    - {item['away']} @ {item['home']}: {item['reason']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
