#!/usr/bin/env python3
"""Detect stale genome fitness snapshots for registered agents.

Classifications:
- FRESH:   snapshot age is less than 1 day
- AGING:   snapshot age is at least 1 day and at most threshold_days
- STALE:   snapshot age is greater than threshold_days
- MISSING: genome metadata or last_snapshot is missing/unreadable

Default behavior fails on STALE and MISSING agents. Strict mode also fails on
AGING agents.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKIP_BALANCE_AGENTS = {"agent0@system"}

# Deprecated agents are still listed in ledger/balances.json because they
# retain historical earnings (zeroing a balance would corrupt the supply
# invariant). Snapshot freshness is not a meaningful signal for them — their
# genome is frozen at the deprecation date by design.
#
# Each entry: agent_id -> (deprecated_at_iso, rationale).
DEPRECATED_AGENTS: dict[str, tuple[str, str]] = {
    "gemini-4@google": (
        "2026-04-23",
        "Deprecated 2026-04-23 due to API-token cost; T6 role reassigned to "
        "Claude-6@claude 2026-04-29. Last snapshot 2026-04-23T03:52:49Z "
        "matches the deprecation date — no further snapshots are expected.",
    ),
}


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_utc_timestamp(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _resolve_now(now: datetime | str | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    return _parse_utc_timestamp(now)


def _validate_threshold_days(threshold_days: float) -> None:
    if not math.isfinite(threshold_days) or threshold_days < 1:
        raise ValueError("--threshold-days must be >= 1")


def _registered_agents(root: Path, *, include_deprecated: bool = False) -> list[str]:
    balances = _load_json(root / "ledger" / "balances.json")
    agents = balances.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("ledger/balances.json missing top-level 'agents' object")
    skip = set(SKIP_BALANCE_AGENTS)
    if not include_deprecated:
        skip |= set(DEPRECATED_AGENTS)
    return sorted(set(agents) - skip)


def _classify_snapshot(
    last_snapshot: str | None,
    *,
    now: datetime,
    threshold_days: float,
) -> tuple[str, float | None, str]:
    if not isinstance(last_snapshot, str) or not last_snapshot.strip():
        return "MISSING", None, "last_snapshot missing"

    try:
        snapshot_dt = _parse_utc_timestamp(last_snapshot)
    except ValueError:
        return "MISSING", None, f"last_snapshot is not valid ISO-8601: {last_snapshot!r}"

    age_seconds = max((now - snapshot_dt).total_seconds(), 0.0)
    age_days = age_seconds / 86400.0

    if age_days < 1:
        return "FRESH", age_days, "snapshot is less than 1 day old"
    if age_days <= threshold_days:
        return "AGING", age_days, f"snapshot is between 1 and {threshold_days:g} days old"
    return "STALE", age_days, f"snapshot is older than {threshold_days:g} days"


def collect_report(
    root: Path,
    *,
    threshold_days: float = 3.0,
    now: datetime | str | None = None,
    include_deprecated: bool = False,
) -> dict[str, Any]:
    _validate_threshold_days(threshold_days)
    current_time = _resolve_now(now)

    agents_report: list[dict[str, Any]] = []
    for agent_id in _registered_agents(root, include_deprecated=include_deprecated):
        meta_path = root / "genomes" / agent_id / "genome_meta.json"
        if not meta_path.exists():
            agents_report.append(
                {
                    "agent_id": agent_id,
                    "status": "MISSING",
                    "last_snapshot": None,
                    "age_days": None,
                    "detail": f"missing {meta_path.relative_to(root).as_posix()}",
                }
            )
            continue

        try:
            meta = _load_json(meta_path)
        except (OSError, json.JSONDecodeError) as exc:
            agents_report.append(
                {
                    "agent_id": agent_id,
                    "status": "MISSING",
                    "last_snapshot": None,
                    "age_days": None,
                    "detail": f"cannot load {meta_path.relative_to(root).as_posix()}: {exc}",
                }
            )
            continue

        if not isinstance(meta, dict):
            agents_report.append(
                {
                    "agent_id": agent_id,
                    "status": "MISSING",
                    "last_snapshot": None,
                    "age_days": None,
                    "detail": f"{meta_path.relative_to(root).as_posix()} is not a JSON object",
                }
            )
            continue

        last_snapshot = meta.get("last_snapshot")
        status, age_days, detail = _classify_snapshot(
            last_snapshot,
            now=current_time,
            threshold_days=threshold_days,
        )
        agents_report.append(
            {
                "agent_id": agent_id,
                "status": status,
                "last_snapshot": last_snapshot if isinstance(last_snapshot, str) else None,
                "age_days": age_days,
                "detail": detail,
            }
        )

    counts = {status: 0 for status in ("FRESH", "AGING", "STALE", "MISSING")}
    for entry in agents_report:
        counts[entry["status"]] += 1

    skipped_deprecated = [
        {"agent_id": agent_id, "deprecated_at": meta[0], "rationale": meta[1]}
        for agent_id, meta in sorted(DEPRECATED_AGENTS.items())
        if not include_deprecated
    ]

    return {
        "root": str(root).replace("\\", "/"),
        "now": current_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "threshold_days": threshold_days,
        "agents": agents_report,
        "counts": counts,
        "skipped_deprecated": skipped_deprecated,
    }


def exit_code_for_report(report: dict[str, Any], *, strict: bool = False) -> int:
    counts = report["counts"]
    if counts["STALE"] or counts["MISSING"]:
        return 1
    if strict and counts["AGING"]:
        return 1
    return 0


def _format_age(age_days: float | None) -> str:
    if age_days is None:
        return "n/a"
    return f"{age_days:.2f}d"


def print_report(report: dict[str, Any]) -> None:
    for entry in report["agents"]:
        print(
            f"[{entry['status']}] {entry['agent_id']}: "
            f"age={_format_age(entry['age_days'])}, "
            f"last_snapshot={entry['last_snapshot'] or 'n/a'} "
            f"({entry['detail']})"
        )

    counts = report["counts"]
    total = len(report["agents"])
    print(
        "\nSummary: "
        f"{total} agent(s), "
        f"{counts['FRESH']} fresh, "
        f"{counts['AGING']} aging, "
        f"{counts['STALE']} stale, "
        f"{counts['MISSING']} missing "
        f"(threshold={report['threshold_days']:g}d, now={report['now']})"
    )

    skipped = report.get("skipped_deprecated") or []
    if skipped:
        names = ", ".join(entry["agent_id"] for entry in skipped)
        print(f"Skipped deprecated: {names} (pass --include-deprecated to include)")


def run(
    root: Path,
    *,
    threshold_days: float = 3.0,
    strict: bool = False,
    now: datetime | str | None = None,
    include_deprecated: bool = False,
) -> tuple[dict[str, Any], int]:
    report = collect_report(
        root,
        threshold_days=threshold_days,
        now=now,
        include_deprecated=include_deprecated,
    )
    return report, exit_code_for_report(report, strict=strict)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check genome snapshot freshness.")
    parser.add_argument("--root", default=None, help="Repository root (default: auto-detect)")
    parser.add_argument(
        "--threshold-days",
        type=float,
        default=3.0,
        help="Maximum age in days before a snapshot becomes stale (default: 3)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat AGING agents as a failure in addition to STALE/MISSING agents",
    )
    parser.add_argument(
        "--include-deprecated",
        action="store_true",
        help=(
            "Also check agents listed in DEPRECATED_AGENTS (default: skip them; "
            "their genome is frozen at the deprecation date by design)"
        ),
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    try:
        report, exit_code = run(
            root,
            threshold_days=args.threshold_days,
            strict=args.strict,
            include_deprecated=args.include_deprecated,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_report(report)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
