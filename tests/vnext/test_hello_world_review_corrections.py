"""Review regressions through serialized Tide; all sources and times are TEST ONLY."""

import copy
import hashlib
import json
from datetime import datetime, timedelta

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.tide.ledger import load
from wea_vnext.tide.replay import ReplayError, digest

from .test_hello_world_candidate import NOW, acceptance, event
from .test_hello_world_financial import (  # noqa: F401
    build,
    financial,
    greeting,
    native,
    raw,
    transact,
)
from .test_tide_replay import MARKER, command, setup_sources


def unrelated_task_sources():
    """Use the existing accepted task fixture with this fixture's bound owners."""
    sources, _ = setup_sources()
    mapping = {
        "repository-1": "1171421025",
        "account-author": "1001",
        "account-reviewer": "1002",
        "account-agent0": "129645949",
        "agent-author": "base@test",
        "agent-reviewer": "second@test",
        "author-binding": "binding-base@test",
        "reviewer-binding": "binding-second@test",
        "agent0-role-binding": "agent0-role",
    }

    def replace(value):
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, str):
            for old, new in mapping.items():
                value = value.replace(old, new)
        return value

    shift = (
        NOW + timedelta(seconds=60) - datetime.fromisoformat(sources[0]["effective_at"])
    )
    body_hash = plan_hash = None
    for source in sources:
        source.update(replace(source))
        source["effective_at"] = (
            datetime.fromisoformat(source["effective_at"]) + shift
        ).isoformat()
        prefix, body = source["body"].split(MARKER)
        data = json.loads(body)
        if "body_hash" in data:
            data["body_hash"] = body_hash
        if data["kind"] == "resolution_plan_revision":
            plan_hash = digest(
                {key: value for key, value in data.items() if key != "kind"}
            )
        if "plan_content_hash" in data:
            data["plan_content_hash"] = plan_hash
        source["body"] = prefix + command(data)
        source["content_hash"] = hashlib.sha256(source["body"].encode()).hexdigest()
        if source["object_kind"] == "issue":
            body_hash = source["content_hash"]
    return sources


def activation_attempt(n, sources, number, mutation):
    data = json.loads(sources[2]["body"][len(n.source.MARKER) :])
    actor = "129645949" if mutation == "operator-invalid-runtime" else "1001"
    if mutation == "foreign-minimal":
        data = {"kind": "hello_world_activation"}
    elif mutation == "operator-invalid-runtime":
        data["runtime"] = list(installed_executor("0.10.0").reference)
    attempt = raw(event(n, number, data, actor))
    if mutation == "malformed":
        attempt["body"] = n.source.MARKER + "{"
        attempt["content_hash"] = hashlib.sha256(attempt["body"].encode()).hexdigest()
    return attempt


@pytest.mark.parametrize(
    "mutation",
    ["foreign-minimal", "foreign-full", "malformed", "operator-invalid-runtime"],
)
def test_forged_activation_cannot_block_initial_or_later_mint(financial, mutation):  # noqa: F811
    root, _, n, _, sources = financial
    work = greeting(n)
    attempt = activation_attempt(n, sources, 6, mutation)
    sources += [raw(work), raw(acceptance(n, work, 5)), attempt]
    head, paid = transact(financial, sources)
    assert paid["balances"]["base@test"] == 142
    assert paid["current_supply"] == 367
    assert paid["dispositions"][attempt["revision_id"]]["status"] == "unresolved"
    second = greeting(n, 21, "1002", "second@test", "Fresh second account greeting")
    later = activation_attempt(n, sources, 23, mutation)
    sources += [raw(second), raw(acceptance(n, second, 22)), later]
    head2, updated = transact(financial, sources, 30, base=head, anchor=False)
    assert updated["balances"]["second@test"] == 242
    assert updated["current_supply"] == 409
    assert updated["dispositions"][later["revision_id"]]["status"] == "unresolved"
    assert (
        len([r for r in updated["hello_world"]["records"] if r["source"] == "vnext"])
        == 2
    )
    assert build(financial, sources, 40, base=head2, anchor=False) is None
    assert load(root, head2)[0].state() == updated


def test_two_valid_operator_activations_still_fail_closed(financial):  # noqa: F811
    _, _, n, _, sources = financial
    data = json.loads(sources[2]["body"][len(n.source.MARKER) :])
    sources += [raw(event(n, 6, data, "129645949"))]
    with pytest.raises(ValueError, match="exactly one authenticated activation"):
        build(financial, sources)
    sources.pop()
    head, before = transact(financial, sources)
    work = greeting(n, 21)
    sources += [
        raw(work),
        raw(acceptance(n, work, 22)),
        raw(event(n, 23, data, "129645949")),
    ]
    _, blocked = transact(financial, sources, 30, base=head, anchor=False)
    assert blocked["hello_world"] == before["hello_world"]
    assert blocked["balances"] == before["balances"]
    assert blocked["current_supply"] == 325
    assert (
        blocked["dispositions"]["hello-world:source-boundary"]["status"] == "unresolved"
    )


@pytest.mark.parametrize("text", ["\ud800", "\udfff"])
def test_unencodable_work_is_not_retained_and_tasks_and_fresh_work_continue(
    financial, text  # noqa: F811
):
    root, _, n, _, sources = financial
    invalid = greeting(n, text=text)
    # The captured JSON body contains an ASCII escape; only its decoded greeting
    # is unencodable. Do not alter that snapshot or substitute replacement bytes.
    assert invalid.body.encode("utf-8")
    sources += [raw(invalid), *unrelated_task_sources()]
    head, state = transact(financial, sources, 2500)
    assert state["dispositions"][invalid.revision_id]["status"] == "unresolved"
    assert "UTF-8" in state["dispositions"][invalid.revision_id]["reason"]
    assert state["hello_world"]["works"] == {}
    assert state["current_supply"] == 325
    assert state["escrow_wea"] == 100
    assert state["balances"]["base@test"] == 0
    assert "issue-42" in state["tasks"]
    fresh = greeting(n, 2501, text="Valid fresh greeting after invalid UTF-8")
    sources += [raw(fresh), raw(acceptance(n, fresh, 2502))]
    head2, updated = transact(financial, sources, 2510, base=head, anchor=False)
    assert updated["current_supply"] == 367
    assert updated["balances"]["base@test"] == 42
    assert updated["escrow_wea"] == 100
    assert updated["tasks"] == state["tasks"]
    assert len(updated["hello_world"]["works"]) == 1
    assert load(root, head2)[0].state() == updated


def test_activated_unconfirmed_hw_preserves_money_and_funds_unrelated_task(financial):  # noqa: F811
    _, _, n, _, sources = financial
    work = greeting(n)
    sources += [raw(work), raw(acceptance(n, work, 5))]
    head, paid = transact(financial, sources)
    unresolved = raw(greeting(n, 21, "1002", "second@test", "Unconfirmed new source"))
    unresolved["revision_status"] = "unresolved"
    sources += [unresolved, *unrelated_task_sources()]
    head2, state = transact(financial, sources, 2500, base=head, anchor=False)
    assert state["hello_world_anchor"] == paid["hello_world_anchor"]
    assert state["hello_world"] == paid["hello_world"]
    assert state["current_supply"] == paid["current_supply"] == 367
    assert state["balances"]["base@test"] == 42
    assert state["balances"]["second@test"] == 200
    assert state["escrow_wea"] == 100
    assert "issue-42" in state["tasks"]
    assert state["dispositions"][unresolved["revision_id"]]["status"] == "unresolved"
    assert (
        state["dispositions"]["hello-world:source-boundary"]["status"] == "unresolved"
    )
    assert sum(state["balances"].values()) + state["escrow_wea"] == 367
    assert build(financial, sources, 2510, base=head2, anchor=False) is None


@pytest.mark.parametrize("ordinary", [True, False])
def test_active_anchor_does_not_exempt_ordinary_or_foreign_required_sources(
    financial, ordinary  # noqa: F811
):
    _, _, n, _, sources = financial
    head, _ = transact(financial, sources)
    unresolved = (
        unrelated_task_sources()[-1]
        if ordinary
        else raw(greeting(n, 21, "1002", "second@test"))
    )
    unresolved = copy.deepcopy(unresolved)
    unresolved["revision_status"] = "unresolved"
    if not ordinary:
        unresolved["repository_id"] = "999"
    with pytest.raises(ReplayError, match="required revision evidence is incomplete"):
        build(financial, [*sources, unresolved], 2500, base=head, anchor=False)
