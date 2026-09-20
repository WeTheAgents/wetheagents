"""P-01 through P-08: participant admission through the real Tide replay."""

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.tide.ledger import STATE, candidate, validate
from wea_vnext.tide.replay import Replay, ReplayError, digest

from .test_tide_ledger import commit, put, repo  # noqa: F401
from .test_tide_replay import batch, bootstrap, command, raw

START = datetime(2026, 9, 9, 16, tzinfo=timezone.utc)


def declarations(
    *,
    owner="123",
    agents=None,
    base="New@claude",
    group="owner-123",
    request_id="request-1",
    approval_id="approval-1",
    at=START,
):
    data = {
        "kind": "participant_request",
        "owner_account_id": owner,
        "base_agent_id": base,
        "control_group_id": group,
        "agents": agents or [{"agent_id": base, "preserve_balance": False}],
    }
    consent = raw(command(data), "comment-" + request_id, request_id, owner, at)
    approval = raw(
        command(
            {
                "kind": "participant_approval",
                "request_revision_id": request_id,
                "request_content_hash": consent["content_hash"],
                "approver_binding_id": "agent0-role-binding",
                "approver_binding_version": 1,
            }
        ),
        "comment-" + approval_id,
        approval_id,
        "account-agent0",
        at + timedelta(seconds=1),
    )
    return [consent, approval]


def participant_batch(engine, sources, *, at=START + timedelta(seconds=2), merges=None):
    value = batch(engine, sources, at, merges)
    return {
        **value,
        "schema": "wea-tide-batch-3"
        if engine.access_snapshot is not None
        else "wea-tide-batch-2",
        **(
            {"access_snapshot": engine.access_snapshot}
            if engine.access_snapshot is not None
            else {}
        ),
        "participant_runtime": list(installed_executor("0.10.0").reference),
    }


def rewrite(source, **changes):
    data = json.loads(source["body"].split("<!-- wea:vnext -->\n")[1])
    data.update(changes)
    result = copy.deepcopy(source)
    result["body"] = command(data)
    import hashlib

    result["content_hash"] = hashlib.sha256(result["body"].encode()).hexdigest()
    return result


def test_new_account_requires_owner_and_approval_and_starts_at_zero():
    engine = Replay(bootstrap())
    sources = declarations()
    engine.apply(participant_batch(engine, sources[:1]))
    assert engine.participants == {}
    assert "New@claude" not in engine.balances
    state = engine.apply(
        participant_batch(engine, sources[1:], at=START + timedelta(seconds=3))
    )
    assert state["balances"]["New@claude"] == 0
    assert state["opening_supply"] == 300
    assert state["escrow_wea"] == 0
    assert len(state["participants"]) == 1
    assert all(b.subject_id != "New@claude" for b in engine.registry.bindings)


@pytest.mark.parametrize(
    "mutation",
    ["owner", "hash", "role", "version", "issue", "unconfirmed", "body", "extra"],
)
def test_invalid_consent_or_approval_has_no_effect(mutation):
    engine = Replay(bootstrap())
    consent, approval = declarations()
    if mutation == "owner":
        consent["actor_account_id"] = "456"
    elif mutation == "hash":
        approval = rewrite(approval, request_content_hash="0" * 64)
    elif mutation == "role":
        approval["actor_account_id"] = approval["original_author_account_id"] = "123"
    elif mutation == "version":
        approval = rewrite(approval, approver_binding_version=True)
    elif mutation == "issue":
        approval["issue_id"] = "another-issue"
    elif mutation == "unconfirmed":
        consent["revision_status"] = "unresolved"
    elif mutation == "body":
        consent["object_kind"] = "issue"
    else:
        consent = rewrite(consent, balance=100)
    engine.apply(participant_batch(engine, [consent, approval]))
    assert engine.participants == {}
    assert engine.balances == bootstrap()["balances"]


@pytest.mark.parametrize(
    "agents",
    [
        [{"agent_id": "New@claude", "preserve_balance": True}],
        [{"agent_id": "agent0@system", "preserve_balance": False}],
        [{"agent_id": "New@claude", "preserve_balance": False}] * 2,
        [
            {"agent_id": "New@claude", "preserve_balance": False},
            {"agent_id": "Bad@system", "preserve_balance": False},
        ],
    ],
)
def test_atomic_rejection_for_invalid_or_reserved_identity(agents):
    engine = Replay(bootstrap())
    engine.apply(participant_batch(engine, declarations(agents=agents)))
    assert engine.participants == {}
    assert engine.balances == bootstrap()["balances"]


def test_merge_time_limits_authority_and_no_activation_only_pr(repo):  # noqa: F811
    root, base = repo
    sources = declarations()
    collection = {
        "cutoff": (START + timedelta(seconds=2)).isoformat(),
        "sources": sources,
        "tracked_issues": [],
    }
    payloads = candidate(
        root,
        base,
        collection,
        {},
        {},
        access_snapshot={"genesis": None, "entries": [], "commits": []},
    )
    put(root, payloads)
    head = commit(root)
    assert validate(root, base, head)["participants"]
    journal = next(
        v for k, v in payloads.items() if k.startswith("ledger/vnext/tides/")
    )
    merged = START + timedelta(seconds=5)
    merges = {journal["batch_id"]: merged.isoformat()}
    engine = Replay(bootstrap())
    engine.apply(journal)
    engine.apply(
        participant_batch(engine, [], at=START + timedelta(seconds=6), merges=merges)
    )
    binding = next(b for b in engine.registry.bindings if b.subject_id == "New@claude")
    assert binding.effective_from == merged

    def draft(at, rid):
        return raw(
            "<!-- wea:domain - -->\n"
            + command(
                {
                    "kind": "draft_issue",
                    "author_agent_id": "New@claude",
                    "author_binding_id": binding.binding_id,
                    "author_binding_version": 1,
                    "max_bank_wea": 1,
                }
            ),
            rid,
            rid,
            "123",
            at,
            kind="issue",
            issue=rid,
        )

    state = engine.apply(
        participant_batch(
            engine,
            [
                draft(merged - timedelta(seconds=1), "early"),
                draft(merged + timedelta(seconds=1), "later"),
            ],
            at=START + timedelta(seconds=7),
            merges=merges,
        )
    )
    assert state["dispositions"]["early"]["status"] == "unresolved"
    assert state["dispositions"]["later"]["status"] == "accepted"
    assert (
        candidate(
            root,
            head,
            {
                **collection,
                "tracked_issues": [42],
                "cutoff": (START + timedelta(seconds=8)).isoformat(),
            },
            merges,
            {},
            access_snapshot={"genesis": None, "entries": [], "commits": []},
        )
        is None
    )


def test_duplicate_conflicting_and_additional_requests():
    engine = Replay(bootstrap())
    first = participant_batch(engine, declarations())
    engine.apply(first)
    initial = copy.deepcopy(engine.participants)
    sources = declarations(approval_id="approval-2")
    engine.apply(participant_batch(engine, sources, at=START + timedelta(seconds=3)))
    assert engine.participants == initial
    for request_id, base, group, name in [
        ("bad-base", "Other@claude", "owner-123", "Other@claude"),
        ("bad-group", "New@claude", "different", "Other@claude"),
        ("collision", "New@claude", "owner-123", "New@claude"),
        ("additional", "New@claude", "owner-123", "Other@claude"),
    ]:
        at = START + timedelta(seconds=engine.sequence * 4)
        sources = declarations(
            request_id=request_id,
            approval_id="approve-" + request_id,
            at=at,
            base=base,
            group=group,
            agents=[{"agent_id": name, "preserve_balance": False}],
        )
        engine.apply(participant_batch(engine, sources, at=at + timedelta(seconds=2)))
        assert (request_id in engine.participants) == (request_id == "additional")
    assert len(engine.participants) == 2


def test_old_batches_keep_semantics_and_runtime_is_pinned():
    initial = bootstrap()
    engine = Replay(initial)
    old = batch(engine, declarations(), START + timedelta(seconds=2))
    state = engine.apply(old)
    assert state["schema"] == "wea-tide-state-1"
    assert "participants" not in state
    assert state["balances"] == initial["balances"]
    assert Replay(initial).apply(old) == state
    new = participant_batch(engine, [], at=START + timedelta(seconds=3))
    bad = copy.deepcopy(new)
    bad["participant_runtime"][2] = "0" * 64
    with pytest.raises(ReplayError, match="participant runtime"):
        engine.apply(bad)
    engine.apply(new)
    assert engine.participants == {}
    with pytest.raises(ReplayError, match="regressing"):
        engine.apply(batch(engine, [], START + timedelta(seconds=4)))


def test_superseded_consent_cannot_gain_approval_or_rewrite_admission():
    for approved in (False, True):
        engine = Replay(bootstrap())
        consent, approval = declarations()
        engine.apply(
            participant_batch(engine, [consent, approval] if approved else [consent])
        )
        before = copy.deepcopy(engine.participants)
        edited = rewrite(
            consent, agents=[{"agent_id": "Changed@claude", "preserve_balance": False}]
        )
        edited["revision_id"] = "edited-request"
        edited["effective_at"] = (START + timedelta(seconds=3)).isoformat()
        engine.apply(
            participant_batch(
                engine, [edited, approval], at=START + timedelta(seconds=4)
            )
        )
        assert engine.participants == before
        assert "Changed@claude" not in engine.balances


def test_competing_requests_in_one_batch_reserve_atomically():
    engine = Replay(bootstrap())
    first = declarations()
    second = declarations(
        owner="456",
        base="Second@claude",
        group="owner-456",
        request_id="request-2",
        approval_id="approval-2",
        at=START + timedelta(seconds=2),
        agents=[
            {"agent_id": "Second@claude", "preserve_balance": False},
            {"agent_id": "New@claude", "preserve_balance": False},
        ],
    )
    state = engine.apply(
        participant_batch(engine, first + second, at=START + timedelta(seconds=4))
    )
    assert set(state["participants"]) == {"request-1"}
    assert "Second@claude" not in state["balances"]
    assert state["dispositions"]["approval-2"]["status"] == "unresolved"


def test_thirteen_canonical_claude_balances_survive_bulk_registration():
    root = Path(__file__).resolve().parents[2]
    initial = json.loads(
        (root / "ledger/vnext/tide-bootstrap.json").read_text(encoding="utf-8")
    )
    before = digest(initial)
    agents = [
        {"agent_id": name, "preserve_balance": True}
        for name in sorted(initial["balances"])
        if name.endswith("@claude")
    ]
    assert len(agents) == 13
    consent, approval = declarations(
        owner="129645949",
        base="agent0@system",
        group="owner-github-129645949",
        agents=agents,
    )
    approval = rewrite(approval, approver_binding_id="pilot-agent0-role-v1")
    for source in (consent, approval):
        source["repository_id"] = initial["repository_id"]
    approval["actor_account_id"] = approval["original_author_account_id"] = "129645949"
    engine = Replay(initial)
    first = participant_batch(engine, [consent, approval])
    state = engine.apply(first)
    assert len(state["participants"]["request-1"]["agents"]) == 13
    assert state["balances"] == initial["balances"]
    assert state["opening_supply"] == 19025
    assert digest(initial) == before
    engine.apply(
        participant_batch(
            engine,
            [],
            at=START + timedelta(seconds=5),
            merges={first["batch_id"]: (START + timedelta(seconds=4)).isoformat()},
        )
    )
    assert (
        len([b for b in engine.registry.bindings if b.subject_id.endswith("@claude")])
        == 13
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_account_id", "456"),
        ("control_group_id", "fake"),
        ("base_agent_id", "Hijack@claude"),
    ],
)
def test_guard_rejects_forged_participant_projection(repo, field, value):  # noqa: F811
    root, base = repo
    payloads = candidate(
        root,
        base,
        {
            "cutoff": (START + timedelta(seconds=2)).isoformat(),
            "sources": declarations(),
            "tracked_issues": [],
        },
        {},
        {},
        access_snapshot={"genesis": None, "entries": [], "commits": []},
    )
    payloads[STATE]["participants"]["request-1"][field] = value
    put(root, payloads)
    with pytest.raises(ReplayError, match="differs from executor replay"):
        validate(root, base, commit(root))
