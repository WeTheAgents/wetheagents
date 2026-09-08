from __future__ import annotations

import json
import subprocess
from datetime import timedelta

import pytest

from wea_vnext.tide import __main__ as cli
from wea_vnext.tide.ledger import BOOTSTRAP, STATE, candidate, git, validate
from wea_vnext.tide.replay import Replay, ReplayError, canonical

from .test_tide_replay import bootstrap, setup_sources


def put(root, values):
    for name, value in values.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical(value) + b"\n")


def commit(root):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Tide test",
        "-c",
        "user.email=tide@example.invalid",
        "commit",
        "-qm",
        "test",
    )
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "test", str(tmp_path)], check=True)
    initial = bootstrap()
    put(
        tmp_path,
        {
            BOOTSTRAP: initial,
            STATE: Replay(initial).state(),
            "ledger/balances.json": {
                "agents": {
                    key: {"balance": value}
                    for key, value in initial["balances"].items()
                }
            },
        },
    )
    base = commit(tmp_path)
    return tmp_path, base


def prepared(repo):
    root, base = repo
    sources, cutoff = setup_sources()
    values = candidate(
        root,
        base,
        {"cutoff": cutoff.isoformat(), "sources": sources, "tracked_issues": []},
        {},
        {"run_id": "1", "run_attempt": "1"},
    )
    put(root, values)
    return root, base, commit(root), cutoff


def test_git_candidate_is_checked_by_task_replay(repo):
    root, base, head, _ = prepared(repo)
    state = validate(root, base, head)
    assert state["escrow_wea"] == 100
    assert state["balances"]["agent-author"] == 100


def test_balanced_but_unearned_payment_fails_guard(repo):
    root, base, head, _ = prepared(repo)
    state = json.loads((root / STATE).read_text())
    state["balances"]["agent-author"] -= 20
    state["balances"]["agent-alpha"] = 20
    put(root, {STATE: state})
    git(root, "reset", "--soft", base)
    forged = commit(root)
    assert forged != head
    with pytest.raises(ReplayError, match="differs from executor replay"):
        validate(root, base, forged)


def test_code_cannot_be_bundled_with_a_ledger_candidate(repo):
    root, base, _, _ = prepared(repo)
    (root / "candidate.py").write_text("raise RuntimeError('must never execute')")
    git(root, "reset", "--soft", base)
    head = commit(root)
    with pytest.raises(ReplayError, match="exactly its batch"):
        validate(root, base, head)


@pytest.mark.parametrize("wrong", ["head_sha", "path", "head_branch", "event"])
def test_guard_rejects_untrusted_workflow_provenance(repo, wrong):
    root, base, head, _ = prepared(repo)

    class API:
        def get(self, path):
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            assert "/actions/runs/" in path
            run = {
                "head_sha": base,
                "path": ".github/workflows/tide.yml",
                "event": "schedule",
                "head_branch": "main",
            }
            run[wrong] = "untrusted"
            return run

    with pytest.raises(ReplayError, match="provenance"):
        validate(root, base, head, api=API())


def test_read_only_cli_reports_canonical_balance(repo, capsys):
    from types import SimpleNamespace

    from wea_cli.tide import show

    root, base = repo
    args = SimpleNamespace(root=str(root), ref=base, issue=None, agent="agent-author")
    assert show(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["commit"] == base
    assert result["result"]["available_wea"] == 200
    assert git(root, "status", "--porcelain") == ""


def test_unrelated_chat_is_a_noop(repo):
    root, base = repo
    sources, cutoff = setup_sources()
    source = sources[0]
    source["body"] = "Just a conversation, with no task declaration."
    import hashlib

    source["content_hash"] = hashlib.sha256(source["body"].encode()).hexdigest()
    assert (
        candidate(
            root, base, {"cutoff": cutoff.isoformat(), "sources": [source]}, {}, {}
        )
        is None
    )


def test_existing_canonical_tide_is_not_paid_again(repo):
    root, _, head, cutoff = prepared(repo)
    assert (
        candidate(
            root,
            head,
            {"cutoff": (cutoff + timedelta(minutes=2)).isoformat(), "sources": []},
            {},
            {},
        )
        is None
    )


def test_candidate_cannot_drop_previously_tracked_issues(repo):
    root, _, base, cutoff = prepared(repo)
    sources, _ = setup_sources()
    changed = dict(sources[-1])
    changed["revision_id"] = "new-invalid-command"
    changed["object_id"] = "new-comment"
    changed["effective_at"] = (cutoff + timedelta(minutes=1)).isoformat()
    values = candidate(
        root,
        base,
        {
            "cutoff": (cutoff + timedelta(minutes=2)).isoformat(),
            "sources": [changed],
            "tracked_issues": [],
        },
        {},
        {},
    )
    assert values is not None
    put(root, values)
    with pytest.raises(ReplayError, match="omits canonical tracked Issues"):
        validate(root, base, commit(root))


def workflow_env(monkeypatch):
    for key, value in {
        "GITHUB_REPOSITORY": "WeTheAgents/wetheagents",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_WORKFLOW_REF": (
            "WeTheAgents/wetheagents/.github/workflows/tide.yml@refs/heads/main"
        ),
        "GITHUB_RUN_ID": "2",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)


def test_main_advance_invalidates_old_green_status():
    writes = []

    class API:
        def get(self, path):
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": "new-main"}}
            if "/pulls?" in path:
                return [{"head": {"sha": "pending-head"}}]
            assert path.endswith("git/commits/pending-head")
            return {"parents": [{"sha": "old-main"}]}

        def request(self, method, path, data):
            writes.append((method, path, data))

    cli.invalidate_pending(API())
    assert len(writes) == 1
    assert writes[0][2]["state"] == "failure"
    assert writes[0][2]["context"] == "tide/replay"


def test_more_than_one_hundred_historical_prs_do_not_stop_the_next_tide(
    repo, monkeypatch
):
    root, base = repo
    workflow_env(monkeypatch)
    calls = []

    class API:
        def get(self, path):
            calls.append(path)
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            if "matching-refs" in path:
                return []
            if path.endswith("page=1"):
                return [
                    {"number": number, "state": "closed"} for number in range(1, 101)
                ]
            if path.endswith("page=2"):
                return []
            raise AssertionError(path)

        def graphql(self, *args):
            raise AssertionError("capture is injected")

    monkeypatch.setattr(
        cli,
        "collect_sources",
        lambda *args, **kwargs: {
            "cutoff": kwargs["cutoff"].isoformat(),
            "sources": [],
            "tracked_issues": [],
        },
    )
    cli.run(root, API(), False)
    assert any(path.endswith("page=2") for path in calls)
    assert git(root, "rev-parse", "HEAD") == base


def test_push_before_pr_crash_recovers_the_same_candidate(repo, monkeypatch):
    root, base, head, _ = prepared(repo)
    git(root, "checkout", "--detach", base)
    workflow_env(monkeypatch)
    created = []

    class API:
        def get(self, path):
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            if "matching-refs" in path:
                return [{"ref": "refs/heads/tide/pending", "object": {"sha": head}}]
            if "/pulls?" in path:
                return []
            raise AssertionError(path)

        def request(self, method, path, data):
            created.append((method, path, data))
            if path.endswith("/pulls"):
                return {
                    "number": 10,
                    "html_url": "https://github.com/WeTheAgents/wetheagents/pull/10",
                }

    cli.run(root, API(), False)
    assert len(created) == 2
    assert created[0][2]["head"] == "tide/pending"
    assert created[1][2]["inputs"] == {"pull_request": "10"}
