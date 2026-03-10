#!/usr/bin/env python3
"""Pipeline driver for W∃A task processing.

Parses evaluation comments, validates format, checks stage transitions.
Only pipeline.py (or wea pipeline advance) may change stage:* labels.

Usage:
    python scripts/pipeline.py --validate-comment --station STATION --body BODY
    python scripts/pipeline.py --check-transition --from LABEL --to LABEL
    python scripts/pipeline.py --run [--root PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_config(root: Path) -> dict:
    path = root / "pipeline" / "config.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_negativa_comment(body: str, config: dict) -> dict | None:
    """Parse Via Negativa evaluation comment. Return parsed dict or None if invalid."""
    cp = config.get("comment_parsing", {}).get("negativa", {})
    prefix = cp.get("prefix", "### Via Negativa Evaluation by ")
    line_pattern = cp.get("line_pattern", r"^\d+\. [^:]+: (PASS|FAIL) — .+$")
    line_count = cp.get("line_count", 6)
    verdict_pattern = cp.get("verdict_pattern", r"^Verdict: (PROCEED|KILL) \(item #\d+ — .+\)$")

    if not body.strip().startswith(prefix.strip()):
        return None

    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    line_re = re.compile(line_pattern)
    verdict_re = re.compile(verdict_pattern)

    checklist_lines = []
    verdict_line = None
    for ln in lines:
        if line_re.match(ln):
            checklist_lines.append(ln)
        elif verdict_re.match(ln):
            verdict_line = ln

    if len(checklist_lines) != line_count or not verdict_line:
        return None

    m = verdict_re.search(verdict_line)
    verdict = m.group(1) if m else None
    return {"verdict": verdict, "lines": checklist_lines} if verdict else None


def parse_spec_comment(body: str, config: dict) -> dict | None:
    """Parse Spec Review comment. Return parsed dict or None if invalid."""
    cp = config.get("comment_parsing", {}).get("spec", {})
    prefix = cp.get("prefix", "### Spec Review by ")
    red_team_re = re.compile(cp.get("red_team_pattern", r"^Red Team result: (GAMING FOUND|NO GAMING FOUND)$"))
    approval_re = re.compile(cp.get("approval_pattern", r"^Approval: (APPROVED|REJECTED)$"))

    if prefix.strip() not in body:
        return None

    red_team = None
    approval = None
    for ln in body.splitlines():
        ln = ln.strip()
        m = red_team_re.match(ln)
        if m:
            red_team = m.group(1)
        m = approval_re.match(ln)
        if m:
            approval = m.group(1)

    if red_team is None or approval is None:
        return None
    return {"red_team": red_team, "approval": approval}


def parse_verify_comment(body: str, config: dict) -> dict | None:
    """Parse Verification Review comment. Return parsed dict or None if invalid."""
    cp = config.get("comment_parsing", {}).get("verify", {})
    prefix = cp.get("prefix", "### Verification Review by ")
    checklist_re = re.compile(cp.get("checklist_pattern", r"^- (Gaming|Out-of-scope|Fragility|Removable code): (NONE|FOUND) —"))
    verdict_re = re.compile(cp.get("verdict_pattern", r"^Verdict: (APPROVED|CHANGES REQUESTED)$"))

    if prefix.strip() not in body:
        return None

    checklist_count = 0
    verdict = None
    for ln in body.splitlines():
        ln = ln.strip()
        if checklist_re.search(ln):
            checklist_count += 1
        m = verdict_re.match(ln)
        if m:
            verdict = m.group(1)

    if checklist_count < 4 or verdict is None:
        return None
    return {"verdict": verdict, "checklist_items": checklist_count}


def validate_comment(station: str, body: str, config: dict) -> tuple[bool, str]:
    """Validate comment body for station. Return (ok, message)."""
    parsers = {
        "negativa": parse_negativa_comment,
        "spec": parse_spec_comment,
        "verify": parse_verify_comment,
    }
    if station not in parsers:
        return False, f"Unknown station: {station}"

    result = parsers[station](body, config)
    if result is None:
        return False, f"Comment does not match required format for {station}. See pipeline/PARSE_SPEC.md"
    return True, json.dumps(result)


def check_transition(from_label: str, to_label: str, config: dict) -> tuple[bool, str]:
    """Check if stage transition is valid. Return (ok, message)."""
    valid = config.get("valid_transitions", {})
    rework = config.get("rework_transitions", {})

    all_from = set(valid.keys()) | set(rework.keys())
    if from_label not in all_from:
        return False, f"Unknown source stage: {from_label}"

    allowed = list(valid.get(from_label, [])) + list(rework.get(from_label, []))
    if to_label in allowed:
        return True, "Transition allowed"
    return False, f"Cannot transition {from_label} -> {to_label}. Allowed: {allowed}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline driver for W∃A tasks")
    parser.add_argument("--root", type=Path, default=_root(), help="Repo root")
    sub = parser.add_subparsers(dest="cmd")

    val = sub.add_parser("validate-comment", help="Validate evaluation comment format")
    val.add_argument("--station", required=True, choices=["negativa", "spec", "verify"])
    val.add_argument("--body", required=True, help="Comment body")

    trans = sub.add_parser("check-transition", help="Check if stage transition is allowed")
    trans.add_argument("--from", dest="from_label", required=True, help="Current stage label")
    trans.add_argument("--to", dest="to_label", required=True, help="Target stage label")

    run_p = sub.add_parser("run", help="Run pipeline cycle (stub)")
    run_p.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    config = _load_config(args.root)

    if args.cmd == "validate-comment":
        ok, msg = validate_comment(args.station, args.body, config)
        print(msg)
        return 0 if ok else 1

    if args.cmd == "check-transition":
        ok, msg = check_transition(args.from_label, args.to_label, config)
        print(msg)
        return 0 if ok else 1

    if args.cmd == "run":
        if args.dry_run:
            print("Dry run: pipeline cycle would process issues (not implemented)")
        else:
            print("Pipeline run: stub — comment parsing and transition checks available")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
