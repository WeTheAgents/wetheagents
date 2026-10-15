"""AS-01/02: trusted current-main activation using synthetic GitHub objects."""
# ruff: noqa: F811 -- imported pytest fixtures intentionally share argument names

from __future__ import annotations

import argparse
import copy
import hashlib
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_vnext import access_control as c
from wea_vnext import access_github as g
from wea_vnext import initiatives as i
from wea_vnext.tide.github import GitHubError
from wea_vnext.tide.replay import canonical, digest

from .test_access_protocol_transition import BASE, LATER, update_entry
from .test_access_runtime import (  # noqa: F401
    GitAPI,
    comment_row,
    genesis,
    identities,
    source,
)
from .test_initiatives import OPERATOR

EXECUTION = "c" * 40
NOW = LATER + timedelta(minutes=1)


@pytest.fixture
def activation_run(genesis, identities, monkeypatch):
    # Hash actual closure files, including the new, not-yet-committed capability.
    # Do not stub verify_installed or the journal, source parser, or pure decision.
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "src/wea_vnext",
            "src/wea_cli/access.py",
            g.WORKFLOW,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files = {
        name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
        for name in sorted({*tracked, i.ACTIVATION_CAPABILITY})
    }
    assert files[i.ACTIVATION_CAPABILITY] == i.ACTIVATION_CAPABILITY_HASH
    api = GitAPI()
    journal = g.Journal(api)
    head = journal.append(None, "genesis.json", genesis)
    installed = update_entry(genesis, files)
    journal.append(head, "protocol-900.json", installed)
    installed_reader = g.Journal(api)
    installed_reader.read()
    assert not isinstance(installed_reader.state, i.State)
    command = {
        "schema": i.SCHEMA,
        "request_id": "ddedb0aa-8aad-4974-bd0c-96e18f0f38ea",
        "actor": OPERATOR,
        "operation": "activate-policy",
        "payload": {
            "policy": i.POLICY,
            "code_sha": BASE,
            "execution_code_sha": EXECUTION,
            "activation_schema": i.ACTIVATION_SCHEMA,
            "protocol_hash": digest(files),
        },
    }
    src = source(i.MARKER + canonical(command).decode(), 901, NOW)
    api.comments.append(comment_row(src))
    args = argparse.Namespace(
        activation_comment_id=None,
        protocol_comment_id=None,
        initiative_comment_id=901,
        initiative_sha256=src["content_hash"],
    )
    context = SimpleNamespace(
        api=api,
        args=args,
        files=files,
        src=src,
        checkout=EXECUTION,
        current_files=copy.deepcopy(files),
        main_reads=0,
        stale=False,
        fail=None,
        workflow={
            "path": g.WORKFLOW,
            "head_sha": EXECUTION,
            "head_branch": "main",
            "event": "workflow_dispatch",
        },
    )
    original_get = api.get

    def get(path):
        if path.endswith("/git/ref/heads/main"):
            context.main_reads += 1
            if context.fail == "main":
                raise GitHubError("required main read failed")
            return {
                "object": {
                    "sha": "d" * 40
                    if context.stale and context.main_reads > 1
                    else EXECUTION
                }
            }
        if "/actions/runs/" in path:
            if context.fail == "actions":
                raise GitHubError("required Actions read failed")
            return copy.deepcopy(context.workflow)
        if path.endswith("/issues/comments/901") and context.fail == "comment":
            raise GitHubError("required comment read failed")
        return original_get(path)

    def protocol(*_):
        if context.fail == "manifest":
            raise GitHubError("required manifest read failed")
        return copy.deepcopy(context.current_files)

    def load(*_):
        if context.fail == "identities":
            raise GitHubError("required identities read failed")
        return SimpleNamespace(registry=identities), []

    monkeypatch.setattr(api, "get", get)
    monkeypatch.setattr(g, "GitHub", lambda token: api)
    monkeypatch.setattr(g, "git", lambda *args: context.checkout)
    monkeypatch.setattr(g, "protocol", protocol)
    monkeypatch.setattr(g, "load", load)
    monkeypatch.setattr(c, "utcnow", lambda: NOW)
    real_process = g.process
    monkeypatch.setattr(
        g,
        "process",
        lambda *args, **kwargs: real_process(*args, clock=lambda: NOW, **kwargs),
    )
    for key, value in {
        "GITHUB_REPOSITORY": g.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": EXECUTION,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    api.writes.clear()
    context.before_ref = api.ref
    return context


def test_trusted_run_retains_both_shas_and_exact_checked_manifest(activation_run):
    ctx = activation_run
    result = g.run(ctx.args)
    assert result["status"] == "reconciled"
    assert result["decisions"] == 2  # Installation plus separate activation.
    journal = g.Journal(ctx.api)
    _, retained, entries, _ = journal.read()
    decision = entries[-1]
    assert decision["decision"]["status"] == "recorded"
    assert decision["identity_commit"] == EXECUTION != BASE
    assert decision["provenance"]["activation_evidence"] == {
        "schema": i.ACTIVATION_SCHEMA,
        "installed_code_sha": BASE,
        "execution_code_sha": EXECUTION,
        "protocol_files": ctx.files,
    }
    assert decision["provenance"]["initiative_activation"] == ctx.src["content_hash"]
    assert isinstance(journal.state, i.State)
    assert not journal.state.initiatives
    assert not journal.state.grants
    assert (
        c.replay(retained, entries).registry == c.replay(retained, entries[:1]).registry
    )
    assert all(
        "/ledger" not in path and "/collaborators" not in path
        for _, path, _ in ctx.api.writes
    )


def test_same_dispatch_returns_original_activation_without_new_journal_effect(
    activation_run,
):
    ctx = activation_run
    first = g.run(ctx.args)
    before = canonical(ctx.api.objects)
    ctx.api.writes.clear()
    assert g.run(ctx.args) == first
    assert canonical(ctx.api.objects) == before
    # Receipt repair is separate from activation idempotency.
    assert all(path.endswith("/comments") for _, path, _ in ctx.api.writes)
    assert len(g.Journal(ctx.api).read()[2]) == 2


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("repository", "trusted canonical"),
        ("ref", "trusted canonical"),
        ("checkout", "checkout"),
        ("github-sha", "checkout"),
        ("workflow-path", "provenance"),
        ("workflow-sha", "provenance"),
        ("workflow-branch", "provenance"),
        ("workflow-event", "provenance"),
        ("absent-dispatch", "explicit workflow dispatch"),
        ("manifest-missing", "protocol closure differs"),
        ("manifest-extra", "protocol closure differs"),
        ("manifest-changed", "protocol closure differs"),
        ("body-hash", "body hash differs"),
        ("stale-main", "main changed before activation"),
    ],
)
def test_invalid_trusted_boundary_fails_before_any_write(
    activation_run, monkeypatch, mutation, message
):
    ctx = activation_run
    if mutation in {"repository", "ref", "github-sha"}:
        key = {
            "repository": "GITHUB_REPOSITORY",
            "ref": "GITHUB_REF",
            "github-sha": "GITHUB_SHA",
        }[mutation]
        monkeypatch.setenv(key, "wrong")
    elif mutation == "checkout":
        ctx.checkout = BASE
    elif mutation.startswith("workflow-"):
        key = {
            "workflow-path": "path",
            "workflow-sha": "head_sha",
            "workflow-branch": "head_branch",
            "workflow-event": "event",
        }[mutation]
        ctx.workflow[key] = "wrong"
    elif mutation == "absent-dispatch":
        ctx.workflow["event"] = "issue_comment"
    elif mutation == "manifest-missing":
        del ctx.current_files[i.ACTIVATION_CAPABILITY]
    elif mutation == "manifest-extra":
        ctx.current_files["src/wea_vnext/uninstalled.py"] = "0" * 64
    elif mutation == "manifest-changed":
        ctx.current_files["src/wea_vnext/initiatives.py"] = "0" * 64
    elif mutation == "body-hash":
        ctx.args.initiative_sha256 = "0" * 64
    elif mutation == "stale-main":
        ctx.stale = True
    else:
        raise AssertionError(mutation)
    with pytest.raises(ValueError, match=message):
        g.run(ctx.args)
    assert ctx.api.ref == ctx.before_ref
    assert ctx.api.writes == []


@pytest.mark.parametrize(
    "required_read", ["main", "actions", "comment", "manifest", "identities"]
)
def test_failed_required_read_cannot_publish(activation_run, required_read):
    ctx = activation_run
    ctx.fail = required_read
    with pytest.raises(GitHubError, match=r"required .* read failed"):
        g.run(ctx.args)
    assert ctx.api.ref == ctx.before_ref
    assert ctx.api.writes == []


def test_nonoperator_source_is_retained_as_rejected_without_activation(activation_run):
    ctx = activation_run
    ctx.api.comments[0]["user"]["id"] = 99
    g.run(ctx.args)
    journal = g.Journal(ctx.api)
    _, _, entries, _ = journal.read()
    assert entries[-1]["decision"]["status"] == "rejected"
    assert "operator" in entries[-1]["decision"]["reason"].lower()
    assert not isinstance(journal.state, i.State)
    assert not journal.state.grants


def test_required_graphql_capture_failure_cannot_publish(activation_run, monkeypatch):
    ctx = activation_run

    def fail(*_):
        raise GitHubError("required revision read failed")

    monkeypatch.setattr(ctx.api, "graphql", fail)
    with pytest.raises(GitHubError, match="required revision read failed"):
        g.run(ctx.args)
    assert ctx.api.ref == ctx.before_ref
    assert ctx.api.writes == []


def test_edited_operator_source_is_retained_as_rejected(activation_run, monkeypatch):
    ctx = activation_run
    real_graphql = ctx.api.graphql

    def edited(query, variables):
        value = real_graphql(query, variables)
        node = value["data"]["node"]
        node["lastEditedAt"] = ctx.src["created_at"]
        node["userContentEdits"] = {
            "nodes": [
                {
                    "id": "EDIT_901",
                    "editedAt": ctx.src["created_at"],
                    "deletedAt": None,
                    "editor": {"databaseId": int(c.OPERATOR)},
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }
        return value

    monkeypatch.setattr(ctx.api, "graphql", edited)
    g.run(ctx.args)
    journal = g.Journal(ctx.api)
    _, _, entries, _ = journal.read()
    assert entries[-1]["decision"]["status"] == "rejected"
    assert "unedited" in entries[-1]["decision"]["reason"]
    assert entries[-1]["source"]["edit_history"]
    assert not isinstance(journal.state, i.State)
    assert not journal.state.grants
