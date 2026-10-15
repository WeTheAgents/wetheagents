"""AS-01..03: versioned activation without reinterpretation of old records."""

# Imported pytest fixtures intentionally share test-argument names.
# ruff: noqa: F811

import copy
from pathlib import Path

import pytest

from wea_vnext import access_control as c
from wea_vnext import access_github as g
from wea_vnext import access_protocol as p
from wea_vnext import initiatives as i

from .test_access_runtime import genesis, identities, source  # noqa: F401
from .test_initiatives import AGENT, OPERATOR, History

EXECUTION = "c" * 40


def install_v2(history):
    previous = p.package(history.genesis, history.entries)
    files = {
        **previous["protocol_files"],
        i.ACTIVATION_CAPABILITY: i.ACTIVATION_CAPABILITY_HASH,
    }
    command = {
        "schema": p.SCHEMA,
        "previous_protocol_hash": c.digest(previous["protocol_files"]),
        "code_sha": "d" * 40,
        "protocol_hash": c.digest(files),
        "journal_ref": g.REF,
    }
    src = source(p.MARKER + c.canonical(command).decode(), 900, history.now)
    history.entries.append(
        {
            "schema": p.SCHEMA,
            "source": src,
            "accepted_at": c.json_data(history.now),
            "code_sha": command["code_sha"],
            "protocol_files": files,
            "provenance": {},
            "decision": p.decision(previous, command["code_sha"], files),
        }
    )
    return p.package(history.genesis, history.entries)


def request_v2(history, package=None):
    package = package or p.package(history.genesis, history.entries)
    payload = {
        "policy": i.POLICY,
        "activation_schema": i.ACTIVATION_SCHEMA,
        "code_sha": package["code_sha"],
        "execution_code_sha": EXECUTION,
        "protocol_hash": c.digest(package["protocol_files"]),
    }
    src = history.prepare("activate-policy", payload, OPERATOR)
    proof = {
        "workflow": g.WORKFLOW,
        "event": "workflow_dispatch",
        "code_sha": EXECUTION,
        "initiative_activation": src["content_hash"],
        "activation_evidence": {
            "schema": i.ACTIVATION_SCHEMA,
            "installed_code_sha": package["code_sha"],
            "execution_code_sha": EXECUTION,
            "protocol_files": copy.deepcopy(package["protocol_files"]),
        },
    }
    return src, proof


def test_capability_bytes_and_legacy_positive(genesis, identities):
    assert (
        c.sha256(Path(i.ACTIVATION_CAPABILITY).read_text())
        == i.ACTIVATION_CAPABILITY_HASH
    )
    legacy = History(genesis, identities)
    assert isinstance(legacy.state, i.State)
    assert not i.supports_activation_v2(p.package(genesis, legacy.entries))


def test_new_main_activation_and_exact_retry(genesis, identities):
    history = History(genesis, identities, active=False)
    install_v2(history)
    assert not isinstance(history.state, i.State)
    src, proof = request_v2(history)
    result = history.add_source(src, provenance=proof)
    assert result["status"] == "recorded"
    assert history.state.grants == ()
    assert history.state.registry == c.replay(genesis, history.entries[:2]).registry
    original = copy.deepcopy(history.entries)
    command = i.request(src["body"])
    retry = history.prepare(
        "activate-policy",
        command["payload"],
        OPERATOR,
        request_id=command["request_id"],
    )
    result = history.add_source(retry, provenance=proof)
    assert result["duplicate_of"] == src["object_id"]
    conflict = history.prepare(
        "activate-policy",
        {**command["payload"], "execution_code_sha": "e" * 40},
        OPERATOR,
        request_id=command["request_id"],
    )
    assert history.add_source(conflict, provenance=proof)["status"] == "rejected"
    assert history.entries[: len(original)] == original
    assert c.canonical(c.replay(genesis, original)) == c.canonical(history.state)


@pytest.mark.parametrize(
    "bad",
    [
        "installed",
        "execution",
        "execution-format",
        "hash",
        "policy",
        "version",
        "operator",
        "edited",
        "source-hash",
        "dispatch",
        "workflow",
        "provenance-sha",
        "source-proof",
        "missing-proof",
        "proof-schema",
        "proof-installed",
        "proof-execution",
        "missing-file",
        "extra-file",
        "changed-file",
        "proof-extra",
        "capability-absent",
        "capability-wrong",
    ],
)
def test_activation_v2_rejects_independent_invalid_condition(genesis, identities, bad):
    history = History(genesis, identities, active=False)
    package = install_v2(history)
    src, proof = request_v2(history)
    command = i.request(src["body"])
    payload = command["payload"]
    mutations = {
        "installed": ("code_sha", "e" * 40),
        "execution": ("execution_code_sha", "e" * 40),
        "execution-format": ("execution_code_sha", "not-a-sha"),
        "hash": ("protocol_hash", "0" * 64),
        "policy": ("policy", "other"),
        "version": ("activation_schema", "unknown"),
    }
    if bad in mutations:
        key, value = mutations[bad]
        payload[key] = value
    if bad == "operator":
        command["actor"] = AGENT
    src["body"] = i.MARKER + c.canonical(command).decode()
    src["content_hash"] = c.sha256(src["body"])
    proof["initiative_activation"] = src["content_hash"]
    if bad == "edited":
        src["edit_history"] = [{"edited": True}]
    if bad == "source-hash":
        src["content_hash"] = "0" * 64
    for case, field, value in [
        ("dispatch", "event", "issue_comment"),
        ("workflow", "workflow", "other"),
        ("provenance-sha", "code_sha", "e" * 40),
        ("source-proof", "initiative_activation", "0" * 64),
    ]:
        if bad == case:
            proof[field] = value
    evidence = proof["activation_evidence"]
    if bad == "missing-proof":
        proof.pop("activation_evidence")
    for case, field, value in [
        ("proof-schema", "schema", "unknown"),
        ("proof-installed", "installed_code_sha", "e" * 40),
        ("proof-execution", "execution_code_sha", "e" * 40),
        ("proof-extra", "extra", True),
    ]:
        if bad == case:
            evidence[field] = value
    manifest = evidence["protocol_files"]
    if bad == "missing-file":
        manifest.pop(i.ACTIVATION_CAPABILITY)
    if bad == "extra-file":
        manifest["src/wea_vnext/extra.py"] = "0" * 64
    if bad == "changed-file":
        manifest["src/wea_vnext/initiatives.py"] = "0" * 64
    if bad.startswith("capability-"):
        package = copy.deepcopy(package)
        package["protocol_files"].pop(i.ACTIVATION_CAPABILITY)
        if bad == "capability-wrong":
            package["protocol_files"][i.ACTIVATION_CAPABILITY] = "0" * 64
        # Keep every package/proof binding valid: only capability admission fails.
        payload["protocol_hash"] = c.digest(package["protocol_files"])
        evidence["protocol_files"] = copy.deepcopy(package["protocol_files"])
        src["body"] = i.MARKER + c.canonical(command).decode()
        src["content_hash"] = c.sha256(src["body"])
        proof["initiative_activation"] = src["content_hash"]
    before = history.state
    state, result = i.decide(
        genesis,
        before,
        history.entries,
        src,
        identities,
        c.json_data(history.now),
        [],
        package,
        proof,
    )
    assert result["status"] == "rejected", bad
    assert state == before


@pytest.mark.parametrize("accepted", [False, True])
def test_historical_prefix_survives_versioned_package(genesis, identities, accepted):
    history = History(genesis, identities, active=accepted)
    if not accepted:
        # Even a future-shaped source/evidence under the old package stays rejected.
        src, proof = request_v2(history)
        assert history.add_source(src, provenance=proof)["status"] == "rejected"
    prefix = copy.deepcopy(history.entries)
    previous_state = history.state
    install_v2(history)
    assert history.state == previous_state
    assert history.entries[: len(prefix)] == prefix
    assert c.replay(genesis, prefix) == previous_state
    if not accepted:
        src, proof = request_v2(history)
        assert history.add_source(src, provenance=proof)["status"] == "recorded"
        assert history.entries[: len(prefix)] == prefix
