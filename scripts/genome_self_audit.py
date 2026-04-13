#!/usr/bin/env python3
"""Genome self-audit: staleness, mutation currency, and fitness drift detection.

Complements check_genome_completeness.py (file presence) and
check_genome_naming.py (naming consistency) with runtime-state checks:

  1. Stale snapshot   — last_snapshot older than STALE_DAYS → WARN
  2. Silent agents    — tasks_completed > 0 but mutations == [] → WARN
                        (agent did work but genome never evolved)
  3. Fitness drift    — genome_meta.fitness.tasks_completed differs from
                        what ledger/history/*.jsonl actually shows → FAIL
  4. Section coverage — AGENTS.local.md missing required sections → WARN
                        Required: one H2 heading each for Role, Instructions,
                        Memory (case-insensitive).

Only registered agents in ledger/balances.json are checked.
agent0@system is exempt (no genome directory is expected).

Exit codes:
    0  — all checks PASS or WARN (WARNs are advisory)
    1  — one or more agents FAIL (fitness drift only)

Output: JSON to stdout with fields: status, checks, summary.

Usage:
    python scripts/genome_self_audit.py [--root PATH] [--stale-days N]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SKIP_AGENTS: set[str] = {"agent0@system"}

# Agents with last_snapshot older than this are flagged as stale.
_DEFAULT_STALE_DAYS = 30


def _repo_root(override: str | None = None) -> Path:
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent.parent


def _load_json(path: Path) -> Any:
    """Load JSON, return None on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _parse_iso(ts: str) -> datetime | None:
    """Parse ISO-8601 datetime string, return None on failure."""
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _compute_tasks_completed(agent_id: str, history_dir: Path) -> int:
    """Count payment events for agent_id across all history JSONL files."""
    count = 0
    if not history_dir.is_dir():
        return count
    for jsonl_path in sorted(history_dir.glob("*.jsonl")):
        try:
            text = jsonl_path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "payment" and event.get("agent") == agent_id:
                count += 1
    return count


def _required_sections_present(md_text: str) -> list[str]:
    """Return list of required section names missing from markdown text.

    A section is present when the markdown contains a line starting with
    '## ' followed by the section name (case-insensitive).
    """
    required = {"role", "instructions", "memory"}
    found: set[str] = set()
    for line in md_text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            for req in required:
                if heading.startswith(req):
                    found.add(req)
    return sorted(required - found)


def audit_agent(
    agent_id: str,
    genomes_dir: Path,
    history_dir: Path,
    *,
    stale_days: int = _DEFAULT_STALE_DAYS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Run all self-audit checks for one agent. Returns a list of finding dicts.

    Each finding has: agent, check, status (PASS|WARN|FAIL), detail.
    """
    findings: list[dict[str, Any]] = []
    now = now or datetime.now(timezone.utc)

    agent_dir = genomes_dir / agent_id
    meta_path = agent_dir / "genome_meta.json"
    md_path = agent_dir / "AGENTS.local.md"

    # Skip agents with no genome directory — check_genome_completeness handles that.
    if not agent_dir.is_dir() or not meta_path.exists():
        return findings

    meta = _load_json(meta_path)
    if not isinstance(meta, dict):
        return findings  # check_genome_completeness handles malformed meta

    canonical_id = meta.get("agent_id", agent_id)

    # --- Check 1: Stale snapshot ---
    last_snapshot_str = meta.get("last_snapshot", "")
    if last_snapshot_str:
        last_snapshot = _parse_iso(last_snapshot_str)
        if last_snapshot is not None:
            age_days = (now - last_snapshot).days
            if age_days > stale_days:
                findings.append({
                    "agent": agent_id,
                    "check": "stale_snapshot",
                    "status": "WARN",
                    "detail": (
                        f"last_snapshot is {age_days} days old "
                        f"(threshold: {stale_days}d); genome fitness may be stale"
                    ),
                })
            else:
                findings.append({
                    "agent": agent_id,
                    "check": "stale_snapshot",
                    "status": "PASS",
                    "detail": f"last_snapshot {age_days}d ago",
                })
        else:
            findings.append({
                "agent": agent_id,
                "check": "stale_snapshot",
                "status": "WARN",
                "detail": f"last_snapshot has unrecognised format: {last_snapshot_str!r}",
            })
    else:
        findings.append({
            "agent": agent_id,
            "check": "stale_snapshot",
            "status": "WARN",
            "detail": "last_snapshot field is absent or empty",
        })

    # --- Check 2: Silent agents (tasks done, genome never evolved) ---
    mutations = meta.get("mutations", [])
    fitness = meta.get("fitness", {}) if isinstance(meta.get("fitness"), dict) else {}
    tasks_completed = fitness.get("tasks_completed", 0)

    if tasks_completed > 0 and len(mutations) == 0:
        findings.append({
            "agent": agent_id,
            "check": "silent_agent",
            "status": "WARN",
            "detail": (
                f"tasks_completed={tasks_completed} in genome_meta "
                f"but mutations list is empty — genome has never evolved"
            ),
        })
    else:
        findings.append({
            "agent": agent_id,
            "check": "silent_agent",
            "status": "PASS",
            "detail": (
                f"mutations={len(mutations)}, tasks_completed={tasks_completed}"
            ),
        })

    # --- Check 3: Fitness drift ---
    ledger_tasks_completed = _compute_tasks_completed(canonical_id, history_dir)
    meta_tasks_completed = int(tasks_completed)

    if ledger_tasks_completed != meta_tasks_completed:
        findings.append({
            "agent": agent_id,
            "check": "fitness_drift",
            "status": "FAIL",
            "detail": (
                f"genome_meta.fitness.tasks_completed={meta_tasks_completed} "
                f"but ledger history shows {ledger_tasks_completed} payment events "
                f"for {canonical_id} — run genome_snapshot.py to resync"
            ),
        })
    else:
        findings.append({
            "agent": agent_id,
            "check": "fitness_drift",
            "status": "PASS",
            "detail": f"tasks_completed={meta_tasks_completed} matches ledger",
        })

    # --- Check 4: AGENTS.local.md section coverage ---
    if md_path.exists():
        try:
            md_text = md_path.read_text(encoding="utf-8")
        except OSError:
            md_text = ""
        missing = _required_sections_present(md_text)
        if missing:
            findings.append({
                "agent": agent_id,
                "check": "section_coverage",
                "status": "WARN",
                "detail": (
                    f"AGENTS.local.md missing required sections: "
                    + ", ".join(missing)
                ),
            })
        else:
            findings.append({
                "agent": agent_id,
                "check": "section_coverage",
                "status": "PASS",
                "detail": "all required sections present (Role, Instructions, Memory)",
            })
    else:
        findings.append({
            "agent": agent_id,
            "check": "section_coverage",
            "status": "WARN",
            "detail": "AGENTS.local.md not found — section check skipped",
        })

    return findings


def run(root: Path, *, stale_days: int = _DEFAULT_STALE_DAYS) -> tuple[dict[str, Any], bool]:
    """Run the full genome self-audit. Returns (result_dict, passed)."""
    balances_path = root / "ledger" / "balances.json"
    genomes_dir = root / "genomes"
    history_dir = root / "ledger" / "history"

    balances_data = _load_json(balances_path)
    if not isinstance(balances_data, dict):
        return {
            "status": "FAIL",
            "checks": [],
            "summary": "Could not load ledger/balances.json",
        }, False

    agents = balances_data.get("agents", {})
    now = datetime.now(timezone.utc)

    all_findings: list[dict[str, Any]] = []
    for agent_id in sorted(agents):
        if agent_id in _SKIP_AGENTS:
            continue
        agent_findings = audit_agent(
            agent_id, genomes_dir, history_dir, stale_days=stale_days, now=now
        )
        all_findings.extend(agent_findings)

    fail_count = sum(1 for f in all_findings if f["status"] == "FAIL")
    warn_count = sum(1 for f in all_findings if f["status"] == "WARN")
    pass_count = sum(1 for f in all_findings if f["status"] == "PASS")
    passed = fail_count == 0

    overall = "PASS" if passed else "FAIL"
    parts = [f"{pass_count} PASS"]
    if warn_count:
        parts.append(f"{warn_count} WARN")
    if fail_count:
        parts.append(f"{fail_count} FAIL")
    summary = f"{overall}: {', '.join(parts)} across {len(agents) - len(_SKIP_AGENTS)} agents"

    return {
        "status": overall,
        "checks": all_findings,
        "summary": summary,
    }, passed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Genome self-audit: check staleness, mutation currency, "
            "fitness drift, and section coverage."
        )
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root (default: auto-detected from script location)",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=_DEFAULT_STALE_DAYS,
        dest="stale_days",
        help=f"Days since last_snapshot before flagging stale (default: {_DEFAULT_STALE_DAYS})",
    )
    args = parser.parse_args()

    root = _repo_root(args.root)
    result, passed = run(root, stale_days=args.stale_days)
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
