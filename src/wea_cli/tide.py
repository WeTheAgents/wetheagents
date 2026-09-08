"""Read canonical Tide results without invoking the retired v1 ledger commands."""

from __future__ import annotations

import json
from pathlib import Path

from wea_vnext.tide.ledger import BOOTSTRAP, files, git, load


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
