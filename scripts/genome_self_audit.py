#!/usr/bin/env python3
"""Genome self-audit: checks genome files are complete, consistent, and match the template.

This script goes deeper than check_genome_completeness.py (which verifies file presence and
genome_meta.json structure). genome_self_audit.py checks the *content* of AGENTS.local.md
against the base template, flagging stale template placeholders, missing sections,
wrong section order, and empty required sections.

Checks per agent:
  1. All required sections present (## Role, ## Instructions, ## Pre-submission,
     ## Examples, ## Memory)
  2. Section order matches template
  3. No stale template comments left (<!-- Your specialization... -->, etc.)
  4. Constitution block present and intact
  5. Role section is non-empty (has real content, not just the section header)
  6. Instructions section is non-empty
  7. Pre-submission checklist present (standard checklist lines)
  8. genome_meta.json agent_id matches directory name (cross-file consistency)

Exit codes:
    0  — all PASS (WARN entries do not count as failures)
    1  — one or more FAIL

Output: JSON to stdout with fields: status, checks, summary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# -------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------

_SKIP_AGENTS: set[str] = {"agent0@system"}

# Required ## sections in the order they must appear
REQUIRED_SECTIONS: tuple[str, ...] = (
    "Role",
    "Instructions",
    "Pre-submission",
    "Examples",
    "Memory",
)

# Known stale template placeholder comments that should not survive in a live genome
STALE_PLACEHOLDERS: tuple[str, ...] = (
    "<!-- Your specialization",
    "<!-- How you approach",
    "<!-- Best solutions",
    "<!-- Lessons from tasks",
    "<!-- To be filled",
    "(no content yet)",
    "<!-- Your role here",
)

# The constitution preamble must start with this North Star line
CONSTITUTION_MARKER = "North Star: Guaranteed Software Development."

# The standard pre-submission checklist item that must be present
PRESUBMISSION_CHECKLIST_ITEM = "pytest tests/ -v"


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_balances(balances_path: Path) -> dict[str, Any] | None:
    if not balances_path.exists():
        return None
    try:
        return json.loads(balances_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_sections(text: str) -> dict[str, str]:
    """Return a mapping of section name -> section body text.

    Each section starts at a `## <Name>` heading and extends until the next
    `##` heading or EOF. The constitution preamble (before the first `##`) is
    stored under the key "__constitution__".
    """
    sections: dict[str, str] = {}
    current_name = "__constitution__"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            sections[current_name] = "\n".join(current_lines).strip()
            current_name = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    sections[current_name] = "\n".join(current_lines).strip()
    return sections


def _section_order(text: str) -> list[str]:
    """Return the list of `## Section` names in their document order."""
    return [
        line[3:].strip()
        for line in text.splitlines()
        if line.startswith("## ")
    ]


# -------------------------------------------------------------------
# Per-agent checks
# -------------------------------------------------------------------


def check_agent(agent_id: str, genomes_dir: Path) -> list[dict[str, Any]]:
    """Run all content checks for one agent. Return list of result dicts."""
    results: list[dict[str, Any]] = []

    def _result(check: str, status: str, detail: str) -> dict[str, Any]:
        return {"agent": agent_id, "check": check, "status": status, "detail": detail}

    # --- Locate AGENTS.local.md ---
    agent_dir = genomes_dir / agent_id
    local_md = agent_dir / "AGENTS.local.md"

    if not local_md.is_file():
        results.append(_result(
            "agents_local_md_readable",
            "FAIL",
            f"genomes/{agent_id}/AGENTS.local.md not found — run check_genome_completeness.py first",
        ))
        return results

    try:
        text = local_md.read_text(encoding="utf-8")
    except OSError as exc:
        results.append(_result("agents_local_md_readable", "FAIL", f"Cannot read: {exc}"))
        return results

    results.append(_result("agents_local_md_readable", "PASS", "AGENTS.local.md is readable"))

    sections = _parse_sections(text)
    order = _section_order(text)

    # 1. Constitution block present
    constitution = sections.get("__constitution__", "")
    if CONSTITUTION_MARKER in constitution:
        results.append(_result(
            "constitution_present",
            "PASS",
            "Constitution block contains North Star statement",
        ))
    else:
        results.append(_result(
            "constitution_present",
            "FAIL",
            f"Constitution block missing '{CONSTITUTION_MARKER}' — genome may be truncated",
        ))

    # 2. Required sections present
    present = set(sections.keys()) - {"__constitution__"}
    missing = [s for s in REQUIRED_SECTIONS if s not in present]
    if missing:
        results.append(_result(
            "required_sections_present",
            "FAIL",
            f"Missing required sections: {missing}",
        ))
    else:
        results.append(_result(
            "required_sections_present",
            "PASS",
            f"All required sections present: {list(REQUIRED_SECTIONS)}",
        ))

    # 3. Section order matches template (only check sections that exist)
    expected_order = [s for s in REQUIRED_SECTIONS if s in present]
    required_set = set(expected_order)
    actual_order = [s for s in order if s in required_set]
    if actual_order != expected_order:
        results.append(_result(
            "section_order",
            "FAIL",
            f"Section order mismatch. Expected: {expected_order}, got: {actual_order}",
        ))
    else:
        results.append(_result(
            "section_order",
            "PASS",
            f"Section order matches template: {expected_order}",
        ))

    # 4. No stale template placeholders
    stale_found = [p for p in STALE_PLACEHOLDERS if p in text]
    if stale_found:
        results.append(_result(
            "no_stale_placeholders",
            "FAIL",
            f"Stale template placeholder(s) found: {stale_found}",
        ))
    else:
        results.append(_result(
            "no_stale_placeholders",
            "PASS",
            "No stale template placeholders found",
        ))

    # 5. Role section non-empty
    role_body = sections.get("Role", "")
    if role_body.strip():
        results.append(_result(
            "role_non_empty",
            "PASS",
            "Role section has content",
        ))
    else:
        results.append(_result(
            "role_non_empty",
            "FAIL",
            "Role section is empty — agent has no defined role",
        ))

    # 6. Instructions section non-empty
    instructions_body = sections.get("Instructions", "")
    if len(instructions_body.strip()) > 20:
        results.append(_result(
            "instructions_non_empty",
            "PASS",
            "Instructions section has content",
        ))
    else:
        results.append(_result(
            "instructions_non_empty",
            "FAIL",
            "Instructions section is empty or trivially short",
        ))

    # 7. Pre-submission checklist present
    presubmission_body = sections.get("Pre-submission", "")
    if PRESUBMISSION_CHECKLIST_ITEM in presubmission_body:
        results.append(_result(
            "presubmission_checklist",
            "PASS",
            "Pre-submission section contains standard checklist",
        ))
    else:
        results.append(_result(
            "presubmission_checklist",
            "WARN",
            f"Pre-submission section missing standard checklist item ('{PRESUBMISSION_CHECKLIST_ITEM}')",
        ))

    # 8. genome_meta.json agent_id consistency (cross-file check)
    meta_path = agent_dir / "genome_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_agent_id = meta.get("agent_id") if isinstance(meta, dict) else None
            if meta_agent_id == agent_id:
                results.append(_result(
                    "meta_agent_id_match",
                    "PASS",
                    f"genome_meta.json agent_id matches directory: {agent_id}",
                ))
            else:
                results.append(_result(
                    "meta_agent_id_match",
                    "FAIL",
                    f"genome_meta.json agent_id={meta_agent_id!r} does not match directory {agent_id!r}",
                ))
        except (json.JSONDecodeError, OSError) as exc:
            results.append(_result(
                "meta_agent_id_match",
                "FAIL",
                f"Cannot read genome_meta.json: {exc}",
            ))
    else:
        results.append(_result(
            "meta_agent_id_match",
            "WARN",
            "genome_meta.json not found — skipping cross-file consistency check",
        ))

    return results


# -------------------------------------------------------------------
# Orphan check
# -------------------------------------------------------------------


def _find_orphan_agents(
    agent_ids: set[str],
    genomes_dir: Path,
) -> list[dict[str, Any]]:
    """Warn about genome directories with no corresponding balances.json entry."""
    orphans: list[dict[str, Any]] = []
    if not genomes_dir.is_dir():
        return orphans
    for entry in sorted(genomes_dir.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name not in agent_ids and name not in _SKIP_AGENTS:
            orphans.append({
                "agent": name,
                "check": "orphan_genome",
                "status": "WARN",
                "detail": (
                    f"genomes/{name}/ exists but '{name}' "
                    "has no entry in ledger/balances.json"
                ),
            })
    return orphans


# -------------------------------------------------------------------
# Main runner
# -------------------------------------------------------------------


def run(root: Path, agents_filter: list[str] | None = None) -> tuple[dict[str, Any], bool]:
    """Run the full self-audit. Returns (report_dict, passed_bool)."""
    balances_path = root / "ledger" / "balances.json"
    genomes_dir = root / "genomes"

    if not balances_path.exists():
        return {
            "status": "FAIL",
            "checks": [],
            "summary": f"balances.json not found at {balances_path}",
        }, False

    balances = _load_balances(balances_path)
    if balances is None:
        return {
            "status": "FAIL",
            "checks": [],
            "summary": "balances.json is not valid JSON",
        }, False

    agents_data: dict[str, Any] = balances.get("agents", {})
    if not isinstance(agents_data, dict):
        return {
            "status": "FAIL",
            "checks": [],
            "summary": "balances.json 'agents' is not a dictionary",
        }, False

    all_agent_ids: set[str] = {aid for aid in agents_data if aid not in _SKIP_AGENTS}

    # Filter if requested
    if agents_filter:
        target_ids = [a for a in agents_filter if a not in _SKIP_AGENTS]
    else:
        target_ids = sorted(all_agent_ids)

    all_checks: list[dict[str, Any]] = []
    for agent_id in target_ids:
        all_checks.extend(check_agent(agent_id, genomes_dir))

    # Add orphan warnings (only when running full audit)
    if not agents_filter:
        all_checks.extend(_find_orphan_agents(all_agent_ids | _SKIP_AGENTS, genomes_dir))

    n_pass = sum(1 for c in all_checks if c["status"] == "PASS")
    n_fail = sum(1 for c in all_checks if c["status"] == "FAIL")
    n_warn = sum(1 for c in all_checks if c["status"] == "WARN")

    passed = n_fail == 0
    overall = "PASS" if passed else "FAIL"

    parts: list[str] = []
    if n_pass:
        parts.append(f"{n_pass} PASS")
    if n_fail:
        parts.append(f"{n_fail} FAIL")
    if n_warn:
        parts.append(f"{n_warn} WARN")

    summary = ", ".join(parts) if parts else "no agents checked"

    return {
        "status": overall,
        "checks": all_checks,
        "summary": summary,
    }, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit genome files for completeness, consistency, and template conformance.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    parser.add_argument(
        "--agent",
        action="append",
        dest="agents",
        metavar="AGENT_ID",
        help="Audit only this agent (can be repeated). Default: all agents.",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root, agents_filter=args.agents)

    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
