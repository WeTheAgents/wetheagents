"""Canonical Tide storage with data-only candidate validation."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..engine import installed_executor
from . import domain
from .collection import API_ROOT, collect_sources, cutoff_evidence
from .github import retain_artifacts
from .records import timestamp
from .replay import PARTICIPANT_EXECUTOR, Replay, ReplayError, canonical, digest

BOOTSTRAP = "ledger/vnext/tide-bootstrap.json"
STATE = "ledger/vnext/tide-state.json"
JOURNAL = "ledger/vnext/tides/"
RECEIPTS = "evidence/vnext/tides/"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True
    )
    return result.stdout.decode("utf-8").strip()


def read(root: Path, commit: str, path: str) -> Any:
    raw = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{path}"],
        capture_output=True,
        check=True,
    ).stdout
    data = json.loads(raw)
    if canonical(data) + b"\n" != raw:
        raise ReplayError(f"canonical JSON is required: {path}")
    return data


def files(root: Path, commit: str, prefix: str) -> list[str]:
    return git(root, "ls-tree", "-r", "--name-only", commit, "--", prefix).splitlines()


def load(root: Path, commit: str) -> tuple[Replay, list[dict[str, Any]]]:
    engine = Replay(read(root, commit, BOOTSTRAP))
    batches = []
    for index, path in enumerate(files(root, commit, JOURNAL), 1):
        if path != f"{JOURNAL}{index:016d}.json":
            raise ReplayError("canonical Tide history has a gap or extra path")
        batch = read(root, commit, path)
        engine.apply(batch)
        batches.append(batch)
    if engine.state() != read(root, commit, STATE):
        raise ReplayError("canonical projection does not match task replay")
    return engine, batches


def verify_directory(root: Path) -> dict[str, Any] | None:
    """Check working-tree ledger bytes, including the frozen legacy predecessor."""
    bootstrap_path = root / BOOTSTRAP
    if not bootstrap_path.exists():
        if (root / STATE).exists() or (root / JOURNAL).exists():
            raise ReplayError("Tide state exists without approved initialization")
        return None

    def document(path: str) -> Any:
        raw = (root / path).read_bytes()
        value = json.loads(raw)
        if raw != canonical(value) + b"\n":
            raise ReplayError(f"noncanonical Tide document: {path}")
        return value

    bootstrap = document(BOOTSTRAP)
    import hashlib

    for path, expected in bootstrap["legacy_files"].items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != expected:
            raise ReplayError("legacy ledger changed after the approved source freeze")
    engine = Replay(bootstrap)
    allowed = {BOOTSTRAP, STATE}
    for index, path in enumerate(sorted((root / JOURNAL).glob("*.json")), 1):
        expected = f"{JOURNAL}{index:016d}.json"
        if path.relative_to(root).as_posix() != expected:
            raise ReplayError("Tide journal sequence is incomplete")
        allowed.add(expected)
        engine.apply(document(expected))
    actual = {
        path.relative_to(root).as_posix()
        for path in (root / "ledger/vnext").rglob("*")
        if path.is_file()
    }
    if actual != allowed or engine.state() != document(STATE):
        raise ReplayError("Tide ledger paths or projection differ from executor replay")
    return engine.state()


def funding_merges(
    root: Path, base: str, batches: list[dict[str, Any]], api_get: Any
) -> dict[str, str]:
    result = {}
    for batch in batches:
        receipt = read(root, base, f"{RECEIPTS}{batch['sequence']:016d}.json")
        number = receipt.get("pull_request")
        # PR number is published in the branch's commit before PR creation only
        # when restoring a branch. The immutable head-to-PR association handles
        # the initial creation window without a follow-up ledger commit.
        if number is None:
            commits = git(
                root,
                "log",
                "--format=%H",
                "--diff-filter=A",
                base,
                "--",
                f"{JOURNAL}{batch['sequence']:016d}.json",
            ).splitlines()
            if len(commits) != 1:
                raise ReplayError(
                    "funding Tide has no unique canonical introducing commit"
                )
            prs = api_get(f"{API_ROOT}/commits/{commits[0]}/pulls?per_page=100")
            if type(prs) is not list or len(prs) >= 100:
                raise ReplayError("funding merge association is incomplete")
            matches = [
                item
                for item in prs
                if item.get("merged_at") and item.get("base", {}).get("ref") == "main"
            ]
            if len(matches) != 1:
                raise ReplayError("funding Tide has no unique merged canonical PR")
            number = matches[0]["number"]
        pr = api_get(f"{API_ROOT}/pulls/{number}")
        if not pr.get("merged") or pr.get("base", {}).get("ref") != "main":
            raise ReplayError("funding PR is not merged into canonical main")
        if pr.get("base", {}).get("repo", {}).get("id") != int(batch["repository_id"]):
            raise ReplayError("funding PR belongs to another repository")
        introduced = f"{JOURNAL}{batch['sequence']:016d}.json"
        if read(root, pr["merge_commit_sha"], introduced) != batch:
            raise ReplayError("funding merge does not contain the retained Tide")
        result[batch["batch_id"]] = pr["merged_at"]
    return result


def candidate(
    root: Path,
    base: str,
    collection: dict[str, Any],
    merges: dict[str, str],
    provenance: dict[str, Any],
    *,
    access_snapshot: dict[str, Any],
    hello_world: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    unresolved = [
        source["object_id"]
        for source in collection["sources"]
        if source["revision_status"] != "confirmed"
    ]
    if unresolved:
        raise ReplayError(
            "required revision evidence is incomplete; no candidate: "
            + ", ".join(unresolved[:10])
        )
    engine, _ = load(root, base)
    from . import hello_world as hw

    if hello_world is None:
        hello_world = engine.hello_world_anchor
    if hello_world is not None:
        if hello_world["checkpoint"]["installation_sha256"] != hw.package_hash():
            raise ReplayError("Hello World installed package differs")
        if engine.hello_world_anchor is None:
            hw.validate_historical(root)
    before = engine.state()
    previous_access = engine.access_snapshot
    sequence = engine.sequence + 1
    core = {
        "schema": hw.BATCH_SCHEMA
        if hello_world is not None
        else domain.batch_schema(access_snapshot),
        **({"hello_world": hello_world} if hello_world is not None else {}),
        "access_snapshot": access_snapshot,
        "participant_runtime": list(installed_executor(PARTICIPANT_EXECUTOR).reference),
        "sequence": sequence,
        "previous_hash": engine.last_hash,
        "repository_id": engine.bootstrap["repository_id"],
        "predecessor": base,
        "collection": collection,
        "funding_merges": merges,
    }
    batch = {**core, "batch_id": "tide:" + digest(core)}
    after = engine.apply(batch)
    meaningful = (
        "balances",
        "tasks",
        "dispositions",
        "funding_batches",
        "participants",
        "domain_scopes",
        "initiative_scopes",
        "hello_world",
        "hello_world_anchor",
        "current_supply",
    )
    from ..initiatives import meaningful as meaningful_access

    access_changed = meaningful_access(access_snapshot) != meaningful_access(
        previous_access
    )
    if not access_changed and all(
        before.get(key, {}) == after.get(key, {}) for key in meaningful
    ):
        return None
    payloads = {f"{JOURNAL}{sequence:016d}.json": batch, STATE: after}
    receipt = {
        "schema": "wea-tide-receipt-1",
        "writer": "tide@system",
        "predecessor": base,
        "batch_hash": digest(batch),
        "files": {path: digest(value) for path, value in payloads.items()},
        "provenance": provenance,
        "pull_request": None,
    }
    payloads[f"{RECEIPTS}{sequence:016d}.json"] = receipt
    return payloads


def validate(root: Path, base: str, head: str, *, api: Any = None) -> dict[str, Any]:
    for value in (base, head):
        if not re.fullmatch(r"[0-9a-f]{40}", value):
            raise ReplayError("candidate requires exact Git commits")
    if git(root, "rev-list", "--parents", "-n", "1", head) != f"{head} {base}":
        raise ReplayError("Tide candidate must be one direct child of canonical main")
    engine, batches = load(root, base)
    sequence = engine.sequence + 1
    path = f"{JOURNAL}{sequence:016d}.json"
    receipt_path = f"{RECEIPTS}{sequence:016d}.json"
    changed = set(git(root, "diff", "--name-only", base, head).splitlines())
    if changed != {path, STATE, receipt_path}:
        raise ReplayError(
            "Tide PR must contain exactly its batch, projection, and receipt"
        )
    batch, receipt = read(root, head, path), read(root, head, receipt_path)
    from . import hello_world as hw

    if batch.get("schema") != (
        hw.BATCH_SCHEMA
        if "hello_world" in batch
        else domain.batch_schema(batch.get("access_snapshot", domain.EMPTY))
    ):
        raise ReplayError("new Tide candidates require domain admission schema 3")
    tracked = sorted({source["issue_number"] for source in engine.sources.values()})
    if "hello_world" in batch:
        tracked = sorted(set(tracked) | {1})
    if batch["collection"].get("tracked_issues") != tracked:
        raise ReplayError("candidate collection omits canonical tracked Issues")
    if api is not None:
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ReplayError("Tide predecessor is stale")
        provenance = receipt["provenance"]
        run = api.get(
            f"{API_ROOT}/actions/runs/{int(provenance['run_id'])}/attempts/{int(provenance['run_attempt'])}"
        )
        if (
            run["head_sha"] != base
            or run["path"] != ".github/workflows/tide.yml"
            or run["event"] not in {"schedule", "workflow_dispatch"}
            or run["head_branch"] != "main"
        ):
            raise ReplayError("Tide provenance does not name the trusted main workflow")
        cutoff = timestamp(batch["collection"]["cutoff"])
        if domain.capture(api, cutoff) != batch["access_snapshot"]:
            raise ReplayError("Access snapshot differs from the canonical journal")
        if (
            not timestamp(run["run_started_at"])
            <= cutoff
            <= timestamp(run["updated_at"])
        ):
            raise ReplayError("Tide cutoff is outside its authenticated workflow run")
        expected_merges = funding_merges(root, base, batches, api.get)
        if expected_merges != batch["funding_merges"]:
            raise ReplayError("funding merge evidence differs")
        collector = (
            hw.collect_hello_world_sources
            if "hello_world" in batch
            else collect_sources
        )
        captured = collector(
            api.get,
            api.graphql,
            cutoff=cutoff,
            tracked_issues=tracked,
        )
        captured = retain_artifacts(
            captured, api.get, engine.modules["sources"].declaration
        )
        if cutoff_evidence(captured) != cutoff_evidence(
            batch["collection"]
        ) or captured["capture_hash"] != batch["collection"].get("capture_hash"):
            raise ReplayError(
                "candidate source evidence differs from authenticated GitHub reads"
            )
    expected = candidate(
        root,
        base,
        batch["collection"],
        batch["funding_merges"],
        receipt["provenance"],
        access_snapshot=batch["access_snapshot"],
        hello_world=batch.get("hello_world"),
    )
    if expected is None:
        raise ReplayError("empty Tide candidate is not permitted")
    for target, value in expected.items():
        if read(root, head, target) != value:
            raise ReplayError(f"candidate differs from executor replay: {target}")
    return expected[STATE]
