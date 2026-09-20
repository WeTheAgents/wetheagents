"""Raw GitHub declarations must produce escrow and payment through replay."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.tide.replay import Replay, canonical, digest, replay

from . import current_bdd_support as support

MARKER = "<!-- wea:vnext -->\n"


def raw(
    body, source_id, revision_id, actor, at, *, kind="issue_comment", issue="issue-42"
):
    return {
        "body": body,
        "content_hash": hashlib.sha256(body.encode()).hexdigest(),
        "object_id": source_id,
        "revision_id": revision_id,
        "actor_account_id": actor,
        "original_author_account_id": actor,
        "effective_at": at.isoformat(),
        "object_kind": kind,
        "repository_id": "repository-1",
        "issue_number": 42,
        "issue_id": issue,
        "revision_status": "confirmed",
    }


def command(data):
    return MARKER + json.dumps(data, ensure_ascii=False, indent=2)


def setup_sources(scope="-"):
    draft = support.draft()
    body = (
        (f"<!-- wea:domain {scope} -->\n" if scope is not None else "")
        + "Solve the exact problem\n"
        + command(
            {
                "kind": "draft_issue",
                "author_agent_id": draft.author_agent_id,
                "author_binding_id": draft.author_binding_id,
                "author_binding_version": 1,
                "max_bank_wea": 100,
            }
        )
    )
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    sources = [
        raw(
            body,
            draft.issue_id,
            draft.issue_revision_id,
            draft.creator_github_account_id,
            draft.effective_at,
            kind="issue",
        )
    ]
    assessment = support.assessment()
    for snapshot, sid, rid, actor, at in (
        (
            assessment.assignment_snapshot,
            assessment.assignment_source_comment_id,
            assessment.assignment_source_revision_id,
            assessment.agent0_github_account_id,
            assessment.assignment_effective_at,
        ),
        (
            assessment.snapshot,
            assessment.source_comment_id,
            assessment.source_revision_id,
            assessment.reviewer_github_account_id,
            assessment.effective_at,
        ),
        (
            assessment.completion_snapshot,
            assessment.completion_source_comment_id,
            assessment.completion_source_revision_id,
            assessment.agent0_github_account_id,
            assessment.completion_effective_at,
        ),
    ):
        data = json.loads(snapshot)
        if "body_hash" in data:
            data["body_hash"] = body_hash
        sources.append(raw(command(data), sid, rid, actor, at))
    intake = support.modules()["intake"]
    stage = intake.PlanStage(
        key="audit",
        depth="explore",
        mode="flat_pod",
        schedule=intake.StageSchedule(intake_seconds=86400),
        allocation_wea=100,
        config={
            "slots": 5,
            "additive": True,
            "payout_vector": [20] * 5,
            "acceptance": {"kind": "author"},
        },
        expected_output="Useful newcomer audit",
    )
    plan = support.plan_revision(plan_stages=(stage,))
    data = json.loads(plan.snapshot)
    data["body_hash"] = body_hash
    sources.append(
        raw(
            command(data),
            plan.source_comment_id,
            plan.source_revision_id,
            plan.proposer_github_account_id,
            plan.effective_at,
        )
    )
    content = {key: value for key, value in data.items() if key != "kind"}
    decision = support.decision(plan)
    data = json.loads(decision.snapshot)
    data["plan_content_hash"] = digest(content)
    for key in ("decision_id", "idempotency_key", "author_github_account_id"):
        data.pop(key)
    sources.append(
        raw(
            command(data),
            decision.source_comment_id,
            decision.source_revision_id,
            decision.author_github_account_id,
            decision.effective_at,
        )
    )
    return sources, decision.effective_at + timedelta(minutes=1)


def bootstrap():
    return {
        "runtime": list(installed_executor("0.9.0").reference),
        "repository_id": "repository-1",
        "identities": support.registry().to_data(),
        "balances": {"agent-author": 200, "treasury": 100},
    }


def batch(engine, sources, cutoff, merges=None):
    return {
        "sequence": engine.sequence + 1,
        "previous_hash": engine.last_hash,
        "batch_id": f"tide-{engine.sequence + 1}",
        "funding_merges": merges or {},
        "collection": {"cutoff": cutoff.isoformat(), "sources": sources},
    }


def funded():
    sources, cutoff = setup_sources()
    engine = Replay(bootstrap())
    first = batch(engine, sources, cutoff)
    state = engine.apply(first)
    assert state["escrow_wea"] == 100, state["dispositions"]
    assert state["balances"]["agent-author"] == 100
    return engine, first, cutoff


def test_raw_intake_funds_once_and_replays_from_json():
    engine, first, cutoff = funded()
    second = batch(
        engine, first["collection"]["sources"], cutoff + timedelta(minutes=3)
    )
    expected = engine.apply(second)
    assert expected["escrow_wea"] == 100
    actual = replay(
        json.loads(canonical(bootstrap())), json.loads(canonical([first, second]))
    )
    assert actual == expected


def test_deeply_nested_declaration_cannot_block_independent_funding():
    sources, cutoff = setup_sources()
    malformed = raw(
        MARKER + "[" * 5000 + "0" + "]" * 5000,
        "malformed-comment",
        "malformed-revision",
        "account-alpha",
        cutoff - timedelta(seconds=1),
    )
    engine = Replay(bootstrap())
    state = engine.apply(batch(engine, [*sources, malformed], cutoff))
    assert state["escrow_wea"] == 100
    assert state["dispositions"]["malformed-revision"]["status"] == "unresolved"
    assert "nesting" in state["dispositions"]["malformed-revision"]["reason"]


def test_unfunded_draft_revision_replaces_stale_intake_without_money_effects():
    sources, cutoff = setup_sources()
    engine = Replay(bootstrap())
    engine.apply(batch(engine, sources[:-1], cutoff))
    assert engine.intakes["issue-42"].plan_revisions
    changed = dict(sources[0])
    changed["body"] = changed["body"].replace(
        "Solve the exact problem", "Solve the revised problem"
    )
    changed["content_hash"] = hashlib.sha256(changed["body"].encode()).hexdigest()
    changed["revision_id"] = "revised-draft"
    changed["effective_at"] = (cutoff + timedelta(minutes=1)).isoformat()
    state = engine.apply(batch(engine, [changed], cutoff + timedelta(minutes=2)))
    assert engine.drafts["issue-42"].issue_revision_id == "revised-draft"
    assert not engine.intakes["issue-42"].plan_revisions
    assert state["balances"] == bootstrap()["balances"]
    assert state["escrow_wea"] == 0


def test_missing_intermediate_issue_body_blocks_clock_settlement():
    engine, first, cutoff = funded()
    restored = dict(first["collection"]["sources"][0])
    restored["revision_id"] = "restored-body"
    restored["effective_at"] = (cutoff + timedelta(minutes=3)).isoformat()
    restored["edit_history"] = [
        {
            "revision_id": "unobserved-change",
            "effective_at": (cutoff + timedelta(minutes=2)).isoformat(),
        },
        {"revision_id": "restored-body", "effective_at": restored["effective_at"]},
    ]
    state = engine.apply(
        batch(
            engine,
            [restored],
            cutoff + timedelta(days=10),
            {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()},
        )
    )
    assert state["escrow_wea"] == 100
    assert state["dispositions"]["restored-body"]["status"] == "unresolved"
    assert not engine.runtimes["issue-42"].events


def test_exact_work_event_retry_is_idempotent_inside_the_executor():
    engine, _, cutoff = funded()
    merge_at = cutoff + timedelta(minutes=1)
    engine.apply(
        batch(
            engine,
            [work(merge_at + timedelta(minutes=1))],
            cutoff + timedelta(minutes=3),
            {"tide-1": merge_at.isoformat()},
        )
    )
    state = engine.runtimes["issue-42"]
    event = next(item for item in state.events if item.kind == "work_revision")
    evidence, _ = engine._evidence(cutoff + timedelta(minutes=3))
    repeated = engine.modules["lifecycle"].call_verified(
        "apply_lifecycle_event",
        state,
        event,
        registry=engine.registry,
        github_state=evidence,
        funding_merged_at=merge_at,
    )
    assert repeated is state


def work(at):
    result = raw(
        "### Декларация WEA\n- agent_id: agent-alpha\n- type: deliverable\n"
        "- source: https://github.com/WeTheAgents/wetheagents/blob/"
        + "a" * 40
        + "/audit.md",
        "work-comment",
        "work-revision",
        "account-alpha",
        at,
    )
    result["artifact"] = {
        "source": result["body"].split("- source: ")[1],
        "text": "A useful newcomer audit",
        "sha256": hashlib.sha256(b"A useful newcomer audit").hexdigest(),
    }
    return result


def test_work_acceptance_derives_payment_and_retains_raw_comment():
    engine, first, cutoff = funded()
    merge_at = cutoff + timedelta(minutes=1)
    work_source = work(merge_at + timedelta(minutes=1))
    second = batch(
        engine,
        [work_source],
        cutoff + timedelta(minutes=4),
        {"tide-1": merge_at.isoformat()},
    )
    state = engine.apply(second)
    assert state["dispositions"]["work-revision"]["status"] == "accepted", state[
        "dispositions"
    ]
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
        "accept-comment",
        "accept-revision",
        "account-author",
        cutoff + timedelta(minutes=5),
    )
    third = batch(
        engine,
        [acceptance],
        cutoff + timedelta(minutes=6),
        {"tide-1": merge_at.isoformat()},
    )
    state = engine.apply(third)
    assert state["balances"].get("agent-alpha") == 20, state["dispositions"]
    assert state["escrow_wea"] == 80
    assert replay(bootstrap(), [first, second, third]) == state
    assert engine.sources["work-revision"]["body"] == work_source["body"]


@pytest.mark.parametrize("with_merge", [False, True])
def test_pre_funding_work_cannot_be_laundered_by_a_later_tide(with_merge):
    engine, _, cutoff = funded()
    merge_at = cutoff + timedelta(minutes=2)
    item = work(cutoff + timedelta(minutes=1))
    state = engine.apply(
        batch(
            engine,
            [item],
            cutoff + timedelta(minutes=3),
            {"tide-1": merge_at.isoformat()} if with_merge else {},
        )
    )
    assert state["dispositions"]["work-revision"]["status"] == "unresolved"
    assert state["escrow_wea"] == 100
    assert "agent-alpha" not in state["balances"]


def test_clock_expires_unfilled_task_without_a_fictitious_github_comment():
    engine, first, cutoff = funded()
    second = batch(
        engine,
        [],
        cutoff + timedelta(days=2),
        {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()},
    )
    state = engine.apply(second)
    assert state["escrow_wea"] == 0
    assert state["balances"]["agent-author"] == 200
    assert state["tasks"]["issue-42"]["plan_status"] == "completed"
    assert len(engine.sources) == len(first["collection"]["sources"])
    assert engine.runtimes["issue-42"].events[-1].actor_id == "tide@system"
    assert replay(bootstrap(), [first, second]) == state


def test_common_control_is_confirmed_from_a_real_authorized_source():
    config = bootstrap()
    for binding in config["identities"]["control_group_bindings"]:
        if binding["agent_id"] == "agent-alpha":
            binding["control_group_id"] = "owner-author"
    engine = Replay(config)
    sources, cutoff = setup_sources()
    first = batch(engine, sources, cutoff)
    engine.apply(first)
    merges = {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()}
    engine.apply(
        batch(
            engine,
            [work(cutoff + timedelta(minutes=2))],
            cutoff + timedelta(minutes=3),
            merges,
        )
    )
    lifecycle = engine.modules["lifecycle"]
    disclosure = (
        lifecycle.project_runtime(engine.runtimes["issue-42"])
        .current_stage.works[0]
        .authority.disclosure
    )
    assert disclosure is not None and not disclosure.confirmed
    wrong = raw(
        disclosure.expected_snapshot,
        "wrong-disclosure",
        "wrong-disclosure-r1",
        "account-gamma",
        cutoff + timedelta(minutes=4),
    )
    state = engine.apply(batch(engine, [wrong], cutoff + timedelta(minutes=5), merges))
    assert state["dispositions"]["wrong-disclosure-r1"]["status"] == "unresolved"
    correct = raw(
        disclosure.expected_snapshot,
        "disclosure",
        "disclosure-r1",
        "account-alpha",
        cutoff + timedelta(minutes=6),
    )
    state = engine.apply(
        batch(engine, [correct], cutoff + timedelta(minutes=7), merges)
    )
    assert state["dispositions"]["disclosure-r1"]["status"] == "accepted"
    assert (
        lifecycle.project_runtime(engine.runtimes["issue-42"])
        .current_stage.works[0]
        .authority.disclosure.confirmed
    )
    assert state["escrow_wea"] == 100


def another_task(sources, suffix):
    mapping = {
        source[key]: source[key] + suffix
        for source in sources
        for key in ("object_id", "revision_id")
    }
    encoded = json.dumps(sources)
    for old in sorted(mapping, key=len, reverse=True):
        encoded = encoded.replace(old, mapping[old])
    result = json.loads(encoded)
    plan = next(
        source for source in result if '"resolution_plan_revision"' in source["body"]
    )
    content = json.loads(plan["body"].split(MARKER)[1])
    content.pop("kind")
    approval = result[-1]
    data = json.loads(approval["body"].split(MARKER)[1])
    data["plan_content_hash"] = digest(content)
    approval["body"] = command(data)
    for source in result:
        source["content_hash"] = hashlib.sha256(source["body"].encode()).hexdigest()
    return result


def test_one_batch_funds_two_tasks_and_rejects_a_third_overspend():
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources()
    combined = sources + another_task(sources, "-two") + another_task(sources, "-three")
    first = batch(engine, combined, cutoff)
    state = engine.apply(first)
    assert state["escrow_wea"] == 200, state["dispositions"]
    assert state["balances"]["agent-author"] == 0
    assert len(state["tasks"]) == 2
    assert any(
        item["status"] == "unresolved" and "money:" in item["reason"]
        for item in state["dispositions"].values()
    )
    assert replay(bootstrap(), [first]) == state


def test_a_comment_cannot_impersonate_the_tide_clock():
    engine, _, cutoff = funded()
    current = engine.modules["lifecycle"].project_runtime(engine.runtimes["issue-42"])
    source = raw(
        command(
            {
                "kind": "lifecycle",
                "event": "mode_expiry",
                "actor_kind": "tide",
                "actor_id": "tide@system",
                "plan_id": current.plan_id,
                "payload": {"contract_id": current.current_stage.contract.contract_id},
            }
        ),
        "forged-clock",
        "forged-clock-r1",
        "account-author",
        cutoff + timedelta(minutes=3),
    )
    state = engine.apply(
        batch(
            engine,
            [source],
            cutoff + timedelta(minutes=4),
            {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()},
        )
    )
    assert state["dispositions"]["forged-clock-r1"]["status"] == "unresolved"
    assert state["escrow_wea"] == 100


def test_pre_funding_work_does_not_block_fresh_post_funding_work():
    engine, _, cutoff = funded()
    early = work(cutoff + timedelta(minutes=1))
    later = work(cutoff + timedelta(minutes=3))
    later.update(object_id="fresh-work", revision_id="fresh-work-r1")
    state = engine.apply(
        batch(
            engine,
            [early, later],
            cutoff + timedelta(minutes=4),
            {"tide-1": (cutoff + timedelta(minutes=2)).isoformat()},
        )
    )
    assert state["dispositions"]["work-revision"]["status"] == "unresolved"
    assert state["dispositions"]["fresh-work-r1"]["status"] == "accepted"


def test_another_issues_work_does_not_block_this_issues_work():
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources()
    engine.apply(batch(engine, sources + another_task(sources, "-two"), cutoff))
    first = work(cutoff + timedelta(minutes=2))
    second = work(cutoff + timedelta(minutes=3))
    second.update(
        issue_id="issue-42-two", object_id="second-work", revision_id="second-work-r1"
    )
    state = engine.apply(
        batch(
            engine,
            [first, second],
            cutoff + timedelta(minutes=4),
            {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()},
        )
    )
    assert state["dispositions"]["work-revision"]["status"] == "accepted"
    assert state["dispositions"]["second-work-r1"]["status"] == "accepted"


def test_confirmed_exact_revision_resolves_its_earlier_observation():
    engine, _, cutoff = funded()
    merges = {"tide-1": (cutoff + timedelta(minutes=1)).isoformat()}
    unknown = work(cutoff + timedelta(minutes=2))
    unknown.update(revision_id=None, revision_status="requires-edit-evidence")
    state = engine.apply(
        batch(engine, [unknown], cutoff + timedelta(minutes=3), merges)
    )
    assert any(
        item["status"] == "unresolved" for item in state["dispositions"].values()
    )
    confirmed = dict(unknown, revision_id="confirmed-edit", revision_status="confirmed")
    state = engine.apply(
        batch(engine, [confirmed], cutoff + timedelta(minutes=4), merges)
    )
    assert state["dispositions"]["confirmed-edit"]["status"] == "accepted"
    assert any(item["status"] == "resolved" for item in state["dispositions"].values())


def test_unauthorized_copy_of_triage_source_does_not_block_real_completion():
    engine = Replay(bootstrap())
    sources, cutoff = setup_sources()
    copied = dict(
        sources[1],
        object_id="copied-assignment",
        revision_id="copied-assignment-r1",
        actor_account_id="unbound-account",
    )
    state = engine.apply(batch(engine, [*sources, copied], cutoff))
    assert state["escrow_wea"] == 100, state["dispositions"]
