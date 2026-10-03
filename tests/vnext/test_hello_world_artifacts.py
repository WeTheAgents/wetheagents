"""Synthetic source-window/enrichment regressions; no live source or money writes."""

import base64
import copy
import hashlib
import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from wea_vnext.tide import domain, ledger
from wea_vnext.tide import hello_world as hw
from wea_vnext.tide.github import GitHubError, retain_artifacts
from wea_vnext.tide.ledger import STATE, candidate, load, validate
from wea_vnext.tide.replay import ReplayError, digest

from .test_hello_world_candidate import NOW, event, native  # noqa: F401
from .test_hello_world_financial import capture, raw
from .test_hello_world_financial import financial as financial_fixture
from .test_tide_ledger import commit, put

financial = financial_fixture

URL = "https://github.com/WeTheAgents/wetheagents/blob/" + "a" * 40 + "/audit.md"
TEXT = b"Synthetic ordinary Work artifact.\n"


def artifact(path):
    assert path.endswith("/contents/audit.md?ref=" + "a" * 40)
    return {
        "type": "file",
        "path": "audit.md",
        "encoding": "base64",
        "content": base64.b64encode(TEXT).decode(),
        "size": len(TEXT),
        "sha": hashlib.sha1(
            b"blob " + str(len(TEXT)).encode() + b"\0" + TEXT,
            usedforsecurity=False,
        ).hexdigest(),
    }


def source_window(financial):
    _, _, n, _, sources = financial
    ordinary = raw(event(n, 4, {}))
    ordinary.update(issue_number=2, issue_id="5000000000")
    ordinary["body"] = "<!-- wea:vnext -->\n" + json.dumps(
        {"kind": "work", "agent_id": "alias@test", "source": URL}
    )
    ordinary["content_hash"] = hashlib.sha256(ordinary["body"].encode()).hexdigest()
    return capture([*sources, ordinary], 10)


def enrich(financial, window, reader=artifact):
    return retain_artifacts(
        window, reader, financial[2].engine.modules["sources"].declaration
    )


def build(financial, captured):
    root, base, n, anchor, _ = financial
    with patch.object(hw, "validate_historical", return_value={"synthetic": True}):
        return candidate(
            root,
            base,
            captured,
            {},
            {"run_id": "1", "run_attempt": "1"},
            access_snapshot=n.engine.access_snapshot or domain.EMPTY,
            hello_world=anchor,
        )


def check_guard(financial, values, window):
    root, base, _, _, _ = financial
    put(root, values)
    head = commit(root)

    class API:
        def get(self, path):
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            if "/actions/runs/" in path:
                return {
                    "head_sha": base,
                    "path": ".github/workflows/tide.yml",
                    "event": "workflow_dispatch",
                    "head_branch": "main",
                    "run_started_at": NOW.isoformat(),
                    "updated_at": (NOW + timedelta(seconds=20)).isoformat(),
                }
            return artifact(path)

        def graphql(self, query, variables):
            raise AssertionError(
                "The fixed synthetic collector window needs no GraphQL"
            )

    # The authenticated collector boundary is a fixed complete synthetic window.
    # The fixture has no real GitHub merge witness or grants; their empty
    # projections are fixed. Artifact reads and exact comparison remain real code.
    with (
        patch.object(hw, "validate_historical", return_value={"synthetic": True}),
        patch.object(hw, "collect_hello_world_sources", return_value=window),
        patch.object(domain, "capture", return_value=domain.EMPTY),
        patch.object(ledger, "funding_merges", return_value={}),
    ):
        assert validate(root, base, head, api=API()) == values[STATE]
    return head


def test_source_hash_before_artifact_enrichment_activates_zero_money_and_reloads(
    financial,
):
    window = source_window(financial)
    original = copy.deepcopy(window)
    enriched = enrich(financial, window)
    assert enriched["capture_hash"] == window["capture_hash"]
    assert digest(hw.collection.cutoff_evidence(enriched)) != window["capture_hash"]
    assert window == original
    assert (
        enriched["sources"][-1]["artifact"]["sha256"]
        == hashlib.sha256(TEXT).hexdigest()
    )
    values = build(financial, enriched)
    state = values[STATE]
    assert state["balances"] == financial[2].engine.balances
    assert state["current_supply"] == 325 and state["escrow_wea"] == 0
    assert not state["hello_world"]["works"] and not state["hello_world"]["decisions"]
    assert state["hello_world"]["mint_intents"] == []
    head = check_guard(financial, values, window)
    assert load(financial[0], head)[0].state() == state


def test_preview_accepts_source_hash_before_artifact_enrichment(financial):
    window = source_window(financial)
    enriched = enrich(financial, window)
    _, base, n, anchor, _ = financial
    packet = {
        "schema": hw.SCHEMA,
        "runtime": anchor["runtime"],
        "checkpoint": anchor["checkpoint"],
        "collection": enriched,
    }
    with patch.object(hw, "validate_historical", return_value={"synthetic": True}):
        result = hw.preview(n.engine, base, packet, root=financial[0])
    assert result["writes"] == 0 and result["supply_wea"] == 325
    assert result["hello_world"]["mint_intents"] == []


@pytest.mark.parametrize("mutation", ["body", "missing-source", "hash", "tracked"])
def test_damaged_or_incomplete_original_window_fails_closed(financial, mutation):
    window = source_window(financial)
    enriched = enrich(financial, window)
    if mutation == "body":
        enriched["sources"][-1]["body"] += " altered"
        enriched["sources"][-1]["content_hash"] = hashlib.sha256(
            enriched["sources"][-1]["body"].encode()
        ).hexdigest()
    elif mutation == "missing-source":
        enriched["sources"].pop()
    elif mutation == "tracked":
        enriched["tracked_issues"] = []
    else:
        enriched["capture_hash"] = "0" * 64
    with pytest.raises(ReplayError, match="complete authenticated collection"):
        build(financial, enriched)


@pytest.mark.parametrize(
    "mutation",
    [
        "artifact-text",
        "artifact-hash",
        "missing-artifact",
        "error",
        "body",
        "missing-source",
    ],
)
def test_trusted_guard_still_checks_complete_sources_and_artifacts(financial, mutation):
    window = source_window(financial)
    changed = copy.deepcopy(window)
    if mutation == "body":
        changed["sources"][-1]["body"] += "\n"
        changed["sources"][-1]["content_hash"] = hashlib.sha256(
            changed["sources"][-1]["body"].encode()
        ).hexdigest()
    elif mutation == "missing-source":
        changed["sources"].pop()
    changed["capture_hash"] = digest(hw.collection.cutoff_evidence(changed))
    enriched = enrich(financial, changed)
    row = enriched["sources"][-1]
    if mutation == "artifact-text":
        row["artifact"]["text"] = "Changed bytes with a matching attacker hash"
        row["artifact"]["sha256"] = hashlib.sha256(
            row["artifact"]["text"].encode()
        ).hexdigest()
    elif mutation == "artifact-hash":
        row["artifact"]["sha256"] = "0" * 64
    elif mutation == "missing-artifact":
        del row["artifact"]
    elif mutation == "error":
        del row["artifact"]
        row["artifact_error"] = "Substituted error cannot hide authenticated artifact"
    values = build(financial, enriched)
    with pytest.raises(ReplayError, match="differs from authenticated GitHub reads"):
        check_guard(financial, values, window)


def test_required_artifact_read_failure_still_aborts_collection(financial):
    def unavailable(path):
        raise GitHubError("GitHub GET failed with HTTP 403")

    with pytest.raises(GitHubError, match="403"):
        enrich(financial, source_window(financial), unavailable)


def test_invalid_artifact_blob_remains_an_error_without_mint(financial):
    def corrupt(path):
        row = artifact(path)
        row["sha"] = "0" * 40
        return row

    enriched = enrich(financial, source_window(financial), corrupt)
    assert enriched["sources"][-1]["artifact_error"] == "artifact Git blob hash differs"
    assert "artifact" not in enriched["sources"][-1]
    state = build(financial, enriched)[STATE]
    assert state["current_supply"] == 325 and state["hello_world"]["mint_intents"] == []
