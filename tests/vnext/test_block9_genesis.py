from __future__ import annotations

from dataclasses import replace

import pytest

from wea_vnext.block9.common import Block9Error, canonical_bytes, sha256_hex
from wea_vnext.block9.migration import (
    ReconciliationReport,
    build_conversion_approval_body,
    build_genesis,
    create_conversion_intent,
    freeze_input_bundle,
    reconcile_obligations,
    replay_genesis,
)

from .test_block9_reconciliation import _conversion_fields, _payload


def test_genesis_is_stable_and_contains_pending_intent_without_money_effect() -> None:
    fields = _conversion_fields()
    bundle = fields["bundle"]
    report = reconcile_obligations(
        bundle,
        {
            "issue-1": {
                "outcome": "convert-with-fresh-approval",
                "closure_hash": "f" * 64,
            }
        },
    )
    intent = create_conversion_intent(**fields)
    first = build_genesis(bundle, report, (intent,))
    second = build_genesis(bundle, report, (intent,))
    assert first == second
    state = replay_genesis(first)
    assert state["balances"] == {"agent0@system": 0, "alice": 100}
    assert state["opening_supply"] == 100
    assert state["conversion_intents"][0]["state"] == "pending"
    assert "program_escrows" not in state
    assert "plans" not in state
    assert "contracts" not in state


def test_genesis_rejects_stale_source_hash() -> None:
    bundle = freeze_input_bundle(_payload())
    report = reconcile_obligations(
        bundle,
        {"issue-1": {"outcome": "stop/refund", "closure_hash": "4" * 64}},
    )
    with pytest.raises(Block9Error, match="reconciliation does not bind the input"):
        build_genesis(bundle, replace(report, input_hash="0" * 64), ())


def test_genesis_rederives_reconciliation_coverage_and_hash() -> None:
    bundle = freeze_input_bundle(_payload())
    payload = {
        "input_hash": bundle.input_hash,
        "outcomes": [],
        "unexplained_amount": 0,
    }
    forged = ReconciliationReport(
        input_hash=bundle.input_hash,
        outcomes=(),
        unexplained_amount=0,
        report_hash=sha256_hex(canonical_bytes(payload)),
    )
    with pytest.raises(Block9Error, match="every unfinished v1 obligation"):
        build_genesis(bundle, forged, ())


def test_genesis_rejects_intent_without_conversion_outcome() -> None:
    fields = _conversion_fields()
    bundle = fields["bundle"]
    report = reconcile_obligations(
        bundle,
        {"issue-1": {"outcome": "stop/refund", "closure_hash": "4" * 64}},
    )
    with pytest.raises(Block9Error, match="does not have a conversion outcome"):
        build_genesis(bundle, report, (create_conversion_intent(**fields),))


def test_genesis_rejects_a_conversion_outcome_without_its_intent() -> None:
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
    with pytest.raises(Block9Error, match="every conversion outcome"):
        build_genesis(bundle, report, ())


def test_genesis_revalidates_conversion_intent_against_frozen_approval() -> None:
    fields = _conversion_fields()
    bundle = fields["bundle"]
    intent = create_conversion_intent(**fields)
    approval_values = {
        "source_issue": intent.source_issue,
        "source_revision_hash": intent.source_revision_hash,
        "v1_closure_hash": intent.v1_closure_hash,
        "author_payer_agent_id": intent.author_payer_agent_id,
        "account_id": intent.account_id,
        "authority_binding_id": intent.authority_binding_id,
        "authority_binding_version": intent.authority_binding_version,
        "authority_binding_hash": intent.authority_binding_hash,
        "authority_valid_from": intent.authority_valid_from,
        "authority_valid_until": intent.authority_valid_until,
        "plan": intent.plan,
        "plan_bank": intent.plan_bank,
        "triage_revision": "forged-triage",
        "ruleset_identity": intent.ruleset_identity,
        "runtime": __import__("json").loads(intent.runtime_bytes),
        "issued_at": intent.issued_at,
        "expires_at": intent.expires_at,
        "idempotency_key": intent.idempotency_key,
    }
    approval_hash = sha256_hex(build_conversion_approval_body(approval_values))
    identifier_values = {
        "source_issue": intent.source_issue,
        "source_revision_hash": intent.source_revision_hash,
        "v1_closure_hash": intent.v1_closure_hash,
        "author_payer_agent_id": intent.author_payer_agent_id,
        "account_id": intent.account_id,
        "authority_binding_id": intent.authority_binding_id,
        "authority_binding_version": intent.authority_binding_version,
        "authority_binding_hash": intent.authority_binding_hash,
        "plan_hash": intent.plan_hash,
        "plan_bank": intent.plan_bank,
        "approval_hash": approval_hash,
        "confirmed_read_hash": intent.confirmed_read_hash,
        "idempotency_key": intent.idempotency_key,
    }
    forged = replace(
        intent,
        intent_id=f"conversion:{sha256_hex(canonical_bytes(identifier_values))}",
        triage_revision="forged-triage",
        approval_hash=approval_hash,
    )
    report = reconcile_obligations(
        bundle,
        {
            "issue-1": {
                "outcome": "convert-with-fresh-approval",
                "closure_hash": "f" * 64,
            }
        },
    )
    with pytest.raises(Block9Error, match="authenticated capture"):
        build_genesis(bundle, report, (forged,))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(identities=[]), "identities"),
        (
            lambda value: value["source_hashes"].update(ledger="not-a-hash"),
            "lowercase hexadecimal hash",
        ),
        (
            lambda value: value["historical"].update(extra=[]),
            "historical fields",
        ),
        (
            lambda value: value["conversion_intents"][0].update(state="consumed"),
            "must remain pending",
        ),
        (
            lambda value: value["conversion_intents"][0].update(
                expires_at=value["conversion_intents"][0]["issued_at"]
            ),
            "interval is not fresh",
        ),
    ],
)
def test_replay_genesis_revalidates_the_complete_payload(mutation, message) -> None:
    fields = _conversion_fields()
    bundle = fields["bundle"]
    report = reconcile_obligations(
        bundle,
        {
            "issue-1": {
                "outcome": "convert-with-fresh-approval",
                "closure_hash": "f" * 64,
            }
        },
    )
    intent = create_conversion_intent(**fields)
    value = __import__("json").loads(build_genesis(bundle, report, (intent,)))
    mutation(value)
    with pytest.raises(Block9Error, match=message):
        replay_genesis(canonical_bytes(value))
