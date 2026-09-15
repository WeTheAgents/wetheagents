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


# Terminal plan statuses close a task; only these map to "settlement". A paused
# plan still has unresolved work/escrow and keeps its own label so runtime
# guidance (restore body, wait for author) is not misread as settled.
_TERMINAL_PLAN_STATUSES = frozenset({"completed", "stopped"})


def _stage_lifecycle(plan_status: str, stage: dict[str, Any] | None) -> str:
    """Map a projected stage to a coarse lifecycle label derived from its phase.

    The labels come straight from the runtime projection (`plan_status`, stage
    `status`, stage `phase`); this never invents a state transition.
    """
    if plan_status in _TERMINAL_PLAN_STATUSES:
        return "settlement"
    if plan_status == "paused":
        return "paused"
    if stage is None:
        return "funded"
    if stage.get("status") == "closed" or stage.get("phase") == "closed":
        return "settlement"
    if stage.get("phase") == "decision":
        return "review"
    if stage.get("phase") in {"intake", "join", "moves"}:
        return "open"
    return "funded"


# The canonical integration anchor. Report validation always resolves this
# independently of the requested ref, so a replayable but unmerged candidate
# (e.g. origin/tide/pending) can never be rendered as canonical state.
CANONICAL_REMOTE = "origin"
CANONICAL_BRANCH = "main"


def build_report(root: Path, ref: str | None, agent: str | None) -> dict[str, Any]:
    """Fetch, verify, and replay canonical vNext/Tide state for `wea report`.

    Refreshes canonical ``origin/main`` independently of the requested ref,
    resolves the requested ref, and rejects any ref that is not contained in the
    freshly fetched canonical head (an arbitrary local, unmerged, or pending
    branch is never rendered as canonical). ``ref`` of ``None`` (the default)
    reads the fully-qualified ``refs/remotes/origin/main`` so a local tag named
    ``origin/main`` cannot shadow the default snapshot; an explicit ref is honored
    for historical reads and still validated for containment. Raises
    ``ReportError`` on any fetch/ref/verify/replay failure; no stale fallback.
    """
    import subprocess

    # The trusted anchor is the fully-qualified remote-tracking ref, so a local
    # tag or branch literally named `origin/main` cannot shadow it.
    canonical_ref = f"refs/remotes/{CANONICAL_REMOTE}/{CANONICAL_BRANCH}"
    # The default snapshot resolves the fully-qualified anchor, not a bare name.
    report_ref = ref if ref else canonical_ref
    display_ref = ref if ref else f"{CANONICAL_REMOTE}/{CANONICAL_BRANCH}"

    # 1. Refresh the canonical integration branch, independently of `ref`, with an
    #    explicit destination refspec so a restrictive `remote.origin.fetch` cannot
    #    leave the remote-tracking ref stale.
    refspec = f"refs/heads/{CANONICAL_BRANCH}:{canonical_ref}"
    try:
        git(root, "fetch", "--quiet", CANONICAL_REMOTE, refspec)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise ReportError(
            f"Could not fetch canonical `{canonical_ref}`: "
            f"{detail or 'unknown git error'}. "
            "Fetch origin first (network access to the canonical remote is required)."
        ) from exc

    # 2. Resolve the requested ref and the canonical head separately.
    try:
        commit = git(root, "rev-parse", "--verify", f"{report_ref}^{{commit}}")
        canonical_head = git(
            root, "rev-parse", "--verify", f"{canonical_ref}^{{commit}}"
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise ReportError(
            f"Could not resolve canonical ref `{display_ref}`: "
            f"{detail or 'unknown git error'}. "
            "Fetch origin first (e.g. `git fetch origin`)."
        ) from exc

    # 3. Verify the ref is canonical: equal to, or an ancestor of, canonical
    #    origin/main. `git merge-base A B` == A exactly when A is an ancestor of
    #    B, so a pending candidate branch (a child of, or off, main) is rejected
    #    even though it would replay — it is not merged canonical history.
    if commit != canonical_head:
        try:
            merge_base = git(root, "merge-base", commit, canonical_head)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace").strip()
            raise ReportError(
                f"Could not verify `{display_ref}` against `{canonical_ref}`: "
                f"{detail or 'unknown git error'}."
            ) from exc
        if merge_base != commit:
            raise ReportError(
                f"Ref `{display_ref}` ({commit}) is not canonical: it is not "
                f"contained in the fetched `{canonical_ref}` ({canonical_head}). "
                "Report only reads canonical merged history, not local, unmerged, "
                "or pending branches."
            )

    if not files(root, commit, BOOTSTRAP):
        raise ReportError(
            f"Canonical Tide is not active at `{display_ref}` ({commit}); there is "
            "no vNext state to report. This checkout predates Tide initialization."
        )

    try:
        engine, _batches = load(root, commit)
    except Exception as exc:
        raise ReportError(
            f"Canonical replay failed at `{display_ref}` ({commit}): {exc}. "
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
        "ref": display_ref,
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
