#!/usr/bin/env python3
"""Multi-check failure incident correlator.

Runs all canonical WeTheAgents health checks, collects results, and — when
two or more checks fail — correlates failures using known dependency chains
to suggest a root-cause investigation order.

Exit codes:
    0 — all runnable checks passed
    1 — one or more checks failed (or error)

Usage:
    python scripts/check_incident_correlator.py [--root PATH] [--json-only]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

# Each check specifies:
#   name        — canonical short name, used in correlation rules
#   script      — path relative to repo root (None = check not yet implemented)
#   args        — extra CLI args appended after --root <root>
#   root_arg    — flag name to pass the repo root (None = no root arg)
#
# Checks are executed in list order; that order is also the tiebreak for
# investigation ordering when the dependency graph doesn't fully determine it.

_CHECK_REGISTRY: list[dict[str, Any]] = [
    {
        "name": "idem_consistency",
        "script": None,  # not yet implemented
        "root_arg": "--root",
        "args": [],
    },
    {
        "name": "idem_keys",
        "script": None,  # requires specific keys; no sweep mode
        "root_arg": None,
        "args": [],
    },
    {
        "name": "history_reconciliation",
        "script": None,  # not yet implemented
        "root_arg": "--root",
        "args": [],
    },
    {
        "name": "stale_escrows",
        "script": "scripts/check_stale_escrows.py",
        "root_arg": "--root",
        "args": [],
    },
    {
        "name": "task_escrow_sync",
        "script": "scripts/check_task_escrow_sync.py",
        "root_arg": "--root",
        "args": [],
    },
    {
        "name": "invariant",
        "script": "scripts/check_invariant.py",
        "root_arg": "--root",
        "args": [],
    },
]

# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------
# Maps check_name → list of checks that are *upstream* (potential root causes).
# Reading: "check X can fail *because* of check Y" → Y is in DEPS[X].
#
# Known chains:
#   idem_consistency → idem_keys → invariant
#   stale_escrows   → task_escrow_sync → invariant
#   history_reconciliation → invariant

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "idem_keys": ["idem_consistency"],
    "task_escrow_sync": ["stale_escrows"],
    "invariant": ["idem_keys", "idem_consistency", "task_escrow_sync", "history_reconciliation"],
}

# Human-readable description for each dependency edge, keyed as (upstream, downstream).
EDGE_LABELS: dict[tuple[str, str], str] = {
    ("idem_consistency", "idem_keys"): (
        "idem_consistency failure can cause idem_keys violations "
        "(inconsistent key records corrupt the idem store)"
    ),
    ("idem_consistency", "invariant"): (
        "idem_consistency failure can cause invariant failure "
        "(inconsistent idem records may allow duplicate operations that inflate supply)"
    ),
    ("idem_keys", "invariant"): (
        "idem_keys failure can cause invariant failure "
        "(duplicate keys allow ledger operations to replay, breaking supply conservation)"
    ),
    ("stale_escrows", "task_escrow_sync"): (
        "stale_escrows failure can cause task_escrow_sync failure "
        "(frozen escrows that should have been returned show as orphaned active escrows)"
    ),
    ("task_escrow_sync", "invariant"): (
        "task_escrow_sync failure can cause invariant failure "
        "(escrow/task mismatch leads to balance + escrow != 10000 + minted)"
    ),
    ("history_reconciliation", "invariant"): (
        "history_reconciliation failure can cause invariant failure "
        "(unreconciled transactions leave the supply equation unbalanced)"
    ),
}

# Status constants
STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"   # script not implemented / not runnable in sweep mode
STATUS_ERROR = "ERROR"  # script exists but subprocess raised an OS error


# ---------------------------------------------------------------------------
# Running checks
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parent.parent


def run_check(check: dict[str, Any], root: Path, scripts_root: Path = _REPO_ROOT) -> dict[str, Any]:
    """Execute a single check and return its result dict.

    Args:
        check:        Registry entry for the check.
        root:         Ledger root — passed as --root to the check script.
        scripts_root: Directory tree that contains the check scripts.
                      Defaults to the repo root detected from this file's location.
                      Separating this from ``root`` lets tests point at a
                      real scripts/ directory while using a tmp ledger.
    """
    name = check["name"]
    script_rel = check["script"]

    if script_rel is None:
        return {
            "name": name,
            "script": None,
            "status": STATUS_SKIP,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "skip_reason": "script not implemented",
        }

    script_path = scripts_root / script_rel
    if not script_path.exists():
        return {
            "name": name,
            "script": script_rel,
            "status": STATUS_SKIP,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "skip_reason": f"script not found at {script_rel}",
        }

    cmd = [sys.executable, str(script_path)]
    if check["root_arg"]:
        cmd += [check["root_arg"], str(root)]
    cmd += check["args"]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "name": name,
            "script": script_rel,
            "status": STATUS_ERROR,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "skip_reason": None,
        }

    status = STATUS_PASS if proc.returncode == 0 else STATUS_FAIL
    return {
        "name": name,
        "script": script_rel,
        "status": status,
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "skip_reason": None,
    }


def run_all_checks(root: Path, scripts_root: Path = _REPO_ROOT) -> list[dict[str, Any]]:
    """Run every check in the registry and return result list."""
    return [run_check(check, root, scripts_root) for check in _CHECK_REGISTRY]


# ---------------------------------------------------------------------------
# Correlation engine
# ---------------------------------------------------------------------------


def correlate_failures(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Correlate failures when 2+ checks fail.

    Returns a correlation dict, or None if fewer than 2 checks failed.
    """
    failed = {r["name"] for r in results if r["status"] in (STATUS_FAIL, STATUS_ERROR)}

    if len(failed) < 2:
        return None

    # Red-team fix: If all known checks fail simultaneously, attribute to invariant (graph root)
    known_failed = {name for name in failed if any(name == c["name"] for c in _CHECK_REGISTRY)}
    if len(known_failed) == len(_CHECK_REGISTRY):
        root_causes = ["invariant"]
    else:
        # For each failed check, find which of its upstream checks are also failing.
        # A check is a root cause when none of its upstream checks are failing.
        root_causes = []
        for check_name in failed:
            upstream = DEPENDENCY_GRAPH.get(check_name, [])
            failing_upstream = [u for u in upstream if u in failed]
            if not failing_upstream:
                root_causes.append(check_name)

    # Build investigation order: topological traversal starting from root causes.
    investigation_order = _topological_order(failed, root_causes)

    # Collect which dependency rules were active (both ends failing).
    rules_applied: list[str] = []
    for (upstream, downstream), label in EDGE_LABELS.items():
        if upstream in failed and downstream in failed:
            rules_applied.append(label)

    return {
        "root_causes": sorted(root_causes),
        "investigation_order": investigation_order,
        "rules_applied": rules_applied,
    }


def _topological_order(failed: set[str], root_causes: list[str]) -> list[str]:
    """Return a topological ordering of failed checks, roots first.

    Uses a simple BFS from root causes through the dependency graph
    (following edges in the downstream direction).
    """
    # Build downstream adjacency for failed nodes only.
    downstream: dict[str, list[str]] = {name: [] for name in failed}
    for child, parents in DEPENDENCY_GRAPH.items():
        if child not in failed:
            continue
        for parent in parents:
            if parent in failed:
                downstream[parent].append(child)

    # BFS from root causes.
    visited: list[str] = []
    seen: set[str] = set()
    queue = sorted(root_causes)  # deterministic starting order

    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        visited.append(node)
        for child in sorted(downstream.get(node, [])):
            if child not in seen:
                queue.append(child)

    # Append any remaining failed nodes not reachable from root causes
    # (handles disconnected failures).
    for name in sorted(failed):
        if name not in seen:
            visited.append(name)

    return visited


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_report(
    results: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    """Build the full structured incident report."""
    failed_names = [r["name"] for r in results if r["status"] in (STATUS_FAIL, STATUS_ERROR)]
    overall = "PASS" if not failed_names else "INCIDENT"
    correlation = correlate_failures(results)

    return {
        "version": 1,
        "generated_at": generated_at,
        "overall_status": overall,
        "failed_count": len(failed_names),
        "failed_checks": failed_names,
        "check_results": results,
        "correlation": correlation,
    }


# ---------------------------------------------------------------------------
# Human-readable output
# ---------------------------------------------------------------------------


def print_human_report(report: dict[str, Any]) -> None:
    """Print a concise human-readable summary to stdout."""
    print(f"\nIncident Correlator — {report['generated_at']}")
    print("=" * 60)

    for r in report["check_results"]:
        name = r["name"]
        status = r["status"]
        script = r["script"] or "(no script)"
        if status == STATUS_SKIP:
            reason = r.get("skip_reason", "")
            print(f"  SKIP  {name:<25} — {reason}")
        elif status == STATUS_PASS:
            print(f"  PASS  {name}")
        elif status == STATUS_FAIL:
            print(f"  FAIL  {name}")
        else:
            print(f"  ERROR {name:<25} — {r['stderr'][:80]}")

    print()
    overall = report["overall_status"]
    failed = report["failed_count"]

    if overall == "PASS":
        print(f"Status: PASS — all runnable checks passed.")
        return

    print(f"Status: INCIDENT — {failed} check(s) failed.")

    corr = report.get("correlation")
    if corr:
        print()
        print("Root cause candidates:")
        for rc in corr["root_causes"]:
            print(f"  → {rc}")
        print()
        print("Recommended investigation order:")
        for i, name in enumerate(corr["investigation_order"], 1):
            print(f"  {i}. {name}")
        if corr["rules_applied"]:
            print()
            print("Correlation rules applied:")
            for rule in corr["rules_applied"]:
                print(f"  • {rule}")
    else:
        # Single failure — no correlation needed.
        print("No multi-check correlation (fewer than 2 failures).")
        print(f"Investigate: {report['failed_checks']}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-check failure incident correlator"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect from script location)",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Emit only JSON report, suppress human-readable summary",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = (args.root or Path(__file__).resolve().parent.parent).resolve()

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = run_all_checks(root)
    report = build_report(results, generated_at)

    print(json.dumps(report, indent=2))

    if not args.json_only:
        print_human_report(report)

    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
