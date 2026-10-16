import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import task_execution as execution
from scripts.task_execution import CoordinationError, Coordinator


def register(coordinator, root, task, **kwargs):
    tree = root / f"tree-{task}"
    tree.mkdir(exist_ok=True)
    (tree / "artifact.txt").write_text("keep")
    return coordinator.register(
        str(task), "agent@codex", tree, f"codex/task-{task}", repository="wea", **kwargs
    )


def worker(coordinator, task, *, crash=False):
    source = (
        "import os,sys; from scripts.task_execution import Coordinator; "
        "c=Coordinator(sys.argv[1]); "
        "ctx=c.lease(sys.argv[2]); lease=ctx.__enter__(); "
        "print('ready',flush=True); sys.stdin.readline(); "
        + ("os._exit(7)" if crash else "ctx.__exit__(None,None,None)")
    )
    env = dict(os.environ, PYTHONPATH=str(Path(execution.__file__).parent.parent))
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", source, str(coordinator.root), str(task)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdout.readline().strip() == "ready", process.stderr.read()
    return process


def stop(process):
    process.stdin.write("done\n")
    process.stdin.flush()
    output, errors = process.communicate(timeout=15)
    return process.returncode, output, errors


def test_twenty_retained_tasks_four_processes_restart_and_open_prs(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    for task in range(20):
        register(coordinator, tmp_path, task, pr=f"https://github.com/x/y/pull/{task}")
    processes = [worker(coordinator, task) for task in range(4)]
    try:
        with pytest.raises(CoordinationError, match="Capacity"):
            with coordinator.lease("4"):
                pytest.fail("Fifth execution admitted")
        assert stop(processes.pop(0))[0] == 0
        with coordinator.lease("4") as lease:
            assert lease.run([sys.executable, "-c", "print('lightweight')"]) == 0
    finally:
        for process in processes:
            assert stop(process)[0] == 0
    restarted = Coordinator(coordinator.root)
    for task in range(5, 20):
        with restarted.lease(str(task)) as lease:
            assert lease.run([sys.executable, "-c", "pass"]) == 0
    with restarted.lease("0"):
        pass
    data = restarted.reconcile()
    assert len(data["tasks"]) == 20
    assert len(data["tasks"]["0"]["attempts"]) == 2
    assert all(t["assignment"]["pr"] for t in data["tasks"].values())
    assert all(t["attempts"] for t in data["tasks"].values())
    assert all(
        (tmp_path / f"tree-{i}" / "artifact.txt").read_text() == "keep"
        for i in range(20)
    )


def test_crashed_process_releases_native_lock_and_capacity(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    process = worker(coordinator, 1, crash=True)
    assert stop(process)[0] == 7
    assert coordinator.reconcile()["tasks"]["1"]["attempts"][0]["state"] == "abandoned"
    with coordinator.lease("1"):
        pass
    assert len(coordinator.reconcile()["tasks"]["1"]["attempts"]) == 2


def test_collision_idempotence_domain_and_nested_worktree(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    first = register(coordinator, tmp_path, 1)
    assert register(coordinator, tmp_path, 1) == first
    with pytest.raises(CoordinationError, match="different assignment"):
        register(coordinator, tmp_path, 1, pr="new")
    with pytest.raises(CoordinationError, match="collision"):
        coordinator.register("other", "agent", tmp_path / "tree-1", "other")
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(CoordinationError, match="collision"):
        coordinator.register("other", "agent", other, "codex/task-1", repository="wea")
    nested = tmp_path / "tree-1" / "nested"
    nested.mkdir()
    with pytest.raises(CoordinationError, match="collision"):
        coordinator.register("other", "agent", nested, "other")
    domain = tmp_path / "domain"
    domain.mkdir()
    register(coordinator, tmp_path, 2, resources=(("weather", "task-2", domain),))
    with pytest.raises(CoordinationError, match="collision"):
        register(coordinator, tmp_path, 3, resources=(("weather", "task-3", domain),))
    assert "3" not in coordinator.reconcile()["tasks"]


def test_domain_native_lock_and_publication_contention(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    domain = tmp_path / "domain"
    domain.mkdir()
    register(coordinator, tmp_path, 1, resources=(("weather", "task-1", domain),))
    with coordinator.lease("1"):
        resources = coordinator.reconcile()["tasks"]["1"]["assignment"]["resources"]
        assert len(resources) == 2
        for resource in resources:
            digest = execution.hashlib.sha256(resource["path"].encode()).hexdigest()
            with pytest.raises(CoordinationError, match="Lock busy"):
                with execution.native_lock(coordinator.root / f"tree-{digest}.lock"):
                    pytest.fail("Concurrent writer admitted")
    with coordinator.lease("1") as lease:
        with coordinator.publication_lock(lease):
            with pytest.raises(CoordinationError, match="Lock busy"):
                with Coordinator(coordinator.root).publication_lock(lease):
                    pytest.fail("Concurrent publication admitted")
        with coordinator.publication_lock(lease):
            pass


@pytest.mark.parametrize(
    "state,owner,child,expected",
    [
        ("running", "dead", "dead", "abandoned"),
        ("running", "dead", "alive", "running"),
        ("running", "unknown", "dead", "running"),
        ("running", "dead", "unknown", "running"),
        ("launch_pending", "dead", "dead", "launch_pending"),
    ],
)
def test_recovery_fails_closed_for_orphan_unknown_and_launch_gap(
    tmp_path, monkeypatch, state, owner, child, expected
):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    with coordinator._transaction() as data:
        data["tasks"]["1"]["attempts"].append(
            {
                "token": "crash",
                "state": state,
                "owner": {"status": owner},
                "child": {"status": child},
            }
        )
    monkeypatch.setattr(execution, "liveness", lambda receipt: receipt["status"])
    assert coordinator.reconcile()["tasks"]["1"]["attempts"][0]["state"] == expected
    if expected != "abandoned":
        with pytest.raises(CoordinationError, match="active"):
            with coordinator.lease("1"):
                pytest.fail("Ambiguous attempt resumed")


def test_pid_reuse_and_unknown_probe(monkeypatch):
    assert execution.identity(os.getpid())["birth"]
    monkeypatch.setattr(execution, "process_birth", lambda pid: "new-birth")
    assert execution.liveness({"pid": 123, "birth": "old-birth"}) == "dead"

    def denied(pid):
        raise PermissionError("access denied")

    monkeypatch.setattr(execution, "process_birth", denied)
    assert execution.liveness({"pid": 123, "birth": "old-birth"}) == "unknown"


def test_terminated_process_with_retained_handle_and_exit_259():
    process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(259)"])
    process.wait(timeout=10)
    assert execution.process_birth(process.pid) is None


def test_cli_stdin_pr_metadata_and_publication_requires_task(tmp_path, capsys):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    coordinator.attach_pr("1", "https://github.com/x/y/pull/1")
    coordinator.attach_pr("1", "https://github.com/x/y/pull/1")
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("literal $(not-a-command)")
    command = [
        sys.executable,
        "-c",
        "import pathlib,sys; pathlib.Path('read.txt').write_text(sys.stdin.read())",
    ]
    args = [
        "--root",
        str(coordinator.root),
        "run",
        "--stdin-file",
        str(prompt),
        "1",
        "--",
        *command,
    ]
    assert execution.main(args) == 0
    assert (tmp_path / "tree-1" / "read.txt").read_text() == prompt.read_text()
    task = coordinator.reconcile()["tasks"]["1"]
    assert task["deliverables"] == ["https://github.com/x/y/pull/1"]
    assert task["attempts"][0]["started_at"] <= task["attempts"][0]["ended_at"]
    with coordinator.lease("1"):
        with pytest.raises(CoordinationError, match="active"):
            execution.main(
                [
                    "--root",
                    str(coordinator.root),
                    "publish",
                    "1",
                    "--",
                    sys.executable,
                    "-c",
                    "print('must not run')",
                ]
            )
    assert "must not run" not in capsys.readouterr().out


def test_missing_stdin_does_not_leave_launch_pending(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    with pytest.raises(FileNotFoundError):
        with coordinator.lease("1") as lease:
            lease.run([sys.executable, "-c", "pass"], stdin_path=tmp_path / "absent")
    assert coordinator.reconcile()["tasks"]["1"]["attempts"][0]["state"] == "finished"


def test_fast_child_receipt_fallback_cannot_run_second_child(tmp_path, monkeypatch):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    original = execution.identity

    def child_already_exited(pid):
        if pid != os.getpid():
            raise CoordinationError("Process exited before receipt")
        return original(pid)

    monkeypatch.setattr(execution, "identity", child_already_exited)
    with coordinator.lease("1") as lease:
        assert lease.run([sys.executable, "-c", "pass"]) == 0
        with pytest.raises(CoordinationError, match="already ran"):
            lease.run([sys.executable, "-c", "pass"])


def test_cli_resource_file_bom_spaced_paths_and_inline_resource(tmp_path, capsys):
    root = tmp_path / "registry"
    primary = tmp_path / "primary tree"
    domain = tmp_path / "domain tree"
    other = tmp_path / "other tree"
    for tree in (primary, domain, other):
        tree.mkdir()
    bindings = tmp_path / "bindings file.json"
    bindings.write_text(
        json.dumps([["weather", "codex/domain", str(domain)]]), encoding="utf-8-sig"
    )
    assert (
        execution.main(
            [
                "--root",
                str(root),
                "register",
                "task",
                "agent",
                str(primary),
                "codex/primary",
                "--resources-file",
                str(bindings),
                "--resource",
                json.dumps(["other", "codex/other", str(other)]),
            ]
        )
        == 0
    )
    printed = json.loads(capsys.readouterr().out)
    resources = printed["assignment"]["resources"]
    assert [resource["path"] for resource in resources] == [
        execution.normalized(tree) for tree in (primary, other, domain)
    ]


def test_orphan_publishing_child_blocks_other_task_until_exit(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    register(coordinator, tmp_path, 2)
    release = tmp_path / "release-child"
    child_source = (
        "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); "
        "exec('while not p.exists(): time.sleep(0.02)')"
    )
    owner_source = """
import os, sys, threading, time
from scripts.task_execution import Coordinator
c = Coordinator(sys.argv[1])
with c.lease('1') as lease, c.publication_lock(lease):
    thread = threading.Thread(target=lambda: lease.run(
        [sys.executable, '-c', sys.argv[3], sys.argv[2]]))
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        attempt = c.reconcile()['tasks']['1']['attempts'][-1]
        if attempt.get('child'):
            print('receipt-ready', flush=True)
            os._exit(7)
        time.sleep(0.02)
    os._exit(8)
"""
    env = dict(os.environ, PYTHONPATH=str(Path(execution.__file__).parent.parent))
    owner = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            owner_source,
            str(coordinator.root),
            str(release),
            child_source,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert owner.stdout.readline().strip() == "receipt-ready"
        assert owner.wait(timeout=15) == 7
        receipt = coordinator.reconcile()["tasks"]["1"]["attempts"][-1]["child"]
        assert execution.liveness(receipt) == "alive"
        with coordinator.lease("2") as lease:
            with pytest.raises(CoordinationError, match="Previous publication"):
                with coordinator.publication_lock(lease):
                    pytest.fail("Orphan publisher overlapped")
        release.write_text("release")
        deadline = time.monotonic() + 10
        while execution.liveness(receipt) != "dead" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert execution.liveness(receipt) == "dead"
        assert (
            coordinator.reconcile()["tasks"]["1"]["attempts"][-1]["state"]
            == "abandoned"
        )
        with coordinator.lease("2") as lease, coordinator.publication_lock(lease):
            assert lease.run([sys.executable, "-c", "pass"]) == 0
        assert "publication" not in coordinator.reconcile()
    finally:
        release.write_text("release")
        owner.wait(timeout=15)
        owner.stdout.close()
        owner.stderr.close()


def test_foreground_failure_retains_exit_and_capacity(tmp_path):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    with coordinator.lease("1") as lease:
        assert lease.run([sys.executable, "-c", "raise SystemExit(3)"]) == 3
    attempt = coordinator.reconcile()["tasks"]["1"]["attempts"][0]
    assert attempt["state"] == "finished"
    assert attempt["exit_code"] == 3
    with coordinator.lease("1"):
        pass


def test_atomic_registry_failure_preserves_previous_and_corrupt_fails_closed(
    tmp_path, monkeypatch
):
    coordinator = Coordinator(tmp_path / "registry")
    register(coordinator, tmp_path, 1)
    previous = coordinator.path.read_bytes()

    def fail_replace(source, target):
        raise OSError("simulated write interruption")

    monkeypatch.setattr(execution.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interruption"):
        register(coordinator, tmp_path, 2)
    assert coordinator.path.read_bytes() == previous
    assert not list(coordinator.root.glob("*.tmp"))
    coordinator.path.write_text("corrupt")
    with pytest.raises(json.JSONDecodeError):
        coordinator.reconcile()
    assert coordinator.path.read_text() == "corrupt"
