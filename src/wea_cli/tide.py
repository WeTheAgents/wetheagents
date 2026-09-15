"""Read canonical Tide results without invoking the retired v1 ledger commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wea_vnext.tide.ledger import BOOTSTRAP, files, git, load
from wea_vnext.tide.replay import json_data


class ReportError(Exception):
    """Canonical vNext state could not be read for `wea report`."""


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
# `wea report` — canonical vNext orchestration snapshot (read-only)
# ---------------------------------------------------------------------------


def _stage_lifecycle(plan_status: str, stage: dict[str, Any] | None) -> str:
    """Map a projected stage to a coarse lifecycle label derived from its phase.

    The labels come straight from the runtime projection (`plan_status`, stage
    `status`, stage `phase`); this never invents a state transition.
    """
    if plan_status != "active":
        return "settlement"
    if stage is None:
        return "funded"
    if stage.get("status") == "closed" or stage.get("phase") == "closed":
        return "settlement"
    if stage.get("phase") == "decision":
        return "review"
    if stage.get("phase") in {"intake", "join", "moves"}:
        return "open"
    return "funded"


def build_report(root: Path, ref: str, agent: str | None) -> dict[str, Any]:
    """Fetch, verify, and replay canonical vNext/Tide state for `wea report`.

    Raises ``ReportError`` on any fetch/ref/replay failure; there is no stale
    fallback to legacy files.
    """
    import subprocess

    try:
        commit = git(root, "rev-parse", ref)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise ReportError(
            f"Could not resolve canonical ref `{ref}`: "
            f"{detail or 'unknown git error'}. "
            "Fetch origin first (e.g. `git fetch origin`)."
        ) from exc

    if not files(root, commit, BOOTSTRAP):
        raise ReportError(
            f"Canonical Tide is not active at `{ref}` ({commit}); there is no vNext "
            "state to report. This checkout predates Tide initialization."
        )

    try:
        engine, _batches = load(root, commit)
    except Exception as exc:
        raise ReportError(
            f"Canonical replay failed at `{ref}` ({commit}): {exc}. "
            "Re-fetch origin and confirm the ref is a clean canonical commit."
        ) from exc

    state = engine.state()
    id_to_number = {
        str(source["issue_id"]): source["issue_number"]
        for source in engine.sources.values()
    }

    tasks: list[dict[str, Any]] = []
    for issue_id, projection in state["tasks"].items():
        current_index = projection.get("current_stage_index")
        stages = projection.get("stages", [])
        current = next(
            (item for item in stages if item.get("stage_index") == current_index),
            None,
        )
        contract = (current or {}).get("contract", {}) or {}
        next_action = None
        if agent and issue_id in engine.runtimes:
            next_action = json_data(
                engine.modules["lifecycle"].next_action(
                    engine.runtimes[issue_id], agent
                )
            )
        tasks.append(
            {
                "issue": id_to_number.get(issue_id),
                "issue_id": issue_id,
                "plan_id": projection.get("plan_id"),
                "plan_status": projection.get("plan_status"),
                "funded": issue_id in engine.funding_batches,
                "lifecycle": _stage_lifecycle(
                    projection.get("plan_status", ""), current
                ),
                "stage_key": (current or {}).get("stage_key"),
                "stage_status": (current or {}).get("status"),
                "phase": (current or {}).get("phase"),
                "mode": contract.get("mode"),
                "depth": contract.get("depth"),
                "works": len((current or {}).get("works", [])),
                "paid_wea": (current or {}).get("paid_wea", 0),
                "next_action": next_action,
            }
        )
    tasks.sort(key=lambda item: (item["issue"] is None, item["issue"] or 0))

    balances = state["balances"]
    legacy_files = sorted(engine.bootstrap.get("legacy_files", {}))
    return {
        "ref": ref,
        "commit": commit,
        "sequence": state["sequence"],
        "cutoff": state["cutoff"],
        "last_hash": state["last_hash"],
        "opening_supply": state["opening_supply"],
        "escrow_wea": state["escrow_wea"],
        "total_balance": sum(balances.values()),
        "agent": agent,
        "agent_balance": balances.get(agent) if agent else None,
        "balances": balances,
        "tasks": tasks,
        "legacy_history": {
            "retained": True,
            "note": (
                "ledger/*.json files are frozen v1 history retained as the Tide "
                "predecessor; they are NOT current vNext spending authority. Use this "
                "report and `wea tide` for canonical vNext balances and task state."
            ),
            "files": legacy_files,
        },
    }


def render_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append("  WEA vNEXT REPORT  |  " + str(report.get("commit", ""))[:12])
    lines.append("=" * 64)
    lines.append(f"ref:      {report['ref']}")
    lines.append(f"commit:   {report['commit']}")
    lines.append(f"sequence: {report['sequence']}    cutoff: {report['cutoff']}")
    lines.append(
        f"supply:   {report['opening_supply']} WEA "
        f"(balances {report['total_balance']} + escrow {report['escrow_wea']})"
    )
    if report.get("agent"):
        lines.append(
            f"agent:    {report['agent']}  balance={report.get('agent_balance')}"
        )

    tasks = report.get("tasks", [])
    lines.append("")
    lines.append(f"TASKS ({len(tasks)})")
    if not tasks:
        lines.append("  none funded")
    for task in tasks:
        issue = task["issue"]
        head = f"  #{issue} [{task['lifecycle']}] {task['stage_key'] or ''}".rstrip()
        meta = f"plan={task['plan_status']} phase={task['phase']} works={task['works']}"
        if task.get("paid_wea"):
            meta += f" paid={task['paid_wea']}"
        lines.append(f"{head}  ({meta})")
        action = task.get("next_action")
        if action and action.get("action"):
            boundary = action.get("boundary_at")
            suffix = f" by {boundary}" if boundary else ""
            lines.append(f"      next: {action['action']}{suffix}")

    legacy = report.get("legacy_history", {})
    lines.append("")
    lines.append("LEGACY HISTORY (retained, not vNext authority)")
    lines.append(f"  {legacy.get('note', '')}")
    if legacy.get("files"):
        lines.append("  files: " + ", ".join(legacy["files"]))
    lines.append("=" * 64)
    return "\n".join(lines)
