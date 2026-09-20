"""DWA-01..06: WEA admission uses Access, public contribution does not."""

from __future__ import annotations

import copy
import hashlib
from datetime import timedelta
from types import SimpleNamespace

import pytest

from wea_vnext import access_control as control
from wea_vnext import access_github
from wea_vnext.engine import installed_executor
from wea_vnext.tide import domain
from wea_vnext.tide.replay import Replay, ReplayError, replay

from . import current_bdd_support as support
from .test_access_runtime import GitAPI, declaration, entry, genesis  # noqa: F401
from .test_tide_ledger import commit, put, repo  # noqa: F401
from .test_tide_replay import batch, bootstrap, command, raw, setup_sources, work


@pytest.fixture
def snapshot(genesis):  # noqa: F811
    genesis = copy.deepcopy(genesis)
    genesis["cutoff"] = control.json_data(support.NOW - timedelta(days=20))
    genesis["activation"]["created_at"] = genesis["cutoff"]
    identities = bootstrap()["identities"]
    for binding in identities["bindings"]:
        binding["effective_from"] = control.json_data(support.NOW - timedelta(days=30))
    entries = []
    # Both grants expire five minutes after the funding cutoff.
    start = support.NOW - timedelta(days=7) + timedelta(minutes=1)
    for number, agent in enumerate(("agent-reviewer", "agent-alpha"), 1):
        src = declaration(
            genesis,
            number=number,
            agent=agent,
            at=start,
            issuer={
                "kind": "operator",
                "subject": str(control.OPERATOR),
                "binding_id": "canonical-operator",
                "binding_version": 1,
            },
        )
        _, item = entry(genesis, identities, src, previous=entries, at=start)
        assert item["decision"]["status"] == "granted", item["decision"]
        entries.append(item)
    return {
        "genesis": genesis,
        "entries": entries,
        "commits": ["a" * 40, "b" * 40],
    }


def domain_batch(engine, sources, cutoff, snapshot, merges=None):
    return {
        **batch(engine, sources, cutoff, merges),
        "schema": domain.SCHEMA,
        "participant_runtime": list(installed_executor("0.10.0").reference),
        "access_snapshot": copy.deepcopy(snapshot),
    }


def funded(snapshot):
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources("circle-1")
    first = domain_batch(engine, sources, cutoff, snapshot)
    state = engine.apply(first)
    assert state["escrow_wea"] == 100, state["dispositions"]
    assert state["domain_scopes"] == {"issue-42": "circle-1"}
    return engine, first, cutoff


def submit(engine, cutoff, snapshot, source=None, *, delay=3, merge=True):
    source = source or work(cutoff + timedelta(minutes=2))
    value = domain_batch(
        engine,
        [source],
        cutoff + timedelta(minutes=delay),
        snapshot,
        {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()} if merge else {},
    )
    return engine.apply(value), value


@pytest.mark.parametrize(
    "scope", [None, "unknown", "Circle-1", "none -->\n<!-- wea:domain circle-1"]
)
def test_dwa01_invalid_scope_cannot_fund(snapshot, scope):
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources(scope)
    state = engine.apply(domain_batch(engine, sources, cutoff, snapshot))
    assert state["escrow_wea"] == 0
    assert state["balances"] == bootstrap()["balances"]
    assert state["dispositions"][sources[0]["revision_id"]]["status"] == "unresolved"


def test_dwa01_internal_scope_needs_no_access():
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources("none")
    engine.apply(domain_batch(engine, sources, cutoff, domain.EMPTY))
    state, _ = submit(engine, cutoff, domain.EMPTY)
    assert state["dispositions"]["work-revision"]["status"] == "accepted"


def test_dwa01_scope_change_invalidates_plan_hash(snapshot):
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources("circle-1")
    sources[0]["body"] = sources[0]["body"].replace(
        "wea:domain circle-1", "wea:domain none"
    )
    sources[0]["content_hash"] = hashlib.sha256(sources[0]["body"].encode()).hexdigest()
    state = engine.apply(domain_batch(engine, sources, cutoff, snapshot))
    assert state["escrow_wea"] == 0


def test_dwa02_active_access_admits_work_and_replays(snapshot):
    engine, first, cutoff = funded(snapshot)
    state, second = submit(engine, cutoff, snapshot)
    assert state["dispositions"]["work-revision"]["status"] == "accepted"
    assert replay(bootstrap(), [first, second]) == state
    assert state["escrow_wea"] == 100  # Access is not acceptance or payment.


def test_dwa01_work_cannot_override_the_plan_scope(snapshot):
    engine, _, cutoff = funded(snapshot)
    source = work(cutoff + timedelta(minutes=2))
    source["body"] = command(
        {
            "kind": "work",
            "agent_id": "agent-alpha",
            "source": source["artifact"]["source"],
            "domain_id": "none",
        }
    )
    source["content_hash"] = hashlib.sha256(source["body"].encode()).hexdigest()
    state, _ = submit(engine, cutoff, snapshot, source)
    assert state["dispositions"]["work-revision"]["status"] == "unresolved"
    assert state["domain_scopes"] == {"issue-42": "circle-1"}
    assert state["tasks"]["issue-42"]["stages"][0]["works"] == []


def test_dwa02_missing_worker_grant_rejects_work(snapshot):
    snapshot["entries"] = snapshot["entries"][:1]
    snapshot["commits"] = snapshot["commits"][:1]
    engine, _, cutoff = funded(snapshot)
    state, _ = submit(engine, cutoff, snapshot)
    assert "active Access" in state["dispositions"]["work-revision"]["reason"]
    assert state["tasks"]["issue-42"]["stages"][0]["works"] == []
    assert state["escrow_wea"] == 100


@pytest.mark.parametrize(
    "offset,allowed", [(-1, False), (0, True), (604799, True), (604800, False)]
)
def test_dwa02_and_04_exact_agent_domain_and_interval(snapshot, offset, allowed):
    access = domain.restore(snapshot, support.NOW, None)
    grant = access.grants[-1]
    at = grant.starts_at + timedelta(seconds=offset)
    if allowed:
        domain.require(access, "circle-1", "agent-alpha", at)
    else:
        with pytest.raises(ValueError, match="active Access"):
            domain.require(access, "circle-1", "agent-alpha", at)
    for target, agent in (("other-domain", "agent-alpha"), ("circle-1", "agent-beta")):
        with pytest.raises(ValueError, match="active Access"):
            domain.require(access, target, agent, at)


@pytest.mark.parametrize("kind", ["duel_join", "work_revision", "role_assignment"])
def test_dwa03_new_entry_checks_subject_not_coordinator(snapshot, kind):
    access = domain.restore(snapshot, support.NOW, None)
    event = SimpleNamespace(
        kind=kind,
        actor_id="agent-beta" if kind != "role_assignment" else "agent0@system",
        payload={"assigned_agent_id": "agent-beta"},
        effective_at=support.NOW,
    )
    with pytest.raises(ValueError, match="agent-beta needs active Access"):
        domain.admit(access, "circle-1", event)


def test_dwa03_unadmitted_triage_assignment_cannot_complete_or_fund(snapshot):
    # A registered worker's grant cannot substitute for the assigned reviewer.
    snapshot["entries"] = []
    snapshot["commits"] = []
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources("circle-1")
    state = engine.apply(domain_batch(engine, sources, cutoff, snapshot))
    assert "active Access" in state["dispositions"][sources[1]["revision_id"]]["reason"]
    assert (
        "admitted assignment"
        in state["dispositions"][sources[3]["revision_id"]]["reason"]
    )
    assert state["escrow_wea"] == 0


def test_dwa03_internal_assignment_cannot_be_reused_after_domain_retry(snapshot):
    snapshot["entries"] = []
    snapshot["commits"] = []
    sources, cutoff = setup_sources("circle-1")
    old = copy.deepcopy(sources[0])
    old["revision_id"] = "old-internal-draft"
    old["body"] = old["body"].replace("circle-1", "none")
    old["content_hash"] = hashlib.sha256(old["body"].encode()).hexdigest()
    at = control.timestamp(old["effective_at"]) - timedelta(minutes=2)
    old["effective_at"] = at.isoformat()
    engine = Replay(bootstrap())
    engine.apply(domain_batch(engine, [old], at, domain.EMPTY))
    engine.apply(domain_batch(engine, sources, cutoff, domain.EMPTY))
    state = engine.apply(
        domain_batch(engine, [], cutoff + timedelta(minutes=1), snapshot)
    )
    assert state["domain_scopes"] == {"issue-42": "circle-1"}
    assert not engine.access.grants
    assert state["escrow_wea"] == 0
    for source in (sources[1], sources[3]):
        assert state["dispositions"][source["revision_id"]]["status"] == "unresolved"


def test_dwa02_later_grant_cannot_authorize_old_source(snapshot):
    original = copy.deepcopy(snapshot)
    snapshot["entries"].pop()
    snapshot["commits"].pop()
    engine, _, cutoff = funded(snapshot)
    state, _ = submit(engine, cutoff, snapshot)
    assert state["dispositions"]["work-revision"]["status"] == "unresolved"
    at = cutoff + timedelta(minutes=4)
    src = declaration(
        snapshot["genesis"],
        number=2,
        agent="agent-alpha",
        at=at,
        issuer=control.request(original["entries"][1]["source"]["body"])["issuer"],
    )
    _, grant = entry(
        snapshot["genesis"],
        original["entries"][1]["identities"],
        src,
        previous=snapshot["entries"],
        at=at,
    )
    assert grant["decision"]["status"] == "granted"
    snapshot["entries"].append(grant)
    snapshot["commits"].append("c" * 40)
    state = engine.apply(domain_batch(engine, [], at, snapshot))
    assert state["dispositions"]["work-revision"]["status"] == "unresolved"


def test_dwa02_access_does_not_replace_funding_or_identity(snapshot):
    engine, _, cutoff = funded(snapshot)
    state, _ = submit(engine, cutoff, snapshot, merge=False)
    assert "funding merge" in state["dispositions"]["work-revision"]["reason"]
    engine, _, cutoff = funded(snapshot)
    source = work(cutoff + timedelta(minutes=2))
    source["actor_account_id"] = "account-beta"
    state, _ = submit(engine, cutoff, snapshot, source)
    assert state["dispositions"]["work-revision"]["status"] == "unresolved"
    assert state["tasks"]["issue-42"]["stages"][0]["works"] == []


def test_dwa04_delayed_valid_source_and_payment_after_expiry(snapshot):
    engine, first, cutoff = funded(snapshot)
    # Grant ends cutoff+5min. Capture and acceptance occur after that endpoint.
    state, second = submit(engine, cutoff, snapshot, delay=6)
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
    state, third = submit(engine, cutoff, snapshot, acceptance, delay=8)
    assert state["balances"]["agent-alpha"] == 20
    assert state["escrow_wea"] == 80
    assert replay(bootstrap(), [first, second, third]) == state


def test_dwa04_new_revision_at_expiry_is_rejected(snapshot):
    engine, _, cutoff = funded(snapshot)
    source = work(cutoff + timedelta(minutes=5))
    state, _ = submit(engine, cutoff, snapshot, source, delay=6)
    assert "active Access" in state["dispositions"]["work-revision"]["reason"]


@pytest.mark.parametrize(
    "kind",
    [
        "role_result",
        "work_acceptance",
        "ranked_order",
        "birdie",
        "mode_expiry",
        "duel_move",
    ],
)
def test_dwa04_existing_obligations_have_no_new_access_gate(kind):
    domain.admit(None, "circle-1", SimpleNamespace(kind=kind))


@pytest.mark.parametrize("mutation", ["missing", "tamper", "future", "short", "commit"])
def test_dwa05_invalid_snapshot_aborts_batch(snapshot, mutation):
    engine, _, cutoff = funded(snapshot)
    value = domain_batch(engine, [], cutoff + timedelta(minutes=2), snapshot)
    damaged = value["access_snapshot"]
    if mutation == "missing":
        del value["access_snapshot"]
    elif mutation == "tamper":
        damaged["entries"][0]["decision"]["grant"]["agent_id"] = "agent-beta"
    elif mutation == "future":
        damaged["entries"][0]["accepted_at"] = control.json_data(
            cutoff + timedelta(days=1)
        )
    elif mutation == "short":
        damaged["entries"].pop()
        damaged["commits"].pop()
    elif mutation == "commit":
        damaged["commits"][0] = "c" * 40
    with pytest.raises(ValueError):
        engine.apply(value)


def test_dwa05_schema_downgrade_is_rejected(snapshot):
    engine, _, cutoff = funded(snapshot)
    with pytest.raises(ReplayError, match="downgrade"):
        engine.apply(batch(engine, [], cutoff + timedelta(minutes=1)))


def test_dwa06_historical_task_keeps_original_scope(snapshot):
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources(None)
    first = batch(engine, sources, cutoff)
    engine.apply(first)
    state, second = submit(engine, cutoff, snapshot)
    assert state["domain_scopes"] == {}
    assert state["dispositions"]["work-revision"]["status"] == "accepted"
    assert replay(bootstrap(), [first, second]) == state


def test_dwa06_plain_public_discussion_does_not_need_scope_or_access():
    engine = Replay(bootstrap())
    source = raw(
        "A useful public proposal", "public", "public", "unregistered", support.NOW
    )
    state = engine.apply(domain_batch(engine, [source], support.NOW, domain.EMPTY))
    assert state["tasks"] == {}
    assert state["dispositions"] == {}
    assert state["balances"] == bootstrap()["balances"]


def journal_api(snapshot):
    api = GitAPI()
    journal = access_github.Journal(api)
    parent = journal.append(None, "genesis.json", snapshot["genesis"])
    for item in snapshot["entries"]:
        parent = journal.append(
            parent, f"decision-{item['source']['object_id']}.json", item
        )
    return api


def test_dwa05_capture_reads_real_journal_objects_and_cutoff(snapshot):
    api = journal_api(snapshot)
    before = copy.deepcopy(api.writes)
    saved = domain.capture(api, support.NOW)
    assert saved["entries"] == snapshot["entries"]
    assert len(saved["commits"]) == 2
    assert api.writes == before
    earlier = domain.capture(api, support.NOW - timedelta(days=8))
    assert earlier["genesis"] == snapshot["genesis"]
    assert earlier["entries"] == earlier["commits"] == []
    assert domain.capture(api, support.NOW - timedelta(days=21)) == domain.EMPTY


def test_dwa05_historical_reader_does_not_require_current_writer_bytes(snapshot):
    # A different installed writer closure cannot break historical Tide replay.
    old = snapshot["genesis"]
    old["protocol_files"]["src/wea_vnext/tide/replay.py"] = "0" * 64
    body = control.strict_json(
        old["activation"]["body"].split(control.ACTIVATION_MARKER)[1]
    )
    body["protocol_hash"] = control.digest(old["protocol_files"])
    old["activation"]["body"] = (
        control.ACTIVATION_MARKER + control.canonical(body).decode()
    )
    old["activation"]["content_hash"] = control.sha256(old["activation"]["body"])
    with pytest.raises(ValueError, match="installed Access closure differs"):
        access_github.validate_genesis(old)
    assert domain.restore(snapshot, support.NOW, None).grants
    api = journal_api(snapshot)
    assert domain.capture(api, support.NOW)["entries"] == snapshot["entries"]
    reader = access_github.Journal(api, verify_closure=False)
    reader.read()
    with pytest.raises(ValueError, match="cannot publish"):
        reader.append(api.ref, "decision-3.json", {})


def test_dwa05_corrupt_or_unavailable_journal_is_not_empty(snapshot):
    class Broken:
        def get(self, path):
            raise OSError("GitHub unavailable")

    with pytest.raises(OSError, match="unavailable"):
        domain.capture(Broken(), support.NOW)
    api = journal_api(snapshot)
    api.objects[api.ref]["parents"] = [{"sha": api.ref}]
    with pytest.raises(ValueError, match="cycle"):
        domain.capture(api, support.NOW)


@pytest.mark.parametrize("tamper", [False, True])
def test_dwa05_guard_recaptures_access_independently(
    request,
    snapshot,
    monkeypatch,
    tamper,
):
    from wea_vnext.tide import ledger

    root, base = request.getfixturevalue("repo")
    journal = journal_api(snapshot)
    sources, cutoff = setup_sources("circle-1")
    captured = domain.capture(journal, cutoff)
    collection = {
        "cutoff": cutoff.isoformat(),
        "sources": sources,
        "tracked_issues": [],
    }
    collection["capture_hash"] = control.digest(ledger.cutoff_evidence(collection))
    payloads = ledger.candidate(
        root,
        base,
        collection,
        {},
        {"run_id": "1", "run_attempt": "1"},
        access_snapshot=captured,
    )
    put(root, payloads)
    head = commit(root)

    class API:
        def get(self, path):
            if path.endswith("git/ref/heads/main"):
                return {"object": {"sha": base}}
            if "/actions/runs/" in path:
                return {
                    "head_sha": base,
                    "path": ".github/workflows/tide.yml",
                    "event": "schedule",
                    "head_branch": "main",
                    "run_started_at": (cutoff - timedelta(minutes=1)).isoformat(),
                    "updated_at": (cutoff + timedelta(minutes=1)).isoformat(),
                }
            return journal.get(path)

        def graphql(self, *args):
            raise AssertionError("collection fixture is injected")

    monkeypatch.setattr(ledger, "collect_sources", lambda *args, **kwargs: collection)
    monkeypatch.setattr(ledger, "retain_artifacts", lambda value, *args: value)
    if tamper:
        journal.ref = None
        with pytest.raises(ReplayError, match="canonical journal"):
            ledger.validate(root, base, head, api=API())
    else:
        assert ledger.validate(root, base, head, api=API())["escrow_wea"] == 100
