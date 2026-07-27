from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.hello_world import (
    Agent0HelloWorldDecision,
    HelloWorldError,
    HelloWorldState,
    SystemHelloWorldContract,
    accept_unique_hello_world,
    create_agent0_hello_world_decision,
    create_hello_world_submission,
    restore_v1_hello_world,
)
from wea_vnext.identity import (
    Binding,
    ControlGroupBinding,
    GitHubAccount,
    IdentityRegistry,
    authorize_agent,
)

pytestmark = pytest.mark.skip(
    reason="requires the authenticated canonical Issue #1 snapshot"
)

NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def _identity() -> IdentityRegistry:
    return IdentityRegistry(
        accounts=(GitHubAccount("account-1", "owner", "agent-base"),),
        bindings=(
            Binding(
                "map-base",
                "agent",
                "account-1",
                "agent-base",
                1,
                NOW - timedelta(days=2),
            ),
            Binding(
                "map-alt",
                "agent",
                "account-1",
                "agent-alt",
                1,
                NOW - timedelta(days=1),
            ),
            Binding(
                "map-agent0",
                "agent0",
                "account-1",
                "agent0@system",
                1,
                NOW - timedelta(days=2),
            ),
        ),
        control_group_bindings=(
            ControlGroupBinding(
                "group-base",
                "agent-base",
                "owner-group",
                1,
                NOW - timedelta(days=2),
            ),
            ControlGroupBinding(
                "group-alt",
                "agent-alt",
                "owner-group",
                1,
                NOW - timedelta(days=1),
            ),
        ),
    )


def _identity_two_accounts() -> IdentityRegistry:
    first = _identity()
    return IdentityRegistry(
        accounts=(
            *first.accounts,
            GitHubAccount("account-2", "owner-2", "agent-base-2"),
        ),
        bindings=(
            *first.bindings,
            Binding(
                "map-base-2",
                "agent",
                "account-2",
                "agent-base-2",
                1,
                NOW - timedelta(days=2),
            ),
        ),
        control_group_bindings=(
            *first.control_group_bindings,
            ControlGroupBinding(
                "group-base-2",
                "agent-base-2",
                "owner-group-2",
                1,
                NOW - timedelta(days=2),
            ),
        ),
    )


def _contract(**changes: object) -> SystemHelloWorldContract:
    runtime = installed_executor("0.6.2").reference
    values: dict[str, object] = {
        "contract_id": "contract-system-hello-world",
        "issue_id": "I_kwDOIssueOne",
        "issue_number": 1,
        "body": "Submit mechanically unique Work.",
        "body_hash": hashlib.sha256(
            b"Submit mechanically unique Work."
        ).hexdigest(),
        "ruleset_hash": runtime.ruleset_hash,
        "tide_interface_version": runtime.tide_interface_version,
        "executor_manifest_hash": runtime.executor_manifest_hash,
    }
    values.update(changes)
    return SystemHelloWorldContract(**values)  # type: ignore[arg-type]


def _submission(agent_id: str = "agent-alt"):
    return create_hello_world_submission(
        contract=_contract(),
        github_account_id="account-1",
        agent_id=agent_id,
        comment_id="IC_kwDOComment",
        revision_id="edit-1",
        snapshot="A mechanically unique contribution",
        normalization_version="mechanical-v1",
        comparison_hash="d" * 64,
        effective_at=NOW,
    )


def _decision(
    submission=None,
    *,
    mechanically_unique: bool = True,
    registry: IdentityRegistry | None = None,
) -> Agent0HelloWorldDecision:
    submission = _submission() if submission is None else submission
    registry = _identity() if registry is None else registry
    unique = "true" if mechanically_unique else "false"
    snapshot = "\n".join(
        (
            "### Декларация WEA",
            "- actor_kind: `agent0`",
            "- agent0_id: `agent0@system`",
            "- action: `accept-hello-world`",
            "- contract_id: `contract-system-hello-world`",
            f"- work_id: `{submission.work_id}`",
            f"- mechanically_unique: `{unique}`",
        )
    )
    return create_agent0_hello_world_decision(
        contract=_contract(),
        work_id=submission.work_id,
        github_account_id="account-1",
        agent0_id="agent0@system",
        comment_id=f"agent0-decision-{submission.agent_id}",
        revision_id=f"agent0-revision-{submission.agent_id}",
        mechanically_unique=mechanically_unique,
        effective_at=NOW,
        snapshot=snapshot,
        registry=registry,
    )


def test_s_09_v1_mint_marks_account_key_used_without_a_ledger_effect() -> None:
    result = restore_v1_hello_world(
        state=HelloWorldState(contract=_contract()),
        contract=_contract(),
        registry=_identity(),
        github_account_id="account-1",
        participant_agent_id="agent-alt",
        issue_id="I_kwDOIssueOne",
        comment_id="IC_kwDOLegacy",
        revision_id="legacy-comment-v1",
        snapshot="Legacy Hello World",
        normalization_version="v1-import",
        comparison_hash="e" * 64,
        ledger_history_id="history:register:agent-base",
        legacy_idempotency_key="register:account-1",
    )

    assert result.outcome == "v1-mint-restored"
    assert result.mint_intent is None
    assert result.ledger_effects == ()
    assert result.state.mint_uses[0].mint_key == "hello-world:account-1"
    assert result.state.mint_uses[0].source == "v1"

    with pytest.raises(HelloWorldError, match="evidence IDs disagree"):
        HelloWorldState(
            contract=_contract(),
            records=result.state.records,
            mint_uses=(
                replace(
                    result.state.mint_uses[0],
                    evidence_ids=(
                        "I_kwDOIssueOne",
                        "other-comment",
                        "other-revision",
                        "history:register:agent-base",
                        "register:account-1",
                    ),
                ),
            ),
        )

    repeated = restore_v1_hello_world(
        state=result.state,
        contract=_contract(),
        registry=_identity(),
        github_account_id="account-1",
        participant_agent_id="agent-alt",
        issue_id="I_kwDOIssueOne",
        comment_id="IC_kwDOLegacy",
        revision_id="legacy-comment-v1",
        snapshot="Legacy Hello World",
        normalization_version="v1-import",
        comparison_hash="e" * 64,
        ledger_history_id="history:register:agent-base",
        legacy_idempotency_key="register:account-1",
    )
    assert repeated.outcome == "already-used"
    assert repeated.state is result.state

    with pytest.raises(HelloWorldError, match="conflicting"):
        restore_v1_hello_world(
            state=result.state,
            contract=_contract(),
            registry=_identity(),
            github_account_id="account-1",
            participant_agent_id="agent-alt",
            issue_id="I_kwDOIssueOne",
            comment_id="IC_kwDOLegacy",
            revision_id="different-revision",
            snapshot="Legacy Hello World",
            normalization_version="v1-import",
            comparison_hash="e" * 64,
            ledger_history_id="history:register:agent-base",
            legacy_idempotency_key="register:account-1",
        )


def test_s_09_v1_mint_evidence_cannot_be_claimed_by_two_accounts() -> None:
    registry = _identity_two_accounts()
    first = restore_v1_hello_world(
        state=HelloWorldState(contract=_contract()),
        contract=_contract(),
        registry=registry,
        github_account_id="account-1",
        participant_agent_id="agent-alt",
        issue_id="I_kwDOIssueOne",
        comment_id="IC_kwDOLegacy",
        revision_id="legacy-comment-v1",
        snapshot="Legacy Hello World",
        normalization_version="v1-import",
        comparison_hash="e" * 64,
        ledger_history_id="history:register:agent-base",
        legacy_idempotency_key="register:account-1",
    )

    with pytest.raises(HelloWorldError, match="evidence ID is reused"):
        restore_v1_hello_world(
            state=first.state,
            contract=_contract(),
            registry=registry,
            github_account_id="account-2",
            participant_agent_id="agent-base-2",
            issue_id="I_kwDOIssueOne",
            comment_id="IC_kwDOLegacy",
            revision_id="legacy-comment-v1",
            snapshot="Legacy Hello World",
            normalization_version="v1-import",
            comparison_hash="e" * 64,
            ledger_history_id="history:register:agent-base",
            legacy_idempotency_key="register:account-1",
        )


def test_s_09b_any_linked_agent_mints_once_to_the_immutable_base_agent() -> None:
    registry = _identity()
    participant = authorize_agent(
        github_account_id="account-1",
        agent_id="agent-alt",
        effective_at=NOW,
        registry=registry,
    )
    first = accept_unique_hello_world(
        state=HelloWorldState(contract=_contract()),
        contract=_contract(),
        submission=_submission(),
        participant=participant,
        decision=_decision(),
        registry=registry,
    )

    assert first.outcome == "mint-planned"
    assert first.mint_intent is not None
    assert first.mint_intent.agent_id == "agent-base"
    assert first.mint_intent.amount_wea == 42
    assert first.mint_intent.idempotency_key == "hello-world:account-1"
    assert first.state.records[0].agent_id == "agent-alt"
    assert len(first.state.state_hash) == 64
    assert first.state.to_data()["mint_uses"][0]["base_agent_id"] == "agent-base"

    with pytest.raises(HelloWorldError, match="Work ID must be protocol-derived"):
        replace(first.state.records[0], work_id="work:forged")

    repeated = accept_unique_hello_world(
        state=first.state,
        contract=_contract(),
        submission=_submission("agent-base"),
        participant=authorize_agent(
            github_account_id="account-1",
            agent_id="agent-base",
            effective_at=NOW,
            registry=registry,
        ),
        decision=_decision(_submission("agent-base")),
        registry=registry,
    )
    assert repeated.outcome == "already-used"
    assert repeated.state is first.state
    assert repeated.ledger_effects == ()


def test_s_09b_non_unique_work_never_creates_registry_or_mint() -> None:
    registry = _identity()
    result = accept_unique_hello_world(
        state=HelloWorldState(contract=_contract()),
        contract=_contract(),
        submission=_submission(),
        participant=authorize_agent(
            github_account_id="account-1",
            agent_id="agent-alt",
            effective_at=NOW,
            registry=registry,
        ),
        decision=_decision(mechanically_unique=False),
        registry=registry,
    )

    assert result.outcome == "not-unique"
    assert result.state == HelloWorldState(contract=_contract())
    assert result.ledger_effects == ()


def test_s_09b_mint_requires_the_authenticated_agent0_decision() -> None:
    registry = _identity()
    submission = _submission()
    forged = replace(_decision(submission), actor_binding_id="forged-agent0-binding")

    with pytest.raises(HelloWorldError, match="authority does not match"):
        accept_unique_hello_world(
            state=HelloWorldState(contract=_contract()),
            contract=_contract(),
            submission=submission,
            participant=authorize_agent(
                github_account_id="account-1",
                agent_id="agent-alt",
                effective_at=NOW,
                registry=registry,
            ),
            decision=forged,
            registry=registry,
        )


def test_s_09c_state_pins_the_single_canonical_system_contract() -> None:
    registry = _identity()
    other = _contract(contract_id="other-contract", issue_id="other-issue-one")
    submission = create_hello_world_submission(
        contract=other,
        github_account_id="account-1",
        agent_id="agent-alt",
        comment_id="other-comment",
        revision_id="other-revision",
        snapshot="Another contribution",
        normalization_version="mechanical-v1",
        comparison_hash="c" * 64,
        effective_at=NOW,
    )

    with pytest.raises(HelloWorldError, match="another system Hello World contract"):
        accept_unique_hello_world(
            state=HelloWorldState(contract=_contract()),
            contract=other,
            submission=submission,
            participant=authorize_agent(
                github_account_id="account-1",
                agent_id="agent-alt",
                effective_at=NOW,
                registry=registry,
            ),
            decision=_decision(submission),
            registry=registry,
        )


def test_s_09c_system_contract_has_no_ordinary_task_or_money_authority() -> None:
    contract = _contract()
    payload = contract.to_data()

    assert contract.status == "active"
    assert payload["kind"] == "system_hello_world"
    assert payload["mechanism"] == "hello-world"
    assert payload["bank_total_wea"] == 0
    assert payload["review_fee_wea"] == 0
    assert not {
        "author_agent_id",
        "payer_agent_id",
        "consent",
        "triage",
        "refund_agent_id",
        "escrow",
    }.intersection(payload)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"issue_number": 2}, "Issue #1"),
        ({"kind": "ordinary"}, "system_hello_world"),
        ({"mechanism": "pod"}, "hello-world"),
        ({"bank_total_wea": 1}, "zero bank"),
        ({"review_fee_wea": 1}, "zero review fee"),
        ({"status": "closed"}, "remain active"),
    ],
)
def test_s_09c_system_contract_rejects_ordinary_task_shapes(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(HelloWorldError, match=message):
        _contract(**changes)


def test_s_09c_direct_import_cannot_forge_verified_runtime_authority() -> None:
    import wea_vnext.executors.v0_6_2 as direct_executor

    with pytest.raises(ValueError, match="requires the manifest verifier"):
        direct_executor._bind_verified_runtime(  # type: ignore[attr-defined]
            ("0" * 64, "forged-interface", "1" * 64),
            object(),
        )


def test_s_09c_acceptance_keeps_the_permanent_contract_active() -> None:
    registry = _identity()
    contract = _contract()
    result = accept_unique_hello_world(
        state=HelloWorldState(contract=contract),
        contract=contract,
        submission=_submission(),
        participant=authorize_agent(
            github_account_id="account-1",
            agent_id="agent-alt",
            effective_at=NOW,
            registry=registry,
        ),
        decision=_decision(),
        registry=registry,
    )

    assert result.contract is contract
    assert result.contract.status == "active"
    assert result.task_effects == ()
    assert result.escrow_effects == ()


def test_hello_world_rejects_foreign_state_subclasses() -> None:
    class ForeignState(HelloWorldState):
        pass

    registry = _identity()
    with pytest.raises(HelloWorldError, match="verified Hello World record type"):
        accept_unique_hello_world(
            state=ForeignState(_contract()),
            contract=_contract(),
            submission=_submission(),
            participant=authorize_agent(
                github_account_id="account-1",
                agent_id="agent-alt",
                effective_at=NOW,
                registry=registry,
            ),
            decision=_decision(),
            registry=registry,
        )
