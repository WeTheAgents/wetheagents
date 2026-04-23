#!/usr/bin/env python3
"""Circle-1 checkpoint scanner for a WEA repository.

Produces a structural checkpoint JSON targeting the module_grammar dimension.
Detects declared zone templates and measures file conformance for session-1 zones
(scripts/ and src/wea_cli/).

Usage:
    python scripts/score_repo.py --root . --target wea \\
        --scan-date 2026-04-23 --repo-sha c07e079

Output is a JSON checkpoint record written to stdout.  Optionally save it to
domains/circle-1/checkpoints/ with --save.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT_HINT = _HERE.parent
if str(_ROOT_HINT) not in sys.path:
    sys.path.insert(0, str(_ROOT_HINT))

from scripts.circle1.zone_grammar import score_module_grammar


def _scan_wea(root: Path, scan_date: str, repo_sha: str) -> dict:
    mg = score_module_grammar(root)
    declared_zones = mg["zones_with_declared_templates"]

    if declared_zones:
        template_note = f"Zone templates declared for: {declared_zones}."
    else:
        template_note = "No zone templates declared — using empirical dominant shape only."

    return {
        "scan_date": scan_date,
        "repo_sha": repo_sha,
        "target": "wea",
        "structural": {
            "module_grammar": {
                "declared": mg["declared"],
                "enforced": mg["enforced"],
                "exercised": mg["exercised"],
            },
        },
        "module_grammar_detail": {
            "zones_with_declared_templates": declared_zones,
            "zone_signals": mg["zone_signals"],
        },
        "notes": [
            "Phase-1 scan: module_grammar dimension only.",
            template_note,
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Circle-1 checkpoint scanner")
    parser.add_argument("--root", default=".", help="Repo root directory")
    parser.add_argument("--target", default="wea", choices=["wea"])
    parser.add_argument(
        "--scan-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="ISO date for the checkpoint record",
    )
    parser.add_argument("--repo-sha", default="", help="Git SHA to record in the checkpoint")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save checkpoint to domains/circle-1/checkpoints/ instead of stdout",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = _scan_wea(root, args.scan_date, args.repo_sha)
    payload = json.dumps(result, indent=2)

    if args.save:
        slug = args.repo_sha or args.scan_date.replace("-", "")
        out_dir = root / "domains" / "circle-1" / "checkpoints"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"wea--{args.scan_date}--{slug}.json"
        out_path.write_text(payload + "\n", encoding="utf-8")
        print(f"Saved: {out_path}", file=sys.stderr)
    else:
        print(payload)


if __name__ == "__main__":
    main()
