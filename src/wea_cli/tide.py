"""Read canonical Tide results without invoking the retired v1 ledger commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from wea_vnext.tide.ledger import BOOTSTRAP, files, git, load
from wea_vnext.tide.replay import ReplayError, json_data


class TideReadError(RuntimeError):
    """Raised when the canonical vNext ref cannot be verified, read, or replayed.

    The message is actionable: it tells the agent how to recover (usually to
    fetch ``origin``) instead of silently substituting stale local state.
    """


def show(args) -> int:
    from .cli import resolve_repo_root

    root: Path = resolve_repo_root(args.root)
    commit = git(root, "rev-parse", args.ref)
    if not files(root, commit, BOOTSTRAP):
        print(json.dumps({"status": "inactive", "ref": args.ref, "commit": commit}))
        return 0
    engine, _ = load(root, commit)
    state = engine.state()
    if args.issue is not None:
        ids = {
            str(source["issue_id"])
            for source in engine.sources.values()
            if source["issue_number"] == args.issue
        }
        if len(ids) != 1:
            print("This Issue has not reached a canonical Tide.")
            return 1
        issue_id = ids.pop()
        task = state["tasks"].get(issue_id)
        sources = {
            key
            for key, source in engine.sources.items()
            if str(source["issue_id"]) == issue_id
        }
        state = {
            "issue": args.issue,
            "task": task,
            "dispositions": {
                key: value
                for key, value in state["dispositions"].items()
                if key in sources
            },
        }
        if args.agent and issue_id in engine.runtimes:
            from wea_vnext.tide.replay import json_data

            state["next_action"] = json_data(
                engine.modules["lifecycle"].next_action(
                    engine.runtimes[issue_id], args.agent
                )
            )
    elif args.agent:
        state = {
            "agent": args.agent,
            "available_wea": state["balances"].get(args.agent, 0),
            "tide": state["sequence"],
        }
    print(
        json.dumps(
            {"ref": args.ref, "commit": commit, "result": state},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


# ---------------------------------------------------------------------------
# `wea report` — canonical vNext state for the invoking agent
# ---------------------------------------------------------------------------


def resolve_ref_commit(root: Path, ref: str) -> str:
    """Return the full commit SHA for a fetched, explicit canonical ref.

    Fails with an actionable :class:`TideReadError` instead of falling back to
    a stale working tree when the ref is missing (typically an un-fetched
    ``origin/main``).
    """
    try:
        return git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise TideReadError(
            f"Cannot verify canonical ref `{ref}`. Fetch origin first "
            f"(`git fetch origin`), then pass an existing ref such as "
            f"`--ref origin/main`. Report does not fall back to a stale working tree."
        ) from exc


def _issue_numbers(engine: Any) -> dict[str, int]:
    """Map canonical issue_id -> issue_number from retained sources."""
    mapping: dict[str, int] = {}
    for source in engine.sources.values():
        mapping.setdefault(str(source["issue_id"]), int(source["issue_number"]))
    return mapping


def _stage_label(status: str, phase: str) -> str:
    """Human label for a stage lifecycle position (open/review/settlement...)."""
    if status in {"settled", "closed"}:
        return "settlement"
    if phase in {"review", "decision", "settlement"}:
        return phase
    if phase in {"intake", "open"}:
        return "open"
    return phase or status


def _legacy_summary(root: Path, commit: str) -> dict[str, Any] | None:
    """Compact, explicitly-labelled summary of retained legacy ledger balances.

    Read from the same canonical commit so it never mixes working-tree drift
    into the report. Returns ``None`` when no legacy balances file is retained.
    """
    try:
        raw = subprocess.run(
            ["git", "-C", str(root), "show", f"{commit}:ledger/balances.json"],
            capture_output=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    agents = data.get("agents", {}) if isinstance(data, dict) else {}
    total = sum(
        int(info.get("balance", 0))
        for info in agents.values()
        if isinstance(info, dict)
    )
    return {
        "source": "ledger/balances.json",
        "agents": len(agents),
        "total_wea": total,
        "note": (
            "retained legacy ledger; frozen historical evidence, not vNext authority"
        ),
    }


def build_vnext_report(
    root: Path,
    *,
    ref: str = "origin/main",
    agent: str | None = None,
    issue: int | None = None,
) -> dict[str, Any]:
    """Build a stable, machine-readable canonical vNext report.

    The report is read only from the verified canonical ``ref`` through the same
    read-only replay engine that backs ``wea tide``. It never writes and never
    substitutes stale local state.
    """
    commit = resolve_ref_commit(root, ref)
    if not files(root, commit, BOOTSTRAP):
        return {
            "ref": ref,
            "commit": commit,
            "active": False,
            "agent": agent,
            "note": "vNext Tide is not initialized at this ref.",
        }

    try:
        engine, _ = load(root, commit)
        state = engine.state()
    except ReplayError as exc:
        raise TideReadError(
            f"Canonical Tide replay failed at {commit[:12]} ({ref}): {exc}. "
            f"Re-fetch origin and retry; do not treat local state as canonical."
        ) from exc

    numbers = _issue_numbers(engine)
    tasks: list[dict[str, Any]] = []
    for issue_id, task in state["tasks"].items():
        number = numbers.get(issue_id)
        if issue is not None and number != issue:
            continue
        stages = task["stages"]
        current = next(
            (s for s in stages if s["stage_index"] == task["current_stage_index"]),
            stages[0] if stages else None,
        )
        escrow = task["escrow"]
        available = (
            int(escrow["deposited_wea"])
            - int(escrow["paid_wea"])
            - int(escrow["refunded_wea"])
        )
        entry: dict[str, Any] = {
            "issue": number,
            "issue_id": issue_id,
            "plan_id": task["plan_id"],
            "plan_status": task["plan_status"],
            "current_stage_index": task["current_stage_index"],
            "stage_key": current["stage_key"] if current else None,
            "stage_status": current["status"] if current else None,
            "stage_phase": current["phase"] if current else None,
            "stage_label": _stage_label(
                current["status"] if current else "",
                current["phase"] if current else "",
            ),
            "escrow": {
                "deposited_wea": int(escrow["deposited_wea"]),
                "paid_wea": int(escrow["paid_wea"]),
                "refunded_wea": int(escrow["refunded_wea"]),
                "available_wea": available,
                "status": escrow["status"],
            },
            "next_action": None,
        }
        if agent and issue_id in engine.runtimes:
            entry["next_action"] = json_data(
                engine.modules["lifecycle"].next_action(
                    engine.runtimes[issue_id], agent
                )
            )
        tasks.append(entry)

    tasks.sort(key=lambda item: (item["issue"] is None, item["issue"] or 0))

    unresolved = [
        {"revision_id": key, "reason": value.get("reason", "")}
        for key, value in state["dispositions"].items()
        if value.get("status") == "unresolved"
    ]

    return {
        "ref": ref,
        "commit": commit,
        "active": True,
        "schema": state["schema"],
        "agent": agent,
        "available_wea": (int(state["balances"].get(agent, 0)) if agent else None),
        "tide": {
            "sequence": state["sequence"],
            "cutoff": state["cutoff"],
            "last_hash": state["last_hash"],
            "opening_supply_wea": state["opening_supply"],
            "active_escrow_wea": state["escrow_wea"],
        },
        "tasks": tasks,
        "unresolved_sources": unresolved,
        "legacy": _legacy_summary(root, commit),
    }


def _fmt_time(value: Any) -> str:
    return str(value) if value else "-"


def render_vnext_report(report: dict[str, Any]) -> str:
    """Render a concise human-readable form of :func:`build_vnext_report`."""
    lines: list[str] = []
    bar = "=" * 68
    lines.append(bar)
    short = str(report.get("commit", ""))[:12]
    lines.append(f"  WEA vNext REPORT  |  {report.get('ref', '')} @ {short}")
    lines.append(bar)

    if not report.get("active", False):
        lines.append("")
        lines.append(report.get("note", "vNext Tide is not active at this ref."))
        lines.append(bar)
        return "\n".join(lines)

    tide = report.get("tide", {})
    lines.append("")
    lines.append("CANONICAL TIDE")
    lines.append(
        f"  sequence: {tide.get('sequence')}   cutoff: {_fmt_time(tide.get('cutoff'))}"
    )
    lines.append(
        f"  opening supply: {tide.get('opening_supply_wea')} WEA   "
        f"active escrow: {tide.get('active_escrow_wea')} WEA"
    )
    agent = report.get("agent")
    if agent:
        lines.append(f"  agent: {agent}   available: {report.get('available_wea')} WEA")

    tasks = report.get("tasks", [])
    lines.append("")
    lines.append(f"FUNDED TASKS ({len(tasks)})")
    if not tasks:
        lines.append("  none funded at this ref")
    for task in tasks:
        issue = task.get("issue")
        issue_str = f"#{issue}" if issue is not None else task.get("issue_id", "?")
        escrow = task.get("escrow", {})
        lines.append(
            f"  {issue_str} [{task.get('plan_status')}] "
            f"stage {task.get('current_stage_index')} {task.get('stage_key')} "
            f"({task.get('stage_label')}: status={task.get('stage_status')}, "
            f"phase={task.get('stage_phase')})"
        )
        lines.append(
            f"      escrow: {escrow.get('deposited_wea')} WEA "
            f"(paid {escrow.get('paid_wea')}, refunded {escrow.get('refunded_wea')}, "
            f"available {escrow.get('available_wea')})"
        )
        action = task.get("next_action")
        if action:
            lines.append(
                f"      your next action: {action.get('action')} "
                f"(mode {action.get('mode')}, depth {action.get('depth')})"
            )
            if action.get("boundary_at"):
                lines.append(f"      boundary: {action.get('boundary_at')}")

    unresolved = report.get("unresolved_sources", [])
    lines.append("")
    lines.append(f"UNRESOLVED SOURCES ({len(unresolved)})")
    for item in unresolved[:10]:
        lines.append(f"  {item.get('revision_id')}: {item.get('reason')}")

    legacy = report.get("legacy")
    lines.append("")
    lines.append("RETAINED LEGACY (historical, not vNext authority)")
    if legacy:
        lines.append(
            f"  {legacy.get('source')}: {legacy.get('agents')} agents, "
            f"{legacy.get('total_wea')} WEA — {legacy.get('note')}"
        )
    else:
        lines.append("  no retained legacy balances at this ref")

    lines.append("")
    lines.append(bar)
    return "\n".join(lines)
