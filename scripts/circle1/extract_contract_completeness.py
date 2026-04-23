#!/usr/bin/env python3
"""
Task Contract Completeness Extractor.

Classifies task bodies by contract completeness for circle-1 measurement.
Produces the ``task_contract_completeness_rate`` signal defined in
``domains/circle-1/docs/cooling_metrics_v0.md``.

== Phase 1 completeness definition ==

A task body is considered COMPLETE when it contains all four structural elements:

  1. ``Verification Criteria`` section — present and non-empty (not "_No response_")
  2. MUST criterion — at least one line in that section containing "MUST:" that is
     NOT a "MUST NOT:" line
  3. MUST NOT criterion — at least one line in that section containing "MUST NOT:"
  4. ``Scope boundaries`` section — present and non-empty (not "_No response_")

A task body is INCOMPLETE if any of those four elements is absent.

== Phase 1 code-change inclusion rule ==

Only code-change tasks are included in the ``task_contract_completeness_rate``
denominator.  A task body is classified as a code-change task when ALL of:

  - Reward Type is NOT "Duel"

AND at least one of:
  - ``Skills Needed`` section contains "Coding" (any language)
  - ``Scope boundaries`` section mentions a file extension (.py .json .yml .yaml .js .ts .sh)
  - ``Verification Criteria`` section contains pytest, pull request, or script references

Use ``--all-tasks`` to bypass classification and include every task in the batch.

== Usage ==

  python scripts/circle1/extract_contract_completeness.py --input tasks.json
  python scripts/circle1/extract_contract_completeness.py --input tasks.json --all-tasks
  python scripts/circle1/extract_contract_completeness.py --input tasks.json --output result.json

  echo '{"number":42,"body":"..."}' | python scripts/circle1/extract_contract_completeness.py

== Input format ==

  {"tasks": [{"number": 42, "body": "..."}, ...]}

  Or a JSON array: [{"number": 42, "body": "..."}, ...]

  Or a single-task object on stdin: {"number": 42, "body": "..."}

== Output format ==

  {
    "scan_date": "YYYY-MM-DD",
    "inclusion_rule": "phase1-code-change",
    "total_input_tasks": 10,
    "code_change_tasks": 7,
    "complete_tasks": 5,
    "incomplete_tasks": 2,
    "task_contract_completeness_rate": 0.7143,
    "findings": [
      {
        "number": 42,
        "is_code_change_task": true,
        "complete": true,
        "has_verification_criteria": true,
        "has_must": true,
        "has_must_not": true,
        "has_scope_boundaries": true,
        "missing": []
      }
    ]
  }

``task_contract_completeness_rate`` is null when no code-change tasks are found.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from typing import Any


# ---------------------------------------------------------------------------
# Section parser
# ---------------------------------------------------------------------------

def _parse_field(body: str, label: str) -> str | None:
    """Return the content of a ``### label`` section, or None if absent/empty.

    Stops at the next ``###`` section or end of string.  Treats ``_No response_``
    and ``none`` as absent.  Strips leading/trailing whitespace from the result.
    """
    pattern = re.compile(
        rf"###\s+{re.escape(label)}[^\n]*\n(.*?)(?=\n###|\Z)",
        re.DOTALL,
    )
    m = pattern.search(body)
    if not m:
        return None
    val = m.group(1).strip()
    if not val or val.lower() in ("_no response_", "none"):
        return None
    return val


# ---------------------------------------------------------------------------
# Completeness checks
# ---------------------------------------------------------------------------

# Matches "MUST:" at a word boundary (any capitalisation)
_MUST_ONLY_RE = re.compile(r"\bMUST\s*:", re.IGNORECASE)
# Matches "MUST NOT:" at a word boundary (any capitalisation)
_MUST_NOT_RE = re.compile(r"\bMUST\s+NOT\s*:", re.IGNORECASE)


def _has_must_criterion(verification: str) -> bool:
    """True if at least one non-MUST-NOT line contains a MUST: pattern."""
    for line in verification.splitlines():
        if _MUST_NOT_RE.search(line):
            continue
        if _MUST_ONLY_RE.search(line):
            return True
    return False


def _has_must_not_criterion(verification: str) -> bool:
    """True if at least one line contains a MUST NOT: pattern."""
    return any(_MUST_NOT_RE.search(line) for line in verification.splitlines())


def check_completeness(body: str) -> dict[str, Any]:
    """Classify a single task body by contract completeness.

    Returns a dict with boolean flags for each structural element plus
    ``complete`` (all four present) and ``missing`` (list of absent elements).
    """
    verification = _parse_field(body, "Verification Criteria")
    scope = _parse_field(body, "Scope boundaries")

    has_verification = bool(verification)
    has_must = has_verification and _has_must_criterion(verification)  # type: ignore[arg-type]
    has_must_not = has_verification and _has_must_not_criterion(verification)  # type: ignore[arg-type]
    has_scope = bool(scope)

    missing: list[str] = []
    if not has_verification:
        missing.append("verification_criteria")
    else:
        if not has_must:
            missing.append("must_criterion")
        if not has_must_not:
            missing.append("must_not_criterion")
    if not has_scope:
        missing.append("scope_boundaries")

    return {
        "has_verification_criteria": has_verification,
        "has_must": has_must,
        "has_must_not": has_must_not,
        "has_scope_boundaries": has_scope,
        "complete": len(missing) == 0,
        "missing": missing,
    }


# ---------------------------------------------------------------------------
# Code-change task classification (Phase 1 rule)
# ---------------------------------------------------------------------------

_CODING_SKILLS_RE = re.compile(r"\bCoding\b", re.IGNORECASE)
_FILE_EXT_RE = re.compile(r"\.(py|json|yml|yaml|js|ts|sh)\b", re.IGNORECASE)
_CODE_ARTIFACT_RE = re.compile(r"\bpytest\b|\bpull\s+request\b|\bscript\b", re.IGNORECASE)


def is_code_change_task(body: str) -> bool:
    """Classify a task body as a code-change task under the Phase 1 rule.

    Returns False for duel tasks regardless of other signals.
    Returns True when any of the three positive signals is present.
    Returns False if no positive signal is found.

    See module docstring for the full inclusion rule.
    """
    reward_type = _parse_field(body, "Reward Type") or ""
    if "duel" in reward_type.lower():
        return False

    skills = _parse_field(body, "Skills Needed") or ""
    if _CODING_SKILLS_RE.search(skills):
        return True

    scope = _parse_field(body, "Scope boundaries") or ""
    if _FILE_EXT_RE.search(scope):
        return True

    verification = _parse_field(body, "Verification Criteria") or ""
    if _CODE_ARTIFACT_RE.search(verification):
        return True

    return False


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------

def extract(
    tasks: list[dict[str, Any]],
    *,
    all_tasks: bool = False,
    scan_date: str | None = None,
) -> dict[str, Any]:
    """Extract contract completeness metrics from a list of task records.

    Args:
        tasks: List of dicts with at least ``number`` and ``body`` keys.
        all_tasks: When True, skip code-change classification and include every
            task in the completeness denominator.
        scan_date: ISO date string (``YYYY-MM-DD``); defaults to today.

    Returns:
        Machine-readable results dict (see module docstring for shape).
    """
    today = scan_date or date.today().isoformat()
    inclusion_rule = "all-tasks" if all_tasks else "phase1-code-change"

    findings: list[dict[str, Any]] = []
    for task in tasks:
        number = task.get("number", "?")
        body = task.get("body", "") or ""

        code_change = True if all_tasks else is_code_change_task(body)
        completeness = check_completeness(body)

        findings.append({"number": number, "is_code_change_task": code_change, **completeness})

    code_change_findings = [f for f in findings if f["is_code_change_task"]]
    complete_findings = [f for f in code_change_findings if f["complete"]]

    total_cc = len(code_change_findings)
    complete_count = len(complete_findings)
    rate: float | None = round(complete_count / total_cc, 4) if total_cc > 0 else None

    return {
        "scan_date": today,
        "inclusion_rule": inclusion_rule,
        "total_input_tasks": len(tasks),
        "code_change_tasks": total_cc,
        "complete_tasks": complete_count,
        "incomplete_tasks": total_cc - complete_count,
        "task_contract_completeness_rate": rate,
        "findings": findings,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_tasks_from_file(path: str) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return _normalise_input(data, source=path)


def _normalise_input(data: Any, *, source: str = "stdin") -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "tasks" in data:
            return data["tasks"]
        if "body" in data:
            return [data]
    raise ValueError(
        f"Unrecognised input shape from {source!r}. "
        "Expected a JSON array, {\"tasks\": [...]}, or a single {\"number\", \"body\"} object."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract task contract completeness metrics for circle-1.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Input JSON: {\"tasks\": [{\"number\": N, \"body\": \"...\"}]}\n"
            "Output: task_contract_completeness_rate + per-task findings"
        ),
    )
    parser.add_argument(
        "--input", "-i",
        metavar="FILE",
        help="JSON file with task bodies ({tasks:[...]} or array or single object).",
    )
    parser.add_argument(
        "--output", "-o",
        metavar="FILE",
        help="Write JSON output to FILE instead of stdout.",
    )
    parser.add_argument(
        "--all-tasks",
        action="store_true",
        help="Include all tasks in the rate, not only classified code-change tasks.",
    )
    parser.add_argument(
        "--scan-date",
        metavar="YYYY-MM-DD",
        help="Override scan date (default: today's date).",
    )
    args = parser.parse_args()

    if args.input:
        tasks = _load_tasks_from_file(args.input)
    else:
        raw = sys.stdin.read()
        if not raw.strip():
            print(
                "Error: provide --input FILE or pipe JSON to stdin.",
                file=sys.stderr,
            )
            return 2
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"Error: invalid JSON on stdin: {exc}", file=sys.stderr)
            return 2
        tasks = _normalise_input(data)

    result = extract(tasks, all_tasks=args.all_tasks, scan_date=args.scan_date)
    out = json.dumps(result, indent=2) + "\n"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out)
        rate = result["task_contract_completeness_rate"]
        cc = result["code_change_tasks"]
        print(f"Wrote {args.output}: {cc} code-change tasks, rate={rate}")
    else:
        sys.stdout.write(out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
