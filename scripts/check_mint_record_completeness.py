#!/usr/bin/env python3
"""
Mint Record Completeness Validator.

Validates every entry in ledger/trajectory_mints.json mints[] array
has all 5 mandatory gauntlet fields as non-empty strings:
    frontier_closed, artifact, evidence, made_redundant, redundancy_proof

Output: JSON with status (PASS/FAIL), checks (per-mint results), summary.
Exit 0 if all mints are complete, exit 1 on any violation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MANDATORY_FIELDS = [
    "frontier_closed",
    "artifact",
    "evidence",
    "made_redundant",
    "redundancy_proof",
]

# (trajectory, slot) tuples of mints created before `wea gauntlet mint`
# enforced the five-mandatory-fields rule. These nine records (gauntlet cycle
# 12, all undated — no `accepted_at` and no `idem_key`) are real historical
# entries; per the Stabilization sprint anti-gaming rules we do not
# cosmetically backfill the fields into ledger/trajectory_mints.json. Instead,
# we grandfather them via this explicit allowlist so the checker continues to
# fail on any NEW mint that omits the fields.
#
# Reconciliation path: a future Agent0-mediated ledger write can reconstruct
# `made_redundant` / `redundancy_proof` from the merged PRs and append a
# correction entry, at which point these (trajectory, slot) tuples can be
# removed from this list. See issue #899 for context.
PRE_RULE_GRANDFATHERED_SLOTS: frozenset[tuple[str, int]] = frozenset({
    ("T2", 12),
    ("T1", 13),
    ("T4", 11),
    ("T3", 12),
    ("T2", 13),
    ("T5", 12),
    ("T4", 12),
    ("T1", 14),
    ("T6", 15),
})


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _check_mints(mints: list[Any]) -> list[dict[str, Any]]:
    """Return per-mint validation results.

    Each result has: idem_key, trajectory, slot, status, missing_fields.
    A field is considered missing if it is absent, not a string, or blank.
    """
    checks: list[dict[str, Any]] = []
    for mint in mints:
        if not isinstance(mint, dict):
            checks.append(
                {
                    "idem_key": "(unknown)",
                    "trajectory": "(unknown)",
                    "slot": "(unknown)",
                    "status": "FAIL",
                    "missing_fields": ["(entry is not a dict)"],
                }
            )
            continue

        idem_key = mint.get("idem_key", "(missing idem_key)")
        trajectory = mint.get("trajectory", "(unknown)")
        slot = mint.get("slot", "(unknown)")

        missing = [
            field
            for field in MANDATORY_FIELDS
            if not isinstance(mint.get(field), str) or not mint[field].strip()
        ]

        if missing and (trajectory, slot) in PRE_RULE_GRANDFATHERED_SLOTS:
            checks.append(
                {
                    "idem_key": idem_key,
                    "trajectory": trajectory,
                    "slot": slot,
                    "status": "GRANDFATHERED",
                    "missing_fields": missing,
                    "reason": "pre-rule mint (cycle 12): mandatory-fields rule postdated this record",
                }
            )
            continue

        checks.append(
            {
                "idem_key": idem_key,
                "trajectory": trajectory,
                "slot": slot,
                "status": "FAIL" if missing else "PASS",
                "missing_fields": missing,
            }
        )

    return checks


def run(root: Path | None = None) -> dict[str, Any]:
    """Load trajectory_mints.json from root and validate all mint records.

    Returns a report dict with status, checks, summary.
    Accepts an optional root path for testing; defaults to repo root.
    """
    repo = root if root is not None else _repo_root()
    path = repo / "ledger" / "trajectory_mints.json"

    if not path.exists():
        return {
            "status": "FAIL",
            "checks": [],
            "summary": f"trajectory_mints.json not found at {path}",
        }

    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        return {
            "status": "FAIL",
            "checks": [],
            "summary": f"trajectory_mints.json is not valid JSON: {exc}",
        }

    mints = data.get("mints")
    if mints is None:
        return {
            "status": "FAIL",
            "checks": [],
            "summary": "trajectory_mints.json missing 'mints' key",
        }
    if not isinstance(mints, list):
        return {
            "status": "FAIL",
            "checks": [],
            "summary": f"'mints' is not a list (got {type(mints).__name__})",
        }

    checks = _check_mints(mints)

    n_pass = sum(1 for c in checks if c["status"] == "PASS")
    n_fail = sum(1 for c in checks if c["status"] == "FAIL")
    n_grandfathered = sum(1 for c in checks if c["status"] == "GRANDFATHERED")
    overall = "PASS" if n_fail == 0 else "FAIL"
    grandfathered_suffix = (
        f", {n_grandfathered} grandfathered (pre-rule)" if n_grandfathered else ""
    )
    summary = (
        f"{len(checks)} mints checked: {n_pass} complete, {n_fail} incomplete"
        f"{grandfathered_suffix}"
    )

    return {
        "status": overall,
        "checks": checks,
        "summary": summary,
    }


def main() -> int:
    report = run()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
