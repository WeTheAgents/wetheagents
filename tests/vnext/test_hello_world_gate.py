from __future__ import annotations

import hashlib

import pytest

from wea_vnext.engine import installed_executor
from wea_vnext.hello_world import (
    HelloWorldError,
    SystemHelloWorldContract,
    accept_unique_hello_world,
    create_agent0_hello_world_decision,
    create_hello_world_submission,
    restore_v1_hello_world,
)


def test_s_09c_fails_closed_until_canonical_issue_snapshot_is_installed() -> None:
    runtime = installed_executor("0.6.3").reference
    body = "Submit mechanically unique Work."

    with pytest.raises(HelloWorldError, match="canonical Issue #1 snapshot"):
        SystemHelloWorldContract(
            contract_id="contract-system-hello-world",
            issue_id="caller-supplied-issue-id",
            issue_number=1,
            body=body,
            body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            ruleset_hash=runtime.ruleset_hash,
            tide_interface_version=runtime.tide_interface_version,
            executor_manifest_hash=runtime.executor_manifest_hash,
        )


def test_s_09c_exported_class_globals_cannot_install_canonical_snapshot() -> None:
    runtime = installed_executor("0.6.3").reference
    body = "attacker-selected-body"
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    method_globals = SystemHelloWorldContract.__post_init__.__globals__
    missing = object()
    original = method_globals.get("_CANONICAL_HELLO_WORLD", missing)
    method_globals["_CANONICAL_HELLO_WORLD"] = (
        "attacker-selected-issue",
        body_hash,
    )

    try:
        with pytest.raises(HelloWorldError, match="canonical Issue #1 snapshot"):
            SystemHelloWorldContract(
                contract_id="attacker-selected-contract",
                issue_id="attacker-selected-issue",
                issue_number=1,
                body=body,
                body_hash=body_hash,
                ruleset_hash=runtime.ruleset_hash,
                tide_interface_version=runtime.tide_interface_version,
                executor_manifest_hash=runtime.executor_manifest_hash,
            )
    finally:
        if original is missing:
            method_globals.pop("_CANONICAL_HELLO_WORLD", None)
        else:
            method_globals["_CANONICAL_HELLO_WORLD"] = original


@pytest.mark.parametrize(
    "operation",
    (
        lambda contract: create_hello_world_submission(
            contract=contract,
            github_account_id="attacker-account",
            agent_id="attacker-agent",
            comment_id="attacker-comment",
            revision_id="attacker-revision",
            snapshot="attacker-work",
            normalization_version="attacker-v1",
            comparison_hash="0" * 64,
            effective_at=None,
        ),
        lambda contract: create_agent0_hello_world_decision(
            contract=contract,
            work_id="attacker-work",
            github_account_id="attacker-account",
            agent0_id="agent0@system",
            comment_id="attacker-comment",
            revision_id="attacker-revision",
            mechanically_unique=True,
            effective_at=None,
            snapshot="attacker-decision",
            registry=None,
        ),
        lambda contract: accept_unique_hello_world(
            state=None,
            contract=contract,
            submission=None,
            participant=None,
            decision=None,
            registry=None,
        ),
        lambda contract: restore_v1_hello_world(
            state=None,
            contract=contract,
            registry=None,
            github_account_id="attacker-account",
            participant_agent_id="attacker-agent",
            issue_id="attacker-issue",
            comment_id="attacker-comment",
            revision_id="attacker-revision",
            snapshot="attacker-work",
            normalization_version="attacker-v1",
            comparison_hash="0" * 64,
            ledger_history_id="attacker-ledger-event",
            legacy_idempotency_key="attacker-idem",
        ),
    ),
)
def test_s_09c_raw_allocated_contract_cannot_reach_authoritative_entrypoint(
    operation,
) -> None:
    forged = object.__new__(SystemHelloWorldContract)

    with pytest.raises(HelloWorldError, match="canonical Issue #1 snapshot"):
        operation(forged)
