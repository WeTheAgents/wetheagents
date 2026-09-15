from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_cli import cli as git_transport
from wea_cli import freshness, report, tide


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
    local = tmp_path / "work"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "init", "-b", "feature", str(local)], check=True, capture_output=True
    )
    git(local, "config", "user.name", "Integration Author")
    git(local, "config", "user.email", "author@example.test")
    git(local, "config", "commit.gpgsign", "false")
    git(local, "remote", "add", "origin", str(remote))
    git(local, "remote", "add", "push-origin", str(remote))
    git(local, "commit", "--allow-empty", "-m", "base")
    return local, remote


def commit(root, message):
    git(root, "add", "-A")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def test_push_add_change_delete_exact_sha_and_identity(repository):
    root, remote = repository
    sample = root / "one file.txt"
    for content in ["initial\n", "changed\n", None]:
        if content is None:
            sample.unlink()
        else:
            sample.write_text(content)
        head = commit(root, "change")
        result = git_transport.push_branch(root)
        assert result["head"] == head == git(remote, "rev-parse", "refs/heads/feature")
        assert git(root, "cat-file", "commit", head) == git(
            remote, "cat-file", "commit", head
        )
        assert result["ref"] == "refs/heads/feature"
        assert git_transport.push_branch(root)["status"] == "unchanged"
    assert git(remote, "ls-tree", "--name-only", "feature") == ""


@pytest.mark.parametrize(
    "condition", ["dirty", "untracked", "detached", "main", "other", "nonff"]
)
def test_push_rejects_ambiguous_or_unsafe_state(repository, condition):
    root, remote = repository
    git_transport.push_branch(root)
    before = git(remote, "rev-parse", "feature")
    requested = None
    if condition in {"dirty", "untracked"}:
        (root / "pending").write_text("pending")
        if condition == "dirty":
            git(root, "add", "pending")
    elif condition == "detached":
        git(root, "checkout", "--detach")
        requested = "feature"
    elif condition == "main":
        git(root, "branch", "-m", "main")
    elif condition == "other":
        requested = "other"
    elif condition == "nonff":
        git(root, "commit", "--allow-empty", "-m", "remote advance")
        git_transport.push_branch(root)
        before = git(remote, "rev-parse", "feature")
        git(root, "reset", "--hard", "HEAD~1")
        git(root, "commit", "--allow-empty", "-m", "divergent")
    with pytest.raises(git_transport.TransportError):
        git_transport.push_branch(root, requested)
    assert git(remote, "rev-parse", "feature") == before


def test_push_uses_effective_push_url_and_does_not_publish_other_refs(
    repository, tmp_path
):
    root, remote = repository
    other = tmp_path / "other.git"
    subprocess.run(
        ["git", "init", "--bare", str(other)], check=True, capture_output=True
    )
    git(root, "remote", "set-url", "push-origin", str(other))
    git(root, "remote", "set-url", "--push", "push-origin", str(remote))
    git(root, "config", "push.followTags", "true")
    git(root, "tag", "-a", "private-tag", "-m", "private")
    git(root, "branch", "private-branch")
    git_transport.push_branch(root)
    assert git(remote, "for-each-ref", "--format=%(refname)") == "refs/heads/feature"
    assert git(other, "for-each-ref", "--format=%(refname)") == ""


def test_canonical_ref_fetches_exact_remote_branch(repository):
    root, _ = repository
    head = git(root, "rev-parse", "HEAD")
    git(root, "push", "origin", "HEAD:refs/heads/canonical", "HEAD:refs/heads/main")
    git(root, "commit", "--allow-empty", "-m", "local stale state must not be read")
    assert git_transport.canonical_commit(root, "origin/canonical") == head
    git(root, "push", "origin", "HEAD:refs/heads/tide/pending")
    with pytest.raises(git_transport.TransportError, match="not current canonical"):
        git_transport.canonical_commit(root, "origin/tide/pending")
    with pytest.raises(git_transport.TransportError, match="origin/<branch>"):
        git_transport.canonical_commit(root, "HEAD")
    with pytest.raises(git_transport.TransportError, match="Canonical fetch"):
        git_transport.canonical_commit(root, "origin/missing")


def test_fetch_failure_never_falls_back(repository):
    root, remote = repository
    git(root, "push", "origin", "HEAD:main")
    git_transport.canonical_commit(root, "origin/main")
    git(root, "remote", "set-url", "origin", str(remote / "missing"))
    with pytest.raises(git_transport.TransportError, match="Canonical fetch"):
        git_transport.canonical_commit(root, "origin/main")


def test_ref_verification_failure(monkeypatch, tmp_path):
    def fake_git(root, *args, **kwargs):
        return "wrong" if "FETCH_HEAD^{commit}" in args else "head"

    monkeypatch.setattr(git_transport, "git", fake_git)
    with pytest.raises(git_transport.TransportError, match="changed during fetch"):
        git_transport.canonical_commit(tmp_path, "origin/main")


def test_transport_failure_redacts_credentials(monkeypatch, tmp_path):
    secret = "https://user:SUPER_SECRET@example.test/repo"

    def fail(command, **kwargs):
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        assert "GIT_TRACE" not in kwargs["env"]
        raise subprocess.CalledProcessError(128, command, stderr=secret)

    monkeypatch.setenv("GIT_TRACE", "1")
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(git_transport.TransportError) as error:
        git_transport.git(tmp_path, "push", secret)
    assert "SUPER_SECRET" not in str(error.value)
    assert "authentication" in str(error.value)


def test_report_rendering_separates_legacy_and_delegates_actions(monkeypatch, tmp_path):
    seen = []
    state = {
        "sequence": 11,
        "cutoff": "2026-09-15T06:00:00Z",
        "balances": {"worker": 80},
        "escrow_wea": 20,
        "opening_supply": 100,
        "tasks": {
            "42": {
                "plan_id": "plan",
                "plan_status": "active",
                "current_stage_index": 0,
                "escrow": {"status": "active"},
                "roles": [],
                "settlements": [{"settlement_id": "paid"}],
                "stages": [
                    {
                        "stage_key": phase,
                        "status": "active",
                        "phase": phase,
                        "paid_wea": 0,
                        "refunded_wea": 0,
                        "contract": {},
                    }
                    for phase in ["intake", "author_decision", "settlement"]
                ],
            }
        },
    }

    def action(runtime, agent):
        seen.append((runtime, agent))
        return {"action": "submit", "reason": "runtime-owned"}

    engine = SimpleNamespace(
        state=lambda: state,
        sources={"s": {"issue_id": "42", "issue_number": 980}},
        runtimes={"42": "runtime"},
        modules={"lifecycle": SimpleNamespace(next_action=action)},
    )
    monkeypatch.setattr(git_transport, "canonical_commit", lambda root, ref: "a" * 40)
    monkeypatch.setattr(tide, "load", lambda root, sha: (engine, []))
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger/balances.json").write_text('{"fake_legacy_balance":99999}')
    result = report.build_report(
        "origin/approved",
        "a" * 40,
        "worker",
        *tide.report_state(tmp_path, "a" * 40, "worker"),
    )
    assert result["schema"] == report.SCHEMA
    assert result["ref"] == "origin/approved"
    assert result["total_balances_wea"] == 80
    assert result["active_escrow_wea"] == 20
    assert seen == [("runtime", "worker")]
    text = report.render_report(result)
    assert all(
        word in text
        for word in ["intake", "author_decision", "settlement", "Next: submit"]
    )
    assert "99999" not in text
    assert result["legacy"]["included_in_live_report"] is False


def test_replay_failure_does_not_emit_partial_report(monkeypatch, tmp_path):
    monkeypatch.setattr(git_transport, "canonical_commit", lambda root, ref: "a" * 40)

    def fail(*args):
        raise RuntimeError("private underlying diagnostic")

    monkeypatch.setattr(tide, "report_state", fail)
    monkeypatch.setattr(git_transport, "resolve_repo_root", lambda root: tmp_path)
    with pytest.raises(ValueError, match="No stale fallback") as error:
        git_transport.cmd_report(
            SimpleNamespace(root=str(tmp_path), ref="origin/main", agent="worker")
        )
    assert "private" not in str(error.value)


def test_source_freshness_and_subprocess_contract(tmp_path):
    checkout = Path(__file__).resolve().parents[1]
    source = checkout / "src/wea_cli"
    result = subprocess.run(
        [sys.executable, str(source / "cli.py"), "--cli-contract"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == freshness.contract(source)
    target = tmp_path / "src/wea_cli"
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        source.parent / "wea_vnext",
        target.parent / "wea_vnext",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    freshness.check_checkout(tmp_path, freshness.contract(source))
    (target / "cli.py").write_text("# older CLI\n")
    with pytest.raises(ValueError, match="differs from checkout"):
        freshness.check_checkout(tmp_path, freshness.contract(source))


@pytest.mark.parametrize("outcome", ["missing", "old", "different", "current"])
def test_installed_preflight(monkeypatch, outcome):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("PYTHONPATH", "source-path-must-not-mask-install")
    monkeypatch.setattr(
        shutil,
        "which",
        lambda executable: None if outcome == "missing" else sys.executable,
    )

    def probe(*args, **kwargs):
        assert "PYTHONPATH" not in kwargs["env"]
        if outcome == "old":
            raise subprocess.CalledProcessError(2, args)
        payload = (
            freshness.contract(root / "src/wea_cli") if outcome == "current" else {}
        )
        return SimpleNamespace(stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", probe)
    if outcome == "current":
        assert freshness.preflight(root, "wea")["status"] == "current"
    else:
        with pytest.raises(ValueError, match="pip install --editable"):
            freshness.preflight(root, "wea")


def test_cli_push_subprocess_preserves_sha(repository):
    root, remote = repository
    source = Path(__file__).resolve().parents[1] / "src/wea_cli/cli.py"
    # CLI root recognition requires the repository's ledger directory.
    (root / "ledger").mkdir()
    (root / "ledger/balances.json").write_text("{}")
    commit(root, "synthetic CLI root marker")
    result = subprocess.run(
        [sys.executable, str(source), "--root", str(root), "push"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["head"] == git(remote, "rev-parse", "feature")


def test_legacy_digest_rejects_new_report(tmp_path):
    from scripts.post_ecosystem_digest import DigestError, _render_report_text

    with pytest.raises(DigestError, match="unsupported"):
        _render_report_text({"schema": report.SCHEMA}, root=tmp_path)


@pytest.mark.parametrize(
    "relative", ["executors/nested/model.py", "rulesets/contract.json"]
)
def test_freshness_includes_runtime_python_and_json(tmp_path, relative):
    package = tmp_path / "wea_cli"
    runtime = tmp_path / "wea_vnext"
    for directory in (package, runtime):
        directory.mkdir()
        (directory / "__init__.py").write_text("")
    target = runtime / relative
    target.parent.mkdir(parents=True)
    target.write_text("before")
    before = freshness.contract(package)
    target.write_text("after")
    assert freshness.contract(package) != before
    target.unlink()
    assert freshness.contract(package) != before


def test_push_does_not_recurse_into_submodules(repository, tmp_path):
    root, _ = repository
    subremote = tmp_path / "subremote.git"
    subprocess.run(
        ["git", "init", "--bare", str(subremote)], check=True, capture_output=True
    )
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "clone", str(subremote), str(seed)], check=True, capture_output=True
    )
    git(seed, "config", "user.name", "Test Author")
    git(seed, "config", "user.email", "test@example.test")
    git(seed, "config", "commit.gpgsign", "false")
    git(seed, "commit", "--allow-empty", "-m", "submodule base")
    git(seed, "push", "origin", "HEAD")
    previous = git(subremote, "rev-parse", "HEAD")
    git(
        root,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        str(subremote),
        "sub",
    )
    git(root / "sub", "config", "user.name", "Test Author")
    git(root / "sub", "config", "user.email", "test@example.test")
    git(
        root / "sub",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--allow-empty",
        "-m",
        "private commit",
    )
    commit(root, "reference unpublished submodule commit")
    git(root, "config", "push.recurseSubmodules", "on-demand")
    git_transport.push_branch(root)
    assert git(subremote, "rev-parse", "HEAD") == previous


def test_token_auth_is_process_only_and_scoped(monkeypatch, tmp_path):
    import base64

    monkeypatch.setenv("GH_TOKEN", "private-test-token")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "existing")
    encoded = base64.b64encode(b"x-access-token:private-test-token").decode()

    def run(command, **kwargs):
        assert all(
            "private-test-token" not in arg and encoded not in arg for arg in command
        )
        env = kwargs["env"]
        assert env["GIT_CONFIG_COUNT"] == "3"
        assert env["GIT_CONFIG_VALUE_0"] == "existing"
        assert env["GIT_CONFIG_KEY_1"] == "http.https://github.com/.extraheader"
        assert env["GIT_CONFIG_VALUE_1"] == ""
        assert env["GIT_CONFIG_VALUE_2"] == f"AUTHORIZATION: basic {encoded}"
        return SimpleNamespace(stdout="success")

    monkeypatch.setattr(subprocess, "run", run)
    assert git_transport.git(tmp_path, "push", "push-origin") == "success"
    assert os.environ["GIT_CONFIG_COUNT"] == "1"


@pytest.mark.parametrize("branch", ["feature", "heads/feature"])
@pytest.mark.parametrize("explicit", [False, True])
def test_branch_tag_collision_keeps_exact_destination(repository, branch, explicit):
    root, remote = repository
    if branch != "feature":
        git(root, "branch", "-m", branch)
    git(root, "tag", branch)
    result = git_transport.push_branch(root, branch if explicit else None)
    ref = f"refs/heads/{branch}"
    assert result["branch"] == branch
    assert result["ref"] == ref
    assert result["head"] == git(remote, "rev-parse", ref)
    assert git(remote, "for-each-ref", "--format=%(refname)") == ref


@pytest.mark.parametrize("branch", ["main", "master"])
@pytest.mark.parametrize("explicit", [False, True])
def test_protected_branch_collision_cannot_bypass_guard(repository, branch, explicit):
    root, remote = repository
    git(root, "branch", "-m", branch)
    git(root, "tag", branch)
    with pytest.raises(git_transport.TransportError, match="Main publication"):
        git_transport.push_branch(root, branch if explicit else None)
    assert git(remote, "for-each-ref", "--format=%(refname)") == ""
