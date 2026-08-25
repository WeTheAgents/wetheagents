from __future__ import annotations

from copy import deepcopy

import pytest

from wea_vnext.block9.common import Block9Error, sha256_hex
from wea_vnext.block9.migration import (
    ConversionAuthorityBinding,
    activate_conversion_intent,
    build_conversion_approval_body,
    create_conversion_intent,
    freeze_input_bundle,
    reconcile_obligations,
)


def _payload() -> dict[str, object]:
    return {
        "boundary_id": "boundary-1",
        "predecessor": "a" * 40,
        "source_hashes": {"ledger": "b" * 64, "github": "c" * 64},
        "github_pages": [
            {
                "cursor": "page-1",
                "next_cursor": None,
                "complete": True,
                "issues": [
                    {
                        "issue_id": "issue-1",
                        "revision_hash": "d" * 64,
                        "is_pull_request": False,
                        "is_v1_obligation": True,
                        "unfinished": True,
                        "closure_records": [
                            {
                                "outcome": "settle-v1",
                                "source_id": "ledger-history:issue-1:settlement",
                                "source_revision_hash": "4" * 64,
                            },
                            {
                                "outcome": "stop/refund",
                                "source_id": "ledger-history:issue-1:refund",
                                "source_revision_hash": "4" * 64,
                            },
                            {
                                "outcome": "convert-with-fresh-approval",
                                "source_id": "ledger-history:issue-1:conversion-close",
                                "source_revision_hash": "f" * 64,
                            },
                            {
                                "outcome": "historical-close",
                                "source_id": "ledger-history:issue-1:historical-close",
                                "source_revision_hash": "4" * 64,
                            },
                        ],
                        "approval_revisions": [
                            {
                                "source_id": "github-comment-7",
                                "revision_id": "comment-revision-1",
                                "account_id": "alice-gh",
                                "agent_id": "alice",
                                "body_hash": "2" * 64,
                                "confirmed_read_hash": "3" * 64,
                                "effective_at": "2026-08-22T00:00:00Z",
                            }
                        ],
                    },
                    {
                        "issue_id": "issue-2",
                        "revision_hash": "e" * 64,
                        "is_pull_request": False,
                        "is_v1_obligation": False,
                        "unfinished": False,
                        "closure_records": [],
                        "approval_revisions": [],
                    },
                ],
            }
        ],
        "local_records": [
            {
                "record_id": "task-1",
                "issue_id": "issue-1",
                "deposited": 10,
                "payments": 6,
                "refunds": 4,
                "active_escrow": 0,
            }
        ],
        "pending_payments": [],
        "balances": {"alice": 100, "agent0@system": 0},
        "signed_supply": 100,
        "identities": {"alice": {"account": "alice-gh"}},
        "authority_bindings": [
            {
                "agent_id": "alice",
                "account_id": "alice-gh",
                "binding_id": "alice-binding",
                "binding_version": 1,
                "binding_hash": "1" * 64,
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_until": "2026-09-01T00:00:00Z",
            }
        ],
        "genomes": {"alice": {"revision": 2}},
        "hello_world_keys": ["hello-1"],
        "history_refs": ["v1-event-1"],
        "gauntlet_history": [{"mint": 20}],
        "achievement_history": [{"award": "first"}],
    }


def _conversion_fields() -> dict[str, object]:
    payload = _payload()
    fields: dict[str, object] = {
        "source_issue": "issue-1",
        "source_revision_hash": "d" * 64,
        "v1_closure_hash": "f" * 64,
        "author_agent_id": "alice",
        "payer_agent_id": "alice",
        "account_id": "alice-gh",
        "authority_binding_id": "alice-binding",
        "authority_binding_version": 1,
        "authority_binding_hash": "1" * 64,
        "authority_valid_from": "2026-08-01T00:00:00Z",
        "authority_valid_until": "2026-09-01T00:00:00Z",
        "plan": {
            "title": "Migration plan",
            "stages": [{"task": "first", "contract": "child-1"}],
        },
        "plan_bank": 25,
        "triage_revision": "triage-1",
        "ruleset_identity": "ruleset-0.8",
        "runtime": {"python": "3.13", "executor": "0.8.0", "ruleset": "0.8"},
        "approval_source": "github-comment-7",
        "approval_revision": "comment-revision-1",
        "confirmed_read_hash": "3" * 64,
        "issued_at": "2026-08-22T00:00:00Z",
        "expires_at": "2026-08-23T00:00:00Z",
        "idempotency_key": "convert-issue-1",
    }
    body = build_conversion_approval_body(
        {
            "source_issue": fields["source_issue"],
            "source_revision_hash": fields["source_revision_hash"],
            "v1_closure_hash": fields["v1_closure_hash"],
            "author_payer_agent_id": fields["author_agent_id"],
            "account_id": fields["account_id"],
            "authority_binding_id": fields["authority_binding_id"],
            "authority_binding_version": fields["authority_binding_version"],
            "authority_binding_hash": fields["authority_binding_hash"],
            "authority_valid_from": fields["authority_valid_from"],
            "authority_valid_until": fields["authority_valid_until"],
            "plan": fields["plan"],
            "plan_bank": fields["plan_bank"],
            "triage_revision": fields["triage_revision"],
            "ruleset_identity": fields["ruleset_identity"],
            "runtime": fields["runtime"],
            "issued_at": fields["issued_at"],
            "expires_at": fields["expires_at"],
            "idempotency_key": fields["idempotency_key"],
        }
    )
    approval_hash = sha256_hex(body)
    payload["github_pages"][0]["issues"][0]["approval_revisions"][0][  # type: ignore[index]
        "body_hash"
    ] = approval_hash
    fields["approval_hash"] = approval_hash
    fields["bundle"] = freeze_input_bundle(payload)
    return fields


def _authorities() -> tuple[ConversionAuthorityBinding, ...]:
    return (
        ConversionAuthorityBinding(
            agent_id="alice",
            account_id="alice-gh",
            binding_id="alice-binding",
            binding_version=1,
            binding_hash="1" * 64,
            effective_from="2026-08-01T00:00:00Z",
            effective_until="2026-09-01T00:00:00Z",
        ),
    )


def test_incomplete_github_pagination_blocks_reconciliation() -> None:
    payload = _payload()
    payload["github_pages"][0]["complete"] = False  # type: ignore[index]
    with pytest.raises(Block9Error, match="GitHub pagination is incomplete"):
        freeze_input_bundle(payload)


def test_frozen_balance_and_escrow_total_must_equal_signed_supply() -> None:
    payload = _payload()
    payload["balances"]["alice"] = 101  # type: ignore[index]
    with pytest.raises(Block9Error, match="equal signed supply"):
        freeze_input_bundle(payload)


def test_outcome_must_bind_an_exact_frozen_closure_record() -> None:
    bundle = freeze_input_bundle(_payload())
    with pytest.raises(Block9Error, match="not frozen evidence"):
        reconcile_obligations(
            bundle,
            {"issue-1": {"outcome": "stop/refund", "closure_hash": "9" * 64}},
        )


def test_missing_inverse_issue_link_blocks_reconciliation() -> None:
    payload = _payload()
    payload["local_records"][0]["issue_id"] = "missing"  # type: ignore[index]
    bundle = freeze_input_bundle(payload)
    with pytest.raises(Block9Error, match="local record has no captured Issue"):
        reconcile_obligations(
            bundle,
            {"issue-1": {"outcome": "stop/refund", "closure_hash": "4" * 64}},
        )


def test_local_reference_cannot_be_hidden_by_not_obligation_classification() -> None:
    payload = _payload()
    payload["github_pages"][0]["issues"][0]["is_v1_obligation"] = False  # type: ignore[index]
    with pytest.raises(Block9Error, match="locally referenced Issue"):
        reconcile_obligations(freeze_input_bundle(payload), {})


def test_every_obligation_needs_one_money_complete_outcome() -> None:
    invalid = _payload()
    invalid["local_records"][0]["refunds"] = 3  # type: ignore[index]
    with pytest.raises(Block9Error, match="money does not reconcile"):
        reconcile_obligations(
            freeze_input_bundle(invalid),
            {"issue-1": {"outcome": "stop/refund", "closure_hash": "4" * 64}},
        )
    bundle = freeze_input_bundle(_payload())
    report = reconcile_obligations(
        bundle,
        {
            "issue-1": {
                "outcome": "convert-with-fresh-approval",
                "closure_hash": "f" * 64,
            }
        },
    )
    assert report.outcomes[0].issue_id == "issue-1"
    assert report.unexplained_amount == 0


def test_money_cannot_net_across_records_and_historical_close_needs_zero_money() -> (
    None
):
    payload = _payload()
    second = deepcopy(payload["local_records"][0])  # type: ignore[index]
    second["record_id"] = "task-2"
    payload["local_records"][0]["payments"] = 10  # type: ignore[index]
    second["payments"] = 2
    payload["local_records"].append(second)  # type: ignore[union-attr]
    bundle = freeze_input_bundle(payload)
    outcome = {"issue-1": {"outcome": "stop/refund", "closure_hash": "4" * 64}}
    with pytest.raises(Block9Error, match="per record"):
        reconcile_obligations(bundle, outcome)
    with pytest.raises(Block9Error, match="cannot hide financial activity"):
        reconcile_obligations(
            freeze_input_bundle(_payload()),
            {
                "issue-1": {
                    "outcome": "historical-close",
                    "closure_hash": "4" * 64,
                }
            },
        )


def test_conversion_intent_binds_fresh_authenticated_source_and_is_one_shot() -> None:
    intent = create_conversion_intent(**_conversion_fields())
    assert intent.state == "pending"
    assert intent.plan_hash
    activated, state = activate_conversion_intent(
        intent,
        balances={"alice": 100},
        authority_bindings=_authorities(),
        effective_at="2026-08-22T01:00:00Z",
    )
    assert activated.state == "consumed"
    assert state.balances["alice"] == 75
    assert state.program_escrows[activated.intent_id] == 25
    assert state.first_contracts[activated.intent_id]["contract"] == "child-1"
    retry, same = activate_conversion_intent(
        activated,
        balances={"alice": 75},
        authority_bindings=_authorities(),
        effective_at="2026-08-22T01:00:00Z",
        existing=state,
    )
    assert retry == activated
    assert same == state


def test_conversion_cannot_activate_before_its_approval_was_issued() -> None:
    intent = create_conversion_intent(**_conversion_fields())
    with pytest.raises(Block9Error, match="not yet effective"):
        activate_conversion_intent(
            intent,
            balances={"alice": 100},
            authority_bindings=_authorities(),
            effective_at="2026-08-21T23:59:59Z",
        )


def test_conversion_rejects_a_rotated_current_authority_binding() -> None:
    intent = create_conversion_intent(**_conversion_fields())
    rotated = (
        ConversionAuthorityBinding(
            agent_id="alice",
            account_id="alice-gh",
            binding_id="alice-binding",
            binding_version=2,
            binding_hash="9" * 64,
            effective_from="2026-08-22T00:30:00Z",
            effective_until="2026-09-01T00:00:00Z",
        ),
    )
    with pytest.raises(Block9Error, match="binding changed"):
        activate_conversion_intent(
            intent,
            balances={"alice": 100},
            authority_bindings=rotated,
            effective_at="2026-08-22T01:00:00Z",
        )


def test_insufficient_funds_cancels_and_later_balance_does_not_revive() -> None:
    intent = create_conversion_intent(**_conversion_fields())
    cancelled, state = activate_conversion_intent(
        intent,
        balances={"alice": 5},
        authority_bindings=_authorities(),
        effective_at="2026-08-22T01:00:00Z",
    )
    assert cancelled.state == "cancelled"
    assert state.program_escrows == {}
    later, later_state = activate_conversion_intent(
        cancelled,
        balances={"alice": 1000},
        authority_bindings=_authorities(),
        effective_at="2026-08-22T02:00:00Z",
        existing=state,
    )
    assert later == cancelled
    assert later_state == state


def test_mutated_plan_or_wrong_author_payer_rejects() -> None:
    fields = _conversion_fields()
    fields["payer_agent_id"] = "other"
    with pytest.raises(Block9Error, match="author and payer"):
        create_conversion_intent(**fields)
    fields = deepcopy(_conversion_fields())
    fields["plan"]["title"] = "Substituted plan"  # type: ignore[index]
    with pytest.raises(Block9Error, match="bind the exact payload"):
        create_conversion_intent(**fields)
    fields = deepcopy(_conversion_fields())
    fields["confirmed_read_hash"] = "9" * 64
    with pytest.raises(Block9Error, match="authenticated capture"):
        create_conversion_intent(**fields)


def test_synthetic_conversion_approval_not_in_frozen_input_rejects() -> None:
    fields = _conversion_fields()
    fields["approval_source"] = "caller-generated"
    with pytest.raises(Block9Error, match="not in the frozen input"):
        create_conversion_intent(**fields)


def test_conversion_idempotency_key_conflict_cannot_create_a_second_plan() -> None:
    first = create_conversion_intent(**_conversion_fields())
    consumed, state = activate_conversion_intent(
        first,
        balances={"alice": 100},
        authority_bindings=_authorities(),
        effective_at="2026-08-22T01:00:00Z",
    )
    fields = _conversion_fields()
    fields["idempotency_key"] = first.idempotency_key
    fields["plan"]["title"] = "Different plan"  # type: ignore[index]
    approval_values = {
        key: fields[key]
        for key in (
            "source_issue",
            "source_revision_hash",
            "v1_closure_hash",
            "account_id",
            "authority_binding_id",
            "authority_binding_version",
            "authority_binding_hash",
            "authority_valid_from",
            "authority_valid_until",
            "plan",
            "plan_bank",
            "triage_revision",
            "ruleset_identity",
            "runtime",
            "issued_at",
            "expires_at",
            "idempotency_key",
        )
    }
    approval_values["author_payer_agent_id"] = fields["author_agent_id"]
    body_hash = sha256_hex(build_conversion_approval_body(approval_values))
    payload = _payload()
    payload["github_pages"][0]["issues"][0]["approval_revisions"][0][  # type: ignore[index]
        "body_hash"
    ] = body_hash
    fields["bundle"] = freeze_input_bundle(payload)
    fields["approval_hash"] = body_hash
    second = create_conversion_intent(**fields)
    with pytest.raises(Block9Error, match="idempotency record conflicts"):
        activate_conversion_intent(
            second,
            balances=state.balances,
            authority_bindings=_authorities(),
            effective_at="2026-08-22T01:00:00Z",
            existing=state,
        )
    retry, same = activate_conversion_intent(
        first,
        balances=state.balances,
        authority_bindings=_authorities(),
        effective_at="2026-08-22T01:00:00Z",
        existing=state,
    )
    assert retry == consumed
    assert same == state
