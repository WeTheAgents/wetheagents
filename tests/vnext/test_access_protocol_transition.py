"""APT-01..06: authenticated package changes preserve grants and history."""

# Imported pytest fixtures intentionally share test-argument names.
# ruff: noqa: F811

from __future__ import annotations

import argparse
import copy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_cli import access as cli
from wea_vnext import access_control as c
from wea_vnext import access_github as g
from wea_vnext import access_protocol as p
from wea_vnext.tide import domain, ledger

from .test_access_runtime import (  # noqa: F401
    ACCOUNT,
    AT,
    GitAPI,
    comment_row,
    declaration,
    entry,
    genesis,
    identities,
    source,
)
from .test_tide_ledger import commit, put, repo  # noqa: F401

BASE = "b" * 40
LATER = AT + timedelta(minutes=2)


def historical(genesis):
    old = copy.deepcopy(genesis)
    old["protocol_files"]["src/wea_vnext/access_github.py"] = "0" * 64
    command = c.strict_json(old["activation"]["body"][len(c.ACTIVATION_MARKER) :])
    command["protocol_hash"] = c.digest(old["protocol_files"])
    old["activation"]["body"] = c.ACTIVATION_MARKER + c.canonical(command).decode()
    old["activation"]["content_hash"] = c.sha256(old["activation"]["body"])
    return old


def update_source(old, files, number=900, at=LATER):
    command = {
        "schema": p.SCHEMA,
        "previous_protocol_hash": c.digest(old["protocol_files"]),
        "code_sha": BASE,
        "protocol_hash": c.digest(files),
        "journal_ref": g.REF,
    }
    return source(p.MARKER + c.canonical(command).decode(), number, at)


def update_entry(old, files):
    return {
        "schema": p.SCHEMA,
        "source": update_source(old, files),
        "accepted_at": c.json_data(LATER),
        "code_sha": BASE,
        "protocol_files": files,
        "provenance": {},
        "decision": p.decision(old, BASE, files),
    }


@pytest.fixture
def prepared(genesis, identities, monkeypatch):
    old = historical(genesis)
    api = GitAPI()
    journal = g.Journal(api)
    head = journal.append(None, "genesis.json", old)
    _, grant = entry(old, identities)
    journal.append(head, "decision-1.json", grant)
    src = update_source(old, genesis["protocol_files"])
    api.comments.append(comment_row(src))
    original_get = api.get

    def get(path):
        if path.endswith("git/ref/heads/main"):
            return {"object": {"sha": BASE}}
        return original_get(path)

    monkeypatch.setattr(api, "get", get)
    monkeypatch.setattr(g, "protocol", lambda *args: genesis["protocol_files"])
    return api, old, grant, src


def apply(api, src, at=LATER):
    return g.update_protocol(
        api, Path("."), BASE, int(src["object_id"]), src["content_hash"], {}, lambda: at
    )


def test_update_preserves_grants_and_switches_exact_writer(prepared, genesis):
    api, old, grant, src = prepared
    with pytest.raises(ValueError, match="installed Access closure differs"):
        g.Journal(api).read()
    original_objects = copy.deepcopy(api.objects)
    new_commit = apply(api, src)
    journal = g.Journal(api)
    head, retained, entries, commits = journal.read()
    assert head == new_commit and retained == old and entries[0] == grant
    assert all(api.objects[k] == value for k, value in original_objects.items())
    assert c.replay(old, entries).grants == c.replay(old, [grant]).grants
    assert journal.protocol["protocol_files"] == genesis["protocol_files"]
    assert commits[-1] == new_commit
    before = len(api.writes)
    assert apply(api, src) == new_commit
    assert len(api.writes) == before
    observed = cli.read(
        api, argparse.Namespace(agent="Codex-2@codex", request_id=None), ACCOUNT
    )
    assert len(observed["decisions"]) == 1
    snapshot = domain.capture(api, LATER)
    assert len(snapshot["entries"]) == 2
    assert domain.restore(snapshot, LATER, None).grants == journal.state.grants
    assert len(domain.capture(api, AT)["entries"]) == 1


@pytest.mark.parametrize(
    "failure", ["lost-response", "before-publish", "concurrent-grant"]
)
def test_update_recovers_without_replacing_history(prepared, identities, failure):
    api, old, grant, src = prepared
    if failure == "lost-response":
        api.after_publish = True
    elif failure == "before-publish":
        api.before_publish = True
        before = api.ref
        with pytest.raises(g.GitHubError, match="unresolved"):
            apply(api, src)
        assert api.ref == before
        api.before_publish = False
    else:

        def rival():
            _, extra = entry(
                old,
                identities,
                declaration(old, number=2, agent="Codex-19@codex"),
                [grant],
            )
            g.Journal(api).append(api.ref, "decision-2.json", extra)

        api.rival = rival
    commit_sha = apply(api, src)
    _, retained, entries, commits = g.Journal(api).read()
    assert retained == old
    assert sum(e["schema"] == p.SCHEMA for e in entries) == 1
    assert commits[-1] == commit_sha
    assert len(c.replay(old, entries).grants) == (
        2 if failure == "concurrent-grant" else 1
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "author",
        "editor",
        "edited",
        "issue",
        "predecessor",
        "package",
        "code",
        "ref",
        "clock",
        "receipt",
    ],
)
def test_invalid_update_cannot_replay(genesis, mutation):
    old = historical(genesis)
    value = update_entry(old, genesis["protocol_files"])
    src = value["source"]
    if mutation in {"author", "editor"}:
        src[
            "original_author_account_id" if mutation == "author" else "actor_account_id"
        ] = "99"
    elif mutation == "edited":
        src["edit_history"] = ["edited"]
    elif mutation == "issue":
        src["issue_number"] = 998
    elif mutation == "clock":
        value["accepted_at"] = c.json_data(AT)
    elif mutation == "receipt":
        value["decision"]["protocol_hash"] = "0" * 64
    else:
        command = c.strict_json(src["body"][len(p.MARKER) :])
        key = {
            "predecessor": "previous_protocol_hash",
            "package": "protocol_hash",
            "code": "code_sha",
            "ref": "journal_ref",
        }[mutation]
        command[key] = "0" * 64
        src["body"] = p.MARKER + c.canonical(command).decode()
        src["content_hash"] = c.sha256(src["body"])
    with pytest.raises(ValueError):
        c.replay(old, [value])


def test_update_keeps_overlap_and_request_id_rules(prepared, identities):
    api, old, grant, src = prepared
    apply(api, src)
    retry = declaration(
        old, number=3, request_id=grant["decision"]["request"]["request_id"]
    )
    result = g.process(api, retry, identities, BASE, {}, lambda: LATER)
    assert result["grant"] == grant["decision"]["grant"]
    denied = g.process(
        api, declaration(old, number=4), identities, BASE, {}, lambda: LATER
    )
    assert denied["status"] == "rejected" and "overlap" in denied["reason"].lower()
    fresh = g.process(
        api,
        declaration(old, number=5, agent="Codex-19@codex"),
        identities,
        BASE,
        {},
        lambda: LATER,
    )
    assert fresh["status"] == "active"
    assert c.timestamp(fresh["grant"]["ends_at"]) - LATER == timedelta(days=7)
    assert len(g.Journal(api).read()[2]) == 5


def test_trusted_dispatch_updates_then_reconciles_normally(
    prepared, identities, monkeypatch
):
    api, _, _, src = prepared
    original_get = api.get

    def get(path):
        if "/actions/runs/" in path:
            return {
                "path": g.WORKFLOW,
                "head_sha": BASE,
                "head_branch": "main",
                "event": "workflow_dispatch",
            }
        return original_get(path)

    monkeypatch.setattr(api, "get", get)
    monkeypatch.setattr(g, "GitHub", lambda token: api)
    monkeypatch.setattr(g, "git", lambda *args: BASE)
    monkeypatch.setattr(
        g, "load", lambda *args: (SimpleNamespace(registry=identities), [])
    )
    for key, value in {
        "GITHUB_REPOSITORY": g.REPOSITORY,
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": BASE,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }.items():
        monkeypatch.setenv(key, value)
    args = argparse.Namespace(
        activation_comment_id=None,
        protocol_comment_id=900,
        protocol_sha256=src["content_hash"],
    )
    first = g.run(args)
    assert first["decisions"] == 2
    assert g.run(args) == first
    args.protocol_comment_id = None
    assert g.run(args) == first


def test_stale_main_or_wrong_hash_does_not_append(prepared, monkeypatch):
    api, _, _, src = prepared
    before = api.ref
    with pytest.raises(ValueError, match="source hash"):
        apply(api, {**src, "content_hash": "0" * 64})
    original_get = api.get
    monkeypatch.setattr(
        api,
        "get",
        lambda path: {"object": {"sha": "c" * 40}}
        if path.endswith("git/ref/heads/main")
        else original_get(path),
    )
    with pytest.raises(ValueError, match="main changed"):
        apply(api, src)
    assert api.ref == before


def test_access_snapshot_alone_creates_one_tide_checkpoint(prepared, request):
    api, _, _, src = prepared
    apply(api, src)
    root, base = request.getfixturevalue("repo")
    snapshot = domain.capture(api, LATER)
    collection = {"sources": [], "cutoff": c.json_data(LATER), "tracked_issues": []}
    values = ledger.candidate(root, base, collection, {}, {}, access_snapshot=snapshot)
    assert values is not None
    assert values[ledger.STATE]["escrow_wea"] == 0
    put(root, values)
    head = commit(root)
    ledger.validate(root, base, head)
    collection["cutoff"] = c.json_data(LATER + timedelta(seconds=1))
    assert (
        ledger.candidate(root, head, collection, {}, {}, access_snapshot=snapshot)
        is None
    )
