"""Real schema-5 transactions; every API/source/time is synthetic test evidence."""

import hashlib
import json
import subprocess
from datetime import timedelta

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.tide import domain
from wea_vnext.tide import hello_world as hw
from wea_vnext.tide.ledger import (
    BOOTSTRAP,
    STATE,
    load,
    validate,
)
from wea_vnext.tide.ledger import (
    candidate as build_candidate,
)
from wea_vnext.tide.replay import Replay, ReplayError, canonical, digest

from .test_hello_world_candidate import NOW, acceptance, event, native  # noqa: F401
from .test_initiatives import genesis, history, identities  # noqa: F401
from .test_tide_ledger import commit, put
from .test_tide_participants import declarations

EMPTY = {"genesis": None, "entries": [], "commits": []}


def raw(e):
    return {
        "repository_id": e.repository_id,
        "object_kind": e.object_kind,
        "object_id": e.object_id,
        "revision_id": e.revision_id,
        "effective_at": e.effective_at.isoformat(),
        "body": e.body,
        "content_hash": e.content_hash,
        "actor_account_id": e.actor_account_id,
        **json.loads(canonical(e.payload)),
    }


def capture(sources, seconds, tracked=(1,)):
    value = {
        "schema": "wea-tide-collection-1",
        "repository_id": "1171421025",
        "cutoff": (NOW + timedelta(seconds=seconds)).isoformat(),
        "sources": sources,
        "tracked_issues": list(tracked),
    }
    value["capture_hash"] = digest(hw.collection.cutoff_evidence(value))
    return value


@pytest.fixture
def financial(tmp_path, native, request):  # noqa: F811
    subprocess.run(["git", "init", "-q", "-b", "test", str(tmp_path)], check=True)
    initial = {
        "runtime": list(installed_executor("0.9.0").reference),
        "repository_id": "1171421025",
        "identities": native.registry.to_data(),
        "balances": {"base@test": 100, "second@test": 200, "treasury": 25},
        "legacy_files": {},
    }
    opening_identities = initial["identities"]
    opening_identities["accounts"].append(
        {
            "github_account_id": "265255605",
            "owner": "CursorWEA",
            "base_agent_id": "legacy@test",
        }
    )
    opening_identities["bindings"].append(
        {
            "binding_id": "legacy-owner",
            "actor_kind": "agent",
            "github_account_id": "265255605",
            "subject_id": "legacy@test",
            "version": 1,
            "effective_from": NOW.isoformat(),
            "effective_until": None,
        }
    )
    opening_identities["control_group_bindings"].append(
        {
            "binding_id": "legacy-group",
            "agent_id": "legacy@test",
            "control_group_id": "legacy-control",
            "version": 1,
            "effective_from": NOW.isoformat(),
            "effective_until": None,
        }
    )
    put(tmp_path, {BOOTSTRAP: initial, STATE: Replay(initial).state()})
    base = commit(tmp_path)
    # Establish an actual canonical cutoff before a synthetic installation event.
    engine = Replay(initial)
    access = (
        request.getfixturevalue("history").snapshot()
        if getattr(request, "param", None) == "binding"
        else EMPTY
    )
    core = {
        "schema": domain.batch_schema(access),
        "participant_runtime": list(installed_executor("0.10.0").reference),
        "access_snapshot": access,
        "sequence": 1,
        "previous_hash": None,
        "repository_id": "1171421025",
        "predecessor": base,
        "collection": capture([], 0, ()),
        "funding_merges": {},
    }
    core["previous_hash"] = engine.last_hash
    batch = {**core, "batch_id": "tide:" + digest(core)}
    put(
        tmp_path,
        {"ledger/vnext/tides/0000000000000001.json": batch, STATE: engine.apply(batch)},
    )
    base = commit(tmp_path)
    native.engine = load(tmp_path, base)[0]
    anchor = hw.prepare_anchor(native.engine, base, "github:TEST-installation:created")
    native.checkpoint = anchor["checkpoint"]
    issue = event(native, 1, None, "129645949", issue=True)
    install = raw(event(native, 2, {}, "129645949"))
    install["revision_id"] = anchor["installation_revision_id"]
    install["body"] = hw.INSTALLATION_MARKER + json.dumps(
        {
            "schema": "wea-hello-world-installation-1",
            "runtime": anchor["runtime"],
            "checkpoint": anchor["checkpoint"],
        }
    )
    install["content_hash"] = hashlib.sha256(install["body"].encode()).hexdigest()
    activate = event(
        native,
        3,
        {
            "kind": "hello_world_activation",
            "checkpoint": native.checkpoint,
            "runtime": list(native.reference),
            "issue_revision_id": issue.revision_id,
            "body_hash": native.source.BODY_HASH,
            "attestation_hash": native.source.ATTESTATION_HASH,
        },
        "129645949",
    )
    return tmp_path, base, native, anchor, [raw(issue), install, raw(activate)]


def build(financial, sources, seconds=10, *, base=None, anchor=True, merges=None):
    root, start, _, point, _ = financial
    # Fixture repositories lack the historical Git witness; validate it separately
    # against the real checkout, then use the actual validator result in this adapter.
    from unittest.mock import patch

    with patch.object(
        hw, "validate_historical", return_value={"synthetic_fixture": True}
    ):
        return build_candidate(
            root,
            base or start,
            capture(
                sources,
                seconds,
                sorted(
                    {1}
                    | {
                        r["issue_number"]
                        for r in load(root, base or start)[0].sources.values()
                    }
                ),
            ),
            merges or {},
            {"run_id": "TEST", "run_attempt": "1"},
            access_snapshot=load(root, base or start)[0].access_snapshot or EMPTY,
            hello_world=point if anchor else None,
        )


def transact(financial, sources, seconds=10, *, base=None, anchor=True, merges=None):
    root, start, _, _, _ = financial
    values = build(financial, sources, seconds, base=base, anchor=anchor, merges=merges)
    assert values is not None
    put(root, values)
    head = commit(root)
    from unittest.mock import patch

    with patch.object(
        hw, "validate_historical", return_value={"synthetic_fixture": True}
    ):
        assert validate(root, base or start, head) == values[STATE]
    assert load(root, head)[0].state() == values[STATE]
    return head, values[STATE]


def greeting(n, num=4, actor="1001", agent="alias@test", text="Unique financial test"):
    return event(
        n, num, {"kind": "hello_world_work", "agent_id": agent, "greeting": text}, actor
    )


def test_actual_financial_adapter_serialized_guard_reload_retry_and_alias(financial):
    root, base, n, _, sources = financial
    before = (root / BOOTSTRAP).read_bytes()
    work = greeting(n)
    sources += [raw(work), raw(acceptance(n, work, 5))]
    head, state = transact(financial, sources)
    assert state["schema"] == "wea-tide-state-5"
    assert state["balances"]["base@test"] == 142
    assert state["balances"].get("alias@test", 0) == 0
    assert state["opening_supply"] == 325
    assert state["current_supply"] == 367
    assert sum(state["balances"].values()) + state["escrow_wea"] == 367
    assert build(financial, sources, 20, base=head, anchor=False) is None
    alias = greeting(n, 21, agent="base@test", text="Another alias greeting")
    sources += [raw(alias), raw(acceptance(n, alias, 22))]
    second, state2 = transact(financial, sources, 30, base=head, anchor=False)
    assert state2["balances"] == state["balances"]
    assert state2["current_supply"] == 367
    assert (root / BOOTSTRAP).read_bytes() == before
    assert load(root, second)[0].state() == state2
    # Competing candidates have the same predecessor; stale direct-child guard fails.
    with pytest.raises(ReplayError, match="direct child"):
        validate(root, base, second)


@pytest.mark.parametrize(
    "mutation", ["owner", "role", "rejected", "duplicate", "before-admission", "edited"]
)
def test_new_invalid_financial_sources_do_not_mint(financial, mutation):
    _, _, n, _, sources = financial
    work = greeting(n)
    decision = acceptance(n, work, 5)
    if mutation == "owner":
        work = greeting(n, actor="1002")
        decision = acceptance(n, work, 5)
    elif mutation == "role":
        decision = acceptance(n, work, 5, actor="1002")
    elif mutation == "rejected":
        decision = acceptance(n, work, 5, unique=False)
    elif mutation == "before-admission":
        work = greeting(n, actor="123", agent="New@claude")
        decision = acceptance(n, work, 5)
    elif mutation == "edited":
        work = event(
            n,
            4,
            {
                "kind": "hello_world_work",
                "agent_id": "alias@test",
                "greeting": "edited",
            },
            payload={"edit_history": [{"synthetic": True}]},
        )
        decision = acceptance(n, work, 5)
    else:
        first = greeting(n)
        sources += [raw(first), raw(acceptance(n, first, 5))]
        work = greeting(n, 6, "1002", "second@test")
        decision = acceptance(n, work, 7)
    sources += [raw(work), raw(decision)]
    _, state = transact(financial, sources)
    assert state["balances"].get("second@test") == 200
    assert state["balances"]["base@test"] == (142 if mutation == "duplicate" else 100)
    assert state["current_supply"] == (367 if mutation == "duplicate" else 325)


def test_later_canonical_admission_requires_fresh_work_and_preserves_anchor(financial):
    _, _, n, anchor, sources = financial
    early = greeting(n, 4, "123", "New@claude", "Before admission")
    sources += [raw(early), raw(acceptance(n, early, 5))]
    head, first = transact(financial, sources)
    admitted = declarations(at=NOW + timedelta(seconds=11))
    for r in admitted:
        r["repository_id"] = "1171421025"
    approved = json.loads(admitted[1]["body"].split("<!-- wea:vnext -->\n")[1])
    approved["approver_binding_id"] = "agent0-role"
    admitted[1]["actor_account_id"] = admitted[1]["original_author_account_id"] = (
        "129645949"
    )
    admitted[1]["body"] = "<!-- wea:vnext -->\n" + json.dumps(approved)
    admitted[1]["content_hash"] = hashlib.sha256(
        admitted[1]["body"].encode()
    ).hexdigest()
    sources += admitted
    head2, pending = transact(financial, sources, 20, base=head, anchor=False)
    assert pending["balances"]["New@claude"] == 0
    _, batches = load(financial[0], head2)
    merges = {batches[-1]["batch_id"]: (NOW + timedelta(seconds=21)).isoformat()}
    fresh = greeting(n, 22, "123", "New@claude", "Fresh after canonical admission")
    sources += [
        raw(fresh),
        raw(acceptance(n, early, 23)),
        raw(acceptance(n, fresh, 24)),
    ]
    _, paid = transact(financial, sources, 30, base=head2, anchor=False, merges=merges)
    assert paid["balances"]["New@claude"] == 42
    assert paid["hello_world_anchor"] == anchor
    assert (
        len([r for r in paid["hello_world"]["records"] if r["account_id"] == "123"])
        == 1
    )
    assert first["balances"].get("New@claude", 0) == 0


@pytest.mark.parametrize(
    "mutation",
    ["runtime", "package", "stale", "foreign", "unconfirmed", "issue", "installation"],
)
def test_financial_evidence_failure_is_closed(financial, mutation):
    _, _, n, anchor, sources = financial
    work = greeting(n)
    sources += [raw(work), raw(acceptance(n, work, 5))]
    if mutation == "runtime":
        anchor["runtime"] = list(installed_executor("0.10.0").reference)
    elif mutation == "package":
        anchor["checkpoint"]["installation_sha256"] = "0" * 64
    elif mutation == "stale":
        anchor["checkpoint"]["predecessor"] = "0" * 40
    elif mutation == "foreign":
        sources[-2]["repository_id"] = "999"
    elif mutation == "unconfirmed":
        sources[-2]["revision_status"] = "unresolved"
    elif mutation == "issue":
        sources[0]["issue_state"] = "closed"
    else:
        sources[1]["actor_account_id"] = "1001"
    with pytest.raises((ReplayError, ValueError)):
        build(financial, sources)


def test_schema5_downgrade_and_edited_paid_work_do_not_reverse_money(financial):
    _, _, n, _, sources = financial
    work = greeting(n)
    sources += [raw(work), raw(acceptance(n, work, 5))]
    head, state = transact(financial, sources)
    engine, _ = load(financial[0], head)
    old = {
        "schema": "wea-tide-batch-4",
        "previous_hash": engine.last_hash,
        "sequence": engine.sequence + 1,
    }
    with pytest.raises(ReplayError, match="downgrade"):
        engine.apply(old)
    edited = raw(
        event(
            n,
            21,
            {
                "kind": "hello_world_work",
                "agent_id": "alias@test",
                "greeting": "later edit",
            },
            payload={"edit_history": [{"synthetic": True}]},
        )
    )
    edited["object_id"] = work.object_id
    sources += [edited]
    _, updated = transact(financial, sources, 30, base=head, anchor=False)
    assert updated["balances"] == state["balances"]
    assert updated["current_supply"] == 367
    assert updated["hello_world"]["records"] == state["hello_world"]["records"]


def test_historical_consumed_account_and_retired_tombstone_create_no_money(financial):
    _, _, n, _, sources = financial
    work = greeting(n, 4, "265255605", "legacy@test", "Consumed legacy owner greeting")
    sources += [raw(work), raw(acceptance(n, work, 5))]
    _, state = transact(financial, sources)
    assert state["current_supply"] == state["opening_supply"] == 325
    assert state["balances"].get("legacy@test", 0) == 0
    assert {r["account_id"] for r in state["hello_world"]["records"]} == {
        "264877938",
        "265255605",
        "265329370",
    }
    assert not any(
        b["subject_id"] == "khattab-crow@openclaw"
        for b in state["hello_world_anchor"]["opening_identities"]["bindings"]
    )


def test_cross_batch_work_acceptance_and_edited_unpaid_snapshot(financial):
    _, _, n, _, sources = financial
    work = greeting(n)
    sources += [raw(work)]
    head, waiting = transact(financial, sources)
    assert waiting["current_supply"] == 325
    sources += [raw(acceptance(n, work, 21))]
    head2, paid = transact(financial, sources, 30, base=head, anchor=False)
    assert paid["current_supply"] == 367
    other = greeting(n, 31, "1002", "second@test", "Unpaid later edited")
    sources += [raw(other)]
    head3, _ = transact(financial, sources, 40, base=head2, anchor=False)
    edited = raw(
        event(
            n,
            41,
            {
                "kind": "hello_world_work",
                "agent_id": "second@test",
                "greeting": "Edited before acceptance",
            },
            "1002",
            payload={"edit_history": [{"synthetic": True}]},
        )
    )
    edited["object_id"] = other.object_id
    sources += [edited, raw(acceptance(n, other, 42))]
    _, blocked = transact(financial, sources, 50, base=head3, anchor=False)
    assert blocked["balances"]["second@test"] == 200
    assert blocked["current_supply"] == 367


def test_concurrent_attempt_canonical_order_mints_once(financial):
    _, _, n, _, sources = financial
    alias = greeting(n)
    base = greeting(n, 5, agent="base@test", text="Concurrent alias source")
    sources += [
        raw(alias),
        raw(base),
        raw(acceptance(n, base, 6)),
        raw(acceptance(n, alias, 7)),
    ]
    one = build(financial, sources)
    two = build(financial, list(reversed(sources)))
    assert one[STATE]["balances"] == two[STATE]["balances"]
    assert one[STATE]["hello_world"]["records"] == two[STATE]["hello_world"]["records"]
    assert one[STATE]["balances"]["base@test"] == 142


def test_source_block_preserves_paid_state_and_records_unresolved(financial):
    _, _, n, _, sources = financial
    work = greeting(n)
    sources += [raw(work), raw(acceptance(n, work, 5))]
    head, paid = transact(financial, sources)
    sources[0]["issue_state"] = "closed"
    _, blocked = transact(financial, sources, 20, base=head, anchor=False)
    assert blocked["hello_world"] == paid["hello_world"]
    assert blocked["balances"] == paid["balances"]
    assert (
        blocked["dispositions"]["hello-world:source-boundary"]["status"] == "unresolved"
    )


def test_malformed_hello_world_command_retains_unresolved_disposition(financial):
    _, _, n, _, sources = financial
    malformed = raw(event(n, 4, {}))
    malformed["body"] = n.source.MARKER + "{ invalid synthetic JSON"
    malformed["content_hash"] = hashlib.sha256(malformed["body"].encode()).hexdigest()
    sources += [malformed]
    _, state = transact(financial, sources)
    assert state["current_supply"] == 325
    assert state["dispositions"][malformed["revision_id"]]["status"] == "unresolved"


@pytest.mark.parametrize("financial", ["binding"], indirect=True)
def test_schema4_binding_transition_to5_preserves_authority_and_forbids_downgrade(
    financial,
):
    _, _, n, _, sources = financial
    work = greeting(n)
    sources += [raw(work), raw(acceptance(n, work, 5))]
    head, state = transact(financial, sources)
    engine, batches = load(financial[0], head)
    assert batches[0]["schema"] == "wea-tide-batch-4"
    assert engine.revision_schema
    assert "initiative_scopes" in state
    assert state["current_supply"] == 367
    assert batches[-1]["access_snapshot"] == batches[0]["access_snapshot"]
    regressing = {
        **batches[-1],
        "sequence": engine.sequence + 1,
        "previous_hash": engine.last_hash,
        "collection": capture(sources, 20),
        "access_snapshot": EMPTY,
    }
    with pytest.raises(ReplayError, match="binding admission forbids"):
        engine.apply(regressing)
