"""Permanent Hello World identity semantics for the 0.6.2 executor."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from .canonical import canonical_hash
from .identity import (
    IdentityAuthority,
    IdentityRegistry,
    _utc,
    authorize_agent,
    resolve_binding,
)

HELLO_WORLD_AMOUNT_WEA = 42
_VERIFIED_RUNTIME: tuple[str, str, str] | None = None
_WEA_VERIFIER_CAPABILITY: object | None = globals().get(
    "_WEA_VERIFIER_CAPABILITY"
)


class HelloWorldError(ValueError):
    """Raised when a system Hello World transition is invalid."""


def _bind_verified_runtime(runtime: object, verifier_capability: object) -> None:
    global _VERIFIED_RUNTIME
    if (
        _WEA_VERIFIER_CAPABILITY is None
        or verifier_capability is not _WEA_VERIFIER_CAPABILITY
    ):
        raise HelloWorldError("runtime binding requires the manifest verifier")
    if not isinstance(runtime, tuple) or tuple.__len__(runtime) != 3:
        raise HelloWorldError("verified runtime triple is malformed")
    candidate = tuple(tuple.__getitem__(runtime, index) for index in range(3))
    if any(type(value) is not str for value in candidate):
        raise HelloWorldError("verified runtime triple is malformed")
    if _VERIFIED_RUNTIME is not None and _VERIFIED_RUNTIME != candidate:
        raise HelloWorldError("Hello World runtime is already bound")
    _VERIFIED_RUNTIME = candidate  # type: ignore[assignment]


def _verified_runtime() -> tuple[str, str, str]:
    if _VERIFIED_RUNTIME is None:
        raise HelloWorldError("Hello World must use a manifest-verified executor")
    return _VERIFIED_RUNTIME


def _text(name: str, value: object) -> str:
    if type(value) is not str or not value:
        raise HelloWorldError(f"{name} must be a non-empty string")
    return value


def _hash(name: str, value: object) -> str:
    value = _text(name, value)
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise HelloWorldError(f"{name} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class SystemHelloWorldContract:
    contract_id: str
    issue_id: str
    issue_number: int
    body: str
    body_hash: str
    ruleset_hash: str
    tide_interface_version: str
    executor_manifest_hash: str
    kind: str = "system_hello_world"
    mechanism: str = "hello-world"
    bank_total_wea: int = 0
    review_fee_wea: int = 0
    status: str = "active"

    def __post_init__(self) -> None:
        _text("contract_id", self.contract_id)
        _text("issue_id", self.issue_id)
        _text("body", self.body)
        _hash("body_hash", self.body_hash)
        if hashlib.sha256(self.body.encode("utf-8")).hexdigest() != self.body_hash:
            raise HelloWorldError("body_hash must match the exact contract body")
        _hash("ruleset_hash", self.ruleset_hash)
        _text("tide_interface_version", self.tide_interface_version)
        _hash("executor_manifest_hash", self.executor_manifest_hash)
        if (
            self.ruleset_hash,
            self.tide_interface_version,
            self.executor_manifest_hash,
        ) != _verified_runtime():
            raise HelloWorldError(
                "system Hello World Contract does not match the verified runtime"
            )
        if type(self.issue_number) is not int or self.issue_number != 1:
            raise HelloWorldError("system Hello World requires Issue #1")
        # v0_6_2 deliberately contains no authenticated Issue #1 snapshot and
        # can therefore never activate this Contract. A later immutable
        # executor must embed the permanent Issue ID and approved body hash in
        # its manifest-verified source; this executor is not configurable.
        raise HelloWorldError(
            "canonical Issue #1 snapshot is not installed in this executor"
        )

    def to_data(self) -> dict[str, object]:
        return {
            "bank_total_wea": self.bank_total_wea,
            "body": self.body,
            "body_hash": self.body_hash,
            "contract_id": self.contract_id,
            "executor_manifest_hash": self.executor_manifest_hash,
            "issue_id": self.issue_id,
            "issue_number": self.issue_number,
            "kind": self.kind,
            "mechanism": self.mechanism,
            "review_fee_wea": self.review_fee_wea,
            "ruleset_hash": self.ruleset_hash,
            "status": self.status,
            "tide_interface_version": self.tide_interface_version,
        }


@dataclass(frozen=True)
class HelloWorldSubmission:
    contract_id: str
    issue_id: str
    github_account_id: str
    agent_id: str
    work_id: str
    comment_id: str
    revision_id: str
    snapshot: str
    normalization_version: str
    comparison_hash: str
    effective_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "contract_id",
            "issue_id",
            "github_account_id",
            "agent_id",
            "work_id",
            "comment_id",
            "revision_id",
            "snapshot",
            "normalization_version",
        ):
            _text(name, getattr(self, name))
        _hash("comparison_hash", self.comparison_hash)
        if not isinstance(self.effective_at, datetime):
            raise HelloWorldError("effective_at must be a datetime")
        object.__setattr__(self, "effective_at", _utc(self.effective_at))

    def to_data(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "comment_id": self.comment_id,
            "comparison_hash": self.comparison_hash,
            "contract_id": self.contract_id,
            "effective_at": self.effective_at.isoformat().replace("+00:00", "Z"),
            "github_account_id": self.github_account_id,
            "issue_id": self.issue_id,
            "normalization_version": self.normalization_version,
            "revision_id": self.revision_id,
            "snapshot": self.snapshot,
            "work_id": self.work_id,
        }


@dataclass(frozen=True)
class Agent0HelloWorldDecision:
    contract_id: str
    work_id: str
    github_account_id: str
    agent0_id: str
    actor_binding_id: str
    actor_binding_version: int
    comment_id: str
    revision_id: str
    mechanically_unique: bool
    effective_at: datetime
    snapshot: str

    def __post_init__(self) -> None:
        for name in (
            "contract_id",
            "work_id",
            "github_account_id",
            "agent0_id",
            "actor_binding_id",
            "comment_id",
            "revision_id",
            "snapshot",
        ):
            _text(name, getattr(self, name))
        if (
            type(self.actor_binding_version) is not int
            or self.actor_binding_version < 1
        ):
            raise HelloWorldError("Agent0 binding version must be a positive integer")
        if type(self.mechanically_unique) is not bool:
            raise HelloWorldError("Agent0 uniqueness decision must be a boolean")
        object.__setattr__(self, "effective_at", _utc(self.effective_at))
        if self.snapshot != self.expected_snapshot:
            raise HelloWorldError("Agent0 decision snapshot must match exactly")

    @property
    def expected_snapshot(self) -> str:
        unique = "true" if self.mechanically_unique else "false"
        return "\n".join(
            (
                "### Декларация WEA",
                "- actor_kind: `agent0`",
                f"- agent0_id: `{self.agent0_id}`",
                "- action: `accept-hello-world`",
                f"- contract_id: `{self.contract_id}`",
                f"- work_id: `{self.work_id}`",
                f"- mechanically_unique: `{unique}`",
            )
        )

    def to_data(self) -> dict[str, object]:
        return {
            "actor_binding_id": self.actor_binding_id,
            "actor_binding_version": self.actor_binding_version,
            "agent0_id": self.agent0_id,
            "comment_id": self.comment_id,
            "contract_id": self.contract_id,
            "effective_at": self.effective_at.isoformat().replace("+00:00", "Z"),
            "github_account_id": self.github_account_id,
            "mechanically_unique": self.mechanically_unique,
            "revision_id": self.revision_id,
            "snapshot": self.snapshot,
            "work_id": self.work_id,
        }


def create_agent0_hello_world_decision(
    *,
    contract: SystemHelloWorldContract,
    work_id: str,
    github_account_id: str,
    agent0_id: str,
    comment_id: str,
    revision_id: str,
    mechanically_unique: bool,
    effective_at: datetime,
    snapshot: str,
    registry: IdentityRegistry,
) -> Agent0HelloWorldDecision:
    raise HelloWorldError(
        "canonical Issue #1 snapshot is not installed in this executor"
    )
    if type(contract) is not SystemHelloWorldContract:
        raise HelloWorldError("contract must use the verified system record type")
    if type(registry) is not IdentityRegistry:
        raise HelloWorldError("registry must use the verified identity record type")
    binding = resolve_binding(
        tuple(item for item in registry.bindings if item.actor_kind == "agent0"),
        github_account_id=github_account_id,
        subject_id=agent0_id,
        effective_at=effective_at,
    )
    decision = Agent0HelloWorldDecision(
        contract_id=contract.contract_id,
        work_id=work_id,
        github_account_id=binding.github_account_id,
        agent0_id=binding.subject_id,
        actor_binding_id=binding.binding_id,
        actor_binding_version=binding.version,
        comment_id=comment_id,
        revision_id=revision_id,
        mechanically_unique=mechanically_unique,
        effective_at=effective_at,
        snapshot=snapshot,
    )
    return decision


@dataclass(frozen=True)
class HelloWorldRecord:
    mint_key: str
    source: str
    contract_id: str
    issue_id: str
    comment_id: str
    revision_id: str
    github_account_id: str
    agent_id: str
    base_agent_id: str
    work_id: str
    snapshot: str
    normalization_version: str
    comparison_hash: str
    decision_comment_id: str | None = None
    decision_revision_id: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "mint_key",
            "contract_id",
            "issue_id",
            "comment_id",
            "revision_id",
            "github_account_id",
            "agent_id",
            "base_agent_id",
            "work_id",
            "snapshot",
            "normalization_version",
        ):
            _text(name, getattr(self, name))
        if self.source not in {"v1", "vnext"}:
            raise HelloWorldError("Hello World record source must be v1 or vnext")
        if self.source == "vnext":
            _text("decision_comment_id", self.decision_comment_id)
            _text("decision_revision_id", self.decision_revision_id)
        elif (
            self.decision_comment_id is not None
            or self.decision_revision_id is not None
        ):
            raise HelloWorldError("v1 record cannot contain vNext decision evidence")
        _hash("comparison_hash", self.comparison_hash)
        if self.mint_key != f"hello-world:{self.github_account_id}":
            raise HelloWorldError("Hello World record mint key does not match account")
        expected_work_id = (
            "work:"
            + canonical_hash(
                {"agent_id": self.agent_id, "contract_id": self.contract_id}
            )
            if self.source == "vnext"
            else f"legacy:{self.comment_id}:{self.revision_id}"
        )
        if self.work_id != expected_work_id:
            raise HelloWorldError("Hello World record Work ID must be protocol-derived")

    def to_data(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "base_agent_id": self.base_agent_id,
            "comment_id": self.comment_id,
            "comparison_hash": self.comparison_hash,
            "contract_id": self.contract_id,
            "decision_comment_id": self.decision_comment_id,
            "decision_revision_id": self.decision_revision_id,
            "github_account_id": self.github_account_id,
            "issue_id": self.issue_id,
            "mint_key": self.mint_key,
            "normalization_version": self.normalization_version,
            "revision_id": self.revision_id,
            "snapshot": self.snapshot,
            "source": self.source,
            "work_id": self.work_id,
        }


@dataclass(frozen=True)
class HelloWorldMintUse:
    mint_key: str
    github_account_id: str
    base_agent_id: str
    source: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text("mint_key", self.mint_key)
        _text("github_account_id", self.github_account_id)
        _text("base_agent_id", self.base_agent_id)
        if self.source not in {"v1", "vnext"}:
            raise HelloWorldError("mint use source must be v1 or vnext")
        if self.mint_key != f"hello-world:{self.github_account_id}":
            raise HelloWorldError("Hello World mint key does not match account")
        if type(self.evidence_ids) is not tuple or not self.evidence_ids:
            raise HelloWorldError("mint use requires durable evidence IDs")
        for evidence_id in self.evidence_ids:
            _text("evidence_id", evidence_id)
        expected_count = 5 if self.source == "v1" else 6
        if len(self.evidence_ids) != expected_count:
            raise HelloWorldError(
                f"{self.source} mint use requires {expected_count} evidence IDs"
            )

    def to_data(self) -> dict[str, object]:
        return {
            "base_agent_id": self.base_agent_id,
            "evidence_ids": list(self.evidence_ids),
            "github_account_id": self.github_account_id,
            "mint_key": self.mint_key,
            "source": self.source,
        }


@dataclass(frozen=True)
class HelloWorldState:
    contract: SystemHelloWorldContract
    records: tuple[HelloWorldRecord, ...] = ()
    mint_uses: tuple[HelloWorldMintUse, ...] = ()

    def __post_init__(self) -> None:
        if type(self.contract) is not SystemHelloWorldContract:
            raise HelloWorldError(
                "state contract must use the verified system record type"
            )
        if any(type(item) is not HelloWorldRecord for item in self.records):
            raise HelloWorldError("state records must use verified record types")
        if any(type(item) is not HelloWorldMintUse for item in self.mint_uses):
            raise HelloWorldError("state mint uses must use verified record types")
        records = tuple(sorted(self.records, key=lambda item: item.mint_key))
        uses = tuple(sorted(self.mint_uses, key=lambda item: item.mint_key))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "mint_uses", uses)
        record_keys = [item.mint_key for item in records]
        use_keys = [item.mint_key for item in uses]
        if len(record_keys) != len(set(record_keys)):
            raise HelloWorldError("one account can have only one Hello World record")
        if len(use_keys) != len(set(use_keys)):
            raise HelloWorldError("one account can use only one Hello World mint key")
        if set(record_keys) != set(use_keys):
            raise HelloWorldError("Hello World records and mint uses must be atomic")
        for attribute in ("work_id",):
            values = [getattr(item, attribute) for item in records]
            if len(values) != len(set(values)):
                raise HelloWorldError(
                    f"Hello World {attribute} evidence ID is reused"
                )
        comment_ids = [item.comment_id for item in records] + [
            item.decision_comment_id
            for item in records
            if item.decision_comment_id is not None
        ]
        revision_ids = [item.revision_id for item in records] + [
            item.decision_revision_id
            for item in records
            if item.decision_revision_id is not None
        ]
        if len(comment_ids) != len(set(comment_ids)):
            raise HelloWorldError("Hello World comment_id evidence ID is reused")
        if len(revision_ids) != len(set(revision_ids)):
            raise HelloWorldError("Hello World revision_id evidence ID is reused")
        legacy_ledger_ids: set[str] = set()
        legacy_idempotency_keys: set[str] = set()
        for use in uses:
            if use.source != "v1":
                continue
            ledger_history_id = use.evidence_ids[3]
            legacy_idempotency_key = use.evidence_ids[4]
            if ledger_history_id in legacy_ledger_ids:
                raise HelloWorldError(
                    "Hello World ledger_history evidence ID is reused"
                )
            if legacy_idempotency_key in legacy_idempotency_keys:
                raise HelloWorldError(
                    "Hello World idempotency evidence ID is reused"
                )
            legacy_ledger_ids.add(ledger_history_id)
            legacy_idempotency_keys.add(legacy_idempotency_key)
        uses_by_key = {item.mint_key: item for item in uses}
        for record in records:
            if (
                record.contract_id != self.contract.contract_id
                or record.issue_id != self.contract.issue_id
            ):
                raise HelloWorldError("Hello World record uses another system contract")
            use = uses_by_key[record.mint_key]
            if (
                record.github_account_id != use.github_account_id
                or record.base_agent_id != use.base_agent_id
                or record.source != use.source
            ):
                raise HelloWorldError("Hello World record and mint use disagree")
            expected_evidence = (
                (record.issue_id, record.comment_id, record.revision_id)
                if record.source == "v1"
                else (
                    record.contract_id,
                    record.comment_id,
                    record.revision_id,
                    record.work_id,
                    record.decision_comment_id,
                    record.decision_revision_id,
                )
            )
            if use.evidence_ids[: len(expected_evidence)] != expected_evidence:
                raise HelloWorldError(
                    "Hello World record and mint evidence IDs disagree"
                )

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, object]:
        return {
            "contract": self.contract.to_data(),
            "mint_uses": [item.to_data() for item in self.mint_uses],
            "records": [item.to_data() for item in self.records],
        }


@dataclass(frozen=True)
class MintIntent:
    agent_id: str
    amount_wea: int
    idempotency_key: str

    def __post_init__(self) -> None:
        _text("agent_id", self.agent_id)
        _text("idempotency_key", self.idempotency_key)
        if (
            type(self.amount_wea) is not int
            or self.amount_wea != HELLO_WORLD_AMOUNT_WEA
        ):
            raise HelloWorldError("Hello World mint must be exactly 42 WEA")

    def to_data(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "amount_wea": self.amount_wea,
            "idempotency_key": self.idempotency_key,
        }


@dataclass(frozen=True)
class HelloWorldTransition:
    state: HelloWorldState
    contract: SystemHelloWorldContract
    outcome: str
    mint_intent: MintIntent | None = None

    def __post_init__(self) -> None:
        if type(self.state) is not HelloWorldState:
            raise HelloWorldError("transition state must use the verified record type")
        if type(self.contract) is not SystemHelloWorldContract:
            raise HelloWorldError(
                "transition contract must use the verified record type"
            )
        if self.state.contract != self.contract:
            raise HelloWorldError("transition state uses another system contract")
        if self.mint_intent is not None and type(self.mint_intent) is not MintIntent:
            raise HelloWorldError(
                "transition mint intent must use the verified record type"
            )
        if self.outcome not in {
            "mint-planned",
            "already-used",
            "not-unique",
            "v1-mint-restored",
        }:
            raise HelloWorldError("unsupported Hello World transition outcome")
        if (self.outcome == "mint-planned") != (self.mint_intent is not None):
            raise HelloWorldError("only mint-planned may contain a mint intent")

    @property
    def ledger_effects(self) -> tuple[MintIntent, ...]:
        return () if self.mint_intent is None else (self.mint_intent,)

    @property
    def task_effects(self) -> tuple[object, ...]:
        return ()

    @property
    def escrow_effects(self) -> tuple[object, ...]:
        return ()


def create_hello_world_submission(
    *,
    contract: SystemHelloWorldContract,
    github_account_id: str,
    agent_id: str,
    comment_id: str,
    revision_id: str,
    snapshot: str,
    normalization_version: str,
    comparison_hash: str,
    effective_at: datetime,
) -> HelloWorldSubmission:
    raise HelloWorldError(
        "canonical Issue #1 snapshot is not installed in this executor"
    )
    if type(contract) is not SystemHelloWorldContract:
        raise HelloWorldError("contract must use the verified system record type")
    github_account_id = _text("github_account_id", github_account_id)
    agent_id = _text("agent_id", agent_id)
    work_hash = canonical_hash(
        {"agent_id": agent_id, "contract_id": contract.contract_id}
    )
    return HelloWorldSubmission(
        contract_id=contract.contract_id,
        issue_id=contract.issue_id,
        github_account_id=github_account_id,
        agent_id=agent_id,
        work_id=f"work:{work_hash}",
        comment_id=comment_id,
        revision_id=revision_id,
        snapshot=snapshot,
        normalization_version=normalization_version,
        comparison_hash=comparison_hash,
        effective_at=effective_at,
    )


def _existing_use(
    state: HelloWorldState, mint_key: str
) -> HelloWorldMintUse | None:
    return next((item for item in state.mint_uses if item.mint_key == mint_key), None)


def _verify_agent0_decision(
    decision: Agent0HelloWorldDecision,
    *,
    contract: SystemHelloWorldContract,
    submission: HelloWorldSubmission,
    registry: IdentityRegistry,
) -> Agent0HelloWorldDecision:
    if type(decision) is not Agent0HelloWorldDecision:
        raise HelloWorldError("decision must use the verified Agent0 record type")
    if decision.contract_id != contract.contract_id:
        raise HelloWorldError("Agent0 decision belongs to another system contract")
    if decision.work_id != submission.work_id:
        raise HelloWorldError("Agent0 decision belongs to another Work")
    if decision.effective_at < submission.effective_at:
        raise HelloWorldError("Agent0 decision cannot precede the submission")
    verified = create_agent0_hello_world_decision(
        contract=contract,
        work_id=decision.work_id,
        github_account_id=decision.github_account_id,
        agent0_id=decision.agent0_id,
        comment_id=decision.comment_id,
        revision_id=decision.revision_id,
        mechanically_unique=decision.mechanically_unique,
        effective_at=decision.effective_at,
        snapshot=decision.snapshot,
        registry=registry,
    )
    if verified != decision:
        raise HelloWorldError("Agent0 decision authority does not match the registry")
    return verified


def accept_unique_hello_world(
    *,
    state: HelloWorldState,
    contract: SystemHelloWorldContract,
    submission: HelloWorldSubmission,
    participant: IdentityAuthority,
    decision: Agent0HelloWorldDecision,
    registry: IdentityRegistry,
) -> HelloWorldTransition:
    raise HelloWorldError(
        "canonical Issue #1 snapshot is not installed in this executor"
    )
    if type(state) is not HelloWorldState:
        raise HelloWorldError("state must use the verified Hello World record type")
    if type(contract) is not SystemHelloWorldContract:
        raise HelloWorldError("contract must use the verified system record type")
    if type(submission) is not HelloWorldSubmission:
        raise HelloWorldError("submission must use the verified record type")
    if type(participant) is not IdentityAuthority:
        raise HelloWorldError("participant must use the verified authority type")
    if type(registry) is not IdentityRegistry:
        raise HelloWorldError("registry must use the verified identity record type")
    if state.contract != contract:
        raise HelloWorldError("state uses another system Hello World contract")
    if (
        submission.contract_id != contract.contract_id
        or submission.issue_id != contract.issue_id
    ):
        raise HelloWorldError("submission does not belong to the system contract")
    expected_work_id = "work:" + canonical_hash(
        {"agent_id": submission.agent_id, "contract_id": contract.contract_id}
    )
    if submission.work_id != expected_work_id:
        raise HelloWorldError("Hello World Work ID must be protocol-derived")
    verified = authorize_agent(
        github_account_id=submission.github_account_id,
        agent_id=submission.agent_id,
        effective_at=submission.effective_at,
        registry=registry,
    )
    if verified != participant:
        raise HelloWorldError("participant authority does not match the submission")
    verified_decision = _verify_agent0_decision(
        decision,
        contract=contract,
        submission=submission,
        registry=registry,
    )
    account = registry.account(submission.github_account_id)
    mint_key = account.hello_world_mint_key
    if _existing_use(state, mint_key) is not None:
        return HelloWorldTransition(state, contract, "already-used")
    if not verified_decision.mechanically_unique:
        return HelloWorldTransition(state, contract, "not-unique")
    record = HelloWorldRecord(
        mint_key=mint_key,
        source="vnext",
        contract_id=contract.contract_id,
        issue_id=submission.issue_id,
        comment_id=submission.comment_id,
        revision_id=submission.revision_id,
        github_account_id=submission.github_account_id,
        agent_id=submission.agent_id,
        base_agent_id=account.base_agent_id,
        work_id=submission.work_id,
        snapshot=submission.snapshot,
        normalization_version=submission.normalization_version,
        comparison_hash=submission.comparison_hash,
        decision_comment_id=verified_decision.comment_id,
        decision_revision_id=verified_decision.revision_id,
    )
    use = HelloWorldMintUse(
        mint_key=mint_key,
        github_account_id=account.github_account_id,
        base_agent_id=account.base_agent_id,
        source="vnext",
        evidence_ids=(
            contract.contract_id,
            submission.comment_id,
            submission.revision_id,
            submission.work_id,
            verified_decision.comment_id,
            verified_decision.revision_id,
        ),
    )
    next_state = HelloWorldState(
        contract=contract,
        records=(*state.records, record), mint_uses=(*state.mint_uses, use)
    )
    return HelloWorldTransition(
        next_state,
        contract,
        "mint-planned",
        MintIntent(account.base_agent_id, HELLO_WORLD_AMOUNT_WEA, mint_key),
    )


def restore_v1_hello_world(
    *,
    state: HelloWorldState,
    contract: SystemHelloWorldContract,
    registry: IdentityRegistry,
    github_account_id: str,
    participant_agent_id: str,
    issue_id: str,
    comment_id: str,
    revision_id: str,
    snapshot: str,
    normalization_version: str,
    comparison_hash: str,
    ledger_history_id: str,
    legacy_idempotency_key: str,
) -> HelloWorldTransition:
    raise HelloWorldError(
        "canonical Issue #1 snapshot is not installed in this executor"
    )
    if type(state) is not HelloWorldState:
        raise HelloWorldError("state must use the verified Hello World record type")
    if type(contract) is not SystemHelloWorldContract:
        raise HelloWorldError("contract must use the verified system record type")
    if type(registry) is not IdentityRegistry:
        raise HelloWorldError("registry must use the verified identity record type")
    if state.contract != contract:
        raise HelloWorldError("state uses another system Hello World contract")
    account = registry.account(github_account_id)
    if not any(
        binding.actor_kind == "agent"
        and binding.github_account_id == github_account_id
        and binding.subject_id == participant_agent_id
        for binding in registry.bindings
    ):
        raise HelloWorldError("v1 participant is not linked to the GitHub account")
    mint_key = account.hello_world_mint_key
    existing = _existing_use(state, mint_key)
    if issue_id != contract.issue_id:
        raise HelloWorldError("v1 evidence does not belong to the system contract")
    if existing is not None:
        expected_evidence = (
            issue_id,
            comment_id,
            revision_id,
            _text("ledger_history_id", ledger_history_id),
            _text("legacy_idempotency_key", legacy_idempotency_key),
        )
        existing_record = next(
            item for item in state.records if item.mint_key == mint_key
        )
        if (
            existing.source == "v1"
            and existing.evidence_ids == expected_evidence
            and existing_record.snapshot == snapshot
            and existing_record.comparison_hash == comparison_hash
            and existing_record.normalization_version == normalization_version
            and existing_record.agent_id == participant_agent_id
        ):
            return HelloWorldTransition(state, contract, "already-used")
        raise HelloWorldError("conflicting Hello World migration evidence")
    record = HelloWorldRecord(
        mint_key=mint_key,
        source="v1",
        contract_id=contract.contract_id,
        issue_id=issue_id,
        comment_id=comment_id,
        revision_id=revision_id,
        github_account_id=github_account_id,
        agent_id=participant_agent_id,
        base_agent_id=account.base_agent_id,
        work_id=f"legacy:{comment_id}:{revision_id}",
        snapshot=snapshot,
        normalization_version=normalization_version,
        comparison_hash=comparison_hash,
    )
    use = HelloWorldMintUse(
        mint_key=mint_key,
        github_account_id=github_account_id,
        base_agent_id=account.base_agent_id,
        source="v1",
        evidence_ids=(
            issue_id,
            comment_id,
            revision_id,
            _text("ledger_history_id", ledger_history_id),
            _text("legacy_idempotency_key", legacy_idempotency_key),
        ),
    )
    return HelloWorldTransition(
        HelloWorldState(
            contract=contract,
            records=(*state.records, record), mint_uses=(*state.mint_uses, use)
        ),
        contract,
        "v1-mint-restored",
    )


__all__ = [
    "HELLO_WORLD_AMOUNT_WEA",
    "Agent0HelloWorldDecision",
    "HelloWorldError",
    "HelloWorldMintUse",
    "HelloWorldRecord",
    "HelloWorldState",
    "HelloWorldSubmission",
    "HelloWorldTransition",
    "MintIntent",
    "SystemHelloWorldContract",
    "accept_unique_hello_world",
    "create_agent0_hello_world_decision",
    "create_hello_world_submission",
    "restore_v1_hello_world",
]
