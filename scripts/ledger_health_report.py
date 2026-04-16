#!/usr/bin/env python3
"""Unified ledger health report for WeTheAgents.

Discovers all check_*.py scripts in scripts/, runs each, collects
pass/fail/stdout/duration, and writes a structured JSON snapshot to
ledger/health_report.json.

Exit codes:
    0 — all runnable checks passed (SKIP does not count as failure)
    1 — one or more checks failed, or no scripts discovered

Usage:
    python scripts/ledger_health_report.py [--dry-run] [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_EXIT_PASS = 0
_EXIT_SKIP = 2    # argparse error — check needs external context (PR list, etc.)
_CHECK_TIMEOUT = 60  # seconds — prevents hung scripts from blocking the runner


def discover_checks(scripts_dir: Path) -> list[Path]:
    """Return all check_*.py files in scripts_dir, sorted by name."""
    return sorted(scripts_dir.glob("check_*.py"))


def run_check(script: Path) -> dict:
    """Run a single check script and return a result dict.

    Status values (uppercase to match JSON schema):
        "PASS" — exit 0
        "FAIL" — exit 1 (or any non-zero, non-2 exit), timeout
        "SKIP" — exit 2 (argparse: needs external context)
    """
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT,
        )
        exit_code = proc.returncode
        stdout = proc.stdout
        stderr = proc.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = f"(timed out after {_CHECK_TIMEOUT}s)"
    duration_ms = max(0, int((time.perf_counter() - t0) * 1000))

    combined = (stdout + stderr).strip()
    non_blank = [ln for ln in combined.splitlines() if ln.strip()]
    summary = non_blank[0] if non_blank else "(no output)"

    if exit_code == _EXIT_SKIP:
        status = "SKIP"
    elif exit_code == _EXIT_PASS:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "name": script.name,
        "status": status,
        "summary": summary,
        "duration_ms": duration_ms,
    }


def build_report(scripts_dir: Path) -> tuple[dict, bool]:
    """Discover and run all checks; return (report_dict, all_passed).

    all_passed is True iff every runnable check (non-SKIP) passed.
    If no scripts are found, returns (error report, False).
    """
    scripts = discover_checks(scripts_dir)
    if not scripts:
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "overall": "FAIL",
            "checks": [],
            "error": f"No check_*.py scripts found in {scripts_dir}",
        }
        return report, False

    checks = [run_check(s) for s in scripts]
    runnable = [c for c in checks if c["status"] != "SKIP"]
    overall = "PASS" if runnable and all(c["status"] == "PASS" for c in runnable) else "FAIL"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "checks": checks,
    }
    return report, overall == "PASS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a structured health report to ledger/health_report.json"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the JSON report to stdout but do not write the file",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (auto-detected from script location if omitted)",
    )
    args = parser.parse_args(argv)

    if args.root:
        repo_root = Path(args.root).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent

    scripts_dir = repo_root / "scripts"
    report, all_passed = build_report(scripts_dir)

    output = json.dumps(report, indent=2)

    if args.dry_run:
        print(output)
    else:
        out_path = repo_root / "ledger" / "health_report.json"
        out_path.write_text(output + "\n", encoding="utf-8")
        print(f"Written: {out_path}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
