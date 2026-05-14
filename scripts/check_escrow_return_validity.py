#!/usr/bin/env python3
"""Escrow-return validity checker for WeTheAgents.

Verifies that every ``escrow_return`` event in ``ledger/history/*.jsonl`` has a
corresponding prior escrow-creation event for the same issue.

Computation rules:
  - Replay all history events chronologically (by file sort order, then line).
  - Track all ``escrow`` and ``escrow_create`` events as prior creates.
  - For each ``escrow_return`` event:
      * If a prior create exists for the same issue → OK.
      * If no prior create but a prior payment exists → WARN (pre-history gap:
        escrow predates history tracking; payments prove it was real).
      * If no prior create and no prior payment → FAIL (no evidence the escrow
        ever existed; potential fraudulent injection).
  - If the cumulative amount returned for an issue exceeds the cumulative
    amount created → WARN (over-return; partial returns are valid).
  - ``escrow_return_bulk`` events are NOT individually checked — they are a
    distinct event type used for batch cleanup operations.

Exit codes:
    0 — PASS (no violations)
    1 — FAIL (one or more violations detected)

Output: JSON to stdout with fields: status, violations, warnings, summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _repo_root_from(root: str | None) -> Path:
    if root:
        return Path(root).resolve()
    return Path(__file__).resolve().parent.parent


def _iter_events(history_dir: Path):
    """Yield each parsed event dict from all .jsonl files in sorted order.

    Files are processed in lexicographic order (YYYY-MM-DD.jsonl), then by
    line number within each file. Malformed lines are skipped with a stderr
    warning.
    """
    for jsonl_file in sorted(history_dir.glob("*.jsonl")):
        with open(jsonl_file, encoding="utf-8") as fh:
            for lineno, raw_line in enumerate(fh, 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    print(
                        f"WARNING: skipping malformed JSON in "
                        f"{jsonl_file.name}:{lineno}: {exc}",
                        file=sys.stderr,
                    )

def _event_type(event: dict[str, Any]) -> str:
    for key in ("event", "op", "type"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def run_check(
    root: Path,
    *,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Replay history and return the validity report.

    Parameters
    ----------
    root:
        Repository root directory.
    events:
        Override the event stream (used by tests to inject synthetic data
        without touching the filesystem).

    Returns
    -------
    dict with keys: status, violations, warnings, summary.
    """
    history_dir = root / "ledger" / "history"

    if events is None:
        if not history_dir.is_dir():
            print(
                f"ERROR: history directory not found: {history_dir}",
                file=sys.stderr,
            )
            sys.exit(1)
        event_stream = _iter_events(history_dir)
    else:
        event_stream = iter(events)

    # Running state per issue (keyed by int issue number)
    prior_creates: dict[int, bool] = {}        # issue → True if any create seen
    prior_payments: dict[int, bool] = {}       # issue → True if any payment seen
    total_created: dict[int, int] = {}         # issue → cumulative escrow amount
    total_returned: dict[int, int] = {}        # issue → cumulative return amount

    violations: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for event in event_stream:
        etype = _event_type(event)
        raw_issue = event.get("issue")

        if raw_issue is None:
            continue

        try:
            issue = int(raw_issue)
        except (ValueError, TypeError):
            continue

        amount = event.get("amount")
        if not isinstance(amount, (int, float)):
            amount = 0
        amount = int(amount)

        if etype in ("escrow", "escrow_create"):
            prior_creates[issue] = True
            total_created[issue] = total_created.get(issue, 0) + amount

        elif etype == "payment":
            prior_payments[issue] = True

        elif etype == "escrow_return":
            total_returned[issue] = total_returned.get(issue, 0) + amount

            if not prior_creates.get(issue):
                # No prior create of any type for this issue.
                if prior_payments.get(issue):
                    # Payments prove the escrow was real — it predates history.
                    warnings.append(
                        {
                            "issue": issue,
                            "return_amount": amount,
                            "detail": (
                                "no prior escrow_create in history — "
                                "pre-history gap (payments confirm escrow existed)"
                            ),
                        }
                    )
                else:
                    violations.append(
                        {
                            "issue": issue,
                            "return_amount": amount,
                            "reason": "no prior escrow_create",
                        }
                    )
            else:
                # Prior create exists — check for over-return.
                created = total_created.get(issue, 0)
                returned = total_returned.get(issue, 0)
                if returned > created:
                    warnings.append(
                        {
                            "issue": issue,
                            "detail": (
                                f"return exceeds original escrow: "
                                f"returned={returned} > created={created}"
                            ),
                        }
                    )

        # escrow_return_bulk is intentionally not checked per-issue here.

    status = "FAIL" if violations else "PASS"
    summary = f"{len(violations)} violation(s), {len(warnings)} warning(s)"

    return {
        "status": status,
        "violations": violations,
        "warnings": warnings,
        "summary": summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify every escrow_return event has a prior escrow_create "
            "for the same issue"
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (auto-detected from script location if omitted)",
    )
    args = parser.parse_args(argv)

    root = _repo_root_from(args.root)
    result = run_check(root)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
