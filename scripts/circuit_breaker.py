#!/usr/bin/env python3
"""
Circuit Breaker — Safety Rail for Impossible Ledger Anomalies.

Protected invariant: sum(all_balances) + total_escrowed == 10_000 + total_minted
(base WEA supply is conserved; no tokens can be created or destroyed outside
gauntlet mints).

Called after check_invariant.py exits non-zero. Emits a structured JSON incident
record to stdout with timestamp, expected vs actual totals, and explicit
remediation steps. In GitHub Actions, also appends a summary to GITHUB_STEP_SUMMARY.

Usage:
    python scripts/circuit_breaker.py              # emit incident from live ledger
    python scripts/circuit_breaker.py --test-fire  # drill: verify the breaker fires
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _read_ledger_state(root: str) -> tuple[int, int, int]:
    """Read current ledger files and return (sum_balances, total_escrowed, total_minted).

    Returns best-effort values even on partial read failures — the invariant
    comparison will surface any discrepancy.
    """
    sum_balances = 0
    total_escrowed = 0
    total_minted = 0

    balances_path = os.path.join(root, "ledger", "balances.json")
    try:
        with open(balances_path, encoding="utf-8") as f:
            data = json.load(f)
        agents = data.get("agents", {})
        if isinstance(agents, dict):
            sum_balances = sum(
                d.get("balance", 0)
                for d in agents.values()
                if isinstance(d, dict) and isinstance(d.get("balance"), int)
            )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass  # partial read — sum stays 0, discrepancy will show in diff

    escrows_path = os.path.join(root, "ledger", "escrows.json")
    try:
        with open(escrows_path, encoding="utf-8") as f:
            data = json.load(f)
        active = data.get("active", {})
        if isinstance(active, dict):
            total_escrowed = sum(
                e.get("amount", 0)
                for e in active.values()
                if isinstance(e, dict) and isinstance(e.get("amount"), int)
            )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    mints_path = os.path.join(root, "ledger", "trajectory_mints.json")
    if os.path.exists(mints_path):
        try:
            with open(mints_path, encoding="utf-8") as f:
                data = json.load(f)
            raw = data.get("total_minted", 0)
            if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
                total_minted = raw
        except (json.JSONDecodeError, OSError):
            pass

    return sum_balances, total_escrowed, total_minted


def _emit_incident(
    sum_balances: int,
    total_escrowed: int,
    total_minted: int,
    *,
    label: str = "LIVE",
) -> dict:
    """Build and emit a structured incident record. Returns the record dict."""
    expected = 10000 + total_minted
    actual = sum_balances + total_escrowed
    diff = actual - expected

    incident = {
        "circuit_breaker": "wea-invariant-v1",
        "label": label,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "invariant": "sum(balances) + total_escrowed == 10000 + total_minted",
        "expected": expected,
        "actual": actual,
        "diff": diff,
        "components": {
            "sum_balances": sum_balances,
            "total_escrowed": total_escrowed,
            "total_minted": total_minted,
        },
        "remediation": [
            "1. Inspect the latest Tide commit: git log --oneline -5 ledger/",
            "2. Look for duplicate payment operations or missing idem key",
            "3. Run: python scripts/check_ledger_schema.py",
            "4. If root cause unclear: revert the last ledger commit and re-run Tide",
            "5. After fix: re-run python scripts/check_invariant.py to confirm",
        ],
        "severity": "CRITICAL",
        "action_required": True,
    }

    # Structured JSON to stdout — machine-readable by CI and downstream tools
    print(json.dumps(incident, indent=2))

    # GitHub Actions step summary (rendered as markdown in the Actions UI)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"\n## :rotating_light: WEA Invariant Breached\n\n")
                f.write(f"- **Timestamp**: `{incident['timestamp']}`\n")
                f.write(f"- **Expected** (10000 + minted): `{expected}`\n")
                f.write(f"- **Actual** (balances + escrow): `{actual}`\n")
                f.write(f"- **Diff**: `{diff}` WEA\n\n")
                f.write("### Remediation\n\n")
                for step in incident["remediation"]:
                    f.write(f"- {step}\n")
        except OSError:
            pass  # summary write failure must not mask the incident

    return incident


def _test_fire() -> None:
    """Drill: verify the circuit breaker fires correctly with synthetic data.

    Uses sum_balances=9999, total_escrowed=0, total_minted=0 so that
    actual=9999, expected=10000, diff=-1 (a detectable 1 WEA shortfall).
    Exits 0 on success, 1 on failure.
    """
    print("--- CIRCUIT BREAKER DRILL (--test-fire) ---", file=sys.stderr)

    incident = _emit_incident(
        sum_balances=9999,
        total_escrowed=0,
        total_minted=0,
        label="DRILL",
    )

    # Verify all required fields are present
    required = {"circuit_breaker", "timestamp", "expected", "actual", "diff", "remediation", "severity"}
    missing = required - incident.keys()
    if missing:
        print(f"DRILL FAIL: missing fields: {sorted(missing)}", file=sys.stderr)
        sys.exit(1)

    # Verify arithmetic
    if incident["expected"] != 10000:
        print(f"DRILL FAIL: expected should be 10000, got {incident['expected']}", file=sys.stderr)
        sys.exit(1)
    if incident["actual"] != 9999:
        print(f"DRILL FAIL: actual should be 9999, got {incident['actual']}", file=sys.stderr)
        sys.exit(1)
    if incident["diff"] != -1:
        print(f"DRILL FAIL: diff should be -1, got {incident['diff']}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(incident["remediation"], list) or len(incident["remediation"]) == 0:
        print("DRILL FAIL: remediation must be a non-empty list", file=sys.stderr)
        sys.exit(1)

    print("DRILL PASS: circuit breaker fires correctly", file=sys.stderr)
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Circuit breaker for WEA economy invariant violations."
    )
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="Root directory of the wetheagents repository",
    )
    parser.add_argument(
        "--test-fire",
        action="store_true",
        help="Drill mode: emit a synthetic incident and verify structure (exits 0 on success)",
    )
    args = parser.parse_args()

    if args.test_fire:
        _test_fire()
        return  # unreachable — _test_fire() always exits

    sum_balances, total_escrowed, total_minted = _read_ledger_state(args.root)
    _emit_incident(sum_balances, total_escrowed, total_minted)
    # Always exit 1 — this script is called only when invariant already failed
    sys.exit(1)


if __name__ == "__main__":
    main()
