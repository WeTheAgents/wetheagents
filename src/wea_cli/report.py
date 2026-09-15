"""Canonical read-only agent report, with runtime-owned lifecycle guidance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wea_cli.git_transport import canonical_commit
from wea_cli.tide import report_state

SCHEMA = "wea-report-vnext-1"


def build_report(root: Path, ref: str, agent: str | None) -> dict[str, Any]:
    commit = canonical_commit(root, ref)
    try:
        state, actions, issue_numbers = report_state(root, commit, agent)
        tasks = []
        for issue_id, projection in sorted(state["tasks"].items()):
            numbers = issue_numbers[issue_id]
            stages = [
                {key: value for key, value in stage.items() if key != "contract"}
                for stage in projection["stages"]
            ]
            tasks.append(
                {
                    "issue_id": issue_id,
                    "issue_numbers": numbers,
                    "plan_id": projection["plan_id"],
                    "plan_status": projection["plan_status"],
                    "current_stage_index": projection["current_stage_index"],
                    "escrow": projection["escrow"],
                    "stages": stages,
                    "roles": projection["roles"],
                    "settlements": projection["settlements"],
                    "next_action": actions.get(issue_id),
                }
            )
        return {
            "schema": SCHEMA,
            "ref": ref,
            "commit": commit,
            "sequence": state["sequence"],
            "cutoff": state["cutoff"],
            "balances": state["balances"],
            "total_balances_wea": sum(state["balances"].values()),
            "active_escrow_wea": state["escrow_wea"],
            "opening_supply_wea": state["opening_supply"],
            "agent": agent,
            "agent_available_wea": state["balances"].get(agent) if agent else None,
            "tasks": tasks,
            "legacy": {
                "status": "retained_history_only",
                "included_in_live_report": False,
            },
        }
    except Exception as exc:
        raise ValueError(
            "Canonical Tide replay failed. Check the fetched journal, projection and "
            "installed executor files; refresh the CLI and retry. No stale fallback."
        ) from exc


def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"Tide {report['sequence']} | cutoff {report['cutoff']}",
        f"Canonical {report['ref']} at {report['commit']}",
        f"Balances {report['total_balances_wea']} WEA | active "
        f"escrow {report['active_escrow_wea']} WEA",
        "Legacy ledger: retained history only, excluded from live figures.",
        f"Agent {report['agent'] or '(set WEA_AGENT for actions)'} "
        f"| available {report['agent_available_wea']}",
    ]
    for task in report["tasks"]:
        label = (
            ",".join(f"#{number}" for number in task["issue_numbers"])
            or task["issue_id"]
        )
        escrow = task["escrow"]
        lines.append(f"{label}: {task['plan_status']} | escrow {escrow['status']}")
        for stage in task["stages"]:
            lines.append(
                f"  {stage['stage_key']}: {stage['status']}/{stage['phase']} "
                f"| paid {stage['paid_wea']} | refunded {stage['refunded_wea']}"
            )
        if task["next_action"] is not None:
            action = task["next_action"]
            deadline = action.get("boundary_at")
            suffix = f" (boundary {deadline})" if deadline else ""
            lines.append(f"  Next: {action['action']}{suffix}")
    return "\n".join(lines)
