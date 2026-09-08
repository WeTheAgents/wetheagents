"""Derive protocol records while retaining the exact GitHub body separately."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .canonical import canonical_dumps, thaw_json
from .declarations import parse_declaration

MARKER = "<!-- wea:vnext -->"


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("declaration: duplicate JSON field")
        result[key] = value
    return result


def declaration(body: str) -> dict[str, Any] | None:
    """Read one explicit declaration. Prose before the marker has no authority."""
    if MARKER not in body:
        work = parse_declaration(body)
        if work is None:
            return None
        fields = dict(work.fields)
        if fields.get("type") != "deliverable":
            raise ValueError("declaration: unsupported Markdown declaration")
        required = {"agent_id", "type", "source"}
        snapshot_fields = {"model", "genome", "runtime"}
        if set(fields) not in (required, required | snapshot_fields):
            raise ValueError("declaration: Work requires agent_id, type, source")
        result = {
            "kind": "work",
            "agent_id": fields["agent_id"],
            "source": fields["source"],
        }
        if snapshot_fields <= fields.keys():
            result["snapshot"] = {key: fields[key] for key in sorted(snapshot_fields)}
        return result
    if body.count(MARKER) != 1:
        raise ValueError("declaration: exactly one command marker is required")
    data = json.loads(body.split(MARKER, 1)[1], object_pairs_hook=_unique)
    if type(data) is not dict or type(data.get("kind")) is not str:
        raise ValueError("declaration: command requires an object and kind")
    return data


def normalized(source: Any) -> str:
    """Compute source-dependent IDs; never require a future comment ID in text."""
    if source.body.startswith("### WEA common-control disclosure\n"):
        return source.body
    data = declaration(source.body)
    if data is None:
        raise ValueError("declaration: no WEA command")
    kind = data["kind"]
    if kind == "lifecycle":
        if set(data) != {
            "kind",
            "event",
            "actor_kind",
            "actor_id",
            "plan_id",
            "payload",
        }:
            raise ValueError("declaration: lifecycle command fields do not match")
        if data["actor_kind"] == "tide" or data["event"] == "work_revision":
            raise ValueError(
                "authority: a comment cannot manufacture Tide or Work evidence"
            )
        data = {
            "actor_account_id": source.actor_account_id,
            "actor_id": data["actor_id"],
            "actor_kind": data["actor_kind"],
            "effective_at": source.effective_at.isoformat().replace("+00:00", "Z"),
            "event_id": f"{data['plan_id']}:event:{data['event']}:{source.revision_id}",
            "kind": data["event"],
            "payload": data["payload"],
            "plan_id": data["plan_id"],
            "source_id": source.object_id,
            "source_revision_id": source.revision_id,
        }
    elif kind == "author_plan_decision":
        computed = {"decision_id", "idempotency_key", "author_github_account_id"}
        if computed & data.keys():
            raise ValueError("declaration: decision source fields are computed")
        revision = data["plan_revision_id"]
        data.update(
            author_github_account_id=source.actor_account_id,
            decision_id=f"author-plan-decision:{revision}:{source.revision_id}",
            idempotency_key=f"plan-decision:{revision}:{source.revision_id}",
        )
    elif kind == "draft_issue":
        if "issue_number" in data:
            raise ValueError("declaration: Issue number is computed")
        data["issue_number"] = thaw_json(source.payload)["issue_number"]
    elif kind in {
        "resolution_plan_revision",
        "triage_assignment",
        "triage_assessment",
        "triage_completion",
    }:
        # The typed record validates the closed field set and every binding.
        pass
    else:
        raise ValueError("declaration: unsupported source record")
    return canonical_dumps(data).decode("utf-8")


def work_event(
    source: Any,
    state: Any,
    *,
    project_runtime: Any,
    make_lifecycle_event: Any,
    work_id: Any,
    work_revision_id: Any,
) -> Any:
    """Bind Work to retained bytes using the calling closure's exact factories."""
    data = declaration(source.body)
    if data is None or data.get("kind") != "work":
        return None
    if (
        source.repository_id != state.activation.draft.repository_id
        or thaw_json(source.payload).get("issue_id") != state.activation.draft.issue_id
    ):
        return None
    required = {"kind", "agent_id", "source"}
    if set(data) not in (required, required | {"snapshot"}):
        raise ValueError("declaration: Work fields do not match")
    evidence = thaw_json(source.payload)
    artifact = evidence.get("artifact")
    if type(artifact) is not dict or set(artifact) != {"source", "text", "sha256"}:
        raise ValueError("evidence_boundary: immutable Work artifact is missing")
    if artifact["source"] != data["source"] or type(artifact["text"]) is not str:
        raise ValueError("evidence_boundary: artifact belongs to another source")
    digest = hashlib.sha256(artifact["text"].encode("utf-8")).hexdigest()
    if artifact["sha256"] != digest:
        raise ValueError("evidence_boundary: artifact bytes do not match")
    stage = project_runtime(state).current_stage
    snapshot = data.get("snapshot")
    if stage.contract.mode == "frontier" and (
        type(snapshot) is not dict
        or set(snapshot) != {"model", "genome", "runtime"}
        or any(type(value) is not str or not value for value in snapshot.values())
    ):
        raise ValueError("declaration: Frontier requires the declared runtime snapshot")
    if stage.contract.mode != "frontier" and snapshot is not None:
        raise ValueError("declaration: snapshot belongs only to Frontier")
    work = work_id(stage.contract.contract_id, data["agent_id"])
    previous = next((item for item in stage.works if item.work_id == work), None)
    config = thaw_json(stage.contract.config)
    acceptance = config.get("acceptance", {})
    output = (
        artifact["text"] if acceptance.get("kind") == "normalized_validator" else None
    )
    return make_lifecycle_event(
        plan_id=state.activation.plan.plan_id,
        kind="work_revision",
        actor_kind="agent",
        actor_id=data["agent_id"],
        actor_account_id=source.actor_account_id,
        source_id=source.object_id,
        source_revision_id=source.revision_id,
        effective_at=source.effective_at,
        payload={
            "contract_id": stage.contract.contract_id,
            "content_hash": digest,
            "eligible": True,
            "normalized_output": output,
            "revision_id": work_revision_id(
                work, 1 if previous is None else len(previous.revisions) + 1
            ),
            "snapshot": snapshot,
        },
    )
