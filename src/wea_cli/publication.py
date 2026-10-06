"""Bounded publication of one assigned, already pushed WEA deliverable.

Local assignment bytes are coordination evidence, not identity/admission authority.
The coordinator must confirm current occupancy immediately before invocation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import freshness, git_transport

REPO = "WeTheAgents/wetheagents"
REPOSITORY_ID = 1171421025
DESTINATION = "https://github.com/WeTheAgents/wetheagents.git"
BRANCHES = {"work/agent0", "work/slot-1", "work/slot-2", "work/slot-3"}
TASK = re.compile(r"https://github\.com/WeTheAgents/wetheagents/issues/([1-9][0-9]*)\Z")
OID = re.compile(r"[0-9a-f]{40}\Z")
# GitHub's documented keywords, optional colon/case, and issue reference forms.
# Also reject the same construction with Markdown emphasis/link wrappers or URL.
# This is a conservative text check, not a claim to reproduce GitHub's parser.
CLOSING = re.compile(
    r"\b(?:close[sd]?|fix(?:es|ed)?|resolve[sd]?)\b"
    r"[\s:*_`]*\[?(?:#[1-9][0-9]*\b|"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*\b|"
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/"
    r"(?:issues|pull)/[1-9][0-9]*\b)",
    re.IGNORECASE,
)


class PublicationError(ValueError):
    """A required publication fact could not be established."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw: str) -> Any:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise PublicationError("Duplicate JSON field")
            value[key] = item
        return value

    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, TypeError) as exc:
        raise PublicationError("Invalid or duplicate JSON fields") from exc


@dataclass(frozen=True)
class Intent:
    repository: str
    task_url: str
    agent_id: str
    session: str
    workplace: str
    branch: str
    dispatch_base: str
    head: str
    account: str
    account_id: str
    title: str
    body: str
    draft: bool
    assignment_sha256: str

    def identity(self) -> dict[str, Any]:
        value = asdict(self)
        value["body_sha256"] = digest(value.pop("body").encode("utf-8"))
        return value


def load_intent(args: argparse.Namespace, root: Path) -> Intent:
    raw = Path(args.assignment).read_bytes()
    if digest(raw) != args.assignment_sha256:
        raise PublicationError(
            "Assignment bytes differ from independently pinned digest"
        )
    packet = strict_json(raw.decode("utf-8"))
    keys = {
        "schema",
        "repository",
        "destination",
        "task_url",
        "agent_id",
        "session",
        "workplace",
        "branch",
        "dispatch_base",
        "head",
        "account",
        "account_id",
    }
    if not isinstance(packet, dict) or set(packet) != keys:
        raise PublicationError("Assignment fields differ")
    if any(type(value) is not str or not value for value in packet.values()):
        raise PublicationError("Assignment fields must be nonempty strings")
    if (
        packet["schema"] != "wea-publication-assignment-1"
        or args.repo != REPO
        or packet["repository"] != REPO
        or packet["destination"] != DESTINATION
        or packet["task_url"] != args.task_url
        or not TASK.fullmatch(args.task_url)
        or packet["session"] != args.session
        or packet["head"] != args.expected_head
        or not OID.fullmatch(packet["head"])
        or not OID.fullmatch(packet["dispatch_base"])
        or packet["branch"] not in BRANCHES
        or not Path(packet["workplace"]).is_absolute()
        or Path(packet["workplace"]).resolve() != root.resolve()
        or not re.fullmatch(r"[A-Za-z0-9_-]+@[A-Za-z0-9_-]+", packet["agent_id"])
        or not re.fullmatch(r"[1-9][0-9]*", packet["account_id"])
        or not re.fullmatch(r"[A-Za-z0-9-]+", packet["account"])
    ):
        raise PublicationError(
            "Assignment/session/task/workplace/head/repository mismatch"
        )
    if os.environ.get("WEA_AGENT", packet["agent_id"]) != packet["agent_id"]:
        raise PublicationError("WEA_AGENT conflicts with assigned identity")
    issue = TASK.fullmatch(args.task_url).group(1)
    title = args.title
    if (
        not title.startswith(f"[Task #{issue}] ")
        or not title[len(f"[Task #{issue}] ") :].strip()
    ):
        raise PublicationError("Title must name the exact assigned task")
    body = Path(args.body_file).read_bytes().decode("utf-8").replace("\r\n", "\n")
    if len(body.encode()) > 65536 or "\x00" in body or "\r" in body or "\ufeff" in body:
        raise PublicationError(
            "Body must be UTF-8 without BOM/NUL/lone CR, at most 64KiB"
        )
    if any(ord(char) < 32 for char in title) or len(title) > 256:
        raise PublicationError("Invalid title")
    markers = [line for line in body.split("\n") if line.startswith("Task:")]
    agents = [line for line in body.split("\n") if line.startswith("Agent ID:")]
    if markers != [f"Task: {args.task_url}"] or agents != [
        f"Agent ID: {packet['agent_id']}"
    ]:
        raise PublicationError(
            "Require one exact Task: URL and one exact Agent ID: marker"
        )
    if CLOSING.search(title) or CLOSING.search(body):
        raise PublicationError(
            "Autoclosing keyword/reference construction is forbidden"
        )
    return Intent(
        REPO,
        args.task_url,
        packet["agent_id"],
        args.session,
        str(root.resolve()),
        packet["branch"],
        packet["dispatch_base"],
        packet["head"],
        packet["account"],
        packet["account_id"],
        title,
        body,
        bool(args.draft),
        args.assignment_sha256,
    )


def local_checks(root: Path, intent: Intent) -> None:
    git = git_transport.run
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise PublicationError("Publication root must be the assigned Git toplevel")
    if git(root, "symbolic-ref", "--quiet", "HEAD") != f"refs/heads/{intent.branch}":
        raise PublicationError("Detached or unassigned branch")
    if git(root, "rev-parse", "--verify", "HEAD^{commit}") != intent.head:
        raise PublicationError("HEAD changed from assigned commit")
    if git(
        root,
        "status",
        "--porcelain",
        "--untracked-files=all",
        "--ignore-submodules=none",
    ):
        raise PublicationError("Dirty tracked/untracked/submodule state")
    for marker in (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "BISECT_START",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    ):
        path = Path(git(root, "rev-parse", "--git-path", marker))
        if (path if path.is_absolute() else root / path).exists():
            raise PublicationError("Unfinished Git operation")
    if git(root, "rev-parse", "--is-shallow-repository") != "false":
        raise PublicationError("Complete Git ancestry is required")
    git(root, "merge-base", "--is-ancestor", intent.dispatch_base, intent.head)
    messages = git(
        root, "log", "--format=%B%x00", f"{intent.dispatch_base}..{intent.head}"
    )
    if CLOSING.search(messages):
        raise PublicationError("Autoclosing construction in delivery commit range")


def remote_checks(root: Path, intent: Intent) -> None:
    git = git_transport.run
    urls = git(root, "remote", "get-url", "--push", "--all", "push-origin").split("\n")
    if urls != [DESTINATION]:
        raise PublicationError("Require exactly one canonical push-origin destination")
    if (
        git(
            root,
            "config",
            "--type=bool",
            "--default=false",
            "--get",
            "remote.push-origin.mirror",
        )
        != "false"
    ):
        raise PublicationError("Mirror publication is forbidden")
    ref = f"refs/heads/{intent.branch}"
    rows = git(root, "ls-remote", "--exit-code", DESTINATION, ref).splitlines()
    exact = [row.split("\t") for row in rows if row.partition("\t")[2] == ref]
    if exact != [[intent.head, ref]]:
        raise PublicationError(
            "Already-pushed remote commit does not match assigned HEAD"
        )


class GitHub:
    """Only bounded gh calls; never expose its raw credential-bearing diagnostics."""

    def __init__(self, root: Path):
        self.root = root

    def api(self, endpoint: str, payload: dict | None = None) -> Any:
        args = ["gh", "api", endpoint]
        if payload is not None:
            args += ["--method", "POST", "--input", "-"]
        try:
            result = subprocess.run(
                args,
                cwd=self.root,
                input=None if payload is None else json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
            )
            if result.returncode:
                raise PublicationError(
                    "GitHub request failed; inspect retained attempt"
                )
            return strict_json(result.stdout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PublicationError("GitHub request failed or timed out") from exc

    def binding(self, intent: Intent) -> None:
        user = self.api("user")
        repo = self.api(f"repos/{REPO}")
        if (
            user.get("login") != intent.account
            or str(user.get("id")) != intent.account_id
            or repo.get("id") != REPOSITORY_ID
            or repo.get("full_name") != REPO
            or repo.get("default_branch") != "main"
        ):
            raise PublicationError(
                "Authenticated account or immutable repository binding differs"
            )

    def history(self) -> list[dict]:
        # Inspect complete repository history, not a truncated search or head-only list.
        rows = []
        for page in range(1, 101):
            batch = self.api(f"repos/{REPO}/pulls?state=all&per_page=100&page={page}")
            if not isinstance(batch, list) or len(batch) > 100:
                raise PublicationError("Incomplete PR history")
            rows.extend(batch)
            if len(batch) < 100:
                numbers = [row["number"] for row in rows]
                if len(numbers) != len(set(numbers)):
                    raise PublicationError("PR history changed across pagination")
                return rows
        raise PublicationError(
            "PR history exceeds bounded pagination; reconcile manually"
        )

    def create(self, intent: Intent) -> Any:
        return self.api(
            f"repos/{REPO}/pulls",
            {
                "title": intent.title,
                "body": intent.body,
                "head": intent.branch,
                "base": "main",
                "draft": intent.draft,
            },
        )

    def read(self, number: int) -> Any:
        return self.api(f"repos/{REPO}/pulls/{number}")

    def closing(self, number: int) -> list:
        # The actual server interpretation complements the preflight text check.
        query = (
            'query { repository(owner:"WeTheAgents",name:"wetheagents") { '
            f"pullRequest(number:{number}) {{ closingIssuesReferences(first:100) "
            "{ nodes { number } pageInfo { hasNextPage } } } } }"
        )
        data = self.api("graphql", {"query": query})
        if data.get("errors"):
            raise PublicationError("Closing-reference readback failed")
        result = data["data"]["repository"]["pullRequest"]["closingIssuesReferences"]
        if result["pageInfo"]["hasNextPage"]:
            raise PublicationError("Incomplete closing-reference readback")
        return result["nodes"]


def exact_match(row: dict, intent: Intent) -> bool:
    return (
        row.get("state") == "open"
        and not row.get("merged_at")
        and row.get("title") == intent.title
        and row.get("body") == intent.body
        and row.get("draft") is intent.draft
        and row.get("user", {}).get("login") == intent.account
        and str(row.get("user", {}).get("id")) == intent.account_id
        and row.get("base", {}).get("ref") == "main"
        and row.get("base", {}).get("repo", {}).get("id") == REPOSITORY_ID
        and row.get("head", {}).get("repo", {}).get("id") == REPOSITORY_ID
        and row.get("head", {}).get("ref") == intent.branch
        and row.get("head", {}).get("sha") == intent.head
    )


def select_existing(rows: list[dict], intent: Intent) -> dict | None:
    relevant = [
        row
        for row in rows
        if (
            (
                row.get("state") == "open"
                and row.get("head", {}).get("ref") == intent.branch
            )
            or re.search(
                re.escape(intent.task_url) + r"(?![0-9A-Za-z/?#])",
                (row.get("body") or ""),
            )
            or row.get("title", "").startswith(
                f"[Task #{TASK.fullmatch(intent.task_url).group(1)}]"
            )
        )
    ]
    if not relevant:
        return None
    if len(relevant) != 1 or not exact_match(relevant[0], intent):
        raise PublicationError(
            "Existing slot/task PR conflicts; reconcile without creating/editing"
        )
    return relevant[0]


class Receipt:
    """One durable per-task attempt in shared Git storage, across slot changes.

    Exclusive initial creation prevents two helpers from submitting this task.
    The operator must retain receipts and serialize work; this is not authority.
    """

    def __init__(self, root: Path, intent: Intent):
        common = Path(git_transport.run(root, "rev-parse", "--git-common-dir"))
        if not common.is_absolute():
            common = root / common
        self.path = (
            common / "wea-publication" / (digest(intent.task_url.encode()) + ".json")
        )
        self.intent = intent

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        value = strict_json(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(value, dict)
            or value.get("schema") != "wea-publication-receipt-1"
            or value.get("intent") != self.intent.identity()
            or value.get("status")
            not in {
                "attempted",
                "outcome_unknown",
                "verified",
                "verification_failed_pr_exists",
            }
        ):
            raise PublicationError(
                "Retained task receipt conflicts; coordinator reconciliation required"
            )
        return value

    def save(
        self, status: str, number: int | None = None, *, initial: bool = False
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(
            {
                "schema": "wea-publication-receipt-1",
                "intent": self.intent.identity(),
                "status": status,
                "number": number,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        if initial:
            # Crash/truncated file remains a blocking receipt, never a successful retry.
            with self.path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return
        fd, temporary = tempfile.mkstemp(prefix=".publication-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def verify_pr(api: GitHub, root: Path, intent: Intent, number: int) -> str:
    row = api.read(number)
    if not exact_match(row, intent) or row.get("number") != number:
        raise PublicationError("Created/existing PR metadata differs")
    expected_url = f"https://github.com/{REPO}/pull/{number}"
    if row.get("html_url") != expected_url or api.closing(number):
        raise PublicationError("PR URL or server closing references differ")
    local_checks(root, intent)
    remote_checks(root, intent)
    return expected_url


def publish(
    root: Path,
    intent: Intent,
    *,
    dry_run: bool,
    invoked: dict,
    runtime_files: list[Path],
    api: GitHub | None = None,
) -> dict:
    local_checks(root, intent)
    if dry_run:
        return {
            "status": "local_preview_only",
            "intent": intent.identity(),
            "unverified": ["account", "remote", "PR history", "PATH", "authority"],
        }
    # A matching explicitly invoked CLI is sufficient; stale PATH is a warning.
    current = freshness.check(root, invoked, runtime_files)
    if not current["invoked_matches_checkout"]:
        raise PublicationError("Invoked CLI does not match selected source")
    warning = (
        None
        if current["installed_matches_checkout"]
        else ("PATH CLI is stale or unavailable; use this explicitly verified CLI")
    )
    receipt = Receipt(root, intent)
    previous = receipt.load()
    api = api or GitHub(root)
    api.binding(intent)
    remote_checks(root, intent)
    existing = select_existing(api.history(), intent)
    if existing:
        number = existing["number"]
        try:
            url = verify_pr(api, root, intent, number)
            receipt.save("verified", number, initial=previous is None)
        except (ValueError, OSError, git_transport.GitTransportError):
            return {
                "status": "verification_failed_pr_exists",
                "number": number,
                "url": f"https://github.com/{REPO}/pull/{number}",
                "warning": warning,
            }
        return {"status": "verified_existing", "url": url, "warning": warning}
    if previous is not None:
        raise PublicationError(
            "Previous task attempt unresolved/absent; no automatic create retry"
        )
    local_checks(root, intent)
    remote_checks(root, intent)
    api.binding(intent)
    # Second complete read just before mutation catches slot/history changes.
    if select_existing(api.history(), intent) is not None:
        raise PublicationError(
            "PR appeared during preflight; inspect/retry read-only resolution"
        )
    receipt.save("attempted", initial=True)
    number = None
    try:
        result = api.create(intent)
        candidate = result.get("number") if isinstance(result, dict) else None
        if type(candidate) is int and candidate > 0:
            number = candidate
        if number is None:
            # A lost/malformed acknowledgement gets one read-only reconciliation.
            found = select_existing(api.history(), intent)
            if found:
                number = found["number"]
        if number is None:
            raise PublicationError("No unambiguous create acknowledgement")
        url = verify_pr(api, root, intent, number)
        receipt.save("verified", number)
        return {"status": "verified_created", "url": url, "warning": warning}
    except (ValueError, OSError, git_transport.GitTransportError):
        if number is None:
            try:
                found = select_existing(api.history(), intent)
                if found:
                    number = found["number"]
                    url = verify_pr(api, root, intent, number)
                    receipt.save("verified", number)
                    return {
                        "status": "verified_recovered",
                        "url": url,
                        "warning": warning,
                    }
            except (ValueError, OSError, git_transport.GitTransportError):
                pass
        status = (
            "outcome_unknown" if number is None else "verification_failed_pr_exists"
        )
        try:
            receipt.save(status, number)
        except OSError:
            pass  # The already durable attempted receipt still blocks another create.
        return {
            "status": status,
            "number": number,
            "url": None
            if number is None
            else f"https://github.com/{REPO}/pull/{number}",
            "warning": warning,
        }


def cmd_publish_pr(args: argparse.Namespace) -> int:
    from .cli import resolve_repo_root
    from .tide import runtime_contract_files

    try:
        root = resolve_repo_root(args.root)
        intent = load_intent(args, root)
        result = publish(
            root,
            intent,
            dry_run=args.dry_run,
            invoked=freshness.version_info(
                runtime_contract_files(Path(__file__).parent)
            ),
            runtime_files=runtime_contract_files(root / "src/wea_cli"),
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"].startswith("verified") or args.dry_run else 2
    except (ValueError, OSError, git_transport.GitTransportError):
        # Paths, transport stderr and assignment/body bytes may be private.
        print(
            "Publication blocked: check assignment, clean Git state, "
            "history and retained receipt."
        )
        return 2


def configure_parser(parser) -> None:
    for option in (
        "assignment",
        "assignment-sha256",
        "session",
        "expected-head",
        "task-url",
        "title",
        "body-file",
    ):
        parser.add_argument("--" + option, required=True)
    parser.add_argument(
        "--draft", action="store_true", help="Create a draft deliverable"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Local preview; no GitHub/PATH calls"
    )
    parser.set_defaults(_handler=cmd_publish_pr)
