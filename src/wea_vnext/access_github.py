"""Private GitHub Access journal and explicitly activated trusted handler."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from . import access_control as control
from .tide.collection import API_ROOT, REPOSITORY, REPOSITORY_ID, _pages, _source
from .tide.github import GitHub, GitHubError
from .tide.ledger import load
from .tide.replay import canonical, digest, json_data

BRANCH = "wea/access-journal"
REF = "refs/heads/" + BRANCH
WORKFLOW = ".github/workflows/access.yml"
MAX_GRANTS = 500
# Twenty full comment pages require one more request to confirm completion.
COMMENT_PAGES = 21


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout.strip()


def protocol(root: Path, sha: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("protocol requires a full code SHA")
    paths = git(
        root,
        "ls-tree",
        "-r",
        "--name-only",
        sha,
        "src/wea_vnext",
        "src/wea_cli/access.py",
        WORKFLOW,
    ).splitlines()
    if "src/wea_vnext/access_github.py" not in paths or WORKFLOW not in paths:
        raise ValueError("Access protocol is not installed in the selected commit")
    archive = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "archive",
            sha,
            "src/wea_vnext",
            "src/wea_cli/access.py",
            WORKFLOW,
        ],
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        return {
            p: hashlib.sha256(bundle.extractfile(p).read()).hexdigest() for p in paths
        }


def verify_installed(genesis: dict[str, Any]) -> None:
    """Check actual imported package bytes, including transitive vNext imports."""
    import wea_cli

    for path, expected in genesis["protocol_files"].items():
        if path.startswith("src/wea_vnext/"):
            local = Path(__file__).parent / path.removeprefix("src/wea_vnext/")
        elif path == "src/wea_cli/access.py":
            local = Path(wea_cli.__file__).parent / "access.py"
        elif path == WORKFLOW:
            continue  # Trusted execution checks the committed workflow separately.
        else:
            raise ValueError("unexpected protocol closure path")
        if (
            not local.is_file()
            or hashlib.sha256(local.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"installed Access closure differs: {path}")


class Journal:
    """Append one file by a non-forced ref update; never write main or a ledger."""

    def __init__(self, api: Any):
        self.api = api

    def head(self) -> str | None:
        refs = self.api.get(f"{API_ROOT}/git/matching-refs/heads/{BRANCH}")
        matches = [r for r in refs if r["ref"] == REF]
        if len(matches) > 1:
            raise ValueError("ambiguous Access journal ref")
        return matches[0]["object"]["sha"] if matches else None

    def read(
        self,
    ) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]], list[str]]:
        head = self.head()
        if head is None:
            return None, None, [], []
        history = []
        cursor = head
        visited: set[str] = set()
        while cursor:
            if cursor in visited:
                raise ValueError("Access journal cycle detected")
            visited.add(cursor)
            commit = self.api.get(f"{API_ROOT}/git/commits/{cursor}")
            if commit["sha"] != cursor or len(commit["parents"]) > 1:
                raise ValueError("Access journal requires linear Git ancestry")
            tree = self.api.get(f"{API_ROOT}/git/trees/{commit['tree']['sha']}")
            if tree.get("truncated") or tree["sha"] != commit["tree"]["sha"]:
                raise ValueError("journal tree is incomplete")
            items = tree["tree"]
            if any(i["type"] != "blob" or i["mode"] != "100644" for i in items):
                raise ValueError("journal contains a non-record object")
            files = {i["path"]: i["sha"] for i in items}
            if len(files) != len(items):
                raise ValueError("duplicate journal path")
            history.append((cursor, files))
            cursor = commit["parents"][0]["sha"] if commit["parents"] else None
        previous: dict[str, str] = {}
        documents = []
        commits = []
        for commit_sha, files in reversed(history):
            added = set(files) - set(previous)
            if len(added) != 1 or any(files.get(p) != h for p, h in previous.items()):
                raise ValueError("journal must append exactly one immutable record")
            path = added.pop()
            blob = self.api.get(f"{API_ROOT}/git/blobs/{files[path]}")
            if blob.get("encoding") != "base64":
                raise ValueError("journal blob is not base64")
            raw = base64.b64decode("".join(blob["content"].split()), validate=True)
            # Git blob object IDs require SHA-1. Source/protocol hashes use SHA-256.
            actual = hashlib.sha1(  # nosemgrep
                b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
            ).hexdigest()
            if (
                blob["sha"] != files[path]
                or actual != files[path]
                or len(raw) > 4 * 1024 * 1024
            ):
                raise ValueError("journal blob integrity differs")
            data = control.strict_json(raw.decode("utf-8"))
            if canonical(data) != raw:
                raise ValueError("journal record encoding is not canonical")
            if not documents:
                if path != "genesis.json":
                    raise ValueError("journal has no unique genesis")
                validate_genesis(data)
            elif path != f"decision-{data['source']['object_id']}.json":
                raise ValueError("journal decision filename differs")
            documents.append(data)
            commits.append(commit_sha)
            previous = files
        control.replay(documents[0], documents[1:])
        return head, documents[0], documents[1:], commits[1:]

    def append(self, parent: str | None, path: str, data: dict[str, Any]) -> str:
        if (parent is None and path != "genesis.json") or (
            parent is not None and not re.fullmatch(r"decision-[1-9][0-9]*\.json", path)
        ):
            raise ValueError("invalid Access append path")
        tree_input: dict[str, Any] = {
            "tree": [
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    "content": canonical(data).decode("utf-8"),
                }
            ]
        }
        if parent:
            tree_input["base_tree"] = self.api.get(f"{API_ROOT}/git/commits/{parent}")[
                "tree"
            ]["sha"]
        tree = self.api.request("POST", f"{API_ROOT}/git/trees", tree_input)
        commit = self.api.request(
            "POST",
            f"{API_ROOT}/git/commits",
            {
                "message": f"Access: retain {path}",
                "tree": tree["sha"],
                "parents": [parent] if parent else [],
            },
        )
        if parent:
            self.api.request(
                "PATCH",
                f"{API_ROOT}/git/refs/heads/{BRANCH}",
                {"sha": commit["sha"], "force": False},
            )
        else:
            self.api.request(
                "POST", f"{API_ROOT}/git/refs", {"ref": REF, "sha": commit["sha"]}
            )
        return commit["sha"]


def validate_genesis(data: dict[str, Any]) -> None:
    if set(data) != {
        "schema",
        "repository_id",
        "issue_number",
        "issue_id",
        "code_sha",
        "protocol_files",
        "registry_text",
        "registry_hash",
        "cutoff",
        "activation",
        "provenance",
    }:
        raise ValueError("Access genesis fields differ")
    source = data["activation"]
    if data["schema"] != control.SCHEMA or data["repository_id"] != str(REPOSITORY_ID):
        raise ValueError("Access genesis repository or format differs")
    if (
        source["actor_account_id"] != str(control.OPERATOR)
        or source["original_author_account_id"] != str(control.OPERATOR)
        or source["edit_history"]
        or source["revision_status"] != "confirmed"
        or not source["revision_id"].endswith(":created")
        or source["issue_number"] != data["issue_number"]
        or source["repository_id"] != str(REPOSITORY_ID)
        or control.sha256(source["body"]) != source["content_hash"]
    ):
        raise ValueError("activation requires an exact unedited operator source")
    if not source["body"].startswith(control.ACTIVATION_MARKER):
        raise ValueError("activation marker differs")
    command = control.strict_json(source["body"][len(control.ACTIVATION_MARKER) :])
    expected = {
        "schema": control.SCHEMA,
        "code_sha": data["code_sha"],
        "protocol_hash": digest(data["protocol_files"]),
        "registry_hash": data["registry_hash"],
        "issue_number": data["issue_number"],
        "journal_ref": REF,
    }
    if command != expected or data["cutoff"] != source["created_at"]:
        raise ValueError("activation payload or fresh-source cutoff differs")
    if not re.fullmatch(r"[0-9a-f]{40}", data["code_sha"]):
        raise ValueError("activation code SHA differs")
    control.initial_state(data)
    verify_installed(data)


def repository(api: Any, issue: int) -> dict[str, Any]:
    repo = api.get(API_ROOT)
    if (
        repo.get("id") != REPOSITORY_ID
        or repo.get("full_name") != REPOSITORY
        or repo.get("private") is not True
    ):
        raise ValueError("Access pilot requires the canonical private repository")
    item = api.get(f"{API_ROOT}/issues/{issue}")
    if item.get("number") != issue or "pull_request" in item:
        raise ValueError("Access intake must be the configured Issue")
    return item


def capture(api: Any, issue: int, row: dict[str, Any]) -> dict[str, Any]:
    value = _source(
        row,
        number=issue,
        kind="issue_comment",
        cutoff=control.utcnow(),
        api_graphql=api.graphql,
        max_pages=20,
    )
    if value is None:
        raise ValueError("source is newer than the trusted capture clock")
    return value


def activate(
    api: Any,
    root: Path,
    base: str,
    issue: int,
    comment: int,
    expected_hash: str,
    provenance: dict[str, Any],
) -> str:
    journal = Journal(api)
    head, existing, _, _ = journal.read()
    if existing:
        if (
            existing["activation"]["object_id"] == str(comment)
            and existing["activation"]["content_hash"] == expected_hash
        ):
            return head
        raise ValueError("Access activation is one-time")
    issue_data = repository(api, issue)
    source = capture(api, issue, api.get(f"{API_ROOT}/issues/comments/{comment}"))
    if source["content_hash"] != expected_hash:
        raise ValueError("activation source hash differs")
    raw = subprocess.run(
        ["git", "-C", str(root), "show", f"{base}:domains/registry/v1.json"],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    registry = control.load_domain_registry_bytes(raw.encode(), source="canonical main")
    data = {
        "schema": control.SCHEMA,
        "repository_id": str(REPOSITORY_ID),
        "issue_number": issue,
        "issue_id": str(issue_data["id"]),
        "code_sha": base,
        "protocol_files": protocol(root, base),
        "registry_text": raw,
        "registry_hash": registry.registry_hash,
        "cutoff": source["created_at"],
        "activation": source,
        "provenance": provenance,
    }
    validate_genesis(data)
    try:
        return journal.append(None, "genesis.json", data)
    except GitHubError:
        recovered, observed, _, _ = journal.read()
        if observed == data:
            return recovered
        raise


def process(
    api: Any,
    source: dict[str, Any],
    identities: dict[str, Any],
    identity_commit: str,
    provenance: dict[str, Any],
    clock: Any = control.utcnow,
) -> dict[str, Any]:
    journal = Journal(api)
    for _ in range(3):
        head, genesis, entries, commits = journal.read()
        if genesis is None:
            return {"status": "disabled"}
        existing = next(
            (
                i
                for i, e in enumerate(entries)
                if e["source"]["object_id"] == source["object_id"]
            ),
            None,
        )
        if existing is not None:
            return control.view(entries[existing], commits[existing], clock())
        accepted = json_data(clock())
        candidate_state, decision = control.decide(
            genesis,
            control.replay(genesis, entries),
            entries,
            source,
            identities,
            accepted,
        )
        if len(candidate_state.grants) > MAX_GRANTS:
            raise ValueError(
                "Access pilot grant capacity reached; existing history remains readable"
            )
        entry = {
            "schema": control.SCHEMA,
            "source": source,
            "identities": identities,
            "identity_commit": identity_commit,
            "accepted_at": accepted,
            "provenance": provenance,
            "decision": decision,
        }
        control.replay(genesis, [*entries, entry])
        try:
            commit = journal.append(head, f"decision-{source['object_id']}.json", entry)
            return control.view(entry, commit, clock())
        except GitHubError:
            # Readback resolves both a competing append and a lost acknowledgement.
            continue
    raise GitHubError(
        "Access publication unresolved after readback; retry the same request ID"
    )


def repair_receipts(
    api: Any, genesis: dict[str, Any], entries: list[dict[str, Any]], commits: list[str]
) -> None:
    issue = genesis["issue_number"]
    comments = _pages(
        api.get,
        f"{API_ROOT}/issues/{issue}/comments?sort=created&direction=asc",
        COMMENT_PAGES,
    )
    for entry, commit in zip(entries, commits, strict=True):
        marker = f"<!-- wea-access-receipt:{commit} -->"
        body = (
            marker
            + "\nAccess decision: "
            + entry["decision"]["status"]
            + f"\n\n[Canonical journal](https://github.com/{REPOSITORY}/commit/{commit})\n"
        )
        body += (
            "\n```json\n"
            + json.dumps(entry["decision"], ensure_ascii=False, indent=2)
            + "\n```\n"
        )
        if any(
            c.get("user", {}).get("type") == "Bot"
            and c.get("user", {}).get("login") == "github-actions[bot]"
            and c.get("body") == body
            for c in comments
        ):
            continue
        api.request("POST", f"{API_ROOT}/issues/{issue}/comments", {"body": body})


def run(args: argparse.Namespace) -> dict[str, Any]:
    if (
        os.environ.get("GITHUB_REPOSITORY") != REPOSITORY
        or os.environ.get("GITHUB_REF") != "refs/heads/main"
    ):
        raise ValueError("Access writes require the trusted canonical main workflow")
    api = GitHub(os.environ.get("GITHUB_TOKEN", ""))
    root = Path.cwd()
    base = api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"]
    if git(root, "rev-parse", "HEAD") != base or os.environ.get("GITHUB_SHA") != base:
        raise ValueError("Access handler checkout is not current canonical main")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "")
    workflow_run = api.get(
        f"{API_ROOT}/actions/runs/{int(run_id)}/attempts/{int(attempt)}"
    )
    if (
        workflow_run["path"] != WORKFLOW
        or workflow_run["head_sha"] != base
        or workflow_run["head_branch"] != "main"
        or workflow_run["event"] not in {"issue_comment", "workflow_dispatch"}
    ):
        raise ValueError("Access provenance does not name the trusted workflow")
    provenance = {
        "run_id": run_id,
        "run_attempt": attempt,
        "code_sha": base,
        "workflow": WORKFLOW,
    }
    if args.activation_comment_id:
        activate(
            api,
            root,
            base,
            args.issue,
            args.activation_comment_id,
            args.activation_sha256,
            provenance,
        )
    head, genesis, entries, _ = Journal(api).read()
    if genesis is None:
        return {"status": "disabled"}
    issue = repository(api, genesis["issue_number"])
    if (
        str(issue["id"]) != genesis["issue_id"]
        or protocol(root, base) != genesis["protocol_files"]
    ):
        raise ValueError("activated Issue or protocol closure differs")
    engine, _ = load(root, base)
    identities = json_data(engine.registry)
    processed = {e["source"]["object_id"] for e in entries}
    rows = _pages(
        api.get,
        f"{API_ROOT}/issues/{genesis['issue_number']}/comments?sort=created&direction=asc",
        COMMENT_PAGES,
    )
    for row in sorted(rows, key=lambda r: (r["created_at"], r["id"])):
        if str(row["id"]) in processed or not (row.get("body") or "").startswith(
            control.MARKER
        ):
            continue
        if control.timestamp(row["created_at"]) <= control.timestamp(genesis["cutoff"]):
            continue
        source = capture(api, genesis["issue_number"], row)
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ValueError("canonical identity snapshot changed; dispatch again")
        process(api, source, identities, base, provenance)
    head, genesis, entries, commits = Journal(api).read()
    repair_receipts(api, genesis, entries, commits)
    return {"status": "reconciled", "journal_commit": head, "decisions": len(entries)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--activation-comment-id", type=int)
    parser.add_argument("--activation-sha256", default="")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), ensure_ascii=False))
        return 0
    except (
        ValueError,
        KeyError,
        TypeError,
        OSError,
        GitHubError,
        subprocess.CalledProcessError,
    ) as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
