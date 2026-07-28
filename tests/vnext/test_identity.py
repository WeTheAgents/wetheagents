from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from wea_vnext import declarations as public_declarations
from wea_vnext.engine import installed_executor
from wea_vnext.identity import (
    Binding,
    ControlDisclosure,
    ControlGroupBinding,
    DeclarationError,
    GitHubAccount,
    IdentityError,
    IdentityRegistry,
    authorize_agent,
    authorize_issue_author,
    authorize_manual_declaration,
    control_disclosure_requirement,
    select_cli_authority,
)
from wea_vnext.migration import (
    IdentityMigrationPlan,
    V1IdentityEvidence,
    restore_v1_identity,
)

NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def test_block_3_preserves_every_prior_executor_triple() -> None:
    old = installed_executor("0.6.0").reference
    initial_block_2 = installed_executor("0.6.1").reference
    final_block_2 = installed_executor("0.6.2").reference
    current = installed_executor("0.6.3").reference

    assert old.executor_manifest_hash == (
        "8d2a71e15be535abbbd19eeb4c2b8909f29055f26c87989b26c3826c9f92b6b3"
    )
    assert initial_block_2.executor_manifest_hash == (
        "dc8298657c13202350d9394e9d198c6a0746dd9bbb230c48a254cad38cd7f2b2"
    )
    assert final_block_2.executor_manifest_hash == (
        "975b071d5bb49e14afd71d5b9c07d6113750884c1a9cc9c9b487324b71b100c7"
    )
    assert current.executor_manifest_hash == (
        "46cf69d39af1fcb4265ef0a51683a0af2156e4649da52c369d5a8a142abf84df"
    )
    assert current != old
    assert current != initial_block_2
    assert current != final_block_2


def _registry(*, revoked_at: datetime | None = None) -> IdentityRegistry:
    return IdentityRegistry(
        accounts=(
            GitHubAccount("account-owner", "owner", "agent-author"),
            GitHubAccount("account-worker", "worker", "agent-worker"),
            GitHubAccount("account-other", "other", "agent-other"),
        ),
        bindings=(
            Binding(
                "map-author",
                "agent",
                "account-owner",
                "agent-author",
                1,
                NOW - timedelta(days=10),
            ),
            Binding(
                "map-worker",
                "agent",
                "account-worker",
                "agent-worker",
                1,
                NOW - timedelta(days=10),
                revoked_at,
            ),
            Binding(
                "map-worker-alt",
                "agent",
                "account-worker",
                "agent-worker-alt",
                1,
                NOW - timedelta(days=5),
            ),
            Binding(
                "map-other",
                "agent",
                "account-other",
                "agent-other",
                1,
                NOW - timedelta(days=10),
            ),
        ),
        control_group_bindings=(
            ControlGroupBinding(
                "group-author",
                "agent-author",
                "shared-owner",
                1,
                NOW - timedelta(days=10),
            ),
            ControlGroupBinding(
                "group-worker",
                "agent-worker",
                "shared-owner",
                1,
                NOW - timedelta(days=10),
            ),
            ControlGroupBinding(
                "group-worker-alt",
                "agent-worker-alt",
                "shared-owner",
                1,
                NOW - timedelta(days=5),
            ),
            ControlGroupBinding(
                "group-other",
                "agent-other",
                "independent-owner",
                1,
                NOW - timedelta(days=10),
            ),
        ),
    )


def test_s_03d_manual_declaration_uses_the_named_linked_agent() -> None:
    assert DeclarationError is public_declarations.DeclarationError

    authority = authorize_manual_declaration(
        "\n".join(
            (
                "### Декларация WEA",
                "- agent_id: `agent-worker-alt`",
                "- type: `deliverable`",
                "- source: `https://example.invalid/pr/7`",
            )
        ),
        github_account_id="account-worker",
        effective_at=NOW,
        registry=_registry(),
    )

    assert authority.agent_id == "agent-worker-alt"
    assert authority.account_binding_id == "map-worker-alt"
    assert authority.control_group_id == "shared-owner"
    assert authority.effective_at == NOW


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("- type: `deliverable`", "agent_id"),
        ("- agent_id: `unknown`", "exactly one"),
        ("- agent_id: `agent-other`", "exactly one"),
    ],
)
def test_s_03d_manual_declaration_rejects_missing_unknown_or_foreign_agent(
    line: str, message: str
) -> None:
    with pytest.raises(IdentityError, match=message):
        authorize_manual_declaration(
            f"### Декларация WEA\n{line}",
            github_account_id="account-worker",
            effective_at=NOW,
            registry=_registry(),
        )


def test_s_03d_issue_form_uses_the_same_identity_validator() -> None:
    authority = authorize_issue_author(
        author_agent_id="agent-worker",
        github_account_id="account-worker",
        effective_at=NOW,
        registry=_registry(),
    )

    assert authority.agent_id == "agent-worker"
    assert authority.account_binding_version == 1
    assert len(_registry().state_hash) == 64
    assert _registry().to_data()["accounts"][0]["github_account_id"] == (
        "account-other"
    )


@pytest.mark.parametrize(
    "selected",
    [
        (),
        ("map-worker", "map-worker-alt"),
        ("map-worker", "unknown"),
        ("map-worker", "map-worker"),
    ],
)
def test_s_03e_cli_requires_one_selected_active_binding(
    selected: tuple[str, ...],
) -> None:
    with pytest.raises(IdentityError, match="exactly one selected active binding"):
        select_cli_authority(
            selected_binding_ids=selected,
            github_account_id="account-worker",
            effective_at=NOW,
            registry=_registry(),
        )


def test_s_03e_cli_uses_its_one_selected_active_binding() -> None:
    authority = select_cli_authority(
        selected_binding_ids=("map-worker-alt",),
        github_account_id="account-worker",
        effective_at=NOW,
        registry=_registry(),
    )

    assert authority.agent_id == "agent-worker-alt"
    assert authority.account_binding_id == "map-worker-alt"


def test_s_03e_agent_authority_ignores_a_parallel_system_role_binding() -> None:
    registry = _registry()
    mixed = IdentityRegistry(
        accounts=registry.accounts,
        bindings=(
            *registry.bindings,
            Binding(
                "map-worker-system",
                "agent0",
                "account-worker",
                "agent-worker",
                1,
                NOW - timedelta(days=10),
            ),
        ),
        control_group_bindings=registry.control_group_bindings,
    )

    authority = authorize_agent(
        github_account_id="account-worker",
        agent_id="agent-worker",
        effective_at=NOW,
        registry=mixed,
    )
    assert authority.account_binding_id == "map-worker"


@pytest.mark.parametrize("field", ["work_id", "stage", "revision"])
def test_s_03e_manual_declaration_rejects_protocol_computed_fields(
    field: str,
) -> None:
    with pytest.raises(DeclarationError, match="computed by the protocol"):
        authorize_manual_declaration(
            "\n".join(
                (
                    "### Декларация WEA",
                    "- agent_id: `agent-worker`",
                    f"- {field}: `forged`",
                )
            ),
            github_account_id="account-worker",
            effective_at=NOW,
            registry=_registry(),
        )


def test_s_03e_revocation_is_evaluated_at_event_time() -> None:
    revoked_at = NOW - timedelta(hours=1)
    registry = _registry(revoked_at=revoked_at)

    historical = authorize_agent(
        github_account_id="account-worker",
        agent_id="agent-worker",
        effective_at=revoked_at - timedelta(seconds=1),
        registry=registry,
    )
    assert historical.agent_id == "agent-worker"

    with pytest.raises(IdentityError, match="exactly one"):
        authorize_agent(
            github_account_id="account-worker",
            agent_id="agent-worker",
            effective_at=NOW,
            registry=registry,
        )


def test_s_03f_same_agent_cannot_participate_in_own_contract() -> None:
    registry = _registry()
    author = authorize_agent(
        github_account_id="account-owner",
        agent_id="agent-author",
        effective_at=NOW,
        registry=registry,
    )

    with pytest.raises(IdentityError, match="same Agent ID"):
        control_disclosure_requirement(
            contract_id="contract-1",
            work_id="work-1",
            author=author,
            participant=author,
            registry=registry,
        )


def test_s_03f_common_control_blocks_selection_until_disclosure_confirmation() -> None:
    registry = _registry()
    author = authorize_agent(
        github_account_id="account-owner",
        agent_id="agent-author",
        effective_at=NOW,
        registry=registry,
    )
    participant = authorize_agent(
        github_account_id="account-worker",
        agent_id="agent-worker",
        effective_at=NOW,
        registry=registry,
    )

    pending = control_disclosure_requirement(
        contract_id="contract-1",
        work_id="work-1",
        author=author,
        participant=participant,
        registry=registry,
    )
    assert pending is not None
    assert pending.author_group_binding_version == 1
    assert pending.participant_group_binding_version == 1
    assert not pending.selection_allowed
    assert not pending.settlement_allowed

    confirmed = pending.confirm(
        revision_id="edit-disclosure-1",
        snapshot=pending.expected_snapshot,
    )
    assert confirmed.selection_allowed
    assert confirmed.settlement_allowed
    assert confirmed.revision_id == "edit-disclosure-1"

    with pytest.raises(IdentityError, match="confirmation must be complete"):
        ControlDisclosure(
            contract_id="contract-1",
            work_id="work-1",
            control_group_id="shared-owner",
            author_agent_id="agent-author",
            participant_agent_id="agent-worker",
            author_group_binding_id="group-author",
            author_group_binding_version=1,
            participant_group_binding_id="group-worker",
            participant_group_binding_version=1,
            effective_at=NOW,
            revision_id="incomplete",
        )

    with pytest.raises(IdentityError, match="exact disclosure content"):
        pending.confirm(
            revision_id="edit-disclosure-2",
            snapshot="Common control: shared-owner",
        )


def test_s_03f_different_control_groups_need_no_disclosure() -> None:
    registry = _registry()
    author = authorize_agent(
        github_account_id="account-owner",
        agent_id="agent-author",
        effective_at=NOW,
        registry=registry,
    )
    participant = authorize_agent(
        github_account_id="account-other",
        agent_id="agent-other",
        effective_at=NOW,
        registry=registry,
    )

    assert (
        control_disclosure_requirement(
            contract_id="contract-1",
            work_id="work-1",
            author=author,
            participant=participant,
            registry=registry,
        )
        is None
    )


def test_s_03f_rejects_authority_not_reproduced_by_the_registry() -> None:
    registry = _registry()
    author = authorize_agent(
        github_account_id="account-owner",
        agent_id="agent-author",
        effective_at=NOW,
        registry=registry,
    )
    participant = authorize_agent(
        github_account_id="account-worker",
        agent_id="agent-worker",
        effective_at=NOW,
        registry=registry,
    )

    forged = replace(participant, control_group_id="independent-owner")
    with pytest.raises(IdentityError, match="does not match registry"):
        control_disclosure_requirement(
            contract_id="contract-1",
            work_id="work-1",
            author=author,
            participant=forged,
            registry=registry,
        )


def test_s_03f_authority_snapshot_survives_later_mapping_change() -> None:
    registry = _registry()
    participant = authorize_agent(
        github_account_id="account-worker",
        agent_id="agent-worker",
        effective_at=NOW,
        registry=registry,
    )
    changed = IdentityRegistry(
        accounts=registry.accounts,
        bindings=tuple(
            Binding(
                item.binding_id,
                item.actor_kind,
                item.github_account_id,
                item.subject_id,
                item.version,
                item.effective_from,
                NOW + timedelta(hours=1)
                if item.binding_id == "map-worker"
                else item.effective_until,
            )
            for item in registry.bindings
        ),
        control_group_bindings=registry.control_group_bindings,
    )

    assert participant.account_binding_id == "map-worker"
    assert participant.control_group_id == "shared-owner"
    assert changed.bindings != registry.bindings


def test_account_registration_is_atomic_idempotent_and_keeps_one_base_agent() -> None:
    account = GitHubAccount("new-account", "new-owner", "new-base")
    account_binding = Binding(
        "new-map-base", "agent", "new-account", "new-base", 1, NOW
    )
    group_binding = ControlGroupBinding(
        "new-group-base", "new-base", "new-owner-group", 1, NOW
    )

    registered = IdentityRegistry().register_agent(
        account=account,
        account_binding=account_binding,
        control_group_binding=group_binding,
    )
    assert registered.account("new-account").base_agent_id == "new-base"
    assert (
        registered.register_agent(
            account=account,
            account_binding=account_binding,
            control_group_binding=group_binding,
        )
        is registered
    )

    with pytest.raises(IdentityError, match="base_agent_id is immutable"):
        registered.register_agent(
            account=GitHubAccount("new-account", "new-owner", "other-agent"),
            account_binding=Binding(
                "new-map-other",
                "agent",
                "new-account",
                "other-agent",
                1,
                NOW,
            ),
            control_group_binding=ControlGroupBinding(
                "new-group-other", "other-agent", "new-owner-group", 1, NOW
            ),
        )

    registry = _registry()
    with pytest.raises(IdentityError, match="overlap"):
        IdentityRegistry(
            accounts=registry.accounts,
            bindings=registry.bindings,
            control_group_bindings=(
                *registry.control_group_bindings,
                ControlGroupBinding(
                    "group-worker-conflict",
                    "agent-worker",
                    "other-group",
                    2,
                    NOW - timedelta(days=1),
                ),
            ),
        )

    with pytest.raises(IdentityError, match="increase over time"):
        IdentityRegistry(
            accounts=registry.accounts,
            bindings=(
                *tuple(
                    item
                    for item in registry.bindings
                    if item.binding_id != "map-worker"
                ),
                Binding(
                    "map-worker-v2",
                    "agent",
                    "account-worker",
                    "agent-worker",
                    2,
                    NOW - timedelta(days=10),
                    NOW - timedelta(days=5),
                ),
                Binding(
                    "map-worker-v1-late",
                    "agent",
                    "account-worker",
                    "agent-worker",
                    1,
                    NOW - timedelta(days=5),
                ),
            ),
            control_group_bindings=registry.control_group_bindings,
        )


def _v1_evidence(
    agent_id: str, *, base_agent_id: str = "agent-base"
) -> V1IdentityEvidence:
    return V1IdentityEvidence(
        github_account_id="account-v1",
        account_owner="legacy-owner",
        base_agent_id=base_agent_id,
        agent_id=agent_id,
        control_group_id="legacy-owner-group",
        account_binding_id=f"map-{agent_id}",
        account_binding_version=1,
        group_binding_id=f"group-{agent_id}",
        group_binding_version=1,
        effective_from=NOW,
        issue_id="I_kwDOIssueOne",
        comment_id=f"comment-{agent_id}",
        revision_id=f"revision-{agent_id}",
        ledger_history_ids=(f"history-{agent_id}",),
        idempotency_keys=(f"register-{agent_id}",),
        aliases=(agent_id, f"legacy-{agent_id}"),
    )


def test_s_09_v1_identity_restoration_uses_all_durable_sources_without_money() -> None:
    plan = restore_v1_identity(
        (_v1_evidence("agent-alt"), _v1_evidence("agent-base"))
    )

    assert len(plan.registry.accounts) == 1
    assert plan.registry.accounts[0].base_agent_id == "agent-base"
    assert {item.subject_id for item in plan.registry.bindings} == {
        "agent-alt",
        "agent-base",
    }
    assert {item.control_group_id for item in plan.registry.control_group_bindings} == {
        "legacy-owner-group"
    }
    assert len(plan.evidence_hash) == 64
    assert plan.ledger_effects == ()

    with pytest.raises(IdentityError, match="hash does not match evidence"):
        IdentityMigrationPlan(plan.registry, plan.evidence, "0" * 64)

    with pytest.raises(IdentityError, match="registry does not match evidence"):
        IdentityMigrationPlan(IdentityRegistry(), plan.evidence, plan.evidence_hash)


def test_s_09_v1_identity_restoration_rejects_unresolved_account_evidence() -> None:
    with pytest.raises(IdentityError, match="disagrees"):
        restore_v1_identity(
            (
                _v1_evidence("agent-base"),
                _v1_evidence("agent-alt", base_agent_id="agent-alt"),
            )
        )

    with pytest.raises(IdentityError, match="durable source IDs"):
        V1IdentityEvidence(
            **{
                **_v1_evidence("agent-base").__dict__,
                "idempotency_keys": (),
            }
        )


def test_s_09_v1_identity_evidence_ids_are_globally_single_use() -> None:
    first = _v1_evidence("agent-base")
    second = replace(
        first,
        github_account_id="account-v1-other",
        account_owner="legacy-owner-other",
        base_agent_id="agent-other",
        agent_id="agent-other",
        control_group_id="legacy-owner-group-other",
        account_binding_id="map-agent-other",
        group_binding_id="group-agent-other",
    )

    with pytest.raises(IdentityError, match="source ID is reused"):
        restore_v1_identity((first, second))
