"""Run one bounded Tide or verify one candidate with trusted main code."""

from __future__ import annotations

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import activation
from .collection import API_ROOT, REPOSITORY, collect_sources
from .github import GitHub, retain_artifacts
from .labels import sync_canonical
from .ledger import (
    BOOTSTRAP,
    RECEIPTS,
    candidate,
    files,
    funding_merges,
    git,
    load,
    validate,
)
from .replay import ReplayError, canonical

BRANCH = "tide/pending"


def report(message: str) -> None:
    print(message)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")


def dispatch_guard(api: GitHub, number: int) -> None:
    api.request(
        "POST",
        f"{API_ROOT}/actions/workflows/guard-vnext-ledger.yml/dispatches",
        {"ref": "main", "inputs": {"pull_request": str(number)}},
    )


def invalidate_pending(api: GitHub) -> None:
    """Remove a stale green status after canonical main advances."""
    base = api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"]
    prs = api.get(
        f"{API_ROOT}/pulls?state=open&head=WeTheAgents:{BRANCH}&base=main&per_page=100"
    )
    if len(prs) == 100:
        raise ReplayError("pending Tide inventory is incomplete")
    for pr in prs:
        head = pr["head"]["sha"]
        commit = api.get(f"{API_ROOT}/git/commits/{head}")
        if [item["sha"] for item in commit["parents"]] != [base]:
            api.request(
                "POST",
                f"{API_ROOT}/statuses/{head}",
                {
                    "state": "failure",
                    "context": "tide/replay",
                    "description": "Canonical main advanced; rebuild this Tide",
                },
            )


def publish_pr(api: GitHub, head: str, sequence: int) -> None:
    pr = api.request(
        "POST",
        f"{API_ROOT}/pulls",
        {
            "base": "main",
            "head": BRANCH,
            "title": (
                "Initialize Tide with existing WEA balances"
                if sequence == 0
                else f"Tide {sequence}: checked WEA settlement batch"
            ),
            "body": (
                "This Tide retains GitHub sources and derives task state and "
                "financial effects through executor replay.\n\n"
                "Inspect the batch, task projection, and unresolved dispositions. "
                "Funding becomes usable after this PR merges. "
                "The author's acceptance remains a separate task decision. "
                "Manual merge is required.\n\n"
                f"Candidate commit: `{head}`. The trusted guard publishes "
                "`tide/replay` on this exact commit."
            ),
        },
    )
    dispatch_guard(api, pr["number"])
    report(f"Tide candidate awaits manual merge: {pr['html_url']}")


def run(
    root: Path,
    api: GitHub,
    retry_closed: bool,
    activation_comment_id: int = 0,
    activation_sha256: str = "",
) -> None:
    base = git(root, "rev-parse", "HEAD")
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
        or os.environ.get("GITHUB_WORKFLOW_REF")
        != f"{REPOSITORY}/.github/workflows/tide.yml@refs/heads/main"
    ):
        raise ReplayError("writer must run from the canonical main Tide workflow")
    if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
        raise ReplayError("main advanced before the Tide started")
    active = bool(files(root, base, BOOTSTRAP))
    if active and activation_comment_id:
        raise ReplayError("Tide is already initialized")
    if not active and not activation_comment_id:
        report("Tide is inactive: no approved canonical activation exists.")
        return
    if active:
        engine, batches = load(root, base)
        sync_canonical(api, engine, base, datetime.now(timezone.utc), report)
    refs = api.get(f"{API_ROOT}/git/matching-refs/heads/{BRANCH}")
    exact = [item for item in refs if item["ref"] == f"refs/heads/{BRANCH}"]
    old_head = exact[0]["object"]["sha"] if exact else ""
    prs = []
    seen = set()
    for page in range(1, 101):
        rows = api.get(
            f"{API_ROOT}/pulls?state=all&head=WeTheAgents:{BRANCH}&base=main&sort=created&direction=desc&per_page=100&page={page}"
        )
        if type(rows) is not list or any(item["number"] in seen for item in rows):
            raise ReplayError("pending-candidate discovery is incomplete")
        prs.extend(rows)
        seen.update(item["number"] for item in rows)
        if len(rows) < 100:
            break
    else:
        raise ReplayError("pending-candidate discovery exceeded its page bound")
    opened = [item for item in prs if item["state"] == "open"]
    if len(opened) > 1:
        raise ReplayError("multiple pending Tide PRs require operator review")
    if opened:
        pr = opened[0]
        predecessor = git(root, "rev-parse", pr["head"]["sha"] + "^")
        if predecessor == base:
            dispatch_guard(api, pr["number"])
            report(f"Pending Tide remains stable for manual review: {pr['html_url']}")
            return
        api.request("PATCH", f"{API_ROOT}/pulls/{pr['number']}", {"state": "closed"})
    if not retry_closed:
        for pr in prs:
            if pr["state"] != "closed" or pr.get("merged_at"):
                continue
            commit = api.get(f"{API_ROOT}/git/commits/{pr['head']['sha']}")
            if [item["sha"] for item in commit["parents"]] == [base]:
                report(
                    "The operator closed this Tide. Automatic publication is paused; "
                    "use manual retry_closed to rebuild it."
                )
                return
    if old_head and git(root, "rev-parse", old_head + "^") == base:
        closed = [
            item
            for item in prs
            if item["head"]["sha"] == old_head and not item.get("merged_at")
        ]
        if closed and not retry_closed:
            report(
                "The operator closed this Tide. Automatic publication is paused; "
                "use manual retry_closed to rebuild it."
            )
            return
        if not closed:
            # Recovery for a successful push followed by a failed PR API call.
            validate_any(root, base, old_head)
            sequence = load(root, base)[0].sequence + 1 if active else 0
            publish_pr(api, old_head, sequence)
            return
    if not active:
        if os.environ.get("GITHUB_ACTOR_ID") != str(activation.OPERATOR):
            raise ReplayError("only the operator can dispatch activation")
        source = activation.fetch_source(api, activation_comment_id, activation_sha256)
        provenance = {
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        }
        payloads = activation.payloads(root, base, source, provenance)
        sequence = 0
    else:
        cutoff = datetime.now(timezone.utc)
        tracked = sorted({raw["issue_number"] for raw in engine.sources.values()})
        collection = collect_sources(
            api.get, api.graphql, cutoff=cutoff, tracked_issues=tracked
        )
        collection = retain_artifacts(
            collection, api.get, engine.modules["sources"].declaration
        )
        merges = funding_merges(root, base, batches, api.get)
        provenance = {
            "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        }
        payloads = candidate(root, base, collection, merges, provenance)
        sequence = engine.sequence + 1
    if payloads is None:
        report(
            "Tide found no new task or financial effects and no new unresolved cases."
        )
        return
    if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
        raise ReplayError(
            "main advanced during collection; retry from the new predecessor"
        )
    for path, data in payloads.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical(data) + b"\n")
    git(root, "add", "--", *sorted(payloads))
    git(
        root,
        "-c",
        "user.name=tide@system",
        "-c",
        "user.email=tide@wetheagents.noreply.github.com",
        "commit",
        "-m",
        f"Tide {sequence}: settle retained WEA evidence",
    )
    head = git(root, "rev-parse", "HEAD")
    validate_any(root, base, head)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "push",
            "origin",
            f"--force-with-lease=refs/heads/{BRANCH}:{old_head}",
            f"HEAD:refs/heads/{BRANCH}",
        ],
        check=True,
    )
    publish_pr(api, head, sequence)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("run", "validate", "guard", "resolve-pr", "invalidate-pending"),
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--pull-request", type=int)
    parser.add_argument("--verify-github", action="store_true")
    parser.add_argument("--retry-closed", action="store_true")
    parser.add_argument("--activation-comment-id", type=int, default=0)
    parser.add_argument("--activation-sha256", default="")
    args = parser.parse_args()
    api = (
        GitHub(os.environ.get("GITHUB_TOKEN", ""))
        if args.command != "validate" or args.verify_github
        else None
    )
    if args.command == "run":
        run(
            args.root,
            api,
            args.retry_closed,
            args.activation_comment_id,
            args.activation_sha256,
        )
    elif args.command == "invalidate-pending":
        invalidate_pending(api)
    elif args.command == "resolve-pr":
        pr = api.get(f"{API_ROOT}/pulls/{args.pull_request}")
        if pr["base"]["ref"] != "main" or pr["base"]["repo"]["full_name"] != REPOSITORY:
            raise ReplayError("guard PR does not target canonical main")
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            for key, value in (
                ("base", pr["base"]["sha"]),
                ("head", pr["head"]["sha"]),
                ("number", pr["number"]),
            ):
                stream.write(f"{key}={value}\n")
    elif args.command == "guard":

        def status(value: str, description: str) -> None:
            api.request(
                "POST",
                f"{API_ROOT}/statuses/{args.head}",
                {"state": value, "context": "tide/replay", "description": description},
            )

        status("pending", "Checking exact candidate with trusted main code")
        try:
            changed = git(
                args.root, "diff", "--name-only", args.base, args.head
            ).splitlines()
            if any(
                path.startswith(("ledger/", RECEIPTS, "evidence/vnext/tide-activation"))
                for path in changed
            ):
                state = validate_any(args.root, args.base, args.head, api=api)
                description = (
                    f"Tide {state['sequence']} matches trusted executor replay"
                )
            else:
                from ..block9.github_native import validate_pull_request_commits

                validate_pull_request_commits(
                    args.root, base_commit=args.base, candidate_commit=args.head
                )
                description = "Code-only writer boundary is unchanged"
            if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != args.base:
                raise ReplayError(
                    "main advanced during validation; candidate must be rebuilt"
                )
        except Exception:
            status("failure", "Trusted candidate validation failed")
            raise
        status("success", description)
    else:
        state = validate_any(args.root, args.base, args.head, api=api)
        report(f"Tide {state['sequence']} matches executor replay.")


def validate_any(root: Path, base: str, head: str, api=None):
    if not files(root, base, BOOTSTRAP):
        return activation.validate_activation(root, base, head, api)
    return validate(root, base, head, api=api)


if __name__ == "__main__":
    main()
