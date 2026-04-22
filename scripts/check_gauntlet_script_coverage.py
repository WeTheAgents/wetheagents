#!/usr/bin/env python3
"""Verify every scripts/check_*.py has test coverage or a documented exception.

For each script, checks at least one of:
  1. A matching test file exists: tests/**/test_{script_stem}.py
  2. The script is listed in scripts/COVERAGE_EXCEPTIONS.txt with a reason

Prints a coverage table and exits 0 when all scripts are covered or excepted;
exits 1 with a list of uncovered scripts otherwise.

Output JSON: {"status": "pass"|"fail", "uncovered": [...], "covered": [...],
              "excepted": [...], "stats": {"total", "covered_count",
              "uncovered_count", "excepted_count"}}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_exceptions(exceptions_file: Path) -> dict[str, str]:
    """Parse COVERAGE_EXCEPTIONS.txt and return {script_name: reason}."""
    if not exceptions_file.exists():
        return {}
    result: dict[str, str] = {}
    for line in exceptions_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            name, _, reason = line.partition(":")
            result[name.strip()] = reason.strip()
        else:
            result[line] = ""
    return result


def find_test_file(script_stem: str, tests_dir: Path) -> Path | None:
    """Return the first matching test file path, or None if not found.

    Searches tests_dir recursively for test_{script_stem}.py,
    skipping __pycache__ directories.
    """
    target = f"test_{script_stem}.py"
    for candidate in tests_dir.rglob(target):
        if "__pycache__" not in candidate.parts:
            return candidate
    return None


def check_coverage(
    scripts_dir: Path,
    tests_dir: Path,
    exceptions_file: Path,
) -> dict:
    """Run coverage analysis and return result dict."""
    exceptions = load_exceptions(exceptions_file)
    missing_exceptions_file = not exceptions_file.exists()

    if not scripts_dir.exists():
        scripts = []
    else:
        scripts = sorted(scripts_dir.glob("check_*.py"))

    covered: list[dict] = []
    uncovered: list[str] = []
    excepted: list[dict] = []

    for script in scripts:
        stem = script.stem
        test_file = find_test_file(stem, tests_dir)
        if test_file is not None:
            covered.append({"script": script.name, "test": str(test_file)})
        elif script.name in exceptions:
            excepted.append({"script": script.name, "reason": exceptions[script.name]})
        else:
            uncovered.append(script.name)

    status = "fail" if uncovered or missing_exceptions_file else "pass"
    return {
        "status": status,
        "uncovered": uncovered,
        "covered": covered,
        "excepted": excepted,
        "stats": {
            "total": len(scripts),
            "covered_count": len(covered),
            "uncovered_count": len(uncovered),
            "excepted_count": len(excepted),
        },
        "_missing_exceptions_file": missing_exceptions_file,
    }


def print_table(result: dict) -> None:
    col_script = max((len(e["script"]) for e in result["covered"]), default=6)
    col_script = max(col_script, max((len(s) for s in result["uncovered"]), default=6))
    col_script = max(col_script, max((len(e["script"]) for e in result["excepted"]), default=6))
    col_script = max(col_script, 6)

    header = f"{'Script':<{col_script}}  {'Status':<9}  Test File"
    print(header)
    print("-" * len(header))

    for entry in result["covered"]:
        print(f"{entry['script']:<{col_script}}  {'COVERED':<9}  {entry['test']}")
    for entry in result["excepted"]:
        print(f"{entry['script']:<{col_script}}  {'EXCEPTED':<9}  (exception: {entry['reason'][:60]})")
    for name in result["uncovered"]:
        print(f"{name:<{col_script}}  {'UNCOVERED':<9}  —")

    stats = result["stats"]
    print()
    print(
        f"Total: {stats['total']}  "
        f"Covered: {stats['covered_count']}  "
        f"Excepted: {stats['excepted_count']}  "
        f"Uncovered: {stats['uncovered_count']}"
    )
    if result.get("_missing_exceptions_file"):
        print("ERROR: scripts/COVERAGE_EXCEPTIONS.txt not found")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Repo root (default: current directory)",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only the JSON result (no table)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    scripts_dir = root / "scripts"
    tests_dir = root / "tests"
    exceptions_file = scripts_dir / "COVERAGE_EXCEPTIONS.txt"

    result = check_coverage(scripts_dir, tests_dir, exceptions_file)

    if not args.json_only:
        print_table(result)
        print()

    output = {k: v for k, v in result.items() if not k.startswith("_")}
    print(json.dumps(output, indent=2))

    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
