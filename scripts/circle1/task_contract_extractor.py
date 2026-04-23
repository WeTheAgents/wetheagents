#!/usr/bin/env python3
"""
Task Contract Completeness Extractor — circle-1 phase 1.

Classifies WEA code-change task bodies by contract completeness.
A complete contract has all four structural elements:

  1. must               — at least one "- [ ] MUST:" line in Verification Criteria
  2. must_not           — at least one "- [ ] MUST NOT:" line in Verification Criteria
  3. verification_criteria — the "### Verification Criteria" section is present
  4. scope_boundaries   — the "### Scope boundaries" section is present with
                          non-trivial content (not a "_No response_" placeholder)

A task is included in the code-change cohort when:
  - mechanic is not "duel"  AND at least one of:
    * "### Skills Needed" section mentions "Coding"
    * Verification Criteria text references code or test artifacts
      (pytest, test, script, .py, PR, file change, commit)

Emits machine-readable JSON with aggregate counts and per-issue findings.

Phase 1 boundary: this extractor classifies task bodies supplied as structured
input (JSON array). It does not mine full GitHub history. Wire it into broader
circle-1 checkpointing later.

Usage:
    python scripts/circle1/task_contract_extractor.py <input.json> [--scan-date YYYY-MM-DD]

    input.json must be a JSON array where each object has:
      - "number" or "issue": issue identifier (str or int)
      - "body": raw GitHub issue body text (str)
      - "mechanic": optional reward mechanic slug (str)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

# ── Regex constants ──────────────────────────────────────────────────────────

# "- [ ] MUST NOT:" or "- [x] MUST NOT:" — checked or unchecked
_MUST_NOT_LINE = re.compile(r"^\s*-\s*\[.?\]\s*MUST\s+NOT\s*:", re.MULTILINE)

# "- [ ] MUST:" — must NOT match "MUST NOT:" because literal "MUST:" ≠ "MUST NOT:"
_MUST_ONLY_LINE = re.compile(r"^\s*-\s*\[.?\]\s*MUST:", re.MULTILINE)

_SECTION_VC = re.compile(r"^###\s+Verification Criteria", re.MULTILINE | re.IGNORECASE)
_SECTION_SB = re.compile(r"^###\s+Scope boundaries", re.MULTILINE | re.IGNORECASE)
_SECTION_SKILLS = re.compile(r"^###\s+Skills Needed", re.MULTILINE | re.IGNORECASE)
_NEXT_SECTION = re.compile(r"\n###")
_PLACEHOLDER = re.compile(r"^_No response_\s*$", re.MULTILINE)

_CODING_IN_SKILLS = re.compile(r"\bCoding\b", re.IGNORECASE)
_CODE_ARTIFACT = re.compile(
    r"\b(pytest|tests?|scripts?|\.py\b|pull.request|file.chang|commit)\b",
    re.IGNORECASE,
)

# ── Section extraction ────────────────────────────────────────────────────────


def _section_text(body: str, header_re: re.Pattern[str]) -> str | None:
    """Return the text content after a section header, up to the next ###, or None."""
    m = header_re.search(body)
    if not m:
        return None
    after = body[m.end():]
    next_m = _NEXT_SECTION.search(after)
    return after[: next_m.start()] if next_m else after


# ── Element detectors ─────────────────────────────────────────────────────────


def _has_must(body: str) -> bool:
    """At least one "- [ ] MUST:" line inside the Verification Criteria section."""
    vc_text = _section_text(body, _SECTION_VC)
    if vc_text is None:
        return False
    return bool(_MUST_ONLY_LINE.search(vc_text))


def _has_must_not(body: str) -> bool:
    """At least one "- [ ] MUST NOT:" line inside the Verification Criteria section."""
    vc_text = _section_text(body, _SECTION_VC)
    if vc_text is None:
        return False
    return bool(_MUST_NOT_LINE.search(vc_text))


def _has_verification_criteria(body: str) -> bool:
    """The "### Verification Criteria" section header is present."""
    return bool(_SECTION_VC.search(body))


def _has_scope_boundaries(body: str) -> bool:
    """The "### Scope boundaries" section is present with non-trivial content."""
    text = _section_text(body, _SECTION_SB)
    if text is None:
        return False
    meaningful = [
        line for line in text.splitlines()
        if line.strip() and not _PLACEHOLDER.match(line)
    ]
    return bool(meaningful)


# ── Code-change classifier ────────────────────────────────────────────────────


def _is_code_change(body: str, mechanic: str = "") -> bool:
    """Conservative heuristic: is this a code-change task?

    Excludes: duel mechanic.
    Includes: Coding skill present, OR code/test artifacts in Verification Criteria.
    """
    if mechanic == "duel":
        return False
    skills_text = _section_text(body, _SECTION_SKILLS)
    if skills_text and _CODING_IN_SKILLS.search(skills_text):
        return True
    vc_text = _section_text(body, _SECTION_VC)
    if vc_text and _CODE_ARTIFACT.search(vc_text):
        return True
    return False


# ── Public API ────────────────────────────────────────────────────────────────

ELEMENTS = ("must", "must_not", "verification_criteria", "scope_boundaries")

_CHECKERS: dict[str, Any] = {
    "must": _has_must,
    "must_not": _has_must_not,
    "verification_criteria": _has_verification_criteria,
    "scope_boundaries": _has_scope_boundaries,
}


def classify_body(
    body: str,
    mechanic: str = "",
    issue: str = "",
) -> dict[str, Any]:
    """Classify a single task body.

    Returns a finding record:
      issue, is_code_change, complete, missing_elements, present_elements.

    A task is "complete" only when it is a code-change task AND has all four
    contract elements.  Non-code-change tasks are classified but never marked
    complete (they are excluded from the rate denominator).
    """
    is_code = _is_code_change(body, mechanic)
    present = {el: _CHECKERS[el](body) for el in ELEMENTS}
    missing = [el for el in ELEMENTS if not present[el]]
    return {
        "issue": issue,
        "is_code_change": is_code,
        "complete": is_code and not missing,
        "missing_elements": missing,
        "present_elements": [el for el in ELEMENTS if present[el]],
    }


def extract_completeness(
    issues: list[dict[str, Any]],
    scan_date: str | None = None,
) -> dict[str, Any]:
    """Run the extractor over a list of issue dicts.

    Each dict must have "number" or "issue" (str or int) and "body" (str).
    Optional: "mechanic" (str).

    Returns a result dict with:
      scan_date, phase, definition, total_inspected, code_change_count,
      complete_count, incomplete_count, task_contract_completeness_rate, findings.

    task_contract_completeness_rate is None when no code-change tasks are found.
    """
    findings = [
        classify_body(
            body=str(item.get("body") or ""),
            mechanic=str(item.get("mechanic") or ""),
            issue=str(item.get("number") or item.get("issue") or ""),
        )
        for item in issues
    ]
    code_change = [f for f in findings if f["is_code_change"]]
    complete = [f for f in code_change if f["complete"]]
    rate = round(len(complete) / len(code_change), 4) if code_change else None

    return {
        "scan_date": scan_date or date.today().isoformat(),
        "phase": "phase-1",
        "definition": (
            "code-change tasks with MUST + MUST NOT + verification_criteria + "
            "scope_boundaries / all code-change tasks in cohort"
        ),
        "total_inspected": len(issues),
        "code_change_count": len(code_change),
        "complete_count": len(complete),
        "incomplete_count": len(code_change) - len(complete),
        "task_contract_completeness_rate": rate,
        "findings": findings,
    }


# ── CLI entry point ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    scan_date = None

    if "--scan-date" in args:
        idx = args.index("--scan-date")
        if idx + 1 >= len(args):
            print("ERROR: --scan-date requires a value", file=sys.stderr)
            return 1
        scan_date = args[idx + 1]
        del args[idx: idx + 2]

    if not args:
        print(
            "Usage: task_contract_extractor.py <input.json> [--scan-date YYYY-MM-DD]",
            file=sys.stderr,
        )
        print(
            "  input.json: JSON array of {number/issue, body, mechanic?}",
            file=sys.stderr,
        )
        return 1

    input_path = Path(args[0])
    if not input_path.exists():
        print(f"ERROR: {input_path} not found", file=sys.stderr)
        return 1

    try:
        issues = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON in {input_path}: {exc}", file=sys.stderr)
        return 1

    if not isinstance(issues, list):
        print("ERROR: input must be a JSON array of issue objects", file=sys.stderr)
        return 1

    result = extract_completeness(issues, scan_date=scan_date)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
