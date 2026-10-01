"""Access adapter behavior, publication failures and recovery (synthetic time)."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from wea_cli import access as cli
from wea_vnext import access_control as c
from wea_vnext import access_github as g
from wea_vnext.tide.collection import API_ROOT, REPOSITORY, REPOSITORY_ID
from wea_vnext.tide.github import GitHubError
from wea_vnext.tide.replay import canonical, digest, json_data

T0 = c.timestamp("2026-09-18T17:00:00Z")
AT = T0 + timedelta(minutes=1)
ACCOUNT = str(c.OPERATOR)


@pytest.fixture
def identities():
    def binding(subject, kind, name):
        return {
            "binding_id": name,
            "actor_kind": kind,
            "github_account_id": ACCOUNT,
            "subject_id": subject,
            "version": 1,
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_until": None,
        }

    return {
        "accounts": [
            {
                "github_account_id": ACCOUNT,
                "owner": "operator",
                "base_agent_id": "agent0@system",
            }
        ],
        "bindings": [
            binding("agent0@system", "agent0", "pilot-agent0-role-v1"),
            binding("Codex-2@codex", "agent", "codex2"),
            binding("Codex-19@codex", "agent", "codex19"),
            binding("agent0@system", "agent", "agent0-account"),
        ],
        "control_group_bindings": [],
    }


def source(body, number=1, at=AT):
    return {
        "repository_id": str(REPOSITORY_ID),
        "issue_number": 997,
        "object_id": str(number),
        "object_kind": "issue_comment",
        "actor_account_id": ACCOUNT,
        "original_author_account_id": ACCOUNT,
        "body": body,
        "content_hash": c.sha256(body),
        "created_at": json_data(at),
        "revision_status": "confirmed",
        "revision_id": f"github:IC_{number}:created",
        "edit_history": [],
        "url": f"https://github.com/{REPOSITORY}/issues/997#issuecomment-{number}",
    }


@pytest.fixture
def genesis():
    raw = Path("domains/registry/v1.json").read_text(encoding="utf-8")
    registry = c.load_domain_registry_bytes(raw.encode(), source="test")
    files = {
        p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in (
            "src/wea_vnext/access_control.py",
            "src/wea_vnext/access_github.py",
            "src/wea_cli/access.py",
            g.WORKFLOW,
        )
    }
    command = {
        "schema": c.SCHEMA,
        "code_sha": "a" * 40,
        "protocol_hash": digest(files),
        "registry_hash": registry.registry_hash,
        "issue_number": 997,
        "journal_ref": g.REF,
    }
    return {
        "schema": c.SCHEMA,
        "repository_id": str(REPOSITORY_ID),
        "issue_number": 997,
        "issue_id": "997997",
        "code_sha": "a" * 40,
        "protocol_files": files,
        "registry_text": raw,
        "registry_hash": registry.registry_hash,
        "cutoff": json_data(T0),
        "activation": source(c.ACTIVATION_MARKER + canonical(command).decode(), 99, T0),
        "provenance": {},
    }


def declaration(
    genesis, *, number=1, request_id=None, agent="Codex-2@codex", issuer=None, at=AT
):
    command = {
        "schema": c.SCHEMA,
        "request_id": request_id or str(uuid4()),
        "agent_id": agent,
        "domain_id": "circle-1",
        "registry_hash": genesis["registry_hash"],
        "issuer": issuer
        or {
            "kind": "agent0",
            "subject": "agent0@system",
            "binding_id": "pilot-agent0-role-v1",
            "binding_version": 1,
        },
    }
    return source(c.MARKER + canonical(command).decode(), number, at)


def entry(genesis, identities, src=None, previous=None, at=AT):
    previous = previous or []
    src = src or declaration(genesis)
    state, decision = c.decide(
        genesis, c.replay(genesis, previous), previous, src, identities, json_data(at)
    )
    return state, {
        "schema": c.SCHEMA,
        "source": src,
        "identities": identities,
        "identity_commit": "b" * 40,
        "accepted_at": json_data(at),
        "provenance": {},
        "decision": decision,
    }


@pytest.mark.parametrize("operator", [False, True])
def test_authority_branches_and_exact_expiry(genesis, identities, operator):
    issuer = (
        {
            "kind": "operator",
            "subject": ACCOUNT,
            "binding_id": "canonical-operator",
            "binding_version": 1,
        }
        if operator
        else None
    )
    state, retained = entry(genesis, identities, declaration(genesis, issuer=issuer))
    assert len(state.grants) == 1, retained
    grant = state.grants[0]
    assert grant.ends_at - grant.starts_at == timedelta(days=7)
    assert (
        c.view(retained, "c" * 40, grant.ends_at - timedelta(microseconds=1))["status"]
        == "active"
    )
    assert c.view(retained, "c" * 40, grant.ends_at)["status"] == "expired"
    _, following = entry(
        genesis,
        identities,
        declaration(genesis, number=2, at=grant.ends_at),
        [retained],
        grant.ends_at,
    )
    assert following["decision"]["status"] == "granted"


@pytest.mark.parametrize(
    "case",
    [
        "account",
        "subject",
        "role",
        "version",
        "recipient",
        "expired",
        "future-role",
        "repository",
        "edited",
        "hash",
        "cutoff",
        "registry",
    ],
)
def test_authority_and_source_rejections(genesis, identities, case):
    src = declaration(genesis)
    command = c.request(src["body"])
    if case == "account":
        src["actor_account_id"] = src["original_author_account_id"] = "123"
    elif case == "subject":
        command["issuer"]["subject"] = "Codex-2@codex"
    elif case == "role":
        command["issuer"]["kind"] = "steward"
    elif case == "version":
        command["issuer"]["binding_version"] = 2
    elif case == "recipient":
        command["agent_id"] = "not-registered"
    elif case == "expired":
        identities["bindings"][0]["effective_until"] = json_data(AT)
    elif case == "future-role":
        identities["bindings"][0]["effective_from"] = json_data(
            AT + timedelta(seconds=1)
        )
    elif case == "repository":
        src["repository_id"] = "123"
    elif case == "edited":
        src["edit_history"] = [{"id": "edit"}]
    elif case == "cutoff":
        src["created_at"] = genesis["cutoff"]
    elif case == "registry":
        command["registry_hash"] = "0" * 64
    src["body"] = c.MARKER + canonical(command).decode()
    src["content_hash"] = "0" * 64 if case == "hash" else c.sha256(src["body"])
    state, retained = entry(genesis, identities, src)
    assert not state.grants
    assert retained["decision"]["status"] == "rejected"
    assert retained["decision"]["reason"]


def test_authority_must_cover_both_times(genesis, identities):
    identities["bindings"][0]["effective_from"] = json_data(AT + timedelta(seconds=1))
    _, retained = entry(genesis, identities, at=AT + timedelta(seconds=2))
    assert retained["decision"]["status"] == "rejected"


def test_retry_reuses_original_interval_and_conflict_is_rejected(genesis, identities):
    src = declaration(genesis)
    _, original = entry(genesis, identities, src)
    retry = copy.deepcopy(src)
    retry.update(object_id="2", revision_id="github:IC_2:created")
    state, duplicate = entry(
        genesis, identities, retry, [original], AT + timedelta(days=8)
    )
    assert len(state.grants) == 1
    assert duplicate["decision"]["grant"] == original["decision"]["grant"]
    assert c.view(duplicate, "c" * 40, AT + timedelta(days=8))["status"] == "expired"
    command = c.request(src["body"])
    conflicting = declaration(
        genesis, number=3, request_id=command["request_id"], agent="Codex-19@codex"
    )
    _, rejected = entry(genesis, identities, conflicting, [original])
    assert "different payload" in rejected["decision"]["reason"]


def test_overlap_and_retained_source_survive_later_edits(genesis, identities):
    _, original = entry(genesis, identities)
    state, rejected = entry(
        genesis, identities, declaration(genesis, number=2), [original]
    )
    assert len(state.grants) == 1
    assert "overlapping" in rejected["decision"]["reason"]
    restored = json.loads(json.dumps([original]))
    assert c.replay(genesis, restored).grants == state.grants
    restored[0]["decision"]["grant"]["ends_at"] = json_data(AT + timedelta(days=8))
    with pytest.raises(ValueError, match="differs"):
        c.replay(genesis, restored)


@pytest.mark.parametrize(
    "extra", ["starts_at", "ends_at", "duration", "revoke", "transfer"]
)
def test_no_caller_clock_or_other_operations(genesis, extra):
    value = c.request(declaration(genesis)["body"])
    value[extra] = "anything"
    with pytest.raises(ValueError, match="fields differ"):
        c.request(c.MARKER + json.dumps(value))


class GitAPI:
    """GitHub's Git-object/ref contract with controllable transport failures."""

    def __init__(self):
        self.objects = {}
        self.ref = None
        self.comments = []
        self.writes = []
        self.after_publish = False
        self.before_publish = False
        self.rival = None
        self.receipt_failure = False
        self.private = True

    def object(self, value):
        sha = hashlib.sha1(canonical(value), usedforsecurity=False).hexdigest()
        self.objects[sha] = {**copy.deepcopy(value), "sha": sha}
        return self.objects[sha]

    def get(self, path):
        if path == API_ROOT:
            return {
                "id": REPOSITORY_ID,
                "full_name": REPOSITORY,
                "private": self.private,
            }
        if path == f"{API_ROOT}/issues/997":
            return {"id": 997997, "number": 997}
        if "/comments?" in path:
            query = parse_qs(urlparse(path).query)
            page, size = int(query["page"][0]), int(query["per_page"][0])
            return copy.deepcopy(self.comments[(page - 1) * size : page * size])
        if "/issues/comments/" in path:
            return next(
                copy.deepcopy(c)
                for c in self.comments
                if str(c["id"]) == path.rsplit("/", 1)[1]
            )
        if "matching-refs" in path:
            return (
                []
                if self.ref is None
                else [{"ref": g.REF, "object": {"sha": self.ref}}]
            )
        return copy.deepcopy(self.objects[path.rsplit("/", 1)[1]])

    def graphql(self, query, variables):
        row = next(c for c in self.comments if c["node_id"] == variables["id"])
        return {
            "data": {
                "node": {
                    "id": row["node_id"],
                    "databaseId": row["id"],
                    "body": row["body"],
                    "createdAt": row["created_at"],
                    "lastEditedAt": None,
                    "userContentEdits": {"nodes": []},
                }
            }
        }

    def request(self, method, path, data):
        self.writes.append((method, path, copy.deepcopy(data)))
        if path.endswith("/git/trees"):
            tree = (
                {}
                if "base_tree" not in data
                else {r["path"]: r for r in self.objects[data["base_tree"]]["tree"]}
            )
            for row in data["tree"]:
                raw = row["content"].encode()
                sha = hashlib.sha1(
                    b"blob " + str(len(raw)).encode() + b"\0" + raw,
                    usedforsecurity=False,
                ).hexdigest()
                self.objects[sha] = {
                    "sha": sha,
                    "encoding": "base64",
                    "content": base64.b64encode(raw).decode(),
                }
                tree[row["path"]] = {
                    "path": row["path"],
                    "mode": row["mode"],
                    "type": "blob",
                    "sha": sha,
                }
            return self.object({"tree": list(tree.values()), "truncated": False})
        if path.endswith("/git/commits"):
            return self.object(
                {
                    "tree": {"sha": data["tree"]},
                    "parents": [{"sha": p} for p in data["parents"]],
                }
            )
        if "/git/refs" in path:
            if self.rival:
                rival, self.rival = self.rival, None
                rival()
            if self.before_publish:
                raise GitHubError("before commit")
            commit = self.objects[data["sha"]]
            if method == "POST":
                if self.ref is not None:
                    raise GitHubError("ref exists")
            elif data.get("force") is not False or commit["parents"] != [
                {"sha": self.ref}
            ]:
                raise GitHubError("non-fast-forward")
            self.ref = data["sha"]
            if self.after_publish:
                self.after_publish = False
                raise GitHubError("response lost")
            return {"object": {"sha": self.ref}}
        if path.endswith("/comments"):
            if self.receipt_failure:
                raise GitHubError("receipt unavailable")
            row = {
                "id": 1000 + len(self.comments),
                "user": {"type": "Bot", "login": "github-actions[bot]"},
                "body": data["body"],
                "created_at": json_data(AT),
            }
            self.comments.append(row)
            return row
        raise AssertionError((method, path))


@pytest.fixture
def api(genesis):
    result = GitAPI()
    g.Journal(result).append(None, "genesis.json", genesis)
    return result


def publish(api, genesis, identities, number=1, at=AT):
    return g.process(
        api, declaration(genesis, number=number), identities, "b" * 40, {}, lambda: at
    )


def test_lost_commit_response_fresh_read_and_receipt_repair(api, genesis, identities):
    api.after_publish = True
    result = publish(api, genesis, identities)
    assert result["status"] == "active"
    head, recovered, entries, commits = g.Journal(api).read()
    assert len(entries) == 1
    assert (
        c.replay(recovered, entries).grants[0].access_id == result["grant"]["access_id"]
    )
    api.receipt_failure = True
    with pytest.raises(GitHubError):
        g.repair_receipts(api, recovered, entries, commits)
    assert g.Journal(api).head() == head
    api.receipt_failure = False
    g.repair_receipts(api, recovered, entries, commits)
    g.repair_receipts(api, recovered, entries, commits)
    assert len(api.comments) == 1
    assert all(
        "ledger" not in path and "/collaborators" not in path
        for _, path, _ in api.writes
    )


def test_before_commit_failure_does_not_issue(api, genesis, identities):
    api.before_publish = True
    with pytest.raises(GitHubError, match="unresolved"):
        publish(api, genesis, identities)
    assert g.Journal(api).read()[2] == []


def test_concurrent_append_loser_revalidates(api, genesis, identities):
    api.rival = lambda: publish(api, genesis, identities, number=2)
    result = publish(api, genesis, identities, number=1)
    assert result["status"] == "rejected"
    assert "overlapping" in result["reason"]
    _, recovered, entries, _ = g.Journal(api).read()
    assert len(entries) == 2
    assert len(c.replay(recovered, entries).grants) == 1


def test_journal_rewrite_and_blob_tampering_fail_closed(api, genesis, identities):
    publish(api, genesis, identities)
    commit = api.objects[api.ref]
    tree = api.objects[commit["tree"]["sha"]]
    blob = api.objects[tree["tree"][-1]["sha"]]
    blob["content"] = base64.b64encode(b"{}").decode()
    with pytest.raises(ValueError, match="integrity"):
        g.Journal(api).read()


def test_disabled_and_explicit_activation(genesis):
    assert g.Journal(GitAPI()).read() == (None, None, [], [])
    g.validate_genesis(genesis)
    genesis["cutoff"] = json_data(AT)
    with pytest.raises(ValueError, match="cutoff"):
        g.validate_genesis(genesis)


def test_cli_parser_has_only_grant_and_show():
    from wea_cli.cli import build_parser, is_readonly_command

    parser = build_parser()
    args = parser.parse_args(["access", "show", "--agent", "Codex-2@codex"])
    assert is_readonly_command("access", args)
    assert (
        parser.parse_args(
            ["access", "grant", "--agent", "x", "--domain", "circle-1"]
        )._handler
        is cli.command
    )
    for operation in ("revoke", "extend", "transfer"):
        with pytest.raises(SystemExit):
            parser.parse_args(["access", operation])


def test_cli_pending_and_expired_read(api, genesis, identities, monkeypatch):
    src = declaration(genesis)
    args = argparse.Namespace(agent="Codex-2@codex", request_id=None)
    api.comments.append(
        {
            "id": 1,
            "body": src["body"],
            "created_at": src["created_at"],
            "user": {"id": int(ACCOUNT)},
            "html_url": src["url"],
        }
    )
    assert cli.read(api, args, ACCOUNT)["status"] == "pending"
    g.process(api, src, identities, "b" * 40, {}, lambda: AT)
    monkeypatch.setattr(c, "utcnow", lambda: AT + timedelta(days=7))
    result = cli.read(api, args, ACCOUNT)
    assert result["decisions"][0]["status"] == "expired"
    assert not result["pending"]


def test_cli_retain_before_post_and_resume_same_request(
    api, genesis, tmp_path, monkeypatch
):
    args = argparse.Namespace(
        agent="Codex-2@codex",
        domain="circle-1",
        request_id=str(uuid4()),
        issuer="agent0",
        binding_id="pilot-agent0-role-v1",
        binding_version=1,
    )
    original = api.request

    def send(method, path, data):
        if path.endswith("/comments"):
            retained = (
                tmp_path / ".wea_runs" / "access-requests" / f"{args.request_id}.json"
            )
            assert json.loads(retained.read_text())["body"] == data["body"]
            src = source(data["body"])
            api.comments.append(
                {
                    "id": 1,
                    "body": src["body"],
                    "created_at": src["created_at"],
                    "user": {"id": int(ACCOUNT)},
                    "html_url": src["url"],
                }
            )
            raise GitHubError("comment response lost")
        return original(method, path, data)

    monkeypatch.setattr(api, "request", send)
    assert cli.submit(api, args, ACCOUNT, tmp_path)["status"] == "pending"
    assert cli.submit(api, args, ACCOUNT, tmp_path)["status"] == "pending"
    assert len(api.comments) == 1
    args.domain = "different"
    with pytest.raises(ValueError, match="different account or payload"):
        cli.submit(api, args, ACCOUNT, tmp_path)


def comment_row(src):
    return {
        "id": int(src["object_id"]),
        "node_id": f"IC_{src['object_id']}",
        "body": src["body"],
        "created_at": src["created_at"],
        "updated_at": src["created_at"],
        "user": {"id": int(ACCOUNT), "login": "peachgabba22", "type": "User"},
        "html_url": src["url"],
        "issue_url": f"https://api.github.com/{API_ROOT}/issues/997",
    }


def test_real_source_capture_checks_rest_graphql_identity(genesis, monkeypatch):
    api = GitAPI()
    row = comment_row(declaration(genesis))
    api.comments.append(row)
    monkeypatch.setattr(c, "utcnow", lambda: AT)
    captured = g.capture(api, 997, row)
    assert captured["revision_id"] == "github:IC_1:created"
    other = copy.deepcopy(row)
    other["body"] += " changed"
    with pytest.raises(ValueError, match="snapshots disagree"):
        g.capture(api, 997, other)


@pytest.mark.parametrize("private", [True, False])
def test_exact_activation_with_committed_protocol_and_response_loss(
    tmp_path, genesis, monkeypatch, private
):
    paths = [*genesis["protocol_files"], "domains/registry/v1.json", ".gitattributes"]
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(name).read_bytes())

    def git(*args):
        return (
            subprocess.run(
                ["git", "-C", str(tmp_path), *args], check=True, capture_output=True
            )
            .stdout.decode()
            .strip()
        )

    git("init")
    git("add", ".")
    git(
        "-c",
        "user.name=Access test",
        "-c",
        "user.email=access@test.invalid",
        "commit",
        "-m",
        "Synthetic protocol fixture",
    )
    sha = git("rev-parse", "HEAD")
    files = g.protocol(tmp_path, sha)
    command = {
        "schema": c.SCHEMA,
        "code_sha": sha,
        "protocol_hash": digest(files),
        "registry_hash": genesis["registry_hash"],
        "issue_number": 997,
        "journal_ref": g.REF,
    }
    approval = source(c.ACTIVATION_MARKER + canonical(command).decode(), 99, T0)
    api = GitAPI()
    api.private = private
    api.comments.append(comment_row(approval))
    api.after_publish = True
    monkeypatch.setattr(c, "utcnow", lambda: AT)
    commit = g.activate(api, tmp_path, sha, 997, 99, approval["content_hash"], {})
    assert commit == api.ref
    assert (
        g.activate(api, tmp_path, sha, 997, 99, approval["content_hash"], {}) == commit
    )
    assert g.Journal(api).read()[1]["cutoff"] == json_data(T0)
    with pytest.raises(ValueError, match="one-time"):
        g.activate(api, tmp_path, sha, 997, 100, "0" * 64, {})


@pytest.mark.parametrize("private", [True, False])
def test_trusted_workflow_reconciles_two_agents_and_skips_old_sources(
    api, genesis, identities, monkeypatch, private
):
    from types import SimpleNamespace

    api.private = private
    base = "b" * 40
    real_get = api.get

    def get(path):
        if path.endswith("/git/ref/heads/main"):
            return {"object": {"sha": base}}
        if "/actions/runs/" in path:
            return {
                "path": g.WORKFLOW,
                "head_sha": base,
                "head_branch": "main",
                "event": "issue_comment",
            }
        return real_get(path)

    monkeypatch.setattr(api, "get", get)
    monkeypatch.setattr(g, "GitHub", lambda token: api)
    monkeypatch.setattr(g, "git", lambda *args: base)
    monkeypatch.setattr(g, "protocol", lambda *args: genesis["protocol_files"])
    monkeypatch.setattr(
        g, "load", lambda *args: (SimpleNamespace(registry=identities), [])
    )
    monkeypatch.setattr(c, "utcnow", lambda: AT)
    # Override the default-bound clock explicitly for this synthetic workflow run.
    real_process = g.process
    monkeypatch.setattr(
        g,
        "process",
        lambda *args, **kwargs: real_process(*args, clock=lambda: AT, **kwargs),
    )
    for key, value in {
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": base,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    api.comments.extend(
        comment_row(src)
        for src in (
            declaration(genesis, number=1, at=T0),
            declaration(genesis, number=2),
            declaration(genesis, number=3, agent="Codex-19@codex"),
        )
    )
    args = argparse.Namespace(activation_comment_id=None)
    assert g.run(args)["decisions"] == 2
    _, recovered, entries, _ = g.Journal(api).read()
    assert len(c.replay(recovered, entries).grants) == 2
    assert g.run(args)["decisions"] == 2
    monkeypatch.setenv("GITHUB_REF", "refs/heads/untrusted")
    with pytest.raises(ValueError, match="trusted canonical"):
        g.run(args)


def test_cli_transport_failure_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "gh", lambda *args: (_ for _ in ()).throw(ValueError("offline"))
    )
    args = argparse.Namespace(
        repo=REPOSITORY, root=".", access_command="show", agent="Codex-2@codex"
    )
    assert cli.command(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"


def test_workflow_has_only_reviewed_main_and_no_financial_permissions():
    text = Path(g.WORKFLOW).read_text()
    assert "github.ref == 'refs/heads/main'" in text
    assert "!github.event.issue.pull_request" in text
    assert "ref: ${{ github.sha }}" in text
    assert "persist-credentials: false" in text
    assert "schedule:" not in text and "pull-requests: write" not in text
    assert "python -m wea_vnext.access_github" in text


def test_edited_request_remains_visible_as_rejected(api, genesis, identities):
    src = declaration(genesis)
    src["edit_history"] = [{"id": "edited-before-capture"}]
    result = g.process(api, src, identities, "b" * 40, {}, lambda: AT)
    assert result["status"] == "rejected"
    request_id = c.request(src["body"])["request_id"]
    observed = cli.read(api, argparse.Namespace(request_id=request_id), ACCOUNT)
    assert observed["status"] == "observed"
    assert "unedited" in observed["decisions"][0]["reason"]


def test_deeply_nested_request_is_rejected_without_poisoning_next_source(
    api, genesis, identities
):
    nested = source(c.MARKER + "[" * 5000 + "0" + "]" * 5000)
    result = g.process(api, nested, identities, "b" * 40, {}, lambda: AT)
    assert result["status"] == "rejected"
    assert "nesting" in result["reason"]
    assert publish(api, genesis, identities, number=2)["status"] == "active"


def test_invalid_unicode_is_retained_rejection(api, genesis, identities):
    value = c.request(declaration(genesis)["body"])
    value["agent_id"] = chr(0xD800)
    src = source(c.MARKER + json.dumps(value, ensure_ascii=True))
    result = g.process(api, src, identities, "b" * 40, {}, lambda: AT)
    assert "invalid Unicode" in result["reason"]
    assert publish(api, genesis, identities, number=2)["status"] == "active"


def test_fresh_cli_retry_rejects_conflicting_payload(
    api, genesis, identities, tmp_path
):
    src = declaration(genesis)
    g.process(api, src, identities, "b" * 40, {}, lambda: AT)
    args = argparse.Namespace(
        agent="Codex-19@codex",
        domain="circle-1",
        request_id=c.request(src["body"])["request_id"],
        issuer="agent0",
        binding_id="pilot-agent0-role-v1",
        binding_version=1,
    )
    with pytest.raises(ValueError, match="different payload"):
        cli.submit(api, args, ACCOUNT, tmp_path)


def test_capacity_does_not_make_prior_history_unreadable(
    api, genesis, identities, monkeypatch
):
    monkeypatch.setattr(g, "MAX_GRANTS", 1)
    publish(api, genesis, identities)
    with pytest.raises(ValueError, match="capacity reached"):
        g.process(
            api,
            declaration(genesis, number=2, agent="Codex-19@codex"),
            identities,
            "b" * 40,
            {},
            lambda: AT,
        )
    assert len(g.Journal(api).read()[2]) == 1


def test_corrupted_receipt_is_replaced_without_regrant(api, genesis, identities):
    publish(api, genesis, identities)
    head, retained, entries, commits = g.Journal(api).read()
    g.repair_receipts(api, retained, entries, commits)
    api.comments[0]["body"] = f"<!-- wea-access-receipt:{head} -->\nwrong body"
    g.repair_receipts(api, retained, entries, commits)
    g.repair_receipts(api, retained, entries, commits)
    assert len(api.comments) == 2
    assert "wrong body" not in api.comments[-1]["body"]
    assert g.Journal(api).head() == head


def test_exact_2000_comment_boundary_preserves_read_and_receipt_repair(
    api, genesis, identities
):
    publish(api, genesis, identities)
    _, retained, entries, commits = g.Journal(api).read()
    api.comments = [
        {
            "id": 10000 + i,
            "created_at": json_data(T0),
            "body": "historical unrelated comment",
            "user": {"type": "User"},
        }
        for i in range(1999)
    ]
    g.repair_receipts(api, retained, entries, commits)
    assert len(api.comments) == 2000

    g.repair_receipts(api, retained, entries, commits)
    observed = cli.read(
        api, argparse.Namespace(agent="Codex-2@codex", request_id=None), ACCOUNT
    )
    assert observed["status"] == "observed"
    assert len(api.comments) == 2000


@pytest.mark.parametrize(
    "target",
    [
        g.WORKFLOW,
        "src/wea_vnext/domain_access.py",
        "src/wea_vnext/access_control.py",
        "src/wea_vnext/access_protocol.py",
        "src/wea_vnext/access_github.py",
        "src/wea_cli/access.py",
    ],
)
def test_installed_guard_pins_access_writer_closure(target):
    from wea_vnext.block9.common import Block9Error
    from wea_vnext.block9.writer import validate_writer_boundary_sources

    paths = [
        *Path("src").rglob("*.py"),
        *Path("src").rglob("*.json"),
        *Path(".github/workflows").glob("*.yml"),
        Path("pyproject.toml"),
    ]
    snapshot = {p.as_posix(): p.read_bytes() for p in paths}
    validate_writer_boundary_sources(snapshot, snapshot)
    changed = dict(snapshot)
    changed[target] += b"\n# changed writer\n"
    with pytest.raises(Block9Error, match="boundary"):
        validate_writer_boundary_sources(snapshot, changed)


def test_invalid_sources_do_not_consume_grant_capacity(
    api, genesis, identities, monkeypatch
):
    monkeypatch.setattr(g, "MAX_GRANTS", 1)
    for number in range(1, 4):
        src = declaration(genesis, number=number)
        src["actor_account_id"] = src["original_author_account_id"] = "123"
        assert (
            g.process(api, src, identities, "b" * 40, {}, lambda: AT)["status"]
            == "rejected"
        )
    assert publish(api, genesis, identities, number=4)["status"] == "active"
    _, retained, entries, _ = g.Journal(api).read()
    assert len(entries) == 4
    assert len(c.replay(retained, entries).grants) == 1


def test_native_git_transfers_history_once_and_reads_new_objects(tmp_path, monkeypatch):
    repository = tmp_path / "source"
    repository.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repository), *args],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "--quiet")
    git("config", "user.name", "Access test")
    git("config", "user.email", "access@example.invalid")
    git("config", "commit.gpgsign", "false")
    (repository / "record.json").write_bytes(b'{"first":true}\n')
    git("add", "record.json")
    git("commit", "--quiet", "-m", "first")
    first = git("rev-parse", "HEAD")
    api = g.GitHub("test-token-never-on-command-line")
    popen = subprocess.Popen
    fetches = []

    def local_transfer(argv, **kwargs):
        if "fetch" in argv:
            assert api.token not in " ".join(argv)
            assert kwargs["env"]["GIT_CONFIG_VALUE_1"] == "false"
            fetches.append(argv[-1])
            argv = [*argv[:-2], str(repository), argv[-1]]
        return popen(argv, **kwargs)

    monkeypatch.setattr(g.subprocess, "Popen", local_transfer)
    try:
        commit = api.get(f"{API_ROOT}/git/commits/{first}")
        tree = api.get(f"{API_ROOT}/git/trees/{commit['tree']['sha']}")
        blob = api.get(f"{API_ROOT}/git/blobs/{tree['tree'][0]['sha']}")
        assert commit["parents"] == []
        assert tree["tree"][0]["mode"] == "100644"
        assert base64.b64decode(blob["content"]) == b'{"first":true}\n'
        assert fetches == [first]
        (repository / "record.json").write_bytes(b'{"second":true}\n')
        git("add", "record.json")
        git("commit", "--quiet", "-m", "second")
        second = git("rev-parse", "HEAD")
        assert api.get(f"{API_ROOT}/git/commits/{second}")["parents"] == [
            {"sha": first}
        ]
        assert fetches == [first, second]
        assert api.get(f"{API_ROOT}/git/commits/{first}") == commit
        assert len(fetches) == 2
    finally:
        directory = Path(api._directory.name)
        api.close()
    assert not directory.exists()


def test_reconciliation_reuses_validated_history(api, genesis, identities, monkeypatch):
    original = c.replay
    replay_sizes = []

    def replay(start, entries):
        replay_sizes.append(len(entries))
        return original(start, entries)

    monkeypatch.setattr(c, "replay", replay)
    journal = g.Journal(api)
    for number, agent in enumerate(("Codex-2@codex", "Codex-19@codex"), 1):
        assert (
            g.process(
                api,
                declaration(genesis, number=number, agent=agent),
                identities,
                "b" * 40,
                {},
                lambda: AT,
                journal=journal,
            )["status"]
            == "active"
        )
    assert len(journal.read()[2]) == 2
    assert replay_sizes == [0]
    assert len(g.Journal(api).read()[2]) == 2
    assert replay_sizes == [0, 2]


def test_2001st_comment_refuses_capture_and_preserves_journal(api, genesis):
    api.comments = [comment_row(declaration(genesis, number=i)) for i in range(1, 2002)]
    head = api.ref
    writes = len(api.writes)
    with pytest.raises(ValueError, match="exceeds 2000"):
        g.comments(api, 997)
    assert api.ref == head
    assert len(api.writes) == writes


def test_full_issue_refuses_receipt_and_retains_cli_request(
    api, genesis, identities, tmp_path
):
    publish(api, genesis, identities)
    _, retained, entries, commits = g.Journal(api).read()
    api.comments = [comment_row(source("unrelated", i, T0)) for i in range(1, 2001)]
    writes = len(api.writes)
    with pytest.raises(ValueError, match="receipt pending"):
        g.repair_receipts(api, retained, entries, commits)
    args = argparse.Namespace(
        request_id=None,
        agent="Codex-19@codex",
        domain="circle-1",
        issuer="agent0",
        binding_id="pilot-agent0-role-v1",
        binding_version=1,
    )
    with pytest.raises(ValueError, match="pending locally"):
        cli.submit(api, args, ACCOUNT, tmp_path)
    assert len(list((tmp_path / ".wea_runs/access-requests").glob("*.json"))) == 1
    assert len(api.writes) == writes


@pytest.mark.skipif(os.name != "nt", reason="Windows Git wrapper timeout regression")
def test_native_git_timeout_terminates_child_processes(tmp_path, monkeypatch):
    from types import SimpleNamespace

    pid_file = tmp_path / "child-pid"
    api = g.GitHub("credential-must-not-appear-in-errors")
    api._directory = SimpleNamespace(name=str(tmp_path))
    popen = subprocess.Popen
    processes = []

    def stalled_transfer(argv, **kwargs):
        if argv[0] != "git":
            return popen(argv, **kwargs)
        code = (
            "import subprocess,sys,time; "
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(60)']); "
            "open(sys.argv[1],'w').write(str(child.pid)); time.sleep(60)"
        )
        process = popen([sys.executable, "-c", code, str(pid_file)], **kwargs)
        processes.append(process)
        wait = process.wait
        deadline = time.monotonic() + 5
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_file.exists()
        process.wait = lambda timeout=None: wait(0.1 if timeout == 120 else timeout)
        return process

    monkeypatch.setattr(g.subprocess, "Popen", stalled_transfer)
    with pytest.raises(
        GitHubError, match="canonical Access Git object transfer failed"
    ):
        api._git("fetch")
    assert processes[0].poll() is not None
    child_pid = pid_file.read_text()
    running = subprocess.run(
        ["tasklist", "/FI", f"PID eq {child_pid}", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert f'"{child_pid}"' not in running
