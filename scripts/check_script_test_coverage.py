#!/usr/bin/env python3
"""Verify every scripts/check_*.py file is covered by at least one test.

Coverage means a ``tests/test_*.py`` file imports or otherwise references the
script stem, such as ``check_invariant`` or ``check_invariant.py``.

Dead test files are limited to ``tests/test_check_*.py`` files whose contents do
not reference any current ``scripts/check_*.py`` script. This keeps unrelated
test modules out of the result while still catching stale check-test files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_WORD_CHAR = r"[A-Za-z0-9_]"


def _read_text(path: Path) -> str:
    """Return file text, or an empty string if the file is unreadable."""
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return ""


def discover_check_scripts(root: Path) -> list[Path]:
    """Return all scripts/check_*.py files, sorted by name."""
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return []
    return sorted(scripts_dir.glob("check_*.py"))


def discover_test_files(root: Path) -> list[Path]:
    """Return all tests/test_*.py files, sorted by name."""
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(tests_dir.glob("test_*.py"))


def discover_check_test_files(root: Path) -> list[Path]:
    """Return all tests/test_check_*.py files, sorted by name."""
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return []
    return sorted(tests_dir.glob("test_check_*.py"))


def build_script_pattern(script_stem: str) -> re.Pattern[str]:
    """Match a script stem as a standalone token, with optional .py suffix."""
    return re.compile(
        rf"(?<!{_WORD_CHAR}){re.escape(script_stem)}(?:\.py)?(?!{_WORD_CHAR})"
    )


def _summary(
    *,
    script_count: int,
    test_count: int,
    uncovered_scripts: list[str],
    dead_test_files: list[str],
) -> str:
    """Build a short human-readable summary."""
    if script_count == 0:
        return "no scripts/check_*.py files found"

    if not uncovered_scripts and not dead_test_files:
        return (
            f"all {script_count} check scripts are covered by "
            f"{test_count} tests/test_*.py files; no dead test files"
        )

    parts = [
        f"{script_count} check scripts scanned",
        f"{test_count} test files scanned",
    ]

    if uncovered_scripts:
        count = len(uncovered_scripts)
        noun = "script" if count == 1 else "scripts"
        names = ", ".join(uncovered_scripts)
        parts.append(f"{count} uncovered {noun}: {names}")

    if dead_test_files:
        count = len(dead_test_files)
        noun = "file" if count == 1 else "files"
        names = ", ".join(dead_test_files)
        parts.append(f"{count} dead test {noun}: {names}")

    return "; ".join(parts)


def run(root: Path) -> tuple[dict[str, Any], bool]:
    """Check that every check script is referenced by at least one test file."""
    check_scripts = discover_check_scripts(root)
    test_files = discover_test_files(root)
    check_test_files = discover_check_test_files(root)

    if not check_scripts:
        result = {
            "status": "PASS",
            "uncovered_scripts": [],
            "dead_test_files": [],
            "summary": _summary(
                script_count=0,
                test_count=len(test_files),
                uncovered_scripts=[],
                dead_test_files=[],
            ),
        }
        return result, True

    test_texts = {path: _read_text(path) for path in test_files}
    script_patterns = {
        script.name: build_script_pattern(script.stem)
        for script in check_scripts
    }

    uncovered_scripts = sorted(
        script_name
        for script_name, pattern in script_patterns.items()
        if not any(pattern.search(text) for text in test_texts.values())
    )

    dead_test_files = sorted(
        test_path.name
        for test_path in check_test_files
        if not any(
            pattern.search(test_texts.get(test_path, ""))
            for pattern in script_patterns.values()
        )
    )

    passed = not uncovered_scripts and not dead_test_files
    result = {
        "status": "PASS" if passed else "FAIL",
        "uncovered_scripts": uncovered_scripts,
        "dead_test_files": dead_test_files,
        "summary": _summary(
            script_count=len(check_scripts),
            test_count=len(test_files),
            uncovered_scripts=uncovered_scripts,
            dead_test_files=dead_test_files,
        ),
    }
    return result, passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    args = parser.parse_args(argv)

    if args.root:
        root = Path(args.root).resolve()
    else:
        root = Path(__file__).resolve().parent.parent

    result, passed = run(root)
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
