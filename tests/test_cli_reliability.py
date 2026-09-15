from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_cli import freshness, git_transport
from wea_cli import tide as canonical_report


def git(root, *args):
    return subprocess.check_output(
        ["git", "-C", str(root), *args],
        text=True,
        encoding="utf-8",
        stderr=subprocess.PIPE,
    ).strip()


@pytest.fixture
def repository(tmp_path):
    remote = tmp_path / "remote.git"
    root = tmp_path / "work"
    git(tmp_path, "init", "--bare", str(remote))
    git(tmp_path, "init", "-b", "agent/test/980-repair", str(root))
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (root / "ledger").mkdir()
    (root / "ledger/balances.json").write_text("{}")
    git(root, "add", ".")
    git(root, "commit", "-m", "initial")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "remote", "add", "push-origin", str(remote))
    return root, remote


def commit(root, text):
    path = root / "delta.txt"
    if text is None:
        path.unlink()
    else:
        path.write_text(text)
    git(root, "add", "-A")
    git(root, "commit", "-m", "delta")
    return git(root, "rev-parse", "HEAD")


def test_push_add_change_delete_exact_sha_and_idempotence(repository):
    root, remote = repository
    for value in ("add", "change", None):
        head = commit(root, value)
        result = git_transport.push_branch(root)
        assert result == {
            "remote": "push-origin",
            "branch": "agent/test/980-repair",
            "head": head,
        }
        assert git(remote, "rev-parse", "refs/heads/agent/test/980-repair") == head
        assert git_transport.push_branch(root) == result
    assert "delta.txt" not in git(remote, "ls-tree", "-r", "--name-only", head)


@pytest.mark.parametrize("branch_name", ["feature", "heads/feature"])
@pytest.mark.parametrize("explicit", [False, True])
def test_push_branch_tag_collision_preserves_exact_target(
    repository, branch_name, explicit
):
    root, remote = repository
    git(root, "branch", "-m", branch_name)
    git(root, "tag", branch_name)
    head = commit(root, "branch advances past colliding tag")
    result = git_transport.push_branch(root, branch_name if explicit else None)
    assert result == {"remote": "push-origin", "branch": branch_name, "head": head}
    assert git(remote, "show-ref") == f"{head} refs/heads/{branch_name}"


@pytest.mark.parametrize("explicit", [False, True])
def test_push_protected_branch_tag_collision_is_rejected(repository, explicit):
    root, remote = repository
    git(root, "branch", "-m", "main")
    git(root, "tag", "main")
    with pytest.raises(git_transport.GitTransportError, match="Protected branch"):
        git_transport.push_branch(root, "main" if explicit else None)
    assert git(remote, "for-each-ref") == ""


@pytest.mark.parametrize(
    "case",
    ["main", "detached", "dirty", "mismatch", "divergent", "mirror", "multi-url"],
)
def test_push_rejects_ambiguity_and_unsafe_updates(repository, case):
    root, remote = repository
    original = git_transport.push_branch(root)["head"]
    branch = None
    if case == "main":
        git(root, "branch", "-m", "main")
    elif case == "detached":
        git(root, "checkout", "--detach")
    elif case == "dirty":
        (root / "unknown").write_text("uncommitted")
    elif case == "mismatch":
        branch = "another-branch"
    elif case == "divergent":
        commit(root, "published")
        git_transport.push_branch(root)
        git(root, "reset", "--hard", original)
        commit(root, "different")
    elif case == "mirror":
        git(root, "config", "remote.push-origin.mirror", "true")
    elif case == "multi-url":
        git(root, "config", "--add", "remote.push-origin.pushurl", str(remote))
        git(root, "config", "--add", "remote.push-origin.pushurl", str(remote) + "2")
    before = git(remote, "show-ref")
    with pytest.raises(git_transport.GitTransportError):
        git_transport.push_branch(root, branch)
    assert git(remote, "show-ref") == before


def test_transport_diagnostics_do_not_expose_credentials(tmp_path, monkeypatch):
    def failed(*args, **kwargs):
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        return subprocess.CompletedProcess(
            args, 1, "", "https://user:secret@host/?token=secret"
        )

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(git_transport.GitTransportError) as exc:
        git_transport.run(tmp_path, "fetch", "origin", operation="Canonical fetch")
    assert "secret" not in str(exc.value)
    assert "authentication" in str(exc.value)


@pytest.mark.parametrize(
    "ref",
    [
        "main",
        "HEAD",
        "origin/HEAD",
        "origin/../evil",
        "origin/missing",
        "origin/tide/pending",
    ],
)
def test_report_rejects_unverified_or_unfetchable_ref(repository, ref):
    with pytest.raises(git_transport.GitTransportError):
        git_transport.fetch_canonical(repository[0], ref)


def test_fetch_resolves_requested_branch_and_updates_stale_ref(repository):
    root, _ = repository
    old = git(root, "rev-parse", "HEAD")
    git(root, "push", "origin", "HEAD:refs/heads/main", "HEAD:refs/heads/canonical")
    assert git_transport.fetch_canonical(root, "origin/main") == old
    head = commit(root, "new canonical")
    git(root, "push", "origin", "HEAD:refs/heads/canonical")
    with pytest.raises(git_transport.GitTransportError):
        git_transport.fetch_canonical(root, "origin/canonical")
    git(root, "push", "origin", "HEAD:refs/heads/main")
    assert git_transport.fetch_canonical(root, "origin/main") == head


@pytest.mark.parametrize("phase", ["intake", "author_decision", "settled"])
def test_report_renders_verified_state_and_runtime_action(
    repository, monkeypatch, phase
):
    root, _ = repository
    git(root, "push", "origin", "HEAD:refs/heads/main")
    calls = []
    stage = {
        "contract": {"expected_output": "large original Plan"},
        "stage_key": "implement",
        "status": "active",
        "phase": phase,
        "paid_wea": 0,
        "refunded_wea": 0,
    }
    task = {
        "plan_id": "plan",
        "plan_status": "active",
        "current_stage_index": 0,
        "escrow": {"status": "active"},
        "stages": [stage],
        "settlements": [],
    }
    state = {
        "sequence": 11,
        "cutoff": "2026-09-15T06:11:03Z",
        "balances": {"worker": 30},
        "escrow_wea": 20,
        "opening_supply": 50,
        "tasks": {"980": task},
    }

    def next_action(runtime, agent):
        calls.append((runtime, agent))
        return {"action": "runtime-owned-action", "boundary_at": "tomorrow"}

    engine = SimpleNamespace(
        state=lambda: state,
        runtimes={"980": "runtime"},
        sources={"source": {"issue_id": "980", "issue_number": 980}},
        modules={"lifecycle": SimpleNamespace(next_action=next_action)},
    )
    monkeypatch.setattr(canonical_report, "load", lambda root, sha: (engine, []))
    report = canonical_report.build_report(root, "origin/main", "worker")
    assert report["commit"] == git(root, "rev-parse", "HEAD")
    assert report["available_wea"] == 30
    assert report["total_balances_wea"] == 30
    assert report["active_escrow_wea"] == 20
    assert not report["legacy"]["included_in_current_totals"]
    assert calls == [("runtime", "worker")]
    rendered = canonical_report.render_report(report)
    assert phase in rendered and "runtime-owned-action" in rendered
    assert "retained history" in rendered and "Tide 11" in rendered
    assert "large original Plan" not in json.dumps(report)
    assert "boundary tomorrow" in rendered
    assert '"action"' not in rendered


def test_report_replay_failure_never_returns_cached_state(repository, monkeypatch):
    root, _ = repository
    git(root, "push", "origin", "HEAD:refs/heads/main")

    def fail(*args):
        raise ValueError("broken replay with secret data")

    monkeypatch.setattr(canonical_report, "load", fail)
    with pytest.raises(git_transport.GitTransportError, match="replay failed") as exc:
        canonical_report.build_report(root, "origin/main", "worker")
    assert "secret" not in str(exc.value)


def test_subprocess_cli_push_and_version(repository):
    root, remote = repository
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    command = [sys.executable, "-m", "wea_cli.cli"]
    result = subprocess.run(
        [*command, "--root", str(root), "push"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["head"] == git(
        remote, "rev-parse", "refs/heads/agent/test/980-repair"
    )
    version = subprocess.run(
        [*command, "--version"], env=env, capture_output=True, text=True, check=True
    )
    assert json.loads(version.stdout)["schema"] == "wea-cli-version-1"


def test_report_fetch_failure_has_no_stdout_fallback(repository):
    root, _ = repository
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "wea_cli.cli",
            "--root",
            str(root),
            "report",
            "--agent",
            "worker",
            "--json",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Canonical fetch" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("installed", [None, "old", "current"])
def test_freshness_detects_old_missing_and_current_install(
    tmp_path, monkeypatch, installed
):
    package = tmp_path / "src/wea_cli"
    package.mkdir(parents=True)
    (package / "cli.py").write_text("contract")
    contract = freshness.fingerprint(
        package, canonical_report.runtime_contract_files(package)
    )
    monkeypatch.setattr(
        freshness.shutil, "which", lambda name: "wea" if installed else None
    )

    def probe(*args, **kwargs):
        assert "PYTHONPATH" not in kwargs["env"]
        assert Path(kwargs["cwd"]) != tmp_path
        return subprocess.CompletedProcess(
            args,
            0 if installed == "current" else 2,
            json.dumps({"schema": "wea-cli-version-1", "fingerprint": contract}),
            "",
        )

    monkeypatch.setattr(subprocess, "run", probe)
    report = freshness.check(
        tmp_path,
        {"fingerprint": contract},
        canonical_report.runtime_contract_files(package),
    )
    assert report["invoked_matches_checkout"]
    assert report["installed_matches_checkout"] == (installed == "current")
    assert "pip install --editable" in report["refresh"]
    (package / "cli.py").write_text("changed contract")
    assert not freshness.check(
        tmp_path,
        {"fingerprint": contract},
        canonical_report.runtime_contract_files(package),
    )["invoked_matches_checkout"]


def test_freshness_includes_shipped_runtime_and_manifest(tmp_path):
    package = tmp_path / "wea_cli"
    package.mkdir()
    (package / "cli.py").write_text("same CLI")
    runtime = tmp_path / "wea_vnext"
    runtime.mkdir()
    source = runtime / "engine.py"
    source.write_text("old runtime")
    initial = freshness.fingerprint(
        package, canonical_report.runtime_contract_files(package)
    )
    source.write_text("new runtime")
    changed = freshness.fingerprint(
        package, canonical_report.runtime_contract_files(package)
    )
    assert changed != initial
    (runtime / "manifest.json").write_text('{"version": "new"}')
    assert (
        freshness.fingerprint(package, canonical_report.runtime_contract_files(package))
        != changed
    )
