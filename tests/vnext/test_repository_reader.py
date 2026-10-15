"""Real bounded HTTP transport plus canonical process routing (no network)."""

# ruff: noqa: F811
from __future__ import annotations

import http.client
import io
import itertools
import json
import os
import shutil
import subprocess
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from wea_vnext import access_github as g
from wea_vnext import access_protocol as protocol
from wea_vnext import repository_reader as r
from wea_vnext.tide.github import GitHub, GitHubError, _NoRedirect

from .test_access_runtime import GitAPI, genesis, identities  # noqa: F401
from .test_initiatives import AGENT0, history, replacement  # noqa: F401

LOCATOR = "https://github.com/WeTheAgents/external"
SHA = "a" * 40
TOKEN = "synthetic-secret-sentinel"
IDENTITY = {"id": 321, "node_id": "R_external", "full_name": "WeTheAgents/external"}
CONTEXT = {
    "data": {
        "node": {
            "id": "R_external",
            "nameWithOwner": "WeTheAgents/external",
            "object": {"oid": SHA},
        }
    }
}


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(
            value if isinstance(value, bytes) else json.dumps(value).encode()
        )


def reader(*responses):
    client = r.RepositoryReader(TOKEN)
    client.opener = Opener(*responses)
    return client


@pytest.mark.parametrize(
    "path",
    ["https://api.github.com/repos/WeTheAgents/external", "repos/WeTheAgents/external"],
)
def test_canonical_writer_still_refuses_external_paths(path):
    client = GitHub(TOKEN)
    client.opener = Opener()
    with pytest.raises(GitHubError, match="outside the canonical repository"):
        client.get(path)
    assert client.opener.calls == []


def test_real_transport_has_only_exact_read_requests():
    client = reader(IDENTITY, CONTEXT)
    assert client.identity(LOCATOR) == IDENTITY
    assert client.commit("R_external", SHA) == CONTEXT["data"]["node"]
    first, second = [call[0] for call in client.opener.calls]
    assert (first.full_url, first.method, first.data) == (
        "https://api.github.com/repos/WeTheAgents/external",
        "GET",
        None,
    )
    assert (second.full_url, second.method) == (
        "https://api.github.com/graphql",
        "POST",
    )
    assert json.loads(second.data) == {
        "query": r.COMMIT_QUERY,
        "variables": {"id": "R_external", "revision": SHA},
    }
    assert "mutation" not in r.COMMIT_QUERY
    assert all(timeout == 30 for _, timeout in client.opener.calls)
    assert not any(
        hasattr(client, name) for name in ("request", "get", "post", "graphql")
    )


@pytest.mark.parametrize(
    "locator",
    [
        "http://github.com/owner/repo",
        "https://evil.test/owner/repo",
        "https://github.com@evil.test/owner/repo",
        "https://github.com:443/owner/repo",
        LOCATOR + "?write=1",
        LOCATOR + "#fragment",
        LOCATOR + "/../other",
        "https://github.com/owner/%2frepo",
        "https://github.com/owner/..",
        LOCATOR + "\\other",
        LOCATOR + "\r\nAuthorization:x",
        LOCATOR + ".git",
    ],
)
def test_locator_attacks_never_reach_transport(locator):
    client = reader()
    with pytest.raises(ValueError):
        client.identity(locator)
    assert not client.opener.calls


@pytest.mark.parametrize(
    "node,revision",
    [
        ("bad/node", SHA),
        ("mutation{x}", SHA),
        ("R_external", "main"),
        ("R_external", SHA + "\n"),
        ("R_external", "b" * 39),
    ],
)
def test_commit_inputs_never_inject_query(node, revision):
    client = reader()
    with pytest.raises(ValueError):
        client.commit(node, revision)
    assert not client.opener.calls


def test_redirect_is_rejected_without_forwarding_auth():
    handler = next(
        h
        for h in r.RepositoryReader(TOKEN).opener.handlers
        if isinstance(h, _NoRedirect)
    )
    request = urllib.request.Request(
        "https://api.github.com/repos/a/b", headers={"Authorization": TOKEN}
    )
    with pytest.raises(GitHubError, match="redirect"):
        handler.redirect_request(
            request, None, 302, TOKEN, {}, "https://evil.test/" + TOKEN
        )


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500])
def test_http_errors_are_secret_safe_and_visibility_explicit(status):
    client = reader(
        urllib.error.HTTPError(
            "https://api.github.com/" + TOKEN, status, TOKEN, {}, None
        )
    )
    with pytest.raises(GitHubError) as caught:
        client.identity(LOCATOR)
    assert TOKEN not in str(caught.value)
    assert f"HTTP {status}" in str(caught.value)
    assert "visibility" in str(caught.value)


@pytest.mark.parametrize(
    "response",
    [
        b"{invalid-secret-sentinel",
        b"\xff",
        b"x" * (r.MAX_BYTES + 1),
        [],
        None,
        TimeoutError(TOKEN),
        urllib.error.URLError(TOKEN),
    ],
    ids=[
        "invalid-json",
        "invalid-utf8",
        "oversized",
        "array",
        "null",
        "timeout",
        "url-error",
    ],
)
def test_bad_responses_fail_closed(response):
    client = reader(response)
    with pytest.raises(GitHubError) as caught:
        client.identity(LOCATOR)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    "change",
    [
        {"id": True},
        {"id": 0},
        {"node_id": None},
        {"node_id": "bad/id"},
        {"full_name": "evil.test/a/b"},
        {"full_name": None},
    ],
)
def test_invalid_metadata_fails_closed(change):
    with pytest.raises(GitHubError):
        reader({**IDENTITY, **change}).identity(LOCATOR)


@pytest.mark.parametrize(
    "value",
    [
        {"errors": [TOKEN], **CONTEXT},
        {"data": None},
        {"data": {"node": None}},
        {"data": {"node": {**CONTEXT["data"]["node"], "id": "R_other"}}},
        {"data": {"node": {**CONTEXT["data"]["node"], "object": {}}}},
        {"data": {"node": {**CONTEXT["data"]["node"], "object": {"oid": "b" * 40}}}},
        {"data": {"node": {**CONTEXT["data"]["node"], "nameWithOwner": "bad/../path"}}},
    ],
)
def test_context_identity_and_commit_are_bound(value):
    with pytest.raises(GitHubError) as caught:
        reader(value).commit("R_external", SHA)
    assert TOKEN not in str(caught.value)


def journal_api(history):
    api = GitAPI()
    journal = g.Journal(api)
    journal.append(None, "genesis.json", history.genesis)
    for item in history.entries:
        prefix = "protocol" if item["schema"] == protocol.SCHEMA else "decision"
        journal.append(
            journal.head(), f"{prefix}-{item['source']['object_id']}.json", item
        )
    api.writes.clear()
    return api, journal


def test_process_captures_real_transport_observations_and_retry(history):
    api, journal = journal_api(history)
    payload = replacement(history, "R_external", "another-domain")
    revision = payload["record"]["revision"]
    context = {
        "data": {"node": {**CONTEXT["data"]["node"], "object": {"oid": revision}}}
    }
    client = reader(IDENTITY, context)
    source = history.prepare("registry-add", payload, AGENT0)
    result = g.process(
        api,
        source,
        history.identities,
        "b" * 40,
        {},
        lambda: history.now,
        repository_reader=client,
    )
    assert result["status"] == "recorded", result
    assert len(client.opener.calls) == 2
    _, _, entries, _ = journal.read()
    assert entries[-1]["repositories"] == [
        {
            "requested_locator": payload["record"]["repository_locator"],
            "repository_id": "R_external",
            "repository_aliases": ["321", "R_external"],
            "repository_locator": LOCATOR,
            "context_revision": revision,
        }
    ]
    assert all(
        path.startswith("repos/WeTheAgents/wetheagents/") for _, path, _ in api.writes
    )
    before = journal.head()
    again = g.process(
        api,
        source,
        history.identities,
        "b" * 40,
        {},
        lambda: history.now,
        repository_reader=client,
    )
    assert again == result
    assert journal.head() == before and len(client.opener.calls) == 2


@pytest.mark.parametrize("status", [401, 403, 404])
def test_process_private_failure_has_no_append(history, status):
    api, journal = journal_api(history)
    client = reader(urllib.error.HTTPError(LOCATOR, status, TOKEN, {}, None))
    source = history.prepare(
        "registry-add", replacement(history, "R_external", "another-domain"), AGENT0
    )
    before = journal.head()
    with pytest.raises(GitHubError, match=f"HTTP {status}"):
        g.process(
            api,
            source,
            history.identities,
            "b" * 40,
            {},
            lambda: history.now,
            repository_reader=client,
        )
    assert journal.head() == before and not api.writes


@pytest.mark.parametrize(
    "name", ["repos/owner/repo/issues", "https://evil.test/", "graphql"]
)
def test_reader_cannot_become_generic_transport(name):
    client = reader()
    with pytest.raises((ValueError, GitHubError)):
        client._read(name)
    assert not client.opener.calls


def test_reader_forbids_mutation_payload():
    client = reader()
    with pytest.raises(GitHubError, match="query is not permitted"):
        client._read(
            "graphql", {"query": "mutation { deleteRepository }", "variables": {}}
        )
    assert not client.opener.calls


def test_preflight_uses_same_reader_without_any_writer(monkeypatch):
    client = reader(IDENTITY, CONTEXT)

    def construct(token):
        assert token == TOKEN
        return client

    monkeypatch.setattr(r, "RepositoryReader", construct)

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight attempted a canonical writer operation")

    for name in (
        "GitHub",
        "Journal",
        "process",
        "repair_receipts",
        "activate",
        "update_protocol",
    ):
        monkeypatch.setattr(g, name, forbidden)
    result = r.preflight(LOCATOR, "321", SHA, "e" * 40, TOKEN, "WEA_DOMAIN_READ_TOKEN")
    assert result["status"] == "read-only-verified"
    assert result["execution_code_sha"] == "e" * 40
    assert result["repository_aliases"] == ["321", "R_external"]
    assert result["context_revision"] == SHA
    assert result["credential_source"] == "WEA_DOMAIN_READ_TOKEN"
    assert TOKEN not in json.dumps(result)
    assert len(client.opener.calls) == 2


def test_preflight_rejects_wrong_permanent_id_before_commit(monkeypatch):
    client = reader(IDENTITY)
    monkeypatch.setattr(r, "RepositoryReader", lambda token: client)
    with pytest.raises(GitHubError, match="repository ID differs"):
        r.preflight(LOCATOR, "R_other", SHA, "e" * 40, TOKEN, "GITHUB_TOKEN")
    assert len(client.opener.calls) == 1


@pytest.mark.parametrize(
    "option",
    ["--protocol-comment-id", "--initiative-comment-id", "--activation-comment-id"],
)
def test_preflight_cli_rejects_write_modes_before_transport(monkeypatch, option):
    monkeypatch.setattr(
        "sys.argv",
        [
            "reader",
            "--locator",
            LOCATOR,
            "--repository-id",
            "321",
            "--revision",
            SHA,
            option,
            "12",
        ],
    )
    monkeypatch.setattr(
        r, "RepositoryReader", lambda token: pytest.fail("unexpected transport")
    )
    with pytest.raises(SystemExit) as caught:
        r.main()
    assert caught.value.code == 2


@pytest.mark.parametrize("domain_token", ["", TOKEN])
def test_preflight_cli_selects_credential_without_printing_it(
    monkeypatch, capsys, domain_token
):
    monkeypatch.setattr(
        "sys.argv",
        ["reader", "--locator", LOCATOR, "--repository-id", "321", "--revision", SHA],
    )
    monkeypatch.setenv("GITHUB_TOKEN", "canonical-synthetic")
    monkeypatch.setenv("WEA_DOMAIN_READ_TOKEN", domain_token)
    monkeypatch.setenv("GITHUB_SHA", "e" * 40)
    client = reader(IDENTITY, CONTEXT)

    def construct(token):
        assert token == (domain_token or "canonical-synthetic")
        return client

    monkeypatch.setattr(r, "RepositoryReader", construct)
    assert r.main() == 0
    output = capsys.readouterr().out
    assert TOKEN not in output and "canonical-synthetic" not in output
    assert json.loads(output)["credential_source"] == (
        "WEA_DOMAIN_READ_TOKEN" if domain_token else "GITHUB_TOKEN"
    )


@pytest.mark.parametrize(
    "error", [ValueError(TOKEN), http.client.IncompleteRead(TOKEN.encode())]
)
def test_header_and_truncated_transport_errors_are_redacted(error):
    with pytest.raises(GitHubError) as caught:
        reader(error).identity(LOCATOR)
    assert TOKEN not in str(caught.value)


PREFLIGHT_FIELDS = ["LOCATOR", "REPOSITORY_ID", "REVISION"]
WRITE_FIELDS = [
    "ISSUE",
    "ACTIVATION_COMMENT",
    "ACTIVATION_HASH",
    "PROTOCOL_COMMENT",
    "PROTOCOL_HASH",
    "INITIATIVE_COMMENT",
    "INITIATIVE_HASH",
]


@pytest.fixture(scope="module")
def bash_path():
    if os.name == "nt":
        git = shutil.which("git")
        assert git, "Git for Windows is required for workflow guard verification"
        directory = Path(git).resolve().parent
        candidates = [directory / "bash.exe", directory.parent / "bin/bash.exe"]
        bash = next((str(path) for path in candidates if path.is_file()), None)
    else:
        bash = shutil.which("bash")
    assert bash, "A working Bash is required for workflow guard verification"
    probe = subprocess.run(
        [bash, "--noprofile", "--norc", "-c", "printf BASH_READY"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert probe.returncode == 0 and probe.stdout == "BASH_READY", probe.stderr
    return bash


@pytest.mark.parametrize("present", list(itertools.product((False, True), repeat=3)))
@pytest.mark.parametrize("write_field", [None, *WRITE_FIELDS])
def test_workflow_preflight_input_guard_stops_before_next_step(
    present, write_field, bash_path
):
    workflow = Path(g.WORKFLOW).read_text()
    step = workflow.split(
        "      - name: Reject mixed or incomplete preflight inputs", 1
    )[1]
    script = textwrap.dedent(
        step.split("        run: |\n", 1)[1].split("      - uses:", 1)[0]
    )
    env = {**os.environ, **dict.fromkeys([*PREFLIGHT_FIELDS, *WRITE_FIELDS], "")}
    env.update(
        {
            name: "present" if enabled else ""
            for name, enabled in zip(PREFLIGHT_FIELDS, present, strict=True)
        }
    )
    if write_field:
        env[write_field] = "present"
    result = subprocess.run(
        [bash_path, "--noprofile", "--norc", "-c", script + "\nprintf VALIDATED\n"],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if all(present) and write_field is None:
        assert result.returncode == 0 and result.stdout == "VALIDATED"
    else:
        assert result.returncode != 0 and "VALIDATED" not in result.stdout
