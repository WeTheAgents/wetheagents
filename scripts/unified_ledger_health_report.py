#!/usr/bin/env python3
"""
Unified ledger health report.

Runs every scripts/check_*.py validation, groups the results into safety
domains, and renders a human-readable dashboard for operators.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from run_all_checks import discover_checks, run_check

CRITICAL_CHECKS = {
    "check_cross_file_integrity.py",
    "check_history_reconciliation.py",
    "check_idem_consistency.py",
    "check_invariant.py",
    "check_issue_ledger_sync.py",
    "check_ledger_schema.py",
    "check_payment_completeness.py",
    "check_task_index_consistency.py",
    "check_trajectory_mint_consistency.py",
}

DOMAINS: list[tuple[str, tuple[str, ...]]] = [
    (
        "Economy",
        (
            "check_invariant.py",
            "check_payment_completeness.py",
            "check_trajectory_mint_consistency.py",
        ),
    ),
    (
        "Ledger Structure",
        (
            "check_cross_file_integrity.py",
            "check_history_reconciliation.py",
            "check_ledger_schema.py",
        ),
    ),
    (
        "Task Lifecycle",
        (
            "check_claim_ttl.py",
            "check_concurrent_claims.py",
            "check_issue_ledger_sync.py",
            "check_stale_escrows.py",
            "check_task_escrow_sync.py",
            "check_task_format.py",
            "check_task_index_consistency.py",
        ),
    ),
    (
        "Idempotency And Protocol",
        (
            "check_idem_consistency.py",
            "check_idem_keys.py",
            "check_pr_scope.py",
        ),
    ),
    (
        "Operational Hygiene",
        (
            "check_diary_incidents.py",
            "check_doc_sync.py",
            "check_genome_naming.py",
            "check_genome_trailer.py",
            "check_incident_correlator.py",
        ),
    ),
]

DOMAIN_BY_SCRIPT = {
    script_name: domain
    for domain, script_names in DOMAINS
    for script_name in script_names
}

STATUS_RANK = {"fail": 4, "blocked": 3, "skip": 2, "pass": 1}
DOMAIN_ORDER = {"FAIL": 4, "BLOCKED": 3, "PARTIAL": 2, "PASS": 1}


def load_description(script: Path) -> str:
    """Return the first non-empty line of a script module docstring."""
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return ""

    docstring = ast.get_docstring(tree) or ""
    for line in docstring.splitlines():
        text = line.strip()
        if text:
            return text.rstrip(".")
    return ""


def _is_blocked(result: dict[str, Any]) -> bool:
    if result.get("status") != "fail":
        return False
    haystack = "\n".join([
        str(result.get("first_line") or ""),
        str(result.get("stdout") or ""),
        str(result.get("stderr") or ""),
    ]).lower()
    blocked_signals = (
        "detected dubious ownership",
        "error fetching github issues",
        "an attempt was made to access a socket",
        "connectex",
        "command '['gh'",
    )
    return any(signal in haystack for signal in blocked_signals)


def _overall_status(results: list[dict[str, Any]]) -> str:
    if any(
        r["status"] == "fail" and not r.get("blocked") and r["script"] in CRITICAL_CHECKS
        for r in results
    ):
        return "CRITICAL"
    if any(r["status"] == "fail" and not r.get("blocked") for r in results):
        return "DEGRADED"
    if any(r["status"] in {"blocked", "skip"} for r in results):
        return "PARTIAL"
    return "HEALTHY"


def _domain_status(items: list[dict[str, Any]]) -> str:
    if any(item["status"] == "fail" for item in items):
        return "FAIL"
    if any(item["status"] == "blocked" for item in items):
        return "BLOCKED"
    if any(item["status"] == "skip" for item in items):
        return "PARTIAL"
    return "PASS"


def build_report(results: list[dict[str, Any]], descriptions: dict[str, str]) -> dict[str, Any]:
    """Build a dashboard-friendly report model from raw check results."""
    enriched: list[dict[str, Any]] = []
    for result in results:
        item = dict(result)
        blocked = _is_blocked(item)
        if blocked:
            item["status"] = "blocked"
        item["blocked"] = blocked
        item["description"] = descriptions.get(result["script"], "")
        item["domain"] = DOMAIN_BY_SCRIPT.get(result["script"], "Additional Checks")
        enriched.append(item)

    domains: list[dict[str, Any]] = []
    for domain_name, _script_names in DOMAINS:
        items = [item for item in enriched if item["domain"] == domain_name]
        if not items:
            continue
        items.sort(key=lambda item: (-STATUS_RANK[item["status"]], item["script"]))
        domains.append({
            "name": domain_name,
            "status": _domain_status(items),
            "total": len(items),
            "passed": sum(1 for item in items if item["status"] == "pass"),
            "failed": [item["script"] for item in items if item["status"] == "fail"],
            "blocked": [item["script"] for item in items if item["status"] == "blocked"],
            "skipped": [item["script"] for item in items if item["status"] == "skip"],
        })

    extra_items = [item for item in enriched if item["domain"] == "Additional Checks"]
    if extra_items:
        extra_items.sort(key=lambda item: (-STATUS_RANK[item["status"]], item["script"]))
        domains.append({
            "name": "Additional Checks",
            "status": _domain_status(extra_items),
            "total": len(extra_items),
            "passed": sum(1 for item in extra_items if item["status"] == "pass"),
            "failed": [item["script"] for item in extra_items if item["status"] == "fail"],
            "blocked": [item["script"] for item in extra_items if item["status"] == "blocked"],
            "skipped": [item["script"] for item in extra_items if item["status"] == "skip"],
        })

    domains.sort(key=lambda item: (-DOMAIN_ORDER.get(item["status"], 0), item["name"]))

    failed = [item for item in enriched if item["status"] == "fail"]
    blocked = [item for item in enriched if item["status"] == "blocked"]
    skipped = [item for item in enriched if item["status"] == "skip"]
    passed = [item for item in enriched if item["status"] == "pass"]

    return {
        "overall_status": _overall_status(enriched),
        "total": len(enriched),
        "passed": len(passed),
        "failed": len(failed),
        "blocked": len(blocked),
        "skipped": len(skipped),
        "domains": domains,
        "results": enriched,
        "failed_checks": failed,
        "blocked_checks": blocked,
        "skipped_checks": skipped,
    }


def render_report(report: dict[str, Any]) -> str:
    """Render a human-readable ledger safety dashboard."""
    status = report["overall_status"]
    lines = [
        "=" * 72,
        "UNIFIED LEDGER HEALTH REPORT",
        "=" * 72,
        f"Overall safety status: {status}",
        (
            f"Checks: {report['passed']} passed, {report['failed']} failed, "
            f"{report['blocked']} blocked, "
            f"{report['skipped']} skipped, {report['total']} total"
        ),
        "",
        "Domain dashboard:",
    ]

    for domain in report["domains"]:
        summary = f"{domain['passed']}/{domain['total']} passing"
        if domain["failed"]:
            summary += " | failing: " + ", ".join(domain["failed"])
        elif domain["blocked"]:
            summary += " | blocked: " + ", ".join(domain["blocked"])
        elif domain["skipped"]:
            summary += " | skipped: " + ", ".join(domain["skipped"])
        lines.append(f"- {domain['name']}: {domain['status']} ({summary})")

    lines.append("")
    failed_checks = report["failed_checks"]
    if failed_checks:
        lines.append("Immediate attention:")
        for item in sorted(failed_checks, key=lambda entry: entry["script"]):
            desc = item["description"] or "No description"
            lines.append(f"- {item['script']}: {desc}")
            lines.append(f"  Signal: {item['first_line']}")
    else:
        lines.append("Immediate attention:")
        lines.append("- None. No failing checks detected.")

    lines.append("")
    blocked_checks = report["blocked_checks"]
    if blocked_checks:
        lines.append("Environment-blocked checks:")
        for item in sorted(blocked_checks, key=lambda entry: entry["script"]):
            lines.append(f"- {item['script']}: {item['first_line']}")
    else:
        lines.append("Environment-blocked checks:")
        lines.append("- None.")

    lines.append("")
    skipped_checks = report["skipped_checks"]
    if skipped_checks:
        lines.append("Context-only checks skipped:")
        for item in sorted(skipped_checks, key=lambda entry: entry["script"]):
            lines.append(f"- {item['script']}: {item['first_line']}")
    else:
        lines.append("Context-only checks skipped:")
        lines.append("- None.")

    lines.append("")
    lines.append("Operator note:")
    if status == "CRITICAL":
        lines.append("- Core ledger guarantees are failing. Freeze risky writes and investigate failing checks first.")
    elif status == "DEGRADED":
        lines.append("- Non-core safety checks are failing. Review the failing domains before the next settlement cycle.")
    elif status == "PARTIAL":
        lines.append("- Core checks did not fail locally, but some checks were blocked by environment or need extra CI context.")
    else:
        lines.append("- All discovered checks passed. Ledger safety surface looks healthy from local verification.")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a unified ledger safety dashboard")
    parser.add_argument(
        "--scripts-dir",
        default=Path(__file__).resolve().parent,
        type=Path,
        help="Directory containing check_*.py scripts",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Emit the report model as JSON",
    )
    args = parser.parse_args(argv)

    scripts_dir = Path(args.scripts_dir).resolve()
    checks = discover_checks(scripts_dir)
    if not checks:
        message = f"No check_*.py scripts found in {scripts_dir}"
        payload = {"error": message, "overall_status": "CRITICAL", "results": []}
        print(json.dumps(payload, indent=2) if args.output_json else message)
        return 1

    descriptions = {script.name: load_description(script) for script in checks}
    results = [run_check(script) for script in checks]
    report = build_report(results, descriptions)

    if args.output_json:
        print(json.dumps(report, indent=2))
    else:
        print(render_report(report))

    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
