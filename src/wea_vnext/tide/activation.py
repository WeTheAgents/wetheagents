"""Explicit operator initialization, separate from ordinary automatic settlement."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from ..engine import installed_executor
from .collection import API_ROOT, REPOSITORY_ID
from .ledger import BOOTSTRAP, STATE, files, git, read
from .replay import EXECUTOR, Replay, ReplayError, digest

MARKER = "<!-- wea:tide-activate -->\n"
RECEIPT = "evidence/vnext/tide-activation.json"
OPERATOR = 129645949
LEGACY = ("ledger/balances.json", "ledger/escrows.json", "ledger/idem_keys.json")


def legacy(root: Path, base: str) -> tuple[dict[str, int], dict[str, str]]:
    hashes = {}
    data = {}
    for path in LEGACY:
        raw = subprocess.run(
            ["git", "-C", str(root), "show", f"{base}:{path}"],
            capture_output=True,
            check=True,
        ).stdout
        hashes[path] = hashlib.sha256(raw).hexdigest()
        data[path] = json.loads(raw)
    if data["ledger/escrows.json"]["active"]:
        raise ReplayError("activation requires the accepted zero-active-escrow cutover")
    balances = {
        key: item["balance"]
        for key, item in data["ledger/balances.json"]["agents"].items()
    }
    return balances, hashes


def fetch_source(api: Any, comment_id: int, expected_sha256: str) -> dict[str, Any]:
    comment = api.get(f"{API_ROOT}/issues/comments/{comment_id}")
    if (
        comment.get("id") != comment_id
        or comment.get("user", {}).get("id") != OPERATOR
        or comment.get("user", {}).get("login") != "peachgabba22"
        or comment.get("issue_url") != f"https://api.github.com/{API_ROOT}/issues/946"
    ):
        raise ReplayError(
            "activation requires the operator's exact canonical Issue #946 comment"
        )
    body = comment.get("body")
    if (
        type(body) is not str
        or hashlib.sha256(body.encode()).hexdigest() != expected_sha256
    ):
        raise ReplayError("activation source hash differs")
    if comment["updated_at"] != comment["created_at"]:
        raise ReplayError("activation requires a new unedited approval comment")
    return {
        "comment_id": comment_id,
        "body": body,
        "body_sha256": expected_sha256,
        "actor_account_id": str(OPERATOR),
        "actor_login": "peachgabba22",
        "created_at": comment["created_at"],
        "author_association": comment.get("author_association"),
        "url": comment["html_url"],
    }


def payloads(
    root: Path, base: str, source: dict[str, Any], provenance: dict[str, Any]
) -> dict[str, Any]:
    if files(root, base, "ledger/vnext/"):
        raise ReplayError("vNext initialization is one-time; a ledger already exists")
    body = source["body"]
    if not body.startswith(MARKER):
        raise ReplayError("activation source marker is missing")
    command = json.loads(body[len(MARKER) :])
    if set(command) != {
        "schema",
        "predecessor",
        "runtime",
        "legacy_files",
        "identities",
    }:
        raise ReplayError("activation command fields do not match")
    if command["schema"] != "wea-tide-activation-1" or command["predecessor"] != base:
        raise ReplayError("activation command belongs to another predecessor")
    reference = list(installed_executor(EXECUTOR).reference)
    if command["runtime"] != reference:
        raise ReplayError("activation selects another runtime")
    balances, hashes = legacy(root, base)
    if command["legacy_files"] != hashes:
        raise ReplayError("legacy source freeze differs from operator approval")
    bootstrap = {
        "schema": "wea-tide-bootstrap-1",
        "repository_id": str(REPOSITORY_ID),
        "runtime": reference,
        "balances": balances,
        "identities": command["identities"],
        "legacy_files": hashes,
        "activation_source": source,
    }
    engine = Replay(bootstrap)
    for binding in engine.registry.bindings:
        if binding.actor_kind == "agent" and binding.subject_id not in balances:
            raise ReplayError("activation cannot invent replacement funded Agent IDs")
    result = {BOOTSTRAP: bootstrap, STATE: engine.state()}
    result[RECEIPT] = {
        "schema": "wea-tide-activation-receipt-1",
        "writer": "tide@system",
        "predecessor": base,
        "source": source,
        "provenance": provenance,
        "files": {path: digest(value) for path, value in result.items()},
    }
    return result


def validate_activation(root: Path, base: str, head: str, api: Any) -> dict[str, Any]:
    if git(root, "rev-list", "--parents", "-n", "1", head) != f"{head} {base}":
        raise ReplayError("activation must be one direct child of canonical main")
    changed = set(git(root, "diff", "--name-only", base, head).splitlines())
    if changed != {BOOTSTRAP, STATE, RECEIPT}:
        raise ReplayError("activation contains unexpected paths")
    receipt = read(root, head, RECEIPT)
    source = receipt["source"]
    if api is not None:
        source = fetch_source(api, source["comment_id"], source["body_sha256"])
        if source != receipt["source"]:
            raise ReplayError(
                "activation source is not the authenticated operator approval"
            )
        provenance = receipt["provenance"]
        run = api.get(
            f"{API_ROOT}/actions/runs/{int(provenance['run_id'])}/attempts/{int(provenance['run_attempt'])}"
        )
        if (
            run["head_sha"] != base
            or run["path"] != ".github/workflows/tide.yml"
            or run["event"] != "workflow_dispatch"
            or run["head_branch"] != "main"
            or run["triggering_actor"]["id"] != OPERATOR
        ):
            raise ReplayError(
                "activation was not dispatched by the approved operator on main"
            )
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ReplayError("activation predecessor is stale")
    expected = payloads(root, base, source, receipt["provenance"])
    for path, value in expected.items():
        if read(root, head, path) != value:
            raise ReplayError(f"activation differs from retained source replay: {path}")
    return expected[STATE]
