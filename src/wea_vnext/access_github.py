"""Canonical GitHub Access journal and explicitly activated trusted handler."""

from __future__ import annotations

import argparse
import atexit
import base64
import hashlib
import io
import json
import os
import re
import signal
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from . import access_control as control
from . import access_protocol
from .tide.collection import API_ROOT, REPOSITORY, REPOSITORY_ID, _pages, _source
from .tide.github import GitHub as GitHubClient
from .tide.github import GitHubError
from .tide.ledger import load
from .tide.replay import canonical, digest, json_data

BRANCH = "wea/access-journal"
REF = "refs/heads/" + BRANCH
WORKFLOW = ".github/workflows/access.yml"
MAX_GRANTS = 500
# Twenty full comment pages require one more request to confirm completion.
COMMENT_PAGES = 21
COMMENT_LIMIT = 2000


class GitHub(GitHubClient):
    """Use native Git for immutable objects, avoiding one REST call per object."""

    def __init__(self, token: str):
        super().__init__(token)
        self._objects: dict[str, dict[str, Any]] = {}
        self._directory: Any = None
        self._batch: Any = None

    def _git(self, *args: str) -> None:
        env = dict(os.environ)
        env.update(
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_TERMINAL_PROMPT="0",
            GIT_CONFIG_COUNT="2",
            GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
            GIT_CONFIG_VALUE_0="AUTHORIZATION: basic "
            + base64.b64encode(("x-access-token:" + self.token).encode()).decode(),
            GIT_CONFIG_KEY_1="http.followRedirects",
            GIT_CONFIG_VALUE_1="false",
        )
        process = None
        try:
            process = subprocess.Popen(
                ["git", "-C", self._directory.name, *args],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=os.name != "nt",
            )
            try:
                result = process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                # Windows Git launches a wrapper plus children; kill the tree.
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                        check=True,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                raise
            if result:
                raise GitHubError("canonical Access Git object transfer failed")
        except (OSError, subprocess.SubprocessError):
            raise GitHubError("canonical Access Git object transfer failed") from None
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def close(self) -> None:
        if self._batch is not None:
            self._batch.stdin.close()
            try:
                self._batch.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._batch.kill()
                self._batch.wait()
            self._batch.stdout.close()
            self._batch.stderr.close()
            self._batch = None
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None

    def _raw(self, sha: str) -> tuple[str, bytes]:
        if self._directory is None:
            self._directory = tempfile.TemporaryDirectory(prefix="wea-access-git-")
            atexit.register(self.close)
            self._git("init", "--bare", "--quiet")
            self._batch = subprocess.Popen(
                ["git", "-C", self._directory.name, "cat-file", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        for attempt in range(2):
            self._batch.stdin.write(sha.encode() + b"\n")
            self._batch.stdin.flush()
            header = self._batch.stdout.readline().decode("ascii").strip().split()
            if header == [sha, "missing"] and attempt == 0:
                self._git(
                    "fetch",
                    "--quiet",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "--no-auto-gc",
                    f"https://github.com/{REPOSITORY}.git",
                    sha,
                )
                continue
            if len(header) != 3 or header[0] != sha or not header[2].isdigit():
                raise GitHubError("Git object header differs")
            size = int(header[2])
            if size > 4 * 1024 * 1024:
                raise GitHubError("Git object exceeds the retained evidence bound")
            raw = self._batch.stdout.read(size)
            if len(raw) != size or self._batch.stdout.read(1) != b"\n":
                raise GitHubError("Git object stream is incomplete")
            return header[1], raw
        raise GitHubError("canonical Git object is unavailable")

    def get(self, path: str) -> Any:
        match = re.fullmatch(
            re.escape(API_ROOT) + r"/git/(commits|trees|blobs)/([0-9a-f]{40})", path
        )
        if match is None:
            return super().get(path)
        kind, sha = match.groups()
        if sha not in self._objects:
            actual, raw = self._raw(sha)
            if actual != {"commits": "commit", "trees": "tree", "blobs": "blob"}[kind]:
                raise GitHubError("Git object type differs")
            if actual == "commit":
                headers = raw.split(b"\n\n", 1)[0].splitlines()
                trees = [
                    h[5:].decode("ascii") for h in headers if h.startswith(b"tree ")
                ]
                if len(trees) != 1:
                    raise GitHubError("Git commit has no unique tree")
                value = {
                    "tree": {"sha": trees[0]},
                    "parents": [
                        {"sha": h[7:].decode("ascii")}
                        for h in headers
                        if h.startswith(b"parent ")
                    ],
                }
            elif actual == "tree":
                rows = []
                while raw:
                    name, rest = raw.split(b"\0", 1)
                    mode, filename = name.split(b" ", 1)
                    rows.append(
                        {
                            "mode": mode.decode(),
                            "path": filename.decode("utf-8"),
                            "sha": rest[:20].hex(),
                            "type": "tree" if mode == b"40000" else "blob",
                        }
                    )
                    raw = rest[20:]
                value = {"tree": rows, "truncated": False}
            else:
                value = {
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode(),
                }
            self._objects[sha] = {**value, "sha": sha}
        return self._objects[sha]


def comments(api: Any, issue: int) -> list[dict[str, Any]]:
    rows = _pages(
        api.get,
        f"{API_ROOT}/issues/{issue}/comments?sort=created&direction=asc",
        COMMENT_PAGES,
    )
    if len(rows) > COMMENT_LIMIT:
        raise ValueError("Access intake exceeds 2000 comments; capture refused")
    return rows


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

    def __init__(self, api: Any, *, verify_closure: bool = True):
        self.api = api
        self.verify_closure = verify_closure
        self._snapshot: Any = None
        self.state: Any = None
        self.protocol: Any = None

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
        if self._snapshot is not None and self._snapshot[0] == head:
            return self._snapshot
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
                validate_genesis(data, verify_closure=False)
            else:
                prefix = (
                    "protocol"
                    if data["schema"] == access_protocol.SCHEMA
                    else "decision"
                )
                if path != f"{prefix}-{data['source']['object_id']}.json":
                    raise ValueError("journal decision filename differs")
            documents.append(data)
            commits.append(commit_sha)
            previous = files
        self.state = control.replay(documents[0], documents[1:])
        self.protocol = access_protocol.package(documents[0], documents[1:])
        if self.verify_closure:
            verify_installed(self.protocol)
        self._snapshot = head, documents[0], documents[1:], commits[1:]
        return self._snapshot

    def remember(
        self,
        head: str,
        genesis: dict[str, Any],
        entries: list[dict[str, Any]],
        commits: list[str],
        state: Any,
    ) -> None:
        self._snapshot = head, genesis, entries, commits
        self.state = state

    def append(self, parent: str | None, path: str, data: dict[str, Any]) -> str:
        if not self.verify_closure:
            raise ValueError("historical Access readers cannot publish decisions")
        if (parent is None and path != "genesis.json") or (
            parent is not None
            and not re.fullmatch(r"(?:decision|protocol)-[1-9][0-9]*\.json", path)
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


def validate_genesis(data: dict[str, Any], *, verify_closure: bool = True) -> None:
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
    if verify_closure:
        verify_installed(data)


def repository(api: Any, issue: int) -> dict[str, Any]:
    repo = api.get(API_ROOT)
    if (
        repo.get("id") != REPOSITORY_ID
        or repo.get("full_name") != REPOSITORY
        or type(repo.get("private")) is not bool
    ):
        raise ValueError(
            "Access requires the canonical repository with explicit Boolean visibility"
        )
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


def update_protocol(
    api: Any,
    root: Path,
    base: str,
    comment: int,
    expected_hash: str,
    provenance: dict[str, Any],
    clock: Any = control.utcnow,
) -> str:
    """Append the exact operator update from trusted main, never rewrite genesis."""
    reader = Journal(api, verify_closure=False)
    for _ in range(3):
        head, genesis, entries, commits = reader.read()
        if genesis is None:
            raise ValueError("protocol update requires an activated journal")
        issue = repository(api, genesis["issue_number"])
        if str(issue["id"]) != genesis["issue_id"]:
            raise ValueError("activated Issue differs")
        source = capture(
            api,
            genesis["issue_number"],
            api.get(f"{API_ROOT}/issues/comments/{comment}"),
        )
        if source["content_hash"] != expected_hash:
            raise ValueError("protocol update source hash differs")
        for entry, commit in zip(entries, commits, strict=True):
            if entry["source"]["object_id"] == str(comment):
                if (
                    entry["schema"] != access_protocol.SCHEMA
                    or entry["source"] != source
                ):
                    raise ValueError(
                        "protocol update retry differs from retained source"
                    )
                return commit
        data = {
            "schema": access_protocol.SCHEMA,
            "source": source,
            "accepted_at": json_data(clock()),
            "code_sha": base,
            "protocol_files": protocol(root, base),
            "provenance": provenance,
        }
        data["decision"] = access_protocol.decision(
            reader.protocol, base, data["protocol_files"]
        )
        control.replay(genesis, [*entries, data])
        verify_installed(data)
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ValueError("canonical main changed before protocol update")
        try:
            return Journal(api).append(head, f"protocol-{comment}.json", data)
        except GitHubError:
            continue
    raise GitHubError("protocol update unresolved; retry the same source and hash")


def process(
    api: Any,
    source: dict[str, Any],
    identities: dict[str, Any],
    identity_commit: str,
    provenance: dict[str, Any],
    clock: Any = control.utcnow,
    journal: Journal | None = None,
) -> dict[str, Any]:
    journal = journal or Journal(api)
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
        from . import initiatives

        initiative = source["body"].startswith(initiatives.MARKER)
        observations = []
        if initiative:
            # Resolve by locator, then check the permanent ID before any append.
            refs = []
            try:
                command = initiatives.request(source["body"])
                refs = initiatives.repository_refs(command)
                provisional = [
                    {
                        "requested_locator": r["repository_locator"],
                        "repository_id": r["repository_id"],
                        "repository_locator": r["repository_locator"],
                        **(
                            {
                                "context_revision": command["payload"]["record"][
                                    "revision"
                                ]
                            }
                            if command["operation"]
                            in {"registry-add", "registry-replace"}
                            else {}
                        ),
                    }
                    for r in refs
                ]
                initiatives.repositories(command, provisional)
                # Pure preflight rejects unauthorized, stale, and inapplicable
                # requests before any required network read can block intake.
                _, preliminary = initiatives.decide(
                    genesis,
                    journal.state,
                    entries,
                    source,
                    identities,
                    accepted,
                    provisional,
                    journal.protocol,
                    provenance,
                )
                if preliminary["status"] == "rejected" or "duplicate_of" in preliminary:
                    refs = []
            except (ValueError, KeyError, TypeError, AttributeError):
                refs = []
            for ref in refs:
                locator = ref["repository_locator"]
                repo = api.get(
                    "https://api.github.com/repos/"
                    + locator.removeprefix("https://github.com/")
                )
                observations.append(
                    {
                        "requested_locator": locator,
                        "repository_id": ref["repository_id"]
                        if ref["repository_id"] in {str(repo["id"]), repo["node_id"]}
                        else repo["node_id"],
                        "repository_locator": "https://github.com/" + repo["full_name"],
                    }
                )
                if command["operation"] in {"registry-add", "registry-replace"}:
                    revision = command["payload"]["record"]["revision"]
                    value = api.graphql(
                        "query($id:ID!,$revision:String!){node(id:$id){"
                        "... on Repository{id nameWithOwner "
                        "object(expression:$revision){"
                        "... on Commit{oid}}}}}",
                        {"id": repo["node_id"], "revision": revision},
                    )
                    node = value.get("data", {}).get("node")
                    if (
                        value.get("errors")
                        or not node
                        or node.get("id") != repo["node_id"]
                    ):
                        raise ValueError(
                            "required permanent repository context read failed"
                        )
                    if not node.get("object") or node["object"].get("oid") != revision:
                        raise ValueError(
                            "context revision is not a commit "
                            "in the permanent repository"
                        )
                    observations[-1].update(
                        context_revision=revision,
                        repository_locator="https://github.com/"
                        + node["nameWithOwner"],
                    )
            candidate_state, decision = initiatives.decide(
                genesis,
                journal.state,
                entries,
                source,
                identities,
                accepted,
                observations,
                journal.protocol,
                provenance,
            )
        else:
            candidate_state, decision = control.decide(
                genesis,
                journal.state,
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
            "schema": initiatives.SCHEMA if initiative else control.SCHEMA,
            **({"repositories": observations} if initiative else {}),
            "source": source,
            "identities": identities,
            "identity_commit": identity_commit,
            "accepted_at": accepted,
            "provenance": provenance,
            "decision": decision,
        }
        if entries and control.timestamp(accepted) < control.timestamp(
            entries[-1]["accepted_at"]
        ):
            raise ValueError("trusted acceptance clock moved backwards")
        try:
            commit = journal.append(head, f"decision-{source['object_id']}.json", entry)
            journal.remember(
                commit, genesis, [*entries, entry], [*commits, commit], candidate_state
            )
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
    observed = comments(api, issue)
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
            for c in observed
        ):
            continue
        if len(observed) >= COMMENT_LIMIT:
            raise ValueError("Access receipt pending: Issue comment capacity reached")
        receipt = api.request(
            "POST", f"{API_ROOT}/issues/{issue}/comments", {"body": body}
        )
        observed.append(receipt)


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
    update_comment = getattr(args, "protocol_comment_id", None)
    if (
        sum(
            bool(value)
            for value in (
                update_comment,
                args.activation_comment_id,
                getattr(args, "initiative_comment_id", None),
            )
        )
        > 1
    ):
        raise ValueError("installation updates and activation are separate operations")
    if update_comment:
        if workflow_run["event"] != "workflow_dispatch":
            raise ValueError("protocol updates require explicit workflow dispatch")
        update_protocol(
            api, root, base, update_comment, args.protocol_sha256, provenance
        )
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
    journal = Journal(api)
    head, genesis, entries, _ = journal.read()
    if genesis is None:
        return {"status": "disabled"}
    issue = repository(api, genesis["issue_number"])
    if (
        str(issue["id"]) != genesis["issue_id"]
        or protocol(root, base) != journal.protocol["protocol_files"]
    ):
        raise ValueError("activated Issue or protocol closure differs")
    engine, _ = load(root, base)
    identities = json_data(engine.registry)
    from . import initiatives

    policy_comment = getattr(args, "initiative_comment_id", None)
    if policy_comment:
        if workflow_run["event"] != "workflow_dispatch":
            raise ValueError(
                "initiative activation requires explicit workflow dispatch"
            )
        row = api.get(f"{API_ROOT}/issues/comments/{int(policy_comment)}")
        source = capture(api, genesis["issue_number"], row)
        if source["content_hash"] != args.initiative_sha256:
            raise ValueError("initiative activation body hash differs")
        if initiatives.request(source["body"])["operation"] != "activate-policy":
            raise ValueError("initiative activation dispatch names another operation")
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ValueError("canonical main changed before activation")
        process(
            api,
            source,
            identities,
            base,
            {
                **provenance,
                "event": "workflow_dispatch",
                "initiative_activation": source["content_hash"],
            },
            journal=journal,
        )
        head, genesis, entries, _ = journal.read()
    processed = {e["source"]["object_id"] for e in entries}
    rows = comments(api, genesis["issue_number"])
    for row in sorted(rows, key=lambda r: (r["created_at"], r["id"])):
        if str(row["id"]) in processed or not (row.get("body") or "").startswith(
            (control.MARKER, initiatives.MARKER)
        ):
            continue
        if control.timestamp(row["created_at"]) <= control.timestamp(genesis["cutoff"]):
            continue
        source = capture(api, genesis["issue_number"], row)
        if source["body"].startswith(initiatives.MARKER):
            if not isinstance(journal.state, initiatives.State):
                continue
            try:
                operation = initiatives.request(source["body"])["operation"]
            except (ValueError, KeyError, TypeError, AttributeError):
                operation = None
            if operation == "activate-policy":
                continue
        if api.get(f"{API_ROOT}/git/ref/heads/main")["object"]["sha"] != base:
            raise ValueError("canonical identity snapshot changed; dispatch again")
        process(api, source, identities, base, provenance, journal=journal)
    head, genesis, entries, commits = journal.read()
    repair_receipts(api, genesis, entries, commits)
    return {"status": "reconciled", "journal_commit": head, "decisions": len(entries)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--activation-comment-id", type=int)
    parser.add_argument("--activation-sha256", default="")
    parser.add_argument("--protocol-comment-id", type=int)
    parser.add_argument("--protocol-sha256", default="")
    parser.add_argument("--initiative-comment-id", type=int)
    parser.add_argument("--initiative-sha256", default="")
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
