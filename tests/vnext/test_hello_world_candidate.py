"""Candidate S-09/S-09B/S-09C; all IDs/times below are synthetic test evidence."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from wea_vnext.engine import installed_executor, load_executor
from wea_vnext.tide.hello_world import (
    SCHEMA,
    checkpoint,
    collect_hello_world_sources,
    preview,
    validate_historical,
)
from wea_vnext.tide.ledger import load, verify_directory
from wea_vnext.tide.replay import canonical, digest

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
BASE = "fee147a968224e9ead3075e62771e82cff1452d2"


@pytest.fixture
def native():
    reference = installed_executor("0.11.0").reference
    modules = load_executor(reference).import_modules(("sources", "identity"))
    identity = modules["identity"]
    accounts = (
        identity.GitHubAccount("1001", "test-one", "base@test"),
        identity.GitHubAccount("1002", "test-two", "second@test"),
        identity.GitHubAccount("129645949", "test-operator", "operator@test"),
    )
    bindings = (
        *(
            identity.Binding(f"binding-{agent}", "agent", account, agent, 1, NOW)
            for account, agent in (
                ("1001", "base@test"),
                ("1001", "alias@test"),
                ("1002", "second@test"),
                ("129645949", "operator@test"),
            )
        ),
        identity.Binding("agent0-role", "agent0", "129645949", "agent0@system", 1, NOW),
    )
    groups = tuple(
        identity.ControlGroupBinding(
            f"group-{b.subject_id}",
            b.subject_id,
            f"control-{b.github_account_id}",
            1,
            NOW,
        )
        for b in bindings
        if b.actor_kind == "agent"
    )
    registry = identity.IdentityRegistry(accounts, bindings, groups)
    engine = SimpleNamespace(
        registry=registry,
        balances={a.base_agent_id: 0 for a in accounts},
        supply=0,
        state=lambda: {
            "cutoff": NOW.isoformat().replace("+00:00", "Z"),
            "balances": {a.base_agent_id: 0 for a in accounts},
            "escrow_wea": 0,
        },
    )
    return SimpleNamespace(
        reference=reference,
        modules=modules,
        source=modules["sources"],
        registry=registry,
        engine=engine,
        checkpoint=checkpoint(engine, BASE),
    )


def event(native, number, data, actor="1001", *, issue=False, payload=None):
    source = native.source
    at = NOW + timedelta(seconds=number)
    body = source.BODY if issue else source.MARKER + json.dumps(data)
    metadata = {
        "issue_id": source.ISSUE_ID,
        "issue_number": 1,
        "revision_status": "confirmed",
        "original_author_account_id": actor,
        "created_at": at.isoformat().replace("+00:00", "Z"),
        "edit_history": [],
        **({"issue_state": "open"} if issue else {}),
        **(payload or {}),
    }
    return source.GitHubEvent(
        repository_id=source.REPOSITORY_ID,
        object_kind="issue" if issue else "issue_comment",
        object_id=source.ISSUE_ID if issue else str(900000 + number),
        revision_id=f"github:TEST-{number}:created",
        effective_at=at,
        body=body,
        content_hash=hashlib.sha256(body.encode()).hexdigest(),
        actor_account_id=actor,
        payload=metadata,
    )


def setup(native):
    issue = event(native, 1, None, "129645949", issue=True)
    activation = event(
        native,
        2,
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
    work = event(
        native,
        3,
        {
            "kind": "hello_world_work",
            "agent_id": "alias@test",
            "greeting": "Synthetic unique greeting",
        },
    )
    return [issue, activation, work, acceptance(native, work, 4)]


def acceptance(native, work, number, *, unique=True, actor="129645949"):
    return event(
        native,
        number,
        {
            "kind": "hello_world_acceptance",
            "work_revision_id": work.revision_id,
            "work_content_hash": work.content_hash,
            "agent0_id": "agent0@system",
            "binding_id": "agent0-role",
            "binding_version": 1,
            "mechanically_unique": unique,
        },
        actor,
    )


def evidence(native, events):
    source = native.source
    boundary = source.GitHubReadBoundary(
        repository=source.REPOSITORY,
        repository_id=source.REPOSITORY_ID,
        captured_at=NOW + timedelta(hours=1),
        read_sequence=1,
        end_cursor="synthetic-test-only",
        complete=True,
    )
    initial = source.ProtocolState(
        schema_version=1,
        ruleset_hash=native.reference.ruleset_hash,
        tide_interface_version=native.reference.tide_interface_version,
        executor_manifest_hash=native.reference.executor_manifest_hash,
    )
    return source.accept_github_batch(
        initial, source.GitHubEventBatch(boundary=boundary, events=events)
    ).state


def replay(native, events, **changes):
    args = {
        "github_state": evidence(native, events),
        "registry": native.registry,
        "checkpoint": native.checkpoint,
        **changes,
    }
    return native.source.call_verified("replay_hello_world", **args)


def test_s_09b_one_mint_to_immutable_base_after_accepted_alias_work(native):
    events = setup(native)
    before = canonical(native.engine.state())
    result = replay(native, events)
    assert result["mint_intents"] == [
        {
            "agent_id": "base@test",
            "amount_wea": 42,
            "idempotency_key": "hello-world:1001",
        }
    ]
    assert result["contract"]["status"] == "active"
    assert (
        result["contract"]["bank_total_wea"]
        == result["contract"]["review_fee_wea"]
        == 0
    )
    assert result["task_effects"] == result["escrow_effects"] == []
    assert canonical(native.engine.state()) == before
    assert replay(native, events) == result
    changed_account = replace(
        native.registry.account("1001"), base_agent_id="alias@test"
    )
    with pytest.raises(ValueError, match="immutable"):
        native.registry.register_agent(
            account=changed_account,
            account_binding=native.registry.bindings[0],
            control_group_binding=native.registry.control_group_bindings[0],
        )


def test_s_09_historical_restoration_consumes_three_accounts_without_money(native):
    events = setup(native)[:2]
    before = native.registry.to_data()
    restored = replay(native, events)
    assert restored["mint_intents"] == []
    assert {r["account_id"] for r in restored["records"]} == {
        "264877938",
        "265255605",
        "265329370",
    }
    retired = next(r for r in restored["records"] if r["account_id"] == "264877938")
    assert retired["evidence"]["mint_key_state"] == "used_retired"
    assert retired["evidence"]["active_authority"] is False
    assert native.registry.to_data() == before
    checked = validate_historical(ROOT)
    assert checked["mint_uses"] == 3 and checked["retired_tombstones"] == 1
    assert checked["left_side"] == checked["right_side"] == 19025


def test_s_09b_retry_second_alias_and_duplicate_comparison_never_mint_again(native):
    events = setup(native)
    second_alias = event(
        native,
        5,
        {
            "kind": "hello_world_work",
            "agent_id": "base@test",
            "greeting": "Other greeting",
        },
    )
    duplicate = event(
        native,
        7,
        {
            "kind": "hello_world_work",
            "agent_id": "second@test",
            "greeting": "Synthetic unique greeting",
        },
        "1002",
    )
    retry = acceptance(native, events[2], 9)
    result = replay(
        native,
        [
            *events,
            second_alias,
            acceptance(native, second_alias, 6),
            duplicate,
            acceptance(native, duplicate, 8),
            retry,
        ],
    )
    assert len(result["mint_intents"]) == 1
    assert result["dispositions"]["github:TEST-6:created"] == "already-used"
    assert result["dispositions"]["github:TEST-8:created"] == "duplicate-comparison"
    assert result["dispositions"][retry.revision_id] == "already-decided"


def test_rejection_and_unaccepted_work_create_no_mint(native):
    events = setup(native)
    assert replay(native, events[:3])["mint_intents"] == []
    assert (
        replay(native, [*events[:3], acceptance(native, events[2], 4, unique=False)])[
            "mint_intents"
        ]
        == []
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing-issue",
        "body",
        "closed",
        "foreign",
        "edited",
        "wrong-owner",
        "unadmitted",
        "wrong-role",
        "wrong-binding",
        "stale",
        "runtime",
        "unconfirmed",
        "wrong-hash",
        "missing-activation",
        "second-activation",
    ],
)
def test_s_09c_bad_sources_fail_closed(native, change):
    events = setup(native)
    if change == "missing-issue":
        events.pop(0)
    elif change == "body":
        events[0] = replace(
            events[0], body="edited", content_hash=hashlib.sha256(b"edited").hexdigest()
        )
    elif change in {"closed", "foreign", "edited", "unconfirmed"}:
        index = 0 if change == "closed" else 2
        payload = dict(events[index].payload)
        key, value = {
            "closed": ("issue_state", "closed"),
            "foreign": ("issue_id", "42"),
            "edited": ("edit_history", ["edited"]),
            "unconfirmed": ("revision_status", "requires-edit-evidence"),
        }[change]
        payload[key] = value
        events[index] = replace(events[index], payload=payload)
    elif change in {"wrong-owner", "unadmitted", "wrong-role"}:
        index = 3 if change == "wrong-role" else 2
        actor = (
            "99999"
            if change == "unadmitted"
            else "1002"
            if change == "wrong-owner"
            else "1001"
        )
        payload = {**dict(events[index].payload), "original_author_account_id": actor}
        events[index] = replace(events[index], actor_account_id=actor, payload=payload)
    elif change in {"wrong-binding", "wrong-hash"}:
        data = json.loads(events[3].body[len(native.source.MARKER) :])
        data["binding_id" if change == "wrong-binding" else "work_content_hash"] = (
            "wrong"
        )
        events[3] = event(native, 4, data, "129645949")
    elif change in {"stale", "runtime"}:
        data = json.loads(events[1].body[len(native.source.MARKER) :])
        if change == "stale":
            data["checkpoint"]["predecessor"] = "0" * 40
        else:
            data["runtime"] = list(installed_executor("0.10.0").reference)
        events[1] = event(native, 2, data, "129645949")
    elif change == "missing-activation":
        events.pop(1)
    elif change == "second-activation":
        data = json.loads(events[1].body[len(native.source.MARKER) :])
        events.append(event(native, 5, data, "129645949"))
    with pytest.raises(ValueError):
        replay(native, events)


def test_raw_import_globals_and_forged_contract_cannot_authorize(native):
    raw = importlib.import_module("wea_vnext.executors.v0_11_0.sources")
    raw._RUNTIME = tuple(native.reference)
    with pytest.raises(ValueError, match="verifier-owned"):
        raw.replay_hello_world(
            github_state=evidence(native, setup(native)),
            registry=native.registry,
            checkpoint=native.checkpoint,
            _verified_runtime_reference=native.reference,
        )
    with pytest.raises(ValueError, match="manifest verifier"):
        raw._bind_verified_runtime(native.reference, None)
    assert not hasattr(native.source, "replay_hello_world")
    with pytest.raises(TypeError):
        replay(native, setup(native), contract=object())
    with pytest.raises(ValueError, match="native ProtocolState"):
        replay(native, setup(native), github_state={})
    with pytest.raises(TypeError, match="manifest verifier"):
        replay(native, setup(native), _verified_runtime_reference=native.reference)


def packet(native, events):
    rows = []
    for e in events:
        rows.append({**e.to_data(), **dict(e.payload)})
    captured = {
        "schema": "wea-tide-collection-1",
        "repository_id": native.source.REPOSITORY_ID,
        "cutoff": (NOW + timedelta(hours=1)).isoformat(),
        "tracked_issues": [1],
        "sources": rows,
    }
    captured["capture_hash"] = digest(captured)
    return {
        "schema": SCHEMA,
        "runtime": list(native.reference),
        "checkpoint": native.checkpoint,
        "collection": captured,
    }


def test_read_only_overlay_preserves_tasks_and_increases_supply_by_exactly_42(native):
    data = packet(native, setup(native))
    before = canonical(native.engine.state())
    result = preview(native.engine, BASE, data, root=ROOT)
    assert result["balances"]["base@test"] == result["supply_wea"] == 42
    assert result["writes"] == 0
    assert result == preview(native.engine, BASE, data, root=ROOT)
    assert before == canonical(native.engine.state())
    bad = copy.deepcopy(data)
    bad["checkpoint"]["installation_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="stale"):
        preview(native.engine, BASE, bad, root=ROOT)


def test_existing_canonical_replay_remains_byte_identical():
    engine, _ = load(ROOT, BASE)
    before = canonical(engine.state())
    on_disk = verify_directory(ROOT)
    assert canonical(on_disk) == before
    assert engine.supply == sum(engine.balances.values()) == 19025
    assert "hello_world" not in on_disk
    assert "0.11" not in canonical(on_disk).decode()


def test_native_wrong_runtime_and_incomplete_boundary_fail_closed(native):
    state = evidence(native, setup(native))
    wrong = replace(state, tide_interface_version="0.10")
    with pytest.raises(ValueError, match="wrong runtime"):
        replay(native, setup(native), github_state=wrong)
    with pytest.raises(ValueError, match="complete"):
        native.source.ConfirmedReadBoundary(
            replace(state.boundaries[0].boundary, complete=False), "0" * 64
        )


def test_retired_account_cannot_be_resurrected(native):
    identity = native.modules["identity"]
    retired = identity.GitHubAccount(
        "264877938", "test-retired", "khattab-crow@openclaw"
    )
    binding = identity.Binding(
        "retired", "agent", "264877938", retired.base_agent_id, 1, NOW
    )
    group = identity.ControlGroupBinding(
        "retired-group", retired.base_agent_id, "retired-group", 1, NOW
    )
    registry = identity.IdentityRegistry(
        (*native.registry.accounts, retired),
        (*native.registry.bindings, binding),
        (*native.registry.control_group_bindings, group),
    )
    point = {**native.checkpoint, "identities_hash": digest(registry.to_data())}
    with pytest.raises(ValueError, match="resurrect"):
        replay(native, setup(native), registry=registry, checkpoint=point)


def test_attested_account_stays_consumed_after_new_admission(native):
    identity = native.modules["identity"]
    historical = identity.GitHubAccount("265255605", "test-historical", "old@test")
    binding = identity.Binding("old-owner", "agent", "265255605", "old@test", 1, NOW)
    group = identity.ControlGroupBinding("old-group", "old@test", "old-control", 1, NOW)
    native.registry = identity.IdentityRegistry(
        (*native.registry.accounts, historical),
        (*native.registry.bindings, binding),
        (*native.registry.control_group_bindings, group),
    )
    native.checkpoint["identities_hash"] = digest(native.registry.to_data())
    events = setup(native)[:2]
    work = event(
        native,
        3,
        {
            "kind": "hello_world_work",
            "agent_id": "old@test",
            "greeting": "New text cannot reset consumed opportunity",
        },
        "265255605",
    )
    result = replay(native, [*events, work, acceptance(native, work, 4)])
    assert result["mint_intents"] == []
    assert result["dispositions"]["github:TEST-4:created"] == "already-used"


def test_operator_role_cannot_substitute_for_agent0(native):
    identity = native.modules["identity"]
    native.registry = identity.IdentityRegistry(
        native.registry.accounts,
        (
            *(b for b in native.registry.bindings if b.actor_kind != "agent0"),
            identity.Binding(
                "operator-role", "operator", "129645949", "operator@system", 1, NOW
            ),
        ),
        native.registry.control_group_bindings,
    )
    native.checkpoint["identities_hash"] = digest(native.registry.to_data())
    with pytest.raises(ValueError):
        replay(native, setup(native))


def test_collector_pins_permanent_issue_and_retains_state():
    from .test_tide_collection import API, CUTOFF

    api = API()
    api.issue.update(id=4015417565, node_id="permanent-test-issue", state="closed")
    captured = collect_hello_world_sources(api.get, api.graphql, cutoff=CUTOFF)
    issue = next(row for row in captured["sources"] if row["object_kind"] == "issue")
    assert issue["object_id"] == issue["issue_id"] == "4015417565"
    assert issue["issue_state"] == "closed"
    assert captured["tracked_issues"] == [1]
    assert len(captured["sources"]) == 2
    api.issue["id"] = 7
    with pytest.raises(ValueError, match="permanent Hello World"):
        collect_hello_world_sources(api.get, api.graphql, cutoff=CUTOFF)


def test_collector_rejects_state_change_during_capture():
    from .test_tide_collection import API, API_ROOT, CUTOFF

    api = API()
    api.issue.update(id=4015417565, node_id="permanent-test-issue", state="open")
    reads = 0

    def get(path):
        nonlocal reads
        row = api.get(path)
        if path == f"{API_ROOT}/issues/1":
            reads += 1
            if reads == 4:
                row["state"] = "closed"
        return row

    with pytest.raises(ValueError, match="changed during capture"):
        collect_hello_world_sources(get, api.graphql, cutoff=CUTOFF)


def test_read_only_cli_explicit_candidate_option(native, monkeypatch, tmp_path, capsys):
    from wea_cli import tide
    from wea_cli.cli import build_parser, is_readonly_command

    path = tmp_path / "synthetic-evidence.json"
    path.write_text(json.dumps(packet(native, setup(native))), encoding="utf-8")
    args = build_parser().parse_args(
        [
            "--root",
            str(ROOT),
            "tide",
            "--ref",
            BASE,
            "--hello-world-evidence",
            str(path),
        ]
    )
    assert is_readonly_command(args.command, args)
    monkeypatch.setattr(tide, "git", lambda *_: BASE)
    monkeypatch.setattr(tide, "files", lambda *_: ["test-bootstrap"])
    monkeypatch.setattr(tide, "load", lambda *_: (native.engine, []))
    assert tide.show(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["writes"] == 0
    assert output["balances"]["base@test"] == 42
    assert "pending" in output["status"]


def test_later_canonical_admission_preserves_activation_and_mints_once(native):
    identity = native.modules["identity"]
    joined = NOW + timedelta(seconds=10)
    account = identity.GitHubAccount("3001", "test-new-owner", "new@test")
    binding = identity.Binding("new-binding", "agent", "3001", "new@test", 1, joined)
    group = identity.ControlGroupBinding(
        "new-group", "new@test", "new-control", 1, joined
    )
    extended = identity.IdentityRegistry(
        (*native.registry.accounts, account),
        (*native.registry.bindings, binding),
        (*native.registry.control_group_bindings, group),
    )
    work = event(
        native,
        15,
        {
            "kind": "hello_world_work",
            "agent_id": "new@test",
            "greeting": "Later admission unique greeting",
        },
        "3001",
    )
    result = replay(
        native,
        [*setup(native)[:2], work, acceptance(native, work, 16)],
        registry=extended,
        opening_registry=native.registry,
    )
    assert result["mint_intents"] == [
        {
            "agent_id": "new@test",
            "amount_wea": 42,
            "idempotency_key": "hello-world:3001",
        }
    ]
    early = event(
        native,
        5,
        {
            "kind": "hello_world_work",
            "agent_id": "new@test",
            "greeting": "Pre-admission greeting",
        },
        "3001",
    )
    with pytest.raises(ValueError):
        replay(
            native,
            [*setup(native)[:2], early, acceptance(native, early, 6)],
            registry=extended,
            opening_registry=native.registry,
        )


def test_registry_extension_cannot_change_a_permanent_base_agent(native):
    identity = native.modules["identity"]
    forged = identity.IdentityRegistry(
        tuple(
            replace(a, base_agent_id="alias@test")
            if a.github_account_id == "1001"
            else a
            for a in native.registry.accounts
        ),
        native.registry.bindings,
        native.registry.control_group_bindings,
    )
    with pytest.raises(ValueError, match="permanent base"):
        replay(native, setup(native), registry=forged, opening_registry=native.registry)


def test_conflicting_source_revision_blocks_all_mints(native):
    events = setup(native)
    conflicting = replace(
        events[2],
        body="different retained bytes",
        content_hash=hashlib.sha256(b"different retained bytes").hexdigest(),
    )
    with pytest.raises(ValueError, match="confirmed boundary"):
        replay(native, [*events, conflicting])
