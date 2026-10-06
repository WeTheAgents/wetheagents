from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_cli import cli
from wea_cli import publication as p


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "work/slot-3")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    (root / "tracked").write_text("base")
    git(root, "add", "tracked")
    git(root, "commit", "-m", "Base")
    base = git(root, "rev-parse", "HEAD")
    (root / "tracked").write_text("delivery")
    git(root, "commit", "-am", "Fixed typo in help")
    head = git(root, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    git(root, "init", "--bare", str(remote))
    git(root, "remote", "add", "push-origin", str(remote))
    git(root, "push", "push-origin", "work/slot-3")
    monkeypatch.setattr(p, "DESTINATION", str(remote))
    intent = p.Intent(
        p.REPO,
        f"https://github.com/{p.REPO}/issues/42",
        "Codex-19@codex",
        "explicit-session",
        str(root),
        "work/slot-3",
        base,
        head,
        "peachgabba22",
        "129645949",
        "[Task #42] Publish safely",
        f"Task: https://github.com/{p.REPO}/issues/42\n"
        "Agent ID: Codex-19@codex\n\nFixed typo.\n",
        True,
        "a" * 64,
    )
    monkeypatch.setattr(
        p.freshness,
        "check",
        lambda *a: {
            "invoked_matches_checkout": True,
            "installed_matches_checkout": False,
        },
    )
    return root, intent, remote


def row(intent, number=7):
    return {
        "number": number,
        "state": "open",
        "merged_at": None,
        "title": intent.title,
        "body": intent.body,
        "draft": intent.draft,
        "html_url": f"https://github.com/{p.REPO}/pull/{number}",
        "user": {"login": intent.account, "id": int(intent.account_id)},
        "base": {"ref": "main", "repo": {"id": p.REPOSITORY_ID}},
        "head": {
            "ref": intent.branch,
            "sha": intent.head,
            "repo": {"id": p.REPOSITORY_ID},
        },
    }


class API:
    def __init__(self, intent):
        self.intent, self.rows, self.creates, self.reads = intent, [], 0, 0
        self.lost = False
        self.accept = True
        self.drift = False
        self.closings = []

    def binding(self, intent):
        assert intent == self.intent

    def history(self):
        return self.rows

    def create(self, intent):
        assert p.Receipt(Path(intent.workplace), intent).load()["status"] == "attempted"
        self.creates += 1
        if self.accept:
            self.rows = [row(intent)]
        if self.lost:
            raise p.PublicationError("Lost acknowledgement")
        return self.rows[0]

    def read(self, number):
        self.reads += 1
        result = dict(self.rows[0])
        if self.drift:
            result["title"] = "Drift"
        return result

    def closing(self, number):
        return self.closings


def publish(root, intent, api, dry=False):
    return p.publish(root, intent, dry_run=dry, invoked={}, runtime_files=[], api=api)


def test_create_and_exact_repeat_use_production_checks_and_receipt(delivery):
    root, intent, _ = delivery
    api = API(intent)
    result = publish(root, intent, api)
    assert result["status"] == "verified_created"
    assert "PATH" in result["warning"]
    assert p.Receipt(root, intent).load()["status"] == "verified"
    assert publish(root, intent, api)["status"] == "verified_existing"
    assert api.creates == 1


def test_lost_ack_reconciles_exact_existing_without_second_create(delivery):
    root, intent, _ = delivery
    api = API(intent)
    api.lost = True
    assert publish(root, intent, api)["status"] == "verified_recovered"
    assert api.creates == 1


def test_unknown_survives_next_invocation_with_empty_history(delivery):
    root, intent, _ = delivery
    api = API(intent)
    api.lost, api.accept = True, False
    assert publish(root, intent, api)["status"] == "outcome_unknown"
    assert p.Receipt(root, intent).load()["status"] == "outcome_unknown"
    with pytest.raises(p.PublicationError, match="no automatic"):
        publish(root, intent, api)
    assert api.creates == 1


def test_crashed_attempt_and_partial_receipt_block_create(delivery):
    root, intent, _ = delivery
    receipt = p.Receipt(root, intent)
    receipt.save("attempted", initial=True)
    api = API(intent)
    with pytest.raises(p.PublicationError):
        publish(root, intent, api)
    receipt.path.write_text('{"schema":')
    with pytest.raises(p.PublicationError):
        publish(root, intent, api)
    assert api.creates == 0


@pytest.mark.parametrize("attribute", ["drift", "closings"])
def test_known_partial_effect_returns_url_and_preserves_barrier(delivery, attribute):
    root, intent, _ = delivery
    api = API(intent)
    setattr(api, attribute, True if attribute == "drift" else [{"number": 42}])
    result = publish(root, intent, api)
    assert result["status"] == "verification_failed_pr_exists"
    assert result["url"].endswith("/pull/7")
    assert p.Receipt(root, intent).load()["number"] == 7
    assert api.creates == 1


@pytest.mark.parametrize(
    "change", ["title", "author", "body", "closed", "base", "head", "draft"]
)
def test_existing_conflict_never_creates(delivery, change):
    root, intent, _ = delivery
    api = API(intent)
    r = row(intent)
    if change == "author":
        r["user"]["id"] = 1
    elif change == "base":
        r["base"]["ref"] = "other"
    elif change == "head":
        r["head"]["sha"] = "b" * 40
    elif change == "closed":
        r["state"] = "closed"
    elif change == "draft":
        r["draft"] = False
    else:
        r[change] += " "
    api.rows = [r]
    with pytest.raises(p.PublicationError, match="conflicts"):
        publish(root, intent, api)
    assert api.creates == 0


def test_offline_preview_never_calls_network_path_or_writes_receipt(
    delivery, monkeypatch
):
    root, intent, _ = delivery

    def forbidden(*a, **kw):
        pytest.fail("Offline preview reached network/PATH")

    monkeypatch.setattr(p.freshness, "check", forbidden)
    monkeypatch.setattr(p, "remote_checks", forbidden)
    monkeypatch.setattr(p, "GitHub", forbidden)
    result = publish(root, intent, None, True)
    assert result["status"] == "local_preview_only"
    assert not p.Receipt(root, intent).path.exists()


@pytest.mark.parametrize(
    "state",
    [
        "untracked",
        "tracked",
        "detached",
        "branch",
        "merge",
        "head",
        "ancestry",
        "closing_commit",
    ],
)
def test_invalid_real_git_state_blocks_before_mutation(delivery, state):
    root, intent, _ = delivery
    if state == "untracked":
        (root / "untracked").write_text("x")
    elif state == "tracked":
        (root / "tracked").write_text("changed")
    elif state == "detached":
        git(root, "checkout", "--detach")
    elif state == "branch":
        git(root, "checkout", "-b", "other")
    elif state == "merge":
        (root / ".git/MERGE_HEAD").write_text(intent.head)
    elif state == "head":
        intent = replace(intent, head=intent.dispatch_base)
    elif state == "ancestry":
        git(root, "checkout", "--orphan", "unrelated")
        git(root, "commit", "-am", "Unrelated")
        unrelated = git(root, "rev-parse", "HEAD")
        git(root, "checkout", "work/slot-3")
        intent = replace(intent, dispatch_base=unrelated)
    else:
        git(root, "commit", "--allow-empty", "-m", "FIXES: #42")
        intent = replace(intent, head=git(root, "rev-parse", "HEAD"))
    api = API(intent)
    with pytest.raises((p.PublicationError, p.git_transport.GitTransportError)):
        publish(root, intent, api)
    assert api.creates == 0


@pytest.mark.parametrize("change", ["wrong", "multiple", "mirror", "stale_head"])
def test_real_remote_configuration_and_oid_checks(delivery, change):
    root, intent, remote = delivery
    if change == "wrong":
        git(
            root,
            "remote",
            "set-url",
            "--push",
            "push-origin",
            "https://example.invalid/repo",
        )
    elif change == "multiple":
        git(root, "remote", "set-url", "--add", "--push", "push-origin", str(remote))
        git(root, "remote", "set-url", "--add", "--push", "push-origin", str(remote))
    elif change == "mirror":
        git(root, "config", "remote.push-origin.mirror", "true")
    else:
        git(root, "commit", "--allow-empty", "-m", "Later")
        intent = replace(intent, head=git(root, "rev-parse", "HEAD"))
    api = API(intent)
    with pytest.raises(p.PublicationError):
        publish(root, intent, api)
    assert api.creates == 0


@pytest.mark.parametrize(
    "text",
    [
        "Fixes #42",
        "CLOSES: #1",
        "resolved owner/repo#2",
        "fix\n#3",
        "**Fixes:** #42",
        "Fixes [#42](https://github.com/x/y/issues/42)",
        "Fixes https://github.com/x/y/issues/42",
        "Fixes: `#42`",
        "Resolves #1, resolves #2",
    ],
)
def test_closing_constructions(text):
    assert p.CLOSING.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Fixed typo",
        "The fixed argument is optional",
        "unfixed #42",
        "Fixes require review",
        "Reference #42",
        "Task: https://github.com/x/y/issues/42",
    ],
)
def test_ordinary_words_and_nonclosing_task_links(text):
    assert p.CLOSING.search(text) is None


def packet_args(tmp_path, root, intent):
    packet = {
        k: getattr(intent, k)
        for k in [
            "repository",
            "task_url",
            "agent_id",
            "session",
            "workplace",
            "branch",
            "dispatch_base",
            "head",
            "account",
            "account_id",
        ]
    }
    packet.update(schema="wea-publication-assignment-1", destination=p.DESTINATION)
    assignment = tmp_path / "assignment.json"
    assignment.write_bytes(json.dumps(packet).encode())
    body = tmp_path / "body.md"
    body.write_bytes(intent.body.replace("\n", "\r\n").encode())
    args = argparse.Namespace(
        assignment=str(assignment),
        assignment_sha256=p.digest(assignment.read_bytes()),
        repo=p.REPO,
        task_url=intent.task_url,
        session=intent.session,
        expected_head=intent.head,
        title=intent.title,
        body_file=str(body),
        draft=True,
    )
    return args, packet


def test_assignment_strictness_and_exact_body_bytes(delivery, tmp_path, monkeypatch):
    root, intent, _ = delivery
    args, packet = packet_args(tmp_path, root, intent)
    monkeypatch.setenv("WEA_AGENT", intent.agent_id)
    assert p.load_intent(args, root).body == intent.body
    Path(args.body_file).write_bytes((" " + intent.body).encode())
    # No strip: a leading space remains part of the validated/submitted bytes.
    with pytest.raises(p.PublicationError):
        p.load_intent(args, root)
    Path(args.body_file).write_bytes(intent.body.encode())
    raw = json.dumps(packet)[:-1] + ',"branch":"work/slot-3"}'
    Path(args.assignment).write_bytes(raw.encode())
    args.assignment_sha256 = p.digest(raw.encode())
    with pytest.raises(p.PublicationError, match="JSON"):
        p.load_intent(args, root)


@pytest.mark.parametrize(
    "change", ["digest", "session", "head", "task", "branch_alias", "account_env"]
)
def test_packet_mismatch(delivery, tmp_path, monkeypatch, change):
    root, intent, _ = delivery
    args, packet = packet_args(tmp_path, root, intent)
    if change == "account_env":
        monkeypatch.setenv("WEA_AGENT", "Other@codex")
    elif change == "branch_alias":
        packet["branch"] = "work/slot-3 "
        Path(args.assignment).write_bytes(json.dumps(packet).encode())
        args.assignment_sha256 = p.digest(Path(args.assignment).read_bytes())
    else:
        attribute = {
            "digest": "assignment_sha256",
            "session": "session",
            "head": "expected_head",
            "task": "task_url",
        }[change]
        setattr(args, attribute, "wrong")
    with pytest.raises(p.PublicationError):
        p.load_intent(args, root)


def test_parser_and_legacy_pr_contract():
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "publish-pr",
            "--assignment",
            "a",
            "--assignment-sha256",
            "b",
            "--session",
            "s",
            "--expected-head",
            "h",
            "--task-url",
            "t",
            "--title",
            "x",
            "--body-file",
            "f",
            "--draft",
        ]
    )
    assert args._handler is p.cmd_publish_pr and args.draft
    assert cli._validate_pr_head("work/slot-3", 42)[1]
    assert not cli._validate_pr_head("agent/codex-19/42-example", 42)[1]
    assert not cli.is_readonly_command("publish-pr", args)


def test_api_submits_exact_bytes_and_sanitizes_failure(tmp_path, monkeypatch):
    seen = []

    def run(args, **kwargs):
        seen.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='{"number":7}')

    monkeypatch.setattr(p.subprocess, "run", run)
    api = p.GitHub(tmp_path)
    body = "  indent\n\nend\n"
    assert api.api("repos/x/y/pulls", {"body": body}) == {"number": 7}
    assert json.loads(seen[0][1]["input"])["body"] == body
    assert seen[0][0][-4:] == ["--method", "POST", "--input", "-"]
    monkeypatch.setattr(
        p.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr="SECRET"),
    )
    with pytest.raises(p.PublicationError) as error:
        api.api("user")
    assert "SECRET" not in str(error.value)


def test_history_pagination_and_failed_read_block(tmp_path, monkeypatch):
    api = p.GitHub(tmp_path)
    pages = [[{"number": n} for n in range(100)], [{"number": 101}]]
    monkeypatch.setattr(api, "api", lambda endpoint: pages.pop(0))
    assert len(api.history()) == 101
    pages[:] = [[{"number": n} for n in range(100)], [{"number": 1}]]
    with pytest.raises(p.PublicationError, match="pagination"):
        api.history()


def test_exclusive_attempt_prevents_overwrite(delivery):
    root, intent, _ = delivery
    receipt = p.Receipt(root, intent)
    receipt.save("attempted", initial=True)
    with pytest.raises(FileExistsError):
        receipt.save("attempted", initial=True)
    assert receipt.load()["status"] == "attempted"


def test_task_url_is_not_a_prefix_match(delivery):
    _, intent, _ = delivery
    other = row(intent)
    other["head"]["ref"] = "work/slot-1"
    other["title"] = "[Task #420] Other task"
    other["body"] = intent.body.replace("issues/42", "issues/420")
    assert p.select_existing([other], intent) is None


def test_wrong_invoked_source_blocks_even_with_current_path(delivery, monkeypatch):
    root, intent, _ = delivery
    monkeypatch.setattr(
        p.freshness,
        "check",
        lambda *a: {
            "invoked_matches_checkout": False,
            "installed_matches_checkout": True,
        },
    )
    api = API(intent)
    with pytest.raises(p.PublicationError, match="Invoked CLI"):
        publish(root, intent, api)
    assert api.creates == 0


def test_another_task_reference_does_not_claim_this_task(delivery):
    _, intent, _ = delivery
    other = row(intent)
    other["state"] = "closed"
    other["head"]["ref"] = "work/agent0"
    other["title"] = "[Task #1047] Workflow documentation"
    other["body"] = (
        "Task: https://github.com/WeTheAgents/wetheagents/issues/1047\n"
        "Related CLI proposal: " + intent.task_url
    )
    assert p.select_existing([other], intent) is None
    other["body"] = "Task: " + intent.task_url
    with pytest.raises(p.PublicationError):
        p.select_existing([other], intent)


def test_cli_reports_exact_safe_preflight_blocker(monkeypatch, capsys):
    monkeypatch.setattr(cli, "resolve_repo_root", lambda root: Path(root))

    def rejected(*args):
        raise p.PublicationError("Existing slot/task PR conflicts")

    monkeypatch.setattr(p, "load_intent", rejected)
    assert p.cmd_publish_pr(argparse.Namespace(root=".")) == 2
    assert (
        capsys.readouterr().out
        == "Publication blocked: Existing slot/task PR conflicts\n"
    )
