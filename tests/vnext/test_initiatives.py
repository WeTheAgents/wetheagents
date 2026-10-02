"""LRI-01..07: future policy, synthetic sources, no live activation."""
# ruff: noqa: F811 -- imported pytest fixtures intentionally share argument names

from __future__ import annotations

import copy
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from wea_vnext import access_control as c
from wea_vnext import access_github as g
from wea_vnext import access_protocol as protocol
from wea_vnext import initiatives as i
from wea_vnext.domain_access import make_domain_record
from wea_vnext.tide import domain, ledger
from wea_vnext.tide.github import GitHubError
from wea_vnext.tide.replay import canonical, digest, json_data

from .test_access_runtime import (  # noqa: F401
    ACCOUNT,
    AT,
    GitAPI,
    declaration,
    entry,
    genesis,
    identities,
    source,
)
from .test_tide_domain_admission import snapshot  # noqa: F401
from .test_tide_ledger import commit, put, repo  # noqa: F401

AGENT = {
    "kind": "agent",
    "subject": "Codex-2@codex",
    "binding_id": "codex2",
    "binding_version": 1,
}
NEXT = {**AGENT, "subject": "Codex-19@codex", "binding_id": "codex19"}
OPERATOR = {
    "kind": "operator",
    "subject": ACCOUNT,
    "binding_id": "canonical-operator",
    "binding_version": 1,
}
AGENT0 = {
    "kind": "agent0",
    "subject": "agent0@system",
    "binding_id": "pilot-agent0-role-v1",
    "binding_version": 1,
}
CREATE = {
    "initiative_id": "research",
    "title": "Repository predictability",
    "question": "Which signals predict a safe change?",
    "responsibility": "Maintain the question and reproducible evidence",
    "repositories": [],
}
EVIDENCE = {
    "inputs": "fixed-path fixture revision a",
    "method": "scan and compare",
    "result": "zero files misses source outside the fixed path",
    "limitations": "one synthetic repository; no independent replication",
    "references": ["https://github.com/WeTheAgents/circle-1-old/issues/2"],
    "common_control": "Both local agents share the operator account",
    "downstream_use": [],
}


def package_genesis(genesis):
    value = copy.deepcopy(genesis)
    value["protocol_files"]["src/wea_vnext/initiatives.py"] = hashlib.sha256(
        Path("src/wea_vnext/initiatives.py").read_bytes()
    ).hexdigest()
    activation = c.strict_json(value["activation"]["body"][len(c.ACTIVATION_MARKER) :])
    activation["protocol_hash"] = digest(value["protocol_files"])
    value["activation"]["body"] = c.ACTIVATION_MARKER + canonical(activation).decode()
    value["activation"]["content_hash"] = c.sha256(value["activation"]["body"])
    return value


class History:
    def __init__(self, genesis, identities, *, active=True, old=None, now=AT):
        self.genesis = copy.deepcopy(genesis)
        self.identities = identities
        self.entries = list(old or [])
        self.now = now
        # A real upgrade retains genesis and appends the installed package first.
        files = package_genesis(genesis)["protocol_files"]
        update = {
            "schema": protocol.SCHEMA,
            "previous_protocol_hash": digest(genesis["protocol_files"]),
            "code_sha": "b" * 40,
            "protocol_hash": digest(files),
            "journal_ref": g.REF,
        }
        src = source(
            protocol.MARKER + canonical(update).decode(),
            80,
            self.now - timedelta(microseconds=1),
        )
        self.entries.append(
            {
                "schema": protocol.SCHEMA,
                "source": src,
                "accepted_at": json_data(self.now),
                "code_sha": "b" * 40,
                "protocol_files": files,
                "provenance": {},
                "decision": protocol.decision(genesis, "b" * 40, files),
            }
        )
        if active:
            result = self.add(
                "activate-policy",
                {
                    "policy": i.POLICY,
                    "code_sha": "b" * 40,
                    "protocol_hash": digest(files),
                },
                OPERATOR,
            )
            assert result["status"] == "recorded", result

    @property
    def state(self):
        return c.replay(self.genesis, self.entries)

    def prepare(self, operation, payload, actor=AGENT, request_id=None, at=None):
        command = {
            "schema": i.SCHEMA,
            "request_id": request_id or str(uuid4()),
            "actor": actor,
            "operation": operation,
            "payload": payload,
        }
        return source(
            i.MARKER + canonical(command).decode(),
            100 + len(self.entries),
            at or self.now,
        )

    def add_source(self, src, observations=None, provenance=None, accepted=None):
        command = i.request(src["body"])
        observations = (
            observations
            if observations is not None
            else [
                {
                    "requested_locator": ref["repository_locator"],
                    **ref,
                    **(
                        {"context_revision": command["payload"]["record"]["revision"]}
                        if command["operation"] in {"registry-add", "registry-replace"}
                        else {}
                    ),
                }
                for ref in i.repository_refs(command)
            ]
        )
        provenance = provenance or (
            {
                "workflow": g.WORKFLOW,
                "event": "workflow_dispatch",
                "code_sha": "b" * 40,
                "initiative_activation": src["content_hash"],
            }
            if command["operation"] == "activate-policy"
            else {}
        )
        _, decision = i.decide(
            self.genesis,
            self.state,
            self.entries,
            src,
            self.identities,
            json_data(accepted or self.now),
            observations,
            protocol.package(self.genesis, self.entries),
            provenance,
        )
        self.entries.append(
            {
                "schema": i.SCHEMA,
                "source": src,
                "identities": copy.deepcopy(self.identities),
                "identity_commit": "b" * 40,
                "accepted_at": json_data(accepted or self.now),
                "repositories": observations,
                "provenance": provenance,
                "decision": decision,
            }
        )
        self.now = (accepted or self.now) + timedelta(seconds=1)
        assert canonical(c.replay(self.genesis, self.entries)) == canonical(self.state)
        return decision

    def add(self, operation, payload, actor=AGENT, **kwargs):
        return self.add_source(self.prepare(operation, payload, actor, **kwargs))

    def card_payload(self, **extra):
        return {
            "initiative_id": "research",
            "previous_revision": digest(self.state.initiatives["research"]),
            **extra,
        }

    def create(self):
        assert self.add("create", copy.deepcopy(CREATE))["status"] == "recorded"

    def decision(self, status="active", **extra):
        return self.add(
            "decision",
            self.card_payload(
                status=status,
                reason="reproduced baseline or counterexample",
                next_question="Try an actual change, or retain closure evidence",
                evidence=copy.deepcopy(EVIDENCE),
                tasks=[],
                **extra,
            ),
        )

    def snapshot(self):
        return {
            "genesis": self.genesis,
            "entries": copy.deepcopy(self.entries),
            "commits": [f"{n:040x}" for n in range(1, len(self.entries) + 1)],
        }


@pytest.fixture
def history(genesis, identities):
    return History(genesis, identities)


def test_lri01_default_steward_activation_without_financial_effect(history):
    before = json_data(history.state.grants)
    history.create()
    assert history.decision()["status"] == "recorded"
    card = history.state.initiatives["research"]
    assert card["steward"] == card["proposer"] == "Codex-2@codex"
    assert card["status"] == "active"
    assert json_data(history.state.grants) == before
    assert set(card) == {
        "initiative_id",
        "title",
        "question",
        "proposer",
        "steward",
        "status",
        "revision",
        "participants",
        "repositories",
        "decisions",
        "handoff",
    }


@pytest.mark.parametrize(
    "bad",
    [
        "account",
        "binding",
        "edited",
        "hash",
        "purpose",
        "participant",
        "repository",
        "boundary",
    ],
)
def test_lri01_invalid_source_has_no_effect(history, bad):
    payload = copy.deepcopy(CREATE)
    if bad == "purpose":
        payload["question"] = ""
    if bad == "participant":
        payload["participants"] = {"Codex-19@codex": "unconsenting"}
    if bad == "repository":
        payload["repositories"] = [
            {
                "repository_id": "other",
                "repository_locator": "https://github.com/WeTheAgents/circle-1",
            }
        ]
    src = history.prepare("create", payload)
    if bad == "account":
        src["original_author_account_id"] = "other"
        src["actor_account_id"] = "other"
    elif bad == "binding":
        command = i.request(src["body"])
        command["actor"]["binding_id"] = "wrong"
        src["body"] = i.MARKER + canonical(command).decode()
        src["content_hash"] = c.sha256(src["body"])
    elif bad == "edited":
        src["edit_history"] = ["edit"]
    elif bad == "hash":
        src["content_hash"] = "0" * 64
    elif bad == "boundary":
        src["created_at"] = json_data(AT - timedelta(seconds=1))
    before = canonical(history.state)
    observed = (
        [
            {
                "requested_locator": payload["repositories"][0]["repository_locator"],
                "repository_id": "mismatch",
                "repository_locator": payload["repositories"][0]["repository_locator"],
            }
        ]
        if bad == "repository"
        else []
    )
    assert history.add_source(src, observed)["status"] == "rejected"
    assert canonical(history.state) == before


def test_lri02_evidence_and_task_link_are_metadata(history):
    history.create()
    payload = history.card_payload(
        status="active",
        reason="counterexample changes the approach",
        next_question="Does this explain an actual patch?",
        evidence=EVIDENCE,
        tasks=["https://github.com/WeTheAgents/wetheagents/issues/1016"],
    )
    before = (history.state.registry, history.state.grants)
    assert history.add("decision", payload)["status"] == "recorded"
    assert (history.state.registry, history.state.grants) == before
    assert (
        history.state.initiatives["research"]["decisions"][-1]["payload"]["evidence"]
        == EVIDENCE
    )
    for bad in (
        {"reports": 5},
        {**EVIDENCE, "method": ""},
        {**EVIDENCE, "common_control": ""},
    ):
        payload = {**payload, **history.card_payload(), "evidence": bad}
        assert history.add("decision", payload)["status"] == "rejected"


def test_lri03_exact_handoff_consent_and_previous_steward(history):
    history.create()
    before = history.state.grants
    payload = history.card_payload(
        next_steward=NEXT["subject"], reason="consenting successor"
    )
    assert history.add("handoff-propose", payload)["status"] == "recorded"
    proposal = history.state.initiatives["research"]["handoff"]
    consent = history.card_payload(proposal_hash=digest(proposal))
    assert history.add("handoff-consent", consent, AGENT)["status"] == "rejected"
    assert (
        history.add("handoff-consent", {**consent, "proposal_hash": "0" * 64}, NEXT)[
            "status"
        ]
        == "rejected"
    )
    assert history.add("handoff-consent", consent, NEXT)["status"] == "recorded"
    assert history.state.initiatives["research"]["steward"] == NEXT["subject"]
    assert history.decision()["status"] == "rejected"
    assert history.state.grants == before


def test_lri03_operator_resolution_still_needs_new_consent(history):
    history.create()
    assert (
        history.add("leave", history.card_payload(reason="lost predecessor"))["status"]
        == "recorded"
    )
    assert (
        history.add(
            "handoff-propose",
            history.card_payload(
                next_steward=NEXT["subject"], reason="resolve vacancy"
            ),
            OPERATOR,
        )["status"]
        == "recorded"
    )
    card = history.state.initiatives["research"]
    assert card["steward"] is None and card["handoff"]["operator_resolution"]
    assert (
        history.add(
            "handoff-consent",
            history.card_payload(proposal_hash=digest(card["handoff"])),
            NEXT,
        )["status"]
        == "recorded"
    )
    assert history.state.initiatives["research"]["status"] == "paused"


def replacement(history, repository_id="R_new_repository", domain_id="circle-1"):
    record = make_domain_record(
        domain_id=domain_id,
        repository_id=repository_id,
        repository_locator="https://github.com/WeTheAgents/new-circle",
        revision="d" * 40,
    )
    return {
        "previous_registry": history.state.registry.registry_hash,
        "record": record.to_mapping(),
        "reason": "exact repository transition",
    }


def test_lri04_registry_revisions_rename_and_protected_replacement(history):
    original = history.state.registry
    payload = replacement(history)
    assert history.add("registry-replace", payload, AGENT0)["status"] == "rejected"
    assert history.add("registry-replace", payload, OPERATOR)["status"] == "recorded"
    assert history.state.groups[0].registry == original
    assert history.state.registry.domain("circle-1").repository_id == "R_new_repository"
    assert history.add("registry-replace", payload, OPERATOR)["status"] == "rejected"
    before = history.state.registry
    observe = replacement(history)
    observations = [
        {
            "requested_locator": observe["record"]["repository_locator"],
            "repository_id": "R_new_repository",
            "repository_locator": "https://github.com/WeTheAgents/renamed-circle",
        }
    ]
    assert (
        history.add_source(
            history.prepare("repository-observe", observe), observations
        )["status"]
        == "recorded"
    )
    assert history.state.registry == before
    assert (
        history.add(
            "registry-add", replacement(history, "R_additional", "new-domain"), AGENT0
        )["status"]
        == "recorded"
    )


@pytest.mark.parametrize("status", ["paused", "archived"])
def test_lri05_lifecycle_has_no_repository_or_obligation_effect(history, status):
    history.create()
    history.decision()
    before = (history.state.registry, history.state.grants)
    assert history.decision(status)["status"] == "recorded"
    with pytest.raises(ValueError, match="active Steward"):
        history.state.assignable("research", history.now)
    assert (history.state.registry, history.state.grants) == before
    assert history.decision()["status"] == "recorded"
    history.state.assignable("research", history.now)


def test_lri05_vacancy_blocks_new_participation(history):
    history.create()
    history.decision()
    history.add("leave", history.card_payload(reason="no successor"))
    card = history.state.initiatives["research"]
    assert card["steward"] is None and card["status"] == "paused"
    assert (
        history.add(
            "participate", history.card_payload(responsibility="new task"), NEXT
        )["status"]
        == "rejected"
    )
    assert history.decision()["status"] == "rejected"


def test_lri06_binding_a_never_authorizes_binding_b(genesis, identities):
    _, old = entry(
        genesis,
        identities,
        declaration(genesis, at=AT - timedelta(seconds=30)),
        at=AT - timedelta(seconds=30),
    )
    history = History(genesis, identities, old=[old])
    old_grant = history.state.grants[0]
    old_record = history.state.binding("circle-1")
    before_replace = history.now
    history.now += timedelta(seconds=10)
    assert (
        history.add("registry-replace", replacement(history), OPERATOR)["status"]
        == "recorded"
    )
    record = history.state.binding("circle-1")
    old_scope = {"domain_id": "circle-1", "binding_revision": old_record.record_hash}
    new_scope = {"domain_id": "circle-1", "binding_revision": record.record_hash}
    domain.require(history.state, old_scope, old_grant.agent_id, history.now)
    with pytest.raises(ValueError, match="needs active Access"):
        domain.require(history.state, new_scope, old_grant.agent_id, history.now)
    body = (
        f"<!-- wea:domain circle-1 -->\n<!-- wea:binding {old_record.record_hash} -->"
    )
    assert domain.scope(body, history.state, before_replace) == old_scope
    with pytest.raises(ValueError, match="binding differs"):
        domain.scope(body, history.state, history.now)
    grant = {
        "agent_id": old_grant.agent_id,
        "domain_id": "circle-1",
        "issuer": AGENT0,
        "registry_hash": history.state.registry.registry_hash,
        "binding_revision": record.record_hash,
    }
    assert history.add("grant", grant, AGENT0)["status"] == "rejected"
    history.now = old_grant.ends_at
    assert history.add("grant", grant, AGENT0)["status"] == "granted"
    new_grant = history.state.grants[-1]
    assert new_grant.starts_at == old_grant.ends_at
    assert new_grant.ends_at - new_grant.starts_at == timedelta(seconds=604800)
    assert history.state.grants[0] == old_grant
    domain.require(history.state, new_scope, old_grant.agent_id, new_grant.starts_at)
    with pytest.raises(ValueError):
        domain.require(
            history.state,
            new_scope,
            old_grant.agent_id,
            new_grant.starts_at - timedelta(microseconds=1),
        )


def test_lri07_exact_retry_conflict_and_replay_prefix(history):
    src = history.prepare("create", CREATE)
    result = history.add_source(src)
    retry = history.prepare(
        "create", CREATE, request_id=result["request"]["request_id"]
    )
    assert history.add_source(retry)["duplicate_of"] == src["object_id"]
    conflict = history.prepare(
        "create",
        {**CREATE, "question": "different"},
        request_id=result["request"]["request_id"],
    )
    assert history.add_source(conflict)["status"] == "rejected"
    snapshot = history.snapshot()
    restored = domain.restore(snapshot, history.now, None)
    assert canonical(restored) == canonical(history.state)
    lost = {
        **snapshot,
        "entries": snapshot["entries"][1:],
        "commits": snapshot["commits"][1:],
    }
    with pytest.raises(ValueError, match="lost retained history"):
        domain.restore(lost, history.now, snapshot)


def test_lri07_metadata_does_not_create_tide_batch_but_later_prefix_is_complete(
    history, request
):
    root, base = request.getfixturevalue("repo")
    snapshot = history.snapshot()
    collection = {"sources": [], "cutoff": json_data(history.now), "tracked_issues": []}
    first = ledger.candidate(root, base, collection, {}, {}, access_snapshot=snapshot)
    assert first is not None and first[ledger.STATE]["schema"] == "wea-tide-state-4"
    put(root, first)
    head = commit(root)
    ledger.validate(root, base, head)
    history.create()
    history.decision()
    collection["cutoff"] = json_data(history.now)
    assert (
        ledger.candidate(
            root, head, collection, {}, {}, access_snapshot=history.snapshot()
        )
        is None
    )
    history.add(
        "registry-add", replacement(history, "R_additional", "new-domain"), AGENT0
    )
    collection["cutoff"] = json_data(history.now)
    second = ledger.candidate(
        root, head, collection, {}, {}, access_snapshot=history.snapshot()
    )
    assert second is not None
    batch = next(v for k, v in second.items() if k.startswith(ledger.JOURNAL))
    assert batch["access_snapshot"]["entries"] == history.entries
    assert second[ledger.STATE]["balances"] == first[ledger.STATE]["balances"]
    assert second[ledger.STATE]["escrow_wea"] == 0


@pytest.mark.parametrize("bad", ["dispatch", "package", "operator", "before-policy"])
def test_lri07_activation_is_a_separate_exact_gate(genesis, identities, bad):
    history = History(genesis, identities, active=False)
    if bad == "before-policy":
        assert history.add("create", CREATE)["status"] == "rejected"
        return
    payload = {
        "policy": i.POLICY,
        "code_sha": history.genesis["code_sha"],
        "protocol_hash": digest(
            protocol.package(history.genesis, history.entries)["protocol_files"]
        ),
    }
    if bad == "package":
        payload["protocol_hash"] = "0" * 64
    src = history.prepare(
        "activate-policy", payload, AGENT if bad == "operator" else OPERATOR
    )
    provenance = {"event": "issue_comment"} if bad == "dispatch" else None
    assert history.add_source(src, provenance=provenance)["status"] == "rejected"
    assert not isinstance(history.state, i.State)


def test_lri07_journal_lost_response_readonly_failure_and_race(history):
    api = GitAPI()
    journal = g.Journal(api)
    journal.append(None, "genesis.json", history.genesis)
    for item in history.entries:
        head = journal.head()
        prefix = "protocol" if item["schema"] == protocol.SCHEMA else "decision"
        journal.append(head, f"{prefix}-{item['source']['object_id']}.json", item)
    src = history.prepare("create", CREATE)
    api.after_publish = True
    result = g.process(api, src, history.identities, "b" * 40, {}, lambda: history.now)
    assert result["status"] == "recorded"
    head, genesis, entries, commits = g.Journal(api).read()
    assert len(entries) == 3
    assert (
        g.process(api, src, history.identities, "b" * 40, {}, lambda: history.now)[
            "revision"
        ]
        == result["revision"]
    )
    src2 = history.prepare("create", {**CREATE, "initiative_id": "another"})
    src2["object_id"] = "200"
    readonly = g.Journal(api, verify_closure=False)
    with pytest.raises(ValueError, match="historical Access readers"):
        g.process(
            api,
            src2,
            history.identities,
            "b" * 40,
            {},
            lambda: history.now,
            journal=readonly,
        )
    assert g.Journal(api).head() == head
    api.before_publish = True
    with pytest.raises(GitHubError, match="unresolved"):
        g.process(api, src2, history.identities, "b" * 40, {}, lambda: history.now)
    api.before_publish = False
    assert g.Journal(api).head() == head
    assert canonical(c.replay(genesis, entries)) == canonical(
        domain.restore(
            {"genesis": genesis, "entries": entries, "commits": commits},
            history.now,
            None,
        )
    )


def test_lri07_concurrent_winner_requires_fresh_replay(history):
    api = GitAPI()
    journal = g.Journal(api)
    journal.append(None, "genesis.json", history.genesis)
    for item in history.entries:
        prefix = "protocol" if item["schema"] == protocol.SCHEMA else "decision"
        journal.append(
            journal.head(), f"{prefix}-{item['source']['object_id']}.json", item
        )
    command = i.request(history.prepare("create", CREATE)["body"])
    winner = source(i.MARKER + canonical(command).decode(), 201, history.now)
    loser = history.prepare("create", CREATE)
    api.rival = lambda: g.process(
        api, winner, history.identities, "b" * 40, {}, lambda: history.now
    )
    result = g.process(
        api, loser, history.identities, "b" * 40, {}, lambda: history.now
    )
    assert result["status"] == "rejected" and "initiative exists" in result["reason"]
    _, _, entries, _ = g.Journal(api).read()
    assert len(entries) == 4
    assert sum(e["decision"].get("effect") == "create" for e in entries) == 1
    assert all(
        "/collaborators" not in path and "archive" not in path
        for _, path, _ in api.writes
    )


def test_lri04_repository_id_read_failure_and_locator_reuse_fail_closed(
    history, monkeypatch
):
    api = GitAPI()
    journal = g.Journal(api)
    journal.append(None, "genesis.json", history.genesis)
    for item in history.entries:
        prefix = "protocol" if item["schema"] == protocol.SCHEMA else "decision"
        journal.append(
            journal.head(), f"{prefix}-{item['source']['object_id']}.json", item
        )
    payload = {
        **CREATE,
        "repositories": [
            {
                "repository_id": "R_expected",
                "repository_locator": "https://github.com/WeTheAgents/circle-1",
            }
        ],
    }
    src = history.prepare("create", payload)
    head = journal.head()
    original = api.get

    def failure(path):
        if path == "https://api.github.com/repos/WeTheAgents/circle-1":
            raise GitHubError("required repository read unavailable")
        return original(path)

    monkeypatch.setattr(api, "get", failure)
    with pytest.raises(GitHubError, match="required repository read"):
        g.process(api, src, history.identities, "b" * 40, {}, lambda: history.now)
    assert journal.head() == head

    def reused(path):
        if path == "https://api.github.com/repos/WeTheAgents/circle-1":
            return {
                "id": 999,
                "node_id": "R_other",
                "full_name": "WeTheAgents/circle-1",
            }
        return original(path)

    monkeypatch.setattr(api, "get", reused)
    result = g.process(api, src, history.identities, "b" * 40, {}, lambda: history.now)
    assert (
        result["status"] == "rejected" and "repository ID differs" in result["reason"]
    )
    assert not g.Journal(api).read()[1].get("initiatives")


def test_lri05_old_funded_work_and_acceptance_survive_archive(request):
    from wea_vnext.engine import installed_executor

    from .test_tide_domain_admission import funded
    from .test_tide_replay import command, raw, work

    snapshot = request.getfixturevalue("snapshot")
    engine, _, cutoff = funded(snapshot)
    identities = snapshot["entries"][0]["identities"]
    history = History(
        snapshot["genesis"],
        identities,
        old=snapshot["entries"],
        now=cutoff + timedelta(seconds=1),
    )
    # The registered proposer owns only initiative metadata.
    proposer = {
        "kind": "agent",
        "subject": "agent-alpha",
        "binding_id": "alpha",
        "binding_version": 1,
    }
    binding = next(
        b
        for b in identities["bindings"]
        if b["actor_kind"] == "agent" and b["subject_id"] == "agent-alpha"
    )
    proposer.update(
        binding_id=binding["binding_id"], binding_version=binding["version"]
    )

    def declared(op, payload):
        src = history.prepare(op, payload, proposer)
        src.update(
            actor_account_id=binding["github_account_id"],
            original_author_account_id=binding["github_account_id"],
        )
        return history.add_source(src)

    assert declared("create", CREATE)["status"] == "recorded"
    for status in ("active", "archived"):
        payload = history.card_payload(
            status=status,
            reason="retain old obligations",
            next_question="retain closure evidence",
            evidence=EVIDENCE,
            tasks=[],
        )
        assert declared("decision", payload)["status"] == "recorded"
    assert history.genesis == snapshot["genesis"]
    assert history.entries[: len(snapshot["entries"])] == snapshot["entries"]
    later = history.snapshot()
    later["commits"][: len(snapshot["commits"])] = snapshot["commits"]

    def apply(sources, minutes):
        from .test_tide_replay import batch

        value = {
            **batch(
                engine,
                sources,
                cutoff + timedelta(minutes=minutes),
                {"tide-1": json_data(cutoff + timedelta(minutes=1))},
            ),
            "schema": domain.REVISION_SCHEMA,
            "access_snapshot": later,
            "participant_runtime": list(installed_executor("0.10.0").reference),
        }
        return engine.apply(value)

    state = apply([work(cutoff + timedelta(minutes=2))], 6)
    assert state["dispositions"]["work-revision"]["status"] == "accepted"
    stage = state["tasks"]["issue-42"]["stages"][0]
    item = stage["works"][0]
    acceptance = raw(
        command(
            {
                "kind": "lifecycle",
                "event": "work_acceptance",
                "actor_kind": "author",
                "actor_id": "agent-author",
                "plan_id": state["tasks"]["issue-42"]["plan_id"],
                "payload": {
                    "contract_id": stage["contract"]["contract_id"],
                    "work_id": item["work_id"],
                    "revision_id": item["revisions"][0]["revision_id"],
                    "novel": None,
                    "verdict": "accept",
                },
            }
        ),
        "accept",
        "accept-revision",
        "account-author",
        cutoff + timedelta(minutes=7),
    )
    state = apply([acceptance], 8)
    assert state["balances"]["agent-alpha"] == 20 and state["escrow_wea"] == 80
    assert (
        sum(state["balances"].values()) + state["escrow_wea"] == state["opening_supply"]
    )


def test_lri06_delayed_legacy_body_and_global_cross_domain_overlap(history):
    # A historical marker cannot reinterpret a previously accepted Draft body.
    assert (
        domain.initiative_scope(
            "<!-- wea:initiative research -->",
            history.state,
            history.state.activation_at,
        )
        is None
    )
    history.add(
        "registry-add", replacement(history, "R_additional", "new-domain"), AGENT0
    )

    def grant(domain_id):
        return {
            "agent_id": "Codex-2@codex",
            "domain_id": domain_id,
            "issuer": AGENT0,
            "registry_hash": history.state.registry.registry_hash,
            "binding_revision": history.state.binding(domain_id).record_hash,
        }

    assert history.add("grant", grant("circle-1"), AGENT0)["status"] == "granted"
    assert history.add("grant", grant("new-domain"), AGENT0)["status"] == "rejected"


def test_lri01_readonly_cli_exposes_exact_card_and_registry(history):
    from argparse import Namespace

    from wea_cli import access as cli
    from wea_cli.cli import build_parser, is_readonly_command

    history.create()
    api = GitAPI()
    journal = g.Journal(api)
    journal.append(None, "genesis.json", history.genesis)
    for item in history.entries:
        prefix = "protocol" if item["schema"] == protocol.SCHEMA else "decision"
        journal.append(
            journal.head(), f"{prefix}-{item['source']['object_id']}.json", item
        )
    writes = len(api.writes)
    read = cli.read(api, Namespace(initiative="research"), ACCOUNT)
    assert read["revision"] == digest(read["initiative"])
    assert read["initiative"]["steward"] == "Codex-2@codex"
    read = cli.read(api, Namespace(registry=True), ACCOUNT)
    assert read["registry"] == history.state.registry.to_mapping()
    assert len(api.writes) == writes
    for argv in (
        ["access", "show", "--registry"],
        ["access", "show", "--initiative", "research"],
    ):
        args = build_parser().parse_args(argv)
        assert is_readonly_command("access", args)


def test_lri04_missing_context_revision_rejects_registry_update(history):
    payload = replacement(history)
    observed = [
        {
            "requested_locator": payload["record"]["repository_locator"],
            "repository_id": payload["record"]["repository_id"],
            "repository_locator": payload["record"]["repository_locator"],
            "context_revision": "0" * 40,
        }
    ]
    before = history.state.registry
    result = history.add_source(
        history.prepare("registry-replace", payload, OPERATOR), observed
    )
    assert (
        result["status"] == "rejected"
        and "context revision differs" in result["reason"]
    )
    assert history.state.registry == before


def test_lri01_lri04_reference_revision_preserves_domain_and_grants(history):
    history.create()
    before = (history.state.registry, history.state.grants)
    refs = [
        {
            "repository_id": "R_reference",
            "repository_locator": "https://github.com/WeTheAgents/research-reference",
        }
    ]
    payload = history.card_payload(
        repositories=refs, reason="retain a new research input"
    )
    assert history.add("references", payload, NEXT)["status"] == "rejected"
    assert history.add("references", payload)["status"] == "recorded"
    assert history.state.initiatives["research"]["repositories"] == refs
    assert (history.state.registry, history.state.grants) == before
    assert history.add("references", payload)["status"] == "rejected"
    payload = history.card_payload(repositories=refs, reason="mismatched ID")
    observed = [
        {
            "requested_locator": refs[0]["repository_locator"],
            "repository_id": "R_other",
            "repository_locator": refs[0]["repository_locator"],
        }
    ]
    assert (
        history.add_source(history.prepare("references", payload), observed)["status"]
        == "rejected"
    )
    assert history.state.initiatives["research"]["repositories"] == refs


@pytest.mark.parametrize("status", ["active", "paused"])
def test_lri01_lri05_new_draft_requires_active_registered_steward(request, status):
    from wea_vnext.engine import installed_executor
    from wea_vnext.tide.replay import Replay

    from .test_tide_replay import MARKER, batch, bootstrap, command, setup_sources

    snapshot = request.getfixturevalue("snapshot")
    sources, cutoff = setup_sources("circle-1")
    created = c.timestamp(sources[0]["effective_at"])
    identities = snapshot["entries"][0]["identities"]
    history = History(
        snapshot["genesis"],
        identities,
        old=snapshot["entries"],
        now=created - timedelta(minutes=2),
    )
    binding = next(
        b
        for b in identities["bindings"]
        if b["actor_kind"] == "agent" and b["subject_id"] == "agent-alpha"
    )
    proposer = {
        "kind": "agent",
        "subject": "agent-alpha",
        "binding_id": binding["binding_id"],
        "binding_version": binding["version"],
    }

    def declared(op, payload):
        src = history.prepare(op, payload, proposer)
        src.update(
            actor_account_id=binding["github_account_id"],
            original_author_account_id=binding["github_account_id"],
        )
        return history.add_source(src)

    assert declared("create", CREATE)["status"] == "recorded"
    assert (
        declared(
            "decision",
            history.card_payload(
                status=status,
                reason="bounded new task assignment",
                next_question="test a real change",
                evidence=EVIDENCE,
                tasks=[],
            ),
        )["status"]
        == "recorded"
    )
    record = history.state.binding("circle-1")
    sources[0]["body"] = (
        f"<!-- wea:binding {record.record_hash} -->\n"
        "<!-- wea:initiative research -->\n" + sources[0]["body"]
    )
    body_hash = c.sha256(sources[0]["body"])
    plan_hash = None
    for src in sources[1:]:
        data = json.loads(src["body"][len(MARKER) :])
        if "body_hash" in data:
            data["body_hash"] = body_hash
        if data["kind"] == "resolution_plan_revision":
            plan_hash = digest({k: v for k, v in data.items() if k != "kind"})
        if "plan_content_hash" in data:
            data["plan_content_hash"] = plan_hash
        src["body"] = command(data)
    for src in sources:
        src["content_hash"] = c.sha256(src["body"])
    engine = Replay(bootstrap())
    value = {
        **batch(engine, sources, cutoff),
        "schema": domain.REVISION_SCHEMA,
        "access_snapshot": history.snapshot(),
        "participant_runtime": list(installed_executor("0.10.0").reference),
    }
    state = engine.apply(value)
    if status == "active":
        assert state["escrow_wea"] == 100, state["dispositions"]
        assert state["domain_scopes"]["issue-42"] == {
            "domain_id": "circle-1",
            "binding_revision": record.record_hash,
        }
        assert state["initiative_scopes"]["issue-42"] == "research"
    else:
        assert state["escrow_wea"] == 0
        assert (
            "active Steward"
            in state["dispositions"][sources[0]["revision_id"]]["reason"]
        )
