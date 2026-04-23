#!/usr/bin/env python3
"""
Task contract completeness extractor — circle-1 phase 1.

Classifies code-change tasks by whether their bodies contain all four
structural contract elements defined in cooling_metrics_v0.md:

  1. verification_criteria  — non-empty "### Verification Criteria" section
  2. must_criterion         — at least one MUST (non-MUST-NOT) checkbox line
  3. must_not_criterion     — at least one MUST NOT checkbox line
  4. scope_boundaries       — non-empty "### Scope boundaries" section

A task is COMPLETE when all four elements are present.
A task is INCOMPLETE when one or more elements are absent.

Code-change scope (phase 1):
  Tasks with reward_type == "duel" are excluded from the rate calculation
  because duels are verbal debates with no repo mutation.  All other tasks
  are treated as code-change candidates.  More precise classification
  (e.g., separating research tasks) requires label metadata and is deferred
  to a later extractor version.

MUST vs MUST NOT detection:
  Both live inside the Verification Criteria section.  A MUST criterion is
  any checkbox line whose text starts with "MUST" but NOT "MUST NOT".
  A MUST NOT criterion is any checkbox line whose text starts with "MUST NOT".
  Matching is case-insensitive; checked and unchecked boxes both count.

Usage (file mode):
  python scripts/circle1/extract_contract_completeness.py \\
      --tasks tasks.json [--output report.json] [--pretty]

Usage (single body):
  python scripts/circle1/extract_contract_completeness.py \\
      --body "### Verification Criteria\\n\\n..." [--issue-id 123]

Input schema (--tasks file):
  {
    "tasks": {
      "<issue_id>": {
        "body": "<issue body string>",
        "reward_type": "<optional: duel|winner_take_all|...>"
      }
    }
  }

Output schema:
  {
    "schema_version": "1",
    "phase": "phase1",
    "scan_date": "YYYY-MM-DD",
    "definition": {
      "complete_requires": [...],
      "code_change_excludes": ["duel"],
      "must_pattern": "...",
      "must_not_pattern": "..."
    },
    "summary": {
      "total_processed": N,
      "code_change_tasks": N,
      "excluded_tasks": N,
      "complete": N,
      "incomplete": N,
      "task_contract_completeness_rate": 0.0
    },
    "findings": [
      {
        "issue_id": "...",
        "is_code_change": true,
        "excluded_reason": null,
        "is_complete": true,
        "elements": {
          "verification_criteria": true,
          "must_criterion": true,
          "must_not_criterion": true,
          "scope_boundaries": true
        },
        "missing_elements": []
      }
    ]
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from typing import Any

# --- Section parsing ---

_SECTION_RE_TEMPLATE = r"###\s+{name}\s*\n(.+?)(?=\n###|\Z)"
_EMPTY_CONTENT = frozenset(("_no response_", "none", ""))


def _parse_section(body: str, section_name: str) -> str | None:
    """Return stripped content of a ### section, or None if absent/empty."""
    pattern = re.compile(
        _SECTION_RE_TEMPLATE.format(name=re.escape(section_name)),
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(body)
    if not m:
        return None
    content = m.group(1).strip()
    if content.lower() in _EMPTY_CONTENT:
        return None
    return content


# --- Contract element detection ---

# Matches: "- [ ] MUST:" or "- [x] MUST:" but NOT "- [ ] MUST NOT:"
_MUST_RE = re.compile(
    r"(?m)^\s*-\s+\[[ xX]\]\s+MUST(?!\s+NOT)\s*:",
    re.IGNORECASE,
)

# Matches: "- [ ] MUST NOT:" or "- [x] MUST NOT:"
_MUST_NOT_RE = re.compile(
    r"(?m)^\s*-\s+\[[ xX]\]\s+MUST\s+NOT\s*:",
    re.IGNORECASE,
)


def extract_elements(body: str) -> dict[str, bool]:
    """
    Return presence/absence of the four Phase 1 contract elements.

    Keys: verification_criteria, must_criterion, must_not_criterion,
          scope_boundaries.
    """
    verification = _parse_section(body, "Verification Criteria")
    scope = _parse_section(body, "Scope boundaries")

    has_verification = verification is not None
    has_must = bool(_MUST_RE.search(verification)) if verification else False
    has_must_not = bool(_MUST_NOT_RE.search(verification)) if verification else False
    has_scope = scope is not None

    return {
        "verification_criteria": has_verification,
        "must_criterion": has_must,
        "must_not_criterion": has_must_not,
        "scope_boundaries": has_scope,
    }


# --- Code-change classification ---

_EXCLUDED_REWARD_TYPES = frozenset(("duel",))


def is_code_change(reward_type: str | None) -> tuple[bool, str | None]:
    """
    Return (is_code_change, excluded_reason).

    Phase 1 exclusion rule: duel tasks are verbal debates with no repo
    mutation and are therefore excluded from the code-change cohort.
    """
    if reward_type and reward_type.lower().strip() in _EXCLUDED_REWARD_TYPES:
        return False, "duel"
    return True, None


# --- Per-task classification ---

def classify_task(
    issue_id: str,
    body: str,
    reward_type: str | None = None,
) -> dict[str, Any]:
    """Return a single task finding dict."""
    code_change, excluded_reason = is_code_change(reward_type)
    elements = extract_elements(body)
    missing = [k for k, v in elements.items() if not v]
    complete = code_change and len(missing) == 0

    return {
        "issue_id": str(issue_id),
        "is_code_change": code_change,
        "excluded_reason": excluded_reason,
        "is_complete": complete,
        "elements": elements,
        "missing_elements": missing,
    }


# --- Batch classification ---

_COMPLETE_REQUIRES = [
    "verification_criteria",
    "must_criterion",
    "must_not_criterion",
    "scope_boundaries",
]


def classify_tasks(tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    Classify a dict of tasks and return a full report.

    ``tasks`` maps issue_id → {body: str, reward_type?: str}.
    """
    findings: list[dict[str, Any]] = []
    for issue_id, task in tasks.items():
        body = task.get("body", "")
        reward_type = task.get("reward_type")
        findings.append(classify_task(issue_id, body, reward_type))

    total = len(findings)
    excluded = sum(1 for f in findings if not f["is_code_change"])
    code_change = total - excluded
    complete = sum(1 for f in findings if f["is_complete"])
    incomplete = code_change - complete
    rate = complete / code_change if code_change > 0 else 0.0

    return {
        "schema_version": "1",
        "phase": "phase1",
        "scan_date": date.today().isoformat(),
        "definition": {
            "complete_requires": _COMPLETE_REQUIRES,
            "code_change_excludes": sorted(_EXCLUDED_REWARD_TYPES),
            "must_pattern": r"- [ ] MUST: (not MUST NOT:) in Verification Criteria",
            "must_not_pattern": r"- [ ] MUST NOT: in Verification Criteria",
        },
        "summary": {
            "total_processed": total,
            "code_change_tasks": code_change,
            "excluded_tasks": excluded,
            "complete": complete,
            "incomplete": incomplete,
            "task_contract_completeness_rate": round(rate, 4),
        },
        "findings": findings,
    }


# --- CLI ---

def _load_tasks_json(path: str) -> dict[str, dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    tasks = data.get("tasks")
    if not isinstance(tasks, dict):
        print(f"ERROR: {path}: top-level 'tasks' key must be a JSON object", file=sys.stderr)
        sys.exit(1)
    return tasks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Task contract completeness extractor (circle-1 phase 1)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tasks", metavar="FILE", help="JSON file of tasks to classify")
    group.add_argument("--body", metavar="TEXT", help="Single task body string")
    parser.add_argument("--issue-id", default="?", help="Issue ID for --body mode")
    parser.add_argument("--reward-type", default=None, help="Reward type for --body mode")
    parser.add_argument("--output", metavar="FILE", help="Write JSON report to FILE")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")

    args = parser.parse_args()

    if args.body is not None:
        tasks = {
            args.issue_id: {
                "body": args.body,
                "reward_type": args.reward_type,
            }
        }
    else:
        tasks = _load_tasks_json(args.tasks)

    report = classify_tasks(tasks)

    indent = 2 if args.pretty else None
    output_text = json.dumps(report, indent=indent, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text + "\n")
        print(f"Report written to {args.output}")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
