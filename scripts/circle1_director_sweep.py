#!/usr/bin/env python3
"""Circle-1 director sweep (offline-friendly).

This is a thin orchestrator around existing checkers/reports so Agent0 can run a
single command and get a compact "temperature" snapshot even when GitHub access
is blocked.

It does NOT mutate the ledger.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _run(cmd: list[str], *, cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "output": proc.stdout,
    }


def _parse_json_report(output: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(payload, dict):
        return payload
    return None


def build_sweep(repo_root: Path, *, limit: int) -> dict[str, Any]:
    python = sys.executable

    invariant = _run([python, "scripts/check_invariant.py"], cwd=repo_root)
    escrow_sync = _run([python, "scripts/check_task_escrow_sync.py"], cwd=repo_root)
    stale_open = _run(
        [python, "scripts/report_task_index_stale_open.py", "--fail", "--limit", str(limit)],
        cwd=repo_root,
    )
    drift_json = _run(
        [python, "scripts/report_task_index_drift.py", "--json", "--limit", str(limit)],
        cwd=repo_root,
    )

    drift_report = _parse_json_report(drift_json["output"])

    drift_counts: dict[str, int] = {}
    if drift_report:
        drift_block = drift_report.get("drift", {}) or {}
        for key, value in drift_block.items():
            if isinstance(value, dict) and isinstance(value.get("count"), int):
                drift_counts[str(key)] = int(value["count"])

    has_drift = any(
        [
            invariant["returncode"] != 0,
            escrow_sync["returncode"] != 0,
            stale_open["returncode"] != 0,
            any(v > 0 for v in drift_counts.values()),
        ]
    )

    recommended_next_action = (
        "Run GitHub-connected task-index reconciliation (close or re-escrow stale open tasks) "
        "then re-run `python scripts/check_task_escrow_sync.py`."
        if has_drift
        else "No action: drift checks are clean."
    )

    return {
        "repo_root": str(repo_root),
        "has_drift": has_drift,
        "recommended_next_action": recommended_next_action,
        "checks": {
            "check_invariant": invariant,
            "check_task_escrow_sync": escrow_sync,
            "report_task_index_stale_open": stale_open,
            "report_task_index_drift_json": drift_json,
        },
        "parsed": {
            "task_index_drift_counts": drift_counts,
            "task_index_drift_report": drift_report,
        },
    }


def _print_human(sweep: dict[str, Any]) -> None:
    checks = sweep["checks"]
    print(f"has_drift={sweep['has_drift']}")

    drift_counts: dict[str, int] = sweep["parsed"]["task_index_drift_counts"] or {}
    if drift_counts:
        print("task_index_drift_counts:")
        for key in sorted(drift_counts.keys()):
            print(f"  - {key}={drift_counts[key]}")

    print("")
    print("returncodes:")
    for name in [
        "check_invariant",
        "check_task_escrow_sync",
        "report_task_index_stale_open",
        "report_task_index_drift_json",
    ]:
        print(f"  - {name}={checks[name]['returncode']}")

    print("")
    print(f"next={sweep['recommended_next_action']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an offline Circle-1 director sweep.")
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root (default: .)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max sample size passed to underlying reports (default: 20).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a compact human summary.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional path to write the JSON sweep payload (UTF-8). "
        "Useful on Windows where shell redirects are easy to misquote. "
        "Implies JSON output.",
    )
    parser.add_argument(
        "--fail",
        action="store_true",
        help="Exit non-zero when drift is detected (default: false).",
    )
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    repo_root = Path(args.root).resolve()
    sweep = build_sweep(repo_root, limit=args.limit)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(sweep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json or args.out:
        print(json.dumps(sweep, indent=2, ensure_ascii=False))
    else:
        _print_human(sweep)

    return 1 if (args.fail and sweep["has_drift"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
