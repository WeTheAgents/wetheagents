#!/usr/bin/env python3
"""Score a WEA repository against circle-1 module_grammar metrics.

Detects declared zone templates and computes module_grammar_uniformity for
each configured zone. Outputs a JSON summary that captures whether zone
templates are declared and the current conformity rate.

Usage:
    python scripts/score_repo.py --root PATH --target wea --scan-date DATE --repo-sha SHA

Example:
    python scripts/score_repo.py --root . --target wea --scan-date 2026-04-23 --repo-sha c07e079
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure scripts/ is on sys.path so circle1 package resolves
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from circle1.zone_template import compute_conformity, is_template_declared, known_zones


def _score_module_grammar(root: Path, zones: list[str]) -> dict[str, object]:
    per_zone: dict[str, object] = {}
    for zone in zones:
        per_zone[zone] = compute_conformity(root, zone)

    all_declared = all(is_template_declared(root, z) for z in zones)
    return {"zones": per_zone, "all_templates_declared": all_declared}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score a repo against circle-1 module_grammar metrics."
    )
    parser.add_argument("--root", required=True, help="Repository root path")
    parser.add_argument(
        "--target",
        default="wea",
        choices=["wea"],
        help="Scoring target (default: wea)",
    )
    parser.add_argument("--scan-date", required=True, help="Scan date (YYYY-MM-DD)")
    parser.add_argument("--repo-sha", required=True, help="Repository SHA at scan time")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: --root {args.root!r} is not a directory", file=sys.stderr)
        return 1

    zones = known_zones()
    module_grammar = _score_module_grammar(root, zones)

    result = {
        "scan_date": args.scan_date,
        "repo_sha": args.repo_sha,
        "target": args.target,
        "module_grammar": module_grammar,
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
