"""Read canonical Tide results without invoking the retired v1 ledger commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from wea_vnext.tide.ledger import BOOTSTRAP, files, git, load
from wea_vnext.tide.replay import json_data

from .git_transport import GitTransportError, fetch_canonical


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


def build_report(root: Path, ref: str, agent: str) -> dict[str, Any]:
    commit = fetch_canonical(root, ref)
    try:
        engine, _ = load(root, commit)
        state = engine.state()
        tasks = []
        for issue_id, projection in sorted(state["tasks"].items()):
            numbers = {
                source["issue_number"]
                for source in engine.sources.values()
                if str(source["issue_id"]) == issue_id
            }
            tasks.append(
                {
                    "issue_id": issue_id,
                    "issue_number": next(iter(numbers)) if len(numbers) == 1 else None,
                    "plan_id": projection["plan_id"],
                    "plan_status": projection["plan_status"],
                    "current_stage_index": projection["current_stage_index"],
                    "escrow": projection["escrow"],
                    "stages": [
                        {
                            key: value
                            for key, value in stage.items()
                            if key != "contract"
                        }
                        for stage in projection["stages"]
                    ],
                    "settlements": projection["settlements"],
                    "next_action": json_data(
                        engine.modules["lifecycle"].next_action(
                            engine.runtimes[issue_id], agent
                        )
                    ),
                }
            )
    except Exception as exc:
        # No partial report, cached fallback, or raw replay source/credential dump.
        raise GitTransportError(
            "Canonical Tide replay failed. Check fetched history and CLI freshness; "
            "ask Agent0 to inspect replay evidence. No current state was reported."
        ) from exc
    return {
        "schema": "wea-report-1",
        "ref": ref,
        "commit": commit,
        "sequence": state["sequence"],
        "cutoff": state["cutoff"],
        "agent": agent,
        "available_wea": state["balances"].get(agent),
        "balances": state["balances"],
        "total_balances_wea": sum(state["balances"].values()),
        "active_escrow_wea": state["escrow_wea"],
        "opening_supply_wea": state["opening_supply"],
        "legacy": {
            "status": "retained_history_only",
            "included_in_current_totals": False,
        },
        "tasks": tasks,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"Canonical vNext: {report['ref']} at {report['commit']}",
        f"Tide {report['sequence']} | cutoff {report['cutoff']}",
        (
            f"Balances {report['total_balances_wea']} WEA "
            f"| active escrow "
            f"{report['active_escrow_wea']} WEA"
        ),
        f"Agent {report['agent']}: {report['available_wea']} WEA available",
        "Legacy ledger: retained history only; excluded from current totals.",
    ]
    for task in report["tasks"]:
        lines.append(
            f"#{task['issue_number'] or task['issue_id']}: "
            f"{task['plan_status']} | stage {task['current_stage_index']} | "
            f"escrow {task['escrow']['status']}"
        )
        for stage in task["stages"]:
            lines.append(
                f"  {stage['stage_key']}: {stage['status']}/{stage['phase']} | "
                f"paid {stage['paid_wea']} WEA | refunded {stage['refunded_wea']} WEA"
            )
        action = task["next_action"]
        boundary = (
            f" | boundary {action['boundary_at']}" if action.get("boundary_at") else ""
        )
        lines.append(f"  Next: {action['action']}{boundary}")
    return "\n".join(lines)


def runtime_contract_files(package: Path) -> list[Path]:
    """Enumerate this project's shipped read-only runtime contract for freshness."""
    return sorted(
        path
        for path in (package.parent / "wea_vnext").rglob("*")
        if path.is_file() and path.suffix in {".py", ".json"}
    )
