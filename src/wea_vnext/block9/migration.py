"""Offline v1 reconciliation, conversion intents, and canonical genesis."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from types import MappingProxyType

from .common import (
    Block9Error,
    canonical_bytes,
    parse_utc,
    require_hash,
    require_positive_int,
    require_text,
    sha256_hex,
)

_OUTCOMES = {
    "settle-v1",
    "stop/refund",
    "convert-with-fresh-approval",
    "historical-close",
}
_INTENT_STATES = {"pending", "consumed", "cancelled", "expired"}
_RETIRED_COMMANDS = {"gauntlet-mint", "award", "revoke", "transform"}
_BUNDLE_FIELDS = {
    "boundary_id",
    "predecessor",
    "source_hashes",
    "github_pages",
    "local_records",
    "pending_payments",
    "balances",
    "signed_supply",
    "identities",
    "authority_bindings",
    "genomes",
    "hello_world_keys",
    "history_refs",
    "gauntlet_history",
    "achievement_history",
}
_CONVERSION_APPROVAL_FIELDS = {
    "source_issue",
    "source_revision_hash",
    "v1_closure_hash",
    "author_payer_agent_id",
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
}


def _nonnegative(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise Block9Error(f"{field} must be a nonnegative integer")
    return value


def _mapping(value: object, *, field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise Block9Error(f"{field} must be an exact mapping")
    return value


def _list(value: object, *, field: str) -> list[object]:
    if type(value) is not list:
        raise Block9Error(f"{field} must be an exact list")
    return value


@dataclass(frozen=True, slots=True)
class FrozenInputBundle:
    canonical_data: bytes
    input_hash: str

    def __post_init__(self) -> None:
        if type(self.canonical_data) is not bytes:
            raise Block9Error("frozen input must use exact bytes")
        require_hash(self.input_hash, field="frozen input_hash")
        if sha256_hex(self.canonical_data) != self.input_hash:
            raise Block9Error("frozen input hash changed")
        try:
            value = json.loads(self.canonical_data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Block9Error("frozen input is unreadable") from exc
        if type(value) is not dict or canonical_bytes(value) != self.canonical_data:
            raise Block9Error("frozen input bytes are not canonical")

    @property
    def data(self) -> dict[str, object]:
        value = json.loads(self.canonical_data)
        if type(value) is not dict:  # pragma: no cover - constructor proof
            raise Block9Error("frozen input is not a mapping")
        return value


@dataclass(frozen=True, slots=True)
class ConversionAuthorityBinding:
    agent_id: str
    account_id: str
    binding_id: str
    binding_version: int
    binding_hash: str
    effective_from: str
    effective_until: str

    def __post_init__(self) -> None:
        for field in ("agent_id", "account_id", "binding_id"):
            require_text(getattr(self, field), field=f"conversion authority {field}")
        require_positive_int(
            self.binding_version, field="conversion authority binding_version"
        )
        require_hash(self.binding_hash, field="conversion authority binding_hash")
        start = parse_utc(
            self.effective_from, field="conversion authority effective_from"
        )
        end = parse_utc(
            self.effective_until, field="conversion authority effective_until"
        )
        if start >= end:
            raise Block9Error("conversion authority interval is empty")

    @classmethod
    def from_mapping(cls, value: object) -> ConversionAuthorityBinding:
        mapping = _mapping(value, field="conversion authority binding")
        required = {
            "agent_id",
            "account_id",
            "binding_id",
            "binding_version",
            "binding_hash",
            "effective_from",
            "effective_until",
        }
        if set(mapping) != required:
            raise Block9Error("conversion authority binding fields are incomplete")
        return cls(**mapping)  # type: ignore[arg-type]

    def active_at(self, value: str) -> bool:
        at = parse_utc(value, field="conversion authority effective_at")
        return (
            parse_utc(self.effective_from, field="conversion authority effective_from")
            <= at
            < parse_utc(
                self.effective_until, field="conversion authority effective_until"
            )
        )


def freeze_input_bundle(payload: Mapping[str, object]) -> FrozenInputBundle:
    if type(payload) is not dict:
        payload = dict(payload)
    if set(payload) != _BUNDLE_FIELDS:
        raise Block9Error("frozen input fields do not match the Block 9 schema")
    require_text(payload["boundary_id"], field="boundary_id")
    require_hash(payload["predecessor"], field="predecessor", length=40)
    source_hashes = _mapping(payload["source_hashes"], field="source_hashes")
    if not source_hashes:
        raise Block9Error("source_hashes cannot be empty")
    for name, digest in source_hashes.items():
        require_text(name, field="source hash name")
        require_hash(digest, field=f"source_hashes.{name}")

    pages = _list(payload["github_pages"], field="github_pages")
    if not pages:
        raise Block9Error("GitHub pagination is incomplete")
    cursors: set[str] = set()
    issues: set[str] = set()
    previous_next: object = None
    for index, raw_page in enumerate(pages):
        page = _mapping(raw_page, field="GitHub page")
        if set(page) != {"cursor", "next_cursor", "complete", "issues"}:
            raise Block9Error("GitHub page fields are incomplete")
        cursor = require_text(page["cursor"], field="GitHub cursor")
        if cursor in cursors:
            raise Block9Error("GitHub pagination contains a duplicate cursor")
        cursors.add(cursor)
        if index and previous_next != cursor:
            raise Block9Error("GitHub pagination cursor chain is incomplete")
        complete = page["complete"]
        if type(complete) is not bool:
            raise Block9Error("GitHub page complete flag must be boolean")
        next_cursor = page["next_cursor"]
        if next_cursor is not None:
            require_text(next_cursor, field="GitHub next cursor")
        if index < len(pages) - 1 and (complete or next_cursor is None):
            raise Block9Error("GitHub pagination is incomplete")
        if index == len(pages) - 1 and (not complete or next_cursor is not None):
            raise Block9Error("GitHub pagination is incomplete")
        previous_next = next_cursor
        for raw_issue in _list(page["issues"], field="GitHub page issues"):
            issue = _mapping(raw_issue, field="GitHub Issue")
            required = {
                "issue_id",
                "revision_hash",
                "is_pull_request",
                "is_v1_obligation",
                "unfinished",
                "approval_revisions",
                "closure_records",
            }
            if set(issue) != required:
                raise Block9Error("GitHub Issue fields are incomplete")
            issue_id = require_text(issue["issue_id"], field="issue_id")
            require_hash(issue["revision_hash"], field="issue revision hash")
            for field in ("is_pull_request", "is_v1_obligation", "unfinished"):
                if type(issue[field]) is not bool:
                    raise Block9Error(f"{field} must be boolean")
            approval_ids: set[tuple[str, str]] = set()
            for raw_approval in _list(
                issue["approval_revisions"], field="approval revisions"
            ):
                approval = _mapping(raw_approval, field="approval revision")
                if set(approval) != {
                    "source_id",
                    "revision_id",
                    "account_id",
                    "agent_id",
                    "body_hash",
                    "confirmed_read_hash",
                    "effective_at",
                }:
                    raise Block9Error("approval revision fields are incomplete")
                source_id = require_text(
                    approval["source_id"], field="approval source_id"
                )
                revision_id = require_text(
                    approval["revision_id"], field="approval revision_id"
                )
                if (source_id, revision_id) in approval_ids:
                    raise Block9Error("approval revision appears more than once")
                approval_ids.add((source_id, revision_id))
                require_text(approval["account_id"], field="approval account_id")
                require_text(approval["agent_id"], field="approval agent_id")
                require_hash(approval["body_hash"], field="approval body_hash")
                require_hash(
                    approval["confirmed_read_hash"],
                    field="approval confirmed_read_hash",
                )
                parse_utc(approval["effective_at"], field="approval effective_at")
            closure_outcomes: set[str] = set()
            for raw_closure in _list(issue["closure_records"], field="closure records"):
                closure = _mapping(raw_closure, field="closure record")
                if set(closure) != {
                    "outcome",
                    "source_id",
                    "source_revision_hash",
                }:
                    raise Block9Error("closure record fields are incomplete")
                outcome = require_text(
                    closure["outcome"], field="closure record outcome"
                )
                if outcome not in _OUTCOMES:
                    raise Block9Error("closure record outcome is unknown")
                if outcome in closure_outcomes:
                    raise Block9Error("closure outcome appears more than once")
                closure_outcomes.add(outcome)
                require_text(closure["source_id"], field="closure source_id")
                require_hash(
                    closure["source_revision_hash"],
                    field="closure source_revision_hash",
                )
            if (
                issue["is_v1_obligation"]
                and issue["unfinished"]
                and not closure_outcomes
            ):
                raise Block9Error("unfinished obligation has no closure evidence")
            if issue["is_pull_request"]:
                continue
            if issue_id in issues:
                raise Block9Error("captured Issue appears more than once")
            issues.add(issue_id)

    record_ids: set[str] = set()
    active_escrow_total = 0
    for raw_record in _list(payload["local_records"], field="local_records"):
        record = _mapping(raw_record, field="local record")
        required = {
            "record_id",
            "issue_id",
            "deposited",
            "payments",
            "refunds",
            "active_escrow",
        }
        if set(record) != required:
            raise Block9Error("local record fields are incomplete")
        record_id = require_text(record["record_id"], field="record_id")
        require_text(record["issue_id"], field="record issue_id")
        if record_id in record_ids:
            raise Block9Error("local record ID appears more than once")
        record_ids.add(record_id)
        for field in ("deposited", "payments", "refunds"):
            _nonnegative(record[field], field=f"{record_id}.{field}")
        active_escrow_total += _nonnegative(
            record["active_escrow"], field=f"{record_id}.active_escrow"
        )

    _list(payload["pending_payments"], field="pending_payments")
    balances = _mapping(payload["balances"], field="balances")
    if not balances:
        raise Block9Error("balances cannot be empty")
    balance_total = 0
    for agent_id, amount in balances.items():
        require_text(agent_id, field="balance Agent ID")
        balance_total += _nonnegative(amount, field=f"balance.{agent_id}")
    signed_supply = _nonnegative(payload["signed_supply"], field="signed_supply")
    if balance_total + active_escrow_total != signed_supply:
        raise Block9Error("balances plus active escrow do not equal signed supply")
    identities = _mapping(payload["identities"], field="identities")
    genomes = _mapping(payload["genomes"], field="genomes")
    if not set(identities).issubset(balances) or not set(genomes).issubset(balances):
        raise Block9Error("identity or genome Agent ID has no balance row")
    authority_bindings = tuple(
        ConversionAuthorityBinding.from_mapping(value)
        for value in _list(payload["authority_bindings"], field="authority_bindings")
    )
    authority_keys = {
        (item.binding_id, item.binding_version) for item in authority_bindings
    }
    if len(authority_keys) != len(authority_bindings):
        raise Block9Error("conversion authority binding appears more than once")
    if (
        tuple(
            sorted(
                authority_bindings,
                key=lambda item: (
                    item.agent_id,
                    item.account_id,
                    item.binding_id,
                    item.binding_version,
                ),
            )
        )
        != authority_bindings
    ):
        raise Block9Error("conversion authority bindings are not canonical")
    for field in (
        "hello_world_keys",
        "history_refs",
        "gauntlet_history",
        "achievement_history",
    ):
        _list(payload[field], field=field)
    raw = canonical_bytes(payload)
    return FrozenInputBundle(raw, sha256_hex(raw))


@dataclass(frozen=True, slots=True)
class ReconciliationOutcome:
    issue_id: str
    outcome: str
    closure_hash: str

    def __post_init__(self) -> None:
        require_text(self.issue_id, field="reconciliation issue_id")
        if self.outcome not in _OUTCOMES:
            raise Block9Error("unknown reconciliation outcome")
        require_hash(self.closure_hash, field="reconciliation closure_hash")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    input_hash: str
    outcomes: tuple[ReconciliationOutcome, ...]
    unexplained_amount: int
    report_hash: str

    def __post_init__(self) -> None:
        require_hash(self.input_hash, field="reconciliation input_hash")
        if type(self.outcomes) is not tuple or any(
            type(item) is not ReconciliationOutcome for item in self.outcomes
        ):
            raise Block9Error("reconciliation outcomes must use exact types")
        canonical = tuple(sorted(self.outcomes, key=lambda item: item.issue_id))
        if canonical != self.outcomes:
            raise Block9Error("reconciliation outcomes are not canonical")
        if len({item.issue_id for item in self.outcomes}) != len(self.outcomes):
            raise Block9Error("reconciliation outcomes contain a duplicate Issue")
        _nonnegative(self.unexplained_amount, field="reconciliation unexplained_amount")
        require_hash(self.report_hash, field="reconciliation report_hash")


def _captured_issues(data: Mapping[str, object]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for raw_page in data["github_pages"]:  # type: ignore[index]
        for raw_issue in raw_page["issues"]:  # type: ignore[index]
            if not raw_issue["is_pull_request"]:
                result[raw_issue["issue_id"]] = raw_issue
    return result


def _require_frozen_bundle(bundle: FrozenInputBundle) -> dict[str, object]:
    if type(bundle) is not FrozenInputBundle:
        raise Block9Error("input bundle must use the exact type")
    data = bundle.data
    if freeze_input_bundle(data) != bundle:
        raise Block9Error("frozen input bundle changed after validation")
    return data


def _closure_hash_for(issue: Mapping[str, object], outcome: str) -> str:
    matches: list[str] = []
    for raw_record in _list(issue["closure_records"], field="closure records"):
        record = _mapping(raw_record, field="closure record")
        if record["outcome"] == outcome:
            matches.append(
                require_hash(
                    record["source_revision_hash"],
                    field="closure source_revision_hash",
                )
            )
    if len(matches) != 1:
        raise Block9Error("outcome has no exact frozen closure evidence")
    return matches[0]


def reconcile_obligations(
    bundle: FrozenInputBundle,
    outcomes: Mapping[str, Mapping[str, object]],
) -> ReconciliationReport:
    data = _require_frozen_bundle(bundle)
    if data["pending_payments"]:
        raise Block9Error("pending payment blocks reconciliation")
    issues = _captured_issues(data)
    records = data["local_records"]
    for record in records:  # type: ignore[union-attr]
        if record["issue_id"] not in issues:
            raise Block9Error(
                f"local record has no captured Issue: {record['record_id']}"
            )
        if not issues[record["issue_id"]]["is_v1_obligation"]:
            raise Block9Error(
                "a locally referenced Issue cannot be classified as not-v1-obligation"
            )
    required = {
        issue_id
        for issue_id, issue in issues.items()
        if issue["is_v1_obligation"] and issue["unfinished"]
    }
    if set(outcomes) != required:
        raise Block9Error("every unfinished v1 obligation needs exactly one outcome")

    issue_money: dict[str, int] = {issue_id: 0 for issue_id in required}
    for record in records:  # type: ignore[union-attr]
        deposited = _nonnegative(record["deposited"], field="deposited")
        payments = _nonnegative(record["payments"], field="payments")
        refunds = _nonnegative(record["refunds"], field="refunds")
        active = _nonnegative(record["active_escrow"], field="active_escrow")
        if active:
            raise Block9Error("active escrow blocks reconciliation")
        if deposited != payments + refunds:
            raise Block9Error("v1 obligation money does not reconcile per record")
        issue_id = record["issue_id"]
        if issue_id in issue_money:
            issue_money[issue_id] += deposited + payments + refunds

    rebuilt: list[ReconciliationOutcome] = []
    for issue_id in sorted(outcomes):
        value = outcomes[issue_id]
        if type(value) is not dict or set(value) != {"outcome", "closure_hash"}:
            raise Block9Error("outcome fields are incomplete")
        outcome = value["outcome"]
        if outcome not in _OUTCOMES:
            raise Block9Error("unknown reconciliation outcome")
        if outcome == "historical-close" and issue_money[issue_id] != 0:
            raise Block9Error("historical-close cannot hide financial activity")
        closure_hash = require_hash(value["closure_hash"], field="closure_hash")
        if closure_hash != _closure_hash_for(issues[issue_id], outcome):
            raise Block9Error("outcome closure hash is not frozen evidence")
        rebuilt.append(ReconciliationOutcome(issue_id, outcome, closure_hash))
    payload = {
        "input_hash": bundle.input_hash,
        "outcomes": [asdict(item) for item in rebuilt],
        "unexplained_amount": 0,
    }
    report_hash = sha256_hex(canonical_bytes(payload))
    return ReconciliationReport(bundle.input_hash, tuple(rebuilt), 0, report_hash)


@dataclass(frozen=True, slots=True)
class ConversionIntent:
    intent_id: str
    source_issue: str
    source_revision_hash: str
    v1_closure_hash: str
    author_payer_agent_id: str
    account_id: str
    authority_binding_id: str
    authority_binding_version: int
    authority_binding_hash: str
    authority_valid_from: str
    authority_valid_until: str
    plan_bytes: bytes
    plan_hash: str
    plan_bank: int
    triage_revision: str
    ruleset_identity: str
    runtime_bytes: bytes
    approval_source: str
    approval_revision: str
    approval_hash: str
    confirmed_read_hash: str
    issued_at: str
    expires_at: str
    idempotency_key: str
    state: str

    def __post_init__(self) -> None:
        for field in (
            "intent_id",
            "source_issue",
            "author_payer_agent_id",
            "account_id",
            "authority_binding_id",
            "triage_revision",
            "ruleset_identity",
            "approval_source",
            "approval_revision",
            "idempotency_key",
        ):
            require_text(getattr(self, field), field=field)
        for field in (
            "source_revision_hash",
            "v1_closure_hash",
            "authority_binding_hash",
            "plan_hash",
            "approval_hash",
            "confirmed_read_hash",
        ):
            require_hash(getattr(self, field), field=field)
        require_positive_int(
            self.authority_binding_version, field="authority_binding_version"
        )
        require_positive_int(self.plan_bank, field="plan_bank")
        authority_start = parse_utc(
            self.authority_valid_from, field="authority_valid_from"
        )
        authority_end = parse_utc(
            self.authority_valid_until, field="authority_valid_until"
        )
        issued = parse_utc(self.issued_at, field="issued_at")
        expiry = parse_utc(self.expires_at, field="expires_at")
        if (
            authority_start >= authority_end
            or not authority_start <= issued < authority_end
            or not issued < expiry <= authority_end
        ):
            raise Block9Error("conversion approval interval is not fresh")
        parsed_values: dict[str, object] = {}
        for field, raw, digest in (
            ("Plan", self.plan_bytes, self.plan_hash),
            ("runtime", self.runtime_bytes, sha256_hex(self.runtime_bytes)),
        ):
            if type(raw) is not bytes:
                raise Block9Error(f"stored {field} must be exact bytes")
            try:
                parsed = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise Block9Error(f"stored {field} is not JSON") from exc
            if canonical_bytes(parsed) != raw:
                raise Block9Error(f"stored {field} is not canonical")
            if field == "Plan" and sha256_hex(raw) != digest:
                raise Block9Error("stored Plan hash changed")
            parsed_values[field] = parsed
        plan = _mapping(parsed_values["Plan"], field="stored Plan")
        if set(plan) != {"title", "stages"}:
            raise Block9Error("stored conversion Plan is incomplete")
        require_text(plan["title"], field="stored plan.title")
        stages = _list(plan["stages"], field="stored plan.stages")
        if not stages:
            raise Block9Error("stored conversion Plan needs at least one stage")
        for raw_stage in stages:
            stage = _mapping(raw_stage, field="stored Plan stage")
            if set(stage) != {"task", "contract"}:
                raise Block9Error("stored Plan stage is incomplete")
            require_text(stage["task"], field="stored stage.task")
            require_text(stage["contract"], field="stored stage.contract")
        runtime = _mapping(parsed_values["runtime"], field="stored runtime")
        if set(runtime) != {"python", "executor", "ruleset"}:
            raise Block9Error("stored runtime triple is incomplete")
        for name, value in runtime.items():
            require_text(value, field=f"stored runtime.{name}")
        approval_body = build_conversion_approval_body(
            {
                "source_issue": self.source_issue,
                "source_revision_hash": self.source_revision_hash,
                "v1_closure_hash": self.v1_closure_hash,
                "author_payer_agent_id": self.author_payer_agent_id,
                "account_id": self.account_id,
                "authority_binding_id": self.authority_binding_id,
                "authority_binding_version": self.authority_binding_version,
                "authority_binding_hash": self.authority_binding_hash,
                "authority_valid_from": self.authority_valid_from,
                "authority_valid_until": self.authority_valid_until,
                "plan": plan,
                "plan_bank": self.plan_bank,
                "triage_revision": self.triage_revision,
                "ruleset_identity": self.ruleset_identity,
                "runtime": runtime,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "idempotency_key": self.idempotency_key,
            }
        )
        if sha256_hex(approval_body) != self.approval_hash:
            raise Block9Error("stored approval does not bind the exact intent")
        identifier_payload = {
            "source_issue": self.source_issue,
            "source_revision_hash": self.source_revision_hash,
            "v1_closure_hash": self.v1_closure_hash,
            "author_payer_agent_id": self.author_payer_agent_id,
            "account_id": self.account_id,
            "authority_binding_id": self.authority_binding_id,
            "authority_binding_version": self.authority_binding_version,
            "authority_binding_hash": self.authority_binding_hash,
            "plan_hash": self.plan_hash,
            "plan_bank": self.plan_bank,
            "approval_hash": self.approval_hash,
            "confirmed_read_hash": self.confirmed_read_hash,
            "idempotency_key": self.idempotency_key,
        }
        if self.intent_id != (
            f"conversion:{sha256_hex(canonical_bytes(identifier_payload))}"
        ):
            raise Block9Error("conversion intent ID changed")
        if self.state not in _INTENT_STATES:
            raise Block9Error("conversion intent state is invalid")

    @property
    def plan(self) -> dict[str, object]:
        value = json.loads(self.plan_bytes)
        if type(value) is not dict:  # pragma: no cover - constructor proof
            raise Block9Error("stored Plan is not a mapping")
        return value

    def payload(self) -> dict[str, object]:
        value = asdict(self)
        value["plan"] = json.loads(value.pop("plan_bytes"))
        value["runtime"] = json.loads(value.pop("runtime_bytes"))
        return value


def build_conversion_approval_body(values: Mapping[str, object]) -> bytes:
    """Build the exact body whose authenticated revision approves conversion."""

    if type(values) is not dict or set(values) != _CONVERSION_APPROVAL_FIELDS:
        raise Block9Error("conversion approval body fields are incomplete")
    return canonical_bytes(values)


def create_conversion_intent(
    *,
    bundle: FrozenInputBundle,
    source_issue: str,
    source_revision_hash: str,
    v1_closure_hash: str,
    author_agent_id: str,
    payer_agent_id: str,
    account_id: str,
    authority_binding_id: str,
    authority_binding_version: int,
    authority_binding_hash: str,
    authority_valid_from: str,
    authority_valid_until: str,
    plan: Mapping[str, object],
    plan_bank: int,
    triage_revision: str,
    ruleset_identity: str,
    runtime: Mapping[str, object],
    approval_source: str,
    approval_revision: str,
    approval_hash: str,
    confirmed_read_hash: str,
    issued_at: str,
    expires_at: str,
    idempotency_key: str,
) -> ConversionIntent:
    data = _require_frozen_bundle(bundle)
    for field, value in (
        ("source_issue", source_issue),
        ("author_agent_id", author_agent_id),
        ("payer_agent_id", payer_agent_id),
        ("account_id", account_id),
        ("authority_binding_id", authority_binding_id),
        ("triage_revision", triage_revision),
        ("ruleset_identity", ruleset_identity),
        ("approval_source", approval_source),
        ("approval_revision", approval_revision),
        ("idempotency_key", idempotency_key),
    ):
        require_text(value, field=field)
    if author_agent_id != payer_agent_id:
        raise Block9Error("conversion author and payer must be the same Agent")
    for field, value in (
        ("source_revision_hash", source_revision_hash),
        ("v1_closure_hash", v1_closure_hash),
        ("authority_binding_hash", authority_binding_hash),
        ("approval_hash", approval_hash),
        ("confirmed_read_hash", confirmed_read_hash),
    ):
        require_hash(value, field=field)
    require_positive_int(authority_binding_version, field="authority_binding_version")
    start = parse_utc(authority_valid_from, field="authority_valid_from")
    end = parse_utc(authority_valid_until, field="authority_valid_until")
    issued = parse_utc(issued_at, field="issued_at")
    expiry = parse_utc(expires_at, field="expires_at")
    if not start <= issued < end or not issued < expiry <= end:
        raise Block9Error("conversion approval interval is not fresh")
    if type(plan) is not dict or set(plan) != {"title", "stages"}:
        raise Block9Error("conversion Plan is incomplete")
    require_text(plan["title"], field="plan.title")
    stages = _list(plan["stages"], field="plan.stages")
    if not stages:
        raise Block9Error("conversion Plan needs at least one stage")
    for stage in stages:
        stage = _mapping(stage, field="Plan stage")
        if set(stage) != {"task", "contract"}:
            raise Block9Error("Plan stage is incomplete")
        require_text(stage["task"], field="stage.task")
        require_text(stage["contract"], field="stage.contract")
    plan_bytes = canonical_bytes(plan)
    plan_hash = sha256_hex(plan_bytes)
    require_positive_int(plan_bank, field="plan_bank")
    if type(runtime) is not dict or set(runtime) != {"python", "executor", "ruleset"}:
        raise Block9Error("runtime triple is incomplete")
    for name, value in runtime.items():
        require_text(value, field=f"runtime.{name}")
    runtime_bytes = canonical_bytes(runtime)
    approval_body = build_conversion_approval_body(
        {
            "source_issue": source_issue,
            "source_revision_hash": source_revision_hash,
            "v1_closure_hash": v1_closure_hash,
            "author_payer_agent_id": author_agent_id,
            "account_id": account_id,
            "authority_binding_id": authority_binding_id,
            "authority_binding_version": authority_binding_version,
            "authority_binding_hash": authority_binding_hash,
            "authority_valid_from": authority_valid_from,
            "authority_valid_until": authority_valid_until,
            "plan": dict(plan),
            "plan_bank": plan_bank,
            "triage_revision": triage_revision,
            "ruleset_identity": ruleset_identity,
            "runtime": dict(runtime),
            "issued_at": issued_at,
            "expires_at": expires_at,
            "idempotency_key": idempotency_key,
        }
    )
    if approval_hash != sha256_hex(approval_body):
        raise Block9Error("conversion approval does not bind the exact payload")
    captured_approval: dict[str, object] | None = None
    captured_issue_revision: str | None = None
    captured_issue: dict[str, object] | None = None
    for raw_page in _list(data["github_pages"], field="github_pages"):
        page = _mapping(raw_page, field="GitHub page")
        for raw_issue in _list(page["issues"], field="GitHub page issues"):
            issue = _mapping(raw_issue, field="GitHub Issue")
            if issue["issue_id"] != source_issue:
                continue
            captured_issue = issue
            captured_issue_revision = require_hash(
                issue["revision_hash"], field="captured issue revision"
            )
            for raw_approval in _list(
                issue["approval_revisions"], field="approval revisions"
            ):
                candidate = _mapping(raw_approval, field="approval revision")
                if (
                    candidate["source_id"] == approval_source
                    and candidate["revision_id"] == approval_revision
                ):
                    if captured_approval is not None:
                        raise Block9Error("conversion approval capture is ambiguous")
                    captured_approval = candidate
    if captured_issue_revision != source_revision_hash:
        raise Block9Error("conversion Issue revision is not in the frozen input")
    if (
        captured_issue is None
        or _closure_hash_for(captured_issue, "convert-with-fresh-approval")
        != v1_closure_hash
    ):
        raise Block9Error("conversion closure is not in the frozen input")
    if captured_approval is None:
        raise Block9Error("conversion approval is not in the frozen input")
    expected_approval = {
        "account_id": account_id,
        "agent_id": author_agent_id,
        "body_hash": approval_hash,
        "confirmed_read_hash": confirmed_read_hash,
        "effective_at": issued_at,
    }
    if any(captured_approval[key] != value for key, value in expected_approval.items()):
        raise Block9Error(
            "conversion approval does not match the authenticated capture"
        )
    identities = _mapping(data["identities"], field="identities")
    identity = _mapping(identities.get(author_agent_id), field="Agent identity")
    if identity.get("account") != account_id:
        raise Block9Error("conversion account is not bound to the author Agent")
    expected_binding = (
        author_agent_id,
        account_id,
        authority_binding_id,
        authority_binding_version,
        authority_binding_hash,
        authority_valid_from,
        authority_valid_until,
    )
    captured_bindings = tuple(
        ConversionAuthorityBinding.from_mapping(value)
        for value in _list(data["authority_bindings"], field="authority_bindings")
    )
    matches = tuple(
        binding
        for binding in captured_bindings
        if (
            binding.agent_id,
            binding.account_id,
            binding.binding_id,
            binding.binding_version,
            binding.binding_hash,
            binding.effective_from,
            binding.effective_until,
        )
        == expected_binding
    )
    if len(matches) != 1 or not matches[0].active_at(issued_at):
        raise Block9Error("conversion authority is not in the frozen input")
    identifier_payload = {
        "source_issue": source_issue,
        "source_revision_hash": source_revision_hash,
        "v1_closure_hash": v1_closure_hash,
        "author_payer_agent_id": author_agent_id,
        "account_id": account_id,
        "authority_binding_id": authority_binding_id,
        "authority_binding_version": authority_binding_version,
        "authority_binding_hash": authority_binding_hash,
        "plan_hash": plan_hash,
        "plan_bank": plan_bank,
        "approval_hash": approval_hash,
        "confirmed_read_hash": confirmed_read_hash,
        "idempotency_key": idempotency_key,
    }
    intent_id = f"conversion:{sha256_hex(canonical_bytes(identifier_payload))}"
    return ConversionIntent(
        intent_id=intent_id,
        source_issue=source_issue,
        source_revision_hash=source_revision_hash,
        v1_closure_hash=v1_closure_hash,
        author_payer_agent_id=author_agent_id,
        account_id=account_id,
        authority_binding_id=authority_binding_id,
        authority_binding_version=authority_binding_version,
        authority_binding_hash=authority_binding_hash,
        authority_valid_from=authority_valid_from,
        authority_valid_until=authority_valid_until,
        plan_bytes=plan_bytes,
        plan_hash=plan_hash,
        plan_bank=plan_bank,
        triage_revision=triage_revision,
        ruleset_identity=ruleset_identity,
        runtime_bytes=runtime_bytes,
        approval_source=approval_source,
        approval_revision=approval_revision,
        approval_hash=approval_hash,
        confirmed_read_hash=confirmed_read_hash,
        issued_at=issued_at,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
        state="pending",
    )


def _rebuild_conversion_intent(
    bundle: FrozenInputBundle, intent: ConversionIntent
) -> ConversionIntent:
    runtime = json.loads(intent.runtime_bytes)
    rebuilt = create_conversion_intent(
        bundle=bundle,
        source_issue=intent.source_issue,
        source_revision_hash=intent.source_revision_hash,
        v1_closure_hash=intent.v1_closure_hash,
        author_agent_id=intent.author_payer_agent_id,
        payer_agent_id=intent.author_payer_agent_id,
        account_id=intent.account_id,
        authority_binding_id=intent.authority_binding_id,
        authority_binding_version=intent.authority_binding_version,
        authority_binding_hash=intent.authority_binding_hash,
        authority_valid_from=intent.authority_valid_from,
        authority_valid_until=intent.authority_valid_until,
        plan=intent.plan,
        plan_bank=intent.plan_bank,
        triage_revision=intent.triage_revision,
        ruleset_identity=intent.ruleset_identity,
        runtime=runtime,
        approval_source=intent.approval_source,
        approval_revision=intent.approval_revision,
        approval_hash=intent.approval_hash,
        confirmed_read_hash=intent.confirmed_read_hash,
        issued_at=intent.issued_at,
        expires_at=intent.expires_at,
        idempotency_key=intent.idempotency_key,
    )
    if rebuilt != intent:
        raise Block9Error("conversion intent changed after evidence validation")
    return rebuilt


_CONVERSION_INTENT_PAYLOAD_FIELDS = {
    "intent_id",
    "source_issue",
    "source_revision_hash",
    "v1_closure_hash",
    "author_payer_agent_id",
    "account_id",
    "authority_binding_id",
    "authority_binding_version",
    "authority_binding_hash",
    "authority_valid_from",
    "authority_valid_until",
    "plan",
    "plan_hash",
    "plan_bank",
    "triage_revision",
    "ruleset_identity",
    "runtime",
    "approval_source",
    "approval_revision",
    "approval_hash",
    "confirmed_read_hash",
    "issued_at",
    "expires_at",
    "idempotency_key",
    "state",
}


def _conversion_intent_from_mapping(value: object) -> ConversionIntent:
    mapping = _mapping(value, field="genesis conversion intent")
    if set(mapping) != _CONVERSION_INTENT_PAYLOAD_FIELDS:
        raise Block9Error("genesis conversion intent fields are incomplete")

    def text(field: str) -> str:
        return require_text(mapping[field], field=f"genesis conversion intent {field}")

    return ConversionIntent(
        intent_id=text("intent_id"),
        source_issue=text("source_issue"),
        source_revision_hash=text("source_revision_hash"),
        v1_closure_hash=text("v1_closure_hash"),
        author_payer_agent_id=text("author_payer_agent_id"),
        account_id=text("account_id"),
        authority_binding_id=text("authority_binding_id"),
        authority_binding_version=require_positive_int(
            mapping["authority_binding_version"],
            field="genesis conversion intent authority_binding_version",
        ),
        authority_binding_hash=text("authority_binding_hash"),
        authority_valid_from=text("authority_valid_from"),
        authority_valid_until=text("authority_valid_until"),
        plan_bytes=canonical_bytes(mapping["plan"]),
        plan_hash=text("plan_hash"),
        plan_bank=require_positive_int(
            mapping["plan_bank"], field="genesis conversion intent plan_bank"
        ),
        triage_revision=text("triage_revision"),
        ruleset_identity=text("ruleset_identity"),
        runtime_bytes=canonical_bytes(mapping["runtime"]),
        approval_source=text("approval_source"),
        approval_revision=text("approval_revision"),
        approval_hash=text("approval_hash"),
        confirmed_read_hash=text("confirmed_read_hash"),
        issued_at=text("issued_at"),
        expires_at=text("expires_at"),
        idempotency_key=text("idempotency_key"),
        state=text("state"),
    )


@dataclass(frozen=True, slots=True)
class ConversionActivationState:
    balances: Mapping[str, int]
    program_escrows: Mapping[str, int]
    plans: Mapping[str, Mapping[str, object]]
    tasks: Mapping[str, Mapping[str, object]]
    first_contracts: Mapping[str, Mapping[str, object]]
    idempotency: Mapping[str, ConversionIdempotencyRecord]


@dataclass(frozen=True, slots=True)
class ConversionIdempotencyRecord:
    key: str
    intent_id: str
    state: str

    def __post_init__(self) -> None:
        require_text(self.key, field="conversion idempotency key")
        require_text(self.intent_id, field="conversion idempotency intent_id")
        if self.state not in {"consumed", "cancelled", "expired"}:
            raise Block9Error("conversion idempotency state is not terminal")


def _activation_state(
    *,
    balances: Mapping[str, int],
    program_escrows: Mapping[str, int] | None = None,
    plans: Mapping[str, Mapping[str, object]] | None = None,
    tasks: Mapping[str, Mapping[str, object]] | None = None,
    first_contracts: Mapping[str, Mapping[str, object]] | None = None,
    idempotency: Mapping[str, ConversionIdempotencyRecord] | None = None,
) -> ConversionActivationState:
    return ConversionActivationState(
        MappingProxyType(dict(balances)),
        MappingProxyType(dict(program_escrows or {})),
        MappingProxyType(dict(plans or {})),
        MappingProxyType(dict(tasks or {})),
        MappingProxyType(dict(first_contracts or {})),
        MappingProxyType(
            {
                key: ConversionIdempotencyRecord(
                    value.key, value.intent_id, value.state
                )
                for key, value in (idempotency or {}).items()
            }
        ),
    )


def activate_conversion_intent(
    intent: ConversionIntent,
    *,
    balances: Mapping[str, int],
    authority_bindings: tuple[ConversionAuthorityBinding, ...],
    effective_at: str,
    existing: ConversionActivationState | None = None,
) -> tuple[ConversionIntent, ConversionActivationState]:
    if type(intent) is not ConversionIntent:
        raise Block9Error("conversion intent must use the exact type")
    if intent.state not in _INTENT_STATES:
        raise Block9Error("conversion intent state is invalid")
    if type(authority_bindings) is not tuple or any(
        type(binding) is not ConversionAuthorityBinding
        for binding in authority_bindings
    ):
        raise Block9Error("current conversion authority registry is invalid")
    at = parse_utc(effective_at, field="effective_at")
    if existing is not None and type(existing) is not ConversionActivationState:
        raise Block9Error("conversion activation state must use the exact type")
    current = existing or _activation_state(balances=balances)
    record = current.idempotency.get(intent.idempotency_key)
    if record is not None:
        if record.intent_id != intent.intent_id:
            raise Block9Error("conversion idempotency record conflicts")
        if intent.state not in {"pending", record.state}:
            raise Block9Error("conversion idempotency state conflicts")
        return replace(intent, state=record.state), current
    if intent.state != "pending":
        return intent, current
    current_bindings = tuple(
        binding
        for binding in authority_bindings
        if binding.agent_id == intent.author_payer_agent_id
        and binding.account_id == intent.account_id
        and binding.active_at(effective_at)
    )
    if len(current_bindings) != 1:
        raise Block9Error("conversion authority is absent or ambiguous")
    current_binding = current_bindings[0]
    if (
        current_binding.binding_id,
        current_binding.binding_version,
        current_binding.binding_hash,
    ) != (
        intent.authority_binding_id,
        intent.authority_binding_version,
        intent.authority_binding_hash,
    ):
        raise Block9Error("conversion authority binding changed")
    start = parse_utc(intent.authority_valid_from, field="authority_valid_from")
    end = parse_utc(intent.authority_valid_until, field="authority_valid_until")
    issued = parse_utc(intent.issued_at, field="issued_at")
    expiry = parse_utc(intent.expires_at, field="expires_at")
    if not start <= at < end:
        raise Block9Error("conversion authority is not active")
    if at < issued:
        raise Block9Error("conversion approval is not yet effective")
    if at >= expiry:
        expired = replace(intent, state="expired")
        return expired, _activation_state(
            balances=current.balances,
            program_escrows=current.program_escrows,
            plans=current.plans,
            tasks=current.tasks,
            first_contracts=current.first_contracts,
            idempotency={
                **current.idempotency,
                intent.idempotency_key: ConversionIdempotencyRecord(
                    intent.idempotency_key, intent.intent_id, "expired"
                ),
            },
        )
    amount = current.balances.get(intent.author_payer_agent_id)
    if type(amount) is not int or amount < intent.plan_bank:
        cancelled = replace(intent, state="cancelled")
        return cancelled, _activation_state(
            balances=current.balances,
            program_escrows=current.program_escrows,
            plans=current.plans,
            tasks=current.tasks,
            first_contracts=current.first_contracts,
            idempotency={
                **current.idempotency,
                intent.idempotency_key: ConversionIdempotencyRecord(
                    intent.idempotency_key, intent.intent_id, "cancelled"
                ),
            },
        )
    if intent.intent_id in current.program_escrows:
        raise Block9Error("conversion would create duplicate program escrow")
    plan = intent.plan
    stages = _list(plan["stages"], field="plan.stages")
    stage = _mapping(stages[0], field="Plan stage")
    updated_balances = dict(current.balances)
    updated_balances[intent.author_payer_agent_id] = amount - intent.plan_bank
    consumed = replace(intent, state="consumed")
    updated = _activation_state(
        balances=updated_balances,
        program_escrows={**current.program_escrows, intent.intent_id: intent.plan_bank},
        plans={**current.plans, intent.intent_id: plan},
        tasks={**current.tasks, intent.intent_id: {"task": stage["task"]}},
        first_contracts={
            **current.first_contracts,
            intent.intent_id: {"contract": stage["contract"]},
        },
        idempotency={
            **current.idempotency,
            intent.idempotency_key: ConversionIdempotencyRecord(
                intent.idempotency_key, intent.intent_id, "consumed"
            ),
        },
    )
    return consumed, updated


def build_genesis(
    bundle: FrozenInputBundle,
    reconciliation: ReconciliationReport,
    intents: tuple[ConversionIntent, ...],
) -> bytes:
    if (
        type(bundle) is not FrozenInputBundle
        or type(reconciliation) is not ReconciliationReport
    ):
        raise Block9Error("genesis inputs must use exact types")
    if reconciliation.input_hash != bundle.input_hash:
        raise Block9Error("reconciliation does not bind the input")
    if reconciliation.unexplained_amount:
        raise Block9Error("reconciliation contains unexplained money")
    rebuilt_reconciliation = reconcile_obligations(
        bundle,
        {
            item.issue_id: {
                "outcome": item.outcome,
                "closure_hash": item.closure_hash,
            }
            for item in reconciliation.outcomes
        },
    )
    if rebuilt_reconciliation != reconciliation:
        raise Block9Error("reconciliation report changed after validation")
    if type(intents) is not tuple:
        raise Block9Error("conversion intents must be a tuple")
    seen: set[str] = set()
    seen_sources: set[str] = set()
    intent_payloads: list[dict[str, object]] = []
    outcome_by_issue = {item.issue_id: item for item in reconciliation.outcomes}
    for intent in sorted(intents, key=lambda item: item.intent_id):
        if type(intent) is not ConversionIntent or intent.state != "pending":
            raise Block9Error("genesis can preserve only pending conversion intents")
        intent = _rebuild_conversion_intent(bundle, intent)
        if intent.intent_id in seen:
            raise Block9Error("genesis contains a duplicate conversion intent")
        if intent.source_issue in seen_sources:
            raise Block9Error("genesis contains duplicate intents for one Issue")
        outcome = outcome_by_issue.get(intent.source_issue)
        if outcome is None or outcome.outcome != "convert-with-fresh-approval":
            raise Block9Error("conversion intent does not have a conversion outcome")
        if outcome.closure_hash != intent.v1_closure_hash:
            raise Block9Error(
                "conversion intent does not bind the reconciled v1 closure"
            )
        seen.add(intent.intent_id)
        seen_sources.add(intent.source_issue)
        intent_payloads.append(intent.payload())
    required_sources = {
        issue_id
        for issue_id, outcome in outcome_by_issue.items()
        if outcome.outcome == "convert-with-fresh-approval"
    }
    if seen_sources != required_sources:
        raise Block9Error("genesis does not preserve every conversion outcome")
    data = bundle.data
    balances: dict[str, int] = {}
    for raw_account, raw_amount in _mapping(
        data["balances"], field="genesis balances"
    ).items():
        account = require_text(raw_account, field="genesis account")
        balances[account] = _nonnegative(raw_amount, field="genesis balance")
    balances = dict(sorted(balances.items()))
    hello_world_keys = sorted(
        require_text(item, field="hello_world_key")
        for item in _list(data["hello_world_keys"], field="hello_world_keys")
    )
    history_refs = sorted(
        require_text(item, field="history_ref")
        for item in _list(data["history_refs"], field="history_refs")
    )
    opening_supply = sum(balances.values())
    payload = {
        "schema": "wea-vnext-genesis-1",
        "input_hash": bundle.input_hash,
        "reconciliation_hash": reconciliation.report_hash,
        "predecessor": data["predecessor"],
        "source_hashes": data["source_hashes"],
        "balances": balances,
        "opening_supply": opening_supply,
        "identities": data["identities"],
        "genomes": data["genomes"],
        "hello_world_keys": hello_world_keys,
        "history_refs": history_refs,
        "conversion_intents": intent_payloads,
        "historical": {
            "gauntlet": data["gauntlet_history"],
            "achievements": data["achievement_history"],
        },
    }
    return canonical_bytes(payload)


def replay_genesis(genesis: bytes) -> dict[str, object]:
    if type(genesis) is not bytes:
        raise Block9Error("genesis must be exact bytes")
    try:
        value = json.loads(genesis)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Block9Error("genesis is not JSON") from exc
    if type(value) is not dict or canonical_bytes(value) != genesis:
        raise Block9Error("genesis bytes are not canonical")
    required = {
        "schema",
        "input_hash",
        "reconciliation_hash",
        "predecessor",
        "source_hashes",
        "balances",
        "opening_supply",
        "identities",
        "genomes",
        "hello_world_keys",
        "history_refs",
        "conversion_intents",
        "historical",
    }
    if set(value) != required or value["schema"] != "wea-vnext-genesis-1":
        raise Block9Error("genesis schema is incomplete")
    require_hash(value["input_hash"], field="genesis input_hash")
    require_hash(value["reconciliation_hash"], field="genesis reconciliation_hash")
    require_hash(value["predecessor"], field="genesis predecessor", length=40)
    source_hashes = _mapping(value["source_hashes"], field="genesis source_hashes")
    if not source_hashes:
        raise Block9Error("genesis source_hashes cannot be empty")
    for name, digest in source_hashes.items():
        require_text(name, field="genesis source hash name")
        require_hash(digest, field=f"genesis source_hashes.{name}")
    balances = _mapping(value["balances"], field="genesis balances")
    if not balances:
        raise Block9Error("genesis balances cannot be empty")
    for agent_id in balances:
        require_text(agent_id, field="genesis balance Agent ID")
    calculated = sum(
        _nonnegative(amount, field="genesis balance") for amount in balances.values()
    )
    opening_supply = _nonnegative(
        value["opening_supply"], field="genesis opening_supply"
    )
    if opening_supply != calculated:
        raise Block9Error("genesis opening supply does not match balances")
    identities = _mapping(value["identities"], field="genesis identities")
    genomes = _mapping(value["genomes"], field="genesis genomes")
    if not set(identities).issubset(balances) or not set(genomes).issubset(balances):
        raise Block9Error("genesis identity or genome has no balance row")
    for agent_id, identity in identities.items():
        require_text(agent_id, field="genesis identity Agent ID")
        _mapping(identity, field=f"genesis identity {agent_id}")
    for agent_id, genome in genomes.items():
        require_text(agent_id, field="genesis genome Agent ID")
        _mapping(genome, field=f"genesis genome {agent_id}")
    for field in ("hello_world_keys", "history_refs"):
        items = _list(value[field], field=f"genesis {field}")
        rebuilt_items = sorted(
            require_text(item, field=f"genesis {field} item") for item in items
        )
        if items != rebuilt_items:
            raise Block9Error(f"genesis {field} is not canonical")
    historical = _mapping(value["historical"], field="genesis historical")
    if set(historical) != {"gauntlet", "achievements"}:
        raise Block9Error("genesis historical fields are incomplete")
    _list(historical["gauntlet"], field="genesis gauntlet history")
    _list(historical["achievements"], field="genesis achievement history")
    raw_intents = _list(value["conversion_intents"], field="genesis conversion_intents")
    intents = tuple(_conversion_intent_from_mapping(item) for item in raw_intents)
    if any(intent.state != "pending" for intent in intents):
        raise Block9Error("genesis conversion intent must remain pending")
    if tuple(sorted(intents, key=lambda item: item.intent_id)) != intents:
        raise Block9Error("genesis conversion intents are not canonical")
    if len({item.intent_id for item in intents}) != len(intents):
        raise Block9Error("genesis conversion intent ID appears more than once")
    if len({item.source_issue for item in intents}) != len(intents):
        raise Block9Error("genesis conversion source Issue appears more than once")
    if len({item.idempotency_key for item in intents}) != len(intents):
        raise Block9Error("genesis conversion idempotency key appears more than once")
    return value


def reject_retired_write(command: str) -> None:
    if command not in _RETIRED_COMMANDS:
        raise Block9Error("unknown retired command")
    raise Block9Error(f"{command} is historical-only after cutover")


__all__ = [
    "ConversionActivationState",
    "ConversionIdempotencyRecord",
    "ConversionIntent",
    "FrozenInputBundle",
    "ReconciliationOutcome",
    "ReconciliationReport",
    "activate_conversion_intent",
    "build_conversion_approval_body",
    "build_genesis",
    "create_conversion_intent",
    "freeze_input_bundle",
    "reconcile_obligations",
    "reject_retired_write",
    "replay_genesis",
]
