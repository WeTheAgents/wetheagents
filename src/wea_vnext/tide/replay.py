"""Replay retained Tide batches through the exact task executor, never postings."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ..engine import installed_executor, load_executor
from . import records

EXECUTOR = "0.9.0"


def json_data(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            item.name: json_data(getattr(value, item.name))
            for item in dataclasses.fields(value)
            if not item.name.startswith("_")
        }
    if isinstance(value, Mapping):
        return {key: json_data(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_data(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if value is None or type(value) in (int, str, bool):
        return value
    raise ValueError(f"unsupported replay value: {type(value).__name__}")


def canonical(value: Any) -> bytes:
    return json.dumps(
        json_data(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class ReplayError(ValueError):
    """Retained history or the global financial invariant is inconsistent."""


class Replay:
    """Ephemeral verified objects reconstructed only from canonical raw history."""

    def __init__(self, bootstrap: dict[str, Any]) -> None:
        reference = installed_executor(EXECUTOR).reference
        if bootstrap["runtime"] != list(reference):
            raise ReplayError("activation runtime differs from the installed executor")
        self.modules = load_executor(reference).import_modules(
            ("identity", "intake", "lifecycle", "sources")
        )
        self.registry = records.registry(self.modules, bootstrap["identities"])
        self.balances = dict(bootstrap["balances"])
        if any(type(value) is not int or value < 0 for value in self.balances.values()):
            raise ReplayError("opening balances must be nonnegative integers")
        self.supply = sum(self.balances.values())
        self.bootstrap = bootstrap
        self.intakes: dict[str, Any] = {}
        self.drafts: dict[str, Any] = {}
        self.runtimes: dict[str, Any] = {}
        self.funding_batches: dict[str, str] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.processed: set[str] = set()
        self.sequence = 0
        self.last_cutoff: datetime | None = None
        self.last_hash = digest(bootstrap)
        self.dispositions: dict[str, dict[str, str]] = {}

    def _event(self, raw: dict[str, Any]) -> Any:
        payload = {"issue_number": raw["issue_number"], "issue_id": raw["issue_id"]}
        if "artifact" in raw:
            payload["artifact"] = raw["artifact"]
        return self.modules["intake"].GitHubEvent.from_revision(
            repository="WeTheAgents/wetheagents",
            repository_id=str(raw["repository_id"]),
            object_kind=raw["object_kind"],
            object_id=str(raw["object_id"]),
            revision_id=raw["revision_id"],
            effective_at=records.timestamp(raw["effective_at"]),
            body=raw["body"],
            actor_account_id=str(raw["actor_account_id"]),
            payload=payload,
        )

    def _evidence(self, cutoff: datetime) -> tuple[Any, list[Any]]:
        intake = self.modules["intake"]
        events = [
            self._event(raw)
            for raw in self.sources.values()
            if raw["revision_status"] == "confirmed"
            and records.timestamp(raw["effective_at"]) <= cutoff
        ]
        boundary = intake.GitHubReadBoundary(
            repository="WeTheAgents/wetheagents",
            repository_id=str(self.bootstrap["repository_id"]),
            captured_at=cutoff,
            read_sequence=self.sequence,
            end_cursor=f"tide:{self.sequence}",
            complete=True,
        )
        evidence = intake.accept_github_evidence_batch(
            intake.initial_github_evidence_state(),
            intake.GitHubEventBatch(boundary=boundary, events=tuple(events)),
        )
        return evidence, sorted(events, key=lambda item: item.canonical_order_key)

    def _balance_records(self) -> tuple[Any, ...]:
        cls = self.modules["intake"].AccountBalance
        return tuple(cls(key, value) for key, value in sorted(self.balances.items()))

    def _apply_delta(self, before: Any, after: Any) -> None:
        old = {item.account_id: item.amount_wea for item in before}
        new = {item.account_id: item.amount_wea for item in after}
        candidate = dict(self.balances)
        for key in old.keys() | new.keys():
            candidate[key] = candidate.get(key, 0) + new.get(key, 0) - old.get(key, 0)
        if any(value < 0 for value in candidate.values()):
            raise ReplayError("cross-Plan available balance is insufficient")
        self.balances = candidate

    def _handle(
        self,
        event: Any,
        events: list[Any],
        evidence: Any,
        batch_id: str,
        cutoff: datetime,
        funding_merges: dict[str, str],
    ) -> str:
        intake, lifecycle, sources = (
            self.modules[key] for key in ("intake", "lifecycle", "sources")
        )
        data = sources.declaration(event.body)
        if data is None:
            if event.body.startswith("### WEA common-control disclosure\n"):
                accepted = any(
                    item.kind == "control_disclosure"
                    and item.payload["disclosure_revision_id"] == event.revision_id
                    for state in self.runtimes.values()
                    for item in state.events
                )
                if not accepted:
                    raise ValueError(
                        "common-control disclosure is not authorized "
                        "or does not match pending Work"
                    )
                return "common-control disclosure confirmed"
            return "not a protocol declaration"
        raw = self.sources[event.revision_id]
        issue = str(raw["issue_id"])
        kind = data["kind"]
        if str(event.repository_id) != str(self.bootstrap["repository_id"]):
            raise ReplayError("source belongs to another repository")
        if kind == "draft_issue":
            if (
                self.sources[event.revision_id].get("original_author_account_id")
                != event.actor_account_id
            ):
                raise ValueError(
                    "Draft revision must come from the original Issue author"
                )
            candidate = records.draft(self.modules, event)
            authority = self.modules["identity"].authorize_agent(
                github_account_id=event.actor_account_id,
                agent_id=candidate.author_agent_id,
                effective_at=event.effective_at,
                registry=self.registry,
            )
            if (
                authority.account_binding_id != candidate.author_binding_id
                or authority.account_binding_version != candidate.author_binding_version
            ):
                raise ValueError(
                    "Draft author binding differs from the source authority"
                )
            if issue in self.runtimes:
                raise ValueError(
                    "active Issue body changed; body-integrity resolution is required"
                )
            if issue in self.drafts and self.drafts[issue] != candidate:
                if self.drafts[issue].author_agent_id != candidate.author_agent_id:
                    raise ValueError("a retained Draft cannot change its author Agent")
                # No funds exist before activation. Retain the old sources in
                # history, but require a fresh Triage/Plan chain for this revision.
                self.intakes[issue] = intake.PlanIntakeState(
                    balances=self._balance_records()
                )
            self.drafts[issue] = candidate
            self.intakes.setdefault(
                issue, intake.PlanIntakeState(balances=self._balance_records())
            )
            return "Draft retained"
        draft = self.drafts.get(issue)
        if draft is None:
            raise ValueError("exact Draft has not been accepted")
        if kind in {"triage_assignment", "triage_assessment"}:
            records.authenticate_triage(self.modules, event, self.registry)
            return "Triage source retained; completion required"
        if kind == "triage_completion":
            assessment = records.assessment(
                self.modules,
                event,
                [
                    item
                    for item in events
                    if str(self.sources[item.revision_id]["issue_id"]) == issue
                ],
                self.registry,
            )
            self.intakes[issue] = intake.call_verified(
                "record_triage_assessment",
                self.intakes[issue],
                draft,
                assessment,
                registry=self.registry,
                github_state=evidence,
            )
            return "Triage completed"
        if kind == "resolution_plan_revision":
            revision = records.plan(self.modules, event)
            if (
                revision.issue_id != issue
                or revision.repository_id != event.repository_id
            ):
                raise ValueError("Plan is posted on another Issue")
            if issue in self.runtimes:
                return "suffix proposal retained; exact author approval required"
            self.intakes[issue] = intake.call_verified(
                "record_plan_revision",
                self.intakes[issue],
                draft,
                revision,
                registry=self.registry,
                github_state=evidence,
            )
            return "Plan revision accepted"
        if kind == "author_plan_decision":
            decision = records.decision(self.modules, event)
            state = intake.call_verified(
                "record_author_plan_decision",
                self.intakes[issue],
                draft,
                decision,
                registry=self.registry,
                github_state=evidence,
            )
            if decision.outcome != "approve":
                self.intakes[issue] = state
                return "author decision retained"
            if issue in self.runtimes:
                raise ValueError(
                    "Plan is already funded; use the suffix-replan protocol"
                )
            # Unactivated records carry no financial authority. Refresh available funds
            # immediately before the executor performs the one atomic full-bank debit.
            state = intake.PlanIntakeState(
                balances=self._balance_records(),
                triage_assessments=state.triage_assessments,
                plan_revisions=state.plan_revisions,
                decisions=state.decisions,
            )
            activation = intake.call_verified(
                "activate_resolution_plan",
                state,
                draft,
                plan_revision_id=decision.plan_revision_id,
                decision_id=decision.decision_id,
                payer_agent_id=draft.author_agent_id,
                payer_github_account_id=draft.creator_github_account_id,
                effective_at=cutoff,
                registry=self.registry,
                github_state=evidence,
            )
            runtime = lifecycle.start_runtime(activation)
            self._apply_delta(state.balances, activation.state.balances)
            self.intakes[issue] = activation.state
            self.runtimes[issue] = runtime
            self.funding_batches[issue] = batch_id
            return "full bank escrowed; work starts only after this Tide merges"
        state = self.runtimes.get(issue)
        if state is None:
            raise ValueError("Plan is not funded")
        funding_batch = self.funding_batches[issue]
        merged_at = funding_merges.get(funding_batch)
        if merged_at is None or event.effective_at <= records.timestamp(merged_at):
            raise ValueError(
                "source predates confirmed funding merge; "
                "submit a new declaration after funding"
            )
        if kind not in {"work", "lifecycle"}:
            raise ValueError("unsupported declaration requires coordinator review")
        derived = lifecycle.derive_source_event(event, state)
        revision = None
        if derived.kind == "suffix_replan":
            target = derived.payload["plan_revision_id"]
            matches = []
            for candidate in events:
                try:
                    item = records.plan(self.modules, candidate)
                except (ValueError, KeyError, TypeError):
                    continue
                if item.revision_id == target:
                    matches.append(item)
            if len(matches) != 1:
                raise ValueError("exact suffix proposal is missing or ambiguous")
            revision = matches[0]
        old = lifecycle.project_runtime(state)
        new_state = lifecycle.call_verified(
            "apply_lifecycle_event",
            state,
            derived,
            registry=self.registry,
            github_state=evidence,
            plan_revision=revision,
            funding_merged_at=records.timestamp(merged_at),
        )
        new = lifecycle.project_runtime(new_state)
        self._apply_delta(old.balances, new.balances)
        self.runtimes[issue] = new_state
        return "executor transition accepted"

    def apply(self, batch: dict[str, Any]) -> dict[str, Any]:
        if (
            batch["previous_hash"] != self.last_hash
            or batch["sequence"] != self.sequence + 1
        ):
            raise ReplayError("Tide predecessor or sequence differs")
        cutoff = records.timestamp(batch["collection"]["cutoff"])
        if self.last_cutoff is not None and cutoff <= self.last_cutoff:
            raise ReplayError("Tide cutoff must advance")
        self.sequence += 1
        for raw in batch["collection"]["sources"]:
            key = (
                raw["revision_id"]
                or f"unresolved:{raw['object_id']}:{raw['content_hash']}"
            )
            old = self.sources.get(key)
            if old is not None:
                stable = (
                    "body",
                    "actor_account_id",
                    "effective_at",
                    "object_id",
                    "repository_id",
                )
                if any(old[field] != raw[field] for field in stable):
                    raise ReplayError("retained source revision changed")
            if records.timestamp(raw["effective_at"]) > cutoff:
                raise ReplayError("source is after the fixed cutoff")
            if hashlib.sha256(raw["body"].encode()).hexdigest() != raw["content_hash"]:
                raise ReplayError("raw source hash differs")
            self.sources[key] = raw
            if raw["revision_status"] != "confirmed":
                self.dispositions[key] = {
                    "status": "unresolved",
                    "reason": "required GitHub edit evidence is missing",
                }
        evidence, events = self._evidence(cutoff)
        latest = {
            (event.object_kind, event.object_id): event.revision_id for event in events
        }
        blocked_issues = set()
        for key, raw in self.sources.items():
            if raw["revision_status"] == "confirmed":
                continue
            confirmed = [
                item
                for item in self.sources.values()
                if item["revision_status"] == "confirmed"
                and all(
                    item[field] == raw[field]
                    for field in (
                        "repository_id",
                        "object_kind",
                        "object_id",
                        "issue_id",
                        "body",
                        "effective_at",
                    )
                )
            ]
            if len(confirmed) == 1:
                self.dispositions[key] = {
                    "status": "resolved",
                    "reason": "exact revision verified: " + confirmed[0]["revision_id"],
                }
            else:
                blocked_issues.add(str(raw["issue_id"]))
        # Current GitHub bodies cannot prove an unobserved intervening edit.
        # Retain the gap and block only its active task, including clock effects.
        for raw in batch["collection"]["sources"]:
            issue = str(raw["issue_id"])
            if raw["object_kind"] != "issue" or issue not in self.runtimes:
                continue
            draft_revision = self.runtimes[issue].activation.draft.issue_revision_id
            anchor = records.timestamp(self.sources[draft_revision]["effective_at"])
            missing = [
                edit["revision_id"]
                for edit in raw.get("edit_history", [])
                if records.timestamp(edit["effective_at"]) > anchor
                and edit["revision_id"] not in self.sources
            ]
            if missing:
                blocked_issues.add(issue)
                self.dispositions[raw["revision_id"]] = {
                    "status": "unresolved",
                    "reason": "active Issue has unobserved body revisions: "
                    + ", ".join(sorted(missing)),
                }
        for event in events:
            key = event.revision_id
            if key in self.processed:
                continue
            if latest[(event.object_kind, event.object_id)] != key:
                continue
            try:
                if str(self.sources[key]["issue_id"]) in blocked_issues:
                    raise ValueError("Issue has unresolved content-edit evidence")
                self._maintenance(
                    event.effective_at, batch["funding_merges"], blocked_issues
                )
                reason = self._handle(
                    event,
                    events,
                    evidence,
                    batch["batch_id"],
                    cutoff,
                    batch["funding_merges"],
                )
            except (ValueError, KeyError, TypeError, RecursionError) as exc:
                self.dispositions[key] = {"status": "unresolved", "reason": str(exc)}
                continue
            self.processed.add(key)
            if reason != "not a protocol declaration":
                self.dispositions[key] = {"status": "accepted", "reason": reason}
        self._maintenance(cutoff, batch["funding_merges"], blocked_issues)
        self.last_hash = digest(batch)
        self.last_cutoff = cutoff
        return self.state()

    def _maintenance(
        self, through: datetime, merges: dict[str, str], blocked: set[str]
    ) -> None:
        lifecycle = self.modules["lifecycle"]
        evidence, _ = self._evidence(through)
        for issue, state in sorted(self.runtimes.items()):
            merged_at = merges.get(self.funding_batches[issue])
            if (
                issue in blocked
                or merged_at is None
                or records.timestamp(merged_at) > through
            ):
                continue
            old = lifecycle.project_runtime(state)
            new_state = lifecycle.call_verified(
                "apply_tide_maintenance",
                state,
                through=through,
                funding_merged_at=records.timestamp(merged_at),
                registry=self.registry,
                github_state=evidence,
            )
            new = lifecycle.project_runtime(new_state)
            self._apply_delta(old.balances, new.balances)
            self.runtimes[issue] = new_state

    def state(self) -> dict[str, Any]:
        projections = {
            issue: self.modules["lifecycle"].project_runtime(state)
            for issue, state in sorted(self.runtimes.items())
        }
        escrow = sum(
            item.escrow.deposited_wea - item.escrow.paid_wea - item.escrow.refunded_wea
            for item in projections.values()
        )
        escrow += sum(
            role.escrow_available_wea
            for item in projections.values()
            for role in item.roles
        )
        if sum(self.balances.values()) + escrow != self.supply:
            raise ReplayError("global balances plus escrow do not equal opening supply")
        return json_data(
            {
                "schema": "wea-tide-state-1",
                "sequence": self.sequence,
                "last_hash": self.last_hash,
                "cutoff": self.last_cutoff,
                "balances": self.balances,
                "opening_supply": self.supply,
                "escrow_wea": escrow,
                "tasks": projections,
                "funding_batches": self.funding_batches,
                "dispositions": self.dispositions,
            }
        )


def replay(bootstrap: dict[str, Any], batches: list[dict[str, Any]]) -> dict[str, Any]:
    engine = Replay(bootstrap)
    for batch in batches:
        engine.apply(batch)
    return engine.state()
