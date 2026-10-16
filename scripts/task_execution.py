"""Private task coordination, independent of WEA admission and financial authority.

Use one shared registry per coordinator host. Foreground commands must not detach
descendants. Locks are cooperative; they do not prevent unrelated manual edits.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import tempfile
import time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path


class CoordinationError(RuntimeError):
    """Unsafe allocation or execution; inspect rather than overwrite."""


def process_birth(pid: int) -> str | None:
    """Creation identity, None if dead; inaccessible/unsupported raises OSError."""
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: PID does not exist.
                return None
            raise OSError(error, "Cannot inspect process")
        try:
            wait = kernel.WaitForSingleObject(handle, 0)
            if wait == 0:  # WAIT_OBJECT_0, including an actual exit code of 259.
                return None
            if wait != 258:  # WAIT_TIMEOUT
                raise ctypes.WinError(ctypes.get_last_error())
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    if os.name == "posix" and Path("/proc").is_dir():
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            return None
        if fields[0] == "Z":
            return None
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        return f"{boot}:{fields[19]}"
    raise OSError("Process creation identity unavailable on this platform")


def identity(pid: int) -> dict:
    birth = process_birth(pid)
    if birth is None:
        raise CoordinationError("Process exited before its identity was recorded")
    return {"pid": pid, "birth": birth}


def liveness(receipt: dict) -> str:
    try:
        if (
            type(receipt["pid"]) is not int
            or receipt["pid"] <= 0
            or not isinstance(receipt["birth"], str)
            or not receipt["birth"]
        ):
            return "unknown"
        birth = process_birth(receipt["pid"])
        return "alive" if birth == receipt["birth"] else "dead"
    except (OSError, KeyError, TypeError, ValueError):
        return "unknown"


@contextmanager
def native_lock(path: Path, timeout: float = 0):
    """Nonblocking advisory lock; OS releases it even after abrupt exit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise CoordinationError(
                        f"Lock busy or unavailable: {path}"
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def normalized(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=True)))


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Coordinator:
    def __init__(self, root: str | Path, limit: int = 4):
        if limit < 1:
            raise ValueError("Execution limit must be positive")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "tasks.json"
        self.limit = limit

    @contextmanager
    def _transaction(self):
        with native_lock(self.root / "registry.lock", timeout=10):
            data = (
                json.loads(self.path.read_text())
                if self.path.exists()
                else {"version": 1, "limit": self.limit, "tasks": {}}
            )
            if data["version"] != 1 or data["limit"] != self.limit:
                raise CoordinationError("Registry version or limit disagrees")
            yield data
            fd, name = tempfile.mkstemp(dir=self.root, prefix="tasks-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def register(
        self,
        task_id: str,
        agent_id: str,
        worktree: str | Path,
        branch: str,
        *,
        repository: str = "",
        evidence: str = "",
        pr: str | None = None,
        resources: tuple = (),
    ) -> dict:
        """Register immutable bindings; resources are (repository, branch, path)."""
        bindings = [
            {"repository": repository, "branch": branch, "path": normalized(worktree)}
        ]
        bindings.extend(
            {"repository": repo, "branch": ref, "path": normalized(path)}
            for repo, ref, path in resources
        )
        if (
            not task_id
            or not agent_id
            or any(
                not b["branch"] or b["branch"] == "main" or not Path(b["path"]).is_dir()
                for b in bindings
            )
        ):
            raise CoordinationError(
                "Task, agent, isolated directory and branch required"
            )
        assignment = {
            "agent": agent_id,
            "resources": bindings,
            "evidence": evidence,
            "pr": pr,
        }
        with self._transaction() as data:
            existing = data["tasks"].get(task_id)
            if existing:
                if existing["assignment"] != assignment:
                    raise CoordinationError(
                        "Task ID already has a different assignment"
                    )
                return existing
            allocated = [
                b for t in data["tasks"].values() for b in t["assignment"]["resources"]
            ]
            for binding in bindings:
                for other in allocated:
                    paths = [binding["path"], other["path"]]
                    common = (
                        os.path.commonpath(paths)
                        if (Path(paths[0]).drive == Path(paths[1]).drive)
                        else ""
                    )
                    if common in paths or (
                        binding["repository"] == other["repository"]
                        and binding["branch"] == other["branch"]
                    ):
                        raise CoordinationError(
                            "Worktree or repository/branch collision"
                        )
                allocated.append(binding)
            task = {"assignment": assignment, "attempts": []}
            data["tasks"][task_id] = task
            return task

    @staticmethod
    def _reconcile(data: dict):
        for task in data["tasks"].values():
            for attempt in task["attempts"]:
                if attempt["state"] not in ("running", "launch_pending"):
                    continue
                owner = liveness(attempt["owner"])
                child = liveness(attempt["child"]) if attempt.get("child") else "dead"
                if owner == child == "dead" and attempt["state"] == "running":
                    attempt["state"] = "abandoned"
                    attempt["ended_at"] = timestamp()

    def reconcile(self) -> dict:
        with self._transaction() as data:
            self._reconcile(data)
            return data

    @contextmanager
    def lease(self, task_id: str):
        owner = identity(os.getpid())
        token = uuid.uuid4().hex
        with ExitStack() as stack:
            with self._transaction() as data:
                self._reconcile(data)
                task = data["tasks"][task_id]
                active = [
                    a
                    for t in data["tasks"].values()
                    for a in t["attempts"]
                    if a["state"] in ("running", "launch_pending")
                ]
                if len(active) >= self.limit or any(
                    a in active for a in task["attempts"]
                ):
                    raise CoordinationError("Capacity exhausted or task still active")
                for resource in sorted(
                    task["assignment"]["resources"], key=lambda r: r["path"]
                ):
                    if normalized(resource["path"]) != resource["path"]:
                        raise CoordinationError("Registered worktree path changed")
                    digest = hashlib.sha256(resource["path"].encode()).hexdigest()
                    stack.enter_context(native_lock(self.root / f"tree-{digest}.lock"))
                task["attempts"].append(
                    {
                        "token": token,
                        "owner": owner,
                        "state": "running",
                        "child": None,
                        "started_at": timestamp(),
                    }
                )
            lease = Lease(self, task_id, token, owner)
            try:
                yield lease
            finally:
                lease._finish()

    @contextmanager
    def publication_lock(self, lease: Lease):
        """Serialize publication and retain ownership if its child outlives owner."""
        if lease.coordinator.root != self.root:
            raise CoordinationError("Publication lease uses another registry")
        with native_lock(self.root / "publication.lock"):
            with self._transaction() as data:
                self._reconcile(data)
                previous = data.get("publication")
                if previous:
                    attempts = data["tasks"][previous["task"]]["attempts"]
                    held = next(a for a in attempts if a["token"] == previous["token"])
                    if held["state"] not in ("finished", "abandoned"):
                        raise CoordinationError(
                            "Previous publication still active or unknown"
                        )
                attempt = lease._attempt(data)
                if attempt["state"] != "running":
                    raise CoordinationError(
                        "Publication requires an active execution lease"
                    )
                data["publication"] = {"task": lease.task, "token": lease.token}
            try:
                yield
            finally:
                with self._transaction() as data:
                    attempt = lease._attempt(data)
                    if attempt["state"] != "launch_pending" and (
                        not attempt.get("child")
                        or "exit_code" in attempt
                        or liveness(attempt["child"]) == "dead"
                    ):
                        data.pop("publication", None)

    def attach_pr(self, task_id: str, url: str):
        """Retain a deliverable reference without changing resource assignment."""
        with self._transaction() as data:
            refs = data["tasks"][task_id].setdefault("deliverables", [])
            if url not in refs:
                refs.append(url)


class Lease:
    def __init__(self, coordinator: Coordinator, task: str, token: str, owner: dict):
        self.coordinator, self.task, self.token, self.owner = (
            coordinator,
            task,
            token,
            owner,
        )

    def _attempt(self, data):
        attempt = next(
            a for a in data["tasks"][self.task]["attempts"] if a["token"] == self.token
        )
        if identity(os.getpid()) != self.owner or attempt["owner"] != self.owner:
            raise CoordinationError("Lease belongs to another process")
        return attempt

    def run(self, command: list[str], *, stdin_path: str | Path | None = None) -> int:
        """Run one foreground child. Never kill a worker or detach descendants."""
        with self.coordinator._transaction() as data:
            attempt = self._attempt(data)
            if (
                attempt["state"] != "running"
                or attempt.get("child")
                or "exit_code" in attempt
            ):
                raise CoordinationError("Lease already ran a command")
            attempt["state"] = "launch_pending"
            cwd = data["tasks"][self.task]["assignment"]["resources"][0]["path"]
        with ExitStack() as streams:
            try:
                stdin = (
                    streams.enter_context(Path(stdin_path).open("rb"))
                    if (stdin_path is not None)
                    else None
                )
                child = subprocess.Popen(command, cwd=cwd, stdin=stdin)
            except OSError:
                with self.coordinator._transaction() as data:
                    self._attempt(data)["state"] = "running"
                raise
        try:
            receipt = identity(child.pid)
        except CoordinationError:
            code = child.wait()
            with self.coordinator._transaction() as data:
                attempt = self._attempt(data)
                attempt.update(state="running", exit_code=code)
            return code
        with self.coordinator._transaction() as data:
            self._attempt(data).update(state="running", child=receipt)
        code = child.wait()
        with self.coordinator._transaction() as data:
            self._attempt(data)["exit_code"] = code
        return code

    def _finish(self):
        with self.coordinator._transaction() as data:
            attempt = self._attempt(data)
            if attempt["state"] == "finished":
                return
            if attempt["state"] == "launch_pending" or (
                attempt.get("child")
                and "exit_code" not in attempt
                and liveness(attempt["child"]) != "dead"
            ):
                raise CoordinationError(
                    "Unresolved child: retain lease receipt for inspection"
                )
            attempt["state"] = "finished"
            attempt["ended_at"] = timestamp()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--limit", type=int, default=4)
    commands = parser.add_subparsers(dest="action", required=True)
    register = commands.add_parser("register")
    for name in ("task", "agent", "worktree", "branch"):
        register.add_argument(name)
    for name in ("repository", "evidence", "pr"):
        register.add_argument(f"--{name}")
    register.add_argument(
        "--resource",
        action="append",
        default=[],
        help="Additional JSON [repository, branch, worktree]",
    )
    register.add_argument(
        "--resources-file",
        type=Path,
        help="UTF-8 JSON list of [repository, branch, worktree] triples",
    )
    commands.add_parser("reconcile")
    run = commands.add_parser("run")
    run.add_argument("--stdin-file")
    run.add_argument("task")
    run.add_argument("command", nargs=argparse.REMAINDER)
    publish = commands.add_parser("publish")
    publish.add_argument("task")
    publish.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    coordinator = Coordinator(args.root, args.limit)
    if args.action == "register":
        resources = [json.loads(r) for r in args.resource]
        if args.resources_file:
            resources.extend(
                json.loads(args.resources_file.read_text(encoding="utf-8-sig"))
            )
        result = coordinator.register(
            args.task,
            args.agent,
            args.worktree,
            args.branch,
            repository=args.repository or "",
            evidence=args.evidence or "",
            pr=args.pr,
            resources=tuple(resources),
        )
        print(json.dumps(result, indent=2))
    elif args.action == "reconcile":
        print(json.dumps(coordinator.reconcile(), indent=2))
    else:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("Foreground command required")
        if args.action == "run":
            with coordinator.lease(args.task) as lease:
                return lease.run(command, stdin_path=args.stdin_file)
        with coordinator.lease(args.task) as lease, coordinator.publication_lock(lease):
            return lease.run(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
