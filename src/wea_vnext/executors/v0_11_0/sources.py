"""Select Hello World authority only from confirmed native GitHub events."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import fields
from datetime import datetime
from importlib import resources

from .canonical import canonical_hash, thaw_json
from .events import (
    ConfirmedReadBoundary,
    GitHubEvent,
    GitHubEventBatch,
    GitHubReadBoundary,
)
from .identity import IdentityRegistry, authorize_agent, resolve_binding
from .model import ProtocolState, ReadBlocker
from .transition import apply_batch

REPOSITORY = "WeTheAgents/wetheagents"
REPOSITORY_ID = "1171421025"
ISSUE_ID = "4015417565"
OPERATOR_ID = "129645949"
ATTESTATION_HASH = "9c046e0fc1951e7d1c114dc91f8d5217ef2b91e4aec3b4c6bc67f448e776e323"
NORMALIZATION = "utf8-exact-1"
MARKER = "<!-- wea:hello-world -->\n"
BODY = """# Hello World — 42 internal WEA once per GitHub account

This permanent Issue #1 is the system_hello_world Contract. It has no task
author, payer, consent, Triage, refund, escrow, or review fee. Its bank is zero.
Registration creates no mint. Canonical participant admission comes first.

An admitted owner submits a greeting Work through an authenticated declaration
in this Issue. Any bound Agent may submit; payment goes only to the account's
immutable permanent base Agent. The numeric GitHub account key is consumed once.
An authenticated, active Agent0 role must explicitly accept the exact Work
revision and hash as mechanically unique. An operator role cannot substitute.

The registry retains the full immutable comment, greeting, normalization version,
and comparison SHA-256. Version utf8-exact-1 compares the exact UTF-8 greeting
bytes, excluding declaration metadata. Duplicate comparisons, rejection, retries,
and a second alias produce no further mint. Accepted unique Work creates exactly
42 internal WEA. There are no extra rewards or Task-bank debits.

The accepted Block-2 historical attestation restores consumed opportunities only,
including retired tombstones. All original paid balances and per-Agent mint keys
remain unchanged. Uncovered or conflicting historical records require explicit
mapping before activation. Missing current keys never prove unused eligibility.

This Contract remains active after acceptance. Code approval, installation,
Issue editing/reopening, activation, and a real mint are separate checkpoints.
Only the separately authorized installation and authenticated activation event
can make this proposed body effective. An Issue edit alone activates nothing.
"""
BODY_HASH = hashlib.sha256(BODY.encode("utf-8")).hexdigest()


def _runtime_gate(capability):
    verified = None

    def bind(runtime, supplied):
        nonlocal verified
        if capability is None or supplied is not capability:
            raise ValueError("Hello World requires the manifest verifier")
        if verified is not None and verified != tuple(runtime):
            raise ValueError("Hello World runtime is already bound")
        verified = tuple(runtime)

    def read():
        return verified

    return bind, read


_bind_verified_runtime, _read_runtime = _runtime_gate(
    globals().get("_WEA_VERIFIER_CAPABILITY")
)
del _runtime_gate


def _copy(value, cls):
    if type(value) is not cls:
        raise ValueError("Hello World requires exact native evidence types")
    return cls(**{field.name: getattr(value, field.name) for field in fields(cls)})


def accept_github_batch(state, batch):
    """Pure native evidence confirmation, with no Contract or money effects."""
    if type(state) is not ProtocolState or type(batch) is not GitHubEventBatch:
        raise ValueError("Hello World evidence requires exact native batch types")
    rebuilt = GitHubEventBatch(
        boundary=_copy(batch.boundary, GitHubReadBoundary),
        events=tuple(_copy(event, GitHubEvent) for event in batch.events),
    )
    return apply_batch(state, rebuilt)


def _evidence(state, runtime):
    if type(state) is not ProtocolState:
        raise ValueError("Hello World requires native ProtocolState")
    rebuilt = ProtocolState(
        schema_version=state.schema_version,
        ruleset_hash=state.ruleset_hash,
        tide_interface_version=state.tide_interface_version,
        executor_manifest_hash=state.executor_manifest_hash,
        boundaries=tuple(
            ConfirmedReadBoundary(
                _copy(_copy(b, ConfirmedReadBoundary).boundary, GitHubReadBoundary),
                b.batch_hash,
            )
            for b in state.boundaries
        ),
        read_blockers=tuple(_copy(b, ReadBlocker) for b in state.read_blockers),
        processed_event_keys=state.processed_event_keys,
        events=tuple(_copy(e, GitHubEvent) for e in state.events),
    )
    if (
        rebuilt.ruleset_hash,
        rebuilt.tide_interface_version,
        rebuilt.executor_manifest_hash,
    ) != runtime:
        raise ValueError("Hello World evidence uses the wrong runtime")
    if rebuilt.read_blockers or len(rebuilt.boundaries) != 1:
        raise ValueError("Hello World requires one complete confirmed boundary")
    boundary = rebuilt.boundaries[0]
    if boundary.repository != REPOSITORY or boundary.repository_id != REPOSITORY_ID:
        raise ValueError("Hello World requires the canonical repository")
    return rebuilt


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Hello World command field")
        result[key] = value
    return result


def _command(event):
    if MARKER not in event.body:
        return None
    if not event.body.startswith(MARKER) or event.body.count(MARKER) != 1:
        raise ValueError("Hello World requires one exact command marker")
    data = json.loads(event.body[len(MARKER) :], object_pairs_hook=_unique)
    if type(data) is not dict:
        raise ValueError("Hello World command must be an object")
    return data


def _fields(data, expected):
    if set(data) != set(expected.split()):
        raise ValueError("Hello World command fields do not match")


def _source(event, *, unedited=True):
    payload = thaw_json(event.payload)
    if (
        event.repository_id != REPOSITORY_ID
        or payload.get("issue_id") != ISSUE_ID
        or type(payload.get("issue_number")) is not int
        or payload["issue_number"] != 1
        or payload.get("revision_status") != "confirmed"
        or payload.get("original_author_account_id") != event.actor_account_id
        or not re.fullmatch(r"[1-9][0-9]*", event.actor_account_id)
    ):
        raise ValueError("Hello World requires an owner-authored Issue #1 source")
    if unedited and (
        payload.get("edit_history") != []
        or payload.get("created_at")
        != event.effective_at.isoformat().replace("+00:00", "Z")
        or not event.revision_id.endswith(":created")
    ):
        raise ValueError("Hello World comment must have an unedited snapshot")
    return payload


def _historical():
    raw = resources.files(__package__).joinpath("attestation.json").read_bytes()
    bundle = json.loads(raw)
    if canonical_hash(bundle) != ATTESTATION_HASH:
        raise ValueError("Hello World historical attestation differs")
    records = []
    for row in bundle["mint_uses"]:
        node = row["submission"]["node_id"]
        snapshot = base64.b64decode(
            bundle["issue_snapshot"]["comment_body_utf8_base64"][node]
        ).decode("utf-8")
        records.append(
            {
                "mint_key": f"hello-world:{row['account']['id']}",
                "account_id": str(row["account"]["id"]),
                "source": "v1-attested",
                "disposition": row["disposition"],
                "snapshot": snapshot,
                "comparison_hash": hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
                "normalization_version": NORMALIZATION,
                "attestation_hash": ATTESTATION_HASH,
                "evidence": row,
            }
        )
    return records


def _replay_hello_world(
    *,
    github_state,
    registry,
    opening_registry,
    checkpoint,
    runtime,
    previous=None,
    retain_failures=False,
):
    """Replay the entire explicit source stream; never accept caller contracts."""
    state = _evidence(github_state, runtime)
    if type(registry) is not IdentityRegistry:
        raise ValueError("Hello World requires a canonical native registry")
    registry._assert_unchanged()
    if type(opening_registry) is not IdentityRegistry:
        raise ValueError("Hello World requires the canonical activation registry")
    opening_registry._assert_unchanged()
    for account in opening_registry.accounts:
        if registry.account(account.github_account_id) != account:
            raise ValueError("Hello World permanent base Agent or owner changed")
    _fields(
        checkpoint, "predecessor state_hash installation_sha256 identities_hash cutoff"
    )
    for field in ("state_hash", "installation_sha256", "identities_hash"):
        if type(checkpoint[field]) is not str or not re.fullmatch(
            r"[0-9a-f]{64}", checkpoint[field]
        ):
            raise ValueError("Hello World checkpoint requires exact hashes")
    if not re.fullmatch(r"[0-9a-f]{40}", checkpoint["predecessor"]):
        raise ValueError("Hello World checkpoint requires an immutable predecessor")
    if canonical_hash(opening_registry.to_data()) != checkpoint["identities_hash"]:
        raise ValueError("Hello World admitted identity checkpoint differs")
    at = datetime.fromisoformat(checkpoint["cutoff"].replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("Hello World checkpoint cutoff requires a timezone")
    records = _historical() if previous is None else list(previous["records"])
    retired = {
        row["evidence"]["legacy_agent_id"]
        for row in records
        if row.get("disposition") == "retired_tombstone"
    }
    if any(binding.subject_id in retired for binding in registry.bindings):
        raise ValueError("Hello World cannot resurrect an attested retired binding")
    issues = [
        e for e in state.events if e.object_kind == "issue" and e.object_id == ISSUE_ID
    ]
    if not issues:
        raise ValueError("Hello World canonical Issue #1 snapshot is missing")
    issue = max(issues, key=lambda e: e.canonical_order_key)
    payload = _source(issue, unedited=False)
    if (
        issue.body != BODY
        or issue.content_hash != BODY_HASH
        or payload.get("issue_state") != "open"
    ):
        raise ValueError("Hello World canonical Issue #1 snapshot differs or is closed")
    commands = []
    malformed = {}
    for e in state.events:
        if e.object_kind != "issue_comment":
            continue
        try:
            commands.append((e, _command(e)))
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            if not retain_failures:
                raise
            malformed[e.revision_id] = "unresolved: " + str(exc)

    activations = []
    for candidate, command in commands:
        if not command or command.get("kind") != "hello_world_activation":
            continue
        try:
            _source(candidate)
            if candidate.actor_account_id != OPERATOR_ID:
                raise ValueError(
                    "Hello World activation requires the authenticated operator"
                )
            _fields(
                command,
                "kind checkpoint runtime issue_revision_id body_hash attestation_hash",
            )
            if (
                command["checkpoint"] != checkpoint
                or command["runtime"] != list(runtime)
                or command["issue_revision_id"] != issue.revision_id
                or command["body_hash"] != BODY_HASH
                or command["attestation_hash"] != ATTESTATION_HASH
                or candidate.effective_at <= at
                or candidate.order_key <= issue.order_key
            ):
                raise ValueError(
                    "Hello World activation is stale or does not bind "
                    "the exact snapshot"
                )
        except (ValueError, KeyError, TypeError) as exc:
            malformed[candidate.revision_id] = "unresolved: " + str(exc)
            continue
        activations.append((candidate, command))
    if len(activations) != 1:
        raise ValueError("Hello World requires exactly one authenticated activation")
    activation, _ = activations[0]
    contract_id = "system-hello-world:" + canonical_hash(
        {
            "issue_id": ISSUE_ID,
            "body_hash": BODY_HASH,
            "runtime": list(runtime),
            "activation_revision": activation.revision_id,
        }
    )

    def restore_event(raw):
        return GitHubEvent(
            **{**raw, "effective_at": datetime.fromisoformat(raw["effective_at"])}
        )

    works = (
        {}
        if previous is None
        else {
            wid: (restore_event(row["event"]), row["declaration"])
            for wid, row in previous["works"].items()
        }
    )
    decisions = set() if previous is None else set(previous["decisions"])
    dispositions = {} if previous is None else dict(previous["dispositions"])
    dispositions.update(malformed)
    mints = []
    used = {row["mint_key"] for row in records}
    comparisons = {row["comparison_hash"] for row in records}
    for event, data in commands:
        if event.revision_id in dispositions:
            continue
        if data is None or data.get("kind") == "hello_world_activation":
            continue
        try:
            _source(event)
            if event.order_key <= activation.order_key:
                raise ValueError(
                    "Hello World Work and acceptance must follow activation"
                )
            if data["kind"] == "hello_world_work":
                _fields(data, "kind agent_id greeting")
                greeting = data["greeting"]
                if type(greeting) is not str or not greeting.strip():
                    raise ValueError("Hello World greeting must be nonempty")
                try:
                    greeting.encode("utf-8")
                except UnicodeEncodeError as exc:
                    raise ValueError(
                        "Hello World greeting must be encodable as UTF-8"
                    ) from exc
                authorize_agent(
                    github_account_id=event.actor_account_id,
                    agent_id=data["agent_id"],
                    effective_at=event.effective_at,
                    registry=registry,
                )
                work_id = "work:" + canonical_hash(
                    {"agent_id": data["agent_id"], "contract_id": contract_id}
                )
                if work_id in works:
                    dispositions[event.revision_id] = "duplicate-work"
                    continue
                works[work_id] = (event, data)
                dispositions[event.revision_id] = "awaiting-agent0"
            elif data["kind"] == "hello_world_acceptance":
                _fields(
                    data,
                    "kind work_revision_id work_content_hash agent0_id "
                    "binding_id binding_version mechanically_unique",
                )
                binding = resolve_binding(
                    tuple(b for b in registry.bindings if b.actor_kind == "agent0"),
                    github_account_id=event.actor_account_id,
                    subject_id=data["agent0_id"],
                    effective_at=event.effective_at,
                )
                if (
                    data["agent0_id"] != "agent0@system"
                    or binding.binding_id != data["binding_id"]
                    or type(data["binding_version"]) is not int
                    or binding.version != data["binding_version"]
                    or type(data["mechanically_unique"]) is not bool
                ):
                    raise ValueError(
                        "Hello World acceptance requires the exact active Agent0 role"
                    )
                matches = [
                    (wid, e, d)
                    for wid, (e, d) in works.items()
                    if e.revision_id == data["work_revision_id"]
                ]
                if len(matches) != 1:
                    raise ValueError(
                        "Hello World acceptance requires an admitted exact Work"
                    )
                wid, work, declaration = matches[0]
                current = [
                    e
                    for e in state.events
                    if e.object_kind == work.object_kind
                    and e.object_id == work.object_id
                ]
                if not current:
                    raise ValueError("Hello World Work snapshot is missing")
                latest = max(current, key=lambda e: e.canonical_order_key)
                _source(latest)
                if (
                    latest.revision_id != work.revision_id
                    or latest.content_hash != work.content_hash
                ):
                    raise ValueError("Hello World Work snapshot was edited")
                if (
                    work.content_hash != data["work_content_hash"]
                    or event.order_key <= work.order_key
                ):
                    raise ValueError(
                        "Hello World acceptance does not bind the Work snapshot"
                    )
                if wid in decisions:
                    dispositions[event.revision_id] = "already-decided"
                    continue
                decisions.add(wid)
                key = f"hello-world:{work.actor_account_id}"
                comparison = hashlib.sha256(
                    declaration["greeting"].encode("utf-8")
                ).hexdigest()
                outcome = (
                    "already-used"
                    if key in used
                    else "rejected"
                    if not data["mechanically_unique"]
                    else "duplicate-comparison"
                    if comparison in comparisons
                    else "mint-planned"
                )
                dispositions[event.revision_id] = outcome
                if outcome != "mint-planned":
                    continue
                account = registry.account(work.actor_account_id)
                used.add(key)
                comparisons.add(comparison)
                records.append(
                    {
                        "mint_key": key,
                        "account_id": work.actor_account_id,
                        "base_agent_id": account.base_agent_id,
                        "agent_id": declaration["agent_id"],
                        "source": "vnext",
                        "work_id": wid,
                        "snapshot": work.body,
                        "greeting": declaration["greeting"],
                        "normalization_version": NORMALIZATION,
                        "comparison_hash": comparison,
                        "work_revision_id": work.revision_id,
                        "decision_revision_id": event.revision_id,
                    }
                )
                mints.append(
                    {
                        "agent_id": account.base_agent_id,
                        "amount_wea": 42,
                        "idempotency_key": key,
                    }
                )
            else:
                raise ValueError("unsupported Hello World command")
        except (ValueError, KeyError, TypeError) as exc:
            if previous is None and not retain_failures:
                raise
            dispositions[event.revision_id] = "unresolved: " + str(exc)
    return {
        "schema": "wea-hello-world-state-1",
        "runtime": list(runtime),
        "contract": {
            "contract_id": contract_id,
            "issue_id": ISSUE_ID,
            "body": BODY,
            "body_hash": BODY_HASH,
            "kind": "system_hello_world",
            "status": "active",
            "mechanism": "hello-world",
            "bank_total_wea": 0,
            "review_fee_wea": 0,
        },
        "activation_revision_id": activation.revision_id,
        "records": sorted(records, key=lambda row: row["mint_key"]),
        "mint_intents": mints,
        "works": {
            wid: {
                "event": {
                    **{
                        f.name: thaw_json(getattr(e, f.name))
                        for f in fields(e)
                        if f.name != "effective_at"
                    },
                    "effective_at": e.effective_at.isoformat(),
                },
                "declaration": d,
            }
            for wid, (e, d) in works.items()
        },
        "decisions": sorted(decisions),
        "dispositions": dispositions,
        "task_effects": [],
        "escrow_effects": [],
    }


def _entrypoint(read_runtime, replay):
    def invoke(
        *,
        github_state,
        registry,
        checkpoint,
        opening_registry=None,
        previous=None,
        retain_failures=False,
        _verified_runtime_reference=None,
    ):
        runtime = read_runtime()
        if runtime is None or tuple(_verified_runtime_reference or ()) != runtime:
            raise ValueError("Hello World requires a verifier-owned runtime call")
        return replay(
            github_state=github_state,
            registry=registry,
            opening_registry=registry if opening_registry is None else opening_registry,
            checkpoint=checkpoint,
            runtime=runtime,
            previous=previous,
            retain_failures=retain_failures,
        )

    return invoke


replay_hello_world = _entrypoint(_read_runtime, _replay_hello_world)
del _entrypoint, _read_runtime, _replay_hello_world
