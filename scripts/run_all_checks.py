#!/usr/bin/env python3
"""
Integration runner for all scripts/check_*.py scripts.

Discovers every check_*.py in the same directory, runs each as a subprocess,
and reports a [PASS]/[FAIL]/[SKIP] table.

Exit codes:
    0 — all runnable checks passed (SKIP does not count as failure)
    1 — one or more checks failed

SKIP is assigned when a script exits 2 (argparse error — requires external
context like PR file lists or positional arguments that are only available
in CI). These checks cannot run in sweep mode and are excluded from the
pass/fail tally.

Usage:
  python scripts/run_all_checks.py [--json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Standard exit codes
_EXIT_PASS = 0
_EXIT_FAIL = 1
_EXIT_ARGPARSE = 2   # missing required args → check needs external context


def discover_checks(scripts_dir: Path) -> list[Path]:
    """Return all check_*.py files in scripts_dir, sorted by name."""
    return sorted(scripts_dir.glob("check_*.py"))


_CHECK_TIMEOUT = 60  # seconds — prevents a hung script from blocking the runner


def run_check(script: Path) -> dict:
    """Run a single check script and return a result dict.

    Each script is expected to detect its own repo root from its file location
    (the standard pattern used throughout this codebase).  No --root is passed
    so that scripts with different CLI shapes are not broken by an unrecognised
    flag.

    Status values:
        "pass"  — exit 0
        "fail"  — exit 1 (or any non-zero, non-2 exit)
        "skip"  — exit 2 (argparse: needs external context, e.g. PR file list)
    """
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT,
        )
        exit_code = result.returncode
        stdout = result.stdout
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        exit_code = -1
        stdout = ""
        stderr = f"(timed out after {_CHECK_TIMEOUT}s)"

    combined = (stdout + stderr).strip()
    non_blank = [ln for ln in combined.splitlines() if ln.strip()]
    first_line = non_blank[0] if non_blank else "(no output)"

    if exit_code == _EXIT_ARGPARSE:
        status = "skip"
    elif exit_code == _EXIT_PASS:
        status = "pass"
    else:
        status = "fail"

    return {
        "script": script.name,
        "exit_code": exit_code,
        "status": status,
        "passed": status == "pass",
        "skipped": status == "skip",
        "first_line": first_line,
        "stdout": stdout,
        "stderr": stderr,
    }


def print_table(results: list[dict]) -> None:
    """Print a human-readable [PASS]/[FAIL]/[SKIP] table."""
    width = max((len(r["script"]) for r in results), default=20)
    for r in results:
        label = {"pass": "[PASS]", "fail": "[FAIL]", "skip": "[SKIP]"}[r["status"]]
        print(f"{label}  {r['script']:<{width}}  {r['first_line']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run all scripts/check_*.py checks")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output machine-readable JSON instead of a table",
    )
    args = parser.parse_args(argv)

    scripts_dir = Path(__file__).resolve().parent

    checks = discover_checks(scripts_dir)
    if not checks:
        msg = "No check_*.py scripts found in " + str(scripts_dir)
        if args.output_json:
            print(json.dumps({"error": msg, "results": [], "all_passed": False}))
        else:
            print(msg)
        return 1

    results = [run_check(script) for script in checks]

    runnable = [r for r in results if not r["skipped"]]
    all_passed = all(r["passed"] for r in runnable)

    if args.output_json:
        print(
            json.dumps(
                {
                    "all_passed": all_passed,
                    "total": len(results),
                    "runnable": len(runnable),
                    "passed": sum(1 for r in runnable if r["passed"]),
                    "failed": sum(1 for r in runnable if not r["passed"]),
                    "skipped": sum(1 for r in results if r["skipped"]),
                    "results": results,
                },
                indent=2,
            )
        )
    else:
        print_table(results)
        passed = sum(1 for r in runnable if r["passed"])
        failed = len(runnable) - passed
        skipped = len(results) - len(runnable)
        print(f"\n{passed}/{len(runnable)} runnable checks passed", end="")
        if skipped:
            print(f"  ({skipped} skipped — need external context)", end="")
        if failed:
            print(f"  ({failed} failed)")
            for r in results:
                if r["status"] == "fail":
                    print(f"\n--- {r['script']} ---")
                    if r["stdout"]:
                        print(r["stdout"].rstrip())
                    if r["stderr"]:
                        print(r["stderr"].rstrip(), file=sys.stderr)
        else:
            print()

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
