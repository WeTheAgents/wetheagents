#!/usr/bin/env python3
"""Validate mandatory gauntlet fields in a raw PR body."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

REQUIRED_FIELDS = (
    "frontier_closed",
    "artifact",
    "evidence",
    "made_redundant",
    "redundancy_proof",
)

FIELD_RE = re.compile(
    rf"^\s*({'|'.join(re.escape(field) for field in REQUIRED_FIELDS)})\s*:\s*(.*)$",
    re.IGNORECASE,
)

PLACEHOLDER_VALUES = {
    "_no response_",
    "no response",
    "todo",
    "tbd",
    "<placeholder>",
}


def _read_body(cli_body: str | None) -> str:
    if cli_body is not None:
        return cli_body

    stdin_body = ""
    if not sys.stdin.isatty():
        stdin_body = sys.stdin.read()
    if stdin_body.strip():
        return stdin_body

    return os.environ.get("PR_BODY", "")


def parse_gauntlet_fields(body: str) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    current_field: str | None = None

    for line in body.splitlines():
        match = FIELD_RE.match(line)
        if match:
            current_field = str(match.group(1)).lower()
            values.setdefault(current_field, []).append(match.group(2))
            continue

        if current_field is not None:
            values[current_field].append(line)

    return {
        field: "\n".join(parts).strip()
        for field, parts in values.items()
    }


def _is_empty_value(value: str | None) -> bool:
    if value is None:
        return True

    stripped = value.strip()
    if not stripped:
        return True

    lowered = stripped.lower()
    if lowered in PLACEHOLDER_VALUES:
        return True

    return bool(re.fullmatch(r"<[^>\n]+>", stripped))


def evaluate_pr_body(body: str) -> dict[str, object]:
    parsed = parse_gauntlet_fields(body)
    missing = [field for field in REQUIRED_FIELDS if field not in parsed]
    empty = [field for field in REQUIRED_FIELDS if field in parsed and _is_empty_value(parsed[field])]
    status = "PASS" if not missing and not empty else "FAIL"
    return {"status": status, "missing": missing, "empty": empty}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("body", nargs="?", help="Raw PR body text")
    args = parser.parse_args(argv)

    result = evaluate_pr_body(_read_body(args.body))
    print(json.dumps(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
